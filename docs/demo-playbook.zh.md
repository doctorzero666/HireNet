# HireNet 演示与测试手册

**版本**：2026-09-05，对应 main 合并 `feature/i18n-data`（种子数据双语化 + 全路由 `lang` 透传）之后的版本。

本手册供两个用途：一是产品负责人自测所有功能是否按预期工作；二是在澳大利亚向他人演示产品，界面语言为英文。所有引用的界面按钮文案均以反引号标出，并逐条核对与 `frontend/src/i18n/en.json` 中键值一致，方便照文案在屏幕上找到对应按钮。

文中所有结论均来自对代码的直接阅读（`app/app.py`、`frontend/src/`、`docs/x402-settlement.md` 等），而非产品记忆或历史演示脚本——仓库里的 `docs/demo-script.md` / `docs/demo-voiceover.md` 是黑客松时期的旧稿，其中提到的 Cobo 支付已在 2026-09 移除，仅作历史参考，不可按其操作。

---

## 1. 准备

**两个公开地址**

| 用途 | 地址 |
| --- | --- |
| 前端（Demo 入口） | `https://frontend-nine-gamma-37.vercel.app` |
| 后端 API | `https://web-production-9c710.up.railway.app` |
| 后端健康检查 | `https://web-production-9c710.up.railway.app/api/health`（返回 `{"status": "ok"}`） |

前端通过 `frontend/vercel.json` 的 rewrite 规则把所有 `/api/*` 请求转发到上面这个 Railway 地址，因此正常使用时不需要单独访问后端域名，只有做健康检查或直接调 API（第 5、6 节）时才需要。

**浏览器建议**：使用最新版 Chrome / Edge / Safari 均可；界面依赖 `localStorage`，请不要使用无痕/隐私模式打开（否则语言选择、JWT 登录状态不会保留，且部分浏览器在隐私模式下访问 `localStorage` 会抛异常——代码里做了 try/catch 兜底，功能仍可用，但设置不会持久化）。窗口宽度建议 ≥ 1024px，页面按 860px 宽的卡片居中布局设计，窄屏会挤压但不会报错。

**如何切换英文**

- 切换按钮固定悬浮在页面右上角（`frontend/src/App.jsx` 里作为 `LanguageToggle className="lang-toggle--floating"` 全局挂载一次），在有导航栏的页面里也会出现在 `NavBar` 内。
- 按钮显示的是"切换到的目标语言"：英文界面下按钮显示"中文"，中文界面下按钮显示 `EN`。这是刻意设计（见 `frontend/src/i18n/LanguageToggle.jsx` 注释），演示时不要误以为按钮显示的是"当前语言"。
- 语言选择保存在浏览器 `localStorage`，键名 `hirenet.lang`，值为 `en` 或 `zh`。
- **默认语言已经是英文**（`frontend/src/i18n/LanguageProvider.jsx` 中 `DEFAULT_LANG = 'en'`）——对任何第一次访问、浏览器里还没有 `hirenet.lang` 记录的访客，生产环境看到的都是英文，不需要任何切换动作；只有在清空过浏览器数据、或想现场展示"切换语言"这个功能点时才需要点它（见第 4 节）。

**关于测试规模**：本仓库的 pytest 总数会随每次改动增减，具体数字以 `README.md` 顶部的 `Tests` 徽章（`![Tests](https://img.shields.io/badge/tests-..._passed-...)`）为准，本手册不写死这个数字，避免和代码脱节。

**演示前 30 秒自检清单**

1. 打开前端地址，能看到 🍃 HireNet 首页三张角色卡（`RoleSelect` 页），无白屏、无控制台报错。
2. 浏览器新标签访问 `https://web-production-9c710.up.railway.app/api/health`，应在几秒内返回 `{"status": "ok"}`；如果第一次请求很慢或超时，多半是 Railway 冷启动，见第 7 节。
3. 确认界面默认就是英文（首页应看到 `Choose your identity` 而不是「选择身份」）；若不是，点右上角切换按钮切回英文一次。
4. 打开一次企业端分析流程到出报告页（第 3.1 节前几步），确认 LLM 调用能正常返回——这一步同时验证了 Zhipu API Key 在 Railway 侧配置有效。

---

## 2. 一句话产品叙事（开场用）

**English (for the Australian audience):**

> HireNet turns a business goal, described in plain language, into a routed decision — should this be done by an AI agent, a hired human, or both — then handles resource matching, task execution, and on-chain settlement, so a company never has to decide "hire someone" or "call an API" before it even knows what the task requires.

（58 词）

**中文（备用，向中文听众口播时使用）：**

> HireNet 用自然语言接收企业的业务目标，自动判断该由 Agent 完成、招聘人类，还是人机协同，再完成资源匹配、任务执行与链上结算——企业不必先决定"招人"还是"调用 Agent"。

（61 字）

---

## 3. 三个角色的演示路径

统一约定：反引号内的英文均为 `en.json` 原文；个别容易混淆的地方额外标出 `模块.键` 路径，方便核对来源。

### 3.1 企业端：从业务目标到链上结算

**① 进入企业角色**

- **点什么**：首页点 `I'm an Employer` 卡片上的 `Enter`（`roleSelect.employer.title` / `roleSelect.enter`）。
- **看到什么**：跳转到 `/employer/hub`，标题 `Guild Hall`，两张卡片：`Enter HQ`（进控制台）与 `Write an engagement`（发起一次真正的需求分析）。
- **背后发生了什么**：纯前端路由跳转，无 API 调用。
- **讲解要点**：`Enter HQ` 对应的 Business HQ 页面（`EmployerDashboard`）里的四个指标（`Spend this month` / `Active Agents` / `Task completion rate` / `Hours saved`）和 Agent 列表、警告条目**全部是前端硬编码的静态演示数据**（`frontend/src/pages/EmployerDashboard.jsx` 里的 `useAgents` / `useWarnings`），不来自后端、点了也不会变化——讲这段时不要暗示这是实时数据。
- **常见坑**：这一页容易被当成"真实业务看板"来问细节，提前说明它是纯 UI mock 即可。

**② 输入业务目标**

- **点什么**：点 `Write an engagement` 进入 `/employer`（`EmployerHome`），标题 `What do you want to get done today?`。可以直接打字，也可以点三个示例 chip 之一自动填充文本框：
  - `Build a smart customer service system` → "I want to build a smart customer service system for an e-commerce platform, covering pre-sales inquiries, after-sales support and complaint handling."
  - `Analyze sales data` → "Help me analyze the last three quarters of sales data and identify growth opportunities and unusual fluctuations."
  - `Build a data dashboard` → "I need a real-time business dashboard that rolls up revenue, complaint rate and conversion across channels."
- 输入非空后点 `Start analysis`。
- **看到什么**：跳转到 `AnalysisChat`（标题 `AI Requirement Analysis`），显示 AI 的第一轮追问。
- **背后发生了什么**：调用 `POST /api/analyze/start`，请求体 `{message, lang}`；`lang` 取当前界面语言（英文界面传 `en`）。后端默认走 v1 实现（`RequirementAnalysisAgent`），系统提示词要求模型"每次最多问 1-2 个最关键问题""通常 2-4 轮对话后"结束。
- **讲解要点**：这是真实的 LLM 调用（智谱 GLM-4），不是预录脚本，每次追问内容可能不同。
- **常见坑**：文本框为空时点 `Start analysis` 前端会直接把焦点还给输入框、**不会发请求**（不是报错，是被 UI 拦下了）；真正的后端空值校验（`POST /api/analyze/start` 传空 `message` 返回 400）只能用 curl 验证，见第 6 节。

**③ 多轮澄清**

