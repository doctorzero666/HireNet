import uuid
from contextlib import closing
from datetime import datetime, timezone

from app.storage.db import _open, _require_nonneg_int

_INSERT_ROYALTY_ENTRY_SQL = """
    INSERT INTO royalty_ledger
        (id, run_id, creator_id, asset_id, amount, currency, chain, status, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _build_royalty_entry_row(entry: dict) -> tuple[str, tuple]:
    """Validate + assemble the SQL parameter tuple for a royalty_ledger INSERT.

    Returns (entry_id, params). Pure: opens no connection — so a batch caller
    can reuse it inside its own transaction (see record_agent_run).
    """
    entry_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    amount = _require_nonneg_int(entry["amount"], "amount")
    params = (
        entry_id,
        entry["run_id"],
        entry["creator_id"],
        entry["asset_id"],
        amount,
        entry["currency"],
        entry.get("chain"),
        entry["status"],
        created_at,
    )
    return entry_id, params


def insert_royalty_entry(db_path: str, entry: dict) -> str:
    entry_id, params = _build_royalty_entry_row(entry)
    with closing(_open(db_path)) as conn:
        with conn:
            conn.execute(_INSERT_ROYALTY_ENTRY_SQL, params)
    return entry_id


def list_royalties_by_creator(db_path: str, creator_id: str) -> list[dict]:
    with closing(_open(db_path)) as conn:
        rows = conn.execute(
            "SELECT * FROM royalty_ledger WHERE creator_id = ? ORDER BY created_at DESC",
            (creator_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_all_royalties(db_path: str) -> list[dict]:
    with closing(_open(db_path)) as conn:
        rows = conn.execute(
            "SELECT * FROM royalty_ledger ORDER BY created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]
