"""
Job Design Agent
When Resource Decision Engine decides human hiring is needed,
this agent generates a clean, realistic JD with a "water score"
"""
import os
import uuid
from openai import OpenAI

from app.agents.lang_support import pick, with_lang_messages
from app.services.validation import parse_llm_json


def get_llm_client():
    from app.agents.agents import get_llm_client as _get
    return _get()


def get_model():
    return os.getenv("ZHIPU_MODEL", "glm-4-plus")


JOB_DESIGN_SYSTEM_PROMPT = """你是 HireNet 的岗位设计 Agent。
你的任务是基于真实需求生成"去水"的岗位定义。

原则：
1. 职责要具体、可验证，不要空泛
2. 技能要求必须区分"必要"和"加分项"
3. 经验年限给出合理区间，不要夸大
4. 薪资范围参考市场水平，不要虚高
5. 最后输出"JD水分评分"：将原始模糊描述与最终JD对比，100分=完全一致，0分=完全失真

只输出 JSON，格式如下：
{
  "job_title": "岗位名称",
  "core_responsibilities": ["职责1", "职责2", "职责3"],
  "required_skills": ["必要技能1", "必要技能2"],
  "nice_to_have_skills": ["加分技能1", "加分技能2"],
  "experience_range": {"min": 1, "max": 3, "unit": "年"},
  "salary_range": {"min": 15000, "max": 25000, "unit": "元/月"},
  "work_type": "full-time | part-time | contract | freelance",
  "water_score": 75,
  "water_analysis": "与原始描述相比，去除了X个夸大要求，澄清了Y个模糊职责",
  "red_flags_removed": ["移除的夸大要求1", "移除的夸大要求2"]
}"""


