# Phase 2 Spec — 把已证明的闭环升级成「能安全承载真实价值」

> 历史文档：黑客松时期编写，其中的 Cobo 集成已于 2026-09 移除；现行结算方案见 README「技术架构」。

> **精度：可执行 spec。** 这是下一步真正开工的文档，按 U1…U6 一个个走（plan → 执行 → 贴真实证据 → 读 diff → code-reviewer → 人审 → commit → `/clear`）。

---

## 命题

Phase 1 证明了闭环*成立*；Phase 2 让它*可信*。收掉三条红线——**多方分账、结算幂等、真实鉴权**——让闭环具备承载真实价值的资格。**本阶段仍然不动真钱**（真实结算是 Phase 3 / 黑客松轨）。

## 通过判据（硬）

注册一个 `split_rule` 含**多个 payee** 的资产 → 触发一次用到它的任务 →

- `royalty_ledger` 每个 payee **各一行**，金额整数基点，`status='accrued'`；
- 各 payee 行 + platform 份额**完全对账**（和 == charge，余数显式分配）；
- 全程身份由**真实（最小）鉴权**服务端派生，绝不客户端可控；
- **重试不产生重复行**（幂等）。

## 仍然守的边界（这些是 Phase 3 / Phase 4 的活，别拖进来）

- **钱不动**：仍 `ledger_only` / `accrued`。真实结算 = Phase 3。
- **仍单 asset**：一次调用一个资产。「多方分账」= 一个资产的收益分给多个 payee；**不是**一次任务用多个资产（那是 Phase 4 的 W2）。
- **auth 压到最小真实身份**，不做完整用户系统。

---

## 单元拆分

### U1 — 分账 schema + `resolve_split` 纯函数

- **目标**：把 `split_rule` 从「creator/platform 两方」推广成 payee 列表 `[{payee_id, bps}]`（含 platform）；`resolve_split(charge, split_rule) → [{payee_id, party, amount}]` 做成**唯一纯函数收口点**。
- **范围内**：bps 整数、`sum == 10000` 校验；整数基点分账；**余数显式分配**（舍入策略用枚举，如 `platform_absorbs`）；对账不变量（输出金额之和 == charge）；纯函数重测（含余数 / 极端 split / 多 payee 边界）。
- **不做**：DB、落库、wiring。
- **关键不变量**：纯、确定、对账。TIER-1。
- **证据**：`resolve_split` 单测全绿，含余数与极端 split 用例。

### U2 — `royalty_ledger` 推广成「一 payee 一行」

- **目标**：schema / DB 从「creator 一行」推广成「一 payee 一行」：`creator_id → payee_id` + 新增 `party` 列。
- **范围内**：DDL 改动 + 对已有 `accrued` 行的迁移；保留 CHECK 约束、整数金额；保持原子跨表写。
- **必须显式决定（别让它漂移）**：platform 份额现在是**进 ledger 成 `party='platform'` 一行**，还是**仍留在 `agent_runs.royalty_splits` JSON、ledger 只记需外付的 payee**？Phase 1 的决定是后者。这里若改成前者就是一次**决定反转**，要明写理由、过人审，不能默默改。
- **证据**：迁移后旧数据完好；从 DB 读出的行能过 U1 schema 校验（往返通过）。

### U3 — 把 `resolve_split` 接进记账路径 + 结算快照冻结

- **目标**：记账路径调 `resolve_split`，每个 payee 写一行；在 `agent_runs` 上**冻结 `applied_split` 快照**（保证可重放 / 可审计——split 规则日后变了，旧账仍能按当时规则解释）。
- **范围内**：单事务原子写（任一失败全回滚）；对账（payee 行 + platform == charge）在真实落库上成立。
- **不做**：多 asset（仍单 asset）。
- **证据**：trace 一次多 payee 调用——DB 里每 payee 一行、和对账、`applied_split` 快照在。

### U4 — 收益页按 payee 展示

- **目标**：`/creator/earnings` 从「creator 的收益」推广成「某 payee 自己的行」，仍按 `(currency, chain)` 分组、**绝不跨币种 / 链相加**。
- **范围内**：只读展示；身份仍服务端派生（U6 前用 stub，U6 接真鉴权）。
- **证据**：多 payee 数据下，每个 payee 只看到自己的、分组正确。

### U5 — 结算幂等

- **目标**：同一笔可计费 / 可结算事件不被重复记账。
- **范围内**：设计幂等键（明确「什么算同一个事件」）；让 `record_agent_run` 对重试天然安全。
- **铁规**：**只测正确的单次路径 + 重试安全；绝不写一个把双重计费固化下来的测试。**
- **关系**：黑客松轨里「每条结算行只结一次」是这条红线的一个聚焦切片；这里做的是产品级的通用版。
- **证据**：同一事件触发两次 → 仍只有一组行。

### U6 — 最小真实身份（auth）

- **目标**：把 `PHASE1_CREATOR_ID` / `PHASE1_CALLER_ID` stub 换成最小真实鉴权：认证态会话；creator / payee / caller 由**认证身份服务端派生**；收益页只显示本人；注册需要身份。
- **范围内**：最小可用身份，关掉 IDOR-stub 与 tampered-asset 两个已知缺口。
- **范围警告**：auth 极易膨胀成「做一整套用户系统」。**压到最小**；若仍过大，拆成独立 Phase 2.5，不要硬塞进这个单元。
- **证据**：登录态下只看到自己的收益；伪造他人身份被拒；注册带真实 creator。

---

## 横切要求（全 Phase 2 适用）

- 6 个单元全部触及 money / auth / provenance → **TIER-1，人逐行审**；①②③ 的安全关键改动加 **Codex 跨模型二审**。
- 整数基点、对账不变量、服务端身份——不松动。
- 每个单元独立走完整工作流，单元之间 `/clear`。

## 与黑客松轨的关系

U1–U4（多方分账，纯记账）产出多 payee 账本行，是黑客松 demo 的地基。黑客松的 Cobo 结算适配器是 **Phase 3 结算层的前切片**：贴在 ledger 之上、自带结算幂等、厂商无关——**别织进 U1–U4 的记账逻辑**。

## 收口后的已知缺口 → 去 Phase 3

- 真实结算（`accrued → settled`）。
- 外部参与（市场、注册、reputation）。
