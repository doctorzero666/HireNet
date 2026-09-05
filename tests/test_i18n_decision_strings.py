"""
WP-I18N-2 / D-D — the decision engine emits its fixed strings natively in both
languages, and the frontend regex mapping layer is gone.

This file REPLACES `tests/test_i18n_backend_strings.py`, which asserted that
every Chinese string `decision_policy` emits was matched by exactly one
pattern in `frontend/src/i18n/backendStrings.json`. That mechanism —
translating the backend's Chinese back into English in the browser — is
deleted: it needed a second, hand-maintained copy of every string, and a
string added on one side without the other silently fell back to Chinese
(which is exactly what happened to `summary.verdict`, and why
`AnalysisReport.jsx` grew a third, bespoke recomposition on top).

What is pinned here instead:

* Every branch of `decide()` and of the v1 `run_resource_decision`, plus all
  three `_build_decision_summary` verdicts, in BOTH languages — the Chinese
  side compared against the exact pre-change literal (the v1 red line), the
  English side asserted to contain no CJK at all.
* The route responses: `/api/analyze/decide` and `/api/analyze/quick`, under
  both `HIRENET_TASK_AGENT` values.

No test here touches the network: the analysis pipeline's one LLM factory is
replaced by `fake_llm`, and the resource evaluation — which is an LLM call —
is stubbed so what is under test is the policy's own strings, not model prose.
"""
import json

import pytest

import app.agents.agents as agents_module
import app.agents.job_design as job_design_module
import app.app as app_module
from app.agents.decision_policy import (
    HUMAN_COST_HINT,
    HUMAN_FALLBACK_REASON,
    HYBRID_COST_HINT,
    HYBRID_REASON,
    UNKNOWN_COST_HINT,
    decide,
)
from app.agents.task_analysis import EVALUATION_FALLBACK_REASON
from app.app import (
    VERDICT_AGENT_ONLY,
    VERDICT_HUMAN_ONLY,
    VERDICT_HYBRID,
    _build_decision_summary,
)
from tests.test_analyze_routes_v1 import (
    CANNED_TASKS,
    COMPLETE_RESPONSE,
    QUICK_REQUIREMENT,
    CountingStub,
)
from tests.test_i18n_helpers import CJK_PATTERN, assert_clean_english, assert_no_cjk
from tests.test_task_analysis_agent import build_agent, eval_json


def english_eval_json(confidence, reason="Strong capability match"):
    """`eval_json` with its Chinese defaults (`estimated_time`, `strengths`)
    replaced — this stands in for what the model returns in an English
    session, so a CJK hit can only come from HireNet's own strings."""
    return eval_json(
        confidence, reason=reason, estimated_time="2 hours", strengths=["Relevant experience"]
    )


@pytest.fixture(autouse=True)
def _guard_no_real_llm(no_real_llm_client):
    """No test in this module may construct the real OpenAI client."""


def _eval(resource_id, resource_name, resource_type, confidence):
    return {
        "resource_id": resource_id,
        "resource_name": resource_name,
        "resource_type": resource_type,
        "confidence": confidence,
        # LLM prose; in a real English session the model writes it in English.
        # Kept language-neutral here so a CJK hit can only come from the policy.
        "reason": "stubbed evaluation",
        "strengths": [],
    }


AGENT_EVAL_EN = _eval("agent_code", "Code Generation Agent", "agent", 0.9)
AGENT_EVAL_ZH = _eval("agent_code", "代码生成 Agent", "agent", 0.9)
HUMAN_EVAL_EN = _eval("candidate_a", "Wei Zhang (Full-stack Engineer)", "human", 0.8)
HUMAN_EVAL_ZH = _eval("candidate_a", "张伟（全栈工程师）", "human", 0.8)


# ─── decide(): the Chinese side is byte-identical to v1 ───────────────────────


