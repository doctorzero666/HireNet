"""
U6 / Phase 1 端到端验收测试。

证明 docs/phase-1-spec.md §1 的唯一硬判据，经【真实雇主端点 POST /api/analyze/quick】触发：

    注册 1 个 SkillAsset（creator = PHASE1_CREATOR_ID）
        → 触发 1 次会用到它的雇主任务（真实 HTTP 端点）
            → royalty_ledger 出现一条 amount/currency/creator_id/status='accrued' 全对的记录。

只 stub 三个 LLM 外部边界（decompose_tasks / run_resource_decision / design_job）。
注册、路由接线、U4 打点、SQLite 账本全部走真实代码——证明的是整条真实路径，不是手搓复制品。
"""
import os
import tempfile

import pytest

import app.app as app_module
import app.agents.job_design as job_design_module
from app.app import create_app
from app.services.asset_bootstrap import JOB_DESIGN_ASSET, bootstrap_job_design_asset
from app.services.skill_registration import register_skill_asset
from app.storage.agent_runs import list_agent_runs_by_caller
from app.storage.royalty_ledger import list_royalties_by_creator, summarize_creator_earnings
from app.storage.skill_assets import get_skill_asset, list_skill_assets

CALLER_ID = "phase1_stub_employer"  # create_app 默认 PHASE1_CALLER_ID

CREATOR_ID = "phase1_stub_creator"  # create_app 默认 PHASE1_CREATOR_ID


@pytest.fixture
def app_and_db():
    """起一个用临时库的 app（create_app 内会自动 bootstrap 第一个资产），同时暴露 db_path 以便直接查账本。"""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    flask_app = create_app(config={"TESTING": True, "DATABASE_PATH": db_path})
    with flask_app.test_client() as client:
        yield client, db_path, flask_app
    os.unlink(db_path)


# ---------------------------------------------------------------------------
# Stubs：只替换三个 LLM 边界，其余真实
# ---------------------------------------------------------------------------

_CANNED_JOB_DESIGN = {
    "job_title": "后端工程师",
    "core_responsibilities": ["设计 API", "维护数据库"],
    "required_skills": ["Python", "SQL"],
    "nice_to_have_skills": ["Flask"],
    "experience_range": {"min": 1, "max": 3, "unit": "年"},
    "salary_range": {"min": 15000, "max": 25000, "unit": "元/月"},
    "work_type": "full-time",
    "water_score": 80,
}


def _stub_decompose_tasks(requirement):
    return {"tasks": [{"id": "t1", "name": "搭建后端", "type": "engineering"}]}


def _human_decision(task_id, name):
    return {
        "task_id": task_id,
        "task_name": name,
        "task_type": "engineering",
        "task_description": "搭建并维护后端服务",
        "recommendation": {"decision": "human"},
    }


def _stub_run_resource_decision(tasks):
    # 一个需要人来做的任务 → generate_jd_report 会真生成 job design 并触发计费
    return {"decisions": [_human_decision("t1", "搭建后端")]}


def _stub_design_job(requirement, task, original_description=""):
    jd = dict(_CANNED_JOB_DESIGN)
    jd["task_id"] = task.get("id")
    jd["task_name"] = task.get("name")
    return jd


@pytest.fixture
def stub_llm(monkeypatch):
    # 路由用的是 app.app 命名空间里的这两个函数引用
    monkeypatch.setattr(app_module, "decompose_tasks", _stub_decompose_tasks)
    monkeypatch.setattr(app_module, "run_resource_decision", _stub_run_resource_decision)
    # design_job 由 generate_jd_report 在 job_design 模块内调用
    monkeypatch.setattr(job_design_module, "design_job", _stub_design_job)


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------

def test_bootstrap_registers_first_asset(app_and_db):
    """create_app 启动即把 Job Design Agent 注册成第一个 SkillAsset，creator = 服务端身份。"""
    _client, db_path, flask_app = app_and_db

    assets = list_skill_assets(db_path)
    assert len(assets) == 1
    asset = assets[0]
    assert asset["name"] == "Job Design Agent"
    assert asset["type"] == "agent"
    assert asset["creator_id"] == CREATOR_ID
    assert len(asset["content_hash"]) == 64
    assert all(c in "0123456789abcdef" for c in asset["content_hash"])
    assert asset["split_rule"] == {"creator": 7000, "platform": 3000}
    # app config 里记下了 bootstrap 出来的 id
    assert flask_app.config["JOB_DESIGN_ASSET_ID"] == asset["id"]


