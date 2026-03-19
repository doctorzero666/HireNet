"""
Candidate Profile Agent
Reads candidate's Second Me soft memories and builds structured profile
"""
import os
from secondme_client import SecondMeClient


# Pre-authorized tokens for the 3 demo candidate accounts
DEMO_CANDIDATES = {
    "candidate_a": {
        "token": os.getenv("CANDIDATE_A_TOKEN"),
        "name": "张伟（全栈工程师）",
        "role_hint": "fullstack",
    },
    "candidate_b": {
        "token": os.getenv("CANDIDATE_B_TOKEN"),
        "name": "李娜（产品经理）",
        "role_hint": "product_manager",
    },
    "candidate_c": {
        "token": os.getenv("CANDIDATE_C_TOKEN"),
        "name": "王芳（数据分析师）",
        "role_hint": "data_analyst",
    },
}

MOCK_PROFILES = {
    "candidate_a": {
        "id": "candidate_a",
        "type": "human",
        "name": "张伟（全栈工程师）",
        "bio": "3年全栈开发经验，熟悉React+Node.js技术栈，有独立交付产品经验",
        "role_hint": "fullstack",
        "skills": ["React", "Node.js", "TypeScript", "Python", "Docker", "PostgreSQL", "RESTful API", "Git"],
        "experience": ["某互联网公司全栈工程师3年，负责前后端开发和系统架构"],
        "preferences": ["全栈工程师", "前端工程师"],
        "capability_summary": "技能：React、Node.js、TypeScript、Python、Docker；经验：3年全栈开发，独立交付多个产品",
        "profile_completeness": 85,
        "raw_memories": [],
    },
    "candidate_b": {
        "id": "candidate_b",
        "type": "human",
        "name": "李娜（产品经理）",
        "bio": "2年AI产品经理经验，擅长需求分析和PRD撰写，有AI产品从0到1落地经验",
        "role_hint": "product_manager",
        "skills": ["需求分析", "PRD写作", "AI产品设计", "用户研究", "数据分析", "Prompt Engineering"],
        "experience": ["AI创业公司产品经理2年，主导3个AI产品从立项到上线"],
        "preferences": ["AI产品经理", "产品总监"],
        "capability_summary": "技能：需求分析、PRD写作、AI产品设计、用户研究；经验：2年AI产品经理，3个产品从0到1",
        "profile_completeness": 80,
        "raw_memories": [],
    },
    "candidate_c": {
        "id": "candidate_c",
        "type": "human",
        "name": "王芳（数据分析师）",
        "bio": "4年数据分析经验，精通Python/SQL，有电商和金融行业数据建模经验",
        "role_hint": "data_analyst",
        "skills": ["Python", "SQL", "数据可视化", "机器学习", "Tableau", "Spark", "统计分析", "数据建模"],
        "experience": ["某电商平台数据分析师4年，负责用户行为分析和推荐系统数据支持"],
        "preferences": ["数据分析师", "数据科学家"],
        "capability_summary": "技能：Python、SQL、数据可视化、机器学习、Tableau；经验：4年数据分析，电商平台用户行为分析",
        "profile_completeness": 90,
        "raw_memories": [],
    },
}

# Pre-authorized tokens for the 3 demo functional agents
DEMO_AGENTS = {
    "agent_code": {
        "token": os.getenv("AGENT_CODE_TOKEN"),
        "name": "代码生成 Agent",
        "type": "agent",
        "capabilities": ["前端开发", "后端开发", "脚本编写", "代码审查"],
        "cost_per_task": "$0.05",
    },
    "agent_content": {
        "token": os.getenv("AGENT_CONTENT_TOKEN"),
        "name": "文案撰写 Agent",
        "type": "agent",
        "capabilities": ["营销文案", "产品描述", "SEO文章", "邮件撰写"],
        "cost_per_task": "$0.02",
    },
    "agent_data": {
        "token": os.getenv("AGENT_DATA_TOKEN"),
        "name": "数据分析 Agent",
        "type": "agent",
        "capabilities": ["数据清洗", "报表生成", "数据可视化", "统计分析"],
        "cost_per_task": "$0.03",
    },
}


