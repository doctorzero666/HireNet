# HireNet 前端页面需求文档（Agent Network 版）

## 1. 文档目标

本文档用于定义 HireNet 的前端页面结构、页面功能模块、用户交互方式，以及每个功能模块所对应的 Agent。

HireNet 不是传统招聘网站，也不是单一求职工具，而是一个 **Human-Agent Labor Network**。因此，前端页面设计的核心目标不是“展示岗位”，而是：

- 让用户清楚理解系统在做什么
- 让用户看见 Agent 的分工与协作
- 降低求职过程中的压迫感和焦虑感
- 用游戏化、像素风、低压力的方式呈现复杂流程
- 将“找工作”与“招聘”转化为“任务理解—资源决策—协同完成”

---

## 2. 设计原则

### 2.1 产品体验原则

1. **任务优先，而不是岗位优先**
   - 页面不应强调“筛选岗位”
   - 页面应强调“今天想完成什么”或“想参与什么任务”

2. **低压力体验**
   - 避免传统招聘平台那种高压、密集信息流、红点催促式设计
   - 使用轻松、温暖、治愈的视觉和文案

3. **Agent 可视化**
   - 用户应明确知道当前是哪个 Agent 在工作
   - 每个模块背后对应哪个 Agent，需要在界面逻辑中清楚映射

4. **分角色体验**
   - 求职者和雇主进入的是同一个系统，但目标不同
   - 求职者侧强调成长、参与、协作
   - 雇主侧强调分析、决策、执行

5. **游戏化但不幼稚**
   - 风格参考：星露谷物语 / 动森的温暖感
   - 结构仍然要保持现代 SaaS dashboard 的清晰度

---

## 3. 用户角色与页面总览

系统入口先做身份分流。

### 3.1 角色

- 求职者（Job Seeker）
- 雇主 / 企业方（Employer）

### 3.2 页面总览

建议前端页面分为 4 个核心页面：

1. **角色选择页（Role Selection Page）**
2. **雇主端主控制台（Employer Task Console）**
3. **求职者端主页面（Job Seeker Journey Page）**
4. **Agent 世界 / Agent 网络页（Agent World Page，可选增强页）**

其中：

- 黑客松 MVP 必做：页面 1、2、3
- 页面 4 在黑客松阶段作为系统展示与项目叙事入口，长期可演化为 Agent Marketplace / Agent Upload Portal

---

## 4. 页面一：角色选择页（Role Selection Page）

### 4.1 页面定位

系统首页，用于让用户先选择自己的身份。

### 4.2 页面目标

- 完成身份分流（Role Routing）
- 降低系统复杂度
- 让用户立即进入与自己目标对应的体验路径
- 提供 Agent 世界页的入口，用于展示 Agent 网络与未来扩展能力

### 4.3 页面功能框

#### 模块 A：品牌区

**功能**
- 展示产品名称：HireNet
- 展示副标题：AI Labor Network
- 展示一句产品定位文案

**建议文案**
- “让工作自然发生的系统”
- “由 Agent 与 Human 协同完成任务”

**对应 Agent**
- 无直接 Agent
- 属于品牌展示层

---

#### 模块 B：角色选择卡片区

**功能**
- 展示两个身份入口：
  - 👤 求职者
  - 🏢 雇主
- 每个卡片说明对应角色的目标

**求职者卡片建议文案**
- 探索机会
- 参与任务
- 建立成长路径

**雇主卡片建议文案**
- 描述需求
- 让系统判断 Agent 还是 Human 更适合
- 找到合适资源

**对应 Agent**
- 无执行型 Agent
- 但会决定进入哪个 Agent 路径

**路由关系**
- 求职者 → Job Seeker Journey Page
- 雇主 → Employer Task Console

---

#### 模块 C：进入系统按钮

**功能**
- 在选择角色后进入对应页面

**对应 Agent**
- `Career Orchestrator`

**原因**
- 由 Orchestrator 接管用户的初始意图，决定后续工作流进入求职者流还是企业流

---

#### 模块 D：Agent 世界入口区

**功能**
- 提供进入 Agent 世界页（Agent World Page）的入口
- 在黑客松阶段用于向评委和用户展示系统中的 Agent 网络与协作关系
- 在长期版本中可扩展为 Agent 上传入口 / Agent 市场入口

**建议文案**
- “看看谁正在让这个世界运转”
- “进入 Agent 世界”
- “上传你的 Agent（未来功能）”

**对应 Agent**
- 当前阶段无单一执行型 Agent
- 由 `Career Orchestrator` 负责页面跳转与整体导航编排

**长期演化方向**
- 展示系统内置 Agent
- 展示第三方上传 Agent
- 作为企业调用专业 Agent 的发现入口

---

