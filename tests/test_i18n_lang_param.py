"""
WP-I18N / I2 — optional `lang` on POST /api/analyze/{start,reply,quick}, and
the output-language directive it drives through every LLM call in a session.

Two layers of coverage, deliberately kept separate:

  * Function-level (this is the same style `tests/test_prompts.py` uses):
    drive the production functions the routes call — `RequirementAnalysisAgent`,
    `decompose_tasks`, `_llm_evaluate_resource`, `design_job` (v1) and
    `TaskAnalysisAgent` (v2) — directly with `fake_llm`, and inspect the
    `messages` it actually received. `lang="en"` must append
    `lang_support.LANG_SUFFIX` to the system prompt; `lang` absent/None must
    leave the wire format byte-identical to the v1 constants / v2 prompt
    files, so `tests/test_prompts.py` and the eval baseline keep meaning what
    they measure.

  * Route-level: `lang="fr"` -> 400 `{"error": "unsupported lang"}` on all
    three routes, under both the v1 (default) and v2 (`HIRENET_TASK_AGENT=v2`)
    flags; and an end-to-end session shows /start's `lang` choice survives
    into /reply and /decide without either endpoint being told again.

No test in this file may touch the network — see the autouse guard below.
"""
import json

import pytest

import app.agents.agents as agents_module
import app.agents.job_design as job_design_module
import app.app as app_module
from app.agents.lang_support import LANG_SUFFIX, normalize_lang
from app.agents.prompts import load_prompt
from app.agents.task_analysis import TaskAnalysisAgent
from tests.test_analyze_routes_v1 import (
    CANNED_DECISIONS,
    CANNED_JOB_DESIGN,
    CANNED_TASKS,
    CLARIFYING_QUESTION,
    COMPLETE_RESPONSE,
    QUICK_REQUIREMENT,
    REQUIREMENT,
    CountingStub,
    start_session,
)
from tests.test_prompts import RESOURCE
from tests.test_prompts import TASK as RESOURCE_TASK
from tests.test_task_analysis_agent import (
    POOL,
    TASKS_RESPONSE,
    build_agent,
    eval_json,
)
from tests.test_task_analysis_agent import COMPLETE_RESPONSE as V2_COMPLETE_RESPONSE


@pytest.fixture(autouse=True)
def _guard_no_real_llm(no_real_llm_client):
    """No test in this module may construct the real OpenAI client."""


# ──────────────────────────────────────────────────────────────────────────────
# normalize_lang — the pure validation helper both routes and this file lean on
# ──────────────────────────────────────────────────────────────────────────────

class TestNormalizeLang:
    def test_absent_defaults_to_zh(self):
        assert normalize_lang(None) == "zh"

    def test_empty_string_defaults_to_zh(self):
        assert normalize_lang("") == "zh"

    def test_zh_passes_through(self):
        assert normalize_lang("zh") == "zh"

    def test_en_passes_through(self):
        assert normalize_lang("en") == "en"

    @pytest.mark.parametrize("bad", ["fr", "EN", "zh-CN", "english", 1, True])
    def test_anything_else_is_none(self, bad):
        assert normalize_lang(bad) is None


# ──────────────────────────────────────────────────────────────────────────────
# Function-level (v1): RequirementAnalysisAgent
# ──────────────────────────────────────────────────────────────────────────────