- **点什么**：在对话框里继续回答 AI 的问题（也可以点 AI 消息末尾自动识别出的快捷选项按钮，如果它以 `[选项A|选项B]` 形式结尾）。
- **看到什么**：AI 逐条追问，直到某一轮回复以完成标记开头，前端随即显示 `Generating your requirement analysis report…` 并自动跳转到报告页。
- **背后发生了什么**：每条追问都是 `POST /api/analyze/reply`；后端用固定标记 `[REQUIREMENT_COMPLETE]` 判断需求是否收集完整（`app/agents/agents.py`）。**默认路径（v1）没有轮次上限**——如果 AI 一直不给出该标记，对话会无限问下去，这是已知设计（`docs/stage1-task-analysis-spec.md` 审计风险 3）。仓库里还有一条实验性的 v2 实现（`TaskAnalysisAgent`，`HIRENET_TASK_AGENT=v2` 开启），带 `max_turns`（默认 6，可用 `HIRENET_TASK_AGENT_MAX_TURNS` 覆盖）强制在达到上限时抽取一次结构化需求；但 v2 在 20 个黄金用例上的结构分低于 v1（0.8500 对 0.8829，见 `evals/reports/2026-09-04-v1-vs-v2.md`），**没有切换为默认**，公开演示环境跑的就是 v1。若要现场展示 v2 的逐步轨迹回放，需要在本地设置 `HIRENET_TASK_AGENT=v2` 后自己跑一遍，再用 `python scripts/replay_trace.py <session_id>` 回放；公开的 Railway 后端不会自动记录轨迹。
- **讲解要点**：可以主动提一句"这一步没有轮次上限，是已知的待改进点，也正是我们在做结构化评测的原因"，显得诚实、专业。
- **常见坑**：AI 有时会把系统提示词模板"回声"出来（尤其在故意输入很怪的内容时），v1 对此没有专门防御，只是靠更严格的 JSON 解析偶然规避；v2 专门修了这个问题（见 `README.md`「需求分析流水线」一节），但 v2 不是默认。演示时避免刻意输入 prompt injection 类文本。
- **常见坑（语言）**：一个分析 session 的语言在 `POST /api/analyze/start` 那一刻就定型（写进 `analysis_sessions[sid]["lang"]`），之后每次 `/reply` 若不显式传新的 `lang` 就沿用这个值。也就是说，如果开场是在中文界面下点的 `Start analysis`，中途才切到英文，**已经发生的追问历史和已经生成的报告不会被回译**，只有下一次真正发起的 LLM 调用才会跟随新语言——演示时避免在同一个 session 中途切换语言，否则报告会中英文混杂，容易被误当成 bug。想看纯英文效果，从头开始一个新 session 之前先把界面切到英文。

**④ 报告页**

- **点什么**：无需操作，`is_complete` 后自动调用 `POST /api/analyze/decide` 并带着结果跳转到 `/employer/report/:sessionId`（`AnalysisReport`）。
- **看到什么**：
  - 顶部 `Execution Plan` 标题，一句 summary（英文界面下是结构化拼出的英文句子，如 `Recommended: a mixed plan — {agentTasks} task(s) via Agent, {humanTasks} task(s) need a human`，而不是直接翻译后端中文句子——这是 i18n 的第二层，见第 4 节）；
  - 4 个指标：`Tasks` / `Agent-ready` / `Needs hiring` / `Human + Agent`；
  - 每个任务一张卡片，三种类型：
    - **Agent 可完成**（绿色，`Agent-ready` 徽章）：显示 `Matched Agent: `、理由、成本，按钮 `Launch Agent`；
    - **需要招聘**（黄色，`Hiring recommended` 徽章）：显示 `Hiring reason`、`Estimated salary`，按钮 `Generate JD`；
    - **人机协同**（蓝色，`Human + Agent` 徽章）：显示 `Division of labor`，**没有可点击按钮**，纯展示。
- **背后发生了什么**：`/api/analyze/decide` 依次做任务拆解（`decompose_tasks`）、逐任务资源评估与决策（`run_resource_decision`）、按需生成 JD（`generate_jd_report`，每成功生成一份 JD 会通过 `Job Design Agent` 这个 SkillAsset 计一次费，即使这次没点"发布"也一样计费——它计的是"生成"这个动作本身）。
- **讲解要点**：三选一决策（Agent / 招聘 / 协同）是本产品的核心卖点，可以强调"这不是简单的岗位匹配，是更前置的劳动力类型决策"。
- **常见坑**：任务数量、决策类型完全取决于 LLM 这次怎么拆解，同一句话两次跑可能给出不同的任务组合；如果演示紧张，建议提前跑一遍摸底，或用固定的示例 chip 文本以提高可预测性。

**⑤ Pact 授权确认**

- **点什么**：在 Agent 任务卡上点 `Launch Agent`，弹出 `Pact Authorization Confirmation` 弹窗；先看 `Cost Breakdown`（`Rate` / `Estimated duration` / `Total cap`）和 `Payee wallet`，再点 `Confirm authorization`。
- **看到什么**：按钮变灰，依次显示 `Creating Pact…` → `Approving…` → `Settling…`；完成后弹窗内出现一块 `Authorization Mandate`，包含四个字段：
  - `Authorized for`（intent，一句英文描述，如 "Run {agent} for task {id}"）
  - `Payee`（收款钱包地址，缩写显示）
  - `Authorization cap`（amount_cap，本次授权的上限金额）
  - `Valid until`（expires_at，本地时区显示的过期时间）
  - 结算成功后还会多一行 `Transaction hash`（如果后端给了可用的交易哈希）。
  弹窗按钮区变为单一的 `Done`。
- **背后发生了什么**：依次调用 `POST /api/pact/create`（创建待批准的授权，字段命名借用 AP2 的 mandate 词汇——`intent`/`payee`/`amount_cap`/`expires_at`，但**没有真实签名**，前端注释里也明确写了不能说"已签名"/"已验证"）→ `POST /api/pact/approve/<id>`（模拟钱包侧批准）→ `POST /api/pact/settle/<id>`（真正记账 + 尝试结算）。
- **讲解要点**：这一整套是"先出示预算上限和过期时间，再授权，再结算"的三段式，对应 AP2 风格的授权心智模型，即使底层这次走的不是真区块链也要讲清楚这个流程本身的设计意图。
- **常见坑（重要）**：
  1. 公开的 Railway 后端目前配置的结算 provider 是 **`sepolia`**（以太坊 Sepolia 测试网，走"平台事后代付"的旧结算路径），**不是 x402**。x402（Base Sepolia USDC、by-invocation 付费）目前只在本地/测试网下用脚本演示过，见第 5 节；公开环境点 `Confirm authorization` 走的是 sepolia 路径，交易在真实的以太坊 Sepolia 测试网上广播，是异步的——结算响应可能直接带回 `tx_hash`，但链上确认（进而在创作者账本里从"待结算"变"已结算"）需要额外一次 `GET /api/royalty/status/<run_id>` 轮询，前端目前**没有自动轮询这一步**，所以刚结算完的创作者账本页仍可能显示 `Pending`，属于正常现象，不是 bug（详见第 7 节）。
  2. **explorer 链接已按结算轨道修好**：`ExecutionPage`（`frontend/src/pages/ExecutionPage.jsx` 的 `explorerHref()`）不再硬编码 `sepolia.etherscan.io`——优先使用后端返回的 `explorer_url`（x402 结算时由 `X402_EXPLORER_TX_URL` 生成），缺失时按 `settlement_method`/`chain` 自行判断：x402（Base Sepolia）指向 `https://sepolia.basescan.org/tx/<hash>`，sepolia 指向 `https://sepolia.etherscan.io/tx/<hash>`；对没有公开浏览器的轨道（anvil、mock、demo bootstrap 预置的 `demo-preset-...` 假哈希）则**不显示链接**，而不是显示一个查不到交易的坏链接。按钮文案也从 `View on Etherscan` 改成了语言中立的 `View on explorer`（`en.json` 键 `executionPage.viewOnExplorer`）。之前"硬编码以太坊 Sepolia、临时切到 x402 会指错链"的问题已经修复，演示两条结算路径时都可以直接点这个按钮，不需要再改用 Pact 弹窗里的链接。
  3. **Agent 名称已双语化，不再固定显示中文**：弹窗顶部的 Agent 名称、创作者名、钱包地址来自 `GET /api/demo/agent`，现在会按请求的 `lang`（`api.js` 在英文界面下自动带 `?lang=en`）解析——返回 `asset_display_field(asset, "name", lang)` 和 `user_display_name(creator_row, lang)`：中文模式显示"数据分析助手" / 创作者"赵设计"，英文模式显示 "Data Analysis Assistant" / 创作者 "Designer Zhao"。这与 `en.json` 里兜底文案写的 "Customer Service Script Generator"／"@Li Si" 是两回事——那两个字符串只在 `/api/demo/agent` 返回 404 时才会被用到（例如 demo 资产未 bootstrap 的测试环境），演示时基本不会遇到。钱包地址本身不受语言影响，仍是 `ANVIL_TO_ADDRESS` 占位地址。

