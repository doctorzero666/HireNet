"""
HireNet Core Agents
- Requirement Analysis Agent  (multi-turn clarification via LLM)
- Task Decomposition Agent    (break requirement into tasks)
- Resource Decision Engine    (agent vs human decision via the ResourceDecision engine)
"""
import os
import json
from openai import OpenAI
from app.agents.candidate_profile import DEMO_AGENTS, get_all_resources
from app.agents.decision_policy import (
    AGENT_RECOMMENDATION_REASON,
    HUMAN_COST_HINT,
    HUMAN_FALLBACK_REASON,
    HUMAN_RECOMMENDATION_REASON,
    HYBRID_COST_HINT,
    HYBRID_REASON,
    UNKNOWN_COST_HINT,
    format_recommendation_reason,
)
from app.agents.lang_support import pick, with_lang_messages


# ─── LLM Client (Zhipu GLM-4, OpenAI-compatible) ──────────────────────────────

def get_llm_client() -> OpenAI:
    """Returns OpenAI-compatible client (Zhipu GLM-4 by default)"""
    api_key = os.getenv("ZHIPU_API_KEY")
    base_url = os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
    return OpenAI(api_key=api_key, base_url=base_url)


def get_model() -> str:
    return os.getenv("ZHIPU_MODEL", "glm-4-plus")


# ─── Requirement Analysis Agent ───────────────────────────────────────────────

REQUIREMENT_SYSTEM_PROMPT = """你是 HireNet 的需求分析 Agent。
你的任务是帮助企业澄清真实的项目需求，消除模糊表达。

规则：
1. 每次最多问 1-2 个最关键的问题，不要一次问太多
2. 问题要简洁、具体，帮助判断"这个任务是一次性的还是长期的？需要判断力还是可以标准化？"
3. 当你认为信息足够了（通常 2-4 轮对话后），输出结构化需求
4. 输出结构化需求时，必须以 [REQUIREMENT_COMPLETE] 开头，然后是 JSON

结构化需求 JSON 格式：
{
  "project_name": "项目名称",
  "core_description": "核心需求描述",
  "tasks_hint": ["可能的任务1", "可能的任务2"],
  "duration": "one-time | ongoing | unknown",
  "team_context": "团队背景描述",
  "urgency": "high | medium | low",
  "budget_hint": "low | medium | high | unknown"
}"""


class RequirementAnalysisAgent:
    def __init__(self, lang: str | None = None):
        """
        Args:
            lang: optional output-language flag ("en"/"zh"/None). WP-I18N /
                I2: when "en", every LLM call this agent makes gets
                `lang_support.LANG_SUFFIX` appended to its system prompt at
                request time. `self.history` itself never carries the
                suffix — `with_lang_messages` builds a fresh, suffixed copy
                for the wire on each call, so REQUIREMENT_SYSTEM_PROMPT stays
                byte-identical in `self.history` across the whole session
                (audit §7.4 / tests/test_prompts.py).
        """
        self.client = get_llm_client()
        self.history = []
        self.lang = lang

    def start(self, initial_input: str) -> str:
        """Start requirement analysis with user's initial description"""
        self.history = [
            {"role": "system", "content": REQUIREMENT_SYSTEM_PROMPT},
            {"role": "user", "content": initial_input},
        ]
        return self._call_llm()

    def reply(self, user_message: str) -> str:
        """Continue the conversation"""
        self.history.append({"role": "user", "content": user_message})
        return self._call_llm()

    def _call_llm(self) -> str:
        messages = with_lang_messages(self.history, self.lang)
        resp = self.client.chat.completions.create(
            model=get_model(),
            messages=messages,
            temperature=0.3,
        )
        assistant_msg = resp.choices[0].message.content
        self.history.append({"role": "assistant", "content": assistant_msg})
        return assistant_msg

    def is_complete(self, response: str) -> bool:
        return "[REQUIREMENT_COMPLETE]" in response

    def extract_requirement(self, response: str) -> dict:
        """Extract structured requirement from response"""
        if "[REQUIREMENT_COMPLETE]" not in response:
            raise ValueError("Requirement not complete yet")
        json_str = response.split("[REQUIREMENT_COMPLETE]")[1].strip()
        # Remove markdown code block if present
        json_str = json_str.replace("```json", "").replace("```", "").strip()
        return json.loads(json_str)