class TestV1RequirementAgentLangSuffix:
    def test_lang_en_appends_suffix_to_the_system_prompt(self, fake_llm):
        fake_llm.queue(CLARIFYING_QUESTION)
        agent = agents_module.RequirementAnalysisAgent(lang="en")
        agent.start("搭建智能客服系统")

        system_msg = fake_llm.calls[0]["messages"][0]
        assert system_msg["role"] == "system"
        assert system_msg["content"] == agents_module.REQUIREMENT_SYSTEM_PROMPT + LANG_SUFFIX

    def test_lang_absent_is_byte_identical_to_the_v1_constant(self, fake_llm):
        fake_llm.queue(CLARIFYING_QUESTION)
        agent = agents_module.RequirementAnalysisAgent()
        agent.start("搭建智能客服系统")

        system_msg = fake_llm.calls[0]["messages"][0]
        assert system_msg["content"] == agents_module.REQUIREMENT_SYSTEM_PROMPT

    def test_suffix_is_reapplied_fresh_each_turn_not_accumulated(self, fake_llm):
        """Multi-turn: the suffix must not double up, and `self.history` must
        stay unsuffixed across turns — with_lang_messages never mutates its
        input, it returns a fresh copy on every call."""
        fake_llm.queue(CLARIFYING_QUESTION, COMPLETE_RESPONSE)
        agent = agents_module.RequirementAnalysisAgent(lang="en")
        agent.start("搭建智能客服系统")
        agent.reply("需要长期运营")

        expected = agents_module.REQUIREMENT_SYSTEM_PROMPT + LANG_SUFFIX
        assert fake_llm.calls[0]["messages"][0]["content"] == expected
        assert fake_llm.calls[1]["messages"][0]["content"] == expected
        # The suffix appears exactly once, not twice.
        assert fake_llm.calls[1]["messages"][0]["content"].count(LANG_SUFFIX) == 1
        # self.history (replayed into every future call) stays pristine.
        assert agent.history[0]["content"] == agents_module.REQUIREMENT_SYSTEM_PROMPT


# ──────────────────────────────────────────────────────────────────────────────
# Function-level (v1): decompose_tasks
# ──────────────────────────────────────────────────────────────────────────────

class TestV1DecomposeTasksLangSuffix:
    def test_lang_en(self, fake_llm):
        fake_llm.queue('{"tasks": []}')
        agents_module.decompose_tasks(REQUIREMENT, lang="en")

        system_msg = fake_llm.calls[0]["messages"][0]
        assert system_msg["role"] == "system"
        assert system_msg["content"] == agents_module.DECOMPOSITION_SYSTEM_PROMPT + LANG_SUFFIX

    def test_lang_absent_is_byte_identical_to_the_v1_constant(self, fake_llm):
        fake_llm.queue('{"tasks": []}')
        agents_module.decompose_tasks(REQUIREMENT)

        system_msg = fake_llm.calls[0]["messages"][0]
        assert system_msg["content"] == agents_module.DECOMPOSITION_SYSTEM_PROMPT

    def test_lang_zh_is_also_byte_identical(self, fake_llm):
        """"zh" is today's behaviour, not a distinct code path from absent."""
        fake_llm.queue('{"tasks": []}')
        agents_module.decompose_tasks(REQUIREMENT, lang="zh")

        system_msg = fake_llm.calls[0]["messages"][0]
        assert system_msg["content"] == agents_module.DECOMPOSITION_SYSTEM_PROMPT


# ──────────────────────────────────────────────────────────────────────────────
# Function-level (v1): _llm_evaluate_resource — the one call with NO system
# message in its v1 wire format, so lang="en" must insert a leading one.
# ──────────────────────────────────────────────────────────────────────────────

