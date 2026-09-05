"""
Application Agent + Tracker Agent
- generate_cover_letter: 根据候选人 profile + 岗位 JD 生成定制化投递材料
- apply_to_job: 记录投递
- get_applications: 查询投递记录（Tracker）
"""
import os
import json
import uuid
from datetime import datetime
from openai import OpenAI

from app.agents.lang_support import localize, pick


# ─── In-memory application store (demo) ───────────────────────────────────────

_applications: list[dict] = []

# Demo jobs to show on candidate side when no company session exists.
#
# WP-I18N-2 / D-B: every user-facing string is a `{"zh": ..., "en": ...}` node;
# ids (`job_id`), enum-ish values (`work_type`, `source`) and numbers stay
# plain. `get_demo_jobs(lang)` resolves them — with no `lang` it returns
# byte-identically what it returned before this change.
DEMO_JOBS = [
    {
        "job_id": "demo_job_1",
        "job_title": {"zh": "全栈工程师", "en": "Full-stack Engineer"},
        "core_responsibilities": {
            "zh": [
                "负责前端 React 页面开发与维护",
                "设计并实现 Node.js 后端 API",
                "参与系统架构设计和技术选型",
            ],
            "en": [
                "Build and maintain the React frontend",
                "Design and implement the Node.js backend API",
                "Contribute to system architecture and technology choices",
            ],
        },
        "required_skills": ["React", "Node.js", "TypeScript", "RESTful API"],
        "nice_to_have_skills": ["Docker", "PostgreSQL", "AWS"],
        "experience_range": {"min": 2, "max": 5, "unit": {"zh": "年", "en": "years"}},
        "salary_range": {"min": 20000, "max": 35000, "unit": {"zh": "元/月", "en": "CNY/month"}},
        "work_type": "full-time",
        "water_score": 85,
        "water_analysis": {
            "zh": "需求明确，职责具体，技能要求合理",
            "en": "Clear requirement, concrete responsibilities, reasonable skill bar",
        },
        "company": {"zh": "某科技创业公司", "en": "A technology startup"},
        "source": "demo",
    },
    {
        "job_id": "demo_job_2",
        "job_title": {"zh": "AI 产品经理", "en": "AI Product Manager"},
        "core_responsibilities": {
            "zh": [
                "负责 AI 功能的产品规划和需求文档",
                "协调研发、设计团队推动产品迭代",
                "分析用户数据，驱动产品决策",
            ],
            "en": [
                "Own product planning and requirement docs for AI features",
                "Coordinate engineering and design to drive product iterations",
                "Analyse user data and turn it into product decisions",
            ],
        },
        "required_skills": {
            "zh": ["PRD 写作", "需求分析", "数据分析", "AI 产品设计"],
            "en": ["PRD writing", "Requirements analysis", "Data analysis", "AI product design"],
        },
        "nice_to_have_skills": {
            "zh": ["Prompt Engineering", "用户研究", "A/B 测试"],
            "en": ["Prompt Engineering", "User research", "A/B testing"],
        },
        "experience_range": {"min": 2, "max": 4, "unit": {"zh": "年", "en": "years"}},
        "salary_range": {"min": 18000, "max": 30000, "unit": {"zh": "元/月", "en": "CNY/month"}},
        "work_type": "full-time",
        "water_score": 78,
        "water_analysis": {
            "zh": "职责清晰，AI 方向有加分项但非强制",
            "en": "Responsibilities are clear; AI background is a plus, not a hard requirement",
        },
        "company": {"zh": "AI 应用公司", "en": "An applied-AI company"},
        "source": "demo",
    },
    {
        "job_id": "demo_job_3",
        "job_title": {"zh": "数据分析师", "en": "Data Analyst"},
        "core_responsibilities": {
            "zh": [
                "建立和维护业务数据看板",
                "进行用户行为分析和漏斗分析",
                "输出数据洞察报告支持业务决策",
            ],
            "en": [
                "Build and maintain the business metrics dashboards",
                "Run user-behaviour and funnel analysis",
                "Publish insight reports that support business decisions",
            ],
        },
        "required_skills": {
            "zh": ["Python", "SQL", "数据可视化", "统计分析"],
            "en": ["Python", "SQL", "Data visualisation", "Statistical analysis"],
        },
        "nice_to_have_skills": {
            "zh": ["机器学习", "Tableau", "Spark"],
            "en": ["Machine learning", "Tableau", "Spark"],
        },
        "experience_range": {"min": 1, "max": 4, "unit": {"zh": "年", "en": "years"}},
        "salary_range": {"min": 15000, "max": 25000, "unit": {"zh": "元/月", "en": "CNY/month"}},
        "work_type": "full-time",
        "water_score": 90,
        "water_analysis": {
            "zh": "需求描述与实际职责高度一致，无夸大要求",
            "en": "The posting matches the actual responsibilities closely, with no inflated requirements",
        },
        "company": {"zh": "电商平台", "en": "An e-commerce platform"},
        "source": "demo",
    },
]


