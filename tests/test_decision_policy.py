"""
Stage 1 / WP3a — unit tests for the pure routing policy (D7).

Two jobs:

1. Cover every branch of `app/agents/decision_policy.py:decide()` with synthetic
   evaluations and no LLM — the thing that was impossible while the policy lived
   inside `run_resource_decision`.
2. Prove the emitted Chinese strings are byte-identical to v1's, by running the
   untouched v1 `run_resource_decision` over the same canned evaluations and
   comparing the two `recommendation` dicts (`test_matches_v1_*`). Three
   frontend cards render `reason` / `cost_hint` verbatim, so "equivalent" is not
   good enough here — it has to be equal.
"""
import pytest

import app.agents.agents as agents_module
from app.agents.candidate_profile import DEMO_AGENTS
from app.agents.decision_policy import (
    AGENT_CONFIDENCE_THRESHOLD,
    DEFAULT_COST_LOOKUP,
    HUMAN_CONFIDENCE_THRESHOLD,
    HUMAN_COST_HINT,
    HUMAN_FALLBACK_REASON,
    HYBRID_AGENT_CONFIDENCE_THRESHOLD,
    HYBRID_COST_HINT,
    HYBRID_REASON,
    UNKNOWN_COST_HINT,
    decide,
    sort_evaluations,
)


@pytest.fixture(autouse=True)
def _guard_no_real_llm(no_real_llm_client):
    """No test in this module may construct the real OpenAI client."""


def make_eval(resource_id, resource_name, resource_type, confidence=None, **extra):
    ev = {
        "resource_id": resource_id,
        "resource_name": resource_name,
        "resource_type": resource_type,
        "can_complete": True,
        "reason": "canned",
        "estimated_time": "2小时",
        "strengths": ["s1"],
    }
    if confidence is not None:
        ev["confidence"] = confidence
    ev.update(extra)
    return ev


CODE_AGENT = lambda c: make_eval("agent_code", "代码生成 Agent", "agent", c)          # noqa: E731
CONTENT_AGENT = lambda c: make_eval("agent_content", "文案撰写 Agent", "agent", c)     # noqa: E731
FULLSTACK = lambda c: make_eval("candidate_a", "张伟（全栈工程师）", "human", c)        # noqa: E731
PM = lambda c: make_eval("candidate_b", "李娜（产品经理）", "human", c)                 # noqa: E731

TASK = {
    "id": "t1",
    "name": "搭建工单系统",
    "description": "对接现有客服工单系统",
    "type": "technical",
    "estimated_hours": 16,
    "requires_judgment": False,
    "is_recurring": False,
}


# ─── The four branches ────────────────────────────────────────────────────────

def test_agent_branch_above_threshold():
    rec = decide([CODE_AGENT(0.9)], TASK)
    assert rec == {
        "decision": "agent",
        "resource": CODE_AGENT(0.9),
        "reason": "推荐使用 代码生成 Agent，置信度 90%",
        "cost_hint": "$0.05",
    }


def test_agent_branch_is_inclusive_at_the_threshold():
    rec = decide([CODE_AGENT(AGENT_CONFIDENCE_THRESHOLD)], TASK)
    assert rec["decision"] == "agent"
    assert rec["reason"] == "推荐使用 代码生成 Agent，置信度 70%"


def test_human_branch_above_threshold():
    rec = decide([FULLSTACK(0.82)], TASK)
    assert rec == {
        "decision": "human",
        "resource": FULLSTACK(0.82),
        "reason": "建议招聘 张伟（全栈工程师） 类型人才，置信度 82%",
        "cost_hint": HUMAN_COST_HINT,
    }
    assert rec["cost_hint"] == "需要评估薪资"


def test_human_branch_is_inclusive_at_the_threshold():
    rec = decide([PM(HUMAN_CONFIDENCE_THRESHOLD)], TASK)
    assert rec["decision"] == "human"
    assert rec["reason"] == "建议招聘 李娜（产品经理） 类型人才，置信度 60%"


