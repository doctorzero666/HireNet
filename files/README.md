# 🌱 HireNet

> 如果“招聘”这件事，本身就是错的呢？

---

## 💥 为什么我们要做 HireNet

今天的招聘流程，看起来是这样的：

1. 写岗位（JD）
2. 发招聘信息
3. 收简历
4. 筛选候选人

但我们很少去质疑一个前提：

> “我们需要招聘一个人”

---

### ⚠️ 一个被默认接受，但其实有问题的系统

现实是：

- 很多工作，本质上只是一些**零散的任务组合**
- HR 很难准确表达真实需求
- 团队也未必真的需要“一个完整的人”
- 求职者在高压环境中盲目投递、不断被筛选

于是我们得到了一个奇怪的系统：

> 用“岗位”去描述问题  
> 用“简历”去匹配问题  
> 用“筛选”去解决问题  

但这并不是解决问题的最好方式。

---

## 💡 我们的核心判断

> ❌ 招聘不是默认答案  
> ✅ 完成任务才是

---

## 🧠 HireNet 是什么

HireNet 是一个：

> **Task-first（任务优先）的 Human-Agent 劳动力网络**

它不是：

- ❌ 招聘网站  
- ❌ 简历平台  
- ❌ AI工具集合  

它是：

> 👉 一个理解工作、拆解工作、并调度资源完成工作的系统

---

## ⚙️ 它是如何工作的？

### 🏢 企业侧（Employer）

企业不再写岗位，而是：

👉 “描述你想完成什么”

系统会：

1. 理解你的真实需求
2. 自动拆解为多个任务
3. 对每个任务做出判断：

- 🤖 Agent 完成
- 👤 Human 完成
- ⚡ Human + Agent 协同完成

4. 最终输出：

- 执行路径
- 成本分析
- 候选人推荐（只有在确实需要人时）

---

### 👤 求职者侧（Job Seeker）

求职者不再问：

> “我该投哪个岗位？”

而是：

> “我应该参与什么样的工作？”

系统提供：

- 个性化任务推荐
- 可视化成长路径（My Journey）
- 能力画像（动态更新）
- 更低压力的交互体验

👉 从“找工作” → “参与协作”

---

## 🤖 背后的核心：Agent Network

HireNet 的本质，是一个多 Agent 协作系统：

- **Career Orchestrator** → 调度系统  
- **Requirement Analysis Agent** → 理解需求  
- **Task Decomposition Agent** → 拆解任务  
- **Resource Decision Engine** → 判断资源类型  
- **Matching Engine** → 匹配人和任务  
- **Candidate Profile Agent** → 构建画像  
- **Job Discovery Agent** → 推荐机会  
- **Application Agent** → 执行动作  
- **Tracker Agent** → 记录成长  

这不是自动化流程。

这是：

> 👉 一个新的“劳动力操作系统”

---

## 🎮 为什么体验看起来不一样？

我们刻意避免做成：

- LinkedIn  
- Boss直聘  
- 传统招聘网站  

因为问题不仅是效率，而是：

> **情绪压力**

---

### 所以我们做了：

- 🎮 像素风 UI（星露谷风格）
- 🌿 低压、温暖的界面设计
- 📈 成长系统（等级 / EXP / Journey）

👉 让“找工作”不再像考试，而更像探索

---

## 🌐 我们真正想做的，不只是这个产品

HireNet 的目标不是一个工具，而是：

> 🧠 一个 AI 时代的劳动力网络基础设施

---

### 🔮 未来的世界会是什么样？

- 企业发布的不是岗位，而是任务  
- Agent 会直接参与执行  
- Human 只在需要判断与创造力的地方参与  
- 开发者可以上传自己的 Agent  
- Agent 会成为新的“劳动力单位”  

---

## 🚀 Demo

👉 https://web-production-9c710.up.railway.app

---

## ⚙️ 技术架构

