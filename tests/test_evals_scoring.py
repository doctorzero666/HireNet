"""Stage 1 / WP4 — deterministic tests for the eval harness itself.

The harness is the instrument the v1-vs-v2 decision is read off, so it needs
its own regression tests: a scorer that quietly awards a free point moves the
D13 verdict just as surely as a change to the pipeline.

**No test in this file touches the network.** Every LLM response is canned, and
the judge tests drive a scripted fake client. `evals.run_eval` — the only
module that makes real calls — is deliberately not imported here.

Coverage:
  * all five §3 components, pass and fail;
  * the two scorer contracts g18 depends on (empty `must_include` scores 1.0;
    `count_range` lower bound 0 makes zero tasks a pass);
  * `must_include` constraints that the golden set omits are skipped, not failed;
  * the failed-run path (structural 0);
  * judge parsing: clean, fenced, prose-wrapped, repaired-once, unrepairable;
  * simulated employer: script order, default line, hard cap;
  * counting proxy: usage capture, retry on 429/5xx, no retry on 400, budget stop;
  * the D13 gate — the single PASS/FAIL line WP5 acts on, including that an
    unmeasurable mean is a FAIL rather than a default pass.
"""
import json

import pytest

from evals.judge import build_judge_input, judge_case
from evals.llm_proxy import BudgetExceeded, CountingLLMProxy, classify_stage, is_retryable
from evals.report import d13_verdict
from evals.scoring import (
    COMPONENT_NAMES,
    decision_counts,
    failure_bullets,
    load_golden_set,
    routing_by_task_id,
    score_case,
    select_cases,
)
from evals.simulated_employer import DEFAULT_REPLY, SimulatedEmployer
from tests.conftest import FakeLLMClient


# ──────────────────────────────────────────────────────────────────────────────
# Canned fixtures — a golden case and a decide-response, both hand-written so a
# change in the real golden set cannot silently change what these tests assert.
# ──────────────────────────────────────────────────────────────────────────────

def make_case(**overrides) -> dict:
    case = {
        "id": "t01",
        "category": "test",
        "input": {"initial_message": "我要做一个客服系统", "clarifications": ["预算 5 万"]},
        "expected": {
            "requirement": {
                "core_description_keywords_any": ["客服"],
                "duration": "one-time",
                "budget_hint": "medium",
            },
            "tasks": {
                "count_range": [2, 3],
                "must_include": [
                    {"name_keywords_any": ["话术"], "type": "creative", "routing": "agent",
                     "requires_judgment": False},
                    {"name_keywords_any": ["对接"], "type": "technical"},
                ],
                "must_not_include_keywords": ["融资"],
            },
            "decisions": {"agent_min": 1, "human_max": 1},
        },
        "judge_rubric": "1–5: 拆解是否合理",
        "review_status": "draft-needs-human-review",
    }
    for key, value in overrides.items():
        case["expected"][key] = value
    return case


def make_result(**overrides) -> dict:
    result = {
        "requirement": {
            "project_name": "智能客服",
            "core_description": "为电商平台搭建智能客服系统",
            "duration": "one-time",
            "budget_hint": "medium",
        },
        "tasks": [
            {"id": "t1", "name": "编写客服话术库", "description": "常见问题话术",
             "type": "creative", "estimated_hours": 16, "requires_judgment": False},
            {"id": "t2", "name": "系统对接开发", "description": "对接订单系统",
             "type": "technical", "estimated_hours": 40, "requires_judgment": True},
        ],
        "decisions": {"decisions": [
            {"task_id": "t1", "task_name": "编写客服话术库", "task_type": "creative",
             "evaluations": [], "recommendation": {"decision": "agent", "reason": "x", "cost_hint": "y"}},
            {"task_id": "t2", "task_name": "系统对接开发", "task_type": "technical",
             "evaluations": [], "recommendation": {"decision": "human", "reason": "x", "cost_hint": "y"}},
        ]},
    }
    result.update(overrides)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# The five §3 components
# ──────────────────────────────────────────────────────────────────────────────

def test_perfect_case_scores_one_on_every_component():
    score = score_case(make_case(), make_result())
    assert score["structural_score"] == 1.0
    assert set(score["components"]) == set(COMPONENT_NAMES)
    assert all(value == 1.0 for value in score["components"].values())


