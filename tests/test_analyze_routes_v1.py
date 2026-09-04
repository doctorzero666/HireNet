"""
Stage 1 / WP2 — characterisation tests for the four analysis routes.

These tests PIN CURRENT BEHAVIOUR of the v1 pipeline
(`POST /api/analyze/{start,reply,decide,quick}`) so the TaskAnalysisAgent
refactor has a safety net. Before this file the conversational path
(`/start` → `/reply` → `/decide`) had ZERO automated coverage: the only
existing e2e file drives `/quick` and stubs out the two functions the
refactor is about to rewrite (audit §10).

Read this as a contract, not as an endorsement. Two assertions below pin
behaviour that is arguably wrong and is deliberately NOT fixed here:

  * a malformed JSON body after the `[REQUIREMENT_COMPLETE]` marker is
    swallowed into `is_complete: False` (app/app.py:178-179, :210-211), so
    the conversation silently continues while the user sees the raw broken
    text in `response`;
  * a pipeline failure returns `{"error": str(e)}`, leaking the exception
    text to the client (app/app.py:277, :1267).

The second one is fixed in a later commit in this work package; when that
lands, the tests here get *stronger* assertions, not different ones.

No test in this file may touch the network — see the autouse guard below.
"""
import pytest

import app.agents.job_design as job_design_module
import app.app as app_module


# ──────────────────────────────────────────────────────────────────────────────
# Guards and fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _guard_no_real_llm(no_real_llm_client):
    """Autouse for this module: constructing the real OpenAI client is an error.

    The guard body lives in tests/conftest.py so the WP3 agent tests can reuse
    it; it is wired up autouse here (rather than in conftest) so the 597
    pre-existing tests keep running exactly as they did.
    """


# ──────────────────────────────────────────────────────────────────────────────
# Canned LLM output
# ──────────────────────────────────────────────────────────────────────────────

CLARIFYING_QUESTION = "了解。请问这套客服系统是一次性交付，还是需要长期运营？"

REQUIREMENT = {
    "project_name": "电商智能客服系统",
    "core_description": "覆盖售前咨询、售后处理和投诉响应的智能客服系统",
    "tasks_hint": ["搭建知识库", "接入工单系统"],
    "duration": "ongoing",
    "team_context": "3 人运营团队，无工程师",
    "urgency": "high",
    "budget_hint": "medium",
}

# What the model actually emits: prose, the marker, then the JSON. Note the
# marker is detected by a plain substring check (agents.py:78).
COMPLETE_RESPONSE = (
    "信息已经足够了。\n"
    "[REQUIREMENT_COMPLETE]\n"
    '{"project_name": "电商智能客服系统", '
    '"core_description": "覆盖售前咨询、售后处理和投诉响应的智能客服系统", '
    '"tasks_hint": ["搭建知识库", "接入工单系统"], '
    '"duration": "ongoing", '
    '"team_context": "3 人运营团队，无工程师", '
    '"urgency": "high", '
    '"budget_hint": "medium"}'
)

# Marker present, JSON truncated — extract_requirement raises, the route
# swallows it (app.py:178-179) and the conversation continues.
MALFORMED_COMPLETE_RESPONSE = (
    "信息已经足够了。\n"
    "[REQUIREMENT_COMPLETE]\n"
    '{"project_name": "电商智能客服系统", "core_description":'
)

CANNED_TASKS = [
    {
        "id": "t1",
        "name": "搭建 FAQ 知识库",
        "description": "整理历史工单并导入知识库",
        "type": "technical",
        "estimated_hours": 16,
        "requires_judgment": False,
        "is_recurring": False,
    },
    {
        "id": "t2",
        "name": "复杂投诉处理",
        "description": "处理需要判断力的升级投诉",
        "type": "operational",
        "estimated_hours": 40,
        "requires_judgment": True,
        "is_recurring": True,
    },
]