class TestDecideDefaultsToTheExactV1Chinese:
    def test_agent_branch(self):
        rec = decide([AGENT_EVAL_ZH])
        assert rec["reason"] == "推荐使用 代码生成 Agent，置信度 90%"
        assert rec["cost_hint"] == "$0.05"

    def test_human_branch(self):
        rec = decide([HUMAN_EVAL_ZH])
        assert rec["reason"] == "建议招聘 张伟（全栈工程师） 类型人才，置信度 80%"
        assert rec["cost_hint"] == "需要评估薪资"

    def test_hybrid_branch(self):
        rec = decide([_eval("agent_code", "代码生成 Agent", "agent", 0.6)])
        assert rec["reason"] == "建议人机协同：Agent 完成基础部分，人工处理复杂判断"
        assert rec["cost_hint"] == "混合成本"

    def test_human_fallback_branch(self):
        rec = decide([_eval("candidate_a", "张伟（全栈工程师）", "human", 0.3)])
        assert rec["reason"] == "此任务需要人类处理，建议招聘"
        assert rec["cost_hint"] == "需要评估薪资"

    def test_zero_evaluation_branch(self):
        rec = decide([])
        assert rec["reason"] == "此任务需要人类处理，建议招聘"
        assert rec["cost_hint"] == "需要评估薪资"

    def test_unknown_cost_hint(self):
        rec = decide([_eval("agent_unlisted", "未登记 Agent", "agent", 0.9)])
        assert rec["cost_hint"] == "未知"

    @pytest.mark.parametrize("lang", [None, "zh"])
    def test_zh_and_absent_are_the_same_output(self, lang):
        assert decide([AGENT_EVAL_ZH], lang=lang) == decide([AGENT_EVAL_ZH])


class TestDecideInEnglish:
    def test_agent_branch(self):
        rec = decide([AGENT_EVAL_EN], lang="en")
        assert rec["reason"] == "Recommended: Code Generation Agent (confidence 90%)"
        assert rec["cost_hint"] == "$0.05"
        assert_no_cjk(rec, "decide agent branch")

    def test_human_branch(self):
        rec = decide([HUMAN_EVAL_EN], lang="en")
        assert rec["reason"] == (
            "Hire a Wei Zhang (Full-stack Engineer)-type candidate (confidence 80%)"
        )
        assert rec["cost_hint"] == HUMAN_COST_HINT["en"]
        assert_no_cjk(rec, "decide human branch")

    def test_hybrid_branch(self):
        rec = decide([_eval("agent_code", "Code Generation Agent", "agent", 0.6)], lang="en")
        assert rec["reason"] == HYBRID_REASON["en"]
        assert rec["cost_hint"] == HYBRID_COST_HINT["en"]
        assert_no_cjk(rec, "decide hybrid branch")

    def test_human_fallback_branch(self):
        rec = decide([_eval("candidate_a", "Wei Zhang", "human", 0.3)], lang="en")
        assert rec["reason"] == HUMAN_FALLBACK_REASON["en"]
        assert rec["cost_hint"] == HUMAN_COST_HINT["en"]
        assert_no_cjk(rec, "decide human fallback branch")

    def test_zero_evaluation_branch(self):
        rec = decide([], lang="en")
        assert rec == {
            "decision": "human",
            "reason": HUMAN_FALLBACK_REASON["en"],
            "cost_hint": HUMAN_COST_HINT["en"],
        }

    def test_unknown_cost_hint(self):
        rec = decide([_eval("agent_unlisted", "Unlisted Agent", "agent", 0.9)], lang="en")
        assert rec["cost_hint"] == UNKNOWN_COST_HINT["en"] == "Unknown"

    def test_every_emitted_string_constant_has_a_cjk_free_english_side(self):
        for name, node in (
            ("HUMAN_COST_HINT", HUMAN_COST_HINT),
            ("HYBRID_COST_HINT", HYBRID_COST_HINT),
            ("HYBRID_REASON", HYBRID_REASON),
            ("HUMAN_FALLBACK_REASON", HUMAN_FALLBACK_REASON),
            ("UNKNOWN_COST_HINT", UNKNOWN_COST_HINT),
            ("EVALUATION_FALLBACK_REASON", EVALUATION_FALLBACK_REASON),
            ("VERDICT_AGENT_ONLY", VERDICT_AGENT_ONLY),
            ("VERDICT_HUMAN_ONLY", VERDICT_HUMAN_ONLY),
            ("VERDICT_HYBRID", VERDICT_HYBRID),
        ):
            assert set(node) == {"zh", "en"}, name
            assert CJK_PATTERN.search(node["zh"]), f"{name}: zh side lost its Chinese"
            assert_no_cjk(node["en"], f"{name}['en']")


