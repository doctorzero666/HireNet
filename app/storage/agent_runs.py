import json
import uuid
from contextlib import closing
from datetime import datetime, timezone

from app.storage.db import _open, _require_nonneg_int


def insert_agent_run(db_path: str, run: dict) -> str:
    run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    charge_amount = _require_nonneg_int(run["charge_amount"], "charge_amount")
    with closing(_open(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO agent_runs
                    (run_id, agent_name, caller_id, task_id, input_tokens, output_tokens,
                     llm_cost_usd, time_ms, success, asset_ids, royalty_splits,
                     charge_amount, charge_currency, charge_chain, payment_method,
                     settlement_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
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
                ),
            )
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