def test_end_to_end_employer_task_records_royalty(app_and_db, stub_llm):
    """端到端硬判据：经真实 POST /api/analyze/quick 触发 → royalty_ledger 出现正确的 creator 行。"""
    client, db_path, _flask_app = app_and_db

    # 触发前账本为空
    assert list_royalties_by_creator(db_path, CREATOR_ID) == []

    resp = client.post(
        "/api/analyze/quick",
        json={
            "requirement": {
                "project_name": "内部工具",
                "core_description": "搭建一个后端服务",
                "duration": "3个月",
            },
            "original_description": "我需要做个后端",
        },
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["jd_report"]["needs_hiring"] is True
    assert body["jd_report"]["job_count"] == 1

    # —— 断言端到端判据：恰一条 creator 行，四项全对 ——
    rows = list_royalties_by_creator(db_path, CREATOR_ID)
    assert len(rows) == 1
    row = rows[0]
    assert row["amount"] == 100 * 7000 // 10000 == 70  # price_amount=100, creator 7000bps
    assert row["currency"] == "USD"
    assert row["creator_id"] == CREATOR_ID
    assert row["status"] == "accrued"
    assert row["chain"] is None


def test_u5_earnings_reflects_accrued(app_and_db, stub_llm):
    """U5 证明：收益汇总显示该 creator 的 accrued，收益页返回 200。"""
    client, db_path, _flask_app = app_and_db

    resp = client.post(
        "/api/analyze/quick",
        json={"requirement": {"core_description": "搭建后端", "duration": "ongoing"}},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)

    summary = summarize_creator_earnings(db_path, CREATOR_ID)
    assert summary["creator_id"] == CREATOR_ID
    assert summary["call_count"] == 1
    assert summary["totals_by_currency"] == [{"currency": "USD", "chain": None, "amount": 70}]

    page = client.get("/creator/earnings")
    assert page.status_code == 200


def test_two_human_tasks_bill_per_task(app_and_db, stub_llm, monkeypatch):
    """每个 human task 各计一次费（计费在循环内，不是每请求一次）：
    2 个 human task → 2 条 creator 账本行、合计 140、2 条 agent_runs 各 charge 100。"""
    client, db_path, _flask_app = app_and_db

    # 覆盖决策 stub，返回两个 human task
    monkeypatch.setattr(
        app_module,
        "run_resource_decision",
        lambda tasks: {"decisions": [_human_decision("t1", "搭建后端"), _human_decision("t2", "搭建前端")]},
    )

    resp = client.post(
        "/api/analyze/quick",
        json={"requirement": {"core_description": "搭建系统", "duration": "3个月"}},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["jd_report"]["job_count"] == 2

    rows = list_royalties_by_creator(db_path, CREATOR_ID)
    assert len(rows) == 2
    assert all(r["amount"] == 70 and r["status"] == "accrued" for r in rows)
    assert sum(r["amount"] for r in rows) == 140

    runs = list_agent_runs_by_caller(db_path, CALLER_ID)
    assert len(runs) == 2
    assert all(run["charge_amount"] == 100 for run in runs)
    assert all(run["royalty_splits"]["platform"]["amount"] == 30 for run in runs)

    summary = summarize_creator_earnings(db_path, CREATOR_ID)
    assert summary["call_count"] == 2
    assert summary["totals_by_currency"] == [{"currency": "USD", "chain": None, "amount": 140}]


def test_bootstrap_ignores_tampered_duplicate_asset(stub_llm):
    """回归：同 content_hash 但经济条款被篡改（price=999, split 10000/0）的资产，
    重启后 bootstrap 必须忽略它，仍选中 100 / 70-30 的正确资产；U6 计费金额不被篡改。"""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        # 1. 首次启动 → bootstrap 创建原始 Job Design Asset（100 / 70-30）
        app1 = create_app(config={"TESTING": True, "DATABASE_PATH": db_path})
        original_id = app1.config["JOB_DESIGN_ASSET_ID"]
        assets = list_skill_assets(db_path)
        assert len(assets) == 1
        assert assets[0]["price_amount"] == 100
        original_hash = assets[0]["content_hash"]

        # 2. 攻击者手动注册一个同内容、但 price=999 / split=10000-0 的重复资产
        tampered = dict(JOB_DESIGN_ASSET)
        tampered["price_amount"] = 999
        tampered["split_rule"] = {"creator": 10000, "platform": 0}
        tampered_res = register_skill_asset(db_path, tampered, CREATOR_ID)
        tampered_id = tampered_res["skill_id"]
        assert tampered_id != original_id
        # 确认确实撞上同一个 content_hash（content_hash 不含经济条款）
        assert tampered_res["content_hash"] == original_hash

        # 3. 再次 create_app() 模拟重启（list_skill_assets 按 created_at DESC，篡改资产排在前面）
        app2 = create_app(config={"TESTING": True, "DATABASE_PATH": db_path})
        selected_id = app2.config["JOB_DESIGN_ASSET_ID"]

        # 4. 必须仍指向 100 / 70-30 的正确资产，绝不指向 999 / 10000-0
        assert selected_id != tampered_id
        assert selected_id == original_id
        selected = get_skill_asset(db_path, selected_id)
        assert selected["price_amount"] == 100
        assert selected["split_rule"] == {"creator": 7000, "platform": 3000}

        # 5. 经真实 POST /api/analyze/quick 跑一次 U6 闭环 → 计费仍 70 / charge 100 / platform 30
        with app2.test_client() as client:
            resp = client.post(
                "/api/analyze/quick",
                json={"requirement": {"core_description": "搭建后端", "duration": "3个月"}},
            )
            assert resp.status_code == 200, resp.get_data(as_text=True)

        rows = list_royalties_by_creator(db_path, CREATOR_ID)
        assert len(rows) == 1
        assert rows[0]["amount"] == 70  # 不是被篡改的 100/999
        assert rows[0]["status"] == "accrued"

        runs = list_agent_runs_by_caller(db_path, CALLER_ID)
        assert len(runs) == 1
        assert runs[0]["charge_amount"] == 100  # 不是 999
        assert runs[0]["royalty_splits"]["platform"]["amount"] == 30  # platform 份额仍在 JSON
    finally:
        os.unlink(db_path)


def test_bootstrap_is_idempotent(app_and_db):
    """重复 bootstrap 不新增资产（同 content_hash 复用）——重启不会重复建。"""
    _client, db_path, _flask_app = app_and_db

    before = list_skill_assets(db_path)
    assert len(before) == 1

    again_id = bootstrap_job_design_asset(db_path, CREATOR_ID)
    after = list_skill_assets(db_path)
    assert len(after) == 1
    assert again_id == before[0]["id"]