# ─── v1 run_resource_decision: the same strings, the same two languages ──────


def _install_stub_evaluator(monkeypatch):
    """Score agents high and humans low, echoing back the resource's own name."""
    def stub(resource, task, lang=None):
        return _eval(
            resource["id"], resource["name"], resource["type"],
            0.9 if resource["type"] == "agent" else 0.2,
        )
    monkeypatch.setattr(agents_module, "evaluate_resource_for_task", stub)


class TestV1RunResourceDecision:
    TASK = {
        "id": "t1", "name": "搭建 FAQ 知识库", "description": "整理历史工单",
        "type": "technical", "requires_judgment": False, "is_recurring": False,
        "estimated_hours": 16,
    }

    def test_lang_absent_is_the_exact_v1_chinese(self, monkeypatch):
        _install_stub_evaluator(monkeypatch)
        rec = agents_module.run_resource_decision([self.TASK])["decisions"][0]["recommendation"]
        assert rec["decision"] == "agent"
        assert rec["reason"].startswith("推荐使用 ")
        assert "，置信度 90%" in rec["reason"]

    def test_lang_en_names_the_english_resource_and_has_no_cjk(self, monkeypatch):
        _install_stub_evaluator(monkeypatch)
        decisions = agents_module.run_resource_decision([self.TASK], lang="en")
        rec = decisions["decisions"][0]["recommendation"]
        assert rec["reason"].startswith("Recommended: ")
        assert rec["reason"].endswith("(confidence 90%)")
        # The pool itself is built in English (D-B), so the quoted resource
        # name is English too — this is the join between the two commits.
        assert_no_cjk(rec, "v1 recommendation")


# ─── v2 TaskAnalysisAgent.decide_all ─────────────────────────────────────────


ENGLISH_POOL = [
    {"id": "agent_code", "type": "agent", "name": "Code Generation Agent",
     "capability_summary": "Frontend development, Backend development"},
]
CHINESE_POOL = [
    {"id": "agent_code", "type": "agent", "name": "代码生成 Agent",
     "capability_summary": "前端开发、后端开发"},
]
V2_TASK = {
    "id": "t1", "name": "Build the FAQ knowledge base", "description": "Import past tickets",
    "type": "technical", "estimated_hours": 16,
    "requires_judgment": False, "is_recurring": False,
}


class TestV2DecideAll:
    def test_lang_en_reaches_the_policy_through_the_agent(self, fake_llm):
        agent = build_agent(fake_llm, lang="en", resource_pool=ENGLISH_POOL)
        agent.state["tasks"] = [V2_TASK]
        fake_llm.queue(english_eval_json(0.9))
        rec = agent.decide_all()["decisions"][0]["recommendation"]
        assert rec["reason"] == "Recommended: Code Generation Agent (confidence 90%)"
        assert_no_cjk(rec, "v2 recommendation")

    def test_lang_absent_is_the_chinese_policy_string(self, fake_llm):
        agent = build_agent(fake_llm, resource_pool=CHINESE_POOL)
        agent.state["tasks"] = [dict(V2_TASK, name="搭建 FAQ 知识库", description="整理历史工单")]
        fake_llm.queue(eval_json(0.9))
        rec = agent.decide_all()["decisions"][0]["recommendation"]
        assert rec["reason"] == "推荐使用 代码生成 Agent，置信度 90%"

    def test_unparseable_evaluation_fallback_reason_follows_lang(self, fake_llm):
        agent = build_agent(fake_llm, lang="en", resource_pool=ENGLISH_POOL)
        agent.state["tasks"] = [V2_TASK]
        fake_llm.queue("not json at all")
        decision = agent.decide_all()["decisions"][0]
        assert decision["evaluations"][0]["reason"] == EVALUATION_FALLBACK_REASON["en"]
        assert_no_cjk(decision["evaluations"][0], "v2 fallback evaluation")

    def test_unparseable_evaluation_fallback_reason_defaults_to_chinese(self, fake_llm):
        agent = build_agent(fake_llm, resource_pool=CHINESE_POOL)
        agent.state["tasks"] = [dict(V2_TASK, name="搭建 FAQ 知识库")]
        fake_llm.queue("not json at all")
        decision = agent.decide_all()["decisions"][0]
        assert decision["evaluations"][0]["reason"] == "评估超时，使用默认分数"