def test_requirement_component_is_a_ratio_of_the_asserted_fields():
    result = make_result()
    result["requirement"]["duration"] = "ongoing"  # 1 of 3 requirement checks now fails
    score = score_case(make_case(), result)
    assert score["components"]["requirement"] == pytest.approx(2 / 3)


def test_requirement_null_fields_are_not_checked():
    """`null` in the golden set means 'do not check' (schema_note), not 'must be null'."""
    case = make_case(requirement={"core_description_keywords_any": ["客服"],
                                  "duration": None, "budget_hint": None})
    result = make_result()
    result["requirement"]["duration"] = "ongoing"
    result["requirement"]["budget_hint"] = "low"
    score = score_case(case, result)
    assert score["components"]["requirement"] == 1.0


def test_requirement_component_is_skipped_when_nothing_is_asserted():
    case = make_case(requirement={"core_description_keywords_any": [],
                                  "duration": None, "budget_hint": None})
    score = score_case(case, make_result())
    assert score["components"]["requirement"] is None
    # …and the mean is taken over the four surviving components only.
    assert score["structural_score"] == 1.0


def test_task_count_out_of_range_is_zero():
    result = make_result()
    result["tasks"] = result["tasks"][:1]  # 1 task, range is [2, 3]
    score = score_case(make_case(), result)
    assert score["components"]["task_count"] == 0.0


def test_must_include_is_a_matched_ratio():
    result = make_result()
    result["tasks"][1]["name"] = "写一份周报"  # no longer matches the 对接 entry
    score = score_case(make_case(), result)
    assert score["components"]["must_include"] == 0.5


def test_must_include_entry_fails_when_the_type_is_wrong():
    result = make_result()
    result["tasks"][0]["type"] = "operational"  # expected creative
    score = score_case(make_case(), result)
    assert score["components"]["must_include"] == 0.5
    entry = score["details"]["must_include"][0]
    assert entry["passed"] is False
    assert entry["closest"]["type"] == {"expected": "creative", "actual": "operational"}


def test_must_include_entry_fails_when_the_routing_is_wrong():
    result = make_result()
    result["decisions"]["decisions"][0]["recommendation"]["decision"] = "human"
    score = score_case(make_case(), result)
    assert score["components"]["must_include"] == 0.5
    assert score["details"]["must_include"][0]["closest"]["routing"] == {
        "expected": "agent", "actual": "human"}


def test_must_include_entry_fails_when_requires_judgment_differs():
    result = make_result()
    result["tasks"][0]["requires_judgment"] = True  # expected False
    score = score_case(make_case(), result)
    assert score["components"]["must_include"] == 0.5


def test_must_not_include_is_all_or_nothing():
    result = make_result()
    result["tasks"][0]["description"] = "顺便帮我准备融资材料"
    score = score_case(make_case(), result)
    assert score["components"]["must_not_include"] == 0.0
    violations = score["details"]["must_not_include"]["violations"]
    assert violations == [{"task": "编写客服话术库", "keyword": "融资"}]


def test_must_not_include_is_skipped_when_the_list_is_empty():
    """g17 ships an empty list; an unstated expectation must not become a free point."""
    case = make_case()
    case["expected"]["tasks"]["must_not_include_keywords"] = []
    score = score_case(case, make_result())
    assert score["components"]["must_not_include"] is None


def test_decisions_distribution_bounds():
    case = make_case(decisions={"agent_min": 2})
    score = score_case(case, make_result())  # only 1 agent decision
    assert score["components"]["decisions"] == 0.0
    assert score["details"]["decisions"]["failures"] == [
        {"bound": "agent_min", "expected": 2, "actual": 1}]
    assert score["details"]["decisions"]["actual"] == {
        "agent": 1, "human": 1, "hybrid": 0, "none": 0}


def test_decisions_component_is_skipped_when_no_bounds_are_given():
    case = make_case(decisions={})
    score = score_case(case, make_result())
    assert score["components"]["decisions"] is None