def test_hybrid_when_agent_misses_its_bar_but_clears_the_hybrid_bar():
    # Top is an agent at 0.65: below 0.7 (agent bar) but at/above 0.5 (hybrid bar).
    rec = decide([CODE_AGENT(0.65), FULLSTACK(0.4)], TASK)
    assert rec == {
        "decision": "hybrid",
        "resource": CODE_AGENT(0.65),
        "reason": HYBRID_REASON,
        "cost_hint": HYBRID_COST_HINT,
    }
    assert rec["reason"] == "建议人机协同：Agent 完成基础部分，人工处理复杂判断"
    assert rec["cost_hint"] == "混合成本"


def test_hybrid_resource_is_the_overall_top_not_the_top_agent():
    """v1 quirk, preserved: the hybrid card can name a human (agents.py:437)."""
    rec = decide([FULLSTACK(0.55), CODE_AGENT(0.5)], TASK)
    assert rec["decision"] == "hybrid"
    assert rec["resource"]["resource_type"] == "human"


def test_hybrid_is_inclusive_at_the_agent_bar():
    rec = decide([CODE_AGENT(HYBRID_AGENT_CONFIDENCE_THRESHOLD)], TASK)
    assert rec["decision"] == "hybrid"


def test_human_fallback_when_nobody_clears_any_bar():
    rec = decide([FULLSTACK(0.45), CODE_AGENT(0.3)], TASK)
    assert rec == {
        "decision": "human",
        "resource": FULLSTACK(0.45),
        "reason": HUMAN_FALLBACK_REASON,
        "cost_hint": HUMAN_COST_HINT,
    }
    assert rec["reason"] == "此任务需要人类处理，建议招聘"


def test_human_fallback_when_only_a_weak_human_was_evaluated():
    rec = decide([PM(0.2)], TASK)
    assert rec["decision"] == "human"
    assert rec["reason"] == HUMAN_FALLBACK_REASON


# ─── D5: never None, even with nothing to go on ───────────────────────────────

def test_zero_evaluations_returns_the_human_recommendation():
    rec = decide([], TASK)
    assert rec == {
        "decision": "human",
        "reason": "此任务需要人类处理，建议招聘",
        "cost_hint": "需要评估薪资",
    }


def test_zero_evaluations_omits_resource_rather_than_writing_null():
    """`task_decision.json` types `resource` as an object; null would fail it."""
    assert "resource" not in decide([], TASK)


@pytest.mark.parametrize(
    "evaluations",
    [
        [],
        [CODE_AGENT(0.99)],
        [FULLSTACK(0.99)],
        [CODE_AGENT(0.55)],
        [FULLSTACK(0.1), CONTENT_AGENT(0.1)],
        [make_eval("x", "X", "agent")],  # confidence key missing entirely
    ],
)
def test_decide_never_returns_none_and_always_carries_the_three_keys(evaluations):
    rec = decide(evaluations, TASK)
    assert rec is not None
    assert rec["decision"] in {"agent", "human", "hybrid"}
    assert rec["reason"] and isinstance(rec["reason"], str)
    assert rec["cost_hint"] and isinstance(rec["cost_hint"], str)


# ─── Ordering and defaults ────────────────────────────────────────────────────

def test_evaluations_are_ranked_by_confidence_regardless_of_input_order():
    rec = decide([FULLSTACK(0.3), CODE_AGENT(0.95), CONTENT_AGENT(0.5)], TASK)
    assert rec["decision"] == "agent"
    assert rec["resource"]["resource_id"] == "agent_code"


def test_missing_confidence_sorts_as_zero():
    ranked = sort_evaluations([make_eval("x", "X", "agent"), CODE_AGENT(0.1)])
    assert [e["resource_id"] for e in ranked] == ["agent_code", "x"]


