"""
Stage 1 / D9 — `analysis_traces` DAO: one row per step of a task-analysis run.

Why a table and not a log line: the Stage 1 eval work (WP4) has to answer
"which step produced the JSON that failed validation, and what did it cost"
for 20 golden cases at a time. A grep over `logger.warning` output cannot do
that; `SELECT * FROM analysis_traces WHERE session_id = ? ORDER BY step_no`
can, and `scripts/replay_trace.py` prints exactly that.

Column set is `app/schemas/analysis_trace.json`, field for field — the schema
is the contract, `insert_trace` validates against it before writing, so a
malformed record fails at the call site instead of landing in the table and
breaking replay months later.

Only the v2 pipeline (`HIRENET_TASK_AGENT=v2`) writes here. v1 is untouched.
"""
import json
from contextlib import closing
from datetime import datetime, timezone

from app.services.validation import validate_analysis_trace
from app.storage.db import _open

_INSERT_TRACE_SQL = """
    INSERT INTO analysis_traces
        (trace_id, session_id, step_no, stage, model, prompt_json,
         response_text, parsed_ok, input_tokens, output_tokens, time_ms,
         created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_BY_SESSION_SQL = """
    SELECT trace_id, session_id, step_no, stage, model, prompt_json,
           response_text, parsed_ok, input_tokens, output_tokens, time_ms,
           created_at
    FROM analysis_traces
    WHERE session_id = ?
    ORDER BY step_no ASC, rowid ASC
"""


def build_trace(
    *,
    trace_id: str,
    session_id: str,
    step_no: int,
    stage: str,
    model: str,
    messages: list | None = None,
    prompt_json: str | None = None,
    response_text: str = "",
    parsed_ok: bool = True,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    time_ms: int | None = None,
) -> dict:
    """Assemble a trace record. Pure — no I/O, no validation, no DB.

    `messages` is the convenience form: the caller hands over the messages list
    it actually sent and this serialises it. `prompt_json` takes precedence when
    both are given (a caller that already has the string should not pay for a
    round trip through json).
    """
    if prompt_json is None:
        prompt_json = json.dumps(messages or [], ensure_ascii=False)
    return {
        "trace_id": trace_id,
        "session_id": session_id,
        "step_no": step_no,
        "stage": stage,
        "model": model,
        "prompt_json": prompt_json,
        "response_text": response_text,
        "parsed_ok": bool(parsed_ok),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "time_ms": time_ms,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def insert_trace(db_path: str, record: dict) -> str:
    """Validate one trace against `analysis_trace.json`, then write it.

    Returns the `trace_id`. Raises `jsonschema.ValidationError` before touching
    the DB when the record does not satisfy the schema — a trace row is only
    useful if it is complete, and a half-written one is worse than none.
    """
    validate_analysis_trace(record)
    params = (
        record["trace_id"],
        record["session_id"],
        record["step_no"],
        record["stage"],
        record["model"],
        record["prompt_json"],
        record["response_text"],
        int(record["parsed_ok"]),
        record.get("input_tokens"),
        record.get("output_tokens"),
        record.get("time_ms"),
        record["created_at"],
    )
    with closing(_open(db_path)) as conn:
        with conn:
            conn.execute(_INSERT_TRACE_SQL, params)
    return record["trace_id"]


def list_traces(db_path: str, session_id: str) -> list[dict]:
    """Every trace row for one session, ordered by `step_no` ascending.

    `rowid` is the tiebreak, not `created_at`: two calls inside the same
    millisecond produce identical ISO timestamps, and step_no is assigned by
    the writer per session, so a duplicate step_no (a bug) still replays in
    insertion order rather than at random.
    """
    with closing(_open(db_path)) as conn:
        rows = conn.execute(_SELECT_BY_SESSION_SQL, (session_id,)).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        item["parsed_ok"] = bool(item["parsed_ok"])
        results.append(item)
    return results
