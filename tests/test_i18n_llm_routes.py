"""
WP-I18N-2 / D-E — the LLM routes that ignored `lang` until now.

`/api/analyze/{start,reply,decide,quick}` already threaded it (WP-I18N / I2,
pinned by tests/test_i18n_lang_param.py). Everything else produced Chinese
prose no matter what the client asked for: `/api/apply`'s cover letter,
`/api/career/*`, `/api/candidate/analyze` (whose prompt literally demanded
"用中文输出"), and the three `/api/mcp` tools.

The assertion is the same one `lang_support` is built around, applied per
call site:

  * `lang == "en"`  -> the messages list actually sent to the model carries
    `LANG_SUFFIX` on its system prompt (or gains a leading system message
    consisting of the suffix, for the calls that have no system prompt);
  * `lang` absent   -> the messages list is BYTE-IDENTICAL to the pre-i18n
    one. The prompt constants themselves are never modified.

No test here touches the network — every LLM call goes through `fake_llm` or
an explicitly injected `FakeLLMClient`.
"""
import json

import pytest

import app.agents.agents as agents_module
import app.agents.application_agent as application_agent_module
from app.agents.agents import CareerStrategyAgent
from app.agents.application_agent import COVER_LETTER_PROMPT, generate_cover_letter
from app.agents.lang_support import LANG_SUFFIX
from tests.conftest import FakeLLMClient


@pytest.fixture(autouse=True)
def _guard_no_real_llm(no_real_llm_client):
    """No test in this module may construct the real OpenAI client."""


COVER_LETTER_JSON = json.dumps({
    "subject": "Application",
    "cover_letter": "Body text.",
    "key_match_points": ["a", "b"],
    "match_score": 88,
}, ensure_ascii=False)

PROFILE = {
    "id": "candidate_a", "type": "human", "name": "Wei Zhang",
    "bio": "Full-stack engineer", "skills": ["React"], "experience": ["3 years"],
}
JOB_DESIGN = {
    "job_id": "demo_job_1", "job_title": "Full-stack Engineer",
    "company": "A technology startup",
    "core_responsibilities": ["Build the frontend"], "required_skills": ["React"],
}


# ─── generate_cover_letter (POST /api/apply) ─────────────────────────────────


@pytest.fixture
def fake_cover_letter_llm(monkeypatch):
    """`application_agent` builds its own client via `_get_llm()`, not the
    shared `get_llm_client` factory — so that is the seam to replace."""
    client = FakeLLMClient()
    monkeypatch.setattr(application_agent_module, "_get_llm", lambda: client)
    return client


class TestGenerateCoverLetter:
    def test_lang_en_appends_the_suffix_to_the_system_prompt(self, fake_cover_letter_llm):
        fake_cover_letter_llm.queue(COVER_LETTER_JSON)
        generate_cover_letter(PROFILE, JOB_DESIGN, lang="en")
        messages = fake_cover_letter_llm.calls[0]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == COVER_LETTER_PROMPT + LANG_SUFFIX
        assert messages[1]["role"] == "user"

    @pytest.mark.parametrize("lang", [None, "zh"])
    def test_lang_absent_or_zh_is_byte_identical_to_the_v1_constant(
        self, fake_cover_letter_llm, lang
    ):
        fake_cover_letter_llm.queue(COVER_LETTER_JSON)
        generate_cover_letter(PROFILE, JOB_DESIGN, lang=lang)
        messages = fake_cover_letter_llm.calls[0]["messages"]
        assert len(messages) == 2
        assert messages[0]["content"] == COVER_LETTER_PROMPT
        assert LANG_SUFFIX not in messages[0]["content"]

    def test_the_prompt_constant_itself_is_never_mutated(self, fake_cover_letter_llm):
        before = COVER_LETTER_PROMPT
        fake_cover_letter_llm.queue(COVER_LETTER_JSON, COVER_LETTER_JSON)
        generate_cover_letter(PROFILE, JOB_DESIGN, lang="en")
        generate_cover_letter(PROFILE, JOB_DESIGN, lang="en")
        assert application_agent_module.COVER_LETTER_PROMPT == before
        # …and the suffix is applied once per call, never accumulated.
        assert fake_cover_letter_llm.calls[1]["messages"][0]["content"] == (
            COVER_LETTER_PROMPT + LANG_SUFFIX
        )


