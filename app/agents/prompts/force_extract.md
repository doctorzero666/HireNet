根据我们刚才的对话，现在请直接输出结构化需求 JSON。
不要再提问，不要有任何其他文字，只输出以下 JSON：
{
  "project_name": "项目名称",
  "core_description": "核心需求描述",
  "tasks_hint": ["可能的任务1", "可能的任务2"],
  "duration": "one-time | ongoing | unknown",
  "team_context": "团队背景描述",
  "urgency": "high | medium | low",
  "budget_hint": "low | medium | high | unknown"
}

规则：
1. 对话里没说清楚的字段，用对话中已有的信息作最合理的推断，不要留空
2. 工期无法判断时写 unknown，预算无法判断时写 unknown，不要写自由文本（例如"3个月"、"面议"）
3. duration 只能是 one-time / ongoing / unknown 三者之一，urgency 只能是 high / medium / low，budget_hint 只能是 low / medium / high / unknown
