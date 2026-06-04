"""
U4 验收测试：record_agent_run service
- charge_amount + split_rule → 正确分账（含精度，平台吸收余数）
- creator_amt + platform_amt == charge_amount 不变量
- 单事务原子性：失败时 agent_runs 与 royalty_ledger 都不留半截
- 错误路径不留半截数据
"""
import os
import sqlite3
import tempfile
import uuid

import pytest
from flask import Flask

from app.services.agent_run_recording import record_agent_run
from app.services.skill_registration import register_skill_asset
from app.services.validation import validate
from app.storage.agent_runs import get_agent_run, list_agent_runs_by_caller
from app.storage.db import init_db
from app.storage.royalty_ledger import list_all_royalties, list_royalties_by_creator


# ---------------------------------------------------------------------------
# Fixtures（拷自 test_storage.py 的 db_path；conftest 改动越界，等出现第三处再 DRY）
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
# Helpers
# ---------------------------------------------------------------------------

def _register_asset(
    db_path: str,
    *,
    creator_id: str = "user_001",
    split: tuple[int, int] = (7000, 3000),
    currency: str = "USD",
) -> str:
    """走真实注册路径准备一个 SkillAsset，避免直插 DB 绕过 content_hash 计算。"""
    payload = {
        "name": "Test Skill",
        "description": "A test skill",
        "type": "skill",
        "io_schema": {"input": {"text": "string"}, "output": {"result": "string"}},
        "price_amount": 100,
        "price_currency": currency,
        "split_rule": {"creator": split[0], "platform": split[1]},
    }
    return register_skill_asset(db_path, payload, creator_id)["skill_id"]


