"""
Phase 3 / U3 — audit_log DAO.

Every state transition on agent_runs.settlement_status emits one row here:
claim (accrued|failed → settling), submit (tx_hash recorded while still
settling, async providers), confirm (settling → settled), fail
(settling → failed). The point is a forensic trail: an on-chain tx that
silently dropped, a chain rollback, a stale check_status race, the U3
reconciliation discrepancy — all become "join audit_log on run_id" queries
instead of "guess from request logs".

Insertion is normally invoked inside the same SQLite transaction as the
DAO that flipped the state (see agent_runs.py), so an audit row can never
be missing for a transition that actually committed. The connection-taking
`_insert_audit_event_conn` exists for that use; `insert_audit_event` is
the standalone variant for callers that don't already hold a connection.
"""
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone

from app.storage.db import _open

_VALID_EVENTS = ("claim", "submit", "confirm", "fail")

_INSERT_AUDIT_EVENT_SQL = """
    INSERT INTO audit_log
        (id, run_id, event_ordinal, event, status_from, status_to,
         method, tx_hash, error, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

# SELECT next ordinal for a run. Both insert paths run this inside the same
# transaction as the follow-up INSERT so the MAX(...)+1 read can't be lapped
# by a concurrent writer between the select and the insert.
_NEXT_ORDINAL_SQL = (
    "SELECT COALESCE(MAX(event_ordinal), 0) + 1 AS next_ord "
    "FROM audit_log WHERE run_id = ?"
)


def _build_audit_event_row(
    run_id: str,
    event: str,
    *,
    event_ordinal: int,
    status_from: str | None,
    status_to: str,
    method: str | None = None,
    tx_hash: str | None = None,
    error: str | None = None,
) -> tuple[str, tuple]:
    """Assemble the SQL parameter tuple. Pure — opens no connection.

    Raises ValueError if event is not one of claim/submit/confirm/fail so a
    typo at a call site fails fast at the service boundary instead of the
    DB CHECK rejecting it later with an opaque IntegrityError.
    """
    if event not in _VALID_EVENTS:
        raise ValueError(
            f"event must be one of {_VALID_EVENTS}, got {event!r}"
        )
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id must be a non-empty string")
    if not isinstance(status_to, str) or not status_to:
        raise ValueError("status_to must be a non-empty string")

    entry_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    params = (
        entry_id,
        run_id,
        event_ordinal,
        event,
        status_from,
        status_to,
        method,
        tx_hash,
        error,
        created_at,
    )
    return entry_id, params


def _insert_audit_event_conn(
    conn: sqlite3.Connection,
    run_id: str,
    event: str,
    *,
    status_from: str | None,
    status_to: str,
    method: str | None = None,
    tx_hash: str | None = None,
    error: str | None = None,
) -> str:
    """Insert via an already-open connection so the caller can keep the
    audit row inside the same transaction as the state change it documents.

    No commit here — the caller's enclosing `with conn:` block commits.

    event_ordinal is derived from MAX(event_ordinal)+1 over the run, inside
    the caller's transaction. The caller is the DAO that just held a write
    lock on agent_runs (claim/confirm/fail/submit), so no concurrent writer
    can slip an audit row in between this SELECT and the follow-up INSERT.
    """
    next_ord = conn.execute(_NEXT_ORDINAL_SQL, (run_id,)).fetchone()[0]
    entry_id, params = _build_audit_event_row(
        run_id, event,
        event_ordinal=next_ord,
        status_from=status_from, status_to=status_to,
        method=method, tx_hash=tx_hash, error=error,
    )
    conn.execute(_INSERT_AUDIT_EVENT_SQL, params)
    return entry_id


def insert_audit_event(
    db_path: str,
    run_id: str,
    event: str,
    *,
    status_from: str | None,
    status_to: str,
    method: str | None = None,
    tx_hash: str | None = None,
    error: str | None = None,
) -> str:
    """Standalone insert — for callers that aren't already in a transaction.

    Uses BEGIN IMMEDIATE so the MAX(event_ordinal)+1 lookup and the INSERT
    sit under a RESERVED lock — without it the default DEFERRED transaction
    would let two callers read the same MAX and both write the same ordinal.
    """
    with closing(_open(db_path)) as conn:
        previous_isolation = conn.isolation_level
        conn.isolation_level = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                next_ord = conn.execute(
                    _NEXT_ORDINAL_SQL, (run_id,)
                ).fetchone()[0]
                entry_id, params = _build_audit_event_row(
                    run_id, event,
                    event_ordinal=next_ord,
                    status_from=status_from, status_to=status_to,
                    method=method, tx_hash=tx_hash, error=error,
                )
                conn.execute(_INSERT_AUDIT_EVENT_SQL, params)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.isolation_level = previous_isolation
    return entry_id


def list_audit_events_by_run(db_path: str, run_id: str) -> list[dict]:
    """Return every audit event for one run, ordered oldest → newest.

    Sort key is event_ordinal ASC — a per-run monotonically increasing
    integer the insert path stamps under the same transaction as the row.
    This replaces the previous (created_at, rowid) tiebreak: ISO timestamps
    can collide at microsecond precision when two consecutive events land
    in one DAO transaction, and rowid relies on SQLite's implicit insert
    order which is not part of the contract. event_ordinal is the contract.
    """
    with closing(_open(db_path)) as conn:
        rows = conn.execute(
            "SELECT id, run_id, event_ordinal, event, status_from, status_to, "
            "method, tx_hash, error, created_at "
            "FROM audit_log WHERE run_id = ? "
            "ORDER BY event_ordinal ASC",
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]