**⑥ 结算结果页**

- **点什么**：Pact 弹窗结算完成后点 `Done`。
- **看到什么**：跳转到 `ExecutionPage`，显示 `Task Complete`、`Cost Breakdown`（$总额 → 创作者份额 + 平台份额 + 税费份额，70/20/10 演示分账比例）、`Royalty record` 编号；若有交易哈希则显示 `Verifiable on-chain` 卡片和 `View on explorer` 链接（按结算轨道指向对应的区块浏览器，见上一步的说明）；最后可点 `Confirm acceptance`。
- **背后发生了什么**：`Confirm acceptance` 会调用 `POST /api/royalty/settle`（若还没有 tx_hash 就再触发一次结算尝试，接口是幂等的：对已经 `settled` 的 run 重复调用直接返回原结果，`settled_count: 0`）。
- **讲解要点**：可以强调分账比例目前是"验证闭环用的模拟规则"，README 里也明确写了"不代表正式商业定价"。
- **常见坑**：`Download script` 与 `Preview` 两个按钮只弹一个 `alert`，没有真实文件下载/预览，属于占位功能，别在演示里点开期待真实内容。

---

### 3.2 求职者端：从海投到精准匹配

**① 进入求职者角色**

- **点什么**：首页点 `I'm a Jobseeker` 卡片的 `Enter`。
- **看到什么**：跳转到 `/jobseeker`（`JobSeekerHome`），标题 `Job Board`。
- **背后发生了什么**：`GET /api/jobs`，返回三类岗位的并集：写死的 3 条 demo 岗位 + 各企业分析会话生成的 JD + 通过 `Publish to job board` 显式发布的 JD，按 `job_id` 去重。

**② 浏览与查看岗位**

- **点什么**：点某张岗位卡的 `View details`。
- **看到什么**：`JobDetail` 页显示 `Job Description` / `Requirements` / `Key Skills`。
- **讲解要点**：默认能看到的 3 条 demo 岗位（`app/agents/application_agent.py` 的 `DEMO_JOBS`）现在是**双语种子数据**——`GET /api/jobs` 按请求的 `lang` 解析，英文模式下会看到 `Full-stack Engineer` / `AI Product Manager` / `Data Analyst`，公司名也是英文（如 `A technology startup`）；中文模式下和以前一样是"全栈工程师"等。注意这是**下次拉取列表时**才生效的（见第 4 节的数据语言矩阵）：如果你已经停在 Job Board 页面，此时才点右上角切换语言，列表不会立即刷新，需要重新进入 `/jobseeker`（或刷新页面）才会用新语言重新请求 `/api/jobs`。企业侧刚生成/发布的 JD 如果是在英文会话里做的，也会是英文（JD 生成走真实 LLM 调用，受 `lang` 参数控制）。

**③ 投递**

- **点什么**：`One-click apply`。
- **看到什么**：跳转 `ApplicationResult`，显示 `Match score`（百分比）和 `Cover letter drafted by AI` 里 AI 生成的求职信正文。
- **背后发生了什么**：`POST /api/apply`；候选人固定取 `GET /api/candidates` 返回列表的**第一个**（`candidate_a`，"张伟（全栈工程师）"）——**无论当前用哪个身份在浏览，投递用的候选人档案都是同一个，不会跟着身份切换变化**，这是当前实现的限制，讲解时说明一下即可。
- **讲解要点（语言）**：`generate_cover_letter`（求职信生成）现在也接受可选的 `lang` 参数（`app/agents/application_agent.py`），通过 `with_lang_messages` 在英文会话下给系统提示词追加英文输出指令；`api.js` 会在英文界面下自动把 `lang: "en"` 带进 `POST /api/apply`，所以英文模式下投递生成的 `Cover letter drafted by AI` 正文、`key_match_points`、`subject` 都会是英文，中文模式下和以前一样是中文。这条链路之前是仅有的两条完全不受 `lang` 影响、写死中文的 LLM 调用之一，现在已经修复；另一条（候选人优势分析）见下一步④。

**④ 我的档案**

- **点什么**：`View my profile card` → `CandidateProfile`；点 `AI: analyze my strengths`。
- **看到什么**：展示技能标签、经历，AI 给出的 3-5 条优势。
- **背后发生了什么**：`POST /api/candidate/analyze`。提示词里原本写死的"用中文输出"一句已经删掉，现在和其它 LLM 调用一样通过 `resolve_request_lang` + `with_lang_messages` 走统一的语言机制，所以英文模式下（`api.js` 自动带 `lang=en`）这里的 3-5 条优势会是英文，中文模式下是中文——不再是"永远中文"。
- **常见坑**：`Edit profile` 按钮只弹 `Demo: profile editing is coming soon 🚧`，没有真实编辑功能。

---

### 3.3 创作者端：从能力接入到持续收益

**① 进入创作者角色，并切换到正确的演示身份**

- **点什么**：首页点 `I'm a Creator` 的 `Enter`，进入 `/creator`（`Creator Workshop`）。
- **重要前置动作**：页面左下角有一个悬浮胶囊（`IdentitySwitcher`），默认显示某个匿名/占位身份。**创作者相关的所有数据（已注册的 Agent、收益账本）都是按当前身份过滤的**，种子数据挂在 `赵设计`（zhao_design，英文名 Designer Zhao）和 `张AI`（zhang_ai，英文名 AI Zhang）两个身份名下——`DEMO_IDENTITIES` 现在也是双语的，胶囊在英文界面下会显示英文名。演示前请点开胶囊，切换到 `赵设计`，再看 Creator Workshop / Earnings Ledger，才能看到预置的历史调用记录；如果不切换，看到的会是空列表或另一个 stub 身份下的数据。
- **背后发生了什么**：胶囊切换调用 `POST /api/demo/identity`，把身份写入一个 cookie，随后整页刷新。**这一套身份机制和 `/login` 页面的 JWT 登录是两套并行系统**——一旦用 JWT 登录过（`hasJwtToken()` 为真），胶囊会直接隐藏，此时创作者数据按 JWT 里的用户身份取，不再理会胶囊；两者不要混用，混用容易让人以为身份切换失效。

**② 查看已注册的 Agent 与收益**

