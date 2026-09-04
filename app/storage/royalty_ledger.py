import uuid
from contextlib import closing
from datetime import datetime, timezone

from app.storage.db import _open, _require_nonneg_int

_INSERT_ROYALTY_ENTRY_SQL = """
    INSERT INTO royalty_ledger
        (id, run_id, creator_id, payee_id, party, asset_id,
         amount, currency, chain, status,
         settlement_method, tx_hash, note, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_VALID_PARTIES = ("creator", "platform", "tax")

# Mirrors the DB CHECK on royalty_ledger.status. 'settling' arrived with
# Stage 2 / WP-D (x402 pre-settled runs) — see app/storage/db.py.
_VALID_STATUSES = ("accrued", "settling", "settled")


def _build_royalty_entry_row(entry: dict) -> tuple[str, tuple]:
    """Validate + assemble the SQL parameter tuple for a royalty_ledger INSERT.

    Returns (entry_id, params). Pure: opens no connection — so a batch caller
    can reuse it inside its own transaction (see record_agent_run).

    Phase 2 / U2: every entry must carry party + payee_id. party is one of
    'creator' / 'platform' / 'tax'; the DB CHECK enforces this too, but raising
    here gives a cleaner Python error before the SQL layer.

    Stage 2 / WP-D: three optional, nullable fields — settlement_method,
    tx_hash, note. Omitting them (every pre-WP-D caller does) writes NULL,
    which is exactly what the migration backfilled onto historical rows, so
    old and new writers produce identical rows for the non-x402 path.
    """
    entry_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    amount = _require_nonneg_int(entry["amount"], "amount")
    party = entry["party"]
    if party not in _VALID_PARTIES:
        raise ValueError(
            f"party must be one of {_VALID_PARTIES}, got {party!r}"
        )
    status = entry["status"]
    if status not in _VALID_STATUSES:
        raise ValueError(
            f"status must be one of {_VALID_STATUSES}, got {status!r}"
        )
    params = (
        entry_id,
        entry["run_id"],
        entry["creator_id"],
        entry["payee_id"],
        party,
        entry["asset_id"],
        amount,
        entry["currency"],
        entry.get("chain"),
        status,
        entry.get("settlement_method"),
        entry.get("tx_hash"),
        entry.get("note"),
        created_at,
    )
    return entry_id, params


def insert_royalty_entries(db_path: str, entries: list[dict]) -> list[str]:
    """Insert a batch of royalty_ledger rows in a single transaction.

    Returns the list of newly assigned entry ids, one per input entry. Atomic:
    either every row lands or none (so a 3-way split never half-records).
    """
    built = [_build_royalty_entry_row(entry) for entry in entries]
    with closing(_open(db_path)) as conn:
        with conn:
            for _, params in built:
                conn.execute(_INSERT_ROYALTY_ENTRY_SQL, params)
    return [entry_id for entry_id, _ in built]


def list_royalties_by_creator(db_path: str, creator_id: str) -> list[dict]:
    """List the creator-party rows for one creator.

    Phase 2 / U2: ledger holds 3 rows per run (creator / platform / tax). This
    helper means "what does this creator earn", so it filters on party='creator'
    too — pre-migration Phase 1 rows were backfilled to party='creator', so the
    semantics stay identical for old data.
    """
    with closing(_open(db_path)) as conn:
        rows = conn.execute(
            "SELECT * FROM royalty_ledger "
            "WHERE creator_id = ? AND party = 'creator' "
            "ORDER BY created_at DESC",
            (creator_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_royalties_by_payee(db_path: str, payee_id: str) -> list[dict]:
    """List every ledger row payable to one payee, regardless of party.

    For a creator id this returns the same set as list_royalties_by_creator
    (since payee_id == creator_id for party='creator' rows). For the platform
    or tax sentinel ids it returns the platform / tax rows directly.
    """
    with closing(_open(db_path)) as conn:
        rows = conn.execute(
            "SELECT * FROM royalty_ledger WHERE payee_id = ? ORDER BY created_at DESC",
            (payee_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_all_royalties(db_path: str) -> list[dict]:
    with closing(_open(db_path)) as conn:
        rows = conn.execute(
            "SELECT * FROM royalty_ledger ORDER BY created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def list_royalties_by_run(db_path: str, run_id: str) -> list[dict]:
    with closing(_open(db_path)) as conn:
        rows = conn.execute(
            "SELECT * FROM royalty_ledger WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def settle_royalties_by_run(db_path: str, run_id: str) -> int:
    """Flip every accrued ledger row for run_id to settled. Returns row count touched.

    Idempotent: a row already in 'settled' stays settled (the UPDATE filters on
    status='accrued'). Phase 2 / U1 settlement is bookkeeping-only — no on-chain
    transfer happens here. Caller is responsible for run_id authentication.

    Phase 2 / U2: with one row per payee, settle flips all 3 rows together so
    the creator / platform / tax shares move in lockstep.
    """
    with closing(_open(db_path)) as conn:
        with conn:
            cur = conn.execute(
                "UPDATE royalty_ledger SET status = 'settled' "
                "WHERE run_id = ? AND status = 'accrued'",
                (run_id,),
            )
            return cur.rowcount


_SUMMARIZE_CREATOR_EARNINGS_SQL = """
    SELECT currency,
           chain,
           SUM(amount) AS total_amount,
           COUNT(*)    AS call_count
      FROM royalty_ledger
     WHERE creator_id = ?
       AND party = 'creator'
       AND status = 'accrued'
  GROUP BY currency, chain
  ORDER BY currency,
           CASE WHEN chain IS NULL THEN 0 ELSE 1 END,
           chain
