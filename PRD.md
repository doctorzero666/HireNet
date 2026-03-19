# HireNet - AI Labor Network PRD (v2.0)

## 1. Product Overview

HireNet 是一个基于 Agent Network 的智能劳动力调度系统，旨在重构“工作如何被完成”。

与传统招聘平台不同，HireNet 不再默认通过“招聘人”来解决问题，而是通过 AI Agent 和人类劳动力的协同，动态决定任务的最优执行方式。

系统核心能力包括：

- 任务理解与拆解（Task Understanding & Decomposition）
- 人机协同决策（Agent vs Human Decision）
- Agent 自动执行（A2A Execution）
- 人才匹配与招聘（Human Matching & Hiring）
- 求职者智能辅助（AI Career Assistant）

目标是构建一个：

> **以任务为中心的人机协同劳动力网络（Human-Agent Labor Network）**

---

## 2. Problem Statement

### 2.1 企业侧问题

当前企业在招聘过程中存在严重问题：

- 不清楚是否真的需要招人
- 无法准确表达岗位需求
- HR 与项目团队存在理解偏差
- 招聘成本高，效率低

同时，大量简单工作其实可以通过自动化完成，但企业缺乏判断能力。

---

### 2.2 求职者侧问题

求职者面临：

- 对自身能力认知不足
- 无法获取全面岗位信息
- 投递流程繁琐重复
- 简历投递效率低、反馈少

---

### 2.3 市场级问题

本质问题是：

> 劳动力市场的信息流动方式是错误的

- 工作被强行抽象为“岗位”
- 人才通过“关键词匹配”
- 招聘成为默认解决方案

导致：

- 人才错配
- 内卷严重
- 企业成本浪费

---

## 3. Product Vision

构建一个：

> **由 Agent 与 Human 共同组成的劳动力网络**

核心思想：

```text
任务优先（Task-first）
而不是岗位优先（Job-first）
```

系统会：

- 先理解“要做什么事情”
- 再判断“谁来做最合适”
- 决定：
  - Agent执行
  - Human执行
  - 或协同完成

---

## 4. Target Users

### Phase 1

- 求职者（核心用户）
- 技术人才 / AI从业者
- 留学生 / 转行人群

---

### Phase 2

- 中小企业
- 创业团队
- 产品团队
- HR团队

---

## 5. Core Product Features

---

## 5.1 企业侧能力（Task-first）

### 1. Requirement Analysis Agent

- 分析企业真实需求
- 判断是否需要招聘

---

### 2. Task Decomposition Agent

- 将需求拆解为任务单元

例如：

```text
搭建官网
→ 文案
→ UI设计
→ 前端开发
→ 部署
```

---

### 3. Resource Decision Engine

核心模块：

```text
任务 → Agent or Human？
```

输出：

- Agent可完成
- 需要人类
- 人机协同

---

### 4. Agent Execution（A2A）

- 调用其他 Agent 完成任务
- 实现自动化执行

---

### 5. Job Design Agent

当需要人类时：

- 自动生成岗位定义
- 明确职责与能力要求
- 提供合理薪资建议

---

## 5.2 求职者侧能力（Career Assistant）

### 1. Candidate Profile Agent

- 构建结构化用户画像

---

### 2. Career Strategy Agent

- 制定求职策略
- 推荐岗位方向

---

### 3. Job Discovery Agent

- 自动搜索岗位
- 构建岗位池

---

### 4. Matching Engine

- 计算岗位匹配度
- 输出匹配解释

---

### 5. Application Agent

- 自动生成投递内容
- 半自动/自动投递简历

---

### 6. Tracker Agent

- 跟踪投递进度
- 提供后续建议

---

## 6. Core Workflow

### 企业侧主流程

```text
输入：企业需求
↓
Requirement Analysis
↓
Task Decomposition
↓
Resource Decision Engine
    ├─ Agent执行（A2A）
    └─ Human招聘流程
            ↓
        Job Design
            ↓
        Talent Matching
            ↓
        招聘执行
```

---

### 求职者侧流程

```text
上传简历
↓
生成画像
↓
岗位推荐
↓
用户确认
↓
自动投递
↓
跟踪进度
```

---

## 7. MVP Scope

### 必做（黑客松）

- Candidate Profile Agent
- Job Discovery Agent
- Matching Engine
- Application Agent（半自动）
- Tracker Agent

---

### 展示型（企业侧）

- Requirement Analysis（简化版）
- Task Decision Demo

---

## 8. Key Metrics

- 每用户投递数量
- 投递转化率（面试率）
- 匹配准确度
- Agent替代率（自动完成任务比例）
- 企业招聘成本下降

---

## 9. Future Expansion

- Agent Marketplace（Agent劳动力市场）
- Human-Agent协同平台
- 自动项目交付系统
- AI招聘操作系统（Recruit OS）

---

## 10. Long-term Vision

> HireNet 不只是招聘工具，而是一个决定“工作如何被完成”的系统。

未来：

- Agent承担标准化工作
- Human专注复杂创造
- HireNet负责调度与匹配