## 5. 页面二：雇主端主控制台（Employer Task Console）

### 5.1 页面定位

这是雇主端的核心页面，也是整个系统最重要的 Demo 页面。

### 5.2 页面目标

- 让企业输入“想做什么事情”
- 让系统分析任务
- 拆解任务
- 判断应该由 Agent、Human，还是协同完成
- 给出成本与执行建议

### 5.3 页面布局建议

三栏布局：

- 左栏：任务输入区
- 中栏：AI 分析过程区（核心）
- 右栏：执行结果区

---

### 5.4 功能框与 Agent 映射

#### 模块 A：任务输入区（Left Panel - Task Input）

**功能**
- 文本框：用户输入需求
- 快捷任务按钮：如“搭建 AI 官网”“分析销售数据”“创建客服系统”
- 开始分析按钮

**交互**
- 用户输入自然语言任务
- 点击“开始分析”后进入中栏逐步推理流程

**对应 Agent**
- `Career Orchestrator`
- `Requirement Analysis Agent`

**分工**
- Career Orchestrator：接收请求并发起工作流
- Requirement Analysis Agent：理解用户的真实需求

---

#### 模块 B：需求理解卡片（Center Step 1 - Task Understanding）

**功能**
- 展示系统对用户需求的理解结果
- 用简短自然语言总结“你想完成什么”

**示例内容**
- 你希望完成：一个 AI 产品官网
- 目标：展示产品、吸引注册、快速上线

**对应 Agent**
- `Requirement Analysis Agent`

**原因**
- 该模块本质上是对企业需求进行语义理解与抽象

---

#### 模块 C：任务拆解卡片（Center Step 2 - Task Decomposition）

**功能**
- 将需求拆成多个子任务
- 以 checklist / 卡片列表形式展示

**示例内容**
- 文案生成
- UI 设计
- 前端开发
- 部署上线

**对应 Agent**
- `Task Decomposition Agent`

**原因**
- 该模块专门负责把模糊需求转化为可执行任务单元

---

#### 模块 D：资源决策卡片（Center Step 3 - Resource Decision）

**功能**
- 对每个子任务判断由谁来做
- 状态类型：
  - Agent
  - Human + Agent
  - Human Required
- 使用清晰的颜色标签区分

**示例内容**
- 文案生成 → Agent
- UI 设计 → Human + Agent
- 前端开发 → Human Required
- 部署上线 → Agent

**对应 Agent**
- `Resource Decision Engine`

**原因**
- 这是整个产品最核心的差异化模块
- 它决定了 HireNet 不是招聘网站，而是劳动力调度系统

---

#### 模块 E：成本分析卡片（Center Step 4 - Cost Comparison）

**功能**
- 对比不同方案成本
- 显示推荐方案

**建议方案**
- 全招聘
- 人机协同（推荐）
- 全 Agent

**对应 Agent**
- `Resource Decision Engine`
- `Matching Engine`（可辅助）

**原因**
- 资源决策不仅是技术判断，也需要输出资源配置建议

---

#### 模块 F：Agent 执行结果区（Right Section A - Agent Execution）

**功能**
- 展示哪些任务已由 Agent 完成
- 显示任务状态、结果入口

**示例内容**
- 文案已生成
- UI 草稿已生成
- 部署流程已完成

**操作按钮**
- 查看结果
- 重新生成

**对应 Agent**
- `A2A Agent Invocation`
- `Task Runner`
- 具体功能型 Agent（如 Coding Agent、Content Agent、Analysis Agent）

**分工**
- A2A Agent Invocation：调用其他 Agent
- Task Runner：执行任务序列
- 功能型 Agent：真正产出结果

---

#### 模块 G：候选人推荐区（Right Section B - Human Candidate Recommendations）

**功能**
- 展示推荐的候选人卡片
- 每个卡片包含：
  - 姓名
  - 角色
  - 技能标签
  - 匹配度
  - 推荐理由
  - 操作按钮（联系 / 面试）

**对应 Agent**
- `Matching Engine`
- `Recruit Assist Agent`
- `Candidate Profile Agent`（提供画像数据）

**分工**
- Matching Engine：计算匹配度
- Recruit Assist Agent：生成推荐与沟通建议
- Candidate Profile Agent：提供候选人画像

---

#### 模块 H：人工接管提示区（Optional System Notice）

**功能**
- 当系统需要用户确认、审批、接管时给出提示

**对应 Agent / 系统模块**
- `Human-in-the-loop Manager`

---

## 6. 页面三：求职者端主页面（Job Seeker Journey Page）

### 6.1 页面定位

求职者端的核心页面。

### 6.2 页面目标

- 降低找工作焦虑
- 不强调“投递数”和“筛选压力”
- 强调“成长路径”“参与任务”“被匹配的机会”

