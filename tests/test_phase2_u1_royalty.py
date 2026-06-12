"""
Phase 2 / U1 验收测试：3-way split + royalty APIs + settlement

覆盖：
- split_rule 加 tax 字段（schema + validator + agent_run_recording）
- 旧 2-way split（无 tax）→ 行为不变（tax_amt=0，platform 吸收余数）
- GET /api/royalty/split?run_id=
- GET /api/royalty/list?session_id=
- POST /api/royalty/settle  body={"run_id":...}
- GET /api/creator/earnings → JSON
"""
import os
import tempfile

import pytest
from flask import Flask

from app.app import create_app
from app.services.agent_run_recording import record_agent_run
from app.services.skill_registration import register_skill_asset
from app.services.validation import validate_split_rule
from app.storage.db import init_db
from app.storage.royalty_ledger import list_royalties_by_creator


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
    creator_id: str = "user_001",
    split: dict | None = None,
    currency: str = "USD",
    name: str = "Test Skill",
) -> str:
    payload = {
        "name": name,
        "description": f"desc for {name}",
        "type": "skill",
        "io_schema": {"input": {"text": "string"}, "output": {"result": "string"}},
        "price_amount": 100,
        "price_currency": currency,
        "split_rule": split or {"creator": 7000, "platform": 3000},
    }
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
# validate_split_rule with tax
# ---------------------------------------------------------------------------

class TestSplitRuleValidator:
    def test_three_way_sums_to_10000_passes(self):
        validate_split_rule({"creator": 7000, "platform": 2000, "tax": 1000})

    def test_two_way_legacy_still_passes(self):
        # 向后兼容：tax 缺失视为 0
        validate_split_rule({"creator": 7000, "platform": 3000})

    def test_three_way_sum_off_by_one_rejected(self):
        with pytest.raises(ValueError, match="must sum to 10000"):
            validate_split_rule({"creator": 7000, "platform": 2000, "tax": 999})

    def test_tax_only_split_must_still_sum(self):
        with pytest.raises(ValueError, match="must sum to 10000"):
            validate_split_rule({"creator": 0, "platform": 0, "tax": 9999})

    def test_explicit_tax_zero_equivalent_to_missing(self):
        validate_split_rule({"creator": 7000, "platform": 3000, "tax": 0})


# ---------------------------------------------------------------------------
# 3-way split in record_agent_run
# ---------------------------------------------------------------------------

class TestThreeWaySplit:
    def test_70_20_10(self, db_path):
        asset_id = _register_asset(
            db_path, split={"creator": 7000, "platform": 2000, "tax": 1000}
        )
        result = _call(db_path, asset_id, charge_amount=100)
        s = result["royalty_splits"]
        assert s["creator"]["amount"] == 70
        assert s["tax"]["amount"] == 10
        assert s["platform"]["amount"] == 20

    def test_sum_invariant_holds_with_tax(self, db_path):
        # charge=7, 5000/3000/2000 → creator=3, tax=1, platform=7-3-1=3
        asset_id = _register_asset(
            db_path, split={"creator": 5000, "platform": 3000, "tax": 2000}
        )
        r = _call(db_path, asset_id, charge_amount=7)
        s = r["royalty_splits"]
        assert s["creator"]["amount"] + s["tax"]["amount"] + s["platform"]["amount"] == 7

    @pytest.mark.parametrize("charge,split", [
        (0, {"creator": 7000, "platform": 2000, "tax": 1000}),
        (1, {"creator": 7000, "platform": 2000, "tax": 1000}),
        (1, {"creator": 3000, "platform": 5000, "tax": 2000}),
        (7, {"creator": 5000, "platform": 3000, "tax": 2000}),
        (100, {"creator": 7000, "platform": 2000, "tax": 1000}),
        (100, {"creator": 0, "platform": 5000, "tax": 5000}),
        (999, {"creator": 1234, "platform": 7766, "tax": 1000}),
        (1_000_001, {"creator": 5000, "platform": 3000, "tax": 2000}),
    ])
    def test_three_way_sum_invariant(self, db_path, charge, split):
        asset_id = _register_asset(db_path, split=split)
        r = _call(db_path, asset_id, charge_amount=charge)
        s = r["royalty_splits"]
        c, t, p = s["creator"]["amount"], s["tax"]["amount"], s["platform"]["amount"]
        assert c >= 0 and t >= 0 and p >= 0
        assert c + t + p == charge, f"3-way split must sum to charge for {split} @ {charge}"

    def test_legacy_two_way_identical_to_phase1(self, db_path):
        # 关键回归：旧 2-way split 必须产出和 Phase 1 一致的数字。
        # tax_amt 必须为 0；platform 必须吸收余数；creator 行为不变。
        asset_id = _register_asset(
            db_path, split={"creator": 7000, "platform": 3000}
        )
        r = _call(db_path, asset_id, charge_amount=100)
        s = r["royalty_splits"]
        assert s["creator"]["amount"] == 70
        assert s["platform"]["amount"] == 30
        assert s["tax"]["amount"] == 0

    def test_list_royalties_by_creator_returns_only_creator_party(self, db_path):
        # Phase 2 / U2: ledger now holds 3 rows per run (creator/platform/tax),
        # but list_royalties_by_creator filters party='creator' so a creator's
        # query returns only their own row — never the platform or tax shares.
        asset_id = _register_asset(
            db_path, split={"creator": 7000, "platform": 2000, "tax": 1000}
        )
        r = _call(db_path, asset_id, charge_amount=100)
        rows = list_royalties_by_creator(db_path, "user_001")
        assert len(rows) == 1
        assert rows[0]["amount"] == 70  # creator only, never tax / platform
        assert rows[0]["run_id"] == r["run_id"]
        assert rows[0]["party"] == "creator"


