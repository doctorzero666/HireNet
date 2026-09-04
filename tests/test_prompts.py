"""
Stage 1 / WP3a — the externalised prompts must be byte-identical to v1's.

WP4 compares v1 against v2 on the same 20 golden cases with real LLM calls. If
the v2 prompts differ from v1's by so much as a full-width comma, that
comparison stops measuring the agent and starts measuring the prompt edit. So
this file is the guard on commit 3a.2: every `app/agents/prompts/*.md` either
equals the v1 constant it was copied from, or renders to exactly the string v1
sends over the wire.

`force_extract.md` is the one deliberate exception — new text for D3, with no
v1 counterpart.
"""
import pytest

import app.agents.agents as agents_module
from app.agents.prompts import available_prompts, load_prompt, render_prompt


@pytest.fixture(autouse=True)
def _guard_no_real_llm(no_real_llm_client):
    """No test in this module may construct the real OpenAI client."""


# ─── The two system prompts are plain constants in v1 ─────────────────────────

def test_requirement_system_prompt_matches_v1_byte_for_byte():
    assert load_prompt("requirement_system") == agents_module.REQUIREMENT_SYSTEM_PROMPT


def test_decomposition_system_prompt_matches_v1_byte_for_byte():
    assert load_prompt("decomposition_system") == agents_module.DECOMPOSITION_SYSTEM_PROMPT


# ─── The two templated prompts are inline f-strings in v1 ─────────────────────
#
# There is no constant to compare against, so compare against what v1 actually
# puts on the wire: drive the untouched v1 function with a fake client and read
# the recorded `messages`.

REQUIREMENT = {
    "project_name": "电商智能客服系统",
    "core_description": "覆盖售前咨询、售后处理和投诉响应",
    "tasks_hint": ["搭建知识库", "接入工单系统"],
    "duration": "ongoing",
    "team_context": "3 人运营团队",
    "urgency": "high",
    "budget_hint": "medium",
}

RESOURCE = {
    "id": "agent_code",
    "type": "agent",
    "name": "代码生成 Agent",
    "capabilities": ["前端开发", "后端开发"],
    "capability_summary": "前端开发、后端开发、脚本编写、代码审查",
}

TASK = {
    "id": "t1",
    "name": "搭建工单系统",
    "description": "对接现有客服工单系统并同步状态",
    "type": "technical",
    "estimated_hours": 16,
    "requires_judgment": True,
    "is_recurring": False,
}


def test_decomposition_user_prompt_renders_to_v1s_wire_format(fake_llm):
    fake_llm.queue('{"tasks": []}')
    agents_module.decompose_tasks(REQUIREMENT)
    v1_user_prompt = fake_llm.calls[0]["messages"][1]["content"]

    rendered = render_prompt(
        "decomposition_user",
        project_name=REQUIREMENT["project_name"],
        core_description=REQUIREMENT["core_description"],
        tasks_hint=", ".join(REQUIREMENT["tasks_hint"]),
        duration=REQUIREMENT["duration"],
        team_context=REQUIREMENT["team_context"],
    )
    assert rendered == v1_user_prompt


def test_decomposition_user_prompt_matches_v1_for_a_sparse_requirement(fake_llm):
    """v1's `.get` defaults ('未知' / '' / 'unknown') are the caller's job now."""
    fake_llm.queue('{"tasks": []}')
    agents_module.decompose_tasks({})
    v1_user_prompt = fake_llm.calls[0]["messages"][1]["content"]

    rendered = render_prompt(
        "decomposition_user",
        project_name="未知",
        core_description="",
        tasks_hint="",
        duration="unknown",
        team_context="未知",
    )
    assert rendered == v1_user_prompt


@pytest.mark.parametrize("requires_judgment", [True, False])
def test_resource_evaluation_prompt_renders_to_v1s_wire_format(fake_llm, requires_judgment):
    task = dict(TASK, requires_judgment=requires_judgment)
    fake_llm.queue('{"can_complete": true, "confidence": 0.9, "reason": "ok"}')
    agents_module._llm_evaluate_resource(RESOURCE, task)
    v1_user_prompt = fake_llm.calls[0]["messages"][0]["content"]

    rendered = render_prompt(
        "resource_evaluation",
        resource_name=RESOURCE["name"],
        resource_kind="AI Agent",
        capability_desc=RESOURCE["capability_summary"],
        task_name=task["name"],
        task_description=task["description"],
        task_type=task["type"],
        requires_judgment="是" if requires_judgment else "否",
    )
    assert rendered == v1_user_prompt


def test_resource_evaluation_prompt_matches_v1_for_a_human_resource(fake_llm):
    human = {
        "id": "candidate_a",
        "type": "human",
        "name": "张伟（全栈工程师）",
        "capability_summary": "技能：React、Node.js",
    }
    fake_llm.queue('{"can_complete": true, "confidence": 0.8, "reason": "ok"}')
    agents_module._llm_evaluate_resource(human, TASK)
    v1_user_prompt = fake_llm.calls[0]["messages"][0]["content"]

    rendered = render_prompt(
        "resource_evaluation",
        resource_name=human["name"],
        resource_kind="人类候选人",
        capability_desc=human["capability_summary"],
        task_name=TASK["name"],
        task_description=TASK["description"],
        task_type=TASK["type"],
        requires_judgment="是",
    )
    assert rendered == v1_user_prompt


# ─── The new one (D3) ─────────────────────────────────────────────────────────

def test_force_extract_prompt_is_new_text_not_a_copy():
    force = load_prompt("force_extract")
    assert force
    assert force != agents_module.REQUIREMENT_SYSTEM_PROMPT
    # It must not re-arm the marker the state machine keys on, or a forced
    # extraction would look like a normal completion (audit g15 / agents.py:78).
    assert "[REQUIREMENT_COMPLETE]" not in force


def test_force_extract_prompt_names_every_required_requirement_field():
    force = load_prompt("force_extract")
    for field in ["project_name", "core_description", "tasks_hint", "duration",
                  "urgency", "budget_hint"]:
        assert field in force


# ─── Loader behaviour ─────────────────────────────────────────────────────────

def test_all_five_prompts_are_loaded_at_import():
    assert available_prompts() == [
        "decomposition_system",
        "decomposition_user",
        "force_extract",
        "requirement_system",
        "resource_evaluation",
    ]


def test_no_prompt_is_empty_or_has_a_trailing_newline():
    for name in available_prompts():
        text = load_prompt(name)
        assert text.strip()
        assert not text.endswith("\n")


def test_unknown_prompt_name_raises_with_the_available_names():
    with pytest.raises(KeyError) as exc:
        load_prompt("nope")
    assert "requirement_system" in str(exc.value)


def test_missing_placeholder_value_raises_instead_of_shipping_the_placeholder():
    with pytest.raises(KeyError):
        render_prompt("decomposition_user", project_name="x")


def test_untemplated_prompts_keep_their_literal_json_braces():
    """`${...}` substitution must not touch the JSON examples in the prompts."""
    assert '"project_name": "项目名称"' in load_prompt("force_extract")
    assert '"id": "t1"' in load_prompt("decomposition_system")