# ─── _build_decision_summary: the verdict ────────────────────────────────────


def _decisions(*kinds):
    return {"decisions": [{"recommendation": {"decision": k}} for k in kinds]}


EMPTY_JD_REPORT = {"needs_hiring": False, "job_count": 0, "average_water_score": None}


class TestDecisionSummaryVerdict:
    @pytest.mark.parametrize("kinds, expected", [
        (("agent", "agent"), "无需招聘，所有任务可由 Agent 完成"),
        (("human", "hybrid"), "建议招聘，当前 Agent 无法满足需求"),
        (("agent", "human", "hybrid"), "建议混合方案：1 个任务用 Agent，2 个任务需要人类"),
    ])
    def test_lang_absent_is_the_exact_pre_change_chinese(self, kinds, expected):
        summary = _build_decision_summary([], _decisions(*kinds), EMPTY_JD_REPORT)
        assert summary["verdict"] == expected

    @pytest.mark.parametrize("kinds, verdict_type, expected", [
        (("agent", "agent"), "agent_only", VERDICT_AGENT_ONLY["en"]),
        (("human", "hybrid"), "human_only", VERDICT_HUMAN_ONLY["en"]),
        (("agent", "human", "hybrid"), "hybrid",
         "Recommended: a mixed plan — 1 task(s) via Agent, 2 task(s) need a human"),
    ])
    def test_lang_en(self, kinds, verdict_type, expected):
        summary = _build_decision_summary([], _decisions(*kinds), EMPTY_JD_REPORT, lang="en")
        assert summary["verdict"] == expected
        assert summary["verdict_type"] == verdict_type
        assert_no_cjk(summary, "decision summary")

    def test_the_structured_fields_are_unchanged_in_both_languages(self):
        kinds = ("agent", "human", "hybrid")
        zh = _build_decision_summary([], _decisions(*kinds), EMPTY_JD_REPORT)
        en = _build_decision_summary([], _decisions(*kinds), EMPTY_JD_REPORT, lang="en")
        assert {k: v for k, v in zh.items() if k != "verdict"} == \
               {k: v for k, v in en.items() if k != "verdict"}


# ─── Routes ───────────────────────────────────────────────────────────────────

ENGLISH_TASKS = [
    {"id": "t1", "name": "Build the FAQ knowledge base",
     "description": "Import past tickets into a knowledge base", "type": "technical",
     "estimated_hours": 16, "requires_judgment": False, "is_recurring": False},
    {"id": "t2", "name": "Handle escalated complaints",
     "description": "Deal with complaints that need judgment", "type": "operational",
     "estimated_hours": 40, "requires_judgment": True, "is_recurring": True},
]

ENGLISH_JOB_DESIGN = {
    "job_title": "Customer Success Specialist",
    "core_responsibilities": ["Handle escalated complaints", "Codify scripts"],
    "required_skills": ["Communication", "Ticketing systems"],
    "nice_to_have_skills": ["E-commerce experience"],
    "experience_range": {"min": 1, "max": 3, "unit": "years"},
    "salary_range": {"min": 12000, "max": 18000, "unit": "CNY/month"},
    "work_type": "full-time",
    "water_score": 82,
}