class TestApplyRoute:
    def _apply(self, client, fake_cover_letter_llm, body):
        fake_cover_letter_llm.queue(COVER_LETTER_JSON)
        return client.post("/api/apply", json=body)

    def test_body_lang_en_reaches_the_cover_letter_prompt(
        self, client, fake_cover_letter_llm
    ):
        res = self._apply(client, fake_cover_letter_llm, {
            "candidate_id": "candidate_a", "job_design": JOB_DESIGN, "lang": "en",
        })
        assert res.status_code == 200, res.get_data(as_text=True)
        assert fake_cover_letter_llm.calls[0]["messages"][0]["content"] == (
            COVER_LETTER_PROMPT + LANG_SUFFIX
        )
        assert res.get_json()["application"]["status"] == "Submitted"

    def test_query_lang_en_works_too(self, client, fake_cover_letter_llm):
        res = self._apply(client, fake_cover_letter_llm, {
            "candidate_id": "candidate_a", "job_design": JOB_DESIGN,
        })
        assert res.status_code == 200
        # No lang anywhere -> unchanged Chinese path.
        assert fake_cover_letter_llm.calls[0]["messages"][0]["content"] == COVER_LETTER_PROMPT
        assert res.get_json()["application"]["status"] == "已投递"

    def test_lang_absent_leaves_the_wire_format_untouched(
        self, client, fake_cover_letter_llm
    ):
        res = self._apply(client, fake_cover_letter_llm, {
            "candidate_id": "candidate_a", "job_design": JOB_DESIGN,
        })
        assert res.status_code == 200
        assert len(fake_cover_letter_llm.calls[0]["messages"]) == 2


# ─── CareerStrategyAgent (/api/career/*) ─────────────────────────────────────


STRATEGY = {
    "summary": "s", "directions": [], "focus_skills": [], "avoid": "a", "encouragement": "e",
}
STRATEGY_READY = "[STRATEGY_READY]\n" + json.dumps(STRATEGY, ensure_ascii=False)


class TestCareerStrategyAgent:
    def test_lang_en_appends_the_suffix(self, fake_llm):
        agent = CareerStrategyAgent(lang="en")
        fake_llm.queue("first turn")
        agent.start("I am a backend engineer")
        assert fake_llm.calls[0]["messages"][0]["content"] == (
            agents_module.CAREER_STRATEGY_SYSTEM_PROMPT + LANG_SUFFIX
        )

    @pytest.mark.parametrize("lang", [None, "zh"])
    def test_lang_absent_is_byte_identical_to_the_v1_constant(self, fake_llm, lang):
        agent = CareerStrategyAgent(lang=lang)
        fake_llm.queue("first turn")
        agent.start("我是后端工程师")
        assert fake_llm.calls[0]["messages"][0]["content"] == (
            agents_module.CAREER_STRATEGY_SYSTEM_PROMPT
        )

    def test_the_suffix_is_reapplied_fresh_each_turn_not_accumulated(self, fake_llm):
        agent = CareerStrategyAgent(lang="en")
        fake_llm.queue("turn one", "turn two", "turn three")
        agent.start("I am a backend engineer")
        agent.reply("I want to move into AI")
        agent.reply("Budget is flexible")
        for call in fake_llm.calls:
            content = call["messages"][0]["content"]
            assert content.count(LANG_SUFFIX) == 1, content
        # The stored history never carries the directive.
        assert agent.history[0]["content"] == agents_module.CAREER_STRATEGY_SYSTEM_PROMPT

    def test_force_generate_strategy_also_carries_the_directive(self, fake_llm):
        agent = CareerStrategyAgent(lang="en")
        fake_llm.queue("turn one", json.dumps(STRATEGY, ensure_ascii=False))
        agent.start("I am a backend engineer")
        agent.force_generate_strategy()
        assert fake_llm.calls[1]["messages"][0]["content"] == (
            agents_module.CAREER_STRATEGY_SYSTEM_PROMPT + LANG_SUFFIX
        )

    def test_force_generate_strategy_without_lang_is_unchanged(self, fake_llm):
        agent = CareerStrategyAgent()
        fake_llm.queue("turn one", json.dumps(STRATEGY, ensure_ascii=False))
        agent.start("我是后端工程师")
        agent.force_generate_strategy()
        assert fake_llm.calls[1]["messages"][0]["content"] == (
            agents_module.CAREER_STRATEGY_SYSTEM_PROMPT
        )


