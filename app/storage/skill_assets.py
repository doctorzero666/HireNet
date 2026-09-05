import json
import uuid
from contextlib import closing
from datetime import datetime, timezone

from app.storage.db import _open, _require_nonneg_int


def insert_skill_asset(db_path: str, asset: dict) -> str:
    skill_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    price_amount = _require_nonneg_int(asset["price_amount"], "price_amount")
    with closing(_open(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO skill_assets
                    (id, creator_id, name, description, type, endpoint_url,
                     io_schema, price_amount, price_currency, price_chain,
                     split_rule, content_hash, wallet_address, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    skill_id,
                    asset["creator_id"],
                    asset["name"],
                    asset["description"],
                    asset["type"],
                    asset.get("endpoint_url"),
                    json.dumps(asset["io_schema"]),
                    price_amount,
                    asset["price_currency"],
                    asset.get("price_chain"),
                    json.dumps(asset["split_rule"]),
                    asset["content_hash"],
                    asset.get("wallet_address"),
                    created_at,
                ),
            )
    return skill_id


def get_skill_asset(db_path: str, skill_id: str) -> dict | None:
    with closing(_open(db_path)) as conn:
        row = conn.execute(
            "SELECT * FROM skill_assets WHERE id = ?", (skill_id,)
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["io_schema"] = json.loads(result["io_schema"])
    result["split_rule"] = json.loads(result["split_rule"])
    return result


def list_skill_assets(db_path: str, creator_id: str | None = None) -> list[dict]:
    with closing(_open(db_path)) as conn:
        if creator_id is None:
            rows = conn.execute(
                "SELECT * FROM skill_assets ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM skill_assets WHERE creator_id = ? ORDER BY created_at DESC",
                (creator_id,),
            ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        item["io_schema"] = json.loads(item["io_schema"])
        item["split_rule"] = json.loads(item["split_rule"])
        results.append(item)
    return results


def backfill_display_en(
    db_path: str,
    skill_id: str,
    name_en: str | None,
    description_en: str | None,
) -> int:
    """Write the English display text onto one asset row. Returns rows changed.

    WP-I18N-2 / D-C. Deliberately separate from `insert_skill_asset`:

    * `name_en` / `description_en` are NOT part of `compute_content_hash`
      (adding them would change the content_hash of every existing asset — a
      provenance break, CLAUDE.md TIER 1 §2), and NOT part of the bootstraps'
      `expected` idempotency match (adding them there would stop every
      already-deployed row from matching and fork it into a duplicate on the
      next boot).
    * `WHERE name_en IS NULL` makes this idempotent across restarts and stops
      a redeploy from overwriting text someone edited on purpose.

    Nothing else about the row is touched — not the hash, not the price, not
    the split rule.
    """
    with closing(_open(db_path)) as conn:
        with conn:
            cursor = conn.execute(
                "UPDATE skill_assets SET name_en = ?, description_en = ? "
                "WHERE id = ? AND name_en IS NULL",
                (name_en, description_en, skill_id),
            )
    return cursor.rowcount