def test_a_null_recommendation_counts_as_no_decision_not_a_crash():
    """v1 seeds `recommendation` with None when a task has no evaluations."""
    result = make_result()
    result["decisions"]["decisions"][0]["recommendation"] = None
    assert decision_counts(result["decisions"]) == {"agent": 0, "human": 1, "hybrid": 0, "none": 1}
    assert routing_by_task_id(result["decisions"]) == {"t2": "human"}


# ──────────────────────────────────────────────────────────────────────────────
# The two contracts g18 depends on (golden_set_review.md, ambiguity #9)
# ──────────────────────────────────────────────────────────────────────────────

def g18_shaped_case() -> dict:
    """The off-scope case's shape: empty must_include, count_range starting at 0."""
    return {
        "id": "g18-shaped",
        "category": "non-business",
        "input": {"initial_message": "今天天气不错", "clarifications": []},
        "expected": {
            "requirement": {"core_description_keywords_any": ["猫"],
                            "duration": "unknown", "budget_hint": "unknown"},
            "tasks": {"count_range": [0, 3], "must_include": [],
                      "must_not_include_keywords": ["招聘", "后端"]},
            "decisions": {"agent_max": 3, "human_max": 3},
        },
        "judge_rubric": "1–5",
    }


def test_contract_a_empty_must_include_scores_one():
    result = {
        "requirement": {"core_description": "养猫还是养狗", "duration": "unknown",
                        "budget_hint": "unknown"},
        "tasks": [],
        "decisions": {"decisions": []},
    }
    score = score_case(g18_shaped_case(), result)
    assert score["components"]["must_include"] == 1.0
    detail = score["details"]["must_include"][0]
    assert detail["passed"] is True and "contract" in detail["note"]


def test_contract_b_zero_tasks_passes_a_count_range_starting_at_zero():
    result = {
        "requirement": {"core_description": "养猫还是养狗", "duration": "unknown",
                        "budget_hint": "unknown"},
        "tasks": [],
        "decisions": {"decisions": []},
    }
    score = score_case(g18_shaped_case(), result)
    assert score["components"]["task_count"] == 1.0
    # Both contracts together make an honest "I produced nothing" a perfect case.
    assert score["structural_score"] == 1.0


def test_g18_still_fails_when_a_software_project_is_fabricated():
    result = {
        "requirement": {"core_description": "搭建一个后端服务", "duration": "one-time",
                        "budget_hint": "medium"},
        "tasks": [{"id": "t1", "name": "后端接口开发", "description": "写 API",
                   "type": "technical", "requires_judgment": False}],
        "decisions": {"decisions": [
            {"task_id": "t1", "recommendation": {"decision": "agent"}}]},
    }
    score = score_case(g18_shaped_case(), result)
    assert score["components"]["must_not_include"] == 0.0
    assert score["components"]["requirement"] == 0.0
    assert score["structural_score"] < 1.0


# ──────────────────────────────────────────────────────────────────────────────
# Omitted expectations are skipped, not failed
# ──────────────────────────────────────────────────────────────────────────────

def test_must_include_entry_without_routing_ignores_routing_entirely():
    """g03/g06/g11/g16 omit `routing` on purpose (review ambiguities #3, #4)."""
    case = make_case()
    case["expected"]["tasks"]["must_include"] = [{"name_keywords_any": ["话术"]}]
    for decision in ("agent", "human", "hybrid"):
        result = make_result()
        result["decisions"]["decisions"][0]["recommendation"]["decision"] = decision
        score = score_case(case, result)
        assert score["components"]["must_include"] == 1.0, decision
        assert "routing" not in (score["details"]["must_include"][0]["closest"] or {})


def test_must_include_entry_with_only_keywords_ignores_type_and_judgment():
    case = make_case()
    case["expected"]["tasks"]["must_include"] = [{"name_keywords_any": ["话术"]}]
    result = make_result()
    result["tasks"][0]["type"] = "strategic"
    result["tasks"][0]["requires_judgment"] = True
    assert score_case(case, result)["components"]["must_include"] == 1.0


def test_keyword_matching_is_case_insensitive_substring():
    case = make_case()
    case["expected"]["tasks"]["must_include"] = [{"name_keywords_any": ["API"]}]
    result = make_result()
    result["tasks"][0]["name"] = "Build the backend api layer"
    assert score_case(case, result)["components"]["must_include"] == 1.0


