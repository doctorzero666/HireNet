"""
Phase 2 / U2 验收测试：royalty_ledger 推广成「一 payee 一行」

不变量（每次 record_agent_run 调用之后必须成立）：
- ledger 里恰好 3 行：party='creator' / 'platform' / 'tax'，全部同一个 run_id
- creator 行：payee_id == asset.creator_id
- platform 行：payee_id == 'platform'
- tax 行：payee_id == 'tax'
- 三行金额相加 == charge_amount（即 U1 对账不变量在落库后仍然成立）
- 三行 status 均为 'accrued'，asset_id / currency / chain 一致
- 三行都能过 royalty_entry schema 校验（持久化往返通过）
"""
import os
import tempfile

import pytest
from flask import Flask

from app.services.agent_run_recording import record_agent_run
from app.services.skill_registration import register_skill_asset
from app.services.validation import validate
from app.storage.db import init_db
from app.storage.royalty_ledger import (
    list_royalties_by_payee,
    list_royalties_by_run,
)


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


def _register_asset(
    db_path: str,
    *,
    creator_id: str = "alice",
    split: dict | None = None,
    currency: str = "USD",
    chain: str | None = None,
    name: str = "U2 Skill",
) -> str:
    payload = {
        "name": name,
        "description": f"desc for {name}",
        "type": "skill",
        "io_schema": {"input": {"text": "string"}, "output": {"result": "string"}},
        "price_amount": 100,
        "price_currency": currency,
        "split_rule": split or {"creator": 7000, "platform": 2000, "tax": 1000},
    }
    if chain is not None:
        payload["price_chain"] = chain
    return register_skill_asset(db_path, payload, creator_id)["skill_id"]


def _call(db_path, asset_id, *, charge_amount=100, currency="USD", chain=None,
          caller_id="caller_001", task_id="task_001"):
    kwargs = {
        "agent_name": "TestAgent",
        "caller_id": caller_id,
        "task_id": task_id,
        "asset_id": asset_id,
        "charge_amount": charge_amount,
        "charge_currency": currency,
        "success": True,
    }
    if chain is not None:
        kwargs["charge_chain"] = chain
    return record_agent_run(db_path, **kwargs)


# ---------------------------------------------------------------------------
# 核心不变量：一次 run → ledger 三行
# ---------------------------------------------------------------------------

class TestThreeRowLedger:
    def test_three_way_split_writes_exactly_three_rows(self, db_path):
        asset_id = _register_asset(
            db_path,
            creator_id="alice",
            split={"creator": 7000, "platform": 2000, "tax": 1000},
        )
        result = _call(db_path, asset_id, charge_amount=100)

        rows = list_royalties_by_run(db_path, result["run_id"])
        assert len(rows) == 3, f"expected 3 ledger rows, got {len(rows)}"

        parties = {r["party"]: r for r in rows}
        assert set(parties.keys()) == {"creator", "platform", "tax"}

        assert parties["creator"]["payee_id"] == "alice"
        assert parties["creator"]["amount"] == 70

        assert parties["platform"]["payee_id"] == "platform"
        assert parties["platform"]["amount"] == 20

        assert parties["tax"]["payee_id"] == "tax"
        assert parties["tax"]["amount"] == 10

    def test_three_rows_sum_to_charge_amount(self, db_path):
        # 对账不变量 (Phase 2 / U1) 在落库后仍然成立：creator + platform + tax == charge.
        asset_id = _register_asset(
            db_path, split={"creator": 5000, "platform": 3000, "tax": 2000}
        )
        result = _call(db_path, asset_id, charge_amount=7)
        rows = list_royalties_by_run(db_path, result["run_id"])
        assert sum(r["amount"] for r in rows) == 7

    @pytest.mark.parametrize("charge,split", [
        (0, {"creator": 7000, "platform": 2000, "tax": 1000}),
        (1, {"creator": 7000, "platform": 2000, "tax": 1000}),
        (7, {"creator": 5000, "platform": 3000, "tax": 2000}),
        (100, {"creator": 7000, "platform": 2000, "tax": 1000}),
        (999, {"creator": 1234, "platform": 7766, "tax": 1000}),
        (1_000_001, {"creator": 5000, "platform": 3000, "tax": 2000}),
    ])
    def test_ledger_sum_invariant_parametric(self, db_path, charge, split):
        asset_id = _register_asset(db_path, split=split)
        result = _call(db_path, asset_id, charge_amount=charge)
        rows = list_royalties_by_run(db_path, result["run_id"])
        assert len(rows) == 3
        assert sum(r["amount"] for r in rows) == charge

    def test_three_rows_share_run_id_and_asset_id(self, db_path):
        asset_id = _register_asset(db_path, creator_id="bob")
        result = _call(db_path, asset_id, charge_amount=100)
        rows = list_royalties_by_run(db_path, result["run_id"])
        assert {r["run_id"] for r in rows} == {result["run_id"]}
        assert {r["asset_id"] for r in rows} == {asset_id}

    def test_three_rows_share_currency_chain_and_status(self, db_path):
        asset_id = _register_asset(
            db_path, creator_id="alice", currency="USDC", chain="ethereum"
        )
        result = _call(db_path, asset_id, charge_amount=100,
                       currency="USDC", chain="ethereum")
        rows = list_royalties_by_run(db_path, result["run_id"])
        assert {r["currency"] for r in rows} == {"USDC"}
        assert {r["chain"] for r in rows} == {"ethereum"}
        assert {r["status"] for r in rows} == {"accrued"}

    def test_legacy_two_way_split_still_writes_three_rows(self, db_path):
        # 旧 2-way split（无 tax）：tax 行金额=0，但仍是真实落库的一行，
        # 这样下游结算层不用为「tax 缺失」单独写代码。
        asset_id = _register_asset(
            db_path, creator_id="alice", split={"creator": 7000, "platform": 3000}
        )
        result = _call(db_path, asset_id, charge_amount=100)
        rows = list_royalties_by_run(db_path, result["run_id"])
        assert len(rows) == 3
        parties = {r["party"]: r["amount"] for r in rows}
        assert parties == {"creator": 70, "platform": 30, "tax": 0}

    def test_each_persisted_row_passes_schema(self, db_path):
        asset_id = _register_asset(db_path)
        result = _call(db_path, asset_id, charge_amount=100)
        rows = list_royalties_by_run(db_path, result["run_id"])
        assert len(rows) == 3
        for row in rows:
            validate(row, "royalty_entry")  # must not raise

    def test_record_agent_run_returns_three_entry_ids(self, db_path):
        asset_id = _register_asset(db_path)
        result = _call(db_path, asset_id, charge_amount=100)
        # 接口契约：返回 3 个 ledger entry id（顺序：creator / platform / tax）
        assert isinstance(result["ledger_entry_ids"], list)
        assert len(result["ledger_entry_ids"]) == 3
        assert len(set(result["ledger_entry_ids"])) == 3  # all unique