# ─── Task Decomposition Agent ─────────────────────────────────────────────────

DECOMPOSITION_SYSTEM_PROMPT = """你是任务拆解 Agent。
将企业项目需求拆解为独立的、可分别判断执行方式的任务单元。

规则：
1. 每个任务要独立、可单独执行
2. 任务类型分为：technical（技术开发）、creative（创意内容）、analytical（数据分析）、strategic（策略规划）、operational（日常运营）
3. 预估工时要保守合理
4. 只输出 JSON，不要有其他文字
5. 最多输出5个任务，合并相似子任务

输出格式：
{
  "tasks": [
    {
      "id": "t1",
      "name": "任务名称",
      "description": "具体描述",
      "type": "technical | creative | analytical | strategic | operational",
      "estimated_hours": 8,
      "requires_judgment": true,
      "is_recurring": false
    }
  ]
}"""


def decompose_tasks(requirement: dict, lang: str | None = None) -> dict:
    """Break requirement into task units.

    `lang`: WP-I18N / I2 — "en" appends the output-language directive to the
    system prompt at request time (see `app.agents.lang_support`).
    """
    client = get_llm_client()

    prompt = f"""请将以下项目需求拆解为任务单元：

项目名称：{requirement.get('project_name', '未知')}
需求描述：{requirement.get('core_description', '')}
任务提示：{', '.join(requirement.get('tasks_hint', []))}
持续时间：{requirement.get('duration', 'unknown')}
团队背景：{requirement.get('team_context', '未知')}"""

    messages = with_lang_messages(
        [
            {"role": "system", "content": DECOMPOSITION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        lang,
    )
    resp = client.chat.completions.create(
        model=get_model(),
        messages=messages,
        temperature=0.2,
    )

    raw = resp.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


# ─── Resource Decision Engine ─────────────────────────────────────────────────

def evaluate_resource_for_task(resource: dict, task: dict, lang: str | None = None) -> dict:
    """Evaluate if a resource (agent or candidate) can complete a given task."""
    return _llm_evaluate_resource(resource, task, lang=lang)


def _llm_evaluate_resource(resource: dict, task: dict, lang: str | None = None) -> dict:
    """Fallback: use local LLM to evaluate resource-task fit

    `lang`: WP-I18N / I2 — "en" appends the output-language directive at
    request time. This call has no system message in the v1 wire format
    (single "user" message); `with_lang_messages` inserts a leading system
    message carrying only the suffix when lang=="en", and is a no-op
    otherwise (see `app.agents.lang_support`).
    """
    client = get_llm_client()

    capability_desc = resource.get("capability_summary") or \
                      "、".join(resource.get("capabilities", []))

    prompt = f"""评估资源是否能完成任务。

资源信息：
- 名称：{resource['name']}
- 类型：{'AI Agent' if resource['type'] == 'agent' else '人类候选人'}
- 能力：{capability_desc}

任务信息：
- 名称：{task['name']}
- 描述：{task['description']}
- 类型：{task['type']}
- 需要判断力：{'是' if task.get('requires_judgment') else '否'}

请输出 JSON，格式完全遵循以下结构：
{{
  "can_complete": true或false,
  "confidence": 0到1之间的数字,
  "reason": "一句话原因（中文）",
  "estimated_time": "时间估算",
  "strengths": ["优势1", "优势2"]
}}"""

    messages = with_lang_messages([{"role": "user", "content": prompt}], lang)
    resp = client.chat.completions.create(
        model=get_model(),
        messages=messages,
        temperature=0.2,
    )
    raw = resp.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    # Extract the first JSON object in case the LLM returns extra content
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Find the first complete JSON object. NOTE: this counter does not track
        # string literals, so a `{` or `}` inside a JSON string breaks it —
        # `app/services/validation.py:parse_llm_json` is the string-aware version.
        brace_count = 0
        start = raw.find('{')
        end = -1
        if start != -1:
            for i, ch in enumerate(raw[start:], start):
                if ch == '{':
                    brace_count += 1
                elif ch == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end = i + 1
                        break
        if end != -1:
            result = json.loads(raw[start:end])
        else:
            raise
    result["resource_id"] = resource["id"]
    result["resource_name"] = resource["name"]
    result["resource_type"] = resource["type"]
    return result


def _filter_resources_for_task(task: dict, resources: list[dict]) -> list[dict]:
    """
    Pre-filter resources based on task type to reduce LLM calls.
    Returns at most 3 relevant resources.
    """
    agents = {r["id"]: r for r in resources if r["type"] == "agent"}
    candidates = {r["id"]: r for r in resources if r["type"] == "human"}

    task_type = task.get("type", "")
    is_recurring = task.get("is_recurring", False)

    agent_content = agents.get("agent_content")
    agent_code = agents.get("agent_code")
    agent_data = agents.get("agent_data")
    candidate_b = candidates.get("candidate_b")
    # Get first candidate (fallback)
    first_candidate = next(iter(candidates.values()), None) if candidates else None

    if task_type == "creative":
        selected = [r for r in [agent_content, first_candidate] if r]
    elif task_type == "technical":
        selected = [r for r in [agent_code, first_candidate] if r]
    elif task_type == "analytical":
        selected = [r for r in [agent_data, first_candidate] if r]
    elif task_type == "strategic":
        pm = candidate_b or first_candidate
        selected = [r for r in [pm, agent_content] if r]
    elif task_type == "operational":
        selected = [r for r in [agent_content, agent_data] if r]
    else:
        selected = [r for r in [agent_content, agent_code, agent_data] if r]

    # For recurring tasks, always include all candidates
    if is_recurring:
        for c in candidates.values():
            if c not in selected:
                selected.append(c)

    return selected[:3]


# ─── Career Strategy Agent ────────────────────────────────────────────────────

CAREER_STRATEGY_SYSTEM_PROMPT = """你是 HireNet 的 Career Strategy Agent，一个真正关心求职者成长的职业顾问。

你的目标：通过 3-5 轮对话，深入了解用户的现状、困惑和期望，给出个性化、可落地的职业发展建议。

对话规则：
1. 每次最多问 1-2 个最关键的问题，不要一次问太多
2. 先倾听，再建议。前几轮专注了解现状，不要急着给建议
3. 语气温暖、具体、有力量感，避免空洞的励志话
4. 结合用户描述的真实技能和经历给出具体建议，不要泛泛而谈
5. 当你认为信息足够了（通常 3-5 轮对话后），输出结构化的职业策略
6. 输出结构化策略时，必须以 [STRATEGY_READY] 开头，然后是 JSON

结构化策略 JSON 格式：
{
  "summary": "一句话总结这个人的核心优势和方向",
  "directions": [
    {
      "title": "推荐方向名称",
      "reason": "为什么适合你（结合用户具体情况）",
      "next_action": "明天就能做的第一步行动"
    }
  ],
  "focus_skills": ["最值得投入的技能1", "技能2"],
  "avoid": "需要规避的陷阱或常见误区",
  "encouragement": "个性化的鼓励语（不要套话）"
}"""


class CareerStrategyAgent:
    def __init__(self):
        self.client = get_llm_client()
        self.history = []

    def start(self, initial_input: str) -> str:
        """开始职业策略对话"""
        self.history = [
            {"role": "system", "content": CAREER_STRATEGY_SYSTEM_PROMPT},
            {"role": "user", "content": initial_input},
        ]
        return self._call_llm()

    def reply(self, user_message: str) -> str:
        """继续对话"""
        self.history.append({"role": "user", "content": user_message})
        return self._call_llm()

    def _call_llm(self) -> str:
        resp = self.client.chat.completions.create(
            model=get_model(),
            messages=self.history,
            temperature=0.5,
        )
        assistant_msg = resp.choices[0].message.content
        self.history.append({"role": "assistant", "content": assistant_msg})
        return assistant_msg

    def is_complete(self, response: str) -> bool:
        return "[STRATEGY_READY]" in response

    def extract_strategy(self, response: str) -> dict:
        if "[STRATEGY_READY]" not in response:
            raise ValueError("Strategy not ready yet")
        json_str = response.split("[STRATEGY_READY]")[1].strip()
        json_str = json_str.replace("```json", "").replace("```", "").strip()
        return json.loads(json_str)

    def force_generate_strategy(self) -> dict:
        """
        Force the LLM to output a structured strategy JSON based on the
        conversation so far — bypassing the [STRATEGY_READY] detection.
        """
        force_prompt = """根据我们刚才的对话，现在请直接输出你对我的职业策略建议。
只输出以下 JSON，不要有任何其他文字：
{
  "summary": "一句话总结这个人的核心优势和方向",
  "directions": [
    {
      "title": "推荐方向名称",
      "reason": "为什么适合你（结合对话中的具体情况）",
      "next_action": "明天就能做的第一步行动"
    }
  ],
  "focus_skills": ["最值得投入的技能1", "技能2"],
  "avoid": "需要规避的陷阱或常见误区",
  "encouragement": "个性化的鼓励语（不要套话）"
}"""
        messages = list(self.history) + [{"role": "user", "content": force_prompt}]
        resp = self.client.chat.completions.create(
            model=get_model(),
            messages=messages,
            temperature=0.3,
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        # Find the first JSON object
        start = raw.find('{')
        if start == -1:
            raise ValueError("No JSON found in response")
        brace = 0
        for i, ch in enumerate(raw[start:], start):
            if ch == '{': brace += 1
            elif ch == '}':
                brace -= 1
                if brace == 0:
                    return json.loads(raw[start:i+1])
        raise ValueError("Could not parse strategy JSON")


def run_resource_decision(tasks: list[dict], lang: str | None = None) -> dict:
    """
    For each task, evaluate all resources and make final decision.
    Returns decision result for each task.

    `lang`: WP-I18N / I2, threaded down to every `evaluate_resource_for_task`
    call this makes. WP-I18N-2 also uses it to pick which side of the
    bilingual demo fixtures the pool is built from, so `resource_name` — which
    ends up verbatim inside `recommendation.reason` — is in the session's
    language. Absent -> the Chinese pool, byte-identical to before.
    """
    resources = get_all_resources(lang)
    decisions = []

    for task in tasks:
        task_result = {
            "task_id": task["id"],
            "task_name": task["name"],
            "task_type": task["type"],
            "evaluations": [],
            "recommendation": None,
        }

        # Pre-filter resources by task type to reduce LLM calls
        filtered_resources = _filter_resources_for_task(task, resources)

        # Evaluate filtered resources for this task
        for resource in filtered_resources:
            eval_result = evaluate_resource_for_task(resource, task, lang=lang)
            task_result["evaluations"].append(eval_result)

        # Sort by confidence
        task_result["evaluations"].sort(
            key=lambda x: x.get("confidence", 0), reverse=True
        )

        # Make recommendation
        top = task_result["evaluations"][0] if task_result["evaluations"] else None
        if top:
            if top["resource_type"] == "agent" and top.get("confidence", 0) >= 0.7:
                # WP-I18N-2 / D-D: the same bilingual constants the v2 policy
                # uses, so the two pipelines cannot drift. `lang` absent emits
                # the exact Chinese f-string this replaced.
                task_result["recommendation"] = {
                    "decision": "agent",
                    "resource": top,
                    "reason": format_recommendation_reason(
                        AGENT_RECOMMENDATION_REASON,
                        top["resource_name"], top["confidence"], lang,
                    ),
                    "cost_hint": DEMO_AGENTS.get(top["resource_id"], {}).get(
                        "cost_per_task", pick(UNKNOWN_COST_HINT, lang)
                    ),
                }
            elif top["resource_type"] == "human" and top.get("confidence", 0) >= 0.6:
                task_result["recommendation"] = {
                    "decision": "human",
                    "resource": top,
                    "reason": format_recommendation_reason(
                        HUMAN_RECOMMENDATION_REASON,
                        top["resource_name"], top["confidence"], lang,
                    ),
                    "cost_hint": pick(HUMAN_COST_HINT, lang),
                }
            else:
                # Check if any agent can do it at lower threshold
                agent_evals = [e for e in task_result["evaluations"] if e["resource_type"] == "agent"]
                human_evals = [e for e in task_result["evaluations"] if e["resource_type"] == "human"]

                if agent_evals and agent_evals[0].get("confidence", 0) >= 0.5:
                    task_result["recommendation"] = {
                        "decision": "hybrid",
                        "resource": top,
                        "reason": pick(HYBRID_REASON, lang),
                        "cost_hint": pick(HYBRID_COST_HINT, lang),
                    }
                else:
                    task_result["recommendation"] = {
                        "decision": "human",
                        "resource": top,
                        "reason": pick(HUMAN_FALLBACK_REASON, lang),
                        "cost_hint": pick(HUMAN_COST_HINT, lang),
                    }

        decisions.append(task_result)

    return {"decisions": decisions}