# ──────────────────────────────────────────────────────────────────────────────
# Failed runs
# ──────────────────────────────────────────────────────────────────────────────

def test_a_failed_run_scores_zero_on_every_component():
    score = score_case(make_case(), None)
    assert score["structural_score"] == 0.0
    assert all(value == 0.0 for value in score["components"].values())
    assert failure_bullets(score) == [
        "no result — the run failed; every component scored 0.0"]


def test_failure_bullets_quote_what_the_scorer_saw():
    result = make_result()
    result["requirement"]["duration"] = "ongoing"
    result["tasks"][1]["name"] = "写一份周报"
    bullets = failure_bullets(score_case(make_case(), result))
    assert any("requirement.duration" in b and "one-time" in b for b in bullets)
    assert any("missing task matching" in b and "对接" in b for b in bullets)


# ──────────────────────────────────────────────────────────────────────────────
# The committed golden set loads and matches the shape the scorer expects
# ──────────────────────────────────────────────────────────────────────────────

def test_committed_golden_set_has_20_reviewable_cases():
    golden = load_golden_set()
    assert len(golden["cases"]) == 20
    assert [c["id"] for c in golden["cases"]] == [f"g{i:02d}" for i in range(1, 21)]
    assert {c["review_status"] for c in golden["cases"]} == {"draft-needs-human-review"}


def test_every_committed_case_can_be_scored_without_raising():
    for case in load_golden_set()["cases"]:
        score = score_case(case, make_result())
        assert 0.0 <= score["structural_score"] <= 1.0


def test_select_cases_keeps_file_order_and_rejects_typos():
    golden = load_golden_set()
    assert [c["id"] for c in select_cases(golden, "g05,g01")] == ["g01", "g05"]
    assert len(select_cases(golden, "all")) == 20
    with pytest.raises(ValueError, match="unknown case id"):
        select_cases(golden, "g99")


# ──────────────────────────────────────────────────────────────────────────────
# The LLM judge — canned responses only
# ──────────────────────────────────────────────────────────────────────────────

def test_judge_parses_a_clean_json_answer():
    client = FakeLLMClient('{"score": 4, "rationale": "话术与对接分开了"}')
    verdict = judge_case(make_case(), make_result(), client, "fake-model")
    assert verdict == {"score": 4, "rationale": "话术与对接分开了", "repaired": False,
                       "error": None, "raw": '{"score": 4, "rationale": "话术与对接分开了"}'}
    assert client.call_count == 1


def test_judge_tolerates_fences_and_prose_via_parse_llm_json():
    client = FakeLLMClient('好的，我的评分如下：\n```json\n{"score": 3, "rationale": "一般"}\n```')
    verdict = judge_case(make_case(), make_result(), client, "fake-model")
    assert verdict["score"] == 3 and verdict["repaired"] is False


def test_judge_repairs_once_and_succeeds():
    client = FakeLLMClient("我觉得大概 4 分吧", '{"score": 4, "rationale": "拆解合理"}')
    verdict = judge_case(make_case(), make_result(), client, "fake-model")
    assert verdict["score"] == 4
    assert verdict["repaired"] is True
    assert client.call_count == 2
    # The repair turn replays the original messages plus the bad answer and the fix-up.
    repair_messages = client.calls[1]["messages"]
    assert repair_messages[-2]["content"] == "我觉得大概 4 分吧"
    assert "只输出这个对象" in repair_messages[-1]["content"]


def test_judge_gives_up_after_one_repair_and_scores_none():
    client = FakeLLMClient("还是不给 JSON", "依然不给 JSON")
    verdict = judge_case(make_case(), make_result(), client, "fake-model")
    assert verdict["score"] is None
    assert verdict["repaired"] is True
    assert "unparseable after one repair" in verdict["error"]
    assert client.call_count == 2


def test_judge_rejects_an_out_of_range_score_then_repairs():
    """Schema-checked, not just parsed: `score: 9` is not a judge answer."""
    client = FakeLLMClient('{"score": 9, "rationale": "很好"}',
                           '{"score": 5, "rationale": "很好"}')
    verdict = judge_case(make_case(), make_result(), client, "fake-model")
    assert verdict["score"] == 5 and verdict["repaired"] is True


