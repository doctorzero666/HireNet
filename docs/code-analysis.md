# HireNet 代码分析：MVP 改造范围

> 日期：2026-06-08 | 原则：最小改动，最大复用

## 一、不动（Keep As-Is）

### 核心 Agent 逻辑 — 完全保留

| 文件 | 理由 |
|------|------|
| `app/agents/agents.py` | RequirementAnalysis、TaskDecomposition、ResourceDecision、CareerStrategy — 核心业务逻辑正确 |
| `app/agents/job_design.py` | JD 生成逻辑正确 |
| `app/agents/candidate_profile.py` | 候选人画像，MVP 不展示但保留 |
| `app/agents/application_agent.py` | 投递逻辑，MVP 不展示但保留 |

### Schema — 完全保留

| 目录 | 理由 |
|------|------|
| `app/schemas/` 全部 | Schema 定义是数据模型的权威来源 |

### 存储层 — 完全保留

| 目录 | 理由 |
|------|------|
| `app/storage/` 全部 | DB 访问层，设计决策正确 |

### 业务服务层 — 完全保留

| 目录 | 理由 |
|------|------|
| `app/services/` 全部 | Skill 注册、版税记账、校验、Agent Run 记录 |

### 路由（部分） — 保留

| 文件 | 理由 |
|------|------|
| `app/routes/skills.py` | Skill Asset 注册 API |
| `app/routes/earnings.py` | 创作者收益 API |

### 测试 — 完全保留

| 目录 | 理由 |
|------|------|
| `tests/` 全部 | 测试是 Phase 1 的工程资产 |

### 架构文档

| 文件 | 理由 |
|------|------|
| `ARCHITECTURE.md` | 系统架构参考 |
| `CLAUDE.md` | 项目宪法，TIER 1/2 规则 |

---

## 二、改（Modify）

### LLM 客户端 — 模型切换

**文件**：`app/agents/agents.py`

**改动**：`get_llm_client()` 函数

```python
# 现在（Kimi）
api_key = os.getenv("KIMI_API_KEY")
base_url = os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1")

# 改为（智谱 GLM-4）
api_key = os.getenv("ZHIPU_API_KEY")
base_url = "https://open.bigmodel.cn/api/paas/v4"
model = "glm-4-flash"  # 或 glm-4
```

**影响范围**：`agents.py` 一处、`.env` 文件

### Flask App — 加 API 端点

**文件**：`app/app.py`

**改动**：
1. 保持现有路由不动
2. 新增 React 前端需要的 API 端点（如 `/api/dashboard/stats`、`/api/agent/performance`）
3. Cobo Pact 回调端点（Demo 阶段模拟）

**不做**：不改现有业务逻辑

---

## 三、废（Discard）

### 全部前端模板

| 文件 | 理由 |
|------|------|
| `app/templates/index.html` | 853 行内联 CSS，像素风游戏 UI |
| `app/templates/employer.html` | 雇主端旧版 |
| `app/templates/jobseeker.html` | 求职者端旧版 |
| `app/templates/agents.html` | Agent 展示页旧版 |
| `app/templates/creator_earnings.html` | 收益页旧版 |
| `app/static/css/pixel.css` | 像素风 CSS |

**替代**：`frontend/` 目录下的 React 项目

### 旧需求文档

| 文件 | 理由 |
|------|------|
| `hire_net_frontend_page_requirements.md` | 691 行旧需求，已被 `docs/ux-spec.md` 替代 |

→ 移到 `docs/archive/` 存档

---

## 四、加（Add）

### 新前端项目

```
frontend/
├── src/
│   ├── App.jsx
│   ├── main.jsx
│   ├── pages/
│   │   ├── Home.jsx          # 节点 0：首页
│   │   ├── Analysis.jsx      # 节点 1：AI 追问
│   │   ├── Report.jsx        # 节点 2：分析报告
│   │   ├── PactConfirm.jsx   # 节点 3：Pact 确认
│   │   ├── Execution.jsx     # 节点 4：执行+交付
│   │   └── Dashboard.jsx     # 节点 5：企业控制台
│   ├── components/
│   │   ├── TaskCard.jsx      # 任务卡片（Agent/招聘/协同三种状态）
│   │   ├── AgentBadge.jsx    # Agent 信息徽章
│   │   ├── ProgressBar.jsx   # 执行进度条
│   │   ├── DataSandbox.jsx   # 节点 0.5：数据沙箱确认
│   │   └── CostBreakdown.jsx # 费用明细
│   └── styles/
│       └── design-tokens.css # DESIGN.md Token
├── index.html
├── package.json
└── vite.config.js
```

### 新文档

```
docs/
├── ux-spec.md        # UX 规格（✅ 已创建）
├── mvp-prd.md         # MVP PRD（✅ 已创建）
├── code-analysis.md   # 本文档
├── DESIGN.md          # 设计 Token 规范（待创建）
└── archive/
    └── hire_net_frontend_page_requirements.md  # 存档旧需求
```

---

## 五、改造影响总览

```
改动量：极小

改：app/agents/agents.py（2 行：API key + base_url）
改：app/app.py（新增 3-5 个 API 端点）
废：app/templates/*.html（5 个文件）
废：app/static/css/pixel.css
加：frontend/ 目录（React 项目，~15 个文件）
存：docs/archive/ 归档旧需求

保留：app/agents/、app/schemas/、app/storage/、app/services/、app/routes/skills.py、app/routes/earnings.py、tests/ 全部不动
```

**核心原则**：后端零重构。只换模型 + 加 API + 废前端。