- **看到什么**：`Creator Workshop` 列表里应能看到"数据分析助手"（若切到赵设计）——徽章显示 `● Online`（因为它配置了 MCP endpoint）。点进去是 `Agent Performance` 页，显示 4 个指标卡（`Total calls` / `This month` / `Accuracy` / `Total`）和 `Earnings Breakdown`（`Accrued` / `Settled` / `Total`）。
- **背后发生了什么**：数据来自 `GET /api/creator/earnings`；启动时后端已经预置了两条历史调用（`app/services/demo_bootstrap.py`）：一条走完整状态机变成 `settled`（带一个明显打了 `demo-preset-` 前缀的假交易哈希，代码注释里特意强调这不冒充任何真实链上凭证），另一条停在 `accrued`。
- **讲解要点**：`Recent Calls` 列表和 `Accuracy: 92%` 是前端写死的展示数据（`AgentPerformance.jsx` 里的 `useCalls`），不是从后端算出来的，别把它当成真实调用日志逐条讲。
- **常见坑**：`Withdraw to wallet` 按钮只弹一条 `💸 Withdrawal request sent to wallet` 提示，**没有发生任何真实转账**。

**③ 收益账本**

- **点什么**：顶部导航 `Earnings Ledger` → `CreatorLedger`。
- **看到什么**：`Call Log` 列表，每行显示 Agent 名、雇主、时间、金额，以及 `✅ Settled` 或 `⏳ Pending` 状态徽章；上方 4 个指标卡：`Total calls` / `Total earnings` / `Settled` / `Pending`。
- **讲解要点**：分账比例 70/20/10（创作者/平台/税费）；`accrued`（待结算，钱在账本上已经记下但还没有实际转出/确认）、`settling`（正在结算中，provider 已经在处理但链上还没确认）、`settled`（已在链上确认，终态）三个状态里，**当前的 `CreatorLedger` 界面把 `settling` 和 `accrued` 都渲染成同一个 `⏳ Pending` 样式**（判定逻辑是 `status === 'settled' ? 已结算 : 待结算`），不会单独区分"正在结算中"，如果要看精确状态需要直接查 `GET /api/royalty/status/<run_id>`。

**④ 注册新 Agent**

- **点什么**：`Register New Agent` → 填写 `Agent name` / `Description` / `Type`（Skill / Agent / Endpoint）/ `Rate $/hour` / `Wallet address` / `MCP Endpoint URL`；可选先点 `Test connection` 探测 MCP 端点。
- **看到什么**：留空 MCP 地址点 `Test connection` 会报错 `Please enter an MCP endpoint URL first`；填完必填项（名称、描述）点 `Submit registration`，成功后弹出 `Registered: {id}` 并跳回 `Creator Workshop`。
- **背后发生了什么**：`POST /api/skills/register`，创建者身份取当前登录/切换的身份（同②的重要前置）；价格换算成"美分基点"存储，注册时不会拒绝空钱包地址（后续也可以不绑定钱包）。
- **讲解要点**：注册的新 Agent 会立刻出现在 `Agent World`（`/agents`）公开索引里，可以现场演示"注册即上架"。

**⑤ Agent World**

- **点什么**：顶部导航 `Agent World`（也可从首页底部 `See who's keeping this world running · Enter the Agent World` 链接进入）。
- **看到什么**：所有已注册 SkillAsset 的卡片，含创作者、调用次数、单价，以及 `🔗 MCP connected` / `📋 MCP pending` 徽章（取决于是否登记了 `endpoint_url`）。
- **讲解要点**：这里能看到的是真实注册在数据库里的 SkillAsset（含种子数据"数据分析助手""SEO 优化 Agent""Job Design Agent"，以及你在④注册的新条目），和企业分析报告卡片里提到的"代码生成 Agent""文案撰写 Agent""数据分析 Agent"（`DEMO_AGENTS`，纯用于需求分析决策引擎内部打分的虚拟资源）**是两套不同的数据**，后者不会出现在 Agent World，讲解时注意别混为一谈。

---

## 4. 语言切换演示

HireNet 现在的口径是：**每一个 SPA 会调用的 JSON 路由都认识 `lang`**（GET 用 `?lang=`，POST 用请求体 `lang` 字段；`frontend/src/services/api.js` 的 `setApiLang` / `apiUrl` / `withLang` 保证每一次请求都会带上当前界面语言，缺省时后端按 `zh` 处理）。`tests/test_i18n_no_cjk_sweep.py` 会把 `frontend/src/services/api.js` 里出现的每一个 `apiUrl(...)` 路由都跑一遍英文请求，断言响应树里不含任何中日韩字符——这条测试是"英文模式下处处英文"这句承诺的机器验证，而不只是这份手册的一家之言。

演示这一功能点时，建议先切到中文走一遍企业分析流程，再切回英文重新走一遍，对照下面这张表讲清楚：切换语言按钮那一下点击，**哪些内容跟着立即变、哪些内容要等到下一次请求或下一次进入页面才变、哪些内容根本不受影响**。

### 数据语言矩阵

| 内容类型 | 存放/生成位置 | 切换语言后的表现 | 生效时机 |
|---|---|---|---|
| **界面文案（Chrome）** | `frontend/src/i18n/en.json` / `zh.json`，`useLang()` 的 `t()` | 全部 15 个页面的按钮、标题、提示语完整双语 | **立即生效**：点击切换按钮的同一渲染周期内就变了，不刷新、不发任何请求 |
| **后端固定策略字串** | `app/agents/decision_policy.py`（`cost_hint`、`reason`）、`app/app.py` 的 `VERDICT_*`（`summary.verdict`）、`app/agents/job_design.py` 的 `NO_HIRING_MESSAGE` / `water_interpretation` | 现在是后端原生双语的 `{"zh","en"}` 常量，由 `pick(value, lang)` 在响应组装时直接选边——前端曾经用来把中文正则替换成英文的 `backendStrings.json` 映射层已经删除，这条路径不再存在两套并行机制 | **下一次响应立即生效**：任何带上新 `lang` 的请求，返回体里这几处字符串就是对应语言；不需要等页面刷新，但需要真的发一次新请求（比如重新走一遍分析流程），已经渲染在屏幕上的旧响应内容不会被就地翻译 |
| **种子/演示数据** | `app/agents/candidate_profile.py`（`DEMO_CANDIDATES`/`MOCK_PROFILES`）、`app/agents/application_agent.py`（`DEMO_JOBS`）、`app/app.py`（`DEMO_IDENTITIES`）、`app/services/demo_bootstrap.py` + `asset_bootstrap.py`（SkillAsset 的 `name_en`/`description_en`）——统一由 `pick()` / `localize()` 按 `lang` 解析 | 完整双语：`GET /api/jobs`、`/api/candidates`、`/api/skills/list`、`/api/demo/identities`、`/api/demo/agent` 等路由按请求的 `lang` 返回对应语言的名字/描述/公司名 | **下一次拉取列表时**才生效，**不是**点切换按钮那一刻。原因：`JobSeekerHome`/`CandidateProfile`/`AgentWorld`/`CreatorLedger` 等页面组件都是 `useEffect(() => {...}, [])`——只在组件**挂载**时发一次请求，不监听语言变化。所以：已经停在某页面时切换语言，页面上显示的旧数据不会变；要看到新语言，需要重新导航进入该页面（触发一次新的挂载 + 请求）或整页刷新。`api.js` 的 `currentLang` 是模块级状态，切换按钮点击后是同步更新的，所以"下一次挂载"用的一定是新语言，不会有竞态 |
| **LLM 生成内容** | 需求澄清对话、任务拆解、JD 生成（`design_job`）、`generate_cover_letter`、`/api/candidate/analyze`、`CareerStrategyAgent`、`/api/mcp` 的模型工具 | 由发起该次调用时的 `lang` 决定：`en` 时后端给系统提示词追加一行 `Output language: respond and produce all JSON string values in English.`（`app/agents/lang_support.py` 的 `with_lang_messages`），生成内容整段是英文 | **生成时就定型，之后不会被动态翻译**：一次分析在英文模式下发起，从首轮追问到最终报告全程英文；`lang` 是写进 `analysis_sessions[sid]["lang"]` 的，之后的 `/reply` 沿用同一个值，除非显式传新值覆盖——历史消息不会因为界面语言切换而回译（另见第 3.1③ 节的"常见坑（语言）"） |
| **MCP 执行结果预览** | `app/mcp_servers/customer_service.py` / `app/mcp_servers/data_analysis.py` 的双语 canned 内容（问候语、FAQ、投诉话术、趋势、异常、报告摘要），`ExecutionPage` 的 `Agent Output Preview`（`executionPage.mcp.outputPreview`） | `POST /api/pact/settle/<id>` 结算成功后会调用 MCP 工具，把 `resolve_request_lang(request)` 的结果当 `lang` 传进去；预览内容是英文还是中文取决于**结算发生那一刻**请求携带的语言 | **结算（settle）那次调用的语言决定**，不是查看页面时的语言；如果结算发生在中文模式下，之后切到英文再回来看这条记录，预览内容仍是结算时生成的那份（中文） |
| **旧版创作者收益页** | `app/templates/creator_earnings.html`（服务端渲染，`GET /creator/earnings` HTML 页） | **始终中文**，不受 `lang` 影响 | 不适用——这个页面不在 SPA 路由树内，正常演示路径（首页→角色卡→前端路由）永远走不到它，只有直接在地址栏输入这个 URL 才会看到，只作历史/后端专用路由参考（见第 6 节 B12） |

