import json
import uuid
from contextlib import closing
from datetime import datetime, timezone

from app.storage.audit_log import _insert_audit_event_conn
from app.storage.db import _open, _require_nonneg_int

_INSERT_AGENT_RUN_SQL = """
    INSERT INTO agent_runs
        (run_id, agent_name, caller_id, task_id, input_tokens, output_tokens,
         llm_cost_usd, time_ms, success, asset_ids, royalty_splits,
         charge_amount, charge_currency, charge_chain, payment_method,
         settlement_status, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _build_agent_run_row(run: dict) -> tuple[str, tuple]:
    """Validate + assemble the SQL parameter tuple for an agent_runs INSERT.

    Returns (run_id, params). Pure: opens no connection, performs no I/O — so a
    batch caller can reuse it inside its own transaction (see record_agent_run).
    """
    run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    charge_amount = _require_nonneg_int(run["charge_amount"], "charge_amount")
    params = (
        run_id,
        run["agent_name"],
        run["caller_id"],
        run["task_id"],
        run.get("input_tokens"),
        run.get("output_tokens"),
        run.get("llm_cost_usd"),
        run.get("time_ms"),
        int(run["success"]),
        json.dumps(run["asset_ids"]),
        json.dumps(run["royalty_splits"]),
        charge_amount,
        run["charge_currency"],
        run.get("charge_chain"),
        run["payment_method"],
        run["settlement_status"],
        created_at,
    )
    return run_id, params


def insert_agent_run(db_path: str, run: dict) -> str:
    run_id, params = _build_agent_run_row(run)
    with closing(_open(db_path)) as conn:
        with conn:
            conn.execute(_INSERT_AGENT_RUN_SQL, params)
    return run_id


def get_agent_run(db_path: str, run_id: str) -> dict | None:
    with closing(_open(db_path)) as conn:
        row = conn.execute(
            "SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["asset_ids"] = json.loads(result["asset_ids"])
    result["royalty_splits"] = json.loads(result["royalty_splits"])
    result["success"] = bool(result["success"])
    return result


def list_agent_runs_by_caller(db_path: str, caller_id: str) -> list[dict]:
    with closing(_open(db_path)) as conn:
        rows = conn.execute(
            "SELECT * FROM agent_runs WHERE caller_id = ? ORDER BY created_at DESC",
            (caller_id,),
        ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        item["asset_ids"] = json.loads(item["asset_ids"])
        item["royalty_splits"] = json.loads(item["royalty_splits"])
        item["success"] = bool(item["success"])
        results.append(item)
    return results


def count_runs_by_asset(db_path: str) -> dict[str, int]:
    """Per-asset run count across every caller — drives the Agent World cards.

    asset_ids is stored as a JSON array (a single run can span multiple
    assets), so the count is computed in Python by iterating decoded arrays
    rather than relying on the optional sqlite JSON1 extension.
    """
    with closing(_open(db_path)) as conn:
        rows = conn.execute("SELECT asset_ids FROM agent_runs").fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        try:
            ids = json.loads(row["asset_ids"])
        except (TypeError, ValueError):
            continue
        for asset_id in ids:
            counts[asset_id] = counts.get(asset_id, 0) + 1
    return counts


# ─── Phase 3 / U1: settlement state machine ──────────────────────────────────
#
# Three DAO helpers wrap the `accrued/failed → settling → settled` lifecycle.
# Each uses a single conditional UPDATE so two threads racing on the same
# run_id can never both move the run forward — the second one sees rowcount=0
# and the caller turns that into a 409 Conflict. The route layer (app.py)
# composes these into the /api/royalty/settle flow.
#
# Why this lives here (DAO), not in a service:
#   - the locking guarantee IS the UPDATE … WHERE status='…' rowcount;
#   - confirm_settlement also flips royalty_ledger rows in the same SQLite
#     transaction so the agent_runs status and the ledger rows can never get
#     out of sync (creator + platform + tax all paid or none).


def claim_settlement(db_path: str, run_id: str) -> bool:
    """Atomically flip status from accrued/failed → settling.

    Returns True iff this caller "owns" the in-flight settlement (rowcount=1).
    False means: run does not exist, or status is already settling/settled —
    in either case the caller MUST NOT call provider.settle() to avoid a
    double-bill.

    failed is a retriable source state so a previously errored run can be
    re-attempted without manual intervention; settled is terminal and the
    caller should short-circuit to a no-op return.

    U3: emits a 'claim' audit event inside the same transaction as the state
    flip — so a successful claim never leaves the audit trail short by one
    row even on a crash mid-call. The from-state is derived from WHICH of
    two conditional UPDATEs matched (accrued first, then failed), rather
    than a pre-flip SELECT — the previous SELECT-then-UPDATE had a TOCTOU
    window where a concurrent writer could change the status between read
    and write, leaving the audit row labelled with a stale status_from.
    The first conditional UPDATE takes a RESERVED lock even when rowcount=0,
    so no other writer can slip in between the two UPDATEs; the rowcount=1
    branch is therefore an atomic statement about the prior state.
    """
    with closing(_open(db_path)) as conn:
        with conn:
            cur = conn.execute(
                "UPDATE agent_runs SET settlement_status = 'settling' "
                "WHERE run_id = ? AND settlement_status = 'accrued'",
                (run_id,),
            )
            if cur.rowcount == 1:
                prev_status = "accrued"
            else:
                cur = conn.execute(
                    "UPDATE agent_runs SET settlement_status = 'settling' "
                    "WHERE run_id = ? AND settlement_status = 'failed'",
                    (run_id,),
                )
                if cur.rowcount != 1:
                    return False
                prev_status = "failed"
            _insert_audit_event_conn(
                conn, run_id, "claim",
                status_from=prev_status,
                status_to="settling",
            )
            return True


def confirm_settlement(
    db_path: str,
    run_id: str,
    tx_hash: str,
    method: str,
) -> int:
    """Flip settling → settled on agent_runs AND ledger rows in one transaction.

    Both writes share the same SQLite transaction: if the ledger UPDATE fails,
    the agent_runs change rolls back too, so we never end up with a 'settled'
    run whose creator/platform/tax rows are still 'accrued'.

    The agent_runs UPDATE is conditional on settlement_status='settling' so a
    stray confirm on an already-settled run is a no-op (returns 0) instead of
    overwriting an existing tx_hash.

    Args:
        tx_hash: provider's transaction identifier (e.g. "mock-abc123" for the
            Mock provider, an on-chain tx hash for a chain provider).
            Persisted on agent_runs.tx_hash.
        method: provider name ("mock", "sepolia", …). Persisted on
            agent_runs.settlement_method so the audit trail records which
            rail completed each settlement.

    Returns:
        rowcount of ledger rows flipped (3 for a typical creator/platform/tax
        split). 0 means the run was not in 'settling' — caller should treat
        as a stale confirm and not assume settlement succeeded.
    """
    with closing(_open(db_path)) as conn:
        with conn:
            run_cur = conn.execute(
                "UPDATE agent_runs "
                "SET settlement_status = 'settled', tx_hash = ?, settlement_method = ? "
                "WHERE run_id = ? AND settlement_status = 'settling'",
                (tx_hash, method, run_id),
            )
            if run_cur.rowcount == 0:
                return 0
            ledger_cur = conn.execute(
                "UPDATE royalty_ledger SET status = 'settled' "
                "WHERE run_id = ? AND status = 'accrued'",
                (run_id,),
            )
            # Phase 1 wrote exactly 1 ledger row (creator only); Phase 2 / U2
            # rebuilt this to 3 rows (creator + platform + tax) for new runs,
            # but pre-U2 rows migrated via _migrate keep their single-row
            # shape. So the rowcount we see here is whatever was 'accrued'
            # for this run — 1 for legacy, 3 for modern, or 0 if the ledger
            # was advanced out-of-band before this confirm fired. The atomic
            # conditional UPDATE itself is the integrity guarantee: every
            # row that WAS 'accrued' is now 'settled', under the same
            # transaction as the agent_runs flip, so the two can never
            # disagree. We no longer reject (1 or 2) as "partial corruption"
            # because that check was incompatible with the U2 migration and
            # the loss of a CHECK constraint at this layer is acceptable —
            # reconcile() in app/services/audit.py is the authoritative
            # creator+platform+tax == charge_amount audit.
            # U3 audit: status_from is 'settling' because the UPDATE WHERE
            # clause guarantees that — we only reach here when the conditional
            # flip actually consumed a 'settling' row.
            _insert_audit_event_conn(
                conn, run_id, "confirm",
                status_from="settling",
                status_to="settled",
                method=method,
                tx_hash=tx_hash,
            )
            return ledger_cur.rowcount


def record_settlement_submission(
    db_path: str,
    run_id: str,
    tx_hash: str,
    method: str,
) -> bool:
    """Persist tx_hash + settlement_method while keeping status='settling'.

    Used for asynchronous on-chain providers where settle() success only means
    "submitted to the rail", not "on-chain confirmed". The row needs a
    tx_hash for a later check_status() poll to find it, but we MUST NOT flip
    to 'settled' yet — that would short-circuit the polling loop and tell
    the rest of the system the creator was paid before the chain confirmed.

    Conditional on settlement_status='settling' so a stale write on an
    already-settled or failed run is a no-op (returns False) rather than
    overwriting the terminal tx_hash with a half-baked one.

    Returns True iff exactly one row was updated.
    """
    with closing(_open(db_path)) as conn:
        with conn:
            cur = conn.execute(
                "UPDATE agent_runs SET tx_hash = ?, settlement_method = ? "
                "WHERE run_id = ? AND settlement_status = 'settling'",
                (tx_hash, method, run_id),
            )
            if cur.rowcount != 1:
                return False
            # U3 audit: status stays 'settling' (this is the async "submitted
            # to rail, awaiting confirmation" event), so status_from ==
            # status_to. The tx_hash + method are what's worth preserving —
            # they're the join key for a later check_status poll.
            _insert_audit_event_conn(
                conn, run_id, "submit",
                status_from="settling",
                status_to="settling",
                method=method,
                tx_hash=tx_hash,
            )
            return True


def fail_settlement(db_path: str, run_id: str, error_msg: str | None = None) -> bool:
    """Flip settling → failed. ledger rows untouched (stay accrued).

    Returns True iff a row was actually flipped (rowcount=1). False means
    the run was not in 'settling' — a race we should treat as "someone else
    already moved this run on", not retry.

    U3: error_msg is now persisted on the audit_log row so the operator
    can see why each retriable failure happened without grepping app
    logs. The agent_runs row itself still has no error column — failure
    reason lives with the audit event, not the run, so retries don't
    pile up successive error strings on a single row.
    """
    with closing(_open(db_path)) as conn:
        with conn:
            cur = conn.execute(
                "UPDATE agent_runs SET settlement_status = 'failed' "
                "WHERE run_id = ? AND settlement_status = 'settling'",
                (run_id,),
            )
            if cur.rowcount != 1:
                return False
            _insert_audit_event_conn(
                conn, run_id, "fail",
                status_from="settling",
                status_to="failed",
                error=error_msg,
            )
            return True