def _raw_insert_corrupted_asset(db_path: str, split_rule_json: str) -> str:
    """直插一个 split_rule sum != 10000 的 skill_asset，用于验证 service 层防御性校验。"""
    asset_id = str(uuid.uuid4())
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO skill_assets
              (id, creator_id, name, description, type, endpoint_url,
               io_schema, price_amount, price_currency, price_chain,
               split_rule, content_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id, "user_001", "X", "x", "skill", None,
                "{}", 100, "USD", None, split_rule_json,
                "0" * 64, "2026-06-04T00:00:00+00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return asset_id


def _base_kwargs(asset_id: str, **overrides) -> dict:
    base = {
        "agent_name": "TestAgent",
        "caller_id": "caller_001",
        "task_id": "task_001",
        "asset_id": asset_id,
        "charge_amount": 100,
        "charge_currency": "USD",
        "success": True,
    }
    base.update(overrides)
    return base


def _assert_db_empty(db_path: str) -> None:
    assert list_agent_runs_by_caller(db_path, "caller_001") == []
    assert list_all_royalties(db_path) == []


# ---------------------------------------------------------------------------
# Happy path / 精度
# ---------------------------------------------------------------------------

class TestSplits:
    def test_70_30_zhengchu(self, db_path):
        asset_id = _register_asset(db_path, split=(7000, 3000))
        result = record_agent_run(db_path, **_base_kwargs(asset_id, charge_amount=100))
        assert result["royalty_splits"]["creator"]["amount"] == 70
        assert result["royalty_splits"]["platform"]["amount"] == 30

    def test_100_0_all_to_creator(self, db_path):
        asset_id = _register_asset(db_path, split=(10000, 0))
        result = record_agent_run(db_path, **_base_kwargs(asset_id, charge_amount=50))
        assert result["royalty_splits"]["creator"]["amount"] == 50
        assert result["royalty_splits"]["platform"]["amount"] == 0
        rows = list_royalties_by_creator(db_path, "user_001")
        assert rows[0]["amount"] == 50

    def test_0_100_all_to_platform(self, db_path):
        # ledger 行仍写入（amount=0），保持"每 run 必有 1 条 ledger"不变量。
        asset_id = _register_asset(db_path, split=(0, 10000))
        result = record_agent_run(db_path, **_base_kwargs(asset_id, charge_amount=100))
        assert result["royalty_splits"]["creator"]["amount"] == 0
        assert result["royalty_splits"]["platform"]["amount"] == 100
        rows = list_royalties_by_creator(db_path, "user_001")
        assert len(rows) == 1
        assert rows[0]["amount"] == 0

    def test_remainder_absorbed_by_platform(self, db_path):
        # charge=7, 5000/5000 → creator=floor(3.5)=3, platform=4
        asset_id = _register_asset(db_path, split=(5000, 5000))
        result = record_agent_run(db_path, **_base_kwargs(asset_id, charge_amount=7))
        assert result["royalty_splits"]["creator"]["amount"] == 3
        assert result["royalty_splits"]["platform"]["amount"] == 4

    def test_floor_always_favors_platform(self, db_path):
        # charge=1, 7000/3000 → creator=floor(0.7)=0, platform=1
        asset_id = _register_asset(db_path, split=(7000, 3000))
        result = record_agent_run(db_path, **_base_kwargs(asset_id, charge_amount=1))
        assert result["royalty_splits"]["creator"]["amount"] == 0
        assert result["royalty_splits"]["platform"]["amount"] == 1


# ---------------------------------------------------------------------------
# 不变量
# ---------------------------------------------------------------------------

class TestInvariants:
    @pytest.mark.parametrize("charge,split", [
        (0, (7000, 3000)),
        (1, (7000, 3000)),
        (1, (3000, 7000)),
        (7, (5000, 5000)),
        (100, (7000, 3000)),
        (100, (10000, 0)),
        (100, (0, 10000)),
        (999, (1234, 8766)),
        (1_000_000, (5000, 5000)),
        (1_000_001, (5000, 5000)),
    ])
    def test_creator_plus_platform_equals_charge_amount(self, db_path, charge, split):
        asset_id = _register_asset(db_path, split=split)
        result = record_agent_run(db_path, **_base_kwargs(asset_id, charge_amount=charge))
        c = result["royalty_splits"]["creator"]["amount"]
        p = result["royalty_splits"]["platform"]["amount"]
        assert c + p == charge
        assert c >= 0 and p >= 0

    def test_ledger_amount_matches_royalty_splits_creator(self, db_path):
        asset_id = _register_asset(db_path, split=(7000, 3000))
        result = record_agent_run(db_path, **_base_kwargs(asset_id, charge_amount=100))
        run = get_agent_run(db_path, result["run_id"])
        assert run["royalty_splits"]["creator"]["amount"] == 70
        ledger_rows = list_royalties_by_creator(db_path, "user_001")
        assert ledger_rows[0]["amount"] == 70
        assert ledger_rows[0]["run_id"] == result["run_id"]

    def test_persisted_agent_run_passes_schema(self, db_path):
        asset_id = _register_asset(db_path, split=(7000, 3000))
        result = record_agent_run(db_path, **_base_kwargs(asset_id))
        run = get_agent_run(db_path, result["run_id"])
        validate(run, "agent_run")  # must not raise

    def test_persisted_ledger_entry_passes_schema(self, db_path):
        asset_id = _register_asset(db_path, split=(7000, 3000))
        record_agent_run(db_path, **_base_kwargs(asset_id))
        rows = list_royalties_by_creator(db_path, "user_001")
        validate(rows[0], "royalty_entry")  # must not raise

    def test_ledger_creator_id_is_asset_creator(self, db_path):
        asset_id = _register_asset(db_path, creator_id="alice_xyz", split=(7000, 3000))
        record_agent_run(db_path, **_base_kwargs(asset_id))
        rows = list_royalties_by_creator(db_path, "alice_xyz")
        assert len(rows) == 1
        assert rows[0]["creator_id"] == "alice_xyz"

    def test_phase1_constants(self, db_path):
        # Phase 1: payment_method 恒为 ledger_only, settlement/status 恒为 accrued
        asset_id = _register_asset(db_path, split=(7000, 3000))
        result = record_agent_run(db_path, **_base_kwargs(asset_id))
        run = get_agent_run(db_path, result["run_id"])
        assert run["payment_method"] == "ledger_only"
        assert run["settlement_status"] == "accrued"
        rows = list_royalties_by_creator(db_path, "user_001")
        assert rows[0]["status"] == "accrued"

    def test_currency_and_chain_flow_through(self, db_path):
        asset_id = _register_asset(db_path)
        result = record_agent_run(
            db_path, **_base_kwargs(asset_id, charge_chain="ethereum")
        )
        run = get_agent_run(db_path, result["run_id"])
        rows = list_royalties_by_creator(db_path, "user_001")
        assert run["charge_currency"] == "USD"
        assert run["charge_chain"] == "ethereum"
        assert rows[0]["currency"] == "USD"
        assert rows[0]["chain"] == "ethereum"


# ---------------------------------------------------------------------------
# 错误路径（每条都顺便断言 DB 没写半截）
# ---------------------------------------------------------------------------

class TestErrorPaths:
    def test_unknown_asset_id(self, db_path):
        with pytest.raises(ValueError, match="Unknown asset_id"):
            record_agent_run(db_path, **_base_kwargs("ghost-asset-id"))
        _assert_db_empty(db_path)

    def test_currency_mismatch(self, db_path):
        asset_id = _register_asset(db_path, currency="USD")
        with pytest.raises(ValueError, match="does not match"):
            record_agent_run(db_path, **_base_kwargs(asset_id, charge_currency="EUR"))
        _assert_db_empty(db_path)

    def test_negative_charge_amount(self, db_path):
        asset_id = _register_asset(db_path)
        with pytest.raises(ValueError):
            record_agent_run(db_path, **_base_kwargs(asset_id, charge_amount=-1))
        _assert_db_empty(db_path)

    def test_float_charge_amount(self, db_path):
        asset_id = _register_asset(db_path)
        with pytest.raises(TypeError):
            record_agent_run(db_path, **_base_kwargs(asset_id, charge_amount=0.5))
        _assert_db_empty(db_path)

    def test_bool_charge_amount_rejected(self, db_path):
        # bool 是 int 的子类，但金额必须是真正的 int —— 防止 True/False 静默通过
        asset_id = _register_asset(db_path)
        with pytest.raises(TypeError):
            record_agent_run(db_path, **_base_kwargs(asset_id, charge_amount=True))
        _assert_db_empty(db_path)

    def test_corrupted_split_rule_in_db(self, db_path):
        bad_asset_id = _raw_insert_corrupted_asset(
            db_path, split_rule_json='{"creator": 8000, "platform": 3000}'
        )
        with pytest.raises(ValueError, match="must sum to 10000"):
            record_agent_run(db_path, **_base_kwargs(bad_asset_id))
        _assert_db_empty(db_path)


# ---------------------------------------------------------------------------
# asset_id 显式校验：U4 只支持单 asset，多 asset / 错类型必须在 DB 之前被拒
# ---------------------------------------------------------------------------

class TestAssetIdValidation:
    """U4 仅支持单 asset。多 asset 必须在 service 入口显式拒绝，
    不能默默走到 SQLite 层抛 ProgrammingError，也不能默默取第一个。
    """

    def test_list_of_asset_ids_rejected_with_clear_error(self, db_path):
        a1 = _register_asset(db_path, split=(7000, 3000))
        a2 = _register_asset(db_path, split=(5000, 5000))

        with pytest.raises(ValueError) as exc_info:
            record_agent_run(db_path, **_base_kwargs([a1, a2]))

        # 必须是显式拒绝（ValueError），不是底层 sqlite3.ProgrammingError
        assert not isinstance(exc_info.value, sqlite3.ProgrammingError)
        msg = str(exc_info.value).lower()
        assert "multi-asset" in msg or "single" in msg, (
            f"error message must clearly say multi-asset not supported, got: {exc_info.value!r}"
        )

        # 既不能写 agent_runs，也不能写 royalty_ledger
        assert list_agent_runs_by_caller(db_path, "caller_001") == []
        assert list_all_royalties(db_path) == []

    def test_tuple_of_asset_ids_rejected(self, db_path):
        a1 = _register_asset(db_path, split=(7000, 3000))
        a2 = _register_asset(db_path, split=(5000, 5000))
        with pytest.raises(ValueError, match="multi-asset|single"):
            record_agent_run(db_path, **_base_kwargs((a1, a2)))
        _assert_db_empty(db_path)

    def test_dict_asset_id_rejected(self, db_path):
        a1 = _register_asset(db_path)
        with pytest.raises((TypeError, ValueError)) as exc_info:
            record_agent_run(db_path, **_base_kwargs({"id": a1}))
        assert not isinstance(exc_info.value, sqlite3.ProgrammingError)
        _assert_db_empty(db_path)

    def test_none_asset_id_rejected(self, db_path):
        _register_asset(db_path)
        with pytest.raises((TypeError, ValueError)) as exc_info:
            record_agent_run(db_path, **_base_kwargs(None))
        assert not isinstance(exc_info.value, sqlite3.ProgrammingError)
        _assert_db_empty(db_path)

    def test_empty_string_asset_id_rejected(self, db_path):
        _register_asset(db_path)
        with pytest.raises(ValueError):
            record_agent_run(db_path, **_base_kwargs(""))
        _assert_db_empty(db_path)


# ---------------------------------------------------------------------------
# 原子性：失败回滚（单事务的关键证据）
# ---------------------------------------------------------------------------

class TestAtomicity:
    def test_atomic_rollback_on_ledger_failure(self, db_path, monkeypatch):
        """ledger INSERT 在事务中途失败时，agent_runs 也必须被回滚。

        通过 monkeypatch 把 record_agent_run 持有的 ledger SQL 引用换成会触发
        sqlite3.OperationalError 的语句（指向不存在的表），让第二条 execute
        在 `with conn:` 块内抛错，强制 SQLite 回滚整个事务。
        """
        asset_id = _register_asset(db_path)

        broken_sql = "INSERT INTO nonexistent_table_xyz VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
        monkeypatch.setattr(
            "app.services.agent_run_recording._INSERT_ROYALTY_ENTRY_SQL",
            broken_sql,
        )

        with pytest.raises(sqlite3.OperationalError):
            record_agent_run(db_path, **_base_kwargs(asset_id))

        # 关键断言：agent_runs 必须也是空的 —— 同一事务被一起回滚
        assert list_agent_runs_by_caller(db_path, "caller_001") == []
        assert list_all_royalties(db_path) == []