def test_judge_does_not_call_the_model_for_a_failed_run():
    client = FakeLLMClient()  # any call would raise AssertionError
    verdict = judge_case(make_case(), None, client, "fake-model")
    assert verdict["score"] is None
    assert verdict["error"] == "run failed — not judged"
    assert client.call_count == 0


def test_judge_client_error_is_reported_not_raised():
    client = FakeLLMClient(RuntimeError("connection reset"))
    verdict = judge_case(make_case(), make_result(), client, "fake-model")
    assert verdict["score"] is None
    assert verdict["error"] == "RuntimeError: connection reset"


def test_judge_input_carries_the_rubric_the_tasks_and_the_routing():
    text = build_judge_input(make_case(), make_result())
    assert "1–5: 拆解是否合理" in text
    assert "编写客服话术库" in text
    assert "路由=agent" in text and "路由=human" in text
    # The employer's own words, so the judge grades against the request, not a summary.
    assert "我要做一个客服系统" in text and "预算 5 万" in text


def test_judge_input_says_so_when_nothing_was_produced():
    text = build_judge_input(make_case(), {"requirement": None, "tasks": [], "decisions": {}})
    assert "没有产出结构化需求" in text and "没有产出任何任务" in text


# ──────────────────────────────────────────────────────────────────────────────
# Simulated employer
# ──────────────────────────────────────────────────────────────────────────────

def test_employer_answers_the_script_in_order_then_the_default_line():
    employer = SimulatedEmployer(["答案一", "答案二"], max_turns=4)
    assert [employer.next_reply() for _ in range(4)] == [
        "答案一", "答案二", DEFAULT_REPLY, DEFAULT_REPLY]
    assert employer.script_exhausted is True
    assert employer.has_turns_left is False
    assert employer.hit_cap is True


def test_employer_refuses_to_speak_past_the_cap():
    employer = SimulatedEmployer([], max_turns=1)
    employer.next_reply()
    with pytest.raises(RuntimeError, match="turn cap"):
        employer.next_reply()


def test_employer_with_no_script_still_answers():
    assert SimulatedEmployer(None, max_turns=2).next_reply() == DEFAULT_REPLY


# ──────────────────────────────────────────────────────────────────────────────
# Counting proxy — measurement, retries, budget
# ──────────────────────────────────────────────────────────────────────────────

class _HTTPError(Exception):
    """Minimal stand-in for an OpenAI SDK error carrying an HTTP status."""

    def __init__(self, status_code, message="boom"):
        super().__init__(message)
        self.status_code = status_code


def test_proxy_records_usage_per_call_and_labels_the_stage():
    inner = FakeLLMClient("hello", "world")
    proxy = CountingLLMProxy(inner, sleep=lambda _s: None)
    proxy.set_context("g01", "pipeline")
    proxy.chat.completions.create(
        model="m", messages=[{"role": "system", "content": "你是任务拆解 Agent。"}])
    proxy.set_context("g01", "judge")
    proxy.chat.completions.create(model="m", messages=[{"role": "user", "content": "judge"}])

    pipeline = proxy.records_for("g01", "pipeline")
    assert len(pipeline) == 1
    assert pipeline[0]["stage"] == "decompose"
    assert pipeline[0]["input_tokens"] == 11 and pipeline[0]["output_tokens"] == 22
    assert proxy.totals(pipeline) == {"calls": 1, "input_tokens": 11, "output_tokens": 22,
                                      "total_tokens": 33, "time_ms": pipeline[0]["time_ms"]}
    assert proxy.records_for("g01", "judge")[0]["stage"] == "other"
    assert proxy.total_tokens == 66


def test_classify_stage_recognises_both_pipelines_prompts():
    assert classify_stage([{"content": "你是 HireNet 的岗位设计 Agent。"}]) == "job_design"
    assert classify_stage([{"content": "你是 HireNet 的需求分析 Agent。"}]) == "clarify"
    assert classify_stage([{"content": "评估资源是否能完成任务。"}]) == "evaluate"
    assert classify_stage([{"content": "unrecognised"}]) == "other"


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retryable_statuses(status):
    assert is_retryable(_HTTPError(status)) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_client_errors_are_not_retried(status):
    assert is_retryable(_HTTPError(status)) is False


