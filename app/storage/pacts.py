"""Stage 2 / WP-G: the authorization mandate ("pact") store, in SQLite.

Replaces the process-local `pact_sessions` dict in `app/app.py`. Two things
that dict could not do and this module must:

  * survive a restart / a second worker — a pact created on one process is
    approved and settled by another;
  * make "approved → settled" (and the x402 rail's "approved → settling")
    an atomic claim without a process-local lock. `transition_pact` is a
    single conditional UPDATE; its rowcount IS the exactly-once guarantee,
    exactly as `agent_runs.claim_settlement` does for a settlement run. Two
    concurrent settles cannot both bill the creator: only one UPDATE matches.

Row → dict shape (the routes return these dicts verbatim, so the shape is a
public API contract):

  * `_BASE_COLUMNS` are the keys every pact carries from creation onward.
    They are always present, NULL included (`approved_at` is `None` on a
    pending pact and the route has always shown it).
  * `_OPTIONAL_COLUMNS` are written later in the lifecycle. SQL NULL means
    "this pact never carried the key", so the conversion OMITS it — a pending
    pact has no `run_id` key at all, and a legacy settle's body has no
    `tx_hash` / `explorer_url` / `settled_amount`, which is what the pact
    tests assert.
  * The two JSON columns therefore distinguish "never written" (SQL NULL) from
    "written as null": `mcp_result` is stored as the JSON text `'null'` when a
    settle ran against an asset with no endpoint_url, so the key comes back
    present with the value `None` — again what the route did in memory.

`content_hash` is stored here but computed in app/app.py (`PACT_HASHED_FIELDS`
/ `_pact_content_hash`). Read it as bounding the CEILING, not the charge: the
digest covers the mandate's identity, `amount_cap`, `currency`, `payee` and
`expires_at`, and deliberately NOT `amount`, which is a settle-time quantity.
A row whose `amount` was edited still passes the integrity check — and is
still refused by `pact_settle`'s `amount > amount_cap` guard, because the cap
it is measured against IS hashed. Anything reading this column must not
conclude that every stored field is sealed. See the long comment beside
`PACT_HASHED_FIELDS` for the full reasoning.

Known narrowing vs the dict it replaces: `creator_id` is a TEXT column, so a
client that posts a non-string `creator_id` (the create route does not
validate that field) no longer gets its exact JSON type echoed back. Every
caller in the app and the test suite sends a string or omits the field.
"""
import json
import sqlite3
from contextlib import closing

from app.storage.db import _open

# The pact state machine. Mirrors the CHECK constraint in db.py::_create_tables
# — the DB is the authority, this tuple exists so callers can name the states
# without re-typing the strings.
PACT_STATUSES = ("pending", "approved", "rejected", "settling", "settled")

# Always present in the returned dict, in the order pact_create builds them.
_BASE_COLUMNS = (
    "pact_id",
    "status",
    "task_id",
    "agent_name",
    "creator_id",
    "asset_id",
    "amount",
    "currency",
    "created_at",
    "approved_at",
    "intent",
    "amount_cap",
    "expires_at",
    "payee",
    "approved_by",
    "approval_method",
    "content_hash",
)

# Present only once written; SQL NULL ⇒ the key is absent from the dict.
_OPTIONAL_COLUMNS = (
    "run_id",
    "royalty_splits",
    "tx_hash",
    "explorer_url",
    "settled_amount",
    "mcp_result",
    # Stage 2 / WP-R (review F2): the reconciliation record for a settle that
    # signed an authorization and never learned its fate. Optional like the
    # rest — a pact that settled cleanly has neither key.
    "last_error",
    "payment_pending",
)

# Stored as JSON text. `json.dumps(None)` is `'null'`, which is how a key
# explicitly set to None stays distinguishable from a never-written column.
_JSON_COLUMNS = frozenset({"royalty_splits", "mcp_result", "payment_pending"})

_ALL_COLUMNS = _BASE_COLUMNS + _OPTIONAL_COLUMNS

# Required at insert time. Everything else is nullable or optional.
_REQUIRED_COLUMNS = ("pact_id", "status", "task_id", "agent_name", "currency",
                     "created_at")


def _require_known_column(column: str) -> str:
    """Whitelist guard for every column name spliced into SQL below.

    The UPDATE statements are assembled from caller-supplied keyword names, so
    this is the only thing standing between a typo'd (or hostile) field name
    and the SQL string. Values always travel as bound parameters.
    """
    if column not in _ALL_COLUMNS:
        raise ValueError(
            f"unknown pact column {column!r}; known columns: "
            f"{', '.join(_ALL_COLUMNS)}"
        )
    return column


