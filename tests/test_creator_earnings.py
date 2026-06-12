"""
U5 验收测试：creator earnings 汇总查询 + 收益页路由

- summarize_creator_earnings：按 (currency, chain) 分组，只统计 status='accrued'
- /creator/earnings：creator_id 来自 PHASE1_CREATOR_ID 配置；query param 被忽略（防 IDOR）
"""
import os
import sqlite3
import tempfile

import pytest
from flask import Flask

from app.app import create_app
from app.services.agent_run_recording import record_agent_run
from app.services.skill_registration import register_skill_asset
from app.storage.db import init_db
from app.storage.royalty_ledger import summarize_creator_earnings


# ---------------------------------------------------------------------------
# Fixtures（沿用 test_agent_run_recording.py 的 db_path 风格）
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
    chain: str | None = None,
    name: str = "Test Skill",
) -> str:
    payload = {
        "name": name,
        "description": f"desc for {name}",
        "type": "skill",
        "io_schema": {"input": {"text": "string"}, "output": {"result": "string"}},
        "price_amount": 100,
        "price_currency": currency,
        "split_rule": {"creator": split[0], "platform": split[1]},
    }
    if chain is not None:
        payload["price_chain"] = chain
    return register_skill_asset(db_path, payload, creator_id)["skill_id"]


def _call(db_path: str, asset_id: str, *, charge_amount: int = 100,
          currency: str = "USD", chain: str | None = None) -> None:
    kwargs = {
        "agent_name": "TestAgent",
        "caller_id": "caller_001",
        "task_id": "task_001",
        "asset_id": asset_id,
        "charge_amount": charge_amount,
        "charge_currency": currency,
        "success": True,
    }
    if chain is not None:
        kwargs["charge_chain"] = chain
    record_agent_run(db_path, **kwargs)