class TestV1EvaluateResourceLangSuffix:
    def test_lang_en_inserts_a_leading_system_message(self, fake_llm):
        fake_llm.queue('{"can_complete": true, "confidence": 0.9, "reason": "ok"}')
        agents_module._llm_evaluate_resource(RESOURCE, RESOURCE_TASK, lang="en")

        messages = fake_llm.calls[0]["messages"]
        assert messages[0] == {"role": "system", "content": LANG_SUFFIX}
        assert messages[1]["role"] == "user"

    def test_lang_absent_has_no_system_message_at_all(self, fake_llm):
        fake_llm.queue('{"can_complete": true, "confidence": 0.9, "reason": "ok"}')
        agents_module._llm_evaluate_resource(RESOURCE, RESOURCE_TASK)

        messages = fake_llm.calls[0]["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"


# ──────────────────────────────────────────────────────────────────────────────
# Function-level (v1): design_job
# ──────────────────────────────────────────────────────────────────────────────

class TestV1DesignJobLangSuffix:
    def test_lang_en(self, fake_llm):
        fake_llm.queue(json.dumps(CANNED_JOB_DESIGN, ensure_ascii=False))
        job_design_module.design_job(
            REQUIREMENT, CANNED_TASKS[1], "raw description", lang="en",
        )

        system_msg = fake_llm.calls[0]["messages"][0]
        assert system_msg["role"] == "system"
        assert system_msg["content"] == job_design_module.JOB_DESIGN_SYSTEM_PROMPT + LANG_SUFFIX

    def test_lang_absent_is_byte_identical_to_the_v1_constant(self, fake_llm):
        fake_llm.queue(json.dumps(CANNED_JOB_DESIGN, ensure_ascii=False))
        job_design_module.design_job(REQUIREMENT, CANNED_TASKS[1], "raw description")

        system_msg = fake_llm.calls[0]["messages"][0]
        assert system_msg["content"] == job_design_module.JOB_DESIGN_SYSTEM_PROMPT


# ──────────────────────────────────────────────────────────────────────────────
# Function-level (v2): TaskAnalysisAgent — one seam (_chat) covers every stage
# ──────────────────────────────────────────────────────────────────────────────

class TestV2TaskAnalysisAgentLangSuffix:
    def test_clarify_stage_lang_en(self, fake_llm):
        agent = build_agent(fake_llm, lang="en")
        fake_llm.queue(CLARIFYING_QUESTION)
        agent.start("搭建智能客服系统")

        system_msg = fake_llm.calls[0]["messages"][0]
        assert system_msg["role"] == "system"
        assert system_msg["content"] == load_prompt("requirement_system") + LANG_SUFFIX

    def test_clarify_stage_lang_absent_is_byte_identical_to_the_prompt_file(self, fake_llm):
        agent = build_agent(fake_llm)
        fake_llm.queue(CLARIFYING_QUESTION)
        agent.start("搭建智能客服系统")

        system_msg = fake_llm.calls[0]["messages"][0]
        assert system_msg["content"] == load_prompt("requirement_system")

    def test_decompose_stage_lang_en(self, fake_llm):
        agent = build_agent(fake_llm, lang="en")
        fake_llm.queue(V2_COMPLETE_RESPONSE, TASKS_RESPONSE)
        agent.start("搭建智能客服系统")
        agent.decompose()

        decompose_system_msg = fake_llm.calls[1]["messages"][0]
        assert decompose_system_msg["role"] == "system"
        assert decompose_system_msg["content"] == load_prompt("decomposition_system") + LANG_SUFFIX

    def test_decompose_stage_lang_absent_is_byte_identical_to_the_prompt_file(self, fake_llm):
        agent = build_agent(fake_llm)
        fake_llm.queue(V2_COMPLETE_RESPONSE, TASKS_RESPONSE)
        agent.start("搭建智能客服系统")
        agent.decompose()

        decompose_system_msg = fake_llm.calls[1]["messages"][0]
        assert decompose_system_msg["content"] == load_prompt("decomposition_system")

    def test_evaluate_stage_lang_en_inserts_a_leading_system_message(self, fake_llm):
        """The resource-evaluation prompt has no system message in v2 either
        (a single "user" message, `_evaluate_resource` in task_analysis.py) —
        same shape as v1's `_llm_evaluate_resource`."""
        agent = build_agent(fake_llm, lang="en")
        fake_llm.queue(
            V2_COMPLETE_RESPONSE, TASKS_RESPONSE,
            eval_json(0.9), eval_json(0.5), eval_json(0.4), eval_json(0.75),
        )
        agent.start("搭建智能客服系统")
        agent.decompose()
        agent.decide_all()

        # calls[0]=clarify, [1]=decompose, [2:6]=the four evaluations.
        for call in fake_llm.calls[2:6]:
            messages = call["messages"]
            assert messages[0] == {"role": "system", "content": LANG_SUFFIX}
            assert messages[1]["role"] == "user"

    def test_evaluate_stage_lang_absent_has_no_system_message(self, fake_llm):
        agent = build_agent(fake_llm)
        fake_llm.queue(
            V2_COMPLETE_RESPONSE, TASKS_RESPONSE,
            eval_json(0.9), eval_json(0.5), eval_json(0.4), eval_json(0.75),
        )
        agent.start("搭建智能客服系统")
        agent.decompose()
        agent.decide_all()

        for call in fake_llm.calls[2:6]:
            messages = call["messages"]
            assert len(messages) == 1
            assert messages[0]["role"] == "user"

    def test_from_state_reconstruction_keeps_the_lang_it_is_given(self, fake_llm):
        """`lang` lives on the agent instance, not `self.state` (it is
        per-session route config, not conversational state) — `from_state`
        must still honour whatever `lang` its caller passes for the new
        instance, exactly like `app.app._v2_agent` does every request."""
        agent = build_agent(fake_llm, lang="en")
        fake_llm.queue(CLARIFYING_QUESTION)
        agent.start("搭建智能客服系统")
        state = agent.to_state()

        rebuilt = TaskAnalysisAgent.from_state(
            state, llm_client=fake_llm, resource_pool=POOL, lang="en",
        )
        fake_llm.queue(COMPLETE_RESPONSE)
        rebuilt.reply("需要长期运营")

        system_msg = fake_llm.calls[-1]["messages"][0]
        assert system_msg["content"] == load_prompt("requirement_system") + LANG_SUFFIX


# ──────────────────────────────────────────────────────────────────────────────
# Route-level: lang="fr" -> 400 on all three routes, both task-agent flags
# ──────────────────────────────────────────────────────────────────────────────

UNSUPPORTED_LANG_BODY = {"error": "unsupported lang"}


class TestUnsupportedLangIs400:
    @pytest.mark.parametrize("task_agent_flag", ["v1", "v2"])
    def test_start(self, client, fake_llm, monkeypatch, task_agent_flag):
        monkeypatch.setenv("HIRENET_TASK_AGENT", task_agent_flag)
        resp = client.post(
            "/api/analyze/start", json={"message": "搭建智能客服系统", "lang": "fr"},
        )
        assert resp.status_code == 400
        assert resp.get_json() == UNSUPPORTED_LANG_BODY
        assert fake_llm.call_count == 0

    @pytest.mark.parametrize("task_agent_flag", ["v1", "v2"])
    def test_reply(self, client, fake_llm, monkeypatch, task_agent_flag):
        monkeypatch.setenv("HIRENET_TASK_AGENT", task_agent_flag)
        session_id, _ = start_session(
            client, fake_llm, response_text=CLARIFYING_QUESTION,
        )
        resp = client.post(
            "/api/analyze/reply",
            json={"session_id": session_id, "message": "需要长期运营", "lang": "fr"},
        )
        assert resp.status_code == 400
        assert resp.get_json() == UNSUPPORTED_LANG_BODY

    @pytest.mark.parametrize("task_agent_flag", ["v1", "v2"])
    def test_quick(self, client, monkeypatch, task_agent_flag):
        monkeypatch.setenv("HIRENET_TASK_AGENT", task_agent_flag)
        resp = client.post(
            "/api/analyze/quick",
            json={"requirement": QUICK_REQUIREMENT, "lang": "fr"},
        )
        assert resp.status_code == 400
        assert resp.get_json() == UNSUPPORTED_LANG_BODY


# ──────────────────────────────────────────────────────────────────────────────
# Route-level: /start's lang choice survives into /reply and /decide
# ──────────────────────────────────────────────────────────────────────────────

class TestV1RouteThreadsLangThroughTheWholeSession:
    def test_decide_passes_the_sessions_lang_to_every_module_level_call(
        self, client, fake_llm, monkeypatch
    ):
        stubs = {
            "decompose_tasks": CountingStub(result={"tasks": CANNED_TASKS}),
            "run_resource_decision": CountingStub(result=CANNED_DECISIONS),
            "design_job": CountingStub(result=dict(CANNED_JOB_DESIGN)),
        }
        monkeypatch.setattr(app_module, "decompose_tasks", stubs["decompose_tasks"])
        monkeypatch.setattr(app_module, "run_resource_decision", stubs["run_resource_decision"])
        monkeypatch.setattr(job_design_module, "design_job", stubs["design_job"])

        fake_llm.queue(COMPLETE_RESPONSE)
        start_resp = client.post(
            "/api/analyze/start", json={"message": "搭建智能客服系统", "lang": "en"},
        )
        assert start_resp.status_code == 200, start_resp.get_data(as_text=True)
        session_id = start_resp.get_json()["session_id"]

        # /decide takes no lang of its own — it must reuse "en" from /start.
        decide_resp = client.post("/api/analyze/decide", json={"session_id": session_id})
        assert decide_resp.status_code == 200, decide_resp.get_data(as_text=True)

        assert stubs["decompose_tasks"].calls[0][1]["lang"] == "en"
        assert stubs["run_resource_decision"].calls[0][1]["lang"] == "en"
        assert stubs["design_job"].calls[0][1]["lang"] == "en"

    def test_lang_absent_at_start_means_every_downstream_call_gets_zh(
        self, client, fake_llm, monkeypatch
    ):
        stubs = {
            "decompose_tasks": CountingStub(result={"tasks": CANNED_TASKS}),
            "run_resource_decision": CountingStub(result=CANNED_DECISIONS),
            "design_job": CountingStub(result=dict(CANNED_JOB_DESIGN)),
        }
        monkeypatch.setattr(app_module, "decompose_tasks", stubs["decompose_tasks"])
        monkeypatch.setattr(app_module, "run_resource_decision", stubs["run_resource_decision"])
        monkeypatch.setattr(job_design_module, "design_job", stubs["design_job"])

        session_id, _ = start_session(client, fake_llm, response_text=COMPLETE_RESPONSE)
        client.post("/api/analyze/decide", json={"session_id": session_id})

        assert stubs["decompose_tasks"].calls[0][1]["lang"] == "zh"
        assert stubs["run_resource_decision"].calls[0][1]["lang"] == "zh"
        assert stubs["design_job"].calls[0][1]["lang"] == "zh"

    def test_reply_can_override_the_sessions_lang_for_the_rest_of_the_session(
        self, client, fake_llm
    ):
        fake_llm.queue(CLARIFYING_QUESTION)
        start_resp = client.post(
            "/api/analyze/start", json={"message": "搭建智能客服系统", "lang": "en"},
        )
        session_id = start_resp.get_json()["session_id"]

        # /reply passes no lang -> the "en" from /start carries over.
        fake_llm.queue("再确认一个问题")
        client.post(
            "/api/analyze/reply",
            json={"session_id": session_id, "message": "需要长期运营"},
        )
        assert fake_llm.calls[1]["messages"][0]["content"] == (
            agents_module.REQUIREMENT_SYSTEM_PROMPT + LANG_SUFFIX
        )

        # /reply now passes lang="zh" explicitly -> overrides the session.
        fake_llm.queue(COMPLETE_RESPONSE)
        client.post(
            "/api/analyze/reply",
            json={"session_id": session_id, "message": "预算中等", "lang": "zh"},
        )
        assert fake_llm.calls[2]["messages"][0]["content"] == (
            agents_module.REQUIREMENT_SYSTEM_PROMPT
        )


class TestV2RouteThreadsLangThroughTheWholeSession:
    def test_reply_and_decide_reuse_the_lang_start_chose(
        self, client, fake_llm, monkeypatch
    ):
        monkeypatch.setenv("HIRENET_TASK_AGENT", "v2")

        fake_llm.queue(CLARIFYING_QUESTION)
        start_resp = client.post(
            "/api/analyze/start", json={"message": "搭建智能客服系统", "lang": "en"},
        )
        assert start_resp.status_code == 200, start_resp.get_data(as_text=True)
        session_id = start_resp.get_json()["session_id"]

        assert fake_llm.calls[0]["messages"][0]["content"] == (
            load_prompt("requirement_system") + LANG_SUFFIX
        )

        # /reply, still no lang of its own -> stays "en".
        fake_llm.queue(V2_COMPLETE_RESPONSE)
        reply_resp = client.post(
            "/api/analyze/reply",
            json={"session_id": session_id, "message": "需要长期运营"},
        )
        assert reply_resp.status_code == 200, reply_resp.get_data(as_text=True)
        assert fake_llm.calls[1]["messages"][0]["content"] == (
            load_prompt("requirement_system") + LANG_SUFFIX
        )

        # /decide: decompose stage must carry the suffix too.
        fake_llm.queue(TASKS_RESPONSE, eval_json(0.9), eval_json(0.5), eval_json(0.4), eval_json(0.75))
        decide_resp = client.post("/api/analyze/decide", json={"session_id": session_id})
        assert decide_resp.status_code == 200, decide_resp.get_data(as_text=True)
        decompose_call = fake_llm.calls[2]
        assert decompose_call["messages"][0]["content"] == (
            load_prompt("decomposition_system") + LANG_SUFFIX
        )