**一句话总结**：界面文案和后端固定策略字串是"请求级"生效——发一次带新 `lang` 的请求就变；种子数据是"挂载级"生效——要等页面重新加载数据；LLM 生成内容和 MCP 预览是"生成时刻"生效——已经生成的内容不会被回译；旧版创作者收益页完全在体系外，永远中文。

---

## 5. x402 真实结算演示（测试网）

x402 是"调用即付费"的结算方式：企业侧不预先充值，而是每次真正调用 SkillAsset 时，由调用方（payer）现场签一笔 EIP-3009 `transferWithAuthorization`，facilitator 验证并广播，创作者的钱在拿到调用结果**之前**就已经到账。这条链路走的是 **Base Sepolia 测试网 USDC**，与企业端默认演示走的以太坊 Sepolia（第 3.1 节⑤）是两条不同的测试网、不同的资产，**不要在同一次演示里混讲**。公开的 Railway 后端目前没有开启 x402（`HIRENET_SETTLEMENT_PROVIDER` 配的是 `sepolia`），因此这一节的操作必须在本地跑，不能对着 Vercel/Railway 上的公开环境做。

### 前置条件

1. 克隆仓库、装好依赖（`pip install -r requirements.txt`）。
2. 在仓库根目录准备 `.env`（未跟踪，不会被提交），至少包含：
   - `X402_PAYER_PRIVATE_KEY`：payer 的私钥。**永远不要打印它**——命令行输出、shell 历史、CI 日志、agent 转录都可能把它留下痕迹。没有配置这个变量时，一次 402 会被作为错误报出来，绝不会静默地发起未付费的调用。
   - 建议同时准备好一个**收款方钱包地址**（可以是你自己的地址），供下面 `X402_E2E_PAYEE` 使用。
3. 用官方脚本生成/检查 payer 钱包：
   ```bash
   python scripts/x402_wallet.py new --write-env .env   # 生成新私钥，写入 .env，权限自动设为 0600；私钥本身不会打印
   python scripts/x402_wallet.py balance                # 只读查询 USDC + 原生代币余额
   ```
   如果 USDC 余额是 0，命令会打印领水提示：<https://faucet.circle.com>，网络选 **Base Sepolia**，代币选 **USDC**，每地址每 2 小时可领 20 USDC。**这条链路不需要 Base Sepolia ETH**——facilitator 代付 gas，payer 只需要 USDC。

### 命令与预期输出

```bash
export X402_E2E_PAYEE=0x你的收款地址

# 第一步：只看报价，不签名、不花钱
python scripts/x402_e2e.py --mode direct --dry-run
```
预期：打印一个 `402 quote`（JSON），字段包括 `scheme: "exact"`、`network: "eip155:84532"`、`asset`（USDC 合约地址）、`amount`（原子单位字符串，如 `"10000"` = 0.01 USDC）、`payTo`（收款地址）；命令结尾提示"quote matches the seeded asset"，退出码 0。**这一步不会花钱**。

```bash
# 第二步：真花一次钱，走最简路径（mcp_client 直接付费调用一个工具）
python scripts/x402_e2e.py --mode direct
```
预期：先看到一次 `402`，随后带签名重试拿到 `200`，打印 `payment` 对象（含 `tx_hash`、`payer`、`payee`、`amount_atomic`、`settle_success: true`），随后 `check_status -> settled`，并打印一行 basescan 链接，格式：
`https://sepolia.basescan.org/tx/<tx_hash>`
点开应能在 Base Sepolia 浏览器上看到一笔 0.01 USDC 从 payer 转到 payee 的 `Transfer`。

```bash
# 第三步：走产品真实路径（经过 /api/pact/create → approve → settle）
python scripts/x402_e2e.py --mode pact
```
预期：打印完整的 `POST /api/pact/create` 请求体（能看到 `intent` / `amount_cap` / `expires_at` / `payee` / `content_hash` 这几个 mandate 字段，与第 3.1 节⑤讲的是同一套字段）、批准、结算，最后打印 `agent_runs` 与三行 `royalty_ledger`（creator / platform / tax），并轮询 `GET /api/royalty/status/<run_id>` 直到 `settlement_status -> settled`。

- 每次非 `--dry-run` 调用花费 **0.01 USDC**（`--max-usdc` 默认 0.01，是签名前就会拦下的硬上限）。
- 退出码 0 = 已结算（或 dry-run 通过）；退出码 3 = `PaymentOutcomeUnknown`（签名已发出但结果未知），**这种情况绝不能重跑**，必须先按下面「常见问题」里的对账步骤处理。

### 讲解要点

1. **402 → 签名 → verify/settle**：先探测拿到 402 报价，payer 用 EIP-3009 签一份"转账授权"（不是真的发交易，是签一段数据），facilitator 验证签名有效后才真正广播这笔 USDC 转账、代付 gas；这就是为什么整场演示 payer 钱包里的 ETH 余额始终是 0，也不需要充值 ETH。
2. **平台费目前收不到**：x402 的 `exact` 方案一次只能付给**一个地址**，所以创作者那一份份额是真实到账的链上转账，但平台和税费那两份在账本上只能记成"应收未收"（`settlement_method: x402-fee-receivable`，状态 `accrued`），这是文档里明确写的 Phase 4 才会解决的限制（`docs/x402-settlement.md` §5），不是 bug，讲解时可以直接引用这一点体现工程严谨性。
3. **一分钱拆分会退化**：种子数据里的 SkillAsset 定价是 1 美分/次，70/20/10 拆分在整数分上没法细分，会算成"创作者 0 分、平台 1 分、税费 0 分"（`RemainderStrategy.PLATFORM_ABSORBS`），尽管链上创作者收到的其实是完整的 1 分——账本和链上数字对不上不是算错了，是最小计价单位下的必然现象。**如果要在演示里同时展示账本和区块浏览器，建议把演示用 SkillAsset 定价调到几美分以上**，避免当场解释这个细节。

---

## 6. 完整功能测试清单

按角色分组；"操作"列写点什么，"预期"列写应该看到什么；"通过 / 失败"两列自测时打勾。带 `curl` 标注的行需要直接调用后端 API（浏览器打不出 400/404/409），公开后端地址是 `https://web-production-9c710.up.railway.app`。

### 企业端

