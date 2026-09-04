"""
WP-I18N / I1 — layer 2 (fixed backend strings) pattern coverage.

`frontend/src/i18n/backendStrings.json` is the canonical mirror of the FIXED
Chinese strings `app/agents/decision_policy.py` (plus
`app.agents.task_analysis.EVALUATION_FALLBACK_REASON`) emits verbatim — a UI
contract, not LLM prose (see the module docstring of `decision_policy.py`).
This file loads that same JSON from Python and asserts every canonical
string is matched by EXACTLY ONE pattern: zero matches means the English
demo silently falls back to Chinese; more than one means an ambiguous
translation could apply, and `frontend/src/i18n/backendStrings.js` always
picks the first that matches.

The frontend never hand-translates these strings — `translateBackend()`
(`frontend/src/i18n/backendStrings.js`) always goes through this same
pattern list, so drift between the two is impossible to introduce silently
as long as this test passes.
"""
import json
import re
from pathlib import Path

import pytest

from app.agents import decision_policy
from app.agents.task_analysis import EVALUATION_FALLBACK_REASON

PATTERNS_PATH = (
    Path(__file__).resolve().parent.parent
    / "frontend" / "src" / "i18n" / "backendStrings.json"
)


def _load_patterns() -> list[dict]:
    data = json.loads(PATTERNS_PATH.read_text(encoding="utf-8"))
    return data["patterns"]


def _matches(pattern: dict, text: str) -> bool:
    if pattern["kind"] == "literal":
        return text == pattern["source"]
    if pattern["kind"] == "regex":
        return re.match(pattern["source"], text) is not None
    raise ValueError(f"unknown pattern kind: {pattern['kind']!r}")


def _matching_patterns(text: str) -> list[dict]:
    return [p for p in _load_patterns() if _matches(p, text)]


def test_backend_strings_json_is_valid_and_non_empty():
    patterns = _load_patterns()
    assert patterns
    for pattern in patterns:
        assert pattern["kind"] in ("literal", "regex")
        assert pattern["source"]
        assert pattern["en"]


# ─── The five literal constants named in decision_policy.py ──────────────────

LITERAL_CANONICAL_STRINGS = [
    decision_policy.HUMAN_COST_HINT,
    decision_policy.HYBRID_COST_HINT,
    decision_policy.HYBRID_REASON,
    decision_policy.HUMAN_FALLBACK_REASON,
    decision_policy.UNKNOWN_COST_HINT,
    # Spec §2 explicitly includes this fallback alongside the decision_policy
    # constants, even though it is defined in task_analysis.py.
    EVALUATION_FALLBACK_REASON,
]


@pytest.mark.parametrize("canonical", LITERAL_CANONICAL_STRINGS)
def test_each_literal_canonical_string_is_matched_by_exactly_one_pattern(canonical):
    matches = _matching_patterns(canonical)
    assert len(matches) == 1, (
        f"{canonical!r} matched {len(matches)} pattern(s) in backendStrings.json, want exactly 1"
    )


# ─── The two dynamic f-string templates in decision_policy.decide() ──────────

@pytest.mark.parametrize(
    "resource_name,confidence",
    [("内容创作 Agent", 0.881), ("代码生成 Agent", 0.70), ("神秘 Agent", 1.0)],
)
def test_agent_recommendation_template_is_matched_by_exactly_one_pattern(resource_name, confidence):
    rendered = f"推荐使用 {resource_name}，置信度 {confidence:.0%}"
    matches = _matching_patterns(rendered)
    assert len(matches) == 1, rendered


@pytest.mark.parametrize(
    "resource_name,confidence",
    [("客户成功", 0.72), ("产品经理", 0.60)],
)
def test_human_recommendation_template_is_matched_by_exactly_one_pattern(resource_name, confidence):
    rendered = f"建议招聘 {resource_name} 类型人才，置信度 {confidence:.0%}"
    matches = _matching_patterns(rendered)
    assert len(matches) == 1, rendered


# ─── End to end: decide() itself, covering every branch ───────────────────────

def _assert_matched(text: str) -> None:
    matches = _matching_patterns(text)
    assert len(matches) == 1, f"{text!r} matched {len(matches)} pattern(s), want exactly 1"


def test_decide_agent_branch_reason_is_matched():
    decision = decision_policy.decide([
        {"resource_id": "agent_content", "resource_type": "agent",
         "resource_name": "内容创作 Agent", "confidence": 0.9},
    ])
    assert decision["decision"] == "agent"
    _assert_matched(decision["reason"])


def test_decide_agent_branch_unknown_resource_cost_hint_is_matched():
    """UNKNOWN_COST_HINT ("未知") — the resource id isn't in DEMO_AGENTS."""
    decision = decision_policy.decide([
        {"resource_id": "not_a_demo_agent", "resource_type": "agent",
         "resource_name": "神秘 Agent", "confidence": 0.95},
    ])
    assert decision["decision"] == "agent"
    _assert_matched(decision["cost_hint"])


def test_decide_human_branch_reason_and_cost_hint_are_matched():
    decision = decision_policy.decide([
        {"resource_id": "candidate_a", "resource_type": "human",
         "resource_name": "客户成功", "confidence": 0.72},
    ])
    assert decision["decision"] == "human"
    _assert_matched(decision["reason"])
    _assert_matched(decision["cost_hint"])


def test_decide_hybrid_branch_reason_and_cost_hint_are_matched():
    decision = decision_policy.decide([
        {"resource_id": "agent_content", "resource_type": "agent",
         "resource_name": "内容创作 Agent", "confidence": 0.55},
    ])
    assert decision["decision"] == "hybrid"
    _assert_matched(decision["reason"])
    _assert_matched(decision["cost_hint"])


def test_decide_human_fallback_branch_reason_and_cost_hint_are_matched():
    """Nobody clears any bar -> the human fallback branch."""
    decision = decision_policy.decide([
        {"resource_id": "agent_content", "resource_type": "agent",
         "resource_name": "内容创作 Agent", "confidence": 0.2},
    ])
    assert decision["decision"] == "human"
    _assert_matched(decision["reason"])
    _assert_matched(decision["cost_hint"])


def test_decide_zero_evaluations_reason_and_cost_hint_are_matched():
    decision = decision_policy.decide([])
    assert decision["decision"] == "human"
    _assert_matched(decision["reason"])
    _assert_matched(decision["cost_hint"])