def test_proxy_retries_a_429_then_succeeds():
    inner = FakeLLMClient(_HTTPError(429), _HTTPError(503), "ok")
    slept: list[float] = []
    proxy = CountingLLMProxy(inner, base_delay=1.0, sleep=slept.append)
    proxy.set_context("g01")
    resp = proxy.chat.completions.create(model="m", messages=[{"content": "x"}])
    assert resp.choices[0].message.content == "ok"
    assert slept == [1.0, 2.0]  # exponential
    assert proxy.records[0]["attempts"] == 3
    assert len(proxy.retry_events) == 2


def test_proxy_does_not_retry_a_400():
    inner = FakeLLMClient(_HTTPError(400, "bad request"), "never reached")
    proxy = CountingLLMProxy(inner, sleep=lambda _s: None)
    with pytest.raises(_HTTPError):
        proxy.chat.completions.create(model="m", messages=[{"content": "x"}])
    assert proxy.retry_events == []


def test_proxy_gives_up_after_max_retries():
    inner = FakeLLMClient(*[_HTTPError(503) for _ in range(5)])
    proxy = CountingLLMProxy(inner, max_retries=5, sleep=lambda _s: None)
    with pytest.raises(_HTTPError):
        proxy.chat.completions.create(model="m", messages=[{"content": "x"}])
    assert inner.call_count == 5


def test_proxy_flags_the_budget_then_refuses_the_next_call():
    inner = FakeLLMClient("a", "b")
    proxy = CountingLLMProxy(inner, budget_tokens=40, sleep=lambda _s: None)
    proxy.set_context("g01")
    proxy.chat.completions.create(model="m", messages=[{"content": "x"}])  # 33 tokens
    assert proxy.budget_exceeded is False
    proxy.chat.completions.create(model="m", messages=[{"content": "x"}])  # 66 > 40
    assert proxy.budget_exceeded is True
    with pytest.raises(BudgetExceeded, match="token budget 40 exhausted"):
        proxy.chat.completions.create(model="m", messages=[{"content": "x"}])
    assert inner.call_count == 2  # the third call never reached the provider


def test_proxy_is_json_serialisable_so_records_can_be_written_to_the_raw_dir():
    inner = FakeLLMClient("a")
    proxy = CountingLLMProxy(inner, sleep=lambda _s: None)
    proxy.set_context("g01")
    proxy.chat.completions.create(model="m", messages=[{"content": "x"}])
    json.dumps(proxy.records)  # must not raise


# ──────────────────────────────────────────────────────────────────────────────
# The D13 gate — the one number WP5 acts on, so it is arithmetic with a test
# ──────────────────────────────────────────────────────────────────────────────

def test_d13_passes_when_v2_is_no_worse_and_not_more_than_20_percent_dearer():
    gate = d13_verdict(0.60, 0.72, 100_000, 119_000)
    assert gate["verdict"] == "PASS"
    assert gate["quality_ok"] and gate["cost_ok"]
    assert gate["ceiling"] == 120_000


def test_d13_ties_pass_on_both_halves():
    """'>=' and '<=', not '>' and '<': a tie is explicitly good enough."""
    assert d13_verdict(0.60, 0.60, 100_000, 120_000)["verdict"] == "PASS"


def test_d13_fails_on_a_quality_regression_however_cheap():
    gate = d13_verdict(0.60, 0.59, 100_000, 1)
    assert gate["verdict"] == "FAIL"
    assert gate["quality_ok"] is False and gate["cost_ok"] is True


def test_d13_fails_on_a_cost_regression_however_good():
    gate = d13_verdict(0.10, 0.99, 100_000, 120_001)
    assert gate["verdict"] == "FAIL"
    assert gate["quality_ok"] is True and gate["cost_ok"] is False


def test_d13_unmeasurable_quality_is_a_fail_not_a_default_pass():
    assert d13_verdict(None, 0.9, 100_000, 100)["verdict"] == "FAIL"
    assert d13_verdict(0.9, None, 100_000, 100)["verdict"] == "FAIL"
