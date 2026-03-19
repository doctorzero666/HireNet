# HireNet - System Architecture v2.0

> 对应 PRD v2.0 | 更新日期：2026-03-17

---

## 核心设计原则

```
Task-first，而不是 Job-first
人与 Agent 是同一网络里的连续体
"要不要招人"本身是一个可以被 Agent 优化的决策
```

---

## 1. 整体架构

```
┌─────────────────────────────────────────────┐
│                  用户层 User Layer           │
│         企业入口              求职者入口      │
└────────────┬────────────────────┬────────────┘
             │                    │
             ▼                    ▼
┌─────────────────────────────────────────────┐
│            编排层 Orchestration Layer        │
│              Career Orchestrator             │
└────────────┬────────────────────┬────────────┘
             │                    │
             ▼                    ▼
┌────────────────────┐  ┌─────────────────────┐
│  企业侧 Agent Hub  │  │  候选人侧 Agent Hub  │
│  Company Agent Hub │  │ Candidate Agent Hub  │
└────────────┬───────┘  └──────────┬──────────┘
             │                     │
             └──────────┬──────────┘
                        ▼
┌─────────────────────────────────────────────┐
│         A2A 网络 / 匹配层                    │
│   Second Me A2A Network + Match Engine       │
│                                             │
│  ┌──────────────┐    ┌────────────────────┐ │
│  │ 功能型 Agent │    │  候选人 Second Me  │ │
│  │ (自建演示用) │    │  (预设3个演示账号) │ │
│  └──────────────┘    └────────────────────┘ │
└─────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────┐
│                 数据层 Data Layer            │
└─────────────────────────────────────────────┘
```

---

## 2. 企业侧 Agent Hub（必做，核心差异化）

### 2.1 Requirement Analysis Agent

**职责：** 通过多轮对话澄清企业真实需求，消除 HR 与业务方之间的理解偏差。

**输入：**
- 企业原始需求描述（自然语言，可模糊）

**核心行为：**
- 识别需求中的模糊点
- 生成追问问题（最多 3-5 轮）
- 示例追问：
  - "这个工作是一次性的还是长期的？"
  - "你们团队现在有没有工程师？"
  - "这个功能需要上线维护，还是只是一个原型？"

**输出：**
- 结构化需求描述（JSON）
  ```json
  {
    "project_name": "...",
    "core_tasks": ["...", "..."],
    "duration": "one-time | ongoing",
    "team_context": "...",
    "urgency": "high | medium | low"
  }
  ```

---

### 2.2 Task Decomposition Agent

**职责：** 将结构化需求拆解为独立的可执行任务单元。

**输入：** Requirement Analysis Agent 的输出

**输出：**
```json
{
  "tasks": [
    { "id": "t1", "name": "文案撰写", "type": "creative", "estimated_hours": 4 },
    { "id": "t2", "name": "前端开发", "type": "technical", "estimated_hours": 20 },
    { "id": "t3", "name": "部署运维", "type": "technical", "estimated_hours": 8 }
  ]
}
```

**注意：** 拆解粒度以"可独立判断执行方式"为标准，不过度拆分。

---

### 2.3 Resource Decision Engine（核心模块）

**职责：** 对每个任务单元判断最优执行方式。

**判断逻辑：**

```
任务输入
    │
    ├─ 是否标准化、重复性？ → Agent 可完成
    ├─ 是否需要创造力/判断力？ → 需要人类
    └─ 两者兼有？ → 人机协同
```

**输出（每个任务）：**
```json
{
  "task_id": "t1",
  "decision": "agent | human | hybrid",
  "reason": "...",
  "confidence": 0.85,
  "if_agent": { "agent_type": "文案 Agent", "estimated_cost": "$0.02" },
  "if_human": { "role_hint": "内容运营", "estimated_cost": "$500/月" }
}
```

**Demo 展示重点：**
- 当 decision = "agent" 时，在 A2A 网络里搜索匹配的功能型 Agent
- 当 decision = "human" 时，触发 Job Design Agent
- 对比成本：Agent 执行 vs 招人的费用差

---

### 2.4 Job Design Agent（仅在需要招人时触发）

**职责：** 基于真实任务需求生成"去水"后的岗位定义。

