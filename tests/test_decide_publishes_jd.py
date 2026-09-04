"""
Stage 1 / WP3b — D11a: JDs from the conversational flow reach GET /api/jobs.

Two halves of one bug (audit risk 8), fixed at the route/agent level so both
the v1 and v2 pipelines get it:

  * `POST /api/analyze/decide` never wrote `sess["jd_report"]`, while
    `/api/analyze/quick` always did — so `GET /api/jobs`, which reads exactly
    that key off every analysis session, could only ever show JDs produced by
    the demo shortcut, never by a real employer conversation;
  * `_publish_jobs` filters on `job.get("job_id")` and `design_job` never set
    one, so the global publish pool was unreachable from the analysis flow —
    dead code guarding a hole.

These tests drive the REAL `design_job` against the scripted fake client
(rather than stubbing it, as the other analysis test files do) because the
`job_id` stamp is the thing under test.
"""
import json

import pytest

import app.app as app_module
from app.agents.job_design import design_job

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

HUMAN_TASK = {
    "id": "t1",
    "name": "复杂投诉处理",
    "description": "处理需要判断力的升级投诉",
    "type": "operational",
    "estimated_hours": 40,
    "requires_judgment": True,
    "is_recurring": True,
}


def jd_json(job_title="客户成功专员"):
    return json.dumps({
        "job_title": job_title,
        "core_responsibilities": ["处理升级投诉"],
        "required_skills": ["沟通"],
        "nice_to_have_skills": [],
        "experience_range": {"min": 1, "max": 3, "unit": "年"},
        "salary_range": {"min": 12000, "max": 18000, "unit": "元/月"},
        "work_type": "full-time",
        "water_score": 82,
    }, ensure_ascii=False)


def human_decision(task_id, name):
    return {
        "task_id": task_id,
        "task_name": name,
        "task_type": "operational",
        "task_description": "处理需要判断力的升级投诉",
        "evaluations": [],
        "recommendation": {"decision": "human", "reason": "需要人", "cost_hint": "需要评估薪资"},
    }


@pytest.fixture(autouse=True)
def _guard_no_real_llm(no_real_llm_client):
    """No test in this module may construct the real OpenAI client."""


@pytest.fixture(autouse=True)
def _pin_v1(monkeypatch):
    """These are route-level assertions; pin the pipeline so both runs agree.

    Individual tests override this with `monkeypatch.setenv(..., "v2")`.
    """
    monkeypatch.setenv("HIRENET_TASK_AGENT", "v1")


@pytest.fixture
def decide_stubs(monkeypatch):
    """Stub only the two decomposition/routing boundaries; design_job is real."""
    monkeypatch.setattr(
        app_module, "decompose_tasks", lambda requirement: {"tasks": [HUMAN_TASK]}
    )
    monkeypatch.setattr(
        app_module,
        "run_resource_decision",
        lambda tasks: {"decisions": [human_decision(t["id"], t["name"]) for t in tasks]},
    )


def start_completed_session(client, fake_llm):
    fake_llm.queue(COMPLETE_RESPONSE)
    body = client.post("/api/analyze/start", json={"message": "搭建智能客服系统"}).get_json()
    assert body["is_complete"] is True, body
    return body["session_id"]


# ──────────────────────────────────────────────────────────────────────────────
# design_job stamps a job_id
# ──────────────────────────────────────────────────────────────────────────────

class TestDesignJobStampsJobId:
    def test_job_id_is_present(self, fake_llm):
        fake_llm.queue(jd_json())
        jd = design_job(REQUIREMENT, HUMAN_TASK, "原始描述")
        assert isinstance(jd["job_id"], str) and jd["job_id"]
        # task_id / task_name keep their existing meaning alongside it.
        assert jd["task_id"] == "t1"
        assert jd["task_name"] == "复杂投诉处理"

    def test_job_ids_are_unique_across_designs(self, fake_llm):
        fake_llm.queue(jd_json(), jd_json())
        first = design_job(REQUIREMENT, HUMAN_TASK, "")
        second = design_job(REQUIREMENT, HUMAN_TASK, "")
        assert first["job_id"] != second["job_id"]

    def test_job_id_is_not_the_task_id(self, fake_llm):
        """Two employers both decompose to "t1"; the dedupe key must not collide."""
        fake_llm.queue(jd_json())
        jd = design_job(REQUIREMENT, HUMAN_TASK, "")
        assert jd["job_id"] != jd["task_id"]


# ──────────────────────────────────────────────────────────────────────────────
# /decide persists jd_report and the JD reaches /api/jobs
# ──────────────────────────────────────────────────────────────────────────────