# ─── LLM ──────────────────────────────────────────────────────────────────────

def _get_llm():
    api_key = os.getenv("ZHIPU_API_KEY")
    base_url = os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
    return OpenAI(api_key=api_key, base_url=base_url)


def _get_model():
    return os.getenv("ZHIPU_MODEL", "glm-4-plus")


# ─── Cover Letter Generator ────────────────────────────────────────────────────

COVER_LETTER_PROMPT = """你是求职助手，根据候选人背景和岗位要求，生成精准的投递材料。

要求：
1. 开场简洁有力，直接说明匹配点
2. 重点突出与该岗位最相关的 2-3 个技能/经历
3. 结尾表达意愿，不要套话
4. 总字数控制在 150-200 字

只输出 JSON，格式：
{
  "subject": "邮件主题（10字内）",
  "cover_letter": "正文内容",
  "key_match_points": ["匹配点1", "匹配点2", "匹配点3"],
  "match_score": 0到100的整数
}"""


def generate_cover_letter(candidate_profile: dict, job_design: dict) -> dict:
    """
    Generate a customized cover letter for a candidate applying to a job.
    """
    client = _get_llm()

    skills = candidate_profile.get("skills", [])
    experience = candidate_profile.get("experience", [])
    bio = candidate_profile.get("bio", "")
    name = candidate_profile.get("name", "候选人")

    required = job_design.get("required_skills", [])
    responsibilities = job_design.get("core_responsibilities", [])
    job_title = job_design.get("job_title", "")
    company = job_design.get("company", "贵公司")

    prompt = f"""候选人信息：
姓名：{name}
自我介绍：{bio or '无'}
技能：{', '.join(skills[:8]) if skills else '未知'}
工作经历：{'; '.join(experience[:3]) if experience else '未知'}

目标岗位：{job_title} @ {company}
岗位职责：{'; '.join(responsibilities)}
必要技能：{', '.join(required)}

请生成投递材料。"""

    resp = client.chat.completions.create(
        model=_get_model(),
        messages=[
            {"role": "system", "content": COVER_LETTER_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
    )

    raw = resp.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    result = json.loads(raw)
    result["candidate_name"] = name
    result["job_title"] = job_title
    return result


# ─── Application Store ─────────────────────────────────────────────────────────

#: The one status an application is created with. Resolved at write time —
#: the record is stored, so localising it later would need a per-reader pass
#: over a demo store that also freezes `candidate_name` / `job_title` in the
#: language the application was submitted in.
APPLIED_STATUS = {"zh": "已投递", "en": "Submitted"}


def apply_to_job(
    candidate_id: str,
    candidate_profile: dict,
    job_design: dict,
    cover_letter_result: dict,
    lang: str | None = None,
) -> dict:
    """Record an application and return the application record."""
    app = {
        "application_id": str(uuid.uuid4())[:8],
        "candidate_id": candidate_id,
        "candidate_name": candidate_profile.get("name", ""),
        "job_id": job_design.get("job_id", str(uuid.uuid4())[:8]),
        "job_title": job_design.get("job_title", ""),
        "company": job_design.get("company", ""),
        "applied_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "status": pick(APPLIED_STATUS, lang),
        "cover_letter": cover_letter_result.get("cover_letter", ""),
        "subject": cover_letter_result.get("subject", ""),
        "key_match_points": cover_letter_result.get("key_match_points", []),
        "match_score": cover_letter_result.get("match_score", 0),
    }
    _applications.append(app)
    return app


def get_applications(candidate_id: str = None) -> list[dict]:
    """Get application records, optionally filtered by candidate."""
    if candidate_id:
        return [a for a in _applications if a["candidate_id"] == candidate_id]
    return list(_applications)


def get_demo_jobs(lang: str | None = None) -> list[dict]:
    """Return demo jobs for candidate-side matching, resolved into one language.

    `lang` absent -> the Chinese literals, byte-identical to the pre-i18n
    return value. Always a fresh list of fresh dicts (`localize` rebuilds
    containers), so a caller that mutates a job cannot corrupt the seed.
    """
    return [localize(job, lang) for job in DEMO_JOBS]