def build_candidate_profile(candidate_id: str) -> dict:
    """
    Read candidate's soft memories from Second Me and build structured profile.
    Returns a unified capability card compatible with agent format.
    Falls back to MOCK_PROFILES when token is missing.
    """
    candidate = DEMO_CANDIDATES.get(candidate_id)
    if not candidate:
        raise ValueError(f"Unknown candidate: {candidate_id}")

    if not candidate.get("token"):
        if candidate_id in MOCK_PROFILES:
            return MOCK_PROFILES[candidate_id]
        raise ValueError(f"Missing token and no mock profile for: {candidate_id}")

    client = SecondMeClient(candidate["token"])

    # Get basic info
    user_info = client.get_user_info()

    # Get all soft memories (skills, experience, preferences)
    memories = client.get_soft_memories()

    # Categorize memories
    skills = []
    experience = []
    preferences = []
    bio_parts = []

    for mem in memories:
        obj = mem.get("factObject", "").lower()
        content = mem.get("factContent", "")

        if any(k in obj for k in ["技能", "skill", "能力", "擅长"]):
            skills.append(content)
        elif any(k in obj for k in ["经历", "经验", "工作", "项目", "experience"]):
            experience.append(content)
        elif any(k in obj for k in ["期望", "偏好", "preference", "目标"]):
            preferences.append(content)
        else:
            bio_parts.append(f"{mem['factObject']}: {content}")

    # Build unified capability card
    profile = {
        "id": candidate_id,
        "type": "human",
        "name": user_info.get("name", candidate["name"]),
        "bio": user_info.get("selfIntroduction") or user_info.get("bio", ""),
        "role_hint": candidate["role_hint"],
        "skills": skills,
        "experience": experience,
        "preferences": preferences,
        "raw_memories": memories,
        "profile_completeness": user_info.get("profileCompleteness", 0),
        # Used by Matching Engine
        "capability_summary": _build_capability_summary(skills, experience),
    }

    return profile


def build_agent_profile(agent_id: str) -> dict:
    """
    Build functional agent profile.
    For agents, we use pre-defined capabilities (no API call needed).
    Optionally reads from agent's Second Me softmemory for richer description.
    """
    agent = DEMO_AGENTS.get(agent_id)
    if not agent:
        raise ValueError(f"Unknown agent: {agent_id}")

    profile = {
        "id": agent_id,
        "type": "agent",
        "name": agent["name"],
        "capabilities": agent["capabilities"],
        "cost_per_task": agent["cost_per_task"],
        "availability": "immediate",  # agents are always available
        "capability_summary": "、".join(agent["capabilities"]),
    }

    # Optionally enrich with softmemory if token available
    if agent.get("token"):
        try:
            client = SecondMeClient(agent["token"])
            memories = client.get_soft_memories()
            if memories:
                profile["extended_capabilities"] = [
                    m["factContent"] for m in memories
                ]
        except Exception:
            pass  # Fall back to pre-defined capabilities

    return profile


def get_all_resources() -> list[dict]:
    """
    Get all available resources (candidates + agents) for matching.
    This is the unified A2A network pool.
    """
    resources = []

    # Add functional agents (always available)
    for agent_id in DEMO_AGENTS:
        try:
            resources.append(build_agent_profile(agent_id))
        except Exception as e:
            print(f"Warning: Could not load agent {agent_id}: {e}")

    # Add candidate Second Mes
    for candidate_id in DEMO_CANDIDATES:
        try:
            resources.append(build_candidate_profile(candidate_id))
        except Exception as e:
            print(f"Warning: Could not load candidate {candidate_id}: {e}")
            if candidate_id in MOCK_PROFILES:
                resources.append(MOCK_PROFILES[candidate_id])
                print(f"  -> Using mock profile for {candidate_id}")

    return resources


def _build_capability_summary(skills: list, experience: list) -> str:
    """Build a short capability summary string for matching"""
    parts = []
    if skills:
        parts.append("技能：" + "、".join(skills[:5]))
    if experience:
        parts.append("经验：" + experience[0][:50] if experience else "")
    return "；".join(filter(None, parts)) or "暂无详细信息"