| # | 操作 | 预期 | 通过 | 失败 |
|---|---|---|---|---|
| E1 | 首页点 `I'm an Employer` → `Enter` | 跳转 `/employer/hub`，标题 `Guild Hall` | ☐ | ☐ |
| E2 | Guild Hall 点 `Enter HQ` | 显示 4 个静态指标卡 + Agent 列表 + 警告条目 | ☐ | ☐ |
| E3 | Guild Hall 点 `Write an engagement` | 跳转 `EmployerHome` | ☐ | ☐ |
| E4 | 点示例 chip `Build a smart customer service system` | 文本框填入对应英文示例句 | ☐ | ☐ |
| E5 | 输入非空文本点 `Start analysis` | 跳转 `AnalysisChat`，显示 AI 首轮追问 | ☐ | ☐ |
| E6 | 空文本点 `Start analysis` | 不发请求，焦点回到文本框，无报错 | ☐ | ☐ |
| E7 | 依次回答问题直至完成标记出现 | 显示 `Generating your requirement analysis report…`，自动跳转 `AnalysisReport` | ☐ | ☐ |
| E8 | 报告页查看 4 个指标 + summary | 数字与 `Task Breakdown` 列表任务数一致 | ☐ | ☐ |
| E9 | Agent 任务卡点 `Launch Agent` | 弹出 Pact 弹窗，显示 Cost Breakdown / Payee wallet | ☐ | ☐ |
| E10 | Pact 弹窗点 `Confirm authorization` | 依次显示 Creating/Approving/Settling，出现 `Authorization Mandate` 区块 | ☐ | ☐ |
| E11 | 结算完成点 `Done` | 跳转 `ExecutionPage`，显示 Cost Breakdown | ☐ | ☐ |
| E12 | 招聘任务卡点 `Generate JD` | 弹出 `JD Draft` markdown 预览 | ☐ | ☐ |
| E13 | JdModal 点 `Publish to job board` | 显示 `Published to the job board`，返回 job_id | ☐ | ☐ |
| E14 | 查看人机协同任务卡 | 只显示 `Division of labor`，无操作按钮（非 bug） | ☐ | ☐ |
| E15 | ExecutionPage 点 `Confirm acceptance` | 显示 `Accepted — settlement complete` | ☐ | ☐ |
| E16 | 导航栏点 `My Tasks` | 无跳转（`Coming soon`，禁用态，非 bug） | ☐ | ☐ |
| E17 | 发布的 JD 出现在求职者端 | `/jobseeker` 岗位列表能看到新发布的岗位 | ☐ | ☐ |

### 求职者端

| # | 操作 | 预期 | 通过 | 失败 |
|---|---|---|---|---|
| J1 | 首页点 `I'm a Jobseeker` → `Enter` | 跳转 `/jobseeker`，标题 `Job Board` | ☐ | ☐ |
| J2 | 查看岗位列表 | 至少 3 条 demo 岗位（全栈工程师 / AI 产品经理 / 数据分析师） | ☐ | ☐ |
| J3 | 点某岗位 `View details` | 跳转 `JobDetail`，显示描述 / Requirements / Key Skills | ☐ | ☐ |
| J4 | 点 `One-click apply` | 跳转 `ApplicationResult`，显示 Match score | ☐ | ☐ |
| J5 | 查看 `Cover letter drafted by AI` | 有正文；正文语言跟随投递时的界面语言（`generate_cover_letter` 已接入 `lang`，见第 3.2③ 节） | ☐ | ☐ |
| J6 | 点 `View my profile card` | 跳转 `CandidateProfile`，显示张伟档案（英文模式为 Wei Zhang） | ☐ | ☐ |
| J7 | 点 `AI: analyze my strengths` | 显示 3-5 条优势；语言跟随当前界面语言（`/api/candidate/analyze` 已接入 `lang`，不再写死中文，见第 3.2④ 节） | ☐ | ☐ |
| J8 | 点 `Edit profile` | 弹出 "coming soon" 提示，无实际编辑 | ☐ | ☐ |

### 创作者端

| # | 操作 | 预期 | 通过 | 失败 |
|---|---|---|---|---|
| C1 | 首页点 `I'm a Creator` → `Enter` | 跳转 `/creator`，标题 `Creator Workshop` | ☐ | ☐ |
| C2 | 左下角胶囊切换到"赵设计" | 页面刷新，身份变为赵设计 | ☐ | ☐ |
| C3 | 查看 Agent 列表 | 显示"数据分析助手"，`● Online` 徽章 | ☐ | ☐ |
| C4 | 点该 Agent | 跳转 `Agent Performance`，显示 4 个指标卡 | ☐ | ☐ |
| C5 | 查看 `Earnings Breakdown` | 显示 `Accrued` / `Settled` / `Total` 三栏 | ☐ | ☐ |
| C6 | 点 `Withdraw to wallet` | 仅弹提示，无真实转账 | ☐ | ☐ |
| C7 | 导航点 `Earnings Ledger` | 跳转 `CreatorLedger`，看到 call log 与状态徽章 | ☐ | ☐ |
| C8 | 点 `Register New Agent` | 跳转 `AgentRegister` 表单 | ☐ | ☐ |
| C9 | 留空 MCP URL 点 `Test connection` | 报错 `Please enter an MCP endpoint URL first` | ☐ | ☐ |
| C10 | 填真实 MCP 地址（如 `http://localhost:5002`）点 `Test connection`（需本地跑起 MCP server） | 显示 `Found {count} tool(s)` 及工具列表 | ☐ | ☐ |
| C11 | 填完必填项点 `Submit registration` | 弹出 `Registered: {id}`，跳回 Creator Workshop | ☐ | ☐ |
| C12 | 导航 `Agent World` | 显示所有已注册 Agent 卡片，含刚注册的新条目 | ☐ | ☐ |

### 语言切换

| # | 操作 | 预期 | 通过 | 失败 |
|---|---|---|---|---|
| L1 | 任意页面点浮动语言按钮（英文下显示"中文"） | 界面文案切为中文 | ☐ | ☐ |
| L2 | 刷新页面 | 语言保持为上一步选择的语言 | ☐ | ☐ |
| L3 | 再点按钮（中文下显示 `EN`） | 切回英文 | ☐ | ☐ |
| L4 | 英文模式下走一遍企业分析流程 | summary、任务卡理由、JD 内容均为英文；Demo Agent 名称（`GET /api/demo/agent`）、种子岗位/候选人姓名也随之变为英文，因为它们现在都按请求的 `lang` 解析（见第 4 节数据语言矩阵） | ☐ | ☐ |
| L5 | 浏览器打开 `https://web-production-9c710.up.railway.app/api/jobs?lang=en` | 返回 JSON 里 `job_title` / `company` / `core_responsibilities` 等字段全是英文，找不到中文字符 | ☐ | ☐ |
| L6 | 浏览器打开 `.../api/candidates?lang=en` | 返回的候选人 `name` / `bio` / `capability_summary` 全是英文（如 "Wei Zhang (Full-stack Engineer)"） | ☐ | ☐ |
| L7 | 浏览器打开 `.../api/skills/list?lang=en` | 返回的 SkillAsset `name` / `description` / `creator_name` 全是英文（如 "Data Analysis Assistant" / "Designer Zhao"） | ☐ | ☐ |
| L8 | 英文模式下完整走一遍 Pact 结算，在 `ExecutionPage` 查看 `Agent Output Preview` | 预览内容（问候语 / FAQ / 趋势 / 异常等 canned 文本）是英文，不是中文（第 4 节"MCP 执行结果预览"一行） | ☐ | ☐ |
| L9 | 英文模式下本地完成一次 x402 结算（第 5 节），在 `ExecutionPage` 点击 `View on explorer` | 链接指向 `sepolia.basescan.org/tx/<hash>`，能打开对应 Base Sepolia 交易，而不是 404 的 Etherscan 链接 | ☐ | ☐ |
| L10（仅限本地） | 本地设置 `HIRENET_TASK_AGENT=v2` 且 `HIRENET_TASK_AGENT_MAX_TURNS=1`，英文模式下发起分析并让 v2 触发强制抽取失败 | 返回的失败提示是英文、使用半角标点（不是旧版"抱歉，我没能……请换一种说法……"那种全角中文句子）；公开 Railway 环境跑的是 v1，这一行不适用于公开环境 | ☐ | ☐ |

