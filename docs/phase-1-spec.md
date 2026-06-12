# Phase 1 实现规格：Schema 先行 + 最小确权闭环

> 用法：在 Claude Code 里进入 plan mode（按两次 Shift+Tab），把本文件作为输入，让它针对 **某一个工作单元** 先产出实现方案；你审过方案再批准执行。一次只做一个工作单元，做完跑验收测试 → 过 code-reviewer → commit → `/clear`，再做下一个。

## 1. 目标与唯一通过判据

证明 HireNet 的核心价值闭环在工程上成立：**一个人注册的知识资产被调用完成任务后，系统能正确地把收益记到这个人名下。**

Phase 1 通过 / 不通过的唯一硬判据（一个端到端测试）：

> 注册 1 个 `SkillAsset`（creator = 某用户）→ 触发 1 次会用到它的任务 → 断言 `royalty_ledger` 中出现一条记录，其 `amount`、`currency`、`creator_id`、`status='accrued'` 全部正确。

## 2. 范围

**做（in scope）：**
- 全部核心对象的 JSON Schema + 校验 + retry / fallback
- SQLite 持久化 + 三张表
- 注册 `SkillAsset` 的接口（含 `content_hash`）
- 调用打点：写 `agent_runs` + `royalty_ledger`
- 创作者收益页（最小可用）
- 把 HireNet 现有的一个 Agent 注册成第一个 `SkillAsset`（你当 creator）

**明确不做（out of scope，谁都不许顺手做）：**
- 真实支付 / 钱包 / 区块链 / 稳定币结算（Phase 1 的钱是账本数字）
- DID / 链上身份 / 加密签名（provenance 只用 sha256 哈希）
- 声誉系统、外部 Agent 注册、市场页
- 复杂的多资产分账算法（用写死的固定比例）
- eval set（Phase 2 才做）

## 3. 数据模型（crypto-ready，但纯链下）

所有金额字段一律是三元组 `amount` + `currency` + `chain`（`chain` 现在可为 null）。这样将来接 x402 / 稳定币时无需改 schema。

**`skill_assets`**
- `id`, `creator_id`, `name`, `description`
- `io_schema` (json)
- `price_amount`, `price_currency`, `price_chain`
- `split_rule` (json，例：`{"creator": 0.7, "platform": 0.3}`)
- `content_hash` (sha256，由 name + description + io_schema 等内容算出)
- `created_at`

**`agent_runs`**（在原计费表基础上扩展）
- `run_id`, `agent_name`, `caller_id`, `task_id`
- `input_tokens`, `output_tokens`, `llm_cost_usd`, `time_ms`, `success`
- `asset_ids` (json，本次用到的资产)
- `royalty_splits` (json，本次各方应得)
- `charge_amount`, `charge_currency`, `charge_chain`
- `payment_method`（枚举，Phase 1 恒为 `ledger_only`）
- `settlement_status`（枚举，Phase 1 恒为 `accrued`）
- `created_at`

**`royalty_ledger`**
- `id`, `run_id`, `creator_id`, `asset_id`
- `amount`, `currency`, `chain`
- `status`（`accrued` / `settled`，Phase 1 只产生 `accrued`）
- `created_at`

## 4. 要定义的 Schema（放 `app/schemas/`）

`Requirement`、`Task`、`ResourceDecision`（四维）、`JobDesign`、`CareerStrategy`、`MatchResult`、`SkillAsset`、`RoyaltySplit`。

每个都要有：schema 定义、校验函数、坏输入被拒的测试、坏 LLM 输出能 repair 或 fallback 的测试。

## 5. 工作单元（按顺序，每个一个会话，每个带验收测试）

**U1. 定义全部 schema + 校验 + retry / fallback。**
验收：单测——合法对象通过；非法对象被拒；模拟“模型返回坏 JSON”时能 repair 或 fallback，不崩。

**U2. 接 SQLite，建三张表 + DB 访问层。**
验收：写入再读出一致；重启进程后数据仍在（持久化测试）。

**U3. 注册 `SkillAsset` 接口（算 `content_hash`）。**
验收：注册成功落库；相同内容算出相同 hash、不同内容不同 hash。

**U4. 调用打点：执行时写 `agent_runs` + `royalty_ledger`，按 `split_rule` 分账。**
验收：单测——给定一次调用和一个 `split_rule`，断言生成的 `royalty_splits` 各方金额正确、之和等于 `charge_amount`（注意精度）。

**U5. 创作者收益页（最小）。**
验收：页面能正确显示某 creator 的累计 `accrued` 金额和调用次数。

**U6. 把现有一个 Agent（如 Job Design Agent）注册成第一个 `SkillAsset`，creator = 你。**
验收：触发一次会用到它的雇主任务，跑通第 1 节的端到端判据。

## 6. Phase 1 完成的定义（Definition of Done）

- 第 1 节的端到端测试通过。
- 所有工作单元的验收测试通过，且 `pytest` 全绿。
- 重启服务后数据不丢。
- 涉及钱 / 分账的代码已经过你逐行人审 + `code-reviewer` subagent review。
- 没有 mock 冒充真实实现（除被明确标注的 out-of-scope 部分）。