def test_sort_is_stable_for_equal_confidence():
    ranked = sort_evaluations([CONTENT_AGENT(0.5), CODE_AGENT(0.5)])
    assert [e["resource_id"] for e in ranked] == ["agent_content", "agent_code"]


def test_sort_does_not_mutate_the_caller_list():
    evaluations = [FULLSTACK(0.1), CODE_AGENT(0.9)]
    sort_evaluations(evaluations)
    assert [e["resource_id"] for e in evaluations] == ["candidate_a", "agent_code"]


def test_agent_with_no_known_cost_falls_back_to_the_v1_default_hint():
    rec = decide([make_eval("agent_unlisted", "未登记 Agent", "agent", 0.9)], TASK)
    assert rec["cost_hint"] == UNKNOWN_COST_HINT == "未知"


def test_default_cost_lookup_mirrors_the_demo_fixtures():
    assert DEFAULT_COST_LOOKUP == {
        agent_id: spec["cost_per_task"] for agent_id, spec in DEMO_AGENTS.items()
    }
    assert DEFAULT_COST_LOOKUP["agent_content"] == "$0.02"


def test_cost_lookup_is_injectable():
    rec = decide(
        [CODE_AGENT(0.9)],
        TASK,
        cost_lookup={"agent_code": "$1.23"},
    )
    assert rec["cost_hint"] == "$1.23"


def test_injected_lookup_replaces_rather_than_extends_the_default():
    rec = decide([CODE_AGENT(0.9)], TASK, cost_lookup={})
    assert rec["cost_hint"] == UNKNOWN_COST_HINT


def test_task_argument_does_not_change_the_v1_policy_outcome():
    """The `task` parameter exists for future task-aware rules; today it is inert."""
    evaluations = [CODE_AGENT(0.9)]
    assert decide(evaluations, None) == decide(evaluations, TASK)
    assert decide(evaluations, {"type": "operational", "requires_judgment": True}) == decide(
        evaluations, TASK
    )


# ─── Byte-identity with v1 ────────────────────────────────────────────────────

def _v1_recommendation(monkeypatch, evaluations):
    """Run the untouched v1 `run_resource_decision` over canned evaluations.

    `_filter_resources_for_task` and `evaluate_resource_for_task` are stubbed so
    the v1 code path runs its real sort + threshold + prose logic on exactly the
    evaluations we hand it, with no LLM and no demo-resource coupling.
    """
    queue = list(evaluations)
    monkeypatch.setattr(
        agents_module,
        "_filter_resources_for_task",
        lambda task, resources: [{"id": e["resource_id"]} for e in queue],
    )
    monkeypatch.setattr(
        agents_module,
        "evaluate_resource_for_task",
        lambda resource, task, **kw: next(e for e in queue if e["resource_id"] == resource["id"]),
    )
    out = agents_module.run_resource_decision([TASK])
    return out["decisions"][0]["recommendation"]


@pytest.mark.parametrize(
    "evaluations",
    [
        pytest.param([CODE_AGENT(0.9)], id="agent-branch"),
        pytest.param([FULLSTACK(0.82)], id="human-branch"),
        pytest.param([CODE_AGENT(0.65), FULLSTACK(0.4)], id="hybrid-branch"),
        pytest.param([FULLSTACK(0.45), CODE_AGENT(0.3)], id="human-fallback-branch"),
        pytest.param([make_eval("agent_unlisted", "未登记 Agent", "agent", 0.9)], id="unknown-cost"),
    ],
)
def test_matches_v1_byte_for_byte(monkeypatch, evaluations):
    assert decide(evaluations, TASK) == _v1_recommendation(monkeypatch, evaluations)


def test_v1_emits_none_where_the_policy_now_emits_a_human_recommendation(monkeypatch):
    """Pins the one deliberate difference (D5): the zero-evaluation case."""
    assert _v1_recommendation(monkeypatch, []) is None
    assert decide([], TASK)["decision"] == "human"