def _stub_v1_pipeline(monkeypatch, tasks, job_design):
    """Stub the two LLM stages around the decision engine, keep the engine real."""
    monkeypatch.setattr(
        app_module, "decompose_tasks", CountingStub(result={"tasks": tasks})
    )
    monkeypatch.setattr(
        job_design_module, "design_job", CountingStub(result=dict(job_design))
    )
    _install_stub_evaluator(monkeypatch)


class TestQuickRouteV1:
    def test_lang_en_response_has_no_cjk_anywhere(self, client, monkeypatch, fake_llm):
        monkeypatch.setenv("HIRENET_TASK_AGENT", "v1")
        _stub_v1_pipeline(monkeypatch, ENGLISH_TASKS, ENGLISH_JOB_DESIGN)
        res = client.post(
            "/api/analyze/quick",
            json={"requirement": {"project_name": "Support tooling",
                                  "core_description": "Build a backend service",
                                  "duration": "3 months"},
                  "lang": "en"},
        )
        assert res.status_code == 200, res.get_data(as_text=True)
        payload = assert_clean_english(res, "/api/analyze/quick?lang=en")
        assert payload["summary"]["verdict"] == VERDICT_AGENT_ONLY["en"]
        for decision in payload["decisions"]["decisions"]:
            assert decision["recommendation"]["reason"].startswith("Recommended: ")

    def test_lang_absent_keeps_the_exact_chinese_verdict(self, client, monkeypatch, fake_llm):
        monkeypatch.setenv("HIRENET_TASK_AGENT", "v1")
        _stub_v1_pipeline(monkeypatch, CANNED_TASKS, {"job_title": "客户成功专员",
                                                      "core_responsibilities": [],
                                                      "required_skills": [],
                                                      "water_score": 80})
        res = client.post("/api/analyze/quick", json={"requirement": QUICK_REQUIREMENT})
        assert res.status_code == 200, res.get_data(as_text=True)
        payload = res.get_json()
        assert payload["summary"]["verdict"] == "无需招聘，所有任务可由 Agent 完成"
        assert payload["decisions"]["decisions"][0]["recommendation"]["reason"].startswith(
            "推荐使用 "
        )


class TestDecideRouteV1:
    def test_the_session_lang_reaches_the_verdict_and_the_reasons(
        self, client, monkeypatch, fake_llm
    ):
        monkeypatch.setenv("HIRENET_TASK_AGENT", "v1")
        _stub_v1_pipeline(monkeypatch, ENGLISH_TASKS, ENGLISH_JOB_DESIGN)

        fake_llm.queue(COMPLETE_RESPONSE)
        start = client.post(
            "/api/analyze/start", json={"message": "Build a support system", "lang": "en"}
        )
        assert start.status_code == 200, start.get_data(as_text=True)
        session_id = start.get_json()["session_id"]

        res = client.post("/api/analyze/decide", json={"session_id": session_id})
        assert res.status_code == 200, res.get_data(as_text=True)
        payload = res.get_json()
        # `requirement` is LLM output from a Chinese canned response, so only
        # the parts this commit owns are asserted CJK-free.
        assert_no_cjk(payload["summary"], "/api/analyze/decide summary")
        assert_no_cjk(payload["decisions"], "/api/analyze/decide decisions")

    def test_lang_absent_keeps_the_chinese_verdict(self, client, monkeypatch, fake_llm):
        monkeypatch.setenv("HIRENET_TASK_AGENT", "v1")
        _stub_v1_pipeline(monkeypatch, CANNED_TASKS, {"job_title": "客户成功专员",
                                                      "core_responsibilities": [],
                                                      "required_skills": [],
                                                      "water_score": 80})
        fake_llm.queue(COMPLETE_RESPONSE)
        start = client.post("/api/analyze/start", json={"message": "搭建智能客服系统"})
        session_id = start.get_json()["session_id"]
        res = client.post("/api/analyze/decide", json={"session_id": session_id})
        assert res.status_code == 200, res.get_data(as_text=True)
        assert res.get_json()["summary"]["verdict"] == "无需招聘，所有任务可由 Agent 完成"