**与传统 JD 的区别：**
- 输入是经过 Requirement Analysis 澄清后的真实需求，而非原始模糊描述
- 主动标注"可选要求"vs"核心要求"
- 给出合理经验年限区间（非夸大要求）

**输出：**
- 岗位名称
- 核心职责（3-5 条，精准）
- 必要技能 vs 加分项（明确区分）
- 建议经验年限（区间，非固定值）
- 薪资参考范围
- **JD 水分评分**（与原始描述对比，生成一致性分数）

---

## 3. 候选人侧 Agent Hub

### 3.1 Candidate Profile Agent

**职责：** 解析候选人简历，生成结构化能力画像。

**输入：**
- 简历文件（PDF/文本）
- 可选：GitHub 链接、自我描述

**输出（能力卡片，与功能型 Agent 格式统一）：**
```json
{
  "profile_id": "candidate_001",
  "type": "human",
  "name": "张三",
  "skills": ["Python", "数据分析", "SQL"],
  "skill_graph": { "Python": 0.9, "机器学习": 0.6 },
  "experience_years": 3,
  "availability": "full-time | part-time | freelance",
  "preferences": { "role_types": ["数据工程师"], "salary_range": "20k-30k" }
}
```

**关键设计：** 输出格式与 A2A 网络中功能型 Agent 的能力描述格式对齐，使两者可在同一 Match Engine 中被评分和比较。

**Demo 实现：** 使用 3 个预设候选人账号，已提前创建 Second Me 并训练完成，注册在 A2A 网络中。

---

### 3.2 Matching Engine（企业侧和候选人侧共用）

**职责：** 计算任务/岗位需求与网络中资源（Agent 或候选人）的匹配度。

**输入：**
- 企业侧：Task 或 Job Design 的结构化输出
- 候选人侧：求职者主动查询

**搜索范围（统一 A2A 网络）：**
```
A2A 网络
  ├── 功能型 Agent（自建 3-5 个 demo 用）
  │     ├── 代码生成 Agent
  │     ├── 文案撰写 Agent
  │     └── 数据分析 Agent
  └── 候选人 Second Me（预设 3 个）
        ├── 候选人A：全栈工程师
        ├── 候选人B：产品经理
        └── 候选人C：数据分析师
```

**输出：**
```json
{
  "matches": [
    { "id": "agent_code", "type": "agent", "score": 0.92, "reason": "..." },
    { "id": "candidate_001", "type": "human", "score": 0.78, "reason": "..." }
  ],
  "recommendation": "优先使用代码生成 Agent 完成原型，建议同步接触候选人A"
}
```

---

### 3.3 Application Agent（模拟投递）

**职责：** 在系统内部完成投递流程，不对接外部平台。

**流程：**
1. 候选人确认目标岗位（来自 Matching Engine 推荐）
2. 自动生成定制化投递材料（Cover Letter 摘要）
3. 在系统内记录投递状态

**不做的事：** 不自动化操作外部招聘平台，不做浏览器自动化。

---

### 3.4 Tracker Agent（状态展示）

**职责：** 展示投递进度，提供后续建议。

**输出：** 投递记录列表 + 状态标签（已投递 / 已查看 / 面试邀请）

**Demo 实现：** 静态数据展示即可，重点展示 UI。

---

## 4. A2A 网络层（Second Me Skills 对接）

### 4.1 功能型 Agent（自建，演示用）

黑客松内自建以下 3 个 Agent，注册进 Second Me A2A 网络：

| Agent 名称 | 能力描述 | 适用任务类型 |
|-----------|---------|------------|
| 代码生成 Agent | 生成前端/后端代码片段，自动化脚本 | technical |
| 文案撰写 Agent | 生成营销文案、产品描述、邮件 | creative |
| 数据分析 Agent | 数据清洗、报表生成、图表 | analytical |

### 4.2 候选人 Second Me（预设演示账号）

提前创建 3 个 Second Me 账号，训练完成后注册进网络：

| 账号 | 技能方向 | 用途 |
|------|---------|------|
| 候选人A | 全栈工程师（React + Node） | 技术类任务匹配演示 |
| 候选人B | 产品经理（AI 方向） | 策略类任务匹配演示 |
| 候选人C | 数据分析师（Python + SQL） | 数据类任务匹配演示 |

### 4.3 A2A 通信格式