<!-- Tech Stack Badges -->
![Python](https://img.shields.io/badge/Python-3.11-blue?style=flat-square&logo=python)
![Flask](https://img.shields.io/badge/Flask-lightgrey?style=flat-square&logo=flask)
![OpenAI](https://img.shields.io/badge/OpenAI-API-black?style=flat-square&logo=openai)
![Gunicorn](https://img.shields.io/badge/Gunicorn-Server-green?style=flat-square)
![Railway](https://img.shields.io/badge/Railway-Deploy-purple?style=flat-square)
![HTML](https://img.shields.io/badge/HTML-Frontend-orange?style=flat-square&logo=html5)
![Pixel UI](https://img.shields.io/badge/UI-Pixel%20RPG-yellow?style=flat-square)

Backend:
- Python
- Flask
- OpenAI API

Deployment:
- Gunicorn
- Railway

Frontend:
- HTML
- Pixel RPG 风格 UI

---

## 🗂 项目结构图

```text
HireNet/
├── files/                                   # 核心 Flask 应用目录
│   ├── app.py                               # 应用主入口 / 路由与核心逻辑
│   ├── ...
│
├── README.md                                # 项目说明文档
├── ARCHITECTURE.md                          # 系统架构设计文档
├── hire_net_frontend_page_requirements.md   # 前端页面需求文档
├── hirenet_rpg_ui_tech_doc.md               # 像素风 UI 技术文档
├── requirements.txt                         # Python 依赖
├── wsgi.py                                  # WSGI 启动入口
├── Procfile                                 # Railway / Gunicorn 启动配置
├── railway.toml                             # Railway 部署配置
├── .env.example                             # 环境变量示例
└── ...
```

### 项目结构说明

- `files/app.py`：项目后端主入口，负责承载 Flask 应用与核心逻辑。
- `ARCHITECTURE.md`：完整系统架构说明，定义了 HireNet 的任务优先（Task-first）Human-Agent Labor Network 设计。
- `hire_net_frontend_page_requirements.md`：定义角色选择页、雇主端主控制台、求职者端主页面、Agent 世界页等前端需求。
- `hirenet_rpg_ui_tech_doc.md`：定义像素风 / RPG 风格前端视觉与实现思路。
- `wsgi.py`：用于 Gunicorn 生产部署时加载 Flask app。
- `Procfile` / `railway.toml`：用于 Railway 平台部署。

---

## 🏗 系统架构图

```text
┌──────────────────────────────────────────────────────────────┐
│                       Interface Layer                        │
│ 企业控制台 / 求职者页面 / Agent World / Agent Chat UI       │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                    Orchestration Layer                       │
│ Career Orchestrator / Workflow Engine / Task Router         │
│ Human-in-the-loop Manager                                   │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                       Decision Layer                         │
│ Requirement Analysis Agent                                  │
│ Task Decomposition Agent                                    │
│ Resource Decision Engine                                    │
│ Job Design Agent                                            │
│ Matching Engine                                             │
└──────────────────────────────────────────────────────────────┘
                 │                               │
       ┌─────────┘                               └─────────┐
       ▼                                                   ▼
┌──────────────────────────────┐              ┌──────────────────────────────┐
│      Agent Resource Hub      │              │      Human Resource Hub      │
│ Coding / Data / Analysis     │              │ Candidate Profiles           │
│ Content / Browser / Ops      │              │ Recruit Pipeline             │
└──────────────────────────────┘              └──────────────────────────────┘
                 │                               │
                 └───────────────┬───────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────┐
│                       Execution Layer                        │
│ A2A Agent Invocation / Browser Agent / ATS Adapter          │
│ Platform Adapter / Task Runner                              │
└──────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────┐
│                    Data & Memory Layer                       │
│ User Info / Soft Memory / Notes / Candidate Memory          │
│ Company Memory / Task Records / Match Results / Logs        │
└──────────────────────────────────────────────────────────────┘
```

### 架构说明

HireNet 采用的是一个 **Task-first（任务优先）** 的 Human-Agent 协作系统。

系统不会默认把企业需求转化为“招聘岗位”，而是先经历以下流程：

1. **理解需求**：企业用自然语言输入想完成的事情。
2. **拆解任务**：系统自动把复杂需求拆解成多个子任务。
3. **资源决策**：判断这些任务应该由 Agent、Human，还是协同完成。
4. **执行与匹配**：
   - 能自动完成的任务进入 Agent 执行链路
   - 需要人参与的任务进入匹配与招聘链路
5. **持续追踪**：通过 Candidate Profile、Tracker、Memory 等模块记录成长与状态。

这一架构的核心价值在于：

> 不再默认“先招聘一个人”，而是先判断“这件事应该如何被完成”。

---

## 🧪 本地运行

```bash
git clone https://github.com/doctorzero666/HireNet.git
cd HireNet

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
python wsgi.py
```

> 如果你使用 Gunicorn 运行生产环境，可以使用：
>
> ```bash
> gunicorn --chdir /app wsgi:app --bind 0.0.0.0:8000 --workers 2 --timeout 120
> ```