def _raw_insert_settled_row(db_path: str, *, creator_id: str, amount: int,
                            currency: str = "USD", chain: str | None = None) -> None:
    """直插一条 status='settled' 的 ledger 行，绕过 service 层（U5 测试用）。

    Phase 1 service 层永远写 'accrued'，所以 'settled' 行只能用 raw SQL 制造。
    Phase 2 / U2: ledger 表有了 payee_id + party NOT NULL 列，raw insert 也得带上。
    """
    import uuid
    from datetime import datetime, timezone
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO royalty_ledger
              (id, run_id, creator_id, payee_id, party, asset_id,
               amount, currency, chain, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                "fake-run-id",
                creator_id,
                creator_id,
                "creator",
                "fake-asset-id",
                amount,
                currency,
                chain,
                "settled",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Storage 层：summarize_creator_earnings
# ---------------------------------------------------------------------------

class TestSummarize:
    def test_empty_ledger(self, db_path):
        result = summarize_creator_earnings(db_path, "user_001")
        assert result == {
            "creator_id": "user_001",
            "call_count": 0,
            "totals_by_currency": [],
        }

    def test_single_currency_multiple_calls(self, db_path):
        asset_id = _register_asset(db_path, split=(7000, 3000))
        for _ in range(3):
            _call(db_path, asset_id, charge_amount=100)
        result = summarize_creator_earnings(db_path, "user_001")
        assert result["creator_id"] == "user_001"
        assert result["call_count"] == 3
        assert result["totals_by_currency"] == [
            {"currency": "USD", "chain": None, "amount": 210},  # 3 * 70
        ]

    def test_multi_currency_grouping(self, db_path):
        usd_asset = _register_asset(db_path, split=(7000, 3000), currency="USD",
                                    name="USD Skill")
        eur_asset = _register_asset(db_path, split=(5000, 5000), currency="EUR",
                                    name="EUR Skill")
        _call(db_path, usd_asset, charge_amount=100, currency="USD")
        _call(db_path, usd_asset, charge_amount=100, currency="USD")
        _call(db_path, eur_asset, charge_amount=80, currency="EUR")

        result = summarize_creator_earnings(db_path, "user_001")
        assert result["call_count"] == 3
        # ORDER BY currency: EUR before USD
        assert result["totals_by_currency"] == [
            {"currency": "EUR", "chain": None, "amount": 40},   # 80 * 50%
            {"currency": "USD", "chain": None, "amount": 140},  # 2 * 70
        ]

    def test_multi_chain_grouping_same_currency(self, db_path):
        nochain = _register_asset(db_path, split=(7000, 3000), currency="USDC",
                                  chain=None, name="USDC no-chain")
        eth = _register_asset(db_path, split=(7000, 3000), currency="USDC",
                              chain="ethereum", name="USDC eth")
        _call(db_path, nochain, charge_amount=100, currency="USDC")
        _call(db_path, eth, charge_amount=100, currency="USDC", chain="ethereum")
        _call(db_path, eth, charge_amount=100, currency="USDC", chain="ethereum")

        result = summarize_creator_earnings(db_path, "user_001")
        assert result["call_count"] == 3
        # NULL chain first (ORDER BY clause), then ethereum
        assert result["totals_by_currency"] == [
            {"currency": "USDC", "chain": None, "amount": 70},
            {"currency": "USDC", "chain": "ethereum", "amount": 140},
        ]

    def test_other_creators_excluded(self, db_path):
        alice_asset = _register_asset(db_path, creator_id="alice",
                                      split=(7000, 3000), name="Alice Skill")
        bob_asset = _register_asset(db_path, creator_id="bob",
                                    split=(7000, 3000), name="Bob Skill")
        _call(db_path, alice_asset, charge_amount=100)
        _call(db_path, bob_asset, charge_amount=100)
        _call(db_path, bob_asset, charge_amount=100)

        alice = summarize_creator_earnings(db_path, "alice")
        bob = summarize_creator_earnings(db_path, "bob")
        assert alice["call_count"] == 1
        assert alice["totals_by_currency"] == [
            {"currency": "USD", "chain": None, "amount": 70},
        ]
        assert bob["call_count"] == 2
        assert bob["totals_by_currency"] == [
            {"currency": "USD", "chain": None, "amount": 140},
        ]

    def test_zero_amount_rows_count_but_dont_sum(self, db_path):
        # split 0/100 → ledger 行写入，amount=0，但 call_count 应包括
        asset_id = _register_asset(db_path, split=(0, 10000))
        _call(db_path, asset_id, charge_amount=100)
        _call(db_path, asset_id, charge_amount=100)

        result = summarize_creator_earnings(db_path, "user_001")
        assert result["call_count"] == 2
        assert result["totals_by_currency"] == [
            {"currency": "USD", "chain": None, "amount": 0},
        ]

    def test_settled_rows_excluded(self, db_path):
        asset_id = _register_asset(db_path, split=(7000, 3000))
        _call(db_path, asset_id, charge_amount=100)  # accrued 70

        # 直插一条 settled 行 —— 不能进入 accrued 累计
        _raw_insert_settled_row(db_path, creator_id="user_001", amount=999)

        result = summarize_creator_earnings(db_path, "user_001")
        assert result["call_count"] == 1
        assert result["totals_by_currency"] == [
            {"currency": "USD", "chain": None, "amount": 70},
        ]


# ---------------------------------------------------------------------------
# 路由层：/creator/earnings
# ---------------------------------------------------------------------------

class TestEarningsRoute:
    def test_default_creator_falls_back_to_phase1_stub(self, client):
        # 不带 creator_id —— 路由应使用 PHASE1_CREATOR_ID 配置值
        stub_id = client.application.config["PHASE1_CREATOR_ID"]
        assert stub_id  # sanity

        resp = client.get("/creator/earnings")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert stub_id in body

    def test_query_param_creator_id_is_ignored(self, client):
        # 防 IDOR 回归（强守卫）：不只检查 creator_id 字符串，更要检查"展示的收益
        # 数据是 stub 的、不是 ghost 的"。给两个 creator 灌入 currency / chain /
        # 金额都不同的可区分数据，请求时挂上 ?creator_id=ghost_user_xyz，断言：
        #   - stub 的金额 / 货币 / call_count 出现在页面上；
        #   - ghost 的金额 / 货币 / chain 完全不出现。
        # 若某天 handler 又读 request.args 并悄悄渲染 ghost 的金额（但仍保留 stub
        # 的 header），仅靠 "stub_id in body" 守不住——这里靠独特数值守。
        db_path = client.application.config["DATABASE_PATH"]
        stub_id = client.application.config["PHASE1_CREATOR_ID"]

        # Stub: USD, 无 chain, 70/30 split, 3 calls × 100 → 3 × 70 = 210 USD accrued
        stub_asset = _register_asset(db_path, creator_id=stub_id,
                                     split=(7000, 3000), currency="USD",
                                     name="Stub Skill")
        for _ in range(3):
            _call(db_path, stub_asset, charge_amount=100, currency="USD")

        # Ghost: EUR + ethereum, 50/50 split, 1 call × 1234 → 617 EUR @ ethereum
        # 选与 stub 完全不同的 currency / chain / 金额位数，泄漏会非常显眼。
        ghost_asset = _register_asset(db_path, creator_id="ghost_user_xyz",
                                      split=(5000, 5000), currency="EUR",
                                      chain="ethereum", name="Ghost Skill")
        _call(db_path, ghost_asset, charge_amount=1234,
              currency="EUR", chain="ethereum")

        resp = client.get("/creator/earnings?creator_id=ghost_user_xyz")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)

        # Positive：页面必须渲染 STUB 的数据
        assert stub_id in body, "stub creator_id missing from page header"
        assert "210" in body, "stub's accrued USD total (210) not rendered"
        assert "ACCRUED USD" in body, "stub's USD label missing"
        # call_count=3 单独 assert "3" 太弱，结合下面 ghost 的全部否定即可：
        # 只要 stub 数据出现 + ghost 数据全不出现，就证明渲染的是 stub。

        # Negative：ghost 的任何可识别 token 都不能泄漏
        assert "ghost_user_xyz" not in body, "ghost creator_id leaked"
        assert "617" not in body, "GHOST'S ACCRUED AMOUNT LEAKED — IDOR regression"
        assert "EUR" not in body, "ghost's currency leaked"
        assert "ethereum" not in body, "ghost's chain leaked"
        assert "ACCRUED EUR" not in body, "ghost's accrued-row label leaked"

    def test_shared_pixel_css_is_served(self, client):
        # 页面通过 url_for('static', filename='css/pixel.css') 引用共享样式 ——
        # 确认 Flask 真的能把它当 static 资源送出去，避免页面默默丢样式。
        resp = client.get("/static/css/pixel.css")
        assert resp.status_code == 200
        assert resp.mimetype == "text/css"
        body = resp.get_data(as_text=True)
        # 几个关键 token / class 必须在 CSS 里出现
        assert "--pixel" in body
        assert ".ledger-row" in body
        assert ".stat" in body
