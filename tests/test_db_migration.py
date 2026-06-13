"""
Migration tests: init_db() must upgrade a U2-era skill_assets table
(missing type / endpoint_url columns) to the U3 schema without data loss.

Scenario: a developer ran U2 code, has a hirenet.db with the old schema,
then pulls the U3 branch. The next server start must succeed, not 500.
"""
import os
import sqlite3
import tempfile

import pytest

from app.app import create_app
from app.services.validation import validate
from app.storage.skill_assets import get_skill_asset

# ---------------------------------------------------------------------------
# U2-era DDL — skill_assets table without type / endpoint_url
# ---------------------------------------------------------------------------

_U2_DDL = """
    CREATE TABLE skill_assets (
        id             TEXT    PRIMARY KEY,
        creator_id     TEXT    NOT NULL,
        name           TEXT    NOT NULL,
        description    TEXT    NOT NULL,
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
        payment_method    TEXT    NOT NULL
            CHECK (payment_method IN ('ledger_only', 'on_chain', 'fiat')),
        settlement_status TEXT    NOT NULL
            CHECK (settlement_status IN ('accrued', 'settled')),
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
"""

# One row that exists before migration (represents U2 user data).
_EXISTING_ID = "u2-skill-existing-001"
_U2_INSERT_SQL = """
    INSERT INTO skill_assets
        (id, creator_id, name, description, io_schema, price_amount,
         price_currency, price_chain, split_rule, content_hash, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
_U2_EXISTING_ROW = (
    _EXISTING_ID,
    "user_001",
    "Old U2 Skill",
    "A skill that was registered before U3 migration",
    '{"input": {"text": "string"}}',
    100,
    "USD",
    None,
    '{"creator": 7000, "platform": 3000}',
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "2026-06-01T00:00:00+00:00",
)

# Payload for a fresh registration after migration.
_NEW_PAYLOAD = {
    "name": "Post-Migration Skill",
    "description": "Registered after U2->U3 migration",
    "type": "skill",
    "io_schema": {"input": {"query": "string"}, "output": {"result": "string"}},
    "price_amount": 50,
    "price_currency": "USD",
    "split_rule": {"creator": 7000, "platform": 3000},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_u2_db(path: str) -> None:
    """Create a U2-era database with one pre-existing skill asset row."""
    conn = sqlite3.connect(path)
    conn.executescript(_U2_DDL)
    conn.execute(_U2_INSERT_SQL, _U2_EXISTING_ROW)
    conn.commit()
    conn.close()


def _column_names(path: str, table: str) -> set:
    conn = sqlite3.connect(path)
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    conn.close()
    return {row[1] for row in rows}


def _read_row(path: str, row_id: str) -> dict | None:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM skill_assets WHERE id = ?", (row_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def u2_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    _make_u2_db(path)
    yield path
    os.unlink(path)


@pytest.fixture
def migrated(u2_db_path):
    """Returns (test_client, db_path) after init_db has run on the U2 database."""
    app = create_app({"DATABASE_PATH": u2_db_path, "TESTING": True})
    with app.test_client() as client:
        yield client, u2_db_path


# ---------------------------------------------------------------------------
# Column migration
# ---------------------------------------------------------------------------

def test_migration_adds_type_column(u2_db_path):
    create_app({"DATABASE_PATH": u2_db_path, "TESTING": True})
    assert "type" in _column_names(u2_db_path, "skill_assets")


def test_migration_adds_endpoint_url_column(u2_db_path):
    create_app({"DATABASE_PATH": u2_db_path, "TESTING": True})
    assert "endpoint_url" in _column_names(u2_db_path, "skill_assets")


def test_migration_adds_wallet_address_column(u2_db_path):
    """Phase 3+ MCP wallet integration: upgrading a U2 DB must gain the
    wallet_address column so Sepolia settlement can route to the Agent's
    on-chain address. Backfill is NULL — legacy rows have no declared
    wallet and fall back to SEPOLIA_TO_ADDRESS at settle time."""
    create_app({"DATABASE_PATH": u2_db_path, "TESTING": True})
    assert "wallet_address" in _column_names(u2_db_path, "skill_assets")


def test_migration_backfills_wallet_address_as_null(u2_db_path):
    """Pre-migration rows must end up with wallet_address=NULL (not a
    placeholder) so settle() falls back rather than misrouting funds."""
    create_app({"DATABASE_PATH": u2_db_path, "TESTING": True})
    row = _read_row(u2_db_path, _EXISTING_ID)
    assert row is not None
    assert row["wallet_address"] is None


# ---------------------------------------------------------------------------
# Data preservation
# ---------------------------------------------------------------------------

def test_migration_preserves_existing_row(u2_db_path):
    """Pre-migration data must survive init_db unchanged (name, creator_id, price)."""
    create_app({"DATABASE_PATH": u2_db_path, "TESTING": True})
    row = _read_row(u2_db_path, _EXISTING_ID)
    assert row is not None, "Pre-migration row must not be deleted by migration"
    assert row["name"] == "Old U2 Skill"
    assert row["creator_id"] == "user_001"
    assert row["price_amount"] == 100
    assert row["content_hash"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_migration_backfills_type_for_existing_rows(u2_db_path):
    """Rows with NULL type (U2 rows) must be backfilled to 'skill' after migration."""
    create_app({"DATABASE_PATH": u2_db_path, "TESTING": True})
    row = _read_row(u2_db_path, _EXISTING_ID)
    assert row is not None
    assert row["type"] == "skill", (
        f"Expected backfilled type='skill' for pre-migration row, got {row['type']!r}"
    )


# ---------------------------------------------------------------------------
# Registration after migration
# ---------------------------------------------------------------------------

def test_register_after_migration_returns_201(migrated):
    """POST /api/skills/register must return 201 (not 500) on a migrated DB."""
    client, _ = migrated
    resp = client.post("/api/skills/register", json=_NEW_PAYLOAD)
    assert resp.status_code == 201, (
        f"Expected 201 after migration, got {resp.status_code}: {resp.get_json()}"
    )
    body = resp.get_json()
    assert "skill_id" in body
    assert "content_hash" in body


def test_registered_asset_after_migration_validates_schema(migrated):
    """Asset registered on migrated DB must pass SkillAsset schema validation."""
    client, db_path = migrated
    resp = client.post("/api/skills/register", json=_NEW_PAYLOAD)
    assert resp.status_code == 201
    stored = get_skill_asset(db_path, resp.get_json()["skill_id"])
    assert stored is not None
    validate(stored, "skill_asset")  # must not raise


def test_registered_asset_type_stored_correctly(migrated):
    """type field of newly registered asset must be persisted after migration."""
    client, db_path = migrated
    resp = client.post("/api/skills/register", json=_NEW_PAYLOAD)
    assert resp.status_code == 201
    stored = get_skill_asset(db_path, resp.get_json()["skill_id"])
    assert stored["type"] == "skill"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_migration_is_idempotent(u2_db_path):
    """Running init_db twice on an already-migrated DB must not raise."""
    create_app({"DATABASE_PATH": u2_db_path, "TESTING": True})
    # Second call — should be a no-op
    create_app({"DATABASE_PATH": u2_db_path, "TESTING": True})
    cols = _column_names(u2_db_path, "skill_assets")
    assert "type" in cols
    assert "endpoint_url" in cols


# ---------------------------------------------------------------------------
# Phase 3 / U1: agent_runs gains settlement_method + tx_hash; widened CHECK
# ---------------------------------------------------------------------------

# Insert a U2-era agent_runs row to verify the table rebuild preserves it.
_EXISTING_RUN_ID = "u2-run-existing-001"
_U2_AGENT_RUN_INSERT_SQL = """
    INSERT INTO agent_runs
        (run_id, agent_name, caller_id, task_id, input_tokens, output_tokens,
         llm_cost_usd, time_ms, success, asset_ids, royalty_splits,
         charge_amount, charge_currency, charge_chain, payment_method,
         settlement_status, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
_U2_EXISTING_RUN = (
    _EXISTING_RUN_ID,
    "OldAgent",
    "caller_u2",
    "task_u2",
    None, None, None, None,
    1,  # success
    '["asset_u2"]',
    '{"creator": {"amount": 70, "currency": "USD"}, "platform": {"amount": 30, "currency": "USD"}, "tax": {"amount": 0, "currency": "USD"}}',
    100,
    "USD",
    None,
    "ledger_only",
    "settled",  # an already-settled U2 row must remain settled across the rebuild
    "2026-06-01T00:00:00+00:00",
)


def _make_u2_db_with_run(path: str) -> None:
    """U2 DDL + one pre-existing agent_runs row (settled). Used to verify the
    Phase 3 table rebuild does not drop / corrupt historical rows."""
    conn = sqlite3.connect(path)
    conn.executescript(_U2_DDL)
    conn.execute(_U2_INSERT_SQL, _U2_EXISTING_ROW)
    conn.execute(_U2_AGENT_RUN_INSERT_SQL, _U2_EXISTING_RUN)
    conn.commit()
    conn.close()


@pytest.fixture
def u2_db_with_run():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    _make_u2_db_with_run(path)
    yield path
    os.unlink(path)


def test_phase3_migration_adds_settlement_method_column(u2_db_with_run):
    create_app({"DATABASE_PATH": u2_db_with_run, "TESTING": True})
    assert "settlement_method" in _column_names(u2_db_with_run, "agent_runs")


def test_phase3_migration_adds_tx_hash_column(u2_db_with_run):
    create_app({"DATABASE_PATH": u2_db_with_run, "TESTING": True})
    assert "tx_hash" in _column_names(u2_db_with_run, "agent_runs")


def test_phase3_migration_preserves_existing_run_row(u2_db_with_run):
    """The U2 agent_runs row must survive the table rebuild with charge_amount,
    settlement_status, etc. all intact. New columns get safe defaults."""
    create_app({"DATABASE_PATH": u2_db_with_run, "TESTING": True})
    conn = sqlite3.connect(u2_db_with_run)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM agent_runs WHERE run_id = ?", (_EXISTING_RUN_ID,)
    ).fetchone()
    conn.close()
    assert row is not None, "Phase 3 migration must not drop pre-existing rows"
    assert row["agent_name"] == "OldAgent"
    assert row["charge_amount"] == 100
    assert row["charge_currency"] == "USD"
    assert row["settlement_status"] == "settled"  # pre-existing terminal state survives
    assert row["settlement_method"] == "ledger_only"  # safe default for backfilled rows
    assert row["tx_hash"] is None


def test_phase3_migration_allows_new_status_values(u2_db_with_run):
    """After migration, the CHECK constraint accepts 'settling' and 'failed'.
    Pre-Phase 3 the same INSERT would have failed with a CHECK violation."""
    create_app({"DATABASE_PATH": u2_db_with_run, "TESTING": True})
    conn = sqlite3.connect(u2_db_with_run)
    try:
        for new_status in ("settling", "failed"):
            conn.execute(
                _U2_AGENT_RUN_INSERT_SQL,
                (
                    f"new-{new_status}-run",
                    "NewAgent", "caller_x", "task_x",
                    None, None, None, None,
                    1,
                    '["asset_x"]',
                    '{"creator": {"amount": 1, "currency": "USD"}, "platform": {"amount": 0, "currency": "USD"}, "tax": {"amount": 0, "currency": "USD"}}',
                    1, "USD", None, "ledger_only", new_status,
                    "2026-06-11T00:00:00+00:00",
                ),
            )
        conn.commit()
    finally:
        conn.close()