_AGENT_EVAL = {
    "can_complete": True,
    "confidence": 0.88,
    "reason": "该 Agent 已有知识库构建能力",
    "estimated_time": "2 天",
    "strengths": ["结构化整理", "批量导入"],
    "resource_id": "agent_content",
    "resource_name": "内容创作 Agent",
    "resource_type": "agent",
}

_HUMAN_EVAL = {
    "can_complete": True,
    "confidence": 0.72,
    "reason": "升级投诉需要人的判断与共情",
    "estimated_time": "长期",
    "strengths": ["沟通", "判断力"],
    "resource_id": "candidate_b",
    "resource_name": "客户成功",
    "resource_type": "human",
}

# Mirrors the runtime shape of run_resource_decision (agents.py:391-448) —
# the envelope is the wrapper object {"decisions": [...]}, never a bare list.
CANNED_DECISIONS = {
    "decisions": [
        {
            "task_id": "t1",
            "task_name": "搭建 FAQ 知识库",
            "task_type": "technical",
            "evaluations": [_AGENT_EVAL],
            "recommendation": {
                "decision": "agent",
                "resource": _AGENT_EVAL,
                "reason": "推荐使用 内容创作 Agent，置信度 88%",
                "cost_hint": "$0.05",
            },
        },
        {
            "task_id": "t2",
            "task_name": "复杂投诉处理",
            "task_type": "operational",
            "task_description": "处理需要判断力的升级投诉",
            "evaluations": [_HUMAN_EVAL],
            "recommendation": {
                "decision": "human",
                "resource": _HUMAN_EVAL,
                "reason": "建议招聘 客户成功 类型人才，置信度 72%",
                "cost_hint": "需要评估薪资",
            },
        },
    ]
}

CANNED_JOB_DESIGN = {
    "job_title": "客户成功专员",
    "core_responsibilities": ["处理升级投诉", "沉淀话术"],
    "required_skills": ["沟通", "工单系统"],
    "nice_to_have_skills": ["电商行业经验"],
    "experience_range": {"min": 1, "max": 3, "unit": "年"},
    "salary_range": {"min": 12000, "max": 18000, "unit": "元/月"},
    "work_type": "full-time",
    "water_score": 82,
}

QUICK_REQUIREMENT = {
    "project_name": "内部工具",
    "core_description": "搭建一个后端服务",
    "duration": "3个月",
}

# Sentinel used by the failure tests. Kept distinctive so a later commit can
# assert it is NOT echoed back to the client.
BOOM = "zhipu exploded at https://open.bigmodel.cn/api/paas/v4"


class CountingStub:
    """Callable stub that records every invocation.

    The recorded count is asserted in the happy-path tests so that a future
    refactor which bypasses the module-level names the routes call today
    (`app.app.decompose_tasks`, `app.app.run_resource_decision`,
    `app.agents.job_design.design_job` — audit §7.4) fails loudly here instead
    of silently reaching for the real Zhipu API.
    """

    def __init__(self, result=None, raises=None):
        self.result = result
        self.raises = raises
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.raises is not None:
            raise self.raises
        return self.result

    @property
    def call_count(self) -> int:
        return len(self.calls)


@pytest.fixture
def pipeline_stubs(monkeypatch):
    """Stub the three LLM boundaries of the decide/quick pipeline."""
    stubs = {
        "decompose_tasks": CountingStub(result={"tasks": CANNED_TASKS}),
        "run_resource_decision": CountingStub(result=CANNED_DECISIONS),
        "design_job": CountingStub(result=dict(CANNED_JOB_DESIGN)),
    }
    monkeypatch.setattr(app_module, "decompose_tasks", stubs["decompose_tasks"])
    monkeypatch.setattr(app_module, "run_resource_decision", stubs["run_resource_decision"])
    monkeypatch.setattr(job_design_module, "design_job", stubs["design_job"])
    return stubs


