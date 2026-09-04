"""
Stage 1 / WP3b — D11a: JDs from the conversational flow reach GET /api/jobs,
and WP5 — analysing is not publishing.

The D11a half (audit risk 8), fixed at the route/agent level so both pipelines
get it:

  * `POST /api/analyze/decide` never wrote `sess["jd_report"]`, while
    `/api/analyze/quick` always did — so `GET /api/jobs`, which reads exactly
    that key off every analysis session, could only ever show JDs produced by
    the demo shortcut, never by a real employer conversation;
  * `design_job` never stamped a `job_id`, so a generated JD could not be
    addressed afterwards by the one route that publishes it.

The WP5 half, from the merge review of that commit: reviving publication turned
`/decide` and `/quick` into an *automatic, unauthenticated* push to the global
`published_jobs` board, bypassing `POST /api/jobs/publish` — the route that
stamps `publisher_id` / `company` / `published_at` and represents the
employer's decision to post. The automatic call is gone from both routes; these
tests pin the new contract in both directions (the JD is analysed and stored,
the board is untouched until someone publishes).

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
        app_module, "decompose_tasks", lambda requirement, **kw: {"tasks": [HUMAN_TASK]}
    )
    monkeypatch.setattr(
        app_module,
        "run_resource_decision",
        lambda tasks, **kw: {"decisions": [human_decision(t["id"], t["name"]) for t in tasks]},
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
            lambda requirement, **kw: {"tasks": [HUMAN_TASK, dict(HUMAN_TASK, id="t2", name="话术沉淀")]},
        )
        monkeypatch.setattr(
            app_module,
            "run_resource_decision",
            lambda tasks, **kw: {"decisions": [human_decision(t["id"], t["name"]) for t in tasks]},
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

    def test_decide_does_not_publish_to_the_global_board(self, client, fake_llm, decide_stubs):
        """WP5: analysing a requirement is not consenting to post the job.

        `/decide` used to push every generated JD straight into
        `published_jobs` — an unauthenticated publication with no
        `publisher_id`, no `company`, no `published_at`, and no way to take it
        back. The board must be exactly as it was.
        """
        before = list(app_module.published_jobs)
        session_id = start_completed_session(client, fake_llm)
        fake_llm.queue(jd_json())

        body = client.post(
            "/api/analyze/decide", json={"session_id": session_id}
        ).get_json()

        assert body["jd_report"]["job_designs"][0]["job_id"], "the JD is still produced"
        assert app_module.published_jobs == before

    def test_the_generated_jd_can_then_be_published_explicitly(
        self, client, fake_llm, decide_stubs
    ):
        """The stamped `job_id` is what makes the explicit route usable."""
        session_id = start_completed_session(client, fake_llm)
        fake_llm.queue(jd_json("客户成功专员"))
        design = client.post(
            "/api/analyze/decide", json={"session_id": session_id}
        ).get_json()["jd_report"]["job_designs"][0]
        job_id = design["job_id"]

        resp = client.post("/api/jobs/publish", json={
            "job_id": job_id,
            "jd": "客户成功专员：处理升级投诉",
            "job_title": design["job_title"],
            "required_skills": design["required_skills"],
            "core_responsibilities": design["core_responsibilities"],
            "work_type": design["work_type"],
            "salary_range": design["salary_range"],
        })
        assert resp.status_code == 200, resp.get_data(as_text=True)

        published = [j for j in app_module.published_jobs if j.get("job_id") == job_id]
        assert len(published) == 1
        assert published[0]["publisher_id"], "the explicit route stamps who published it"
        assert published[0]["company"]
        assert published[0]["published_at"]

        jobs = client.get("/api/jobs").get_json()["jobs"]
        assert [j.get("job_id") for j in jobs].count(job_id) == 1, "listed once, not twice"

    def test_republishing_the_same_job_id_is_rejected(self, client, fake_llm, decide_stubs):
        """Publication is idempotent-by-refusal, and /decide no longer pre-claims the id."""
        session_id = start_completed_session(client, fake_llm)
        fake_llm.queue(jd_json())
        job_id = client.post(
            "/api/analyze/decide", json={"session_id": session_id}
        ).get_json()["jd_report"]["job_designs"][0]["job_id"]

        first = client.post("/api/jobs/publish", json={"job_id": job_id, "jd": "岗位描述"})
        second = client.post("/api/jobs/publish", json={"job_id": job_id, "jd": "岗位描述"})

        assert first.status_code == 200
        assert second.status_code == 409

    def test_a_job_is_listed_once_not_twice(self, client, fake_llm, decide_stubs):
        """It reaches /api/jobs through the session; no duplicate from the board."""
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


# ──────────────────────────────────────────────────────────────────────────────
# /quick: same rule (WP5). The auto-publish there predates D11a — removing it
# is a deliberate behaviour change, not a restoration.
# ──────────────────────────────────────────────────────────────────────────────

class TestQuickDoesNotPublishEither:
    def test_quick_stores_the_report_but_leaves_the_board_alone(
        self, client, fake_llm, decide_stubs
    ):
        before = list(app_module.published_jobs)
        fake_llm.queue(jd_json())

        body = client.post("/api/analyze/quick", json={
            "requirement": REQUIREMENT,
            "original_description": "搭建智能客服系统",
        }).get_json()

        session_id = body["session_id"]
        assert body["jd_report"]["job_count"] == 1
        assert app_module.analysis_sessions[session_id]["jd_report"] == body["jd_report"]
        assert app_module.published_jobs == before


# ──────────────────────────────────────────────────────────────────────────────
# The negative the merge review asked for: a failed report is not a report
# ──────────────────────────────────────────────────────────────────────────────

class TestFailedJdReportIsNotStored:
    def test_decide_does_not_write_jd_report_when_the_design_step_raises(
        self, client, fake_llm, decide_stubs, monkeypatch
    ):
        def _boom(*args, **kwargs):
            raise RuntimeError("job design service is down")

        monkeypatch.setattr(app_module, "generate_jd_report", _boom)
        session_id = start_completed_session(client, fake_llm)

        resp = client.post("/api/analyze/decide", json={"session_id": session_id})

        assert resp.status_code == 500
        assert resp.get_json() == {"error": "analysis failed"}
        assert "jd_report" not in app_module.analysis_sessions[session_id], (
            "a half-finished run must not leave a report behind for GET /api/jobs"
        )
        assert app_module.published_jobs == []

    def test_a_previous_successful_report_is_not_clobbered_by_a_later_failure(
        self, client, fake_llm, decide_stubs, monkeypatch
    ):
        session_id = start_completed_session(client, fake_llm)
        fake_llm.queue(jd_json())
        good = client.post(
            "/api/analyze/decide", json={"session_id": session_id}
        ).get_json()["jd_report"]

        def _boom(*args, **kwargs):
            raise RuntimeError("job design service is down")

        monkeypatch.setattr(app_module, "generate_jd_report", _boom)
        assert client.post(
            "/api/analyze/decide", json={"session_id": session_id}
        ).status_code == 500

        assert app_module.analysis_sessions[session_id]["jd_report"] == good
