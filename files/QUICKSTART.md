# HireNet 快速启动指南

## 1. 安装依赖

```bash
cd hirenet
pip install -r requirements.txt
```

## 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入以下关键值：

| 变量 | 说明 | 优先级 |
|------|------|--------|
| `SECONDME_CLIENT_ID` | 已填好（234268a6...） | ✅ |
| `SECONDME_CLIENT_SECRET` | 去控制台 Regenerate 后填入 | 🔴 必须 |
| `KIMI_API_KEY` | Kimi 开放平台申请 | 🔴 必须 |
| `CANDIDATE_A_TOKEN` | 候选人A的 Second Me access token | 🔴 今晚完成 |
| `CANDIDATE_B_TOKEN` | 候选人B的 Second Me access token | 🔴 今晚完成 |
| `CANDIDATE_C_TOKEN` | 候选人C的 Second Me access token | 🔴 今晚完成 |
| `AGENT_CODE_TOKEN` | 代码Agent的 Second Me access token | 🔴 今晚完成 |
| `AGENT_CONTENT_TOKEN` | 文案Agent的 Second Me access token | 🟡 可选 |
| `AGENT_DATA_TOKEN` | 数据Agent的 Second Me access token | 🟡 可选 |

## 3. 创建演示账号（今晚必做）

需要创建 6 个 Second Me 账号（用不同邮箱注册）：

### 候选人账号（3个）

| 账号 | 角色 | 需要在 Second Me 里填写的内容 |
|------|------|---------------------------|
| 候选人A | 全栈工程师 | 技能：React, Node.js, Python, Docker；经验：3年全栈开发经历 |
| 候选人B | 产品经理 | 技能：需求分析, PRD写作, AI产品；经验：2年AI产品经理 |
| 候选人C | 数据分析师 | 技能：Python, SQL, 数据可视化, 机器学习；经验：4年数据分析 |

每个账号创建 Second Me 后，在"软记忆"里添加以下条目：
- factObject: "技能" → factContent: "列出技能"
- factObject: "工作经历" → factContent: "描述经历"
- factObject: "期望岗位" → factContent: "填写偏好"

然后通过 OAuth2 Debugger 获取 access token，填入 .env

### 功能型 Agent 账号（3个）

| 账号 | 角色 | 软记忆内容 |
|------|------|----------|
| 代码Agent | AI代码生成助手 | 技能：前端开发、后端开发、脚本编写 |
| 文案Agent | AI文案创作助手 | 技能：营销文案、SEO、产品描述 |
| 数据Agent | AI数据分析助手 | 技能：数据清洗、可视化、统计分析 |

## 4. 获取演示账号的 Access Token

使用 Second Me OAuth2 Debugger：
https://develop-docs.second.me/en/docs/authentication/oauth2-debugger

用每个演示账号登录，授权你的 HireNet 应用，获取 access token，填入 .env

## 5. 运行

```bash
python app.py
```

访问 http://localhost:3000

## 6. 验证安装

```bash
python test_basic.py
```

## 演示场景

### 场景A：不需要招人
输入："我需要给官网写5篇SEO博客文章，大概500字每篇"

期望输出：Agent 可完成，推荐文案撰写 Agent，预计成本 $0.10

### 场景B：需要招人
输入："我们要开发一个AI数据看板，需要长期维护，团队里没有工程师"

期望输出：需要招聘全栈工程师，JD水分评分，候选人匹配结果

### 场景C：混合方案
输入："搭建电商网站，需要UI设计、前端开发和产品文案"

期望输出：混合方案，部分用Agent，部分需要人
