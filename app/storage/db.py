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
            settlement_status TEXT    NOT NULL CHECK (settlement_status IN ('accrued', 'settling', 'settled', 'failed')),
            settlement_method TEXT    NOT NULL DEFAULT 'ledger_only',
            tx_hash           TEXT,
            created_at        TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS royalty_ledger (
            id         TEXT    PRIMARY KEY,
            run_id     TEXT    NOT NULL,
            creator_id TEXT    NOT NULL,
            payee_id   TEXT    NOT NULL,
            party      TEXT    NOT NULL CHECK (party IN ('creator', 'platform', 'tax')),
            asset_id   TEXT    NOT NULL,
            amount     INTEGER NOT NULL CHECK (amount >= 0),
            currency   TEXT    NOT NULL,
            chain      TEXT,
            status     TEXT    NOT NULL CHECK (status IN ('accrued', 'settled')),
            created_at TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id            TEXT    PRIMARY KEY,
            name          TEXT    NOT NULL,
            role          TEXT    NOT NULL CHECK (role IN ('enterprise', 'creator', 'jobseeker')),
            password_hash TEXT    NOT NULL,
            created_at    TEXT    NOT NULL
        );
    """)


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns that were introduced after U2, if they are missing from an existing table.

    SQLite does not support ADD COLUMN with NOT NULL unless a DEFAULT is provided, so
    the new columns are added as nullable TEXT here. The service layer guarantees that
    every new write supplies a valid value, preserving the effective constraint.
    Pre-existing rows (U2 data) have their type backfilled to 'skill'.

    Phase 2 / U2: royalty_ledger gains payee_id + party so each split party gets its
    own row. Pre-existing rows are backfilled to ('creator', creator_id) — they were
    the single creator row written in Phase 1.

    Phase 3 / U1: agent_runs.settlement_status expands from ('accrued','settled')
    to ('accrued','settling','settled','failed') so a multi-step provider call
    can be tracked. SQLite cannot ALTER a CHECK constraint, so we rebuild the
    table (CREATE new → INSERT SELECT → DROP old → RENAME). We also add
    settlement_method (DEFAULT 'ledger_only') and tx_hash (nullable) columns
    in the same rebuild so existing rows naturally land on safe defaults.

    Crash-safety: every ALTER + backfill UPDATE runs inside a single explicit
    transaction. Python's sqlite3 module auto-commits before DDL by default,
    which would otherwise leave the DB in a half-migrated state if a later
    step crashed. We flip isolation_level to None so BEGIN / COMMIT / ROLLBACK
    apply to the whole batch — any failure rolls back to the pre-migration
    schema instead of stranding the DB between versions.
    """
    skill_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(skill_assets)").fetchall()
    }
    ledger_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(royalty_ledger)").fetchall()
    }
    agent_run_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(agent_runs)").fetchall()
    }

    pending = (
        "type" not in skill_cols
        or "endpoint_url" not in skill_cols
        or "payee_id" not in ledger_cols
        or "party" not in ledger_cols
        or "settlement_method" not in agent_run_cols
        or "tx_hash" not in agent_run_cols
    )
    if not pending:
        return

    previous_isolation = conn.isolation_level
    conn.isolation_level = None
    try:
        conn.execute("BEGIN")
        try:
            if "type" not in skill_cols:
                conn.execute("ALTER TABLE skill_assets ADD COLUMN type TEXT")
                conn.execute(
                    "UPDATE skill_assets SET type = 'skill' WHERE type IS NULL"
                )

            if "endpoint_url" not in skill_cols:
                conn.execute(
                    "ALTER TABLE skill_assets ADD COLUMN endpoint_url TEXT"
                )

            if "payee_id" not in ledger_cols:
                conn.execute(
                    "ALTER TABLE royalty_ledger ADD COLUMN payee_id TEXT"
                )
                conn.execute(
                    "UPDATE royalty_ledger SET payee_id = creator_id "
                    "WHERE payee_id IS NULL"
                )

            if "party" not in ledger_cols:
                conn.execute(
                    "ALTER TABLE royalty_ledger ADD COLUMN party TEXT"
                )
                conn.execute(
                    "UPDATE royalty_ledger SET party = 'creator' "
                    "WHERE party IS NULL"
                )

            if (
                "settlement_method" not in agent_run_cols
                or "tx_hash" not in agent_run_cols
            ):
                # Rebuild agent_runs to widen the settlement_status CHECK and
                # add the two new columns. The new table mirrors _create_tables;
                # SELECT … carries pre-existing rows over with NULL tx_hash and
                # 'ledger_only' as settlement_method (matches the column DEFAULT,
                # spelled explicitly so the INSERT doesn't rely on DDL defaults
                # applying to SELECT projections).
                conn.execute("""
                    CREATE TABLE agent_runs_new (
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
                        settlement_status TEXT    NOT NULL CHECK (settlement_status IN ('accrued', 'settling', 'settled', 'failed')),
                        settlement_method TEXT    NOT NULL DEFAULT 'ledger_only',
                        tx_hash           TEXT,
                        created_at        TEXT    NOT NULL
                    )
                """)
                conn.execute("""
                    INSERT INTO agent_runs_new (
                        run_id, agent_name, caller_id, task_id,
                        input_tokens, output_tokens, llm_cost_usd, time_ms,
                        success, asset_ids, royalty_splits,
                        charge_amount, charge_currency, charge_chain,
                        payment_method, settlement_status,
                        settlement_method, tx_hash, created_at
                    )
                    SELECT
                        run_id, agent_name, caller_id, task_id,
                        input_tokens, output_tokens, llm_cost_usd, time_ms,
                        success, asset_ids, royalty_splits,
                        charge_amount, charge_currency, charge_chain,
                        payment_method, settlement_status,
                        'ledger_only', NULL, created_at
                    FROM agent_runs
                """)
                conn.execute("DROP TABLE agent_runs")
                conn.execute("ALTER TABLE agent_runs_new RENAME TO agent_runs")

            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.isolation_level = previous_isolation