def design_job(
    requirement: dict,
    task: dict,
    original_description: str = "",
    lang: str | None = None,
) -> dict:
    """
    Generate a clean, realistic job description based on actual needs.

    Args:
        requirement: Structured requirement from RequirementAnalysisAgent
        task: Specific task that needs human execution
        original_description: The original raw input for water score comparison
        lang: WP-I18N / I2 — "en" appends the output-language directive to
            the system prompt at request time (`app.agents.lang_support`).
            JOB_DESIGN_SYSTEM_PROMPT itself is never edited.
    """
    client = get_llm_client()

    prompt = f"""基于以下真实需求，生成岗位定义：

原始需求描述（用于水分对比）：
{original_description or requirement.get('core_description', '未提供')}

经过澄清的真实需求：
- 项目：{requirement.get('project_name', '未知')}
- 核心描述：{requirement.get('core_description', '')}
- 持续时间：{requirement.get('duration', 'unknown')}
- 团队背景：{requirement.get('team_context', '')}
- 预算水平：{requirement.get('budget_hint', 'unknown')}

需要完成的具体任务：
- 任务名：{task.get('name', '')}
- 任务描述：{task.get('description', '')}
- 类型：{task.get('type', '')}
- 预计工时：{task.get('estimated_hours', 0)}小时
- 是否需要判断力：{'是' if task.get('requires_judgment') else '否'}
- 是否长期重复：{'是' if task.get('is_recurring') else '否'}

请生成精准、去水的岗位定义。"""

    messages = with_lang_messages(
        [
            {"role": "system", "content": JOB_DESIGN_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        lang,
    )
    resp = client.chat.completions.create(
        model=get_model(),
        messages=messages,
        temperature=0.3,
    )

    # CLAUDE.md TIER-1 rule 1: no bare `json.loads` on model output. The old
    # `raw.replace("```json", "").replace("```", "")` mangled any JD whose text
    # happened to contain a backtick fence and then handed the result to
    # `json.loads`; `parse_llm_json` strips the fence properly and finds the
    # object even when the model wraps it in a sentence. A failure still raises
    # (JSONDecodeError / ValueError) and is still caught one frame up in
    # `generate_jd_report`, which skips this design — behaviour unchanged.
    raw = resp.choices[0].message.content.strip()
    job_design = parse_llm_json(raw)
    job_design["task_id"] = task.get("id")
    job_design["task_name"] = task.get("name")
    # Stage 1 / D11a (audit risk 8): nothing used to set a job_id, so a JD the
    # analysis flow produced could not be addressed afterwards — `POST
    # /api/jobs/publish` and the candidate side both key on job_id. task_id is
    # not a substitute: two analysis sessions both decompose to "t1", and the
    # candidate side dedupes on job_id — reusing task_id would make the second
    # employer's JD silently vanish behind the first one's.
    job_design["job_id"] = f"jd_{uuid.uuid4().hex[:12]}"
    return job_design


#: `jd_report.message` when the decision engine routed every task to an Agent.
NO_HIRING_MESSAGE = {
    "zh": "所有任务均可由 Agent 完成，无需招聘",
    "en": "Every task can be handled by an Agent — no hiring needed",
}

#: The five `water_interpretation` bands, highest score first.
WATER_INTERPRETATION_VERY_HIGH = {
    "zh": "JD 描述与实际需求高度一致，信息可信度高",
    "en": "The JD matches the real requirement closely — high confidence in the posting",
}
WATER_INTERPRETATION_HIGH = {
    "zh": "JD 描述较为准确，有少量优化空间",
    "en": "The JD is broadly accurate, with a little room to tighten it",
}
WATER_INTERPRETATION_MEDIUM = {
    "zh": "JD 存在中等程度失真，已进行关键修正",
    "en": "The JD was moderately distorted; the key points have been corrected",
}
WATER_INTERPRETATION_LOW = {
    "zh": "原始 JD 存在较多水分，本次进行了大幅优化",
    "en": "The original JD was substantially inflated and has been heavily rewritten",
}
WATER_INTERPRETATION_VERY_LOW = {
    "zh": "原始需求描述严重失真，建议重新沟通确认",
    "en": "The original description was severely distorted — talk it through again before posting",
}


def generate_jd_report(
    decisions: dict,
    requirement: dict,
    original_description: str,
    on_design=None,
    lang: str | None = None,
) -> dict:
    """
    For all tasks that need human hiring, generate job designs.
    Returns a full hiring report.

    on_design: optional callback `(task: dict, job_design: dict) -> None` invoked
    once per SUCCESSFULLY generated job design. U6 uses it to bill one SkillAsset
    invocation (writes agent_runs + royalty_ledger via the U4 path). Default None
    keeps existing behaviour unchanged. The callback runs OUTSIDE the design_job
    try block on purpose: a design failure must not trigger billing, and a billing
    failure must propagate (not be swallowed) so no royalty is silently lost.

    lang: WP-I18N / I2 — forwarded to every `design_job` call this makes.
    """
    # `(d.get("recommendation") or {})`: a decision may carry recommendation=None
    # (no evaluations survived), and the two-arg .get default only covers a
    # missing key, not a present None. See _build_decision_summary in app/app.py.
    human_tasks = [
        d for d in decisions.get("decisions", [])
        if (d.get("recommendation") or {}).get("decision") in ("human", "hybrid")
    ]

    if not human_tasks:
        return {
            "needs_hiring": False,
            "message": pick(NO_HIRING_MESSAGE, lang),
            "job_designs": [],
        }

    job_designs = []
    for task_decision in human_tasks:
        # Rebuild the task the JD is written from.
        #
        # Stage 1 / D6 (audit risk 5): `estimated_hours`, `requires_judgment`
        # and `is_recurring` are REAL task fields the decomposition step
        # produces — but v1's run_resource_decision drops them, so this function
        # had nothing to read and fabricated all three: every JD was written as
        # "40 hours, judgment required", and `is_recurring` was guessed from the
        # requirement's duration string. TaskAnalysisAgent (v2) carries them
        # onto the decision, so when they are there we use them.
        #
        # `key in task_decision` rather than `.get(key, default)`: `False` and
        # `0` are meaningful values that a truthiness test would silently
        # replace with the fabricated default. A v1 decision carries none of the
        # three keys, so v1 output is bit-for-bit what it was.
        task = {
            "id": task_decision["task_id"],
            "name": task_decision["task_name"],
            "type": task_decision["task_type"],
            "description": task_decision.get("task_description", ""),
            "requires_judgment": (
                task_decision["requires_judgment"]
                if "requires_judgment" in task_decision
                else True
            ),
            "is_recurring": (
                task_decision["is_recurring"]
                if "is_recurring" in task_decision
                else requirement.get("duration") == "ongoing"
            ),
            "estimated_hours": (
                task_decision["estimated_hours"]
                if "estimated_hours" in task_decision
                else 40  # fabricated default, v1 only
            ),
        }

        try:
            jd = design_job(requirement, task, original_description, lang=lang)
        except Exception as e:
            print(f"Job design failed for task {task['id']}: {e}")
            continue

        job_designs.append(jd)
        if on_design is not None:
            on_design(task, jd)  # bill one invocation; billing errors propagate

    # Calculate overall water score
    if job_designs:
        avg_water_score = sum(j.get("water_score", 50) for j in job_designs) / len(job_designs)
    else:
        avg_water_score = 50

    return {
        "needs_hiring": True,
        "job_count": len(job_designs),
        "average_water_score": round(avg_water_score),
        "water_interpretation": _interpret_water_score(avg_water_score, lang),
        "job_designs": job_designs,
    }


def _interpret_water_score(score: float, lang: str | None = None) -> str:
    """One of five fixed sentences for the JD "water" (inflation) score.

    WP-I18N-2 / D-D: bilingual like the decision-policy strings — the report
    these land in is part of the /api/analyze/decide and /quick responses, so
    an English session must not get Chinese here. `lang` absent gives exactly
    the pre-change Chinese sentence.
    """
    if score >= 85:
        band = WATER_INTERPRETATION_VERY_HIGH
    elif score >= 70:
        band = WATER_INTERPRETATION_HIGH
    elif score >= 50:
        band = WATER_INTERPRETATION_MEDIUM
    elif score >= 30:
        band = WATER_INTERPRETATION_LOW
    else:
        band = WATER_INTERPRETATION_VERY_LOW
    return pick(band, lang)
