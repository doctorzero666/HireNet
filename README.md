# 🍃 HireNet

> 如果"招聘"这件事，本身就是错的呢？

![Python](https://img.shields.io/badge/Python-3.11-blue?style=flat-square&logo=python)
![Flask](https://img.shields.io/badge/Flask-3.x-lightgrey?style=flat-square&logo=flask)
![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react)
![Tests](https://img.shields.io/badge/tests-480_passed-brightgreen?style=flat-square)
![Hackathon](https://img.shields.io/badge/AI×Web3-Hackathon-orange?style=flat-square)

---

## 💥 为什么是 HireNet

今天的招聘流程：写 JD → 发岗位 → 收简历 → 筛候选人。

但我们很少去质疑前提：**"我们需要招聘一个人"**。

现实是——很多工作只是零散任务的组合。HR 很难准确表达需求，团队也未必真的需要一个完整的人。于是我们得到了一个奇怪的系统：用岗位描述问题，用简历匹配问题，用筛选解决问题。

> 这不是解决问题的最好方式。

---

## 💡 核心判断

> ❌ 招聘不是默认答案  
> ✅ 完成任务才是

---

## 🧠 HireNet 是什么

> **一个 Task-first 的 Human-Agent 劳动力网络。由 AI 理解工作、拆解工作、并调度资源完成工作。支付由 Cobo 安全托管，收益自动链上结算。**

不是招聘网站，不是简历平台，不是 AI 工具集合。

它是一个新的"劳动力操作系统"——企业描述想完成什么，系统自动判断：AI Agent 独立做、人类来做、还是人机协同。

---

## ⚙️ 如何工作

### 🏢 企业端

不再写 JD。直接描述需求。

系统会：
1. AI 追问明确真实需求
2. 自动拆解为多个任务
3. 对每个任务做出决策——🤖 Agent 完成 / 👤 招募人才 / ⚡ 人机协同
4. 一键启动 Agent，通过 **Cobo Agentic Wallet** 完成支付
5. 创作者自动收到链上收益，tx_hash 可查

### 🎨 创作者端

上传 AI Agent → 被企业调用 → 自动获得版税收益。

不是"接单"，是让技能变成可被调用、可累积版税的**数字资产**。

### 👤 求职者端

不再问"我该投哪个岗"。而是浏览真实的任务需求，AI 分析你的优势，一键匹配最适合的方向。

从"找工作" → "参与协作"。

---

## 🤖 背后的 Agent 网络

HireNet 的底层是一个多 Agent 协作系统：

- **Requirement Analysis Agent** → 理解需求
- **Task Decomposition Agent** → 拆解任务
- **Resource Decision Engine** → 判断谁来做
- **Job Design Agent** → 生成精准 JD
- **Matching Engine** → 匹配技能与任务
- **Candidate Profile Agent** → 构建画像
- **Application Agent** → 生成求职信

全部由**智谱 GLM-4** 驱动。

---

## 💰 支付闭环

```
企业 Pact → Cobo approve → settle
  → royalty_ledger 写 3 行（creator + platform + tax）
  → 创作者实时看到 accrued 收益
  → 链上 tx_hash 可查
```

**结算 provider 可替换**：Mock（Demo）/ Cobo WaaS 2.0 / x402。

---

## 🎮 为什么体验不一样

我们刻意避免做成 LinkedIn、Boss直聘。

因为问题不仅是效率，更是**情绪压力**。

所以：
- 🍃 Island 动森风 UI —— 低压、温暖、不影响判断
- 🔐 JWT 真鉴权 —— 每人只看自己的数据
- 🎯 身份切换 —— 一套系统，三端视角

---

## 🚀 本地运行

```bash
git clone https://github.com/doctorzero666/HireNet.git
cd HireNet

# 后端
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填 ZHIPU_API_KEY
PORT=5001 python wsgi.py

# 前端（新开终端）
cd frontend && npm install && npm run dev
# → http://localhost:5173
```

---

## 📂 项目结构

```
HireNet/
├── app/               # Flask 后端
│   ├── agents/        # AI Agent 集合
│   ├── services/      # 结算 provider / auth
│   ├── storage/       # SQLite DAO
│   └── app.py         # 路由 + create_app
├── frontend/          # React SPA
│   └── src/
│       ├── pages/     # 15 个页面
│       ├── components/# Ribbon / Icon / StreamText 等
│       └── styles/    # Island CSS
├── tests/             # 480 pytest
├── docs/              # PRD / UX Spec / Phase Specs
└── wsgi.py            # 启动入口
```

---

## 🏆 Hackathon

- **赛道**：Cobo Track — Trustless Agent Work Agreements
- **赞助方**：Cobo（Agentic Wallet）+ 智谱（GLM-4）
- **提交**：代码仓库 + Demo 视频 + README