def start_session(client, fake_llm, response_text=CLARIFYING_QUESTION, message="搭建智能客服系统"):
    """Drive POST /api/analyze/start once and return (session_id, payload)."""
    fake_llm.queue(response_text)
    resp = client.post("/api/analyze/start", json={"message": message})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    return body["session_id"], body


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/analyze/start
# ──────────────────────────────────────────────────────────────────────────────

class TestAnalyzeStart:
    def test_returns_exactly_the_four_contract_keys(self, client, fake_llm):
        _sid, body = start_session(client, fake_llm)
        assert set(body) == {"session_id", "response", "is_complete", "requirement"}

    def test_incomplete_turn_echoes_the_model_text_verbatim(self, client, fake_llm):
        _sid, body = start_session(client, fake_llm)
        assert body["response"] == CLARIFYING_QUESTION
        assert body["is_complete"] is False
        assert body["requirement"] is None
        assert isinstance(body["session_id"], str) and body["session_id"]

    def test_calls_the_llm_exactly_once_with_the_users_message(self, client, fake_llm):
        start_session(client, fake_llm, message="搭建智能客服系统")
        assert fake_llm.call_count == 1
        messages = fake_llm.calls[0]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[-1] == {"role": "user", "content": "搭建智能客服系统"}

    def test_marker_flips_is_complete_and_populates_requirement(self, client, fake_llm):
        _sid, body = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        assert body["is_complete"] is True
        assert body["requirement"] == REQUIREMENT
        # The raw model text (marker included) is still returned untouched.
        assert body["response"] == COMPLETE_RESPONSE

    def test_marker_with_malformed_json_leaves_is_complete_false(self, client, fake_llm):
        """PINNED CURRENT BEHAVIOUR — not an endorsement (app.py:178-179).

        The parse error is swallowed, `is_complete` goes back to False, and the
        broken text is still handed to the user in `response`.
        """
        _sid, body = start_session(client, fake_llm, response_text=MALFORMED_COMPLETE_RESPONSE)
        assert body["is_complete"] is False
        assert body["requirement"] is None
        assert body["response"] == MALFORMED_COMPLETE_RESPONSE

    def test_empty_message_400(self, client, fake_llm):
        resp = client.post("/api/analyze/start", json={"message": ""})
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "Message is required"}
        assert fake_llm.call_count == 0

    def test_whitespace_only_message_400(self, client, fake_llm):
        resp = client.post("/api/analyze/start", json={"message": "   \n "})
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "Message is required"}

    def test_missing_message_key_400(self, client, fake_llm):
        resp = client.post("/api/analyze/start", json={})
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "Message is required"}


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/analyze/reply
# ──────────────────────────────────────────────────────────────────────────────