"""


def summarize_creator_earnings(db_path: str, creator_id: str) -> dict:
    """Aggregate accrued royalty totals for a single creator.

    Returns:
        {
          "creator_id": str,
          "call_count": int,                # accrued creator rows for this creator
          "totals_by_currency": [           # one row per (currency, chain)
              {"currency": "USD", "chain": None, "amount": 350},
              ...
          ],
        }

    Notes:
        - Filters party='creator' so the platform / tax shares of the same run
          do not get counted as creator income (Phase 2 / U2: ledger now holds
          all three parties).
        - Filters status='accrued' explicitly so 'settled' rows do not silently
          leak into the "accrued earnings" total.
        - Groups by (currency, chain) because the schema treats them as a
          triple — (USDC, ethereum) and (USDC, base) are distinct ledgers.
        - call_count is the sum of per-group COUNT(*), which equals the number
          of creator-party ledger rows for this creator (one per run).
    """
    with closing(_open(db_path)) as conn:
        rows = conn.execute(
            _SUMMARIZE_CREATOR_EARNINGS_SQL, (creator_id,)
        ).fetchall()

    totals_by_currency: list[dict] = []
    call_count = 0
    for row in rows:
        totals_by_currency.append({
            "currency": row["currency"],
            "chain": row["chain"],
            "amount": int(row["total_amount"]),
        })
        call_count += int(row["call_count"])

    return {
        "creator_id": creator_id,
        "call_count": call_count,
        "totals_by_currency": totals_by_currency,
    }


_LIST_CREATOR_LEDGER_SQL = """
    SELECT
        rl.run_id      AS run_id,
        rl.amount      AS amount,
        rl.currency    AS currency,
        rl.chain       AS chain,
        rl.status      AS status,
        rl.created_at  AS created_at,
        ar.agent_name  AS agent_name,
        ar.caller_id   AS caller_id,
        ar.tx_hash     AS tx_hash,
        u.name         AS caller_name
      FROM royalty_ledger rl
      LEFT JOIN agent_runs ar ON ar.run_id    = rl.run_id
      LEFT JOIN users      u  ON u.id         = ar.caller_id
     WHERE rl.creator_id = ?
       AND rl.party      = 'creator'
  ORDER BY rl.created_at DESC
"""


def list_creator_ledger(db_path: str, creator_id: str) -> list[dict]:
    """Per-run ledger view for the creator's earnings page.

    One row per agent_run paid to this creator. Joins agent_runs for the
    caller-facing labels (agent_name, tx_hash) and users for the caller's
    display name. LEFT JOIN so a ledger row with a missing run / caller still
    surfaces — the UI gets a None name instead of dropping the entry.
    """
    with closing(_open(db_path)) as conn:
        rows = conn.execute(
            _LIST_CREATOR_LEDGER_SQL, (creator_id,)
        ).fetchall()
    return [
        {
            "run_id": row["run_id"],
            "agent_name": row["agent_name"],
            "caller_id": row["caller_id"],
            "caller_name": row["caller_name"],
            "amount": int(row["amount"]),
            "currency": row["currency"],
            "chain": row["chain"],
            "status": row["status"],
            "tx_hash": row["tx_hash"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
