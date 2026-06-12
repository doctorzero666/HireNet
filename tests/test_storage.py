"""
U2 验收测试：SQLite 持久化层
- 写入/读出一致
- 跨连接持久性（重启模拟）
- DB 读回的 dict 能通过对应 U1 schema 校验（C-2）
- DB CHECK 约束拒绝非法值（C-3）
- 金额列为 INTEGER（C-1）
"""
import os
import sqlite3
import tempfile
import uuid

import pytest
from flask import Flask

from app.storage.db import init_db, _open
from app.storage.skill_assets import get_skill_asset, insert_skill_asset, list_skill_assets
from app.storage.agent_runs import get_agent_run, insert_agent_run, list_agent_runs_by_caller
from app.storage.royalty_ledger import (
    insert_royalty_entries,
    list_all_royalties,
    list_royalties_by_creator,
)


def insert_royalty_entry(db_path: str, entry: dict) -> str:
    """Single-entry test helper preserving the pre-U2 call shape.

    The storage layer only exposes the batch insert (`insert_royalty_entries`)
    now; tests in this file write one row at a time, so wrap the batch call
    with a length-1 list and return the lone id.
    """
    return insert_royalty_entries(db_path, [entry])[0]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = path
    init_db(app)
    yield path
    os.unlink(path)


# ---------------------------------------------------------------------------
# Minimal data builders — amounts in integer basis points
# ---------------------------------------------------------------------------