企业侧 Resource Decision Engine 发起搜索：
```json
{
  "query": {
    "task_type": "technical",
    "skills_required": ["Python", "数据可视化"],
    "duration": "one-time",
    "budget_hint": "low"
  }
}
```

网络返回匹配列表（Agent 和候选人统一格式）。

---

## 5. 数据层（简化版）

| 存储类型 | 用途 | 实现方式 |
|---------|------|---------|
| 结构化数据 | 候选人 Profile、任务记录、投递状态 | SQLite 或 JSON 文件（demo 用） |
| 向量数据库 | 技能语义匹配 | 轻量向量库（如 ChromaDB） |
| 会话缓存 | Agent 多轮对话状态 | 内存 / Redis |

---

## 6. 砍掉的模块（对比旧架构）

以下模块在 v2.0 中**明确移除**，开发时不要投入时间：

| 模块 | 移除原因 |
|------|---------|
| Browser Agent | 浏览器自动化复杂度高，与核心叙事无关 |
| Platform Adapters | 依赖外部平台 API，黑客松内无法稳定实现 |
| Human Takeover Manager | 依赖 Browser Agent，连带移除 |
| Job Discovery Agent | 与 Task-first 逻辑方向相反，造成叙事混乱 |
| Company Profile Agent | 可并入 Requirement Analysis，不需独立 Agent |
| Market Intelligence Agent | 数据获取复杂，非核心功能 |
| Salary & Level Reasoner | 并入 Job Design Agent 输出即可 |

---

## 7. Demo 场景设计（开发时对照）

### 场景 A：企业发现不需要招人

```
输入："我们需要给官网写 5 篇 SEO 文章"
→ Requirement Analysis：确认是一次性任务，500字/篇
→ Task Decomposition：1个任务单元（文案创作）
→ Resource Decision：Agent 可完成（置信度 91%）
→ A2A 网络搜索：匹配到"文案撰写 Agent"
→ 输出：预计成本 $0.10，无需招人
```

### 场景 B：企业确认需要招人

```
输入："我们要做一个 AI 数据看板，需要长期维护"
→ Requirement Analysis：确认需要长期合作，涉及复杂判断
→ Task Decomposition：3个任务单元
→ Resource Decision：需要人类（数据工程师）
→ Job Design Agent：生成去水 JD（JD 一致性评分：78分）
→ Matching Engine：匹配到候选人C（数据分析师，匹配度 84%）
→ 输出：推荐人选 + 面试建议
```

### 场景 C：混合方案

```
输入："搭建一个电商网站，需要 UI 设计 + 前端开发 + 文案"
→ Task Decomposition：3个独立任务
→ Resource Decision：
    UI设计 → 需要人（创造力）→ 匹配候选人B
    前端开发 → Agent 可完成（标准模板）→ 匹配代码生成 Agent
    文案 → Agent 可完成 → 匹配文案撰写 Agent
→ 输出：混合方案，成本对比展示
```

---

## 8. 开发分工建议

| 模块 | 优先级 | 建议负责人方向 |
|------|-------|-------------|
| Requirement Analysis Agent | P0 | 后端 / Prompt 工程 |
| Task Decomposition Agent | P0 | 后端 / Prompt 工程 |
| Resource Decision Engine | P0 | 后端逻辑 |
| A2A 网络对接 + 自建 Agent 注册 | P0 | 后端 / Second Me Skills |
| 3个候选人 Second Me 预设账号 | P0 | 需要今晚就开始训练 |
| Matching Engine | P1 | 后端 |
| Candidate Profile Agent | P1 | 后端 / Prompt 工程 |
| 前端 UI（企业侧流程） | P1 | 前端 |
| Application Agent + Tracker | P2 | 前端为主 |

---

## 9. 关键风险与应对

| 风险 | 概率 | 应对方案 |
|------|------|---------|
| Second Me A2A 接口不稳定 | 中 | 本地 mock A2A 响应作为备用 |
| 候选人 Second Me 训练时间不够 | 高 | **今晚立刻开始**，需要12-24小时训练时间 |
| Resource Decision 准确率低 | 低 | 固定 3 个 demo 场景，剧本化保证演示效果 |
| 多 Agent 编排复杂度超预期 | 中 | 降级为顺序调用，不做并行编排 |