class TestDecidePersistsJdReport:
    def test_session_holds_the_jd_report_after_decide(self, client, fake_llm, decide_stubs):
        session_id = start_completed_session(client, fake_llm)
        fake_llm.queue(jd_json())
        resp = client.post("/api/analyze/decide", json={"session_id": session_id})
        assert resp.status_code == 200, resp.get_data(as_text=True)

        stored = app_module.analysis_sessions[session_id]["jd_report"]
        assert stored == resp.get_json()["jd_report"]
        assert stored["job_count"] == 1

    def test_generated_jd_is_listed_by_api_jobs(self, client, fake_llm, decide_stubs):
        session_id = start_completed_session(client, fake_llm)
        fake_llm.queue(jd_json("客户成功专员"))
        body = client.post(
            "/api/analyze/decide", json={"session_id": session_id}
        ).get_json()
        job_id = body["jd_report"]["job_designs"][0]["job_id"]

        jobs = client.get("/api/jobs").get_json()["jobs"]
        listed = [j for j in jobs if j.get("job_id") == job_id]
        assert len(listed) == 1, [j.get("job_id") for j in jobs]
        assert listed[0]["job_title"] == "客户成功专员"

    def test_two_human_tasks_produce_two_distinct_listed_jobs(
        self, client, fake_llm, monkeypatch
    ):
        monkeypatch.setattr(
            app_module,
            "decompose_tasks",
            lambda requirement: {"tasks": [HUMAN_TASK, dict(HUMAN_TASK, id="t2", name="话术沉淀")]},
        )
        monkeypatch.setattr(
            app_module,
            "run_resource_decision",
            lambda tasks: {"decisions": [human_decision(t["id"], t["name"]) for t in tasks]},
        )
        session_id = start_completed_session(client, fake_llm)
        fake_llm.queue(jd_json("客户成功专员"), jd_json("客服内容运营"))
        body = client.post(
            "/api/analyze/decide", json={"session_id": session_id}
        ).get_json()

        designs = body["jd_report"]["job_designs"]
        assert len(designs) == 2
        job_ids = [d["job_id"] for d in designs]
        assert len(set(job_ids)) == 2

        jobs = client.get("/api/jobs").get_json()["jobs"]
        listed = [j.get("job_id") for j in jobs if j.get("job_id") in job_ids]
        assert sorted(listed) == sorted(job_ids)

    def test_published_pool_is_no_longer_bypassed(self, client, fake_llm, decide_stubs):
        """`_publish_jobs` was dead: it filtered on a job_id nothing produced."""
        session_id = start_completed_session(client, fake_llm)
        fake_llm.queue(jd_json())
        body = client.post(
            "/api/analyze/decide", json={"session_id": session_id}
        ).get_json()
        job_id = body["jd_report"]["job_designs"][0]["job_id"]
        assert job_id in {j.get("job_id") for j in app_module.published_jobs}

    def test_a_job_is_listed_once_not_twice(self, client, fake_llm, decide_stubs):
        """It reaches /api/jobs through the session AND the pool; dedupe holds."""
        session_id = start_completed_session(client, fake_llm)
        fake_llm.queue(jd_json())
        body = client.post(
            "/api/analyze/decide", json={"session_id": session_id}
        ).get_json()
        job_id = body["jd_report"]["job_designs"][0]["job_id"]

        jobs = client.get("/api/jobs").get_json()["jobs"]
        assert [j.get("job_id") for j in jobs].count(job_id) == 1


class TestDecidePersistsJdReportOnV2:
    """Same route-level fix, v2 pipeline (the decisions come from the agent)."""

    def test_session_holds_the_jd_report_and_api_jobs_lists_it(
        self, client, fake_llm, monkeypatch
    ):
        monkeypatch.setenv("HIRENET_TASK_AGENT", "v2")

        fake_llm.queue(COMPLETE_RESPONSE)
        session_id = client.post(
            "/api/analyze/start", json={"message": "搭建智能客服系统"}
        ).get_json()["session_id"]

        # decompose → one recurring operational task → shortlist is exactly
        # [agent_content, agent_data, candidate_a], so three evaluations, then
        # one design_job call. The queue length is the assertion: an extra
        # entry would be silently consumed by the next stage.
        fake_llm.queue(
            json.dumps({"tasks": [HUMAN_TASK]}, ensure_ascii=False),
            json.dumps({"can_complete": False, "confidence": 0.2, "reason": "判断力不足"}),
            json.dumps({"can_complete": False, "confidence": 0.1, "reason": "不匹配"}),
            json.dumps({"can_complete": True, "confidence": 0.85, "reason": "有客服经验"}),
            jd_json("客户成功专员"),
        )
        resp = client.post("/api/analyze/decide", json={"session_id": session_id})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert fake_llm.responses == [], "the scripted queue must be consumed exactly"

        assert body["jd_report"]["job_count"] == 1
        assert body["jd_report"]["job_designs"][0]["job_title"] == "客户成功专员"
        assert body["decisions"]["decisions"][0]["recommendation"]["decision"] == "human"
        stored = app_module.analysis_sessions[session_id]["jd_report"]
        assert stored == body["jd_report"]

        job_id = body["jd_report"]["job_designs"][0]["job_id"]
        jobs = client.get("/api/jobs").get_json()["jobs"]
        assert [j.get("job_id") for j in jobs].count(job_id) == 1