class TestQuickRouteV2:
    """The v2 pipeline runs the real TaskAnalysisAgent, so every stage is a
    scripted LLM response: decompose, then one evaluation per shortlisted
    resource. `design_job` stays stubbed — it is a separate LLM call."""

    def _queue_v2(self, fake_llm, tasks, scripted_evaluation):
        fake_llm.queue(json.dumps({"tasks": tasks}, ensure_ascii=False))
        # Generous: one scripted evaluation per (task, resource) pair the
        # shortlist can produce. Unused entries are simply never popped.
        for _ in range(len(tasks) * 8):
            fake_llm.queue(scripted_evaluation(None))

    def test_lang_en_response_has_no_cjk_anywhere(self, client, monkeypatch, fake_llm):
        monkeypatch.setenv("HIRENET_TASK_AGENT", "v2")
        monkeypatch.setattr(
            job_design_module, "design_job", CountingStub(result=dict(ENGLISH_JOB_DESIGN))
        )
        self._queue_v2(fake_llm, ENGLISH_TASKS, lambda r: english_eval_json(0.9))
        res = client.post(
            "/api/analyze/quick",
            json={"requirement": {"project_name": "Support tooling",
                                  "core_description": "Build a backend service",
                                  "duration": "3 months"},
                  "lang": "en"},
        )
        assert res.status_code == 200, res.get_data(as_text=True)
        payload = assert_clean_english(res, "/api/analyze/quick?lang=en (v2)")
        assert payload["summary"]["verdict"] == VERDICT_AGENT_ONLY["en"]

    def test_lang_absent_keeps_the_chinese_verdict(self, client, monkeypatch, fake_llm):
        monkeypatch.setenv("HIRENET_TASK_AGENT", "v2")
        monkeypatch.setattr(
            job_design_module, "design_job",
            CountingStub(result={"job_title": "客户成功专员", "core_responsibilities": [],
                                 "required_skills": [], "water_score": 80}),
        )
        self._queue_v2(fake_llm, CANNED_TASKS, lambda r: eval_json(0.9))
        res = client.post("/api/analyze/quick", json={"requirement": QUICK_REQUIREMENT})
        assert res.status_code == 200, res.get_data(as_text=True)
        payload = res.get_json()
        assert payload["summary"]["verdict"] == "无需招聘，所有任务可由 Agent 完成"
        assert payload["decisions"]["decisions"][0]["recommendation"]["reason"].startswith(
            "推荐使用 "
        )


# ─── jd_report's own fixed strings ───────────────────────────────────────────


class TestJdReportFixedStrings:
    """`jd_report.message` and `water_interpretation` ride in the /decide and
    /quick responses, so they are part of the same contract as the decision
    strings — the audit had them filed as "latent", but the no-CJK sweep of
    /api/analyze/quick catches them."""

    def test_no_hiring_message_defaults_to_the_exact_chinese(self):
        report = job_design_module.generate_jd_report(
            _decisions("agent", "agent"), {}, original_description=""
        )
        assert report["message"] == "所有任务均可由 Agent 完成，无需招聘"

    def test_no_hiring_message_in_english(self):
        report = job_design_module.generate_jd_report(
            _decisions("agent", "agent"), {}, original_description="", lang="en"
        )
        assert report["message"] == job_design_module.NO_HIRING_MESSAGE["en"]
        assert_no_cjk(report, "jd_report (no hiring)")

    @pytest.mark.parametrize("score, expected", [
        (90, "JD 描述与实际需求高度一致，信息可信度高"),
        (75, "JD 描述较为准确，有少量优化空间"),
        (60, "JD 存在中等程度失真，已进行关键修正"),
        (40, "原始 JD 存在较多水分，本次进行了大幅优化"),
        (10, "原始需求描述严重失真，建议重新沟通确认"),
    ])
    def test_every_water_band_defaults_to_the_exact_chinese(self, score, expected):
        assert job_design_module._interpret_water_score(score) == expected

    @pytest.mark.parametrize("score", [90, 75, 60, 40, 10])
    def test_every_water_band_has_an_english_side(self, score):
        assert_no_cjk(
            job_design_module._interpret_water_score(score, "en"),
            f"water_interpretation({score}, 'en')",
        )
