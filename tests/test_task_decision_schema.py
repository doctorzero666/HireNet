"""
Stage 1 / WP2 — TaskDecision + AnalysisTrace contracts.

`TaskDecision` is the runtime object the analysis routes actually return inside
the `{"decisions": [...]}` wrapper. It is a DIFFERENT object from the existing
`resource_decision.json` (executor_type / payment_method / asset_ids /
settlement_timing), which stays untouched — see tests/test_schemas.py.
"""
import jsonschema
import pytest

from app.services.validation import (
    validate,
    validate_analysis_trace,
    validate_requirement,
    validate_task,
    validate_task_decision,
)


# ─── Fixtures: minimal valid objects ──────────────────────────────────────────

VALID_EVALUATION = {
    "can_complete": True,
    "confidence": 0.88,
    "reason": "该 Agent 已有知识库构建能力",
    "estimated_time": "2 天",
    "strengths": ["结构化整理"],
    "resource_id": "agent_content",
    "resource_name": "内容创作 Agent",
    "resource_type": "agent",
}

VALID_TASK_DECISION = {
    "task_id": "t1",
    "task_name": "搭建 FAQ 知识库",
    "task_type": "technical",
    "task_description": "整理历史工单并导入知识库",
    "estimated_hours": 16,
    "requires_judgment": False,
    "is_recurring": False,
    "evaluations": [VALID_EVALUATION],
    "recommendation": {
        "decision": "agent",
        "resource": VALID_EVALUATION,
        "reason": "推荐使用 内容创作 Agent，置信度 88%",
        "cost_hint": "$0.05",
    },
}

VALID_ANALYSIS_TRACE = {
    "trace_id": "tr_0001",
    "session_id": "9f2c1b8a4d5e6f70",
    "step_no": 0,
    "stage": "clarify",
    "model": "glm-4-plus",
    "prompt_json": '[{"role": "system", "content": "..."}]',
    "response_text": "请问这套系统是一次性交付还是长期运营？",
    "parsed_ok": True,
    "input_tokens": 412,
    "output_tokens": 37,
    "time_ms": 1830,
    "created_at": "2026-09-04T02:11:07Z",
}


def _without(obj: dict, key: str) -> dict:
    return {k: v for k, v in obj.items() if k != key}


# ─── TaskDecision ─────────────────────────────────────────────────────────────

class TestTaskDecisionSchema:
    def test_valid_passes(self):
        validate_task_decision(VALID_TASK_DECISION)

    def test_named_validator_matches_the_generic_one(self):
        validate(VALID_TASK_DECISION, "task_decision")

    def test_optional_task_fields_may_be_absent(self):
        """estimated_hours / requires_judgment / is_recurring are optional (D6)."""
        lean = dict(VALID_TASK_DECISION)
        for key in ("estimated_hours", "requires_judgment", "is_recurring"):
            lean.pop(key)
        validate_task_decision(lean)

    def test_missing_recommendation_fails(self):
        with pytest.raises(jsonschema.ValidationError):
            validate_task_decision(_without(VALID_TASK_DECISION, "recommendation"))

    def test_null_recommendation_fails(self):
        """The old engine emitted None here and blew up three call sites (D5)."""
        with pytest.raises(jsonschema.ValidationError):
            validate_task_decision({**VALID_TASK_DECISION, "recommendation": None})

    def test_bad_decision_value_fails(self):
        bad = {
            **VALID_TASK_DECISION,
            "recommendation": {**VALID_TASK_DECISION["recommendation"], "decision": "robot"},
        }
        with pytest.raises(jsonschema.ValidationError):
            validate_task_decision(bad)

    def test_capitalised_decision_value_fails(self):
        """The runtime vocabulary is lowercase; Agent|Human|Hybrid belongs to
        resource_decision.json's executor_type and must not leak in here."""
        bad = {
            **VALID_TASK_DECISION,
            "recommendation": {**VALID_TASK_DECISION["recommendation"], "decision": "Agent"},
        }
        with pytest.raises(jsonschema.ValidationError):
            validate_task_decision(bad)

    def test_recommendation_without_cost_hint_fails(self):
        rec = _without(VALID_TASK_DECISION["recommendation"], "cost_hint")
        with pytest.raises(jsonschema.ValidationError):
            validate_task_decision({**VALID_TASK_DECISION, "recommendation": rec})

    def test_missing_task_description_fails(self):
        """task_description was consumed by the JD stage but never produced;
        the new contract makes it mandatory so that gap cannot reappear."""
        with pytest.raises(jsonschema.ValidationError):
            validate_task_decision(_without(VALID_TASK_DECISION, "task_description"))

    def test_empty_evaluations_still_needs_a_recommendation(self):
        """Zero evaluations is legal; a null recommendation is not (D5)."""
        no_evals = {
            **VALID_TASK_DECISION,
            "evaluations": [],
            "recommendation": {
                "decision": "human",
                "reason": "此任务需要人类处理，建议招聘",
                "cost_hint": "unknown",
            },
        }
        validate_task_decision(no_evals)

    def test_confidence_must_be_a_number(self):
        """A string confidence raises TypeError at the threshold comparison
        long before anyone sees it, so the schema rejects it up front."""
        bad_eval = {**VALID_EVALUATION, "confidence": "0.9"}
        with pytest.raises(jsonschema.ValidationError):
            validate_task_decision({**VALID_TASK_DECISION, "evaluations": [bad_eval]})

    def test_confidence_above_one_fails(self):
        bad_eval = {**VALID_EVALUATION, "confidence": 1.4}
        with pytest.raises(jsonschema.ValidationError):
            validate_task_decision({**VALID_TASK_DECISION, "evaluations": [bad_eval]})

    def test_bad_resource_type_fails(self):
        bad_eval = {**VALID_EVALUATION, "resource_type": "cyborg"}
        with pytest.raises(jsonschema.ValidationError):
            validate_task_decision({**VALID_TASK_DECISION, "evaluations": [bad_eval]})

    def test_unknown_top_level_key_fails(self):
        with pytest.raises(jsonschema.ValidationError):
            validate_task_decision({**VALID_TASK_DECISION, "task_desciption": "typo"})

    def test_task_type_enum_stays_advisory(self):
        """D10: Stage 1 validates and logs, it does not reject out-of-vocabulary
        task types — 'general' and 'engineering' are both live in the repo."""
        for task_type in ("general", "engineering", "operational"):
            validate_task_decision({**VALID_TASK_DECISION, "task_type": task_type})

    def test_it_is_not_the_settlement_resource_decision(self):
        """Guard against the two same-named objects being quietly unified."""
        settlement_shaped = {
            "executor_type": "Agent",
            "payment_method": "ledger_only",
            "asset_ids": ["skill_001"],
            "settlement_timing": "on_completion",
        }
        with pytest.raises(jsonschema.ValidationError):
            validate_task_decision(settlement_shaped)
        validate(settlement_shaped, "resource_decision")  # still valid over there


