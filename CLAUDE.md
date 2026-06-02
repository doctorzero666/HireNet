# HireNet — 项目宪法（CLAUDE.md）

> 这个文件是 Claude Code 每次启动自动读入的项目规则。最重要的规则放在最前面。

## 项目是什么（先理解 why，再写 code）

HireNet 是一个 AI 时代的 Human-Agent 劳动力网络，但它真正的护城河不是“任务市场”，而是 **知识资产的确权与版税分配**：

- 一个人可以把自己的技能/经验封装成可被调用的 skill 或 agent（= 一个 `SkillAsset`）。
- 当这个资产被调用、完成任务、创造价值时，系统要把收益按约定分给它的创作者（`creator`）。
- “任务怎么被完成（Agent / Human / Hybrid）”是地基；“创作者怎么因为知识贡献而持续获得分成”是灵魂。

写任何功能时，如果一个设计削弱了“创作者能因其知识资产获得可追溯的收益”这条主线，就是走偏了——停下来问用户。

## TIER 1：硬规则（每次动手前检查，违反即视为工作失败）

1. 所有 LLM 输出必须经过 schema 校验后才能使用。优先用 `schema validation + retry-with-repair + fallback`，而不是裸 `json.loads`。
2. 涉及钱、分账（royalty）、鉴权（auth）、provenance 哈希的代码，必须等用户逐行审过才能合并。这些区域不存在“快速通过”。
3. 禁止用 mock 数据或假实现冒充真实功能。如果某部分尚未真正实现，显式写 `# TODO:` 并在回复里明确告诉用户哪些是假的。
4. 改动范围不许超出当前任务。发现需要顺手改别处，先停下来问用户，不要自作主张。
5. 一个 commit 只做一件能独立验收的事。
6. 报告进度时给证据，不要只说“完成了 / 测试通过了”。优先贴出你运行的命令和它的真实输出。
7. 非平凡任务（>3 步、涉及架构决策、跨多文件）先进 plan mode 写方案，等用户批准再执行。

## TIER 2：工作方式

- 一个会话只解决一个功能单元，干完用户会 `/clear` 再开下一个。不要在一个会话里跨越太多职责。
- 每个功能单元都要配测试；没有测试的功能视为未完成。
- 不确定就问，不要在多种解读之间默默选一种。
- 简单优先：能用直白的函数 / workflow 解决的，不要上复杂的多 agent 编排。

## 技术栈与目录约定

- 后端：Python + Flask；持久化：SQLite（Phase 1 起）。
- 测试：pytest。
- 目录结构：
  - `app/routes/` — Flask 路由（保持薄，业务逻辑别塞这里）
  - `app/agents/` — 各 Agent 逻辑
  - `app/schemas/` — 所有 JSON Schema 与校验
  - `app/services/` — 业务逻辑（含计费 / 分账 / provenance）
  - `app/storage/` — DB 访问层
  - `app/templates/` — 前端页面
  - `tests/` — 测试
  - `docs/` — 文档与各 Phase spec

## 常用命令

- 安装依赖：`pip install -r requirements.txt`
- 跑测试：`pytest`
- 起服务：`python wsgi.py`
- 健康检查：`GET /api/health` 应返回 200

## 领域词汇（统一用词，别造新词）

- `SkillAsset` — 一个人注册的、可被调用的知识资产（skill 或 agent）。
- `creator` — `SkillAsset` 的创作者 / 负责人，分成的收款方。
- `ResourceDecision` — 四维资源决策：执行方(Agent/Human/Hybrid) × 支付方式 × 用哪些资产 × 结算时机。
- `agent_runs` — 每次调用的计费 + 审计记录。
- `RoyaltyLedger` — 分成账本，每条记录“该给某 creator 多少钱”。
- `content_hash` — 注册资产时对其内容算的 sha256，用作 provenance 凭证。
- 金额一律存为三元组：`amount` + `currency` + `chain`（即使现在 chain 为空）。
- `settlement_status` — `accrued`（已计提，钱是账本数字）/ `settled`（已真实结算）。

## 当前阶段

当前在 **Phase 1**：schema 先行 + 最小确权闭环。详见 `docs/phase-1-spec.md`。

Phase 1 的唯一通过判据：注册 1 个 `SkillAsset` → 触发 1 次任务 → `royalty_ledger` 出现 amount / currency / creator_id / status 全部正确的分成记录。
