"""
Pure routing policy for one task's resource evaluations (Stage 1 / D7).

This is the threshold logic that used to live inline in
`app/agents/agents.py:412-447` (`run_resource_decision`), lifted out so it can
be unit-tested with synthetic evaluations and no LLM.

Two hard constraints on this file:

1. **The Chinese strings are a UI contract, not prose.**
   `frontend/src/components/{AgentTaskCard,HiringTaskCard,HybridTaskCard}.jsx`
   render `recommendation.reason` and `recommendation.cost_hint` verbatim, and
   WP4 compares v1 against v2 on the same golden cases. Every string emitted
   below is byte-identical to the v1 branch it replaces — see the `v1:` comment
   on each branch for the source line.

2. **`decide()` never returns None.**
   v1 left `recommendation` as `None` when a task had zero evaluations
   (`agents.py:396` + the `if top:` guard at `:414`), and the three consumers
   read it with `.get("recommendation", {})` — a default that only applies to a
   *missing* key, not to a present `None`. D5 settles it: with zero evaluations
   emit the explicit human recommendation instead of a null.

v1 is left untouched; this module is used by the v2 `TaskAnalysisAgent` only.
"""
from typing import Mapping

from app.agents.candidate_profile import DEMO_AGENTS

# ─── Thresholds (v1: app/agents/agents.py:415, :422, :434) ────────────────────

#: An agent wins the task outright at or above this confidence (v1 `agents.py:415`).
AGENT_CONFIDENCE_THRESHOLD = 0.7

#: A human wins the task outright at or above this confidence (v1 `agents.py:422`).
HUMAN_CONFIDENCE_THRESHOLD = 0.6

#: Neither side cleared its bar, but the best agent is at least this confident,
#: so the task is split between agent and human (v1 `agents.py:434`).
HYBRID_AGENT_CONFIDENCE_THRESHOLD = 0.5


# ─── Emitted strings (all byte-identical to v1) ───────────────────────────────

#: v1 `agents.py:427`, `:446` — the same literal on both human branches.
HUMAN_COST_HINT = "需要评估薪资"

#: v1 `agents.py:440`.
HYBRID_COST_HINT = "混合成本"

#: v1 `agents.py:438`.
HYBRID_REASON = "建议人机协同：Agent 完成基础部分，人工处理复杂判断"

#: v1 `agents.py:445` — also the D5 zero-evaluation recommendation.
HUMAN_FALLBACK_REASON = "此任务需要人类处理，建议招聘"

#: v1 `agents.py:420` — the default of the demo cost lookup when the resource id
#: is not a demo agent (e.g. the top resource is a human).
UNKNOWN_COST_HINT = "未知"


def _default_cost_lookup() -> dict[str, str]:
    """Resource id → cost hint, from the demo agent fixtures.

    v1 reached into the `DEMO_AGENTS` module global directly
    (`agents.py:420`); exposing it as a plain mapping is what makes `decide()`
    testable without importing the demo fixtures (or, later, without a DB).
    """
    return {
        agent_id: spec["cost_per_task"]
        for agent_id, spec in DEMO_AGENTS.items()
        if "cost_per_task" in spec
    }


#: Built once at import from the demo fixtures. Callers that have a real cost
#: source pass their own mapping into `decide(cost_lookup=...)`.
DEFAULT_COST_LOOKUP: dict[str, str] = _default_cost_lookup()


def sort_evaluations(evaluations: list[dict]) -> list[dict]:
    """Return the evaluations sorted by confidence, highest first (v1 `agents.py:408-410`).

    Missing `confidence` sorts as 0, exactly as v1's `x.get("confidence", 0)` did.
    Python's sort is stable, so equal confidences keep their evaluation order.
    """
    return sorted(evaluations, key=lambda e: e.get("confidence", 0), reverse=True)


def decide(
    evaluations: list[dict],
    task: dict | None = None,
    cost_lookup: Mapping[str, str] | None = None,
) -> dict:
    """Pick the executor for one task from its resource evaluations.

    Args:
        evaluations: the per-resource evaluation dicts. Sorted here by
            confidence descending, so the caller may pass them in any order.
        task: the task being routed. **Unused by the v1 policy** — the thresholds
            look only at the evaluations. It is in the signature because the
            policy is the natural home for task-aware routing rules (D7), and
            because adding it later would change every call site. Any use of it
            here changes v1-identical behaviour and belongs in its own commit.
        cost_lookup: resource id → cost hint. Defaults to the demo-agent
            fixtures (`DEFAULT_COST_LOOKUP`).

    Returns:
        `{"decision": "agent"|"human"|"hybrid", "reason": str, "cost_hint": str}`
        plus `"resource"` (the winning evaluation, verbatim) whenever there is
        at least one evaluation. Never None, never a null `resource` value —
        the key is simply absent when nothing was evaluated (see
        `app/schemas/task_decision.json`).
    """
    lookup = DEFAULT_COST_LOOKUP if cost_lookup is None else cost_lookup
    ranked = sort_evaluations(evaluations)

    if not ranked:
        # D5: v1 emitted `None` here (`agents.py:396`), which 500s the summary
        # and JD stages. The strings are v1's no-agent branch (`agents.py:442-447`).
        return {
            "decision": "human",
            "reason": HUMAN_FALLBACK_REASON,
            "cost_hint": HUMAN_COST_HINT,
        }

    top = ranked[0]
    top_confidence = top.get("confidence", 0)
    top_type = top.get("resource_type")

    if top_type == "agent" and top_confidence >= AGENT_CONFIDENCE_THRESHOLD:
        # v1 `agents.py:416-421`
        return {
            "decision": "agent",
            "resource": top,
            "reason": f"推荐使用 {top['resource_name']}，置信度 {top_confidence:.0%}",
            "cost_hint": lookup.get(top["resource_id"], UNKNOWN_COST_HINT),
        }

    if top_type == "human" and top_confidence >= HUMAN_CONFIDENCE_THRESHOLD:
        # v1 `agents.py:423-428`
        return {
            "decision": "human",
            "resource": top,
            "reason": f"建议招聘 {top['resource_name']} 类型人才，置信度 {top_confidence:.0%}",
            "cost_hint": HUMAN_COST_HINT,
        }

    # Nobody cleared their own bar. v1 `agents.py:430-447`: if the best *agent*
    # is still reasonably confident, split the task; otherwise hire.
    # (v1 also computed `human_evals` here and never read it — dropped.)
    agent_evals = [e for e in ranked if e.get("resource_type") == "agent"]
    if agent_evals and agent_evals[0].get("confidence", 0) >= HYBRID_AGENT_CONFIDENCE_THRESHOLD:
        # v1 `agents.py:435-440` — note `resource` is the overall top, not the
        # top agent, which is what makes the hybrid card name a human sometimes.
        return {
            "decision": "hybrid",
            "resource": top,
            "reason": HYBRID_REASON,
            "cost_hint": HYBRID_COST_HINT,
        }

    # v1 `agents.py:442-447`
    return {
        "decision": "human",
        "resource": top,
        "reason": HUMAN_FALLBACK_REASON,
        "cost_hint": HUMAN_COST_HINT,
    }
