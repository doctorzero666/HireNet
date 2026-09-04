"""
Stage 1 / WP3b — the `HIRENET_TASK_AGENT` flag and the D6 JD-task fix.

Three things this file pins, all introduced by the route-wiring commit:

  * how the flag resolves (D2): `v1` unless the value is exactly `v2`;
  * that `v2` actually routes to `TaskAnalysisAgent` — traces get written and
    the v1 module-level bindings are NOT called (audit risk 2 in reverse: the
    two paths must not quietly mix);
  * D6 (audit risk 5): `generate_jd_report` uses the decision's own
    `estimated_hours` / `requires_judgment` / `is_recurring` when they are
    there, and falls back to v1's fabricated values when they are not.

The full v2 route characterisation lives in tests/test_analyze_routes_v2.py.
"""
import json

import pytest

import app.agents.job_design as job_design_module
import app.app as app_module
from app.agents.job_design import generate_jd_report
from app.storage.analysis_traces import list_traces


@pytest.fixture(autouse=True)
def _guard_no_real_llm(no_real_llm_client):
    """No test in this module may construct the real OpenAI client."""


# ──────────────────────────────────────────────────────────────────────────────
# D2 — flag resolution
# ──────────────────────────────────────────────────────────────────────────────

class TestFlagResolution:
    def test_unset_is_v1(self, monkeypatch):
        monkeypatch.delenv("HIRENET_TASK_AGENT", raising=False)
        assert app_module._task_agent_version() == "v1"

    @pytest.mark.parametrize("value", ["v2", "V2", " v2 "])
    def test_v2_selects_v2(self, monkeypatch, value):
        monkeypatch.setenv("HIRENET_TASK_AGENT", value)
        assert app_module._task_agent_version() == "v2"

    @pytest.mark.parametrize("value", ["v1", "", "  ", "2", "v3", "true", "yes"])
    def test_anything_else_is_v1(self, monkeypatch, value):
        """Fail safe: an unrecognised value serves the shipped pipeline."""
        monkeypatch.setenv("HIRENET_TASK_AGENT", value)
        assert app_module._task_agent_version() == "v1"

    def test_is_read_per_request_not_at_import(self, monkeypatch):
        monkeypatch.setenv("HIRENET_TASK_AGENT", "v2")
        assert app_module._task_agent_version() == "v2"
        monkeypatch.setenv("HIRENET_TASK_AGENT", "v1")
        assert app_module._task_agent_version() == "v1"


# ──────────────────────────────────────────────────────────────────────────────
# D2 — the flag really switches pipelines
# ──────────────────────────────────────────────────────────────────────────────

REQUIREMENT = {
    "project_name": "电商智能客服系统",
    "core_description": "覆盖售前咨询与售后处理的智能客服系统",
    "tasks_hint": ["搭建知识库"],
    "duration": "ongoing",
    "team_context": "3 人运营团队",
    "urgency": "high",
    "budget_hint": "medium",
}

COMPLETE_RESPONSE = (
    "信息够了。\n[REQUIREMENT_COMPLETE]\n" + json.dumps(REQUIREMENT, ensure_ascii=False)
)


class TestFlagSwitchesPipeline:
    def test_v1_start_stores_a_live_agent_object(self, client, fake_llm, monkeypatch):
        monkeypatch.delenv("HIRENET_TASK_AGENT", raising=False)
        fake_llm.queue("请问是一次性交付还是长期运营？")
        body = client.post("/api/analyze/start", json={"message": "搭建客服系统"}).get_json()
        sess = app_module.analysis_sessions[body["session_id"]]
        assert sess["agent"] is not None
        assert "agent_state" not in sess
        assert "turn_count" not in body

    def test_v2_start_stores_a_serialised_state_dict(self, client, fake_llm, monkeypatch):
        """D4 proven in the real flow: the session holds JSON, not an object."""
        monkeypatch.setenv("HIRENET_TASK_AGENT", "v2")
        fake_llm.queue("请问是一次性交付还是长期运营？")
        body = client.post("/api/analyze/start", json={"message": "搭建客服系统"}).get_json()

        sess = app_module.analysis_sessions[body["session_id"]]
        assert sess["agent"] is None
        assert sess["agent_version"] == "v2"
        assert isinstance(sess["agent_state"], dict)
        # The whole thing survives a JSON round trip — that is the point of D4.
        assert json.loads(json.dumps(sess["agent_state"])) == sess["agent_state"]
        assert body["turn_count"] == 1

    def test_v2_start_writes_one_trace_row(self, client, fake_llm, monkeypatch, app_db_path):
        monkeypatch.setenv("HIRENET_TASK_AGENT", "v2")
        fake_llm.queue("请问是一次性交付还是长期运营？")
        body = client.post("/api/analyze/start", json={"message": "搭建客服系统"}).get_json()

        rows = list_traces(app_db_path, body["session_id"])
        assert len(rows) == 1
        assert rows[0]["stage"] == "clarify"
        assert rows[0]["step_no"] == 0
        assert "搭建客服系统" in rows[0]["prompt_json"]

    def test_v1_writes_no_traces_at_all(self, client, fake_llm, monkeypatch, app_db_path):
        monkeypatch.delenv("HIRENET_TASK_AGENT", raising=False)
        fake_llm.queue("请问是一次性交付还是长期运营？")
        body = client.post("/api/analyze/start", json={"message": "搭建客服系统"}).get_json()
        assert list_traces(app_db_path, body["session_id"]) == []

    def test_v2_quick_does_not_call_the_v1_module_bindings(
        self, client, fake_llm, monkeypatch
    ):
        """The two paths must never mix — audit §7.4 / risk 2."""
        monkeypatch.setenv("HIRENET_TASK_AGENT", "v2")
        called = []
        monkeypatch.setattr(
            app_module, "decompose_tasks", lambda *a, **k: called.append("decompose")
        )
        monkeypatch.setattr(
            app_module, "run_resource_decision", lambda *a, **k: called.append("decide")
        )
        # One task, routed to an agent → no JD, no billing, no design_job call.
        fake_llm.queue(
            json.dumps({"tasks": [{
                "id": "t1", "name": "对接工单系统", "description": "同步客服对话",
                "type": "technical", "estimated_hours": 16,
                "requires_judgment": False, "is_recurring": False,
            }]}, ensure_ascii=False),
            json.dumps({"can_complete": True, "confidence": 0.9, "reason": "匹配"}),
            json.dumps({"can_complete": True, "confidence": 0.4, "reason": "一般"}),
        )
        resp = client.post("/api/analyze/quick", json={"requirement": REQUIREMENT})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert called == []
        assert resp.get_json()["decisions"]["decisions"][0]["recommendation"]["decision"] == "agent"