### 登录与身份

| # | 操作 | 预期 | 通过 | 失败 |
|---|---|---|---|---|
| A1 | `/login` 页用 `li_boss` / `demo123` 登录 | 跳转首页，左下角身份胶囊消失 | ☐ | ☐ |
| A2 | `/login` 页用错误密码登录 | 显示错误提示（401） | ☐ | ☐ |
| A3 | 清空浏览器 `localStorage` 中 `hn_token` | 身份胶囊重新出现 | ☐ | ☐ |

### 错误路径（需要 `curl`，浏览器点不出这些状态码）

| # | 操作 | 预期 | 通过 | 失败 |
|---|---|---|---|---|
| X1 | `curl -X POST .../api/analyze/start -d '{"message":""}'` | `400 {"error":"Message is required"}` | ☐ | ☐ |
| X2 | `curl -X POST .../api/analyze/start -d '{"message":"hi","lang":"fr"}'` | `400 {"error":"unsupported lang"}` | ☐ | ☐ |
| X3 | `curl -X POST .../api/analyze/reply -d '{"session_id":"nope","message":"hi"}'` | `404 {"error":"Session not found"}` | ☐ | ☐ |
| X4 | 对一个 `expires_at` 已过期的 pact 调用 `POST /api/pact/settle/<id>` | `409 {"error":"pact expired"}` | ☐ | ☐ |
| X5 | 对一个 `amount > amount_cap` 的 pact 调用 settle | `409 {"error":"amount exceeds cap"}` | ☐ | ☐ |
| X6 | 对已批准的 pact 重复调用 `POST /api/pact/approve/<id>` | `400`，提示当前状态不是 pending | ☐ | ☐ |
| X7 | `POST /api/jobs/publish` 两次传相同 `job_id` | 第二次 `409 {"error":"job_id already published: ..."}` | ☐ | ☐ |
| X8 | `POST /api/auth/register` 用 `user_id: "li_boss"` | `400 {"error":"user_id is reserved: li_boss"}` | ☐ | ☐ |
| X9 | `GET /api/pact/status/pact-doesnotexist` | `404` | ☐ | ☐ |
| X10 | 对已 `settled` 的 run 重复 `POST /api/royalty/settle` | `200`，`settled_count: 0`，幂等无副作用 | ☐ | ☐ |

### 后端专用路由（当前无前端入口，仅可用 `curl` / Postman 验证是否存活）

| # | 路由 | 备注 | 通过 | 失败 |
|---|---|---|---|---|
| B1 | `POST /api/match` | 按 job_design 匹配候选人（旧版接口，前端未接） | ☐ | ☐ |
| B2 | `POST /api/candidate-match` | 候选人对全部岗位打分 | ☐ | ☐ |
| B3 | `GET /api/my-match` | 同上的"我的匹配"视角 | ☐ | ☐ |
| B4 | `GET /api/tracker` | 投递记录查询 | ☐ | ☐ |
| B5 | `POST /api/career/start` / `/reply` / `/generate` | 职业策略 Agent 三件套 | ☐ | ☐ |
| B6 | `POST /api/tracker/task-complete` | 任务完成打点 | ☐ | ☐ |
| B7 | `GET /api/profile/state` | 求职者 EXP/等级状态 | ☐ | ☐ |
| B8 | `POST /api/analyze/quick` | 跳过多轮对话的一次性分析入口 | ☐ | ☐ |
| B9 | `POST /api/mcp` | HireNet 自身对外暴露的 MCP JSON-RPC 端点 | ☐ | ☐ |
| B10 | `GET /api/royalty/split` / `/api/royalty/list` | 按 run_id / session_id 查询分账明细 | ☐ | ☐ |
| B11 | `GET /api/audit/run/<run_id>`（需 `Authorization: Bearer <JWT>`） | 结算审计轨迹 + 链上对账 | ☐ | ☐ |
| B12 | `GET /creator/earnings`（HTML 模板页，非 JSON） | 服务端渲染的创作者收益页 | ☐ | ☐ |

以上共 **17 + 8 + 12 + 10 + 3 + 10 + 12 = 72** 行。

---

## 7. 常见问题与恢复

**后端冷启动延迟**：Railway 免费/低配实例在长时间无请求后会休眠，第一次访问（包括 `/api/health`）可能需要数秒到十几秒才有响应，属正常现象。演示前务必按第 1 节的自检清单先"预热"一次，不要临场才第一次打开。

**LLM 超时 / 报错**：`app/agents/agents.py` 里创建的 OpenAI 兼容客户端（对接智谱 GLM-4）没有设置自定义超时，走 SDK 默认值；如果请求分析卡住不返回，通常是智谱侧限流或网络问题，刷新重试一次即可；如果连续失败，检查 Railway 上 `ZHIPU_API_KEY` 是否还有效、额度是否用尽。`POST /api/candidate/analyze` 失败会返回 `502`（LLM 调用失败），`POST /api/analyze/decide` 失败统一返回 `500 {"error":"analysis failed"}`（后端特意不把异常细节吐给前端，避免泄露 API base URL 等信息，真实原因要看服务端日志）。

**Pact 卡在 `settling` 是什么意思，怎么对账**：`settling` 表示"已经提交给结算 provider，但链上还没有被确认为终态"，是正常的中间状态，不是失败。两种常见来源：
1. **公开环境（sepolia provider）**：`POST /api/royalty/settle` 对异步链上 provider 是"广播即返回"，此时账本三行仍是 `accrued`，run 状态是 `settling`；只有再调用一次 `GET /api/royalty/status/<run_id>` 才会去查链上收据、在确认后把 run 和创作者那一行 `royalty_ledger` 翻成 `settled`。前端目前**不会自动做这次轮询**，所以演示里如果创作者账本迟迟显示 `Pending`，先手动 `curl` 一次这个状态接口再看。
2. **本地 x402 演示**：如果签名已经发出（钱可能已经在链上转移），但因为超时或网络问题没能读到 facilitator 的确认响应，会抛出 `PaymentOutcomeUnknown`，pact 会被**故意**卡在 `settling`（防止重试时对同一笔授权签第二次、造成双花）。这时不能直接重跑脚本，需要按 `docs/x402-settlement.md` §6 的步骤人工对账：记下 pact 上的 `payment_pending.nonce` / `payee` / `amount_atomic`，去 Base Sepolia 浏览器按这三个信息查那笔 `Transfer`（USDC 合约同时会发 `AuthorizationUsed(authorizer, nonce)` 事件，用 nonce 能精确定位）；确认已经成功就手动把 run 记为已结算、不要再结算一次；确认没有成功就等待签名的 `validBefore`（约 5 分钟）过期后，把 pact 状态改回 `approved` 再重试。

**清空浏览器语言偏好**：打开浏览器开发者工具 → Application/存储 → Local Storage → 找到网站条目 → 删除键 `hirenet.lang`（顺带可以删 `hn_token` 清掉登录态），刷新页面即可回到默认英文。