# ---------------------------------------------------------------------------
# 按 payee 的查询路径（U4 收益页要用）
# ---------------------------------------------------------------------------

class TestListByPayee:
    def test_creator_sees_only_creator_share(self, db_path):
        asset_id = _register_asset(
            db_path, creator_id="alice",
            split={"creator": 7000, "platform": 2000, "tax": 1000},
        )
        _call(db_path, asset_id, charge_amount=100)
        rows = list_royalties_by_payee(db_path, "alice")
        assert len(rows) == 1
        assert rows[0]["party"] == "creator"
        assert rows[0]["amount"] == 70

    def test_platform_sees_only_platform_rows(self, db_path):
        a1 = _register_asset(db_path, creator_id="alice",
                             split={"creator": 7000, "platform": 2000, "tax": 1000})
        a2 = _register_asset(db_path, creator_id="bob",
                             split={"creator": 7000, "platform": 2000, "tax": 1000},
                             name="Bob Skill")
        _call(db_path, a1, charge_amount=100)
        _call(db_path, a2, charge_amount=100)

        rows = list_royalties_by_payee(db_path, "platform")
        assert len(rows) == 2
        assert all(r["party"] == "platform" for r in rows)
        assert all(r["amount"] == 20 for r in rows)

    def test_tax_sees_only_tax_rows(self, db_path):
        asset_id = _register_asset(
            db_path, creator_id="alice",
            split={"creator": 7000, "platform": 2000, "tax": 1000},
        )
        _call(db_path, asset_id, charge_amount=100)
        _call(db_path, asset_id, charge_amount=100)

        rows = list_royalties_by_payee(db_path, "tax")
        assert len(rows) == 2
        assert all(r["party"] == "tax" for r in rows)
        assert all(r["amount"] == 10 for r in rows)

    def test_other_creator_does_not_see_alice_share(self, db_path):
        alice_asset = _register_asset(db_path, creator_id="alice")
        _call(db_path, alice_asset, charge_amount=100)
        # 不是 alice 的人查不到她的 creator 行
        assert list_royalties_by_payee(db_path, "bob") == []


# ---------------------------------------------------------------------------
# 原子性：3-way 不能半行落库
# ---------------------------------------------------------------------------

class TestAtomicity:
    def test_three_rows_land_atomically_on_failure(self, db_path, monkeypatch):
        """ledger INSERT 在中途失败时，agent_runs + 已写入的 ledger 行都必须回滚。

        把 _INSERT_ROYALTY_ENTRY_SQL 换成一条会触发 OperationalError 的语句，
        让第一条 ledger INSERT 就抛错。结果：agent_runs 表也必须是空的，
        ledger 三行一行都不能留。
        """
        import sqlite3
        from app.storage.agent_runs import list_agent_runs_by_caller
        from app.storage.royalty_ledger import list_all_royalties

        asset_id = _register_asset(db_path, creator_id="alice")

        broken_sql = "INSERT INTO nonexistent_ledger_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        monkeypatch.setattr(
            "app.services.agent_run_recording._INSERT_ROYALTY_ENTRY_SQL",
            broken_sql,
        )

        with pytest.raises(sqlite3.OperationalError):
            _call(db_path, asset_id, charge_amount=100)

        # 任何一行都不能留下来
        assert list_agent_runs_by_caller(db_path, "caller_001") == []
        assert list_all_royalties(db_path) == []