### 6.3 页面结构建议

建议做成两段式布局：

- 上半区：探索 / 推荐任务
- 下半区：成长路径 / 历史进度

---

### 6.4 功能框与 Agent 映射

#### 模块 A：欢迎与状态区

**功能**
- 展示欢迎文案
- 展示当前成长状态
- 提供温和、低压力的情绪氛围

**建议文案**
- 欢迎回来，今天想参与什么？
- 你最近正在成长为：AI 产品协作者

**对应 Agent**
- `Career Strategy Agent`
- `Tracker Agent`

**原因**
- Career Strategy Agent 决定职业方向
- Tracker Agent 提供最近进度信息

---

#### 模块 B：机会推荐区

**功能**
- 推荐适合用户参与的任务或岗位
- 每张卡片展示：
  - 任务 / 岗位名称
  - 所需技能
  - 推荐理由
  - 匹配度
  - 操作按钮（查看 / 参与 / 投递）

**对应 Agent**
- `Job Discovery Agent`
- `Matching Engine`
- `Career Strategy Agent`

**分工**
- Job Discovery Agent：发现机会
- Matching Engine：算匹配
- Career Strategy Agent：决定推荐优先级

---

#### 模块 C：我的成长路径（My Journey）

**功能**
- 展示用户的任务参与记录、投递记录、成长轨迹
- 用时间轴 / 成就卡 / 技能树形式呈现

**可展示内容**
- 已参与任务
- 已投递岗位
- 新解锁技能
- 推荐下一步方向

**对应 Agent**
- `Tracker Agent`
- `Candidate Profile Agent`
- `Career Strategy Agent`

**分工**
- Tracker Agent：记录历史行为
- Candidate Profile Agent：维护画像
- Career Strategy Agent：给成长建议

---

#### 模块 D：个人画像摘要区

**功能**
- 展示用户当前技能标签、目标方向、画像摘要

**对应 Agent**
- `Candidate Profile Agent`

**原因**
- 这个模块本质上是用户数字画像的可视化

---

#### 模块 E：一键投递 / 一键参与按钮

**功能**
- 针对推荐任务/岗位触发后续动作

**对应 Agent**
- `Application Agent`
- `Career Orchestrator`

**分工**
- Application Agent：执行求职动作
- Career Orchestrator：编排后续流程

---

## 7. 页面四：Agent 世界页（Agent World Page）

### 7.1 页面定位

系统的展示与扩展页，用来展示这是一个 Agent Network，而不是单个 AI。在黑客松阶段，它主要承担项目叙事与 Agent 协作可视化的作用；在长期版本中，它可以演化为 Agent Marketplace / Agent Upload Portal。

### 7.2 页面目标

- 可视化各个 Agent
- 让用户和评委理解“每个 Agent 各司其职”
- 强化产品叙事
- 在黑客松阶段作为 Agent 协作网展示页
- 在长期阶段作为第三方 Agent 接入与上传入口

### 7.3 功能框与 Agent 映射

#### 模块 A：Agent 地图 / Agent 卡片墙

**功能**
- 展示系统内各个 Agent 角色
- 每个 Agent 一张卡

**展示信息**
- Agent 名称
- 职责
- 当前状态
- 可处理的任务类型

**建议展示的 Agent**
- Requirement Analysis Agent
- Task Decomposition Agent
- Resource Decision Engine
- Matching Engine
- Candidate Profile Agent
- Job Discovery Agent
- Application Agent
- Tracker Agent
- Recruit Assist Agent

---

#### 模块 B：Agent 协作链路图

**功能**
- 用流程图形式展示 Agent 之间如何协作

**示例链路**
- 雇主输入需求 → Requirement Analysis → Task Decomposition → Resource Decision → Agent Execution / Candidate Matching

**对应 Agent**
- 所有核心 Agent

---

#### 模块 C：当前活跃 Agent 状态

**功能**
- 显示当前哪些 Agent 正在工作
- 提供一种“世界正在运转”的感觉

**对应 Agent**
- `Career Orchestrator`
- `Task Runner`
- 所有被调用中的功能型 Agent

---

#### 模块 D：第三方 Agent 上传入口（Future Module）

**功能**
- 提供未来第三方 Agent 的上传与注册入口
- 允许用户或开发者将自己的专业 Agent 接入系统
- 使这些 Agent 成为未来可被企业调用的执行资源

**展示信息（未来）**
- Agent 名称
- Agent 类型（如设计、数据、前端、运营、文案）
- Agent 能力说明
- Agent 状态（审核中 / 可用 / 已接入）
- 上传按钮 / 注册按钮

**对应 Agent / 系统模块**
- `Career Orchestrator`
- `A2A Agent Invocation`
- `Agent Resource Hub`
- （未来）Agent Registry / Agent Onboarding Service

