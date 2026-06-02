# Phase 1 Spec — Schema 先行 + 最小确权闭环

> 状态：骨架，细节待补充。

## 唯一通过判据（不可放宽）

注册 1 个 `SkillAsset` → 触发 1 次任务 → `royalty_ledger` 出现以下字段全部正确的记录：

| 字段 | 要求 |
|------|------|
| `amount` | 数值，非零 |
| `currency` | 字符串（e.g. `"CNY"` / `"USD"`） |
| `creator_id` | 对应 `SkillAsset` 的创作者 ID |
| `status` | `"accrued"` 或 `"settled"` |

## 核心交付物

### 数据模型（SQLite — Phase 1 首次引入持久化）

- [ ] `skill_assets` 表
- [ ] `agent_runs` 表（计费 / 审计记录）
- [ ] `royalty_ledger` 表

所有金额字段用三元组：`amount` + `currency` + `chain`（chain 现在为空字符串）。

### 最小 API 闭环

- [ ] `POST /api/skills/register` — 注册 SkillAsset，返回 `skill_id` + `content_hash`
- [ ] `POST /api/skills/invoke` — 触发调用，写 `agent_runs`，计提 royalty
- [ ] `GET /api/royalties` — 查询 `royalty_ledger`（至少返回 creator_id / amount / currency / status）

### Schema 校验（TIER 1 硬规则，不可跳过）

- [ ] `app/schemas/skill_asset.json`
- [ ] `app/schemas/agent_run.json`
- [ ] `app/schemas/royalty_entry.json`
- [ ] 所有 LLM 输出经过 `schema validate + retry-with-repair + fallback`，禁止裸 `json.loads`

## TODO：设计细节待补充

- [ ] 金额计算规则（分成比例、如何从调用费推算 royalty）
- [ ] `content_hash` 计算方式（sha256 of 哪些字段？）
- [ ] `ResourceDecision` 四维决策与 royalty 计提的联动
- [ ] 结算触发时机（立即 `accrued` vs 批量 `settled`）
- [ ] auth：creator 如何证明自己是资产所有者
