"""
Stage 1 / WP3b — characterisation tests for the four analysis routes under
`HIRENET_TASK_AGENT=v2`.

This is `tests/test_analyze_routes_v1.py` re-run against the TaskAnalysisAgent
pipeline: the same route surface, the same status codes, the same response
keys, the same `decisions` wrapper and `summary` shape. Where v1 gets its
behaviour from three stubbed module functions, v2 gets it from one scripted
`FakeLLMClient`, so these tests also pin the number and ORDER of LLM calls the
new pipeline makes — the thing that decides what a v2 run costs.

On top of the v1 contract it pins what v2 adds:

  * `turn_count` (D3) on /start and /reply, and forced extraction at the cap;
  * one `analysis_traces` row per LLM call plus the synthetic `decide` row
    (D9), in step order, replayable by scripts/replay_trace.py;
  * `agent_runs.input_tokens` / `output_tokens` / `time_ms` / `llm_cost_usd`
    populated (D8) — NULL on every run before this work package;
  * billing rows byte-for-byte what the equivalent v1 scenario produces;
  * that the v1 module-level bindings are NOT called on the v2 path — nobody
    gets to silently mix the two pipelines (audit §7.4 / risk 2).

No test in this file may touch the network — see the autouse guard below.
"""
import json
import os
import sys
import tempfile

import pytest

import app.agents.job_design as job_design_module
import app.app as app_module
from app.app import create_app
from app.services.mock_settlement import MockSettlementProvider
from app.storage.agent_runs import list_agent_runs_by_caller
from app.storage.analysis_traces import list_traces
from app.storage.royalty_ledger import list_royalties_by_creator
from tests.conftest import FakeLLMClient
from tests.test_analyze_routes_v1 import CountingStub

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import replay_trace  # noqa: E402

CALLER_ID = "phase1_stub_employer"
CREATOR_ID = "phase1_stub_creator"


# ──────────────────────────────────────────────────────────────────────────────
# Guards and fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _guard_no_real_llm(no_real_llm_client):
    """Constructing the real OpenAI client is an error in this module."""


@pytest.fixture(autouse=True)
def _v2(monkeypatch):
    """Every test in this file runs the v2 pipeline."""
    monkeypatch.setenv("HIRENET_TASK_AGENT", "v2")


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

COMPLETE_RESPONSE = (
    "信息已经足够了。\n"
    "[REQUIREMENT_COMPLETE]\n"
    + json.dumps(REQUIREMENT, ensure_ascii=False)
)

# Marker present, JSON truncated. v1 swallowed the parse error into
# `is_complete: False`; v2 spends one repair call first and then does the same,
# which is what keeps the route contract identical.
MALFORMED_COMPLETE_RESPONSE = (
    "信息已经足够了。\n"
    "[REQUIREMENT_COMPLETE]\n"
    '{"project_name": "电商智能客服系统", "core_description":'
)

# type=technical, no judgment, not recurring → shortlist [agent_code,
# candidate_a] → exactly 2 evaluations.
TASK_AGENT = {
    "id": "t1",
    "name": "搭建 FAQ 知识库",
    "description": "整理历史工单并导入知识库",
    "type": "technical",
    "estimated_hours": 16,
    "requires_judgment": False,
    "is_recurring": False,
}

# type=operational + recurring → shortlist [agent_content, agent_data,
# candidate_a] → exactly 3 evaluations.
TASK_HUMAN = {
    "id": "t2",
    "name": "复杂投诉处理",
    "description": "处理需要判断力的升级投诉",
    "type": "operational",
    "estimated_hours": 40,
    "requires_judgment": True,
    "is_recurring": True,
}

DECOMPOSE_RESPONSE = json.dumps({"tasks": [TASK_AGENT, TASK_HUMAN]}, ensure_ascii=False)


