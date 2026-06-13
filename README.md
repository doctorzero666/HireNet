# 🍃 HireNet — AI 劳动力网络

> 如果"招聘"这件事，本身就是错的呢？

![Python](https://img.shields.io/badge/Python-3.11-blue?style=flat-square&logo=python)
![Flask](https://img.shields.io/badge/Flask-3.x-lightgrey?style=flat-square&logo=flask)
![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react)
![Tests](https://img.shields.io/badge/tests-532_passed-brightgreen?style=flat-square)
![Hackathon](https://img.shields.io/badge/AI×Web3-Hackathon-orange?style=flat-square)

---

## 💥 为什么是 HireNet

今天的招聘流程：写 JD → 发岗位 → 筛简历 → 面试。但我们很少质疑前提——**"需要招聘一个人"** 真的是默认答案吗？

HireNet 不做招聘。企业描述需求，AI 拆解任务，Agent 自动执行，Cobo/Anvil 链上结算——创作者获得版税，求职者精准匹配。

> **一个让 AI 替你工作、链上替你分钱的劳动力网络。**

---

## 🎬 产品全貌

HireNet 有三个入口，对应三种角色。点击下方截图区查看每个界面的详细介绍。

---

## 🏠 起始页：角色选择

> <img width="2418" height="1648" alt="image" src="https://github.com/user-attachments/assets/b99d69c2-4e45-40d5-8fb6-addba90a00a5" />


进入系统后，用户选择自己的身份——雇主、创作者、求职者。三个角色各有独立的操作流程和收益模型，共享底层 AI 分析引擎和链上结算网络。

底部「进入 Agent 世界」可浏览所有已注册的 AI Agent，查看谁在让这个世界运转。

---

## 🏢 雇主端：从需求到执行

### 雇主分流页

> <img width="2510" height="1644" alt="image" src="https://github.com/user-attachments/assets/17dbf778-1eb9-4d5d-b9c9-1fb86bf4271b" />


选择「雇主」后到达分流页。两条路径可选：
- **业务大本营**：查看 Dashboard，了解正在运行的 Agent 和业务指标
- **发起委托**：描述需求，让 AI 拆解并匹配 Agent

### 需求描述

> <img width="2100" height="1420" alt="image" src="https://github.com/user-attachments/assets/4a865495-2aed-4cba-93f4-a92d06649f3a" />

企业用自然语言描述想完成的事——例如「为电商平台搭建智能客服系统」。不需要写 JD，不需要懂技术。系统给出示例提示引导输入。

### AI 智能追问

> <img width="1812" height="1312" alt="image" src="https://github.com/user-attachments/assets/5cf6d4c7-66db-4ab6-beac-53a68b74f67c" />



智谱 GLM-4 驱动的需求分析 Agent 自动追问关键信息——覆盖场景、预算、渠道等。用户通过快捷选项或自然语言回答。只有真正理解需求后，系统才进入下一步。

### 分析报告：任务拆解 + Agent 匹配

> <img width="1640" height="1660" alt="image" src="https://github.com/user-attachments/assets/f9197a22-4332-4c66-89dc-04e79e001121" />


AI 将需求拆解为多个任务，并对每个任务做出智能决策：
- 🟢 **Agent 可完成**：已有 AI Agent 能独立处理
- 🟡 **需招聘人才**：仍需人类参与，自动生成精准 JD
- 🔵 **人机协同**：Agent + 人类配合完成

### Pact 授权：Cobo/Anvil 链上支付

> <img width="1030" height="1484" alt="image" src="https://github.com/user-attachments/assets/0d15d0ce-f764-4d34-95c0-f4c6c2ca5b1d" />


点击「启动 Agent」后，弹窗展示费用构成、创作者钱包地址、预估工时。用户确认后，系统通过 Cobo Agentic Wallet（或本地 Anvil 链）完成链上结算。**这是核心闭环。**

### 执行交付 + 链上可查

> <img width="1600" height="1288" alt="image" src="https://github.com/user-attachments/assets/16c4f30a-21ee-42a3-a8f9-ac4d01ca4b20" />


Agent 完成后，页面展示费用拆分——创作者、平台、税费各分多少，一分不差。**交易哈希（tx_hash）可直接在 Anvil 本地链上查验**，实现「链上可查、不可篡改」。

### 企业控制台 Dashboard

> <img width="1868" height="1618" alt="image" src="https://github.com/user-attachments/assets/7ea990bd-c6c8-4bcf-82ed-5e8fe67488d4" />


雇主可随时查看业务全景——月销售额、活跃 Agent 数、任务完成率、节省的人力成本。所有 Agent 的调用次数和准确率一目了然。

---

## 🎨 创作者端：注册 Agent 并获利

### 创作者工坊

> <img width="2228" height="1556" alt="image" src="https://github.com/user-attachments/assets/6632aa06-a568-4892-9185-91b98e5e51db" />


展示创作者已注册的所有 Agent。每个 Agent 标注是否已连接 MCP 端点。点击可查看详细性能数据。

### 注册 Agent + MCP 接入

> <img width="2406" height="1764" alt="image" src="https://github.com/user-attachments/assets/cb7bfb87-7636-4ff3-8fc4-83e636ff1c5c" />


创作者填写 Agent 信息（名称、描述、类型、时薪、钱包地址），并配置 MCP 端点 URL。点击「测试连接」可验证 MCP Server 是否返回可用工具列表——**这是 Demo 关键展示点**，证明 Agent 不是静态数据，而是可以真实调用的服务。

### Agent 性能面板

><img width="2150" height="1802" alt="image" src="https://github.com/user-attachments/assets/7485b0d4-fa79-43ce-9938-d9d324c79055" />


展示单个 Agent 的调用次数、准确率、累计收益。每次被企业调用，Cobo/Anvil 自动结算一笔版税到创作者钱包。

### 收益账本

> <img width="2072" height="1596" alt="image" src="https://github.com/user-attachments/assets/1afc9715-5602-4f22-865e-9002c84c0e27" />


创作者的所有收益记录——累计收益、已结算、待结算、调用记录、交易哈希。每一笔都有链上 tx_hash 可追溯。

---

## 👤 求职者端：精准匹配 + AI 分析

### 岗位广场

> <img width="2140" height="1572" alt="image" src="https://github.com/user-attachments/assets/88d94aee-2228-4c63-ba20-4f7c0af46abe" />


不是海投简历。浏览由企业端自动生成的精准岗位，薪资区间、工作类型、技术要求一目了然。

### 岗位详情 + 一键投递

> <img width="2118" height="1584" alt="image" src="https://github.com/user-attachments/assets/efade0d3-c0c8-4c15-9c1c-31d5504d6cd8" />
<img width="2136" height="1698" alt="image" src="https://github.com/user-attachments/assets/7a327998-d5ac-4254-b1e0-1c8acb23a94a" />



查看完整 JD 后，一键投递。系统自动匹配候选人与岗位的契合度。

### 我的资料 + AI 分析优势

> <img width="2062" height="1816" alt="image" src="https://github.com/user-attachments/assets/c3f6fe01-ceeb-4bf7-b73b-8fb27e1e869e" />


填写个人资料后，AI 分析技能和经历，告诉你最适合什么方向、核心优势在哪里。从「被筛选」到「认识自己」。

---

## 🤖 Agent 世界

> <img width="2384" height="1474" alt="image" src="https://github.com/user-attachments/assets/30a7a2d6-35cb-4e27-9804-7fc96a6567da" />


所有已注册的 Agent 在此陈列——创作者名、时薪、调用次数、MCP 连接状态。hover 卡片展示青绿边框动画。

已接入 MCP 的 Agent 带 🔗 标签，点击可进入性能面板查看详情。

---

## 💰 商业模式

HireNet 的收入来自每笔交易的平台分成：**企业支付，创作者拿七成，平台抽两成，税费一成**。

Agent 被调用得越多，平台收益越多——一个自增长的飞轮。

---

## 🏗 技术架构

| 层 | 技术 |
|----|------|
| 前端 | React 18 + Vite + Island 动森风 UI |
| 后端 | Flask + SQLite + 智谱 GLM-4 |
| 链上结算 | Anvil 本地测试链（可切换 Cobo WaaS 2.0）|
| Agent 协议 | MCP (Model Context Protocol) |
| 鉴权 | JWT + pbkdf2 |
| 测试 | pytest 532 passed |

---

## 🚀 本地运行

```bash
git clone https://github.com/doctorzero666/HireNet.git
cd HireNet

# 安装依赖
pip install -r requirements.txt
cd frontend && npm install && cd ..

# 启动全部服务（Anvil + 后端 + MCP Server + 前端）
bash start.sh
# → http://localhost:5173
```

---

## 📂 项目结构

```
HireNet/
├── app/               # Flask 后端
│   ├── agents/        # AI Agent（需求分析/JD生成/候选人匹配）
│   ├── mcp_servers/   # Demo MCP Server（数据分析/客服）
│   ├── services/      # 结算提供者/auth/bootstrap
│   └── storage/       # SQLite DAO
├── frontend/          # React SPA（15 个页面）
├── tests/             # pytest 532 passed
├── docs/              # PRD/UX Spec/Demo 配音脚本
└── start.sh           # 一键启动
```

---

## 🏆 Hackathon

- **赛道**：AI × Web3 Agentic Builders — Cobo Track
- **赞助方**：Cobo（Agentic Wallet）+ 智谱（GLM-4）
- **提交材料**：代码仓库 + Demo 视频 + README
