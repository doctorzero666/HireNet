# 🍃 HireNet — AI 劳动力网络

> 企业发布需求 → AI Agent 自动执行 → 创作者获得链上收益。由 Cobo 安全托管，智谱 GLM-4 驱动智能。

![Python](https://img.shields.io/badge/Python-3.11-blue?style=flat-square&logo=python)
![Flask](https://img.shields.io/badge/Flask-3.x-lightgrey?style=flat-square&logo=flask)
![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react)
![Vite](https://img.shields.io/badge/Vite-8-646CFF?style=flat-square&logo=vite)
![Tests](https://img.shields.io/badge/tests-480_passed-brightgreen?style=flat-square)
![Hackathon](https://img.shields.io/badge/AI×Web3-Hackathon-orange?style=flat-square)

---

## 🎯 一句话

HireNet 是一个 Task-first 的 Human-Agent 劳动力网络。企业描述需求，AI 拆解任务、匹配 Agent，通过 Cobo Agentic Wallet 完成链上结算，创作者获得持续版税收益。

---

## 🎬 Demo

```
企业登录 → 描述需求 → AI 追问分析 → 任务拆解 → Agent 匹配
  → Pact 确认 → Cobo 结算 → tx_hash 链上可查
  → 创作者登录 → 收益面板 → 看到结算到账
  → 求职者浏览岗位广场 → 一键投递 → AI 求职信
```

---

## 🏗 技术架构

| 层 | 技术 |
|----|------|
| 前端 | React 18 + Vite + Island 动森风 UI |
| 后端 | Flask + SQLite + 智谱 GLM-4 |
| 支付 | Cobo Agentic Wallet (Pact → approve → settle) |
| 鉴权 | JWT + pbkdf2 |
| 测试 | pytest 480 passed |

### 系统架构

```
┌─────────────────────────────────────────┐
│           Interface Layer               │
│  15 页 React SPA（企业/创作者/求职者）    │
└─────────────────────────────────────────┘
                  │
┌─────────────────────────────────────────┐
│           Decision Layer                │
│  需求分析 · 任务拆解 · Agent 匹配        │
│  JD 生成 · 候选人匹配 · 求职信生成       │
│  全部由智谱 GLM-4 驱动                  │
└─────────────────────────────────────────┘
                  │
┌─────────────────────────────────────────┐
│           Settlement Layer              │
│  Pact 创建 → 审批 → settling → settled  │
│  3-way 分账 (creator + platform + tax)  │
│  Cobo Provider / Mock Provider 可切换    │
└─────────────────────────────────────────┘
```

---

## 📂 项目结构

```
HireNet/
├── app/                        # Flask 后端
│   ├── agents/                 # AI Agent（需求分析/JD生成/候选人匹配）
│   ├── services/               # 结算provider/auth
│   ├── storage/                # SQLite DAO
│   ├── routes/                 # 路由
│   └── app.py                  # 主入口（路由+create_app）
├── frontend/                   # React 前端
│   ├── src/
│   │   ├── pages/              # 15 个页面
│   │   ├── components/         # 共享组件（Ribbon/Icon/StreamText）
│   │   ├── services/api.js     # API 调用层
│   │   ├── hooks/              # useStream
│   │   └── styles/             # Island CSS + tokens
│   └── vite.config.js
├── tests/                      # 480 tests (pytest)
├── docs/                       # PRD/UX Spec/Phase Specs
└── wsgi.py                     # 启动入口
```

---

## 🚀 本地运行

```bash
git clone https://github.com/doctorzero666/HireNet.git
cd HireNet

# 后端
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填写 ZHIPU_API_KEY
PORT=5001 python wsgi.py

# 前端（新开终端）
cd frontend
npm install
npm run dev              # http://localhost:5173
```

---

## 💰 支付闭环

```
企业创建 Pact → Cobo approve → settle
  → royalty_ledger 写 3 行（creator + platform + tax）
  → 创作者 GET /api/creator/earnings 看到 accrued 收益
```

Provider 接口设计为可替换（Mock / Cobo / x402）。

---

## 📋 Hackathon 提交

- **赛道**：Cobo Track — Trustless Agent Work Agreements
- **赞助方**：Cobo（Agentic Wallet）+ 智谱（GLM-4）
- **提交材料**：代码仓库 + Demo 视频 + README
