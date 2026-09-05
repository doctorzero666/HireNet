"""
Candidate Profile Agent
Manages demo candidate and agent profiles for matching.

WP-I18N-2 / D-B: every user-facing string below is a `{"zh": ..., "en": ...}`
node. Dict KEYS and every id (`candidate_a`, `agent_code`, …) are unchanged —
they are used as identifiers by `build_candidate_profile`, `/api/jobs` dedup
and the decision policy's cost lookup.

The accessors (`build_candidate_profile`, `build_agent_profile`,
`get_all_resources`) take an optional `lang` and return a fully RESOLVED dict,
so no caller ever sees a `{"zh", "en"}` node. With `lang` absent they return
byte-identically what they returned before this change — which matters
because these dicts are also fed into the resource-evaluation prompt, whose
v1 wire format `tests/test_prompts.py` pins.
"""
from app.agents.lang_support import DEFAULT_LANG, SUPPORTED_LANGS, localize

DEMO_CANDIDATES = {
    "candidate_a": {
        "name": {"zh": "张伟（全栈工程师）", "en": "Wei Zhang (Full-stack Engineer)"},
        "role_hint": "fullstack",
    },
    "candidate_b": {
        "name": {"zh": "李娜（产品经理）", "en": "Na Li (Product Manager)"},
        "role_hint": "product_manager",
    },
    "candidate_c": {
        "name": {"zh": "王芳（数据分析师）", "en": "Fang Wang (Data Analyst)"},
        "role_hint": "data_analyst",
    },
}

MOCK_PROFILES = {
    "candidate_a": {
        "id": "candidate_a",
        "type": "human",
        "name": {"zh": "张伟（全栈工程师）", "en": "Wei Zhang (Full-stack Engineer)"},
        "bio": {
            "zh": "3年全栈开发经验，熟悉React+Node.js技术栈，有独立交付产品经验",
            "en": (
                "3 years of full-stack development experience, fluent in the "
                "React + Node.js stack, has shipped products end to end alone"
            ),
        },
        "role_hint": "fullstack",
        "skills": ["React", "Node.js", "TypeScript", "Python", "Docker", "PostgreSQL", "RESTful API", "Git"],
        "experience": {
            "zh": ["某互联网公司全栈工程师3年，负责前后端开发和系统架构"],
            "en": [
                "3 years as a full-stack engineer at an internet company, "
                "responsible for frontend, backend and system architecture"
            ],
        },
        "preferences": {
            "zh": ["全栈工程师", "前端工程师"],
            "en": ["Full-stack Engineer", "Frontend Engineer"],
        },
        # Composed sentence, not a mechanical join — it gets its own English
        # text rather than a wrapped sub-field (WP-I18N-2 / D-B).
        "capability_summary": {
            "zh": "技能：React、Node.js、TypeScript、Python、Docker；经验：3年全栈开发，独立交付多个产品",
            "en": (
                "Skills: React, Node.js, TypeScript, Python, Docker. "
                "Experience: 3 years of full-stack development, several products shipped solo"
            ),
        },
        "profile_completeness": 85,
        "raw_memories": [],
    },
    "candidate_b": {
        "id": "candidate_b",
        "type": "human",
        "name": {"zh": "李娜（产品经理）", "en": "Na Li (Product Manager)"},
        "bio": {
            "zh": "2年AI产品经理经验，擅长需求分析和PRD撰写，有AI产品从0到1落地经验",
            "en": (
                "2 years as an AI product manager, strong at requirements "
                "analysis and PRD writing, has taken AI products from zero to one"
            ),
        },
        "role_hint": "product_manager",
        "skills": {
            "zh": ["需求分析", "PRD写作", "AI产品设计", "用户研究", "数据分析", "Prompt Engineering"],
            "en": [
                "Requirements analysis", "PRD writing", "AI product design",
                "User research", "Data analysis", "Prompt Engineering",
            ],
        },
        "experience": {
            "zh": ["AI创业公司产品经理2年，主导3个AI产品从立项到上线"],
            "en": [
                "2 years as a product manager at an AI startup, led 3 AI "
                "products from kickoff to launch"
            ],
        },
        "preferences": {
            "zh": ["AI产品经理", "产品总监"],
            "en": ["AI Product Manager", "Head of Product"],
        },
        "capability_summary": {
            "zh": "技能：需求分析、PRD写作、AI产品设计、用户研究；经验：2年AI产品经理，3个产品从0到1",
            "en": (
                "Skills: requirements analysis, PRD writing, AI product design, "
                "user research. Experience: 2 years as an AI product manager, "
                "3 products taken from zero to one"
            ),
        },
        "profile_completeness": 80,
        "raw_memories": [],
    },
    "candidate_c": {
        "id": "candidate_c",
        "type": "human",
        "name": {"zh": "王芳（数据分析师）", "en": "Fang Wang (Data Analyst)"},
        "bio": {
            "zh": "4年数据分析经验，精通Python/SQL，有电商和金融行业数据建模经验",
            "en": (
                "4 years of data analysis experience, expert in Python and SQL, "
                "has built data models for e-commerce and finance"
            ),
        },
        "role_hint": "data_analyst",
        "skills": {
            "zh": ["Python", "SQL", "数据可视化", "机器学习", "Tableau", "Spark", "统计分析", "数据建模"],
            "en": [
                "Python", "SQL", "Data visualisation", "Machine learning",
                "Tableau", "Spark", "Statistical analysis", "Data modelling",
            ],
        },
        "experience": {
            "zh": ["某电商平台数据分析师4年，负责用户行为分析和推荐系统数据支持"],
            "en": [
                "4 years as a data analyst at an e-commerce platform, covering "
                "user-behaviour analysis and data support for the recommendation system"
            ],
        },
        "preferences": {
            "zh": ["数据分析师", "数据科学家"],
            "en": ["Data Analyst", "Data Scientist"],
        },
        "capability_summary": {
            "zh": "技能：Python、SQL、数据可视化、机器学习、Tableau；经验：4年数据分析，电商平台用户行为分析",
            "en": (
                "Skills: Python, SQL, data visualisation, machine learning, "
                "Tableau. Experience: 4 years of data analysis, user-behaviour "
                "analysis at an e-commerce platform"
            ),
        },
        "profile_completeness": 90,
        "raw_memories": [],
    },
}

