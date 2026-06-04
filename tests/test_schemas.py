"""
U1 验收测试：Schema 定义 + 校验 + Retry / Fallback

验收标准：
- 合法对象通过
- 非法对象被拦截
- 模拟"模型返回坏 JSON"时能 repair 或 fallback，不崩溃
"""
import json
import pytest
import jsonschema

from app.services.validation import validate, parse_llm_json, validate_llm_output, validate_split_rule


# ─── Fixtures: minimal valid objects for each schema ──────────────────────────

VALID_REQUIREMENT = {
    "project_name": "HireNet MVP",
    "core_description": "Build a talent marketplace with AI agents",
    "tasks_hint": ["backend API", "frontend UI"],
    "duration": "one-time",
    "urgency": "high",
    "budget_hint": "medium",
}

VALID_TASK = {
    "id": "t1",
    "name": "Build REST API",
    "description": "Implement Flask REST endpoints",
    "type": "technical",
    "estimated_hours": 16,
    "requires_judgment": False,
    "is_recurring": False,
}

VALID_RESOURCE_DECISION = {
    "executor_type": "Agent",
    "payment_method": "ledger_only",
    "asset_ids": ["skill_001"],
    "settlement_timing": "on_completion",
}

VALID_JOB_DESIGN = {
    "job_title": "Backend Engineer",
    "core_responsibilities": ["Design APIs", "Write tests"],
    "required_skills": ["Python", "Flask"],
    "experience_range": {"min": 1, "max": 3, "unit": "年"},
    "salary_range": {"min": 15000, "max": 25000, "unit": "元/月"},
    "work_type": "full-time",
    "water_score": 85,
}

VALID_CAREER_STRATEGY = {
    "summary": "Full-stack engineer pivoting to AI products",
    "directions": [
        {
            "title": "AI Product Manager",
            "reason": "Your engineering background + product sense is rare",
            "next_action": "Write one AI PRD this week",
        }
    ],
    "focus_skills": ["Prompt Engineering", "Product Sense"],
    "avoid": "Don't spread across too many directions at once",
    "encouragement": "Your unique background is a genuine advantage",
}

VALID_MATCH_RESULT = {
    "candidate_id": "cand_001",
    "job_id": "job_001",
    "match_score": 82,
    "match_reasons": ["Strong Python skills", "API design experience"],
}

VALID_SKILL_ASSET = {
    "creator_id": "user_001",
    "name": "Job Design Agent",
    "description": "Generates de-watered job descriptions",
    "io_schema": {"input": {"requirement": "object"}, "output": {"job_design": "object"}},
    "price_amount": 50,          # integer basis points (= 0.50 USD at 1/100 cent)
    "price_currency": "USD",
    "split_rule": {"creator": 7000, "platform": 3000},  # basis points: 70% / 30%
    # sha256 of empty string — valid 64-char lowercase hex provenance hash
    "content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
}

VALID_ROYALTY_SPLIT = {
    "creator": 7000,   # basis points: 70%
    "platform": 3000,  # basis points: 30%
}


# ─── Requirement schema ───────────────────────────────────────────────────────

class TestRequirementSchema:
    def test_valid_passes(self):
        validate(VALID_REQUIREMENT, "requirement")

    def test_missing_required_field_blocked(self):
        bad = {k: v for k, v in VALID_REQUIREMENT.items() if k != "urgency"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "requirement")

    def test_invalid_duration_enum_blocked(self):
        bad = {**VALID_REQUIREMENT, "duration": "bi-weekly"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "requirement")

    def test_invalid_budget_hint_enum_blocked(self):
        bad = {**VALID_REQUIREMENT, "budget_hint": "rich"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "requirement")


# ─── Task schema ──────────────────────────────────────────────────────────────