# ---------------------------------------------------------------------------
# GET /api/royalty/split
# ---------------------------------------------------------------------------

class TestRoyaltySplitRoute:
    def _register_and_call(self, client, *, split=None, charge=100):
        db_path = client.application.config["DATABASE_PATH"]
        creator_id = client.application.config["PHASE1_CREATOR_ID"]
        asset_id = _register_asset(
            db_path, creator_id=creator_id,
            split=split or {"creator": 7000, "platform": 2000, "tax": 1000},
            name="Split Route Skill",
        )
        result = _call(db_path, asset_id, charge_amount=charge)
        return result["run_id"]

    def test_returns_three_way_split(self, client):
        run_id = self._register_and_call(client, charge=100)
        resp = client.get(f"/api/royalty/split?run_id={run_id}")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["run_id"] == run_id
        assert body["charge_amount"] == 100
        assert body["charge_currency"] == "USD"
        assert body["royalty_splits"]["creator"]["amount"] == 70
        assert body["royalty_splits"]["platform"]["amount"] == 20
        assert body["royalty_splits"]["tax"]["amount"] == 10
        assert body["settlement_status"] == "accrued"

    def test_missing_run_id_400(self, client):
        resp = client.get("/api/royalty/split")
        assert resp.status_code == 400
        assert "run_id" in resp.get_json()["error"]

    def test_unknown_run_id_404(self, client):
        resp = client.get("/api/royalty/split?run_id=nonexistent-uuid")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/royalty/list
# ---------------------------------------------------------------------------

class TestRoyaltyListRoute:
    def test_missing_session_id_400(self, client):
        resp = client.get("/api/royalty/list")
        assert resp.status_code == 400

    def test_returns_empty_entries_for_unknown_session(self, client):
        # Phase 2 / U1: sessions don't track runs yet —— shape 必须稳定，entries 为空。
        resp = client.get("/api/royalty/list?session_id=session_xyz")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["session_id"] == "session_xyz"
        assert body["entries"] == []


# ---------------------------------------------------------------------------
# POST /api/royalty/settle
# ---------------------------------------------------------------------------

