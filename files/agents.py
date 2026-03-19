"""
HireNet Core Agents
- Requirement Analysis Agent  (multi-turn clarification via LLM)
- Task Decomposition Agent    (break requirement into tasks)
- Resource Decision Engine    (agent vs human decision via Second Me /act)
"""
import os
import json
from openai import OpenAI
from secondme_client import SecondMeClient
from candidate_profile import DEMO_CANDIDATES, DEMO_AGENTS, get_all_resources


# ─── LLM Client (Kimi or OpenAI-compatible) ───────────────────────────────────

def get_llm_client() -> OpenAI:
    """Returns OpenAI-compatible client (Kimi by default)"""
    api_key = os.getenv("KIMI_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1")
    return OpenAI(api_key=api_key, base_url=base_url)


def get_model() -> str:
    return os.getenv("KIMI_MODEL", "moonshot-v1-8k")


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
    def __init__(self):
        self.client = get_llm_client()
        self.history = []

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
        resp = self.client.chat.completions.create(
            model=get_model(),
            messages=self.history,
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


def decompose_tasks(requirement: dict) -> dict:
    """Break requirement into task units"""
    client = get_llm_client()

    prompt = f"""请将以下项目需求拆解为任务单元：

项目名称：{requirement.get('project_name', '未知')}
需求描述：{requirement.get('core_description', '')}
任务提示：{', '.join(requirement.get('tasks_hint', []))}
持续时间：{requirement.get('duration', 'unknown')}
团队背景：{requirement.get('team_context', '未知')}"""

    resp = client.chat.completions.create(
        model=get_model(),
        messages=[
            {"role": "system", "content": DECOMPOSITION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    raw = resp.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


# ─── Resource Decision Engine ─────────────────────────────────────────────────

RESOURCE_DECISION_ACTION_CONTROL = """Output only a valid JSON object, no explanation, no markdown.
Structure:
{
  "can_complete": boolean,
  "confidence": number between 0 and 1,
  "reason": "one sentence explanation in Chinese",
  "estimated_time": "time estimate string",
  "strengths": ["strength1", "strength2"]
}

Rules:
- Set can_complete=true if this resource's capabilities clearly match the task requirements
- Set confidence based on how well the match is (0.9+ = excellent, 0.7-0.9 = good, 0.5-0.7 = possible, <0.5 = unlikely)
- If insufficient information to judge, set can_complete=false with confidence=0.3
- strengths should list 1-3 specific relevant capabilities"""


def evaluate_resource_for_task(resource: dict, task: dict) -> dict:
    """
    Use Second Me /act API to evaluate if a resource (agent or candidate)
    can complete a given task.

    This is the core A2A interaction: we're asking each Second Me
    "can you complete this task?" and getting a structured response.
    """
    # Get the token for this resource
    token = None
    if resource["type"] == "human":
        candidate = DEMO_CANDIDATES.get(resource["id"])
        if candidate:
            token = candidate.get("token")
    else:
        agent = DEMO_AGENTS.get(resource["id"])
        if agent:
            token = agent.get("token")

    if not token:
        # Fallback: use LLM-based evaluation
        return _llm_evaluate_resource(resource, task)

    # Use Second Me /act for structured judgment
    try:
        client = SecondMeClient(token)
        message = f"""任务需求：{task['name']}
任务描述：{task['description']}
任务类型：{task['type']}
预计工时：{task['estimated_hours']}小时
是否需要判断力：{'是' if task.get('requires_judgment') else '否'}
是否长期重复：{'是' if task.get('is_recurring') else '否'}

请评估你是否能完成此任务。"""

        result = client.act_stream(
            message=message,
            action_control=RESOURCE_DECISION_ACTION_CONTROL,
            system_prompt=f"你是{resource['name']}，请根据你的能力评估是否能完成以下任务。",
        )
        result["resource_id"] = resource["id"]
        result["resource_name"] = resource["name"]
        result["resource_type"] = resource["type"]
        return result

    except Exception as e:
        print(f"Act API failed for {resource['id']}, falling back to LLM: {e}")
        return _llm_evaluate_resource(resource, task)


def _llm_evaluate_resource(resource: dict, task: dict) -> dict:
    """Fallback: use local LLM to evaluate resource-task fit"""
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

    resp = client.chat.completions.create(
        model=get_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    raw = resp.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    # Extract the first JSON object in case the LLM returns extra content
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Find the first complete JSON object
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


def run_resource_decision(tasks: list[dict]) -> dict:
    """
    For each task, evaluate all resources and make final decision.
    Returns decision result for each task.
    """
    resources = get_all_resources()
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
            eval_result = evaluate_resource_for_task(resource, task)
            task_result["evaluations"].append(eval_result)

        # Sort by confidence
        task_result["evaluations"].sort(
            key=lambda x: x.get("confidence", 0), reverse=True
        )

        # Make recommendation
        top = task_result["evaluations"][0] if task_result["evaluations"] else None
        if top:
            if top["resource_type"] == "agent" and top.get("confidence", 0) >= 0.7:
                task_result["recommendation"] = {
                    "decision": "agent",
                    "resource": top,
                    "reason": f"推荐使用 {top['resource_name']}，置信度 {top['confidence']:.0%}",
                    "cost_hint": DEMO_AGENTS.get(top["resource_id"], {}).get("cost_per_task", "未知"),
                }
            elif top["resource_type"] == "human" and top.get("confidence", 0) >= 0.6:
                task_result["recommendation"] = {
                    "decision": "human",
                    "resource": top,
                    "reason": f"建议招聘 {top['resource_name']} 类型人才，置信度 {top['confidence']:.0%}",
                    "cost_hint": "需要评估薪资",
                }
            else:
                # Check if any agent can do it at lower threshold
                agent_evals = [e for e in task_result["evaluations"] if e["resource_type"] == "agent"]
                human_evals = [e for e in task_result["evaluations"] if e["resource_type"] == "human"]

                if agent_evals and agent_evals[0].get("confidence", 0) >= 0.5:
                    task_result["recommendation"] = {
                        "decision": "hybrid",
                        "resource": top,
                        "reason": "建议人机协同：Agent 完成基础部分，人工处理复杂判断",
                        "cost_hint": "混合成本",
                    }
                else:
                    task_result["recommendation"] = {
                        "decision": "human",
                        "resource": top,
                        "reason": "此任务需要人类处理，建议招聘",
                        "cost_hint": "需要评估薪资",
                    }

        decisions.append(task_result)

    return {"decisions": decisions}