**原因**
- 该模块承接了系统从“内置 Agent 网络”向“开放 Agent 劳动力市场”扩展的可能性
- 对黑客松阶段来说，这个模块可以先以概念入口或灰态按钮形式存在，用于展示长期愿景

---

## 8. 页面导航与交互流

### 8.1 总体交互流

```text
角色选择页
→ 求职者流 / 雇主流 / Agent 世界页
→ 对应核心页面
→ 由 Career Orchestrator 调度 Agent
→ 用户查看结果 / 继续交互
```

### 8.2 雇主端交互流

```text
选择“雇主”
→ 进入 Employer Task Console
→ 输入需求
→ 系统逐步分析
→ 资源决策
→ Agent 执行 / 推荐候选人
→ 用户查看结果或发起下一步动作
```

### 8.3 求职者端交互流

```text
选择“求职者”
→ 进入 Job Seeker Journey Page
→ 查看推荐机会
→ 查看成长路径
→ 发起参与 / 投递
→ 系统记录到 Journey 中
```

---

## 9. Agent 与页面模块映射总表

| 页面 | 功能模块 | 对应 Agent |
|---|---|---|
| 角色选择页 | 进入系统按钮 | Career Orchestrator |
| 角色选择页 | Agent 世界入口区 | Career Orchestrator |
| 雇主端主控制台 | 任务输入区 | Career Orchestrator / Requirement Analysis Agent |
| 雇主端主控制台 | 需求理解 | Requirement Analysis Agent |
| 雇主端主控制台 | 任务拆解 | Task Decomposition Agent |
| 雇主端主控制台 | 资源决策 | Resource Decision Engine |
| 雇主端主控制台 | 成本分析 | Resource Decision Engine / Matching Engine |
| 雇主端主控制台 | Agent 执行结果 | A2A Agent Invocation / Task Runner / 功能型 Agent |
| 雇主端主控制台 | 候选人推荐 | Matching Engine / Recruit Assist Agent / Candidate Profile Agent |
| 雇主端主控制台 | 人工接管提示 | Human-in-the-loop Manager |
| 求职者端主页面 | 欢迎与状态 | Career Strategy Agent / Tracker Agent |
| 求职者端主页面 | 机会推荐 | Job Discovery Agent / Matching Engine / Career Strategy Agent |
| 求职者端主页面 | My Journey | Tracker Agent / Candidate Profile Agent / Career Strategy Agent |
| 求职者端主页面 | 个人画像摘要 | Candidate Profile Agent |
| 求职者端主页面 | 一键投递 / 参与 | Application Agent / Career Orchestrator |
| Agent 世界页 | Agent 卡片墙 | 全部核心 Agent |
| Agent 世界页 | 协作链路图 | 全部核心 Agent |
| Agent 世界页 | 活跃状态区 | Career Orchestrator / Task Runner / 活跃 Agent |
| Agent 世界页 | 第三方 Agent 上传入口（未来） | Career Orchestrator / A2A Agent Invocation / Agent Resource Hub / Agent Registry（未来） |

---

## 10. 黑客松 MVP 页面优先级

### P0（必须做）

1. 角色选择页
2. 雇主端主控制台
3. 求职者端主页面
4. Agent 世界页（展示版）

### P1（加分项）

1. Agent 世界页中的协作链路动画
2. Agent 世界页中的第三方 Agent 上传入口（灰态/概念版）

---

## 11. 视觉与文案建议

### 11.1 视觉风格

- 像素风灵感：星露谷物语
- 但布局保留现代 SaaS dashboard 的清晰结构
- 关键词：温暖、治愈、放松、可信、可读

### 11.2 文案风格

避免高压表达：

- 不说“筛选你”
- 不说“你是否符合”
- 不说“失败 / 拒绝”

改为：

- 适合你的方向
- 推荐你参与的任务
- 下一步成长建议
- 系统为你找到更自然的选择

---

## 12. 总结

HireNet 的前端页面不是简单展示功能，而是要把复杂的 Agent Network 转化为用户能理解、愿意使用、不会感到压迫的体验系统。

页面设计的核心不是“信息密度”，而是：

 - 角色分流清晰
 - Agent 分工明确
 - 过程可视化
 - 决策可理解
 - 体验低压力
 - 系统具备从内置 Agent 网络向开放 Agent 劳动力市场演化的入口

最终，用户应该感受到的不是“我在被招聘系统审视”，而是：

> 我正在和一个会理解我、帮助我、替我协调资源的系统一起完成任务。


从黑客松阶段开始，Agent 世界页就不只是一个加分展示页，而是整个系统世界观的入口：它既解释了当前 Agent 如何协作，也预留了未来第三方 Agent 接入、上传和被企业调用的产品扩展路径。