class TestTaskSchema:
    def test_valid_passes(self):
        validate(VALID_TASK, "task")

    def test_missing_id_blocked(self):
        bad = {k: v for k, v in VALID_TASK.items() if k != "id"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "task")

    def test_invalid_type_enum_blocked(self):
        bad = {**VALID_TASK, "type": "managerial"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "task")

    def test_negative_hours_blocked(self):
        bad = {**VALID_TASK, "estimated_hours": -1}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "task")


# ─── ResourceDecision schema ──────────────────────────────────────────────────

class TestResourceDecisionSchema:
    def test_valid_passes(self):
        validate(VALID_RESOURCE_DECISION, "resource_decision")

    def test_invalid_executor_type_blocked(self):
        bad = {**VALID_RESOURCE_DECISION, "executor_type": "Bot"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "resource_decision")

    def test_invalid_payment_method_blocked(self):
        bad = {**VALID_RESOURCE_DECISION, "payment_method": "crypto"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "resource_decision")

    def test_invalid_settlement_timing_blocked(self):
        bad = {**VALID_RESOURCE_DECISION, "settlement_timing": "weekly"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "resource_decision")


# ─── JobDesign schema ─────────────────────────────────────────────────────────

class TestJobDesignSchema:
    def test_valid_passes(self):
        validate(VALID_JOB_DESIGN, "job_design")

    def test_missing_job_title_blocked(self):
        bad = {k: v for k, v in VALID_JOB_DESIGN.items() if k != "job_title"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "job_design")

    def test_water_score_out_of_range_blocked(self):
        bad = {**VALID_JOB_DESIGN, "water_score": 150}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "job_design")

    def test_invalid_work_type_blocked(self):
        bad = {**VALID_JOB_DESIGN, "work_type": "gig"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "job_design")

    def test_empty_responsibilities_blocked(self):
        bad = {**VALID_JOB_DESIGN, "core_responsibilities": []}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "job_design")


# ─── CareerStrategy schema ────────────────────────────────────────────────────

class TestCareerStrategySchema:
    def test_valid_passes(self):
        validate(VALID_CAREER_STRATEGY, "career_strategy")

    def test_missing_summary_blocked(self):
        bad = {k: v for k, v in VALID_CAREER_STRATEGY.items() if k != "summary"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "career_strategy")

    def test_empty_directions_blocked(self):
        bad = {**VALID_CAREER_STRATEGY, "directions": []}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "career_strategy")

    def test_direction_missing_next_action_blocked(self):
        bad_direction = {"title": "PM", "reason": "Good fit"}  # missing next_action
        bad = {**VALID_CAREER_STRATEGY, "directions": [bad_direction]}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "career_strategy")


# ─── MatchResult schema ───────────────────────────────────────────────────────

class TestMatchResultSchema:
    def test_valid_passes(self):
        validate(VALID_MATCH_RESULT, "match_result")

    def test_missing_match_reasons_blocked(self):
        bad = {k: v for k, v in VALID_MATCH_RESULT.items() if k != "match_reasons"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "match_result")

    def test_empty_match_reasons_blocked(self):
        bad = {**VALID_MATCH_RESULT, "match_reasons": []}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "match_result")

    def test_score_out_of_range_blocked(self):
        bad = {**VALID_MATCH_RESULT, "match_score": 101}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "match_result")


# ─── SkillAsset schema ────────────────────────────────────────────────────────