class TestAnalyzeReply:
    def test_returns_the_same_four_keys_as_start(self, client, fake_llm):
        session_id, _ = start_session(client, fake_llm)
        fake_llm.queue("再确认一个问题：预算大概什么量级？")
        resp = client.post(
            "/api/analyze/reply",
            json={"session_id": session_id, "message": "需要长期运营"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert set(body) == {"session_id", "response", "is_complete", "requirement"}
        assert body["session_id"] == session_id
        assert body["is_complete"] is False
        assert body["requirement"] is None

    def test_marker_on_a_later_turn_completes_the_session(self, client, fake_llm):
        session_id, first = start_session(client, fake_llm)
        assert first["is_complete"] is False

        fake_llm.queue(COMPLETE_RESPONSE)
        resp = client.post(
            "/api/analyze/reply",
            json={"session_id": session_id, "message": "需要长期运营，预算中等"},
        )
        body = resp.get_json()
        assert resp.status_code == 200
        assert body["is_complete"] is True
        assert body["requirement"] == REQUIREMENT

    def test_conversation_history_is_replayed_to_the_model(self, client, fake_llm):
        session_id, _ = start_session(client, fake_llm)
        fake_llm.queue(COMPLETE_RESPONSE)
        client.post(
            "/api/analyze/reply",
            json={"session_id": session_id, "message": "需要长期运营"},
        )
        assert fake_llm.call_count == 2
        second_call_messages = fake_llm.calls[1]["messages"]
        roles = [m["role"] for m in second_call_messages]
        assert roles == ["system", "user", "assistant", "user"]
        assert second_call_messages[-1]["content"] == "需要长期运营"

    def test_marker_with_malformed_json_leaves_is_complete_false(self, client, fake_llm):
        """PINNED CURRENT BEHAVIOUR (app.py:210-211) — same swallow as /start."""
        session_id, _ = start_session(client, fake_llm)
        fake_llm.queue(MALFORMED_COMPLETE_RESPONSE)
        resp = client.post(
            "/api/analyze/reply",
            json={"session_id": session_id, "message": "需要长期运营"},
        )
        body = resp.get_json()
        assert resp.status_code == 200
        assert body["is_complete"] is False
        assert body["requirement"] is None
        assert body["response"] == MALFORMED_COMPLETE_RESPONSE

    def test_unknown_session_404(self, client, fake_llm):
        resp = client.post(
            "/api/analyze/reply",
            json={"session_id": "does-not-exist", "message": "hi"},
        )
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "Session not found"}
        assert fake_llm.call_count == 0


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/analyze/decide
# ──────────────────────────────────────────────────────────────────────────────

class TestAnalyzeDecide:
    def test_unknown_session_404(self, client, fake_llm):
        resp = client.post("/api/analyze/decide", json={"session_id": "nope"})
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "Session not found"}

    def test_session_without_requirement_400(self, client, fake_llm):
        session_id, _ = start_session(client, fake_llm)  # no marker → no requirement
        resp = client.post("/api/analyze/decide", json={"session_id": session_id})
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "Requirement analysis not complete"}

    def test_happy_path_returns_the_five_contract_keys(self, client, fake_llm, pipeline_stubs):
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        resp = client.post("/api/analyze/decide", json={"session_id": session_id})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert set(body) == {"requirement", "tasks", "decisions", "jd_report", "summary"}
        assert body["requirement"] == REQUIREMENT
        assert body["tasks"] == CANNED_TASKS

    def test_happy_path_actually_used_the_patched_module_level_names(
        self, client, fake_llm, pipeline_stubs
    ):
        """Audit §7.4: the routes must keep calling these module-level bindings."""
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        client.post("/api/analyze/decide", json={"session_id": session_id})
        assert pipeline_stubs["decompose_tasks"].call_count == 1
        assert pipeline_stubs["run_resource_decision"].call_count == 1
        # one human/hybrid decision in CANNED_DECISIONS → one job design
        assert pipeline_stubs["design_job"].call_count == 1
        # decompose_tasks receives the requirement extracted from the chat
        assert pipeline_stubs["decompose_tasks"].calls[0][0][0] == REQUIREMENT
        # run_resource_decision receives the decomposed task list
        assert pipeline_stubs["run_resource_decision"].calls[0][0][0] == CANNED_TASKS

    def test_decisions_stay_a_wrapper_object(self, client, fake_llm, pipeline_stubs):
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        body = client.post("/api/analyze/decide", json={"session_id": session_id}).get_json()
        decisions = body["decisions"]
        assert isinstance(decisions, dict)
        assert set(decisions) == {"decisions"}
        assert isinstance(decisions["decisions"], list)
        assert len(decisions["decisions"]) == 2

    def test_each_decision_carries_task_id_and_a_recommendation(
        self, client, fake_llm, pipeline_stubs
    ):
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        body = client.post("/api/analyze/decide", json={"session_id": session_id}).get_json()
        for decision in body["decisions"]["decisions"]:
            assert isinstance(decision["task_id"], str)
            rec = decision["recommendation"]
            assert rec["decision"] in ("agent", "human", "hybrid")
            assert isinstance(rec["reason"], str) and rec["reason"]
            assert isinstance(rec["cost_hint"], str) and rec["cost_hint"]
        # evaluations are part of the returned payload surface (audit C13)
        assert body["decisions"]["decisions"][0]["evaluations"] == [_AGENT_EVAL]

    def test_summary_keys(self, client, fake_llm, pipeline_stubs):
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        body = client.post("/api/analyze/decide", json={"session_id": session_id}).get_json()
        summary = body["summary"]
        assert set(summary) == {
            "verdict",
            "verdict_type",
            "task_count",
            "agent_tasks",
            "human_tasks",
            "needs_hiring",
            "job_count",
            "water_score",
        }
        assert summary["task_count"] == 2
        assert summary["agent_tasks"] == 1
        assert summary["human_tasks"] == 1
        assert summary["verdict_type"] == "hybrid"
        assert summary["needs_hiring"] is True
        assert summary["job_count"] == 1
        assert summary["water_score"] == 82

    def test_jd_report_shape(self, client, fake_llm, pipeline_stubs):
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        body = client.post("/api/analyze/decide", json={"session_id": session_id}).get_json()
        jd_report = body["jd_report"]
        assert jd_report["needs_hiring"] is True
        assert jd_report["job_count"] == 1
        assert len(jd_report["job_designs"]) == 1
        assert jd_report["job_designs"][0]["job_title"] == "客户成功专员"

    def test_decompose_failure_is_a_500_with_a_json_error_key(
        self, client, fake_llm, monkeypatch
    ):
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        monkeypatch.setattr(
            app_module, "decompose_tasks", CountingStub(raises=RuntimeError(BOOM))
        )
        resp = client.post("/api/analyze/decide", json={"session_id": session_id})
        assert resp.status_code == 500
        body = resp.get_json()
        assert body is not None, "the error body must stay JSON, not Flask's HTML page"
        assert "error" in body


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/analyze/quick
# ──────────────────────────────────────────────────────────────────────────────

