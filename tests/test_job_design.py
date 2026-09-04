"""
Stage 1 / WP5 — `app/agents/job_design.py` parses model output through
`app/services/validation.py` instead of a bare `json.loads`.

CLAUDE.md TIER-1 rule 1 forbids `json.loads` on model output, and this was the
last call site in the analysis flow still doing it — with a hand-rolled fence
strip (`raw.replace("```json", "").replace("```", "")`) in front of it. The
failure behaviour is deliberately unchanged: `design_job` still raises and
`generate_jd_report` still skips that one design and carries on.
"""
import json

import pytest

from app.agents.job_design import design_job, generate_jd_report
from tests.conftest import FakeLLMClient


@pytest.fixture(autouse=True)
def _guard_no_real_llm(no_real_llm_client):
    """No test in this module may construct the real OpenAI client."""


JD = {
    "job_title": "前端开发工程师",
    "core_responsibilities": ["实现官网改版页面", "对接后端接口"],
    "required_skills": ["React", "TypeScript"],
    "nice_to_have_skills": ["设计基础"],
    "experience_range": {"min": 2, "max": 4, "unit": "年"},
    "salary_range": {"min": 20000, "max": 30000, "unit": "元/月"},
    "work_type": "full-time",
    "water_score": 88,
    "water_analysis": "去除了两个夸大要求",
    "red_flags_removed": ["精通一切前端框架"],
}

REQUIREMENT = {
    "project_name": "企业官网改版",
    "core_description": "官网改版，包含产品介绍页和联系我们表单",
    "duration": "one-time",
    "team_context": "有一个前端，没有设计师",
    "budget_hint": "medium",
}

TASK = {
    "id": "t1",
    "name": "前端页面实现",
    "description": "实现改版后的官网页面",
    "type": "technical",
    "estimated_hours": 40,
    "requires_judgment": False,
    "is_recurring": False,
}


def human_decision(task_id, name="前端页面实现"):
    return {
        "task_id": task_id,
        "task_name": name,
        "task_type": "technical",
        "task_description": "实现改版后的官网页面",
        "evaluations": [],
        "recommendation": {"decision": "human", "reason": "需要招聘", "cost_hint": "需要评估薪资"},
    }


# ──────────────────────────────────────────────────────────────────────────────
# design_job
# ──────────────────────────────────────────────────────────────────────────────

def test_a_fenced_json_reply_is_parsed(fake_llm):
    fake_llm.queue("```json\n" + json.dumps(JD, ensure_ascii=False) + "\n```")

    result = design_job(REQUIREMENT, TASK)

    assert result["job_title"] == JD["job_title"]
    assert result["water_score"] == 88
    assert result["task_id"] == "t1"
    assert result["task_name"] == "前端页面实现"
    assert result["job_id"].startswith("jd_")


def test_a_bare_json_reply_is_parsed(fake_llm):
    fake_llm.queue(json.dumps(JD, ensure_ascii=False))
    assert design_job(REQUIREMENT, TASK)["job_title"] == JD["job_title"]


def test_json_wrapped_in_prose_is_parsed(fake_llm):
    """New capability, not a regression: `parse_llm_json` tolerates prose.

    The old fence-stripping `json.loads` raised here, so this JD used to be
    dropped. Nothing else about the failure path changed.
    """
    fake_llm.queue("好的，这是岗位定义：\n" + json.dumps(JD, ensure_ascii=False) + "\n希望有帮助。")

    assert design_job(REQUIREMENT, TASK)["job_title"] == JD["job_title"]


def test_a_garbage_reply_raises(fake_llm):
    fake_llm.queue("抱歉，我无法生成岗位定义。")

    with pytest.raises((json.JSONDecodeError, ValueError)):
        design_job(REQUIREMENT, TASK)


# ──────────────────────────────────────────────────────────────────────────────
# generate_jd_report — "skip this design" is unchanged
# ──────────────────────────────────────────────────────────────────────────────

def test_a_garbage_reply_skips_that_one_design_and_the_report_still_comes_back(fake_llm, capsys):
    fake_llm.queue(
        "这不是 JSON",                                    # t1 — dropped
        json.dumps(JD, ensure_ascii=False),               # t2 — kept
    )
    decisions = {"decisions": [human_decision("t1"), human_decision("t2", "表单开发")]}

    report = generate_jd_report(decisions, REQUIREMENT, "官网改版")

    assert report["needs_hiring"] is True
    assert report["job_count"] == 1
    assert [j["task_id"] for j in report["job_designs"]] == ["t2"]
    assert report["average_water_score"] == 88
    assert "Job design failed for task t1" in capsys.readouterr().out


def test_a_design_that_was_skipped_is_never_billed(fake_llm):
    """The `on_design` callback (U6 billing) must not fire for a dropped JD."""
    billed = []
    fake_llm.queue("这不是 JSON")
    decisions = {"decisions": [human_decision("t1")]}

    report = generate_jd_report(
        decisions, REQUIREMENT, "官网改版", on_design=lambda task, jd: billed.append(task["id"])
    )

    assert billed == []
    assert report["job_count"] == 0