# ──────────────────────────────────────────────────────────────────────────────
# D6 — generate_jd_report reads the decision's task fields when they exist
# ──────────────────────────────────────────────────────────────────────────────

V1_DECISION = {
    "task_id": "t1",
    "task_name": "复杂投诉处理",
    "task_type": "operational",
    "task_description": "处理需要判断力的升级投诉",
    "evaluations": [],
    "recommendation": {"decision": "human", "reason": "r", "cost_hint": "c"},
}

CANNED_JD = {
    "job_title": "客户成功专员",
    "core_responsibilities": ["处理升级投诉"],
    "required_skills": ["沟通"],
    "nice_to_have_skills": [],
    "experience_range": {"min": 1, "max": 3, "unit": "年"},
    "salary_range": {"min": 12000, "max": 18000, "unit": "元/月"},
    "work_type": "full-time",
    "water_score": 82,
}


@pytest.fixture
def captured_tasks(monkeypatch):
    """Capture the task dict generate_jd_report hands to design_job."""
    seen = []

    def _design_job(requirement, task, original_description=""):
        seen.append(task)
        return dict(CANNED_JD)

    monkeypatch.setattr(job_design_module, "design_job", _design_job)
    return seen


class TestJdTaskFields:
    def test_v1_decision_still_gets_the_fabricated_defaults(self, captured_tasks):
        """No new keys on the decision → byte-identical v1 behaviour."""
        generate_jd_report(
            {"decisions": [V1_DECISION]},
            {"project_name": "P", "core_description": "D", "duration": "ongoing"},
            original_description="raw",
        )
        task = captured_tasks[0]
        assert task["estimated_hours"] == 40
        assert task["requires_judgment"] is True
        assert task["is_recurring"] is True  # duration == "ongoing"

    def test_v1_non_ongoing_duration_still_yields_is_recurring_false(self, captured_tasks):
        generate_jd_report(
            {"decisions": [V1_DECISION]},
            {"project_name": "P", "core_description": "D", "duration": "one-time"},
            original_description="raw",
        )
        assert captured_tasks[0]["is_recurring"] is False

    def test_v2_decision_fields_win_over_the_fabrication(self, captured_tasks):
        decision = dict(V1_DECISION, estimated_hours=12, requires_judgment=False,
                        is_recurring=False)
        generate_jd_report(
            {"decisions": [decision]},
            # duration says "ongoing" — the decision says otherwise and wins.
            {"project_name": "P", "core_description": "D", "duration": "ongoing"},
            original_description="raw",
        )
        task = captured_tasks[0]
        assert task["estimated_hours"] == 12
        assert task["requires_judgment"] is False
        assert task["is_recurring"] is False

    def test_falsy_values_are_not_treated_as_absent(self, captured_tasks):
        """`0` hours is a real answer; a truthiness test would overwrite it with 40."""
        decision = dict(V1_DECISION, estimated_hours=0)
        generate_jd_report(
            {"decisions": [decision]},
            {"project_name": "P", "core_description": "D", "duration": "unknown"},
            original_description="raw",
        )
        assert captured_tasks[0]["estimated_hours"] == 0

    def test_partial_fields_mix_real_and_fabricated(self, captured_tasks):
        decision = dict(V1_DECISION, estimated_hours=6)
        generate_jd_report(
            {"decisions": [decision]},
            {"project_name": "P", "core_description": "D", "duration": "one-time"},
            original_description="raw",
        )
        task = captured_tasks[0]
        assert task["estimated_hours"] == 6
        assert task["requires_judgment"] is True     # absent → v1 default
        assert task["is_recurring"] is False          # absent → duration-derived

    def test_task_description_is_carried_through(self, captured_tasks):
        generate_jd_report(
            {"decisions": [V1_DECISION]},
            {"project_name": "P", "core_description": "D", "duration": "ongoing"},
            original_description="raw",
        )
        assert captured_tasks[0]["description"] == "处理需要判断力的升级投诉"