class TestSkillAssetSchema:
    def test_valid_passes(self):
        validate(VALID_SKILL_ASSET, "skill_asset")

    def test_negative_price_blocked(self):
        bad = {**VALID_SKILL_ASSET, "price_amount": -1}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "skill_asset")

    def test_missing_split_rule_blocked(self):
        bad = {k: v for k, v in VALID_SKILL_ASSET.items() if k != "split_rule"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "skill_asset")

    def test_split_rule_over_max_blocked(self):
        bad = {**VALID_SKILL_ASSET, "split_rule": {"creator": 15000, "platform": 3000}}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "skill_asset")

    def test_price_chain_null_allowed(self):
        asset = {**VALID_SKILL_ASSET, "price_chain": None}
        validate(asset, "skill_asset")

    def test_missing_content_hash_blocked(self):
        bad = {k: v for k, v in VALID_SKILL_ASSET.items() if k != "content_hash"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "skill_asset")

    def test_short_content_hash_blocked(self):
        bad = {**VALID_SKILL_ASSET, "content_hash": "abc123"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "skill_asset")

    def test_non_hex_content_hash_blocked(self):
        # 64 chars but contains uppercase — not valid lowercase hex
        bad = {**VALID_SKILL_ASSET, "content_hash": "A" * 64}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "skill_asset")

    def test_valid_sha256_hash_passes(self):
        # sha256("hello") — a known, valid lowercase 64-char hex string
        asset = {**VALID_SKILL_ASSET,
                 "content_hash": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"}
        validate(asset, "skill_asset")


# ─── RoyaltySplit schema ──────────────────────────────────────────────────────

class TestRoyaltySplitSchema:
    def test_valid_passes(self):
        validate(VALID_ROYALTY_SPLIT, "royalty_split")

    def test_creator_over_max_blocked(self):
        with pytest.raises(jsonschema.ValidationError):
            validate({"creator": 10001, "platform": 3000}, "royalty_split")

    def test_negative_platform_blocked(self):
        with pytest.raises(jsonschema.ValidationError):
            validate({"creator": 7000, "platform": -100}, "royalty_split")

    def test_extra_field_blocked(self):
        with pytest.raises(jsonschema.ValidationError):
            validate({"creator": 7000, "platform": 3000, "dao": 1000}, "royalty_split")

    def test_float_creator_blocked(self):
        # Schema requires integer type; floats must be rejected
        with pytest.raises(jsonschema.ValidationError):
            validate({"creator": 0.7, "platform": 0.3}, "royalty_split")


# ─── parse_llm_json ───────────────────────────────────────────────────────────

class TestParseLlmJson:
    def test_plain_json_passes(self):
        raw = '{"key": "value"}'
        assert parse_llm_json(raw) == {"key": "value"}

    def test_strips_json_fence(self):
        raw = '```json\n{"key": "value"}\n```'
        assert parse_llm_json(raw) == {"key": "value"}

    def test_strips_plain_fence(self):
        raw = '```\n{"key": "value"}\n```'
        assert parse_llm_json(raw) == {"key": "value"}

    def test_raises_on_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            parse_llm_json("not json at all")

    def test_extracts_json_from_prose(self):
        # LLM adds explanatory text before/after the JSON object
        raw = 'Here is the result:\n{"key": "value"}\nThis completes the output.'
        assert parse_llm_json(raw) == {"key": "value"}

    def test_extracts_json_with_nested_objects(self):
        raw = 'Output:\n{"outer": {"inner": 1}}\nDone.'
        assert parse_llm_json(raw) == {"outer": {"inner": 1}}


# ─── validate_llm_output ─────────────────────────────────────────────────────

class TestValidateLlmOutput:
    def test_good_json_returns_data(self):
        raw = json.dumps(VALID_REQUIREMENT)
        result = validate_llm_output(raw, "requirement")
        assert result["project_name"] == "HireNet MVP"

    def test_markdown_wrapped_json_passes(self):
        raw = f'```json\n{json.dumps(VALID_REQUIREMENT)}\n```'
        result = validate_llm_output(raw, "requirement")
        assert result["urgency"] == "high"

    def test_bad_json_returns_fallback(self):
        fallback = {**VALID_REQUIREMENT, "project_name": "__fallback__"}
        result = validate_llm_output("totally broken {{{", "requirement", fallback=fallback)
        assert result["project_name"] == "__fallback__"

    def test_bad_json_without_fallback_raises(self):
        with pytest.raises((json.JSONDecodeError, ValueError)):
            validate_llm_output("totally broken {{{", "requirement")

    def test_invalid_schema_returns_fallback(self):
        bad = json.dumps({"project_name": "x"})  # missing required fields
        fallback = {**VALID_REQUIREMENT}
        result = validate_llm_output(bad, "requirement", fallback=fallback)
        assert result == fallback

    def test_repair_with_mock_llm_succeeds(self):
        good_raw = json.dumps(VALID_REQUIREMENT)
        mock_llm = lambda prompt: good_raw  # noqa: E731
        result = validate_llm_output("bad json {{{", "requirement", llm_fn=mock_llm)
        assert result["project_name"] == "HireNet MVP"

    def test_exhausted_retries_returns_fallback(self):
        always_bad = lambda prompt: "still broken"  # noqa: E731
        fallback = {**VALID_REQUIREMENT, "project_name": "__fallback__"}
        result = validate_llm_output(
            "bad json", "requirement",
            llm_fn=always_bad, max_retries=2, fallback=fallback,
        )
        assert result["project_name"] == "__fallback__"

    def test_exhausted_retries_raises_without_fallback(self):
        always_bad = lambda prompt: "still broken"  # noqa: E731
        with pytest.raises(json.JSONDecodeError):
            validate_llm_output(
                "bad json", "requirement",
                llm_fn=always_bad, max_retries=1,
            )

    def test_repair_called_correct_number_of_times(self):
        call_count = {"n": 0}

        def counting_llm(prompt):
            call_count["n"] += 1
            return "still broken"

        fallback = {**VALID_REQUIREMENT}
        validate_llm_output(
            "bad", "requirement",
            llm_fn=counting_llm, max_retries=2, fallback=fallback,
        )
        assert call_count["n"] == 2  # called once per retry attempt

    def test_invalid_fallback_raises(self):
        # M2: fallback that fails schema validation must raise, not be silently returned
        invalid_fallback = {"project_name": "x"}  # missing all other required fields
        with pytest.raises(jsonschema.ValidationError):
            validate_llm_output(
                "bad json {{{", "requirement",
                fallback=invalid_fallback,
            )


# ─── validate_split_rule ──────────────────────────────────────────────────────

class TestValidateSplitRule:
    def test_valid_split_passes(self):
        validate_split_rule({"creator": 7000, "platform": 3000})

    def test_full_creator_split_passes(self):
        validate_split_rule({"creator": 10000, "platform": 0})

    def test_sum_over_10000_raises(self):
        with pytest.raises(ValueError, match="sum to 10000"):
            validate_split_rule({"creator": 9900, "platform": 9900})

    def test_sum_under_10000_raises(self):
        with pytest.raises(ValueError, match="sum to 10000"):
            validate_split_rule({"creator": 5000, "platform": 3000})

    def test_zero_creator_raises(self):
        with pytest.raises(ValueError, match="sum to 10000"):
            validate_split_rule({"creator": 0, "platform": 5000})


# ─── AgentRun schema ──────────────────────────────────────────────────────────

VALID_AGENT_RUN = {
    "run_id": "run_001",
    "agent_name": "TestAgent",
    "caller_id": "caller_001",
    "task_id": "task_001",
    "input_tokens": 100,
    "output_tokens": 50,
    "llm_cost_usd": "0.002",
    "time_ms": 1200,
    "success": True,
    "asset_ids": ["skill_001"],
    "royalty_splits": {"user_001": {"amount": 35, "currency": "USD"}},
    "charge_amount": 50,
    "charge_currency": "USD",
    "charge_chain": None,
    "payment_method": "ledger_only",
    "settlement_status": "accrued",
    "created_at": "2026-06-04T00:00:00+00:00",
}


class TestAgentRunSchema:
    def test_valid_passes(self):
        validate(VALID_AGENT_RUN, "agent_run")

    def test_charge_chain_null_allowed(self):
        validate({**VALID_AGENT_RUN, "charge_chain": None}, "agent_run")

    def test_charge_chain_string_allowed(self):
        validate({**VALID_AGENT_RUN, "charge_chain": "ethereum"}, "agent_run")

    def test_invalid_settlement_status_blocked(self):
        bad = {**VALID_AGENT_RUN, "settlement_status": "cancelled"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "agent_run")

    def test_negative_charge_amount_blocked(self):
        bad = {**VALID_AGENT_RUN, "charge_amount": -1}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "agent_run")

    def test_missing_agent_name_blocked(self):
        bad = {k: v for k, v in VALID_AGENT_RUN.items() if k != "agent_name"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "agent_run")

    def test_missing_charge_currency_blocked(self):
        bad = {k: v for k, v in VALID_AGENT_RUN.items() if k != "charge_currency"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "agent_run")

    def test_invalid_payment_method_blocked(self):
        bad = {**VALID_AGENT_RUN, "payment_method": "cash"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "agent_run")

    def test_extra_field_blocked(self):
        bad = {**VALID_AGENT_RUN, "unexpected": "value"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "agent_run")