class TestCareerRoutes:
    def test_start_threads_lang_and_reply_reuses_it(self, client, fake_llm):
        fake_llm.queue("first turn")
        res = client.post("/api/career/start", json={"message": "I am a backend engineer", "lang": "en"})
        assert res.status_code == 200, res.get_data(as_text=True)
        session_id = res.get_json()["session_id"]
        assert fake_llm.calls[0]["messages"][0]["content"].endswith(LANG_SUFFIX)

        # /reply says nothing about lang -> the session's "en" carries over.
        fake_llm.queue("second turn")
        res = client.post(
            "/api/career/reply", json={"session_id": session_id, "message": "more context"}
        )
        assert res.status_code == 200, res.get_data(as_text=True)
        assert fake_llm.calls[1]["messages"][0]["content"].endswith(LANG_SUFFIX)

        # …and so does /generate.
        fake_llm.queue(json.dumps(STRATEGY, ensure_ascii=False))
        res = client.post("/api/career/generate", json={"session_id": session_id})
        assert res.status_code == 200, res.get_data(as_text=True)
        assert fake_llm.calls[2]["messages"][0]["content"].endswith(LANG_SUFFIX)

    def test_lang_absent_keeps_the_v1_wire_format(self, client, fake_llm):
        fake_llm.queue("first turn")
        res = client.post("/api/career/start", json={"message": "我是后端工程师"})
        assert res.status_code == 200
        assert fake_llm.calls[0]["messages"][0]["content"] == (
            agents_module.CAREER_STRATEGY_SYSTEM_PROMPT
        )

    def test_reply_can_override_the_sessions_lang(self, client, fake_llm):
        fake_llm.queue("first turn")
        session_id = client.post(
            "/api/career/start", json={"message": "hello", "lang": "en"}
        ).get_json()["session_id"]
        fake_llm.queue("second turn")
        client.post(
            "/api/career/reply",
            json={"session_id": session_id, "message": "换成中文", "lang": "zh"},
        )
        assert fake_llm.calls[1]["messages"][0]["content"] == (
            agents_module.CAREER_STRATEGY_SYSTEM_PROMPT
        )

    @pytest.mark.parametrize("path, body", [
        ("/api/career/start", {"message": "hello", "lang": "fr"}),
    ])
    def test_unsupported_lang_is_400(self, client, fake_llm, path, body):
        res = client.post(path, json=body)
        assert res.status_code == 400
        assert res.get_json() == {"error": "unsupported lang"}
        assert fake_llm.call_count == 0

    def test_unsupported_lang_is_400_on_reply_and_generate(self, client, fake_llm):
        fake_llm.queue("first turn")
        session_id = client.post(
            "/api/career/start", json={"message": "hello"}
        ).get_json()["session_id"]
        for path in ("/api/career/reply", "/api/career/generate"):
            res = client.post(path, json={"session_id": session_id, "message": "x", "lang": "de"})
            assert res.status_code == 400, path
            assert res.get_json() == {"error": "unsupported lang"}


# ─── /api/candidate/analyze ──────────────────────────────────────────────────