# ─── AnalysisTrace ────────────────────────────────────────────────────────────

class TestAnalysisTraceSchema:
    def test_valid_passes(self):
        validate_analysis_trace(VALID_ANALYSIS_TRACE)

    def test_all_pipeline_stages_are_accepted(self):
        for stage in ("clarify", "extract", "decompose", "evaluate", "decide", "jd"):
            validate_analysis_trace({**VALID_ANALYSIS_TRACE, "stage": stage})

    def test_unknown_stage_fails(self):
        with pytest.raises(jsonschema.ValidationError):
            validate_analysis_trace({**VALID_ANALYSIS_TRACE, "stage": "match"})

    def test_missing_session_id_fails(self):
        with pytest.raises(jsonschema.ValidationError):
            validate_analysis_trace(_without(VALID_ANALYSIS_TRACE, "session_id"))

    def test_missing_parsed_ok_fails(self):
        with pytest.raises(jsonschema.ValidationError):
            validate_analysis_trace(_without(VALID_ANALYSIS_TRACE, "parsed_ok"))

    def test_usage_fields_may_be_null_when_the_provider_omits_usage(self):
        unknown_usage = {
            **VALID_ANALYSIS_TRACE,
            "input_tokens": None,
            "output_tokens": None,
            "time_ms": None,
        }
        validate_analysis_trace(unknown_usage)

    def test_negative_step_no_fails(self):
        with pytest.raises(jsonschema.ValidationError):
            validate_analysis_trace({**VALID_ANALYSIS_TRACE, "step_no": -1})

    def test_negative_token_count_fails(self):
        with pytest.raises(jsonschema.ValidationError):
            validate_analysis_trace({**VALID_ANALYSIS_TRACE, "input_tokens": -5})

    def test_parsed_ok_must_be_boolean(self):
        with pytest.raises(jsonschema.ValidationError):
            validate_analysis_trace({**VALID_ANALYSIS_TRACE, "parsed_ok": "yes"})

    def test_unknown_key_fails(self):
        with pytest.raises(jsonschema.ValidationError):
            validate_analysis_trace({**VALID_ANALYSIS_TRACE, "cost_usd": 0.002})


# ─── Requirement / Task named validators ──────────────────────────────────────

VALID_REQUIREMENT = {
    "project_name": "电商智能客服系统",
    "core_description": "覆盖售前咨询、售后处理和投诉响应",
    "tasks_hint": ["搭建知识库"],
    "duration": "ongoing",
    "urgency": "high",
    "budget_hint": "medium",
}


class TestNamedRequirementAndTaskValidators:
    def test_requirement_valid_passes(self):
        validate_requirement(VALID_REQUIREMENT)

    def test_requirement_duration_unknown_is_accepted(self):
        """'unknown' is a first-class member of the duration enum: an unclear
        timeline is recorded as `unknown`, never as free text like '3个月'."""
        validate_requirement({**VALID_REQUIREMENT, "duration": "unknown"})

    def test_requirement_free_text_duration_is_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            validate_requirement({**VALID_REQUIREMENT, "duration": "3个月"})

    def test_requirement_budget_hint_unknown_is_accepted(self):
        """Unknown budget is the categorical 'unknown', not prose."""
        validate_requirement({**VALID_REQUIREMENT, "budget_hint": "unknown"})

    def test_requirement_free_text_budget_hint_is_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            validate_requirement({**VALID_REQUIREMENT, "budget_hint": "需要评估薪资"})

    def test_task_valid_passes(self):
        validate_task(
            {
                "id": "t1",
                "name": "搭建 FAQ 知识库",
                "description": "整理历史工单并导入知识库",
                "type": "technical",
                "estimated_hours": 16,
                "requires_judgment": False,
                "is_recurring": False,
            }
        )

    def test_task_missing_id_is_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            validate_task({"name": "x", "description": "y", "type": "technical",
                           "estimated_hours": 1, "requires_judgment": False,
                           "is_recurring": False})
