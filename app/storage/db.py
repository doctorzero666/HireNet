import os
import sqlite3
from contextlib import closing

from flask import Flask


def _open(path: str) -> sqlite3.Connection:
    """Open a connection with row_factory set. Internal use only."""
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _require_nonneg_int(value: object, field: str) -> int:
    """Raise if value is not a non-negative plain int (bools and floats rejected)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be a non-negative int (basis points), got {type(value).__name__!r}")
    if value < 0:
        raise ValueError(f"{field} must be >= 0, got {value}")
    return value


def _create_tables(conn: sqlite3.Connection) -> None:
    # CHECK constraints enforce domain rules at the DB layer.
    # If upgrading an existing hirenet.db, delete the file so init_db recreates
    # it with these constraints — SQLite does not support ADD CONSTRAINT.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS skill_assets (
            id             TEXT    PRIMARY KEY,
            creator_id     TEXT    NOT NULL,
            name           TEXT    NOT NULL,
            description    TEXT    NOT NULL,
            type           TEXT    NOT NULL,
            endpoint_url   TEXT,
            io_schema      TEXT    NOT NULL,
            price_amount   INTEGER NOT NULL CHECK (price_amount >= 0),
            price_currency TEXT    NOT NULL,
            price_chain    TEXT,
            split_rule     TEXT    NOT NULL,
            content_hash   TEXT    NOT NULL,
            created_at     TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agent_runs (
            run_id            TEXT    PRIMARY KEY,
            agent_name        TEXT    NOT NULL,
            caller_id         TEXT    NOT NULL,
            task_id           TEXT    NOT NULL,
            input_tokens      INTEGER,
            output_tokens     INTEGER,
            llm_cost_usd      TEXT,
            time_ms           INTEGER,
            success           INTEGER NOT NULL CHECK (success IN (0, 1)),
            asset_ids         TEXT    NOT NULL,
            royalty_splits    TEXT    NOT NULL,
            charge_amount     INTEGER NOT NULL CHECK (charge_amount >= 0),
            charge_currency   TEXT    NOT NULL,
            charge_chain      TEXT,
            payment_method    TEXT    NOT NULL CHECK (payment_method IN ('ledger_only', 'on_chain', 'fiat')),
            settlement_status TEXT    NOT NULL CHECK (settlement_status IN ('accrued', 'settled')),
            created_at        TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS royalty_ledger (
            id         TEXT    PRIMARY KEY,
            run_id     TEXT    NOT NULL,
            creator_id TEXT    NOT NULL,
            asset_id   TEXT    NOT NULL,
            amount     INTEGER NOT NULL CHECK (amount >= 0),
            currency   TEXT    NOT NULL,
            chain      TEXT,
            status     TEXT    NOT NULL CHECK (status IN ('accrued', 'settled')),
            created_at TEXT    NOT NULL
        );
    """)


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns that were introduced after U2, if they are missing from an existing table.

    SQLite does not support ADD COLUMN with NOT NULL unless a DEFAULT is provided, so
    the new columns are added as nullable TEXT here. The service layer guarantees that
    every new write supplies a valid value, preserving the effective constraint.
    Pre-existing rows (U2 data) have their type backfilled to 'skill'.
    """
    rows = conn.execute("PRAGMA table_info(skill_assets)").fetchall()
    existing = {row[1] for row in rows}

    needs_commit = False

    if "type" not in existing:
        conn.execute("ALTER TABLE skill_assets ADD COLUMN type TEXT")
        conn.execute("UPDATE skill_assets SET type = 'skill' WHERE type IS NULL")
        needs_commit = True

    if "endpoint_url" not in existing:
        conn.execute("ALTER TABLE skill_assets ADD COLUMN endpoint_url TEXT")
        needs_commit = True

    if needs_commit:
        conn.commit()


def init_db(app: Flask) -> None:
    db_path = app.config["DATABASE_PATH"]
    parent = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(parent, exist_ok=True)
    with closing(_open(db_path)) as conn:
        _create_tables(conn)
        _migrate(conn)