def evaluation(confidence, reason="能力匹配"):
    return json.dumps({
        "can_complete": confidence >= 0.5,
        "confidence": confidence,
        "reason": reason,
        "estimated_time": "2 天",
        "strengths": ["经验匹配"],
    }, ensure_ascii=False)


#: The five evaluations the two tasks above provoke, in call order:
#: t1: agent_code 0.9 (wins → "agent"), candidate_a 0.4
#: t2: agent_content 0.2, agent_data 0.1, candidate_a 0.85 (wins → "human")
DECIDE_EVALUATIONS = [
    evaluation(0.9, "该 Agent 已有知识库构建能力"),
    evaluation(0.4, "全栈工程师，能做但不专精"),
    evaluation(0.2, "文案 Agent 无法处理投诉判断"),
    evaluation(0.1, "数据 Agent 不匹配"),
    evaluation(0.85, "升级投诉需要人的判断与共情"),
]

#: LLM calls one /decide makes with the script above: 1 decompose + 5 evaluate.
DECIDE_LLM_CALLS = 1 + len(DECIDE_EVALUATIONS)

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

BOOM = "zhipu exploded at https://open.bigmodel.cn/api/paas/v4"


@pytest.fixture
def v1_bindings(monkeypatch):
    """Stub the v1 module-level names so a leak into the v1 path is loud.

    Same objects `tests/test_analyze_routes_v1.py` patches. On the v2 path they
    must never be called; if the branch ever falls through, `call_count` says so
    instead of the test quietly passing on v1 behaviour.
    """
    stubs = {
        "decompose_tasks": CountingStub(result={"tasks": []}),
        "run_resource_decision": CountingStub(result={"decisions": []}),
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


def queue_decide_script(fake_llm):
    fake_llm.queue(DECOMPOSE_RESPONSE, *DECIDE_EVALUATIONS)


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/analyze/start
# ──────────────────────────────────────────────────────────────────────────────

class TestAnalyzeStart:
    def test_returns_the_four_contract_keys_plus_turn_count(self, client, fake_llm):
        _sid, body = start_session(client, fake_llm)
        assert set(body) == {
            "session_id", "response", "is_complete", "requirement", "turn_count",
        }

    def test_incomplete_turn_echoes_the_model_text_verbatim(self, client, fake_llm):
        _sid, body = start_session(client, fake_llm)
        assert body["response"] == CLARIFYING_QUESTION
        assert body["is_complete"] is False
        assert body["requirement"] is None
        assert isinstance(body["session_id"], str) and body["session_id"]

    def test_turn_count_starts_at_one_and_increments(self, client, fake_llm):
        session_id, body = start_session(client, fake_llm)
        assert body["turn_count"] == 1
        fake_llm.queue("再确认一个问题：预算大概什么量级？")
        second = client.post(
            "/api/analyze/reply", json={"session_id": session_id, "message": "长期运营"}
        ).get_json()
        assert second["turn_count"] == 2

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
        assert body["response"] == COMPLETE_RESPONSE

    def test_marker_with_malformed_json_leaves_is_complete_false(self, client, fake_llm):
        """Same observable outcome as v1 — reached differently.

        v1 swallowed the JSONDecodeError (app.py:178-179). v2 routes the text
        through validate_llm_output, which spends ONE repair call before giving
        up; the second queued response is that repair attempt, and it fails too.
        """
        fake_llm.queue(MALFORMED_COMPLETE_RESPONSE, "还是坏的 {")
        resp = client.post("/api/analyze/start", json={"message": "搭建智能客服系统"})
        body = resp.get_json()
        assert resp.status_code == 200
        assert body["is_complete"] is False
        assert body["requirement"] is None
        assert body["response"] == MALFORMED_COMPLETE_RESPONSE
        assert fake_llm.call_count == 2

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
# D3 — the turn cap and forced extraction, driven through the route
# ──────────────────────────────────────────────────────────────────────────────

class TestForcedExtraction:
    def test_cap_of_one_forces_extraction_on_start(self, client, fake_llm, monkeypatch):
        """v1 has no cap anywhere — agent, route or browser (audit risk 3)."""
        monkeypatch.setenv("HIRENET_TASK_AGENT_MAX_TURNS", "1")
        fake_llm.queue(
            CLARIFYING_QUESTION,                                # turn 1, no marker
            json.dumps(REQUIREMENT, ensure_ascii=False),        # forced extraction
        )
        body = client.post(
            "/api/analyze/start", json={"message": "搭建智能客服系统"}
        ).get_json()

        assert fake_llm.call_count == 2
        assert body["is_complete"] is True
        assert body["requirement"] == REQUIREMENT
        assert body["turn_count"] == 1
        # The employer still sees the model's own words, not the forced JSON.
        assert body["response"] == CLARIFYING_QUESTION

    def test_forced_extraction_prompt_is_appended_to_the_history(
        self, client, fake_llm, monkeypatch
    ):
        monkeypatch.setenv("HIRENET_TASK_AGENT_MAX_TURNS", "1")
        fake_llm.queue(CLARIFYING_QUESTION, json.dumps(REQUIREMENT, ensure_ascii=False))
        client.post("/api/analyze/start", json={"message": "搭建智能客服系统"})

        forced = fake_llm.calls[1]["messages"]
        assert forced[-1]["role"] == "user"
        assert forced[-1]["content"] != "搭建智能客服系统"
        assert [m["role"] for m in forced] == ["system", "user", "assistant", "user"]

    def test_failed_forced_extraction_stops_calling_the_model(
        self, client, fake_llm, monkeypatch
    ):
        """After the cap fails, /reply must not keep spending the employer's money."""
        monkeypatch.setenv("HIRENET_TASK_AGENT_MAX_TURNS", "1")
        fake_llm.queue(CLARIFYING_QUESTION, "还是没有 JSON", "依然没有")
        body = client.post(
            "/api/analyze/start", json={"message": "搭建智能客服系统"}
        ).get_json()
        assert body["is_complete"] is False
        calls_after_start = fake_llm.call_count

        reply = client.post(
            "/api/analyze/reply",
            json={"session_id": body["session_id"], "message": "还有别的信息"},
        )
        assert reply.status_code == 200
        assert reply.get_json()["is_complete"] is False
        assert fake_llm.call_count == calls_after_start

    def test_the_forced_run_is_fully_traced(self, client, fake_llm, monkeypatch, app_db_path):
        monkeypatch.setenv("HIRENET_TASK_AGENT_MAX_TURNS", "1")
        fake_llm.queue(CLARIFYING_QUESTION, json.dumps(REQUIREMENT, ensure_ascii=False))
        body = client.post(
            "/api/analyze/start", json={"message": "搭建智能客服系统"}
        ).get_json()

        rows = list_traces(app_db_path, body["session_id"])
        assert [r["stage"] for r in rows] == ["clarify", "extract"]
        assert [r["parsed_ok"] for r in rows] == [True, True]


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/analyze/reply
# ──────────────────────────────────────────────────────────────────────────────

class TestAnalyzeReply:
    def test_returns_the_same_keys_as_start(self, client, fake_llm):
        session_id, _ = start_session(client, fake_llm)
        fake_llm.queue("再确认一个问题：预算大概什么量级？")
        resp = client.post(
            "/api/analyze/reply",
            json={"session_id": session_id, "message": "需要长期运营"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert set(body) == {
            "session_id", "response", "is_complete", "requirement", "turn_count",
        }
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
        """The state dict really does rebuild the conversation (D4)."""
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
        session_id, _ = start_session(client, fake_llm)
        fake_llm.queue(MALFORMED_COMPLETE_RESPONSE, "还是坏的 {")
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

    def test_happy_path_returns_the_five_contract_keys(self, client, fake_llm, v1_bindings):
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        queue_decide_script(fake_llm)
        resp = client.post("/api/analyze/decide", json={"session_id": session_id})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert set(body) == {"requirement", "tasks", "decisions", "jd_report", "summary"}
        assert body["requirement"] == REQUIREMENT
        assert body["tasks"] == [TASK_AGENT, TASK_HUMAN]

    def test_the_v1_bindings_are_never_called(self, client, fake_llm, v1_bindings):
        """Audit §7.4 / risk 2 in reverse: the two paths must not mix."""
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        queue_decide_script(fake_llm)
        client.post("/api/analyze/decide", json={"session_id": session_id})
        assert v1_bindings["decompose_tasks"].call_count == 0
        assert v1_bindings["run_resource_decision"].call_count == 0
        # design_job IS still the call site generate_jd_report uses on both paths.
        assert v1_bindings["design_job"].call_count == 1

    def test_the_llm_call_budget_is_exactly_what_the_script_says(
        self, client, fake_llm, v1_bindings
    ):
        """Cost is a contract too: 1 decompose + 5 evaluations, nothing else."""
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        queue_decide_script(fake_llm)
        client.post("/api/analyze/decide", json={"session_id": session_id})
        assert fake_llm.call_count == 1 + DECIDE_LLM_CALLS
        assert fake_llm.responses == [], "the scripted queue must be consumed exactly"

    def test_decisions_stay_a_wrapper_object(self, client, fake_llm, v1_bindings):
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        queue_decide_script(fake_llm)
        body = client.post("/api/analyze/decide", json={"session_id": session_id}).get_json()
        decisions = body["decisions"]
        assert isinstance(decisions, dict)
        assert set(decisions) == {"decisions"}
        assert isinstance(decisions["decisions"], list)
        assert len(decisions["decisions"]) == 2

    def test_each_decision_carries_task_id_and_a_recommendation(
        self, client, fake_llm, v1_bindings
    ):
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        queue_decide_script(fake_llm)
        body = client.post("/api/analyze/decide", json={"session_id": session_id}).get_json()
        for decision in body["decisions"]["decisions"]:
            assert isinstance(decision["task_id"], str)
            rec = decision["recommendation"]
            # D5: never None on the v2 path, by construction.
            assert isinstance(rec, dict)
            assert rec["decision"] in ("agent", "human", "hybrid")
            assert isinstance(rec["reason"], str) and rec["reason"]
            assert isinstance(rec["cost_hint"], str) and rec["cost_hint"]
        assert len(body["decisions"]["decisions"][0]["evaluations"]) == 2

    def test_the_routing_matches_the_scripted_confidences(self, client, fake_llm, v1_bindings):
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        queue_decide_script(fake_llm)
        body = client.post("/api/analyze/decide", json={"session_id": session_id}).get_json()
        by_task = {d["task_id"]: d for d in body["decisions"]["decisions"]}
        assert by_task["t1"]["recommendation"]["decision"] == "agent"
        assert by_task["t1"]["recommendation"]["resource"]["resource_id"] == "agent_code"
        assert by_task["t2"]["recommendation"]["decision"] == "human"
        assert by_task["t2"]["recommendation"]["resource"]["resource_type"] == "human"

    def test_task_description_reaches_the_decision(self, client, fake_llm, v1_bindings):
        """D6 / audit risk 5: v1 consumed this field and never produced it."""
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        queue_decide_script(fake_llm)
        body = client.post("/api/analyze/decide", json={"session_id": session_id}).get_json()
        by_task = {d["task_id"]: d for d in body["decisions"]["decisions"]}
        assert by_task["t2"]["task_description"] == TASK_HUMAN["description"]
        assert by_task["t2"]["estimated_hours"] == 40
        assert by_task["t2"]["requires_judgment"] is True
        assert by_task["t2"]["is_recurring"] is True

    def test_the_jd_is_written_from_the_real_task_fields(self, client, fake_llm, v1_bindings):
        """D6, end to end: no more "40 hours, judgment required" for every JD."""
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        queue_decide_script(fake_llm)
        client.post("/api/analyze/decide", json={"session_id": session_id})
        _args, kwargs = v1_bindings["design_job"].calls[0]
        task = _args[1] if len(_args) > 1 else kwargs["task"]
        assert task["description"] == TASK_HUMAN["description"]
        assert task["estimated_hours"] == 40
        assert task["requires_judgment"] is True
        assert task["is_recurring"] is True

    def test_summary_keys(self, client, fake_llm, v1_bindings):
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        queue_decide_script(fake_llm)
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

    def test_jd_report_shape(self, client, fake_llm, v1_bindings):
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        queue_decide_script(fake_llm)
        body = client.post("/api/analyze/decide", json={"session_id": session_id}).get_json()
        jd_report = body["jd_report"]
        assert jd_report["needs_hiring"] is True
        assert jd_report["job_count"] == 1
        assert len(jd_report["job_designs"]) == 1
        assert jd_report["job_designs"][0]["job_title"] == "客户成功专员"

    def test_decompose_failure_is_a_500_with_a_json_error_key(self, client, fake_llm):
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        fake_llm.queue(RuntimeError(BOOM))
        resp = client.post("/api/analyze/decide", json={"session_id": session_id})
        assert resp.status_code == 500
        body = resp.get_json()
        assert body is not None, "the error body must stay JSON, not Flask's HTML page"
        assert "error" in body

    def test_500_body_is_generic_and_does_not_leak_the_exception(
        self, client, fake_llm, caplog
    ):
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        fake_llm.queue(RuntimeError(BOOM))
        with caplog.at_level("ERROR"):
            resp = client.post("/api/analyze/decide", json={"session_id": session_id})
        assert resp.get_json() == {"error": "analysis failed"}
        assert BOOM not in resp.get_data(as_text=True)
        assert "open.bigmodel.cn" not in resp.get_data(as_text=True)
        assert BOOM in caplog.text


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

    def test_happy_path_returns_the_six_contract_keys(self, client, fake_llm, v1_bindings):
        queue_decide_script(fake_llm)
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

    def test_no_clarification_turns_are_spent(self, client, fake_llm, v1_bindings):
        """The client already knows the requirement; /quick must not re-ask."""
        queue_decide_script(fake_llm)
        client.post("/api/analyze/quick", json={"requirement": QUICK_REQUIREMENT})
        assert fake_llm.call_count == DECIDE_LLM_CALLS
        assert [c["temperature"] for c in fake_llm.calls][0] == 0.2  # decompose, not clarify

    def test_the_v1_bindings_are_never_called(self, client, fake_llm, v1_bindings):
        queue_decide_script(fake_llm)
        client.post("/api/analyze/quick", json={"requirement": QUICK_REQUIREMENT})
        assert v1_bindings["decompose_tasks"].call_count == 0
        assert v1_bindings["run_resource_decision"].call_count == 0
        assert v1_bindings["design_job"].call_count == 1

    def test_the_supplied_requirement_seeds_the_agent_state(
        self, client, fake_llm, v1_bindings
    ):
        queue_decide_script(fake_llm)
        body = client.post(
            "/api/analyze/quick",
            json={"requirement": QUICK_REQUIREMENT, "original_description": "我需要做个后端"},
        ).get_json()
        sess = app_module.analysis_sessions[body["session_id"]]
        assert sess["agent_version"] == "v2"
        assert sess["agent_state"]["requirement"] == QUICK_REQUIREMENT
        assert sess["agent_state"]["initial_input"] == "我需要做个后端"
        assert sess["agent_state"]["history"] == []

    def test_decisions_wrapper_and_summary_match_the_decide_route(
        self, client, fake_llm, v1_bindings
    ):
        queue_decide_script(fake_llm)
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

    def test_decompose_failure_is_a_500_with_a_json_error_key(self, client, fake_llm):
        fake_llm.queue(RuntimeError(BOOM))
        resp = client.post("/api/analyze/quick", json={"requirement": QUICK_REQUIREMENT})
        assert resp.status_code == 500
        body = resp.get_json()
        assert body is not None, "the error body must stay JSON, not Flask's HTML page"
        assert "error" in body

    def test_500_body_is_generic_and_does_not_leak_the_exception(
        self, client, fake_llm, caplog
    ):
        fake_llm.queue(RuntimeError(BOOM))
        with caplog.at_level("ERROR"):
            resp = client.post("/api/analyze/quick", json={"requirement": QUICK_REQUIREMENT})
        assert resp.get_json() == {"error": "analysis failed"}
        assert BOOM not in resp.get_data(as_text=True)
        assert "open.bigmodel.cn" not in resp.get_data(as_text=True)
        assert BOOM in caplog.text


# ──────────────────────────────────────────────────────────────────────────────
# D9 — traces
# ──────────────────────────────────────────────────────────────────────────────

class TestTraces:
    def _full_run(self, client, fake_llm):
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        queue_decide_script(fake_llm)
        resp = client.post("/api/analyze/decide", json={"session_id": session_id})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        return session_id

    def test_one_row_per_llm_call_plus_the_synthetic_decide_row(
        self, client, fake_llm, v1_bindings, app_db_path
    ):
        session_id = self._full_run(client, fake_llm)
        rows = list_traces(app_db_path, session_id)
        # design_job is stubbed here, so it makes no LLM call of its own.
        assert len(rows) == fake_llm.call_count + 1

    def test_the_stages_appear_in_pipeline_order(
        self, client, fake_llm, v1_bindings, app_db_path
    ):
        session_id = self._full_run(client, fake_llm)
        stages = [r["stage"] for r in list_traces(app_db_path, session_id)]
        assert stages == ["clarify", "decompose"] + ["evaluate"] * 5 + ["decide"]

    def test_step_no_is_contiguous_from_zero_across_requests(
        self, client, fake_llm, v1_bindings, app_db_path
    ):
        """The counter lives in the session, so /start and /decide share it."""
        session_id = self._full_run(client, fake_llm)
        rows = list_traces(app_db_path, session_id)
        assert [r["step_no"] for r in rows] == list(range(len(rows)))

    def test_the_decide_row_records_no_model_call(
        self, client, fake_llm, v1_bindings, app_db_path
    ):
        session_id = self._full_run(client, fake_llm)
        decide_row = list_traces(app_db_path, session_id)[-1]
        assert decide_row["stage"] == "decide"
        assert decide_row["model"] == "policy"
        assert decide_row["parsed_ok"] is True
        assert decide_row["input_tokens"] is None
        assert decide_row["output_tokens"] is None
        assert json.loads(decide_row["prompt_json"]) == []
        # …but it carries the outcome, which is the point of replaying at all.
        assert "recommendation" in decide_row["response_text"]

    def test_llm_rows_carry_usage_and_the_real_model_id(
        self, client, fake_llm, v1_bindings, app_db_path
    ):
        session_id = self._full_run(client, fake_llm)
        llm_rows = [r for r in list_traces(app_db_path, session_id) if r["stage"] != "decide"]
        for row in llm_rows:
            assert row["model"] == "glm-4-plus"
            assert row["input_tokens"] == 11    # conftest FakeUsage
            assert row["output_tokens"] == 22
            assert isinstance(row["time_ms"], int) and row["time_ms"] >= 0
            assert row["parsed_ok"] is True

    def test_prompts_and_responses_are_stored_verbatim(
        self, client, fake_llm, v1_bindings, app_db_path
    ):
        session_id = self._full_run(client, fake_llm)
        rows = list_traces(app_db_path, session_id)
        assert rows[0]["response_text"] == COMPLETE_RESPONSE
        assert "搭建智能客服系统" in rows[0]["prompt_json"]
        assert rows[1]["response_text"] == DECOMPOSE_RESPONSE

    def test_replay_cli_lists_the_whole_run(
        self, client, fake_llm, v1_bindings, app_db_path, capsys
    ):
        session_id = self._full_run(client, fake_llm)
        assert replay_trace.main([session_id, "--db", app_db_path]) == 0
        out = capsys.readouterr().out
        assert f"session {session_id} — 8 step(s)" in out
        assert "[0] clarify" in out
        assert "[1] decompose" in out
        assert "[7] decide  model=policy" in out
        assert out.index("[1] decompose") < out.index("[7] decide")

    def test_a_v1_session_leaves_the_table_empty(self, client, fake_llm, monkeypatch, app_db_path):
        monkeypatch.setenv("HIRENET_TASK_AGENT", "v1")
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        assert list_traces(app_db_path, session_id) == []


# ──────────────────────────────────────────────────────────────────────────────
# D8 — usage reaches agent_runs; billing is unchanged
# ──────────────────────────────────────────────────────────────────────────────

def make_app_client():
    """A client with its own temp DB, so two pipelines can be compared in one test."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    flask_app = create_app(config={
        "TESTING": True,
        "DATABASE_PATH": db_path,
        "SETTLEMENT_PROVIDER": MockSettlementProvider(),
    })
    return flask_app.test_client(), db_path


class TestBillingAndUsage:
    def test_agent_runs_telemetry_columns_are_populated(
        self, client, fake_llm, v1_bindings, app_db_path
    ):
        """D8 / audit risk 9: these four columns were NULL on every run ever."""
        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        queue_decide_script(fake_llm)
        client.post("/api/analyze/decide", json={"session_id": session_id})

        runs = list_agent_runs_by_caller(app_db_path, CALLER_ID)
        assert len(runs) == 1
        run = runs[0]
        # 1 clarify + 1 decompose + 5 evaluate = 7 calls at 11/22 tokens each.
        assert run["input_tokens"] == 7 * 11
        assert run["output_tokens"] == 7 * 22
        assert isinstance(run["time_ms"], int) and run["time_ms"] >= 0
        assert isinstance(run["llm_cost_usd"], str)
        assert float(run["llm_cost_usd"]) > 0

    def test_v1_leaves_the_telemetry_columns_null(self, fake_llm, monkeypatch):
        monkeypatch.setenv("HIRENET_TASK_AGENT", "v1")
        v1_client, db_path = make_app_client()
        try:
            monkeypatch.setattr(
                app_module, "decompose_tasks", lambda r: {"tasks": [TASK_HUMAN]}
            )
            monkeypatch.setattr(
                app_module,
                "run_resource_decision",
                lambda tasks: {"decisions": [_v1_human_decision()]},
            )
            monkeypatch.setattr(
                job_design_module, "design_job",
                lambda *a, **k: dict(CANNED_JOB_DESIGN),
            )
            resp = v1_client.post(
                "/api/analyze/quick", json={"requirement": QUICK_REQUIREMENT}
            )
            assert resp.status_code == 200, resp.get_data(as_text=True)
            run = list_agent_runs_by_caller(db_path, CALLER_ID)[0]
            assert run["input_tokens"] is None
            assert run["output_tokens"] is None
            assert run["llm_cost_usd"] is None
            assert run["time_ms"] is None
        finally:
            os.unlink(db_path)

    def test_billing_rows_match_the_equivalent_v1_scenario(self, fake_llm, monkeypatch):
        """Same one-human-task scenario on both pipelines → identical money."""
        v1_client, v1_db = make_app_client()
        v2_client, v2_db = make_app_client()
        try:
            monkeypatch.setenv("HIRENET_TASK_AGENT", "v1")
            monkeypatch.setattr(
                app_module, "decompose_tasks", lambda r: {"tasks": [TASK_HUMAN]}
            )
            monkeypatch.setattr(
                app_module,
                "run_resource_decision",
                lambda tasks: {"decisions": [_v1_human_decision()]},
            )
            monkeypatch.setattr(
                job_design_module, "design_job",
                lambda *a, **k: dict(CANNED_JOB_DESIGN),
            )
            assert v1_client.post(
                "/api/analyze/quick", json={"requirement": QUICK_REQUIREMENT}
            ).status_code == 200

            monkeypatch.setenv("HIRENET_TASK_AGENT", "v2")
            # decompose → the same single human task, then its 3 evaluations.
            fake_llm.queue(
                json.dumps({"tasks": [TASK_HUMAN]}, ensure_ascii=False),
                evaluation(0.2), evaluation(0.1), evaluation(0.85),
            )
            assert v2_client.post(
                "/api/analyze/quick", json={"requirement": QUICK_REQUIREMENT}
            ).status_code == 200

            v1_rows = list_royalties_by_creator(v1_db, CREATOR_ID)
            v2_rows = list_royalties_by_creator(v2_db, CREATOR_ID)
            assert len(v1_rows) == len(v2_rows) == 1
            for key in ("amount", "currency", "chain", "status", "creator_id", "party"):
                assert v1_rows[0][key] == v2_rows[0][key]
            assert v2_rows[0]["amount"] == 70

            v1_run = list_agent_runs_by_caller(v1_db, CALLER_ID)[0]
            v2_run = list_agent_runs_by_caller(v2_db, CALLER_ID)[0]
            for key in ("charge_amount", "charge_currency", "charge_chain",
                        "caller_id", "agent_name", "payment_method",
                        "settlement_status"):
                assert v1_run[key] == v2_run[key], key
            # The two apps bootstrap their own asset, so asset_id legitimately
            # differs; every money field in the split must not.
            assert _splits_without_asset_id(v1_run) == _splits_without_asset_id(v2_run)
            assert v2_run["charge_amount"] == 100
            assert v2_run["royalty_splits"]["platform"]["amount"] == 30
        finally:
            os.unlink(v1_db)
            os.unlink(v2_db)

    def test_two_human_tasks_still_bill_once_each(self, client, fake_llm, v1_bindings, app_db_path):
        """§7.5: billing is per successful design, not per request."""
        two_human = json.dumps(
            {"tasks": [TASK_HUMAN, dict(TASK_HUMAN, id="t3", name="话术沉淀")]},
            ensure_ascii=False,
        )
        fake_llm.queue(
            two_human,
            evaluation(0.2), evaluation(0.1), evaluation(0.85),
            evaluation(0.2), evaluation(0.1), evaluation(0.85),
        )
        resp = client.post("/api/analyze/quick", json={"requirement": QUICK_REQUIREMENT})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json()["jd_report"]["job_count"] == 2

        rows = list_royalties_by_creator(app_db_path, CREATOR_ID)
        assert len(rows) == 2
        assert sum(r["amount"] for r in rows) == 140
        runs = list_agent_runs_by_caller(app_db_path, CALLER_ID)
        assert len(runs) == 2
        assert all(run["charge_amount"] == 100 for run in runs)
        assert all(run["royalty_splits"]["platform"]["amount"] == 30 for run in runs)


def _splits_without_asset_id(run: dict) -> dict:
    return {
        party: {k: v for k, v in share.items() if k != "asset_id"}
        for party, share in run["royalty_splits"].items()
    }


def _v1_human_decision():
    """A v1-shaped decision: no estimated_hours / requires_judgment / is_recurring."""
    return {
        "task_id": TASK_HUMAN["id"],
        "task_name": TASK_HUMAN["name"],
        "task_type": TASK_HUMAN["type"],
        "task_description": TASK_HUMAN["description"],
        "evaluations": [],
        "recommendation": {"decision": "human", "reason": "需要人", "cost_hint": "需要评估薪资"},
    }
