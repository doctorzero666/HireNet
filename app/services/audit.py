"""
Phase 3 / U3 — settlement audit + reconciliation service.

Two responsibilities:

1. ``get_audit_trail(db_path, run_id)`` — wrap list_audit_events_by_run with
   no extra processing. Lives in the service layer (not the route) so a
   future scheduled reconciler or admin tooling can call it without
   importing Flask.

2. ``reconcile(db_path, run_id)`` — recompute the per-run invariant
   ``charge_amount == sum(royalty_ledger.amount)`` and report whether it
   holds. The invariant is established by record_agent_run (creator + tax
   + platform shares sum to charge_amount by construction), so a mismatch
   on a previously-recorded run means either a hand-edited DB row or a
   bug in a later writer — exactly the case U3 wants visible.

The "on-chain" framing matches the spec language ("链上金额 == 账本金额")
even though for the Mock provider no chain is involved: the agent_runs
charge_amount is what the provider was told to transfer, and that is the
'chain side' of the accounting. Real on-chain providers (Anvil /
Sepolia) record the same charge_amount on agent_runs and rely on the
provider's own status check to confirm the chain settled it — the
reconcile here is the ledger-vs-rail invariant, not the rail-vs-chain
one. The latter belongs in a provider-specific reconciler and is out of
U3 scope per the spec.
"""
from contextlib import closing

from app.storage.audit_log import list_audit_events_by_run
from app.storage.db import _open


def get_audit_trail(db_path: str, run_id: str) -> list[dict]:
    """Return the full audit trail for one run, oldest event first."""
    return list_audit_events_by_run(db_path, run_id)


def reconcile(db_path: str, run_id: str) -> dict:
    """Reconcile chain-side billed amount against the royalty ledger.

    Returns:
        {
          "run_id":         <str>,
          "matched":        <bool>,            # see "matched" rules below
          "onchain_amount": <int>,             # agent_runs.charge_amount
          "ledger_amount":  <int>,             # SUM of the matching (currency, chain) bucket
          "currency":       <str | None>,      # run's charge_currency
          "chain":          <str | None>,      # run's charge_chain
          "groups": [                          # per (currency, chain) breakdown
              {"currency": <str>, "chain": <str | None>, "amount": <int>},
              ...
          ],
          "settlement_status": <str | None>,   # current run state
          "tx_hash":        <str | None>,      # rail tx id, if any
        }

    Raises:
        LookupError: run_id is unknown. Routes turn this into a 404.

    Consistency:
        Both reads (agent_runs row + ledger sum) run inside the SAME
        connection under BEGIN EXCLUSIVE so a concurrent claim/confirm/fail
        cannot shift either side between the two queries. Without the
        single-snapshot read, an interleaving writer would produce a
        phantom mismatch that does not exist on either side individually.

        codereviewer P1: BEGIN EXCLUSIVE is the SQLite equivalent of a
        SELECT ... FOR UPDATE — it blocks every other writer AND every
        other connection's reads against this file for the duration of
        the reconcile. BEGIN IMMEDIATE alone would let parallel readers
        keep going, which is fine for correctness on a single connection
        but leaves the reconciliation 'trusting' the database to stay
        coherent across the two SELECTs from outside. EXCLUSIVE makes the
        snapshot guarantee explicit: nothing else is touching either
        table while we compute the invariant.

    matched semantics (cross-(currency, chain) safety):
        The project constitution forbids summing across (currency, chain) —
        a USDC-on-base row and a USDC-on-ethereum row are NOT
        interchangeable, and neither is USD + USDC. So `matched` is True
        only when:
          (a) the ledger has exactly one (currency, chain) bucket, AND
          (b) it equals the run's (charge_currency, charge_chain), AND
          (c) its sum equals charge_amount.
        Any extra bucket (different currency or chain on the same run)
        means a hand-edited row or a migration bug and surfaces matched=False
        with the full per-bucket breakdown in `groups`, so an operator can
        see which bucket is wrong without re-querying the ledger.

    Notes:
        - SUM over an empty ledger returns no rows here (GROUP BY drops the
          all-NULL group). For a run with no ledger rows, groups=[] and
          ledger_amount=0 → matched=False (assuming non-zero charge_amount),
          which is the right signal — a run MUST have ledger rows from
          record_agent_run.
        - matched is computed even when settlement_status != 'settled' so
          a regression in the accrual path (creator+platform+tax !=
          charge_amount) is caught at any lifecycle stage.
    """
    with closing(_open(db_path)) as conn:
        previous_isolation = conn.isolation_level
        conn.isolation_level = None
        try:
            conn.execute("BEGIN EXCLUSIVE")
            try:
                run_row = conn.execute(
                    "SELECT charge_amount, charge_currency, charge_chain, "
                    "settlement_status, tx_hash "
                    "FROM agent_runs WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                if run_row is None:
                    raise LookupError(f"Unknown run_id: {run_id!r}")

                bucket_rows = conn.execute(
                    "SELECT currency, chain, "
                    "       COALESCE(SUM(amount), 0) AS total "
                    "FROM royalty_ledger WHERE run_id = ? "
                    "GROUP BY currency, chain",
                    (run_id,),
                ).fetchall()
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.isolation_level = previous_isolation

    onchain_amount = int(run_row["charge_amount"])
    currency = run_row["charge_currency"]
    chain = run_row["charge_chain"]

    groups = [
        {
            "currency": b["currency"],
            "chain": b["chain"],
            "amount": int(b["total"]),
        }
        for b in bucket_rows
    ]

    expected_bucket = next(
        (g for g in groups if g["currency"] == currency and g["chain"] == chain),
        None,
    )
    expected_amount = expected_bucket["amount"] if expected_bucket else 0

    matched = (
        len(groups) == 1
        and expected_bucket is not None
        and expected_amount == onchain_amount
    )

    return {
        "run_id": run_id,
        "matched": matched,
        "onchain_amount": onchain_amount,
        "ledger_amount": expected_amount,
        "currency": currency,
        "chain": chain,
        "groups": groups,
        "settlement_status": run_row["settlement_status"],
        "tx_hash": run_row["tx_hash"],
    }
