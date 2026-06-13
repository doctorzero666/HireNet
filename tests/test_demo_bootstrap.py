"""
Demo bootstrap 测试 — 预填 zhang_ai 的"客服话术生成器"Agent + 两条历史调用。

测试用自己的 fixture（不走 conftest 的 TESTING=True 路径），直接拿 db_path 调
bootstrap 函数 — bootstrap 模块本身不读 app.config。

为了测 /api/demo/agent endpoint，我们显式 create_app 时关闭 TESTING 来让 demo
bootstrap 在 create_app 里跑起来。conftest 那 526 tests 仍走 TESTING=True，
不受影响。
"""
import os
import tempfile

import pytest

from app.app import create_app
from app.services.demo_bootstrap import (
    DEMO_CS_AGENT,
    bootstrap_demo_cs_asset,
    bootstrap_demo_runs,
)
from app.services.mock_settlement import MockSettlementProvider
from app.storage.agent_runs import list_agent_runs_by_caller
from app.storage.db import init_db
from app.storage.royalty_ledger import (
    list_royalties_by_creator,
    list_royalties_by_run,
)
from app.storage.skill_assets import get_skill_asset, list_skill_assets


@pytest.fixture
def db_path():
    """裸 DB — init_db 跑完即返回路径，调用者自己决定调哪些 bootstrap 函数。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    # init_db 需要一个 app-like 容器，用 minimal Flask app 满足。
    from flask import Flask
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = path
    init_db(app)
    yield path
    os.unlink(path)


# ---------------------------------------------------------------------------
# bootstrap_demo_cs_asset
# ---------------------------------------------------------------------------

def test_bootstrap_creates_zhang_ai_asset(db_path):
    """注册一份属于 zhang_ai 的客服话术 Agent，字段全对。"""
    asset_id = bootstrap_demo_cs_asset(db_path)
    assert isinstance(asset_id, str) and asset_id

    asset = get_skill_asset(db_path, asset_id)
    assert asset is not None
    assert asset["name"] == "客服话术生成器"
    assert asset["type"] == "agent"
    assert asset["creator_id"] == "zhang_ai"
    assert asset["price_amount"] == 3000
    assert asset["price_currency"] == "USD"
    assert asset["split_rule"] == {"creator": 7000, "platform": 2000, "tax": 1000}
    assert len(asset["content_hash"]) == 64


def test_bootstrap_cs_asset_is_idempotent(db_path):
    """二次调用复用同一份资产；list_skill_assets 仍只有 1 条。"""
    a1 = bootstrap_demo_cs_asset(db_path)
    a2 = bootstrap_demo_cs_asset(db_path)
    assert a1 == a2
    assert len(list_skill_assets(db_path)) == 1


# ---------------------------------------------------------------------------
# bootstrap_demo_runs
# ---------------------------------------------------------------------------

def test_bootstrap_runs_creates_settled_and_accrued(db_path):
    """li_boss 名下产生一条 settled+tx_hash、一条 accrued；royalty_ledger 6 条。"""
    asset_id = bootstrap_demo_cs_asset(db_path)
    bootstrap_demo_runs(db_path, asset_id)

    runs = list_agent_runs_by_caller(db_path, "li_boss")
    assert len(runs) == 2

    by_task = {r["task_id"]: r for r in runs}
    settled = by_task["demo-cs-task-settled"]
    accrued = by_task["demo-cs-task-accrued"]

    # settled run：状态机走完，tx_hash + method 都带 demo-preset 前缀（不冒充真凭证）
    assert settled["settlement_status"] == "settled"
    assert settled["tx_hash"].startswith("demo-preset-")
    assert settled["settlement_method"] == "demo-preset"
    assert settled["charge_amount"] == 3000  # 1 小时 @ $30

    # accrued run：未结算，无 tx_hash
    assert accrued["settlement_status"] == "accrued"
    assert accrued["tx_hash"] is None
    assert accrued["charge_amount"] == 6000  # 2 小时 @ $30

    # zhang_ai 的 creator ledger 行：两笔（一 settled 一 accrued），份额 7000bp
    creator_rows = list_royalties_by_creator(db_path, "zhang_ai")
    assert len(creator_rows) == 2
    statuses = sorted(r["status"] for r in creator_rows)
    assert statuses == ["accrued", "settled"]
    amounts = sorted(r["amount"] for r in creator_rows)
    # creator 份额: settled 70% of 3000 = 2100, accrued 70% of 6000 = 4200
    assert amounts == [2100, 4200]

    # settled run 的 3 行 ledger 全部翻为 settled（creator/platform/tax 一致）
    settled_ledger = list_royalties_by_run(db_path, settled["run_id"])
    assert len(settled_ledger) == 3
    assert all(row["status"] == "settled" for row in settled_ledger)
    parties = sorted(row["party"] for row in settled_ledger)
    assert parties == ["creator", "platform", "tax"]

    # accrued run 的 3 行 ledger 全部 accrued
    accrued_ledger = list_royalties_by_run(db_path, accrued["run_id"])
    assert len(accrued_ledger) == 3
    assert all(row["status"] == "accrued" for row in accrued_ledger)


def test_bootstrap_runs_is_idempotent(db_path):
    """二次调用不重复插行 — task_id 用固定值，幂等判据明确。"""
    asset_id = bootstrap_demo_cs_asset(db_path)
    bootstrap_demo_runs(db_path, asset_id)
    bootstrap_demo_runs(db_path, asset_id)

    runs = list_agent_runs_by_caller(db_path, "li_boss")
    assert len(runs) == 2  # 仍只有两条，不是四条


# ---------------------------------------------------------------------------
# GET /api/demo/agent
# ---------------------------------------------------------------------------

def test_demo_agent_endpoint_returns_404_when_not_bootstrapped():
    """TESTING=True 路径下 demo bootstrap 不跑，endpoint 返回 404。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        app = create_app(config={
            "TESTING": True,
            "DATABASE_PATH": path,
            "SETTLEMENT_PROVIDER": MockSettlementProvider(),
        })
        with app.test_client() as client:
            resp = client.get("/api/demo/agent")
        assert resp.status_code == 404
    finally:
        os.unlink(path)


def test_demo_agent_endpoint_returns_metadata_when_bootstrapped():
    """显式 TESTING=False 让 demo bootstrap 在 create_app 跑起来，endpoint 返回元数据。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        app = create_app(config={
            "TESTING": False,
            "DATABASE_PATH": path,
            "SETTLEMENT_PROVIDER": MockSettlementProvider(),
        })
        with app.test_client() as client:
            # 切到 li_boss 让 caller_id 一致，避免 fallback 影响
            client.post("/api/demo/identity", json={"identity_id": "li_boss"})
            resp = client.get("/api/demo/agent")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["name"] == DEMO_CS_AGENT["name"]
        assert body["creator_id"] == "zhang_ai"
        assert body["creator_name"] == "张AI"
        assert body["price_per_hour"] == 30.0
        assert body["currency"] == "USD"
        assert body["asset_id"]
        # wallet 至少是 0x 开头的地址样式（占位的本地 Anvil 默认账户）
        assert isinstance(body["wallet"], str) and body["wallet"].startswith("0x")
    finally:
        os.unlink(path)