class TestAnalyzeQuick:
    def test_missing_requirement_400(self, client):
        resp = client.post("/api/analyze/quick", json={})
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "requirement is required"}

    def test_empty_requirement_400(self, client):
        resp = client.post("/api/analyze/quick", json={"requirement": {}})
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "requirement is required"}

    def test_happy_path_returns_the_six_contract_keys(self, client, pipeline_stubs):
        resp = client.post(
            "/api/analyze/quick",
            json={"requirement": QUICK_REQUIREMENT, "original_description": "我需要做个后端"},
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert set(body) == {
            "session_id",
            "requirement",
            "tasks",
            "decisions",
            "jd_report",
            "summary",
        }
        assert body["requirement"] == QUICK_REQUIREMENT
        assert isinstance(body["session_id"], str) and body["session_id"]

    def test_happy_path_actually_used_the_patched_module_level_names(
        self, client, pipeline_stubs
    ):
        client.post("/api/analyze/quick", json={"requirement": QUICK_REQUIREMENT})
        assert pipeline_stubs["decompose_tasks"].call_count == 1
        assert pipeline_stubs["run_resource_decision"].call_count == 1
        assert pipeline_stubs["design_job"].call_count == 1

    def test_decisions_wrapper_and_summary_match_the_decide_route(
        self, client, pipeline_stubs
    ):
        body = client.post(
            "/api/analyze/quick", json={"requirement": QUICK_REQUIREMENT}
        ).get_json()
        assert set(body["decisions"]) == {"decisions"}
        assert set(body["summary"]) == {
            "verdict",
            "verdict_type",
            "task_count",
            "agent_tasks",
            "human_tasks",
            "needs_hiring",
            "job_count",
            "water_score",
        }

    def test_decompose_failure_is_a_500_with_a_json_error_key(self, client, monkeypatch):
        monkeypatch.setattr(
            app_module, "decompose_tasks", CountingStub(raises=RuntimeError(BOOM))
        )
        resp = client.post("/api/analyze/quick", json={"requirement": QUICK_REQUIREMENT})
        assert resp.status_code == 500
        body = resp.get_json()
        assert body is not None, "the error body must stay JSON, not Flask's HTML page"
        assert "error" in body
