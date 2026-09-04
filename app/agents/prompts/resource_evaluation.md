评估资源是否能完成任务。

资源信息：
- 名称：${resource_name}
- 类型：${resource_kind}
- 能力：${capability_desc}

任务信息：
- 名称：${task_name}
- 描述：${task_description}
- 类型：${task_type}
- 需要判断力：${requires_judgment}

请输出 JSON，格式完全遵循以下结构：
{
  "can_complete": true或false,
  "confidence": 0到1之间的数字,
  "reason": "一句话原因（中文）",
  "estimated_time": "时间估算",
  "strengths": ["优势1", "优势2"]
}