def _seed_demo_users(conn: sqlite3.Connection) -> None:
    """Seed the 4 Demo users + 2 Phase 1 stub identities on init. Idempotent.

    Demo passwords are 'demo123' — DO NOT REUSE IN PROD. The 4 demo ids/roles
    must match DEMO_IDENTITIES in app/app.py so JWT login and demo cookie
    identity refer to the same person.

    The 2 stub ids (RESERVED_USER_IDS) own pre-existing royalty / agent_run
    rows from Phase 1. We seed them with an unloginable sentinel
    password_hash ("disabled$reserved-stub-user") so verify_password always
    returns False (the digest_hex side fails bytes.fromhex). Combined with
    auth_register rejecting these ids up-front, an attacker can't claim a
    stub identity and then JWT-login as the owner of historical rows.
    """
    from datetime import datetime, timezone
    from app.services.auth import hash_password
    from app.storage.users import RESERVED_USER_IDS

    # Sentinel hash — contains '$' (so create_user's format check is satisfied
    # if anything ever round-trips this through the DAO), but neither side is
    # valid hex, so verify_password short-circuits to False.
    DISABLED_HASH = "disabled$reserved-stub-user"

    # password=None means "hash 'demo123' lazily" so we don't burn ~200ms per
    # PBKDF2 call on every app startup when all rows already exist.
    seed_users = [
        ("li_boss",              "李老板",                 "enterprise", None),
        ("zhang_ai",             "张AI",                   "creator",    None),
        ("wang_dev",             "王工",                   "jobseeker",  None),
        ("zhao_design",          "赵设计",                 "creator",    None),
        ("phase1_stub_creator",  "Phase 1 Stub Creator",  "creator",    DISABLED_HASH),
        ("phase1_stub_employer", "Phase 1 Stub Employer", "enterprise", DISABLED_HASH),
    ]
    # Defensive check: the seeded stub ids must stay in sync with the
    # register-route guard.
    assert {uid for uid, _, _, ph in seed_users if ph == DISABLED_HASH} == set(RESERVED_USER_IDS), \
        "seeded stub ids must match RESERVED_USER_IDS"

    existing = {row[0] for row in conn.execute("SELECT id FROM users").fetchall()}
    if existing.issuperset(uid for uid, *_ in seed_users):
        return

    now = datetime.now(timezone.utc).isoformat()
    for uid, name, role, pw_hash in seed_users:
        if uid in existing:
            continue
        # Lazy: demo passwords get hashed only for the row we're inserting.
        resolved_hash = pw_hash if pw_hash is not None else hash_password("demo123")
        conn.execute(
            "INSERT OR IGNORE INTO users (id, name, role, password_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (uid, name, role, resolved_hash, now),
        )
    conn.commit()


def init_db(app: Flask) -> None:
    db_path = app.config["DATABASE_PATH"]
    parent = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(parent, exist_ok=True)
    with closing(_open(db_path)) as conn:
        _create_tables(conn)
        _migrate(conn)
        _seed_demo_users(conn)
