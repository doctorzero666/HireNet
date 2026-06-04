import uuid
from contextlib import closing
from datetime import datetime, timezone

from app.storage.db import _open, _require_nonneg_int


def insert_royalty_entry(db_path: str, entry: dict) -> str:
    entry_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    amount = _require_nonneg_int(entry["amount"], "amount")
    with closing(_open(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO royalty_ledger
                    (id, run_id, creator_id, asset_id, amount, currency, chain, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    entry["run_id"],
                    entry["creator_id"],
                    entry["asset_id"],
                    amount,
                    entry["currency"],
                    entry.get("chain"),
                    entry["status"],
                    created_at,
                ),
            )
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