class TestRoyaltySettleRoute:
    def _make_run(self, client):
        db_path = client.application.config["DATABASE_PATH"]
        creator_id = client.application.config["PHASE1_CREATOR_ID"]
        asset_id = _register_asset(
            db_path, creator_id=creator_id,
            split={"creator": 7000, "platform": 2000, "tax": 1000},
            name="Settle Skill",
        )
        return _call(db_path, asset_id, charge_amount=100)["run_id"]

    def test_settle_flips_status_to_settled(self, client):
        run_id = self._make_run(client)
        resp = client.post("/api/royalty/settle", json={"run_id": run_id})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["run_id"] == run_id
        # Phase 2 / U2: each run has 3 ledger rows (creator / platform / tax)
        # and settle flips all 3 in lockstep.
        assert body["settled_count"] == 3
        assert body["status"] == "settled"
        # Phase 3 / U1: settle now goes through a SettlementProvider; the Mock
        # provider returns a "mock-<hex>" tx_hash that the route persists onto
        # agent_runs and echoes back in the response.
        assert body.get("tx_hash", "").startswith("mock-")

        from app.storage.royalty_ledger import list_royalties_by_creator
        creator_id = client.application.config["PHASE1_CREATOR_ID"]
        rows = list_royalties_by_creator(
            client.application.config["DATABASE_PATH"], creator_id,
        )
        assert any(r["run_id"] == run_id and r["status"] == "settled" for r in rows)

    def test_settle_is_idempotent(self, client):
        run_id = self._make_run(client)
        first = client.post("/api/royalty/settle", json={"run_id": run_id}).get_json()
        second = client.post("/api/royalty/settle", json={"run_id": run_id}).get_json()
        # First call settles all 3 rows (creator / platform / tax) atomically.
        assert first["settled_count"] == 3
        # 第二次调用：行已是 settled，filter 命中 0 行，但仍返回 settled 状态
        assert second["settled_count"] == 0
        assert second["status"] == "settled"

    def test_missing_body_400(self, client):
        resp = client.post("/api/royalty/settle", json={})
        assert resp.status_code == 400

    def test_unknown_run_id_404(self, client):
        resp = client.post("/api/royalty/settle", json={"run_id": "nope-uuid"})
        assert resp.status_code == 404

    def test_empty_body_no_json_415(self, client):
        # No body + no Content-Type now hits the new Content-Type guard, so
        # the response is 415 instead of the old 400. (A request that
        # advertises Content-Type: application/json with an empty body still
        # falls through to the 'run_id required' 400 — see test below.)
        resp = client.post("/api/royalty/settle")
        assert resp.status_code == 415
        assert "Content-Type" in resp.get_json()["error"]

    def test_non_dict_array_body_400_not_500(self, client):
        # Regression: a JSON array body used to trip .get() with AttributeError → 500.
        resp = client.post(
            "/api/royalty/settle",
            data="[1]",
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "JSON object" in resp.get_json()["error"]

    def test_non_dict_string_body_400_not_500(self, client):
        # Regression: a JSON string body used to trip .get() with AttributeError → 500.
        resp = client.post(
            "/api/royalty/settle",
            data='"x"',
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "JSON object" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
# GET /api/creator/earnings  (JSON sibling of /creator/earnings)
# ---------------------------------------------------------------------------

class TestCreatorEarningsJSONRoute:
    def test_returns_json_summary(self, client):
        db_path = client.application.config["DATABASE_PATH"]
        creator_id = client.application.config["PHASE1_CREATOR_ID"]
        asset_id = _register_asset(
            db_path, creator_id=creator_id,
            split={"creator": 7000, "platform": 2000, "tax": 1000},
            name="JSON Earnings Skill",
        )
        for _ in range(2):
            _call(db_path, asset_id, charge_amount=100)

        resp = client.get("/api/creator/earnings")
        assert resp.status_code == 200
        assert resp.mimetype == "application/json"
        body = resp.get_json()
        assert body["creator_id"] == creator_id
        assert body["call_count"] == 2
        assert body["totals_by_currency"] == [
            {"currency": "USD", "chain": None, "amount": 140},
        ]

    def test_query_param_creator_id_is_ignored(self, client):
        # IDOR 回归：API 也必须忽略 query param 里的 creator_id。
        db_path = client.application.config["DATABASE_PATH"]
        stub_id = client.application.config["PHASE1_CREATOR_ID"]
        ghost_asset = _register_asset(
            db_path, creator_id="ghost_user_xyz",
            split={"creator": 7000, "platform": 2000, "tax": 1000},
            currency="EUR", name="Ghost JSON Skill",
        )
        _call(db_path, ghost_asset, charge_amount=1234, currency="EUR")

        resp = client.get("/api/creator/earnings?creator_id=ghost_user_xyz")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["creator_id"] == stub_id
        assert body["call_count"] == 0
        assert body["totals_by_currency"] == []