def _skill_asset(**overrides) -> dict:
    base = {
        "creator_id": "user_001",
        "name": "Test Skill",
        "description": "A test skill",
        "type": "skill",
        "endpoint_url": None,
        "io_schema": {"input": {"text": "string"}, "output": {"result": "string"}},
        "price_amount": 50,          # 50 basis points
        "price_currency": "USD",
        "price_chain": None,
        "split_rule": {"creator": 7000, "platform": 3000},
        "content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    }
    base.update(overrides)
    return base


def _agent_run(**overrides) -> dict:
    base = {
        "agent_name": "TestAgent",
        "caller_id": "caller_001",
        "task_id": "task_001",
        "input_tokens": 100,
        "output_tokens": 50,
        "llm_cost_usd": "0.002",
        "time_ms": 1200,
        "success": True,
        "asset_ids": ["skill_001"],
        "royalty_splits": {"user_001": {"amount": 35, "currency": "USD"}},
        "charge_amount": 50,         # 50 basis points
        "charge_currency": "USD",
        "charge_chain": None,
        "payment_method": "ledger_only",
        "settlement_status": "accrued",
    }
    base.update(overrides)
    return base


def _royalty_entry(run_id: str, **overrides) -> dict:
    base = {
        "run_id": run_id,
        "creator_id": "user_001",
        "payee_id": "user_001",
        "party": "creator",
        "asset_id": "skill_001",
        "amount": 35,                # 35 basis points
        "currency": "USD",
        "chain": None,
        "status": "accrued",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Raw row builders — for direct DB inserts that bypass the storage layer (C-3)
# ---------------------------------------------------------------------------

def _raw_skill_asset_row(**overrides) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "creator_id": "user_001",
        "name": "Raw Test",
        "description": "raw",
        "type": "skill",
        "endpoint_url": None,
        "io_schema": "{}",
        "price_amount": 50,
        "price_currency": "USD",
        "price_chain": None,
        "split_rule": "{}",
        "content_hash": "e" * 64,
        "created_at": "2026-06-04T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def _raw_agent_run_row(**overrides) -> dict:
    base = {
        "run_id": str(uuid.uuid4()),
        "agent_name": "test",
        "caller_id": "caller",
        "task_id": "task",
        "input_tokens": None,
        "output_tokens": None,
        "llm_cost_usd": None,
        "time_ms": None,
        "success": 1,
        "asset_ids": "[]",
        "royalty_splits": "{}",
        "charge_amount": 50,
        "charge_currency": "USD",
        "charge_chain": None,
        "payment_method": "ledger_only",
        "settlement_status": "accrued",
        "created_at": "2026-06-04T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def _raw_royalty_row(**overrides) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "run_id": "run_001",
        "creator_id": "user_001",
        "payee_id": "user_001",
        "party": "creator",
        "asset_id": "skill_001",
        "amount": 35,
        "currency": "USD",
        "chain": None,
        "status": "accrued",
        "created_at": "2026-06-04T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def _raw_insert(db_path: str, table: str, row: dict) -> None:
    """Insert a row directly into the DB, bypassing the storage layer."""
    conn = sqlite3.connect(db_path)
    try:
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" * len(row))
        conn.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",  # noqa: S608
            list(row.values()),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# TestInitDb
# ---------------------------------------------------------------------------

class TestInitDb:
    def test_creates_all_tables(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            app = Flask(__name__)
            app.config["DATABASE_PATH"] = path
            init_db(app)
            conn = sqlite3.connect(path)
            try:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            finally:
                conn.close()
            table_names = {r[0] for r in rows}
            assert "skill_assets" in table_names
            assert "agent_runs" in table_names
            assert "royalty_ledger" in table_names
        finally:
            os.unlink(path)

    def test_idempotent(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            app = Flask(__name__)
            app.config["DATABASE_PATH"] = path
            init_db(app)
            init_db(app)  # second call must not raise
        finally:
            os.unlink(path)

    def test_migration_rollback_on_failure(self, monkeypatch):
        """A migration error must roll back every prior ALTER, not strand the DB.

        Simulates the Phase 1 → U2 upgrade path: create a DB with the old
        royalty_ledger schema (no payee_id / party), then force the second
        ALTER to fail. Expect: neither payee_id NOR party exists after the
        crash — the explicit transaction in _migrate rolled both back together.

        sqlite3.Connection is immutable, so instead of monkey-patching its
        execute we swap _open() for a factory that returns a proxy connection
        which intercepts the offending ALTER.
        """
        from app.storage import db as db_module

        class FailingConnection:
            """Thin proxy that rejects the `party` ALTER once, passthrough else."""
            def __init__(self, real):
                self._real = real
            def execute(self, sql, *args, **kwargs):
                if "ADD COLUMN party" in sql:
                    raise sqlite3.OperationalError("simulated mid-migration crash")
                return self._real.execute(sql, *args, **kwargs)
            def executescript(self, sql, *args, **kwargs):
                return self._real.executescript(sql, *args, **kwargs)
            def commit(self):
                return self._real.commit()
            def rollback(self):
                return self._real.rollback()
            def close(self):
                return self._real.close()
            @property
            def isolation_level(self):
                return self._real.isolation_level
            @isolation_level.setter
            def isolation_level(self, value):
                self._real.isolation_level = value

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            # Hand-build a pre-U2 royalty_ledger (no payee_id, no party).
            conn = sqlite3.connect(path)
            conn.executescript("""
                CREATE TABLE royalty_ledger (
                    id         TEXT PRIMARY KEY,
                    run_id     TEXT NOT NULL,
                    creator_id TEXT NOT NULL,
                    asset_id   TEXT NOT NULL,
                    amount     INTEGER NOT NULL,
                    currency   TEXT NOT NULL,
                    chain      TEXT,
                    status     TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE skill_assets (
                    id             TEXT PRIMARY KEY,
                    creator_id     TEXT NOT NULL,
                    name           TEXT NOT NULL,
                    description    TEXT NOT NULL,
                    type           TEXT NOT NULL,
                    endpoint_url   TEXT,
                    io_schema      TEXT NOT NULL,
                    price_amount   INTEGER NOT NULL,
                    price_currency TEXT NOT NULL,
                    price_chain    TEXT,
                    split_rule     TEXT NOT NULL,
                    content_hash   TEXT NOT NULL,
                    created_at     TEXT NOT NULL
                );
                CREATE TABLE agent_runs (run_id TEXT PRIMARY KEY);
            """)
            conn.commit()
            conn.close()

            _real_open = db_module._open
            monkeypatch.setattr(
                db_module, "_open",
                lambda p: FailingConnection(_real_open(p)),
            )

            app = Flask(__name__)
            app.config["DATABASE_PATH"] = path
            with pytest.raises(sqlite3.OperationalError, match="simulated mid-migration crash"):
                db_module.init_db(app)

            monkeypatch.undo()

            # Verify rollback: neither column should be present on royalty_ledger.
            conn = sqlite3.connect(path)
            try:
                cols = {r[1] for r in conn.execute(
                    "PRAGMA table_info(royalty_ledger)"
                ).fetchall()}
            finally:
                conn.close()
            assert "payee_id" not in cols, (
                "payee_id leaked through after a failed migration — "
                "_migrate is not atomic"
            )
            assert "party" not in cols
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# TestSkillAssets
# ---------------------------------------------------------------------------

class TestSkillAssets:
    def test_insert_returns_uuid(self, db_path):
        returned = insert_skill_asset(db_path, _skill_asset())
        assert returned
        uuid.UUID(returned)  # raises if not a valid UUID

    def test_get_roundtrip(self, db_path):
        skill_id = insert_skill_asset(db_path, _skill_asset())
        result = get_skill_asset(db_path, skill_id)
        assert result is not None
        assert result["creator_id"] == "user_001"
        assert isinstance(result["io_schema"], dict)
        assert isinstance(result["split_rule"], dict)
        assert result["created_at"]

    def test_get_unknown_returns_none(self, db_path):
        assert get_skill_asset(db_path, "nonexistent-id") is None

    def test_list_all(self, db_path):
        insert_skill_asset(db_path, _skill_asset(creator_id="A"))
        insert_skill_asset(db_path, _skill_asset(creator_id="B"))
        insert_skill_asset(db_path, _skill_asset(creator_id="B"))
        assert len(list_skill_assets(db_path)) == 3

    def test_list_by_creator(self, db_path):
        insert_skill_asset(db_path, _skill_asset(creator_id="A"))
        insert_skill_asset(db_path, _skill_asset(creator_id="B"))
        insert_skill_asset(db_path, _skill_asset(creator_id="B"))
        result = list_skill_assets(db_path, creator_id="B")
        assert len(result) == 2
        assert all(r["creator_id"] == "B" for r in result)

    def test_price_amount_is_integer(self, db_path):
        """C-1: price_amount must come back as a Python int, not str."""
        insert_skill_asset(db_path, _skill_asset(price_amount=123))
        rows = list_skill_assets(db_path)
        assert isinstance(rows[0]["price_amount"], int)
        assert rows[0]["price_amount"] == 123

    def test_float_price_amount_rejected(self, db_path):
        """M-3: float amount must raise at write time, not silently coerce."""
        with pytest.raises(TypeError):
            insert_skill_asset(db_path, _skill_asset(price_amount=0.5))

    def test_string_price_amount_rejected(self, db_path):
        """M-3: string amount must raise at write time."""
        with pytest.raises(TypeError):
            insert_skill_asset(db_path, _skill_asset(price_amount="50"))

    def test_persistence_across_connections(self, db_path):
        """m-3: data survives after the writing connection is closed."""
        skill_id = insert_skill_asset(db_path, _skill_asset())
        # Open an entirely independent connection to prove data is on disk
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT id, creator_id FROM skill_assets WHERE id = ?", (skill_id,)
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["creator_id"] == "user_001"

    def test_db_output_validates_against_schema(self, db_path):
        """C-2: dict returned by get_skill_asset must pass U1 schema validation."""
        from app.services.validation import validate
        skill_id = insert_skill_asset(db_path, _skill_asset())
        result = get_skill_asset(db_path, skill_id)
        validate(result, "skill_asset")  # must not raise


# ---------------------------------------------------------------------------
# TestAgentRuns
# ---------------------------------------------------------------------------

class TestAgentRuns:
    def test_insert_returns_run_id(self, db_path):
        run_id = insert_agent_run(db_path, _agent_run())
        assert run_id

    def test_get_roundtrip(self, db_path):
        run_id = insert_agent_run(db_path, _agent_run())
        result = get_agent_run(db_path, run_id)
        assert result is not None
        assert result["agent_name"] == "TestAgent"
        assert isinstance(result["asset_ids"], list)
        assert isinstance(result["royalty_splits"], dict)
        assert result["success"] is True

    def test_success_false(self, db_path):
        run_id = insert_agent_run(db_path, _agent_run(success=False))
        result = get_agent_run(db_path, run_id)
        assert result["success"] is False

    def test_get_unknown_returns_none(self, db_path):
        assert get_agent_run(db_path, "nope") is None

    def test_list_by_caller(self, db_path):
        insert_agent_run(db_path, _agent_run(caller_id="A"))
        insert_agent_run(db_path, _agent_run(caller_id="A"))
        insert_agent_run(db_path, _agent_run(caller_id="B"))
        assert len(list_agent_runs_by_caller(db_path, "A")) == 2
        assert len(list_agent_runs_by_caller(db_path, "B")) == 1

    def test_charge_amount_is_integer(self, db_path):
        """C-1: charge_amount must come back as int."""
        run_id = insert_agent_run(db_path, _agent_run(charge_amount=75))
        result = get_agent_run(db_path, run_id)
        assert isinstance(result["charge_amount"], int)
        assert result["charge_amount"] == 75

    def test_float_charge_amount_rejected(self, db_path):
        """M-3: float charge_amount must raise."""
        with pytest.raises(TypeError):
            insert_agent_run(db_path, _agent_run(charge_amount=0.5))

    def test_persistence_across_connections(self, db_path):
        """m-3: data survives after the writing connection is closed."""
        run_id = insert_agent_run(db_path, _agent_run())
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT run_id FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["run_id"] == run_id

    def test_db_output_validates_against_schema(self, db_path):
        """C-2: dict returned by get_agent_run must pass U1 schema validation."""
        from app.services.validation import validate
        run_id = insert_agent_run(db_path, _agent_run())
        result = get_agent_run(db_path, run_id)
        validate(result, "agent_run")  # must not raise


# ---------------------------------------------------------------------------
# TestRoyaltyLedger
# ---------------------------------------------------------------------------

class TestRoyaltyLedger:
    def test_insert_returns_id(self, db_path):
        entry_id = insert_royalty_entry(db_path, _royalty_entry("run_001"))
        assert entry_id

    def test_list_by_creator_roundtrip(self, db_path):
        insert_royalty_entry(db_path, _royalty_entry("run_001"))
        rows = list_royalties_by_creator(db_path, "user_001")
        assert len(rows) == 1
        assert rows[0]["amount"] == 35
        assert rows[0]["status"] == "accrued"

    def test_amount_is_integer(self, db_path):
        """C-1: amount must come back as int, not str."""
        insert_royalty_entry(db_path, _royalty_entry("run_001", amount=150))
        rows = list_royalties_by_creator(db_path, "user_001")
        assert isinstance(rows[0]["amount"], int)
        assert rows[0]["amount"] == 150

    def test_float_amount_rejected(self, db_path):
        """M-3: float amount must raise."""
        with pytest.raises(TypeError):
            insert_royalty_entry(db_path, _royalty_entry("run_001", amount=0.35))

    def test_chain_nullable(self, db_path):
        insert_royalty_entry(db_path, _royalty_entry("run_001", chain=None))
        rows = list_royalties_by_creator(db_path, "user_001")
        assert rows[0]["chain"] is None

    def test_list_all(self, db_path):
        insert_royalty_entry(db_path, _royalty_entry("run_001", creator_id="A"))
        insert_royalty_entry(db_path, _royalty_entry("run_002", creator_id="B"))
        assert len(list_all_royalties(db_path)) == 2

    def test_persistence_across_connections(self, db_path):
        """m-3: data survives after the writing connection is closed."""
        insert_royalty_entry(db_path, _royalty_entry("run_001"))
        # Independent connection — no shared state with writing path
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT amount, status FROM royalty_ledger WHERE creator_id = ?",
                ("user_001",),
            ).fetchall()
        finally:
            conn.close()
        assert len(rows) >= 1
        assert rows[0]["status"] == "accrued"

    def test_db_output_validates_against_schema(self, db_path):
        """C-2: dict returned by list_royalties_by_creator must pass U1 schema validation."""
        from app.services.validation import validate
        insert_royalty_entry(db_path, _royalty_entry("run_001"))
        rows = list_royalties_by_creator(db_path, "user_001")
        assert rows
        validate(rows[0], "royalty_entry")  # must not raise


# ---------------------------------------------------------------------------
# TestCheckConstraints — C-3: DB must reject invalid values at the SQLite layer
# ---------------------------------------------------------------------------

class TestCheckConstraints:
    def test_negative_price_amount_rejected(self, db_path):
        with pytest.raises(sqlite3.IntegrityError):
            _raw_insert(db_path, "skill_assets", _raw_skill_asset_row(price_amount=-1))

    def test_invalid_settlement_status_rejected(self, db_path):
        with pytest.raises(sqlite3.IntegrityError):
            _raw_insert(db_path, "agent_runs", _raw_agent_run_row(settlement_status="pending"))

    def test_invalid_payment_method_rejected(self, db_path):
        with pytest.raises(sqlite3.IntegrityError):
            _raw_insert(db_path, "agent_runs", _raw_agent_run_row(payment_method="cash"))

    def test_negative_charge_amount_rejected(self, db_path):
        with pytest.raises(sqlite3.IntegrityError):
            _raw_insert(db_path, "agent_runs", _raw_agent_run_row(charge_amount=-1))

    def test_invalid_success_value_rejected(self, db_path):
        with pytest.raises(sqlite3.IntegrityError):
            _raw_insert(db_path, "agent_runs", _raw_agent_run_row(success=2))

    def test_negative_royalty_amount_rejected(self, db_path):
        with pytest.raises(sqlite3.IntegrityError):
            _raw_insert(db_path, "royalty_ledger", _raw_royalty_row(amount=-1))

    def test_invalid_royalty_status_rejected(self, db_path):
        with pytest.raises(sqlite3.IntegrityError):
            _raw_insert(db_path, "royalty_ledger", _raw_royalty_row(status="invalid"))


# ---------------------------------------------------------------------------
# TestCrossTableConsistency — end-to-end acceptance criteria
# ---------------------------------------------------------------------------

class TestCrossTableConsistency:
    def test_full_flow_write_read_consistency(self, db_path):
        """
        Register SkillAsset → trigger AgentRun → royalty_ledger has correct entry.
        Verifies amount/currency/chain triple (m-4) and schema validation (C-2).
        """
        from app.services.validation import validate

        # Step 1: register a SkillAsset
        skill_id = insert_skill_asset(db_path, _skill_asset())

        # Step 2: record an agent run that used this asset
        run_id = insert_agent_run(db_path, _agent_run(asset_ids=[skill_id]))

        # Step 3: write the royalty ledger entry
        entry_id = insert_royalty_entry(
            db_path,
            _royalty_entry(
                run_id,
                asset_id=skill_id,
                creator_id="user_001",
                amount=35,
                currency="USD",
                chain=None,
                status="accrued",
            ),
        )

        # Basic read-back
        assert get_skill_asset(db_path, skill_id) is not None
        assert get_agent_run(db_path, run_id) is not None

        ledger = list_royalties_by_creator(db_path, "user_001")
        assert len(ledger) >= 1
        entry = next(r for r in ledger if r["id"] == entry_id)

        # m-4: amount / currency / chain all asserted
        assert entry["amount"] == 35
        assert entry["currency"] == "USD"
        assert entry["chain"] is None
        assert entry["creator_id"] == "user_001"
        assert entry["status"] == "accrued"

        # C-2: schema validation on every read-back dict
        validate(get_skill_asset(db_path, skill_id), "skill_asset")
        validate(get_agent_run(db_path, run_id), "agent_run")
        validate(entry, "royalty_entry")