**Railway / Vercel 重新部署**：两边都是 Git 集成的自动部署——推送到 `main` 分支即会触发对应平台的构建与发布（Railway 用 `railway.toml` 里的 `gunicorn wsgi:app --workers 1` 启动命令；Vercel 按 `frontend/` 目录的默认构建流程，并通过 `frontend/vercel.json` 的 rewrite 把 `/api/*` 转发到 Railway 地址）。如果代码没变但想强制重新部署，登录对应平台后台手动触发一次 redeploy 即可，无需改代码。**注意**：`wsgi.py` 里写明后端必须以**单进程**（`--workers 1`）运行，因为需求分析会话、职业策略会话、已发布岗位、求职者 EXP 状态目前都存在进程内内存字典里——一次重启会清空所有正在进行中的分析会话和已发布的 demo 岗位（Pact 已经落库在 SQLite，不受影响）。演示中途不要触发重新部署。

---

## 8. 附录

### 8.1 环境变量速查（只列名字与作用，不列值）

**任务分析 / 语言**

| 变量 | 作用 |
|---|---|
| `HIRENET_TASK_AGENT` | 选择需求分析走 `v1`（默认）还是 `v2` 实现 |
| `HIRENET_TASK_AGENT_MAX_TURNS` | v2 实现的澄清轮次上限（默认 6） |
| `ZHIPU_API_KEY` / `ZHIPU_BASE_URL` / `ZHIPU_MODEL` | 智谱 GLM-4 的鉴权与端点配置 |

**结算 / 链上**

| 变量 | 作用 |
|---|---|
| `HIRENET_SETTLEMENT_PROVIDER` | 选择结算后端：`mock` / `anvil` / `sepolia` / `x402` |
| `HIRENET_X402_GATE` | 是否在 MCP server 上安装 x402 付费墙（`"1"` 开启） |
| `X402_PAYER_PRIVATE_KEY` | x402 调用方（payer）的私钥 |
| `X402_MAX_AMOUNT_PER_PAYMENT` | x402 单笔付款的钱包级上限（原子单位） |
| `X402_PACT_INVOKE_TIMEOUT_S` | x402 付费调用允许的最长耗时 |
| `X402_NETWORK` | x402 使用的 CAIP-2 网络 id |
| `X402_USDC_ADDRESS` | x402 结算用的 USDC 合约地址 |
| `X402_FACILITATOR_URL` | x402 facilitator 服务地址 |
| `X402_RPC_URL` | 读取链上收据用的 RPC 端点 |
| `X402_EXPLORER_TX_URL` | 区块浏览器交易链接模板 |
| `X402_PAYER_ADDRESS` | `x402_wallet.py balance` 命令的默认查询地址 |
| `X402_E2E_PAYEE` | `x402_e2e.py` 演示脚本的收款地址 |
| `HIRENET_MCP_ENDPOINT_URL` | 本地 MCP server 对外声明的 endpoint（供 x402 网关匹配 SkillAsset） |
| `SEPOLIA_RPC_URL` / `SEPOLIA_PRIVATE_KEY` / `SEPOLIA_FROM_ADDRESS` / `SEPOLIA_TO_ADDRESS` | 以太坊 Sepolia 结算 provider 的 RPC 与钱包配置 |
| `ANVIL_RPC_URL` / `ANVIL_FROM_KEY` / `ANVIL_TO_ADDRESS` | 本地 Anvil 链演示 provider 的配置 |

**身份 / 鉴权**

| 变量 | 作用 |
|---|---|
| `HIRENET_JWT_SECRET` | JWT 签名密钥 |
| `APP_SECRET_KEY` | Flask session 密钥 |
| `HIRENET_PHASE1_CREATOR_ID` / `HIRENET_PHASE1_CALLER_ID` | 未切换身份时的兜底创作者/调用者 id |

**运行环境**

| 变量 | 作用 |
|---|---|
| `HIRENET_DB_PATH` | 后端与独立 MCP server 共用的 SQLite 文件路径 |
| `APP_PORT` / `MCP_PORT` / `ANVIL_PORT` / `PORT` | `start.sh` 与 `wsgi.py` 使用的本地端口 |

### 8.2 演示数据一览（中英双语）

自 `feature/i18n-data` 起，下列种子数据在 Python 源码里都是 `{"zh": ..., "en": ...}` 节点，由 `pick()` / `localize()` 按请求的 `lang` 解析；英文名来自各自的 `*_EN` 常量或 `name_en`/`description_en` 列（详见第 4 节数据语言矩阵）。

**SkillAsset（可在 Agent World 看到）**

| 名称（zh） | 名称（en） | 创作者 | 定价 | 说明 |
|---|---|---|---|---|
| Job Design Agent | Job Design Agent（中英同名） | `phase1_stub_creator`（stub） | $1.00/次 | 每次成功生成 JD 计费一次；Pact 未指定 `asset_id` 时的兜底资产；英文描述见 `app/services/asset_bootstrap.py` 的 `JOB_DESIGN_ASSET_EN` |
| 数据分析助手 | Data Analysis Assistant | 赵设计 / Designer Zhao（`zhao_design`） | $40/单位时长 | `GET /api/demo/agent` 返回的就是它；企业端 Pact 演示默认用的是这一个 |
| SEO 优化 Agent | SEO Optimization Agent | 张AI / AI Zhang（`zhang_ai`） | $25/单位时长 | endpoint 指向真实跑着的 customer_service MCP（:5002） |

**demo 候选人（`GET /api/candidates`）**：

| 姓名（zh） | 姓名（en） | 角色 |
|---|---|---|
| 张伟（全栈工程师） | Wei Zhang (Full-stack Engineer) | fullstack |
| 李娜（产品经理） | Na Li (Product Manager) | product_manager |
| 王芳（数据分析师） | Fang Wang (Data Analyst) | data_analyst |

求职者端投递流程固定使用第一个（张伟 / Wei Zhang），与当前身份无关。

**demo 岗位（`DEMO_JOBS`）**：

| 岗位（zh） | 岗位（en） | 公司（zh / en） |
|---|---|---|
| 全栈工程师 | Full-stack Engineer | 某科技创业公司 / A technology startup |
| AI 产品经理 | AI Product Manager | AI 应用公司 / An applied-AI company |
| 数据分析师 | Data Analyst | 电商平台 / An e-commerce platform |

**决策引擎内部使用的虚拟资源（不会出现在 Agent World）**：代码生成 Agent、文案撰写 Agent、数据分析 Agent（`DEMO_AGENTS`）——仅用于需求分析报告页任务卡片里的"推荐使用 XX"文案，与上面注册在 Agent World 的真实 SkillAsset 是两套数据；这套虚拟资源的名字同样通过 `get_all_resources(lang)` 双语化。

**demo 身份 / 登录账号（密码均为 `demo123`）**：

| id | 姓名（zh） | 姓名（en） | 角色 |
|---|---|---|---|
| `li_boss` | 李老板 | Boss Li | Enterprise |
| `zhang_ai` | 张AI | AI Zhang | Creator |
| `wang_dev` | 王工 | Engineer Wang | Jobseeker |
| `zhao_design` | 赵设计 | Designer Zhao | Creator |

### 8.3 相关文档链接

- `README.md` / `README.en.md` — 产品定位、流程、技术架构表
- `docs/x402-settlement.md` — x402 结算设计、环境变量、已知限制
- `docs/x402-first-run.md` — 第一次真实 x402 结算的完整日志与链上核验
- `docs/stage1-task-analysis-spec.md` — v1/v2 需求分析流水线的决策记录
- `evals/README.md` 与 `evals/reports/2026-09-04-v1-vs-v2.md` — v1/v2 结构化评测方法与结果
- `docs/retrospective-task-analysis-agent.zh.md` — 上述评测的复盘文章
- `docs/demo-script.md` / `docs/demo-voiceover.md` — 黑客松时期的旧版演示脚本（含已下线的 Cobo 集成，仅供历史参考，不要按其操作）