DEMO_AGENTS = {
    "agent_code": {
        "name": {"zh": "代码生成 Agent", "en": "Code Generation Agent"},
        "type": "agent",
        "capabilities": {
            "zh": ["前端开发", "后端开发", "脚本编写", "代码审查"],
            "en": ["Frontend development", "Backend development", "Scripting", "Code review"],
        },
        # Not user-prose: a currency string the decision policy reads verbatim
        # as `cost_hint` (`decision_policy.DEFAULT_COST_LOOKUP`). Same in both
        # languages, so it stays a plain value.
        "cost_per_task": "$0.05",
    },
    "agent_content": {
        "name": {"zh": "文案撰写 Agent", "en": "Copywriting Agent"},
        "type": "agent",
        "capabilities": {
            "zh": ["营销文案", "产品描述", "SEO文章", "邮件撰写"],
            "en": ["Marketing copy", "Product descriptions", "SEO articles", "Email writing"],
        },
        "cost_per_task": "$0.02",
    },
    "agent_data": {
        "name": {"zh": "数据分析 Agent", "en": "Data Analysis Agent"},
        "type": "agent",
        "capabilities": {
            "zh": ["数据清洗", "报表生成", "数据可视化", "统计分析"],
            "en": ["Data cleaning", "Report generation", "Data visualisation", "Statistical analysis"],
        },
        "cost_per_task": "$0.03",
    },
}

#: How a list of capabilities is joined into one `capability_summary` line.
#: Chinese uses the enumeration comma "、" (which is what the pre-i18n code
#: emitted); English uses ", ". A composed string, so it is built per language
#: rather than wrapped after the fact.
_CAPABILITY_JOINER = {"zh": "、", "en": ", "}


def _resolved(lang: str | None) -> str:
    """`lang` if it is one we support, else the default (Chinese)."""
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


def build_candidate_profile(candidate_id: str, lang: str | None = None) -> dict:
    """Return candidate profile (mock data), resolved into one language."""
    if candidate_id not in MOCK_PROFILES:
        raise ValueError(f"Unknown candidate: {candidate_id}")
    return localize(MOCK_PROFILES[candidate_id], lang)


def build_agent_profile(agent_id: str, lang: str | None = None) -> dict:
    """Build functional agent profile, resolved into one language."""
    agent = DEMO_AGENTS.get(agent_id)
    if not agent:
        raise ValueError(f"Unknown agent: {agent_id}")
    capabilities = localize(agent["capabilities"], lang)
    return {
        "id": agent_id,
        "type": "agent",
        "name": localize(agent["name"], lang),
        "capabilities": capabilities,
        "cost_per_task": agent["cost_per_task"],
        "availability": "immediate",
        "capability_summary": _CAPABILITY_JOINER[_resolved(lang)].join(capabilities),
    }


def get_all_resources(lang: str | None = None) -> list[dict]:
    """Get all available resources (candidates + agents) for matching."""
    resources = []
    for agent_id in DEMO_AGENTS:
        try:
            resources.append(build_agent_profile(agent_id, lang))
        except Exception as e:
            print(f"Warning: Could not load agent {agent_id}: {e}")
    for candidate_id in MOCK_PROFILES:
        resources.append(localize(MOCK_PROFILES[candidate_id], lang))
    return resources