class TestCandidateAnalyzeRoute:
    BODY = {"profile": {"id": "candidate_a", "skills": ["React"]}}

    def test_the_prompt_no_longer_demands_chinese(self, client, fake_llm):
        fake_llm.queue("- point one")
        res = client.post("/api/candidate/analyze", json=self.BODY)
        assert res.status_code == 200, res.get_data(as_text=True)
        prompt = fake_llm.calls[0]["messages"][-1]["content"]
        assert "用中文输出" not in prompt

    def test_lang_en_inserts_a_leading_system_message(self, client, fake_llm):
        fake_llm.queue("- point one\n- point two")
        res = client.post("/api/candidate/analyze", json=dict(self.BODY, lang="en"))
        assert res.status_code == 200, res.get_data(as_text=True)
        messages = fake_llm.calls[0]["messages"]
        assert messages[0] == {"role": "system", "content": LANG_SUFFIX}
        assert messages[1]["role"] == "user"

    def test_lang_absent_sends_exactly_one_user_message(self, client, fake_llm):
        fake_llm.queue("- 优势一")
        res = client.post("/api/candidate/analyze", json=self.BODY)
        assert res.status_code == 200
        messages = fake_llm.calls[0]["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_query_param_lang_also_works(self, client, fake_llm):
        fake_llm.queue("- point one")
        res = client.post("/api/candidate/analyze?lang=en", json=self.BODY)
        assert res.status_code == 200
        assert fake_llm.calls[0]["messages"][0] == {"role": "system", "content": LANG_SUFFIX}


# ─── /api/mcp ────────────────────────────────────────────────────────────────


def _rpc(client, tool, arguments):
    return client.post("/api/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    })


class TestMcpToolLangArgument:
    def test_analyze_requirements_lang_en(self, client, fake_llm):
        fake_llm.queue("a clarifying question")
        res = _rpc(client, "hirenet_analyze_requirements",
                   {"description": "Build a support system", "lang": "en"})
        assert res.status_code == 200, res.get_data(as_text=True)
        assert fake_llm.calls[0]["messages"][0]["content"] == (
            agents_module.REQUIREMENT_SYSTEM_PROMPT + LANG_SUFFIX
        )

    def test_analyze_requirements_lang_absent_is_unchanged(self, client, fake_llm):
        fake_llm.queue("一个澄清问题")
        res = _rpc(client, "hirenet_analyze_requirements", {"description": "搭建客服系统"})
        assert res.status_code == 200
        assert fake_llm.calls[0]["messages"][0]["content"] == (
            agents_module.REQUIREMENT_SYSTEM_PROMPT
        )

    def test_career_strategy_lang_en(self, client, fake_llm):
        fake_llm.queue("first turn", json.dumps(STRATEGY, ensure_ascii=False))
        res = _rpc(client, "hirenet_career_strategy",
                   {"background": "Backend engineer, 5 years", "lang": "en"})
        assert res.status_code == 200, res.get_data(as_text=True)
        assert fake_llm.calls[0]["messages"][0]["content"].endswith(LANG_SUFFIX)

    def test_match_candidates_lang_en_uses_the_english_pool(self, client, fake_llm):
        for _ in range(6):
            fake_llm.queue(json.dumps({
                "can_complete": True, "confidence": 0.8, "reason": "Good fit",
                "estimated_time": "2 hours", "strengths": ["Relevant experience"],
            }, ensure_ascii=False))
        res = _rpc(client, "hirenet_match_candidates",
                   {"job_title": "Full-stack Engineer", "requirements": "React", "lang": "en"})
        assert res.status_code == 200, res.get_data(as_text=True)
        matches = json.loads(res.get_json()["result"]["content"][0]["text"])
        assert matches, "expected at least one human candidate"
        assert all("candidate" in m for m in matches)
        names = [m["candidate"]["name"] for m in matches]
        assert "Wei Zhang (Full-stack Engineer)" in names

    def test_get_jobs_lang_en_returns_english_jobs(self, client):
        res = _rpc(client, "hirenet_get_jobs", {"lang": "en"})
        assert res.status_code == 200
        jobs = json.loads(res.get_json()["result"]["content"][0]["text"])
        assert [j["job_id"] for j in jobs] == ["demo_job_1", "demo_job_2", "demo_job_3"]
        assert jobs[0]["job_title"] == "Full-stack Engineer"

    def test_get_jobs_lang_absent_is_unchanged(self, client):
        res = _rpc(client, "hirenet_get_jobs", {})
        jobs = json.loads(res.get_json()["result"]["content"][0]["text"])
        assert jobs[0]["job_title"] == "全栈工程师"

    def test_unsupported_lang_is_an_invalid_params_error(self, client, fake_llm):
        res = _rpc(client, "hirenet_get_jobs", {"lang": "fr"})
        assert res.status_code == 400
        error = res.get_json()["error"]
        assert error["code"] == -32602
        assert error["message"] == "unsupported lang"
        assert fake_llm.call_count == 0