# ─── RoyaltyEntry schema ──────────────────────────────────────────────────────

VALID_ROYALTY_ENTRY = {
    "id": "entry_001",
    "run_id": "run_001",
    "creator_id": "user_001",
    "asset_id": "skill_001",
    "amount": 35,
    "currency": "USD",
    "chain": None,
    "status": "accrued",
    "created_at": "2026-06-04T00:00:00+00:00",
}


class TestRoyaltyEntrySchema:
    def test_valid_accrued_passes(self):
        validate(VALID_ROYALTY_ENTRY, "royalty_entry")

    def test_valid_settled_passes(self):
        validate({**VALID_ROYALTY_ENTRY, "status": "settled"}, "royalty_entry")

    def test_chain_null_allowed(self):
        validate({**VALID_ROYALTY_ENTRY, "chain": None}, "royalty_entry")

    def test_chain_string_allowed(self):
        validate({**VALID_ROYALTY_ENTRY, "chain": "ethereum"}, "royalty_entry")

    def test_invalid_status_blocked(self):
        bad = {**VALID_ROYALTY_ENTRY, "status": "pending"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "royalty_entry")

    def test_missing_status_blocked(self):
        bad = {k: v for k, v in VALID_ROYALTY_ENTRY.items() if k != "status"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "royalty_entry")

    def test_missing_creator_id_blocked(self):
        bad = {k: v for k, v in VALID_ROYALTY_ENTRY.items() if k != "creator_id"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "royalty_entry")

    def test_negative_amount_blocked(self):
        bad = {**VALID_ROYALTY_ENTRY, "amount": -1}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "royalty_entry")

    def test_missing_currency_blocked(self):
        bad = {k: v for k, v in VALID_ROYALTY_ENTRY.items() if k != "currency"}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "royalty_entry")

    def test_extra_field_blocked(self):
        bad = {**VALID_ROYALTY_ENTRY, "bonus": 999}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "royalty_entry")


# ─── ResourceDecision — M6 conditional asset_ids constraint ──────────────────

class TestResourceDecisionConditionalAssetIds:
    def test_agent_non_empty_asset_ids_passes(self):
        validate(VALID_RESOURCE_DECISION, "resource_decision")  # executor=Agent, ids=["skill_001"]

    def test_agent_empty_asset_ids_blocked(self):
        bad = {**VALID_RESOURCE_DECISION, "executor_type": "Agent", "asset_ids": []}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "resource_decision")

    def test_hybrid_empty_asset_ids_blocked(self):
        bad = {**VALID_RESOURCE_DECISION, "executor_type": "Hybrid", "asset_ids": []}
        with pytest.raises(jsonschema.ValidationError):
            validate(bad, "resource_decision")

    def test_human_empty_asset_ids_passes(self):
        human = {**VALID_RESOURCE_DECISION, "executor_type": "Human", "asset_ids": []}
        validate(human, "resource_decision")