def _encode(column: str, value):
    """Python value → the value bound into the SQL statement."""
    if column in _JSON_COLUMNS:
        return json.dumps(value)
    return value


def _row_to_pact(row: sqlite3.Row) -> dict:
    """sqlite3.Row → the dict shape the pact routes return."""
    pact = {column: row[column] for column in _BASE_COLUMNS}
    for column in _OPTIONAL_COLUMNS:
        raw = row[column]
        if raw is None:
            continue
        pact[column] = json.loads(raw) if column in _JSON_COLUMNS else raw
    return pact


def create_pact(db_path: str, pact: dict) -> dict:
    """Insert a new pact and return it as read back from the row.

    Deliberately returns the round-tripped row rather than the caller's dict:
    the create route's response is then, byte for byte, what a later
    `GET /api/pact/status/<id>` returns, and any storage round-trip that
    changed a value shows up immediately instead of at settle time (where
    `content_hash` would fail).
    """
    for column in _REQUIRED_COLUMNS:
        if pact.get(column) is None:
            raise ValueError(f"pact.{column} is required")

    columns = [column for column in _ALL_COLUMNS if column in pact]
    unknown = set(pact) - set(_ALL_COLUMNS)
    if unknown:
        raise ValueError(
            f"unknown pact field(s): {', '.join(sorted(unknown))}"
        )
    params = [_encode(column, pact[column]) for column in columns]
    sql = (
        f"INSERT INTO pacts ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' * len(columns))})"
    )
    with closing(_open(db_path)) as conn:
        with conn:
            conn.execute(sql, params)
    return get_pact(db_path, pact["pact_id"])


def get_pact(db_path: str, pact_id: str) -> dict | None:
    with closing(_open(db_path)) as conn:
        row = conn.execute(
            "SELECT * FROM pacts WHERE pact_id = ?", (pact_id,)
        ).fetchone()
    if row is None:
        return None
    return _row_to_pact(row)


def transition_pact(db_path: str, pact_id: str, from_status: str,
                    to_status: str, **fields) -> bool:
    """Atomically move a pact from `from_status` to `to_status`.

    Returns True iff exactly one row moved — i.e. this caller "owns" the
    transition. False means the pact does not exist or is no longer in
    `from_status`, and the caller MUST NOT proceed as if it had claimed it.
    This single conditional UPDATE is what replaced `_pact_lock`: two threads
    racing to settle the same approved pact both run this statement, SQLite
    serialises them, and only the first one sees rowcount 1.

    `fields` are written in the SAME statement as the status flip, so a
    successful claim can never leave the row half-updated (a `settled` pact
    with no run_id). Passing `status` here is refused — the status is what
    the transition itself is for.
    """
    assignments = ["status = ?"]
    params: list = [to_status]
    for column, value in fields.items():
        if column == "status":
            raise ValueError(
                "pass the new status as to_status, not as a field"
            )
        _require_known_column(column)
        assignments.append(f"{column} = ?")
        params.append(_encode(column, value))
    params.extend([pact_id, from_status])
    sql = (
        f"UPDATE pacts SET {', '.join(assignments)} "
        "WHERE pact_id = ? AND status = ?"
    )
    with closing(_open(db_path)) as conn:
        with conn:
            cursor = conn.execute(sql, params)
            return cursor.rowcount == 1


def update_pact_fields(db_path: str, pact_id: str, **fields) -> bool:
    """Write non-status fields on a pact. Returns True iff the row exists.

    For writes that happen AFTER the caller has already claimed the pact with
    `transition_pact` (the tx hash of a payment that went through but could
    not be recorded, the MCP result of a completed settle). It cannot change
    `status`: every status change goes through `transition_pact` so it is
    always conditional on the state it is leaving.
    """
    if not fields:
        raise ValueError("update_pact_fields needs at least one field")
    assignments = []
    params: list = []
    for column, value in fields.items():
        if column in ("status", "pact_id"):
            raise ValueError(f"{column} cannot be updated this way")
        _require_known_column(column)
        assignments.append(f"{column} = ?")
        params.append(_encode(column, value))
    params.append(pact_id)
    sql = f"UPDATE pacts SET {', '.join(assignments)} WHERE pact_id = ?"
    with closing(_open(db_path)) as conn:
        with conn:
            cursor = conn.execute(sql, params)
            return cursor.rowcount == 1


def list_pacts(db_path: str, status: str | None = None) -> list[dict]:
    """Every pact, newest first; optionally filtered to one status."""
    with closing(_open(db_path)) as conn:
        if status is None:
            rows = conn.execute(
                "SELECT * FROM pacts ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM pacts WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
    return [_row_to_pact(row) for row in rows]
