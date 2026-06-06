> Phase 2 设计草案，未实现；本方案会取代 Phase 1 的 creator-only ledger 决定，须在 Phase 1 闭环验证完成后再考虑。

# 设计方案：SkillAsset 多方分账机制（revenue split）

> 本文件只是**设计方案**，不含实现。等用户逐行审过、批准后再写代码。
> 本区域属于 TIER1「钱 / 分账」红线代码，必须人审。

## Context（为什么做）

当前 `SkillAsset` 的分账用的是**固定字段** `split_rule = {"creator": 7000, "platform": 3000}`
（见 `app/schemas/royalty_split.json`、`validate_split_rule`、`record_agent_run`）。这套结构有两个问题，
和 HireNet 的灵魂（创作者能因知识资产持续、**可追溯、可对账**地分到钱）冲突：

1. **加不了第三方**：以后要给「推荐人 referrer」之类的新角色分成，就得改表结构和所有计算代码——不是加法式扩展。
2. **历史不可重现**：现在 `royalty_ledger` 只记 creator 一行、platform 份额塞在 `agent_runs.royalty_splits` JSON 里，
   且分账逻辑散在 `record_agent_run` 内联。一旦将来改了某资产的分成比例，无法保证旧交易能按当时规则重算复盘。

本方案把分账改成**列表式多方配置 + 一个纯函数 chokepoint + 结算时快照冻结**，让「加分成方」「改比例」都变成
**加法式、且绝不污染历史交易**。

> 现状是测试阶段、DB 无生产数据，可按 `db.py` 既有约定（删库重建）迁移，无需写数据迁移脚本。
> 本方案会**取代** Phase 1 早先「ledger 只记 creator、platform 进 JSON」的决定。

---

## 1. 数据模型

### 1.1 分账配置形状（取代现有 `royalty_split.json`）

挂在 `SkillAsset.split_rule` 上（保留字段名），新形状：

```json
{
  "rounding": "platform_absorbs",
  "shares": [
    { "party": "creator",  "bps": 7000 },
    { "party": "platform", "bps": 3000 }
  ]
}
```

- `shares`：**列表**，每项 `{ party: string, bps: integer }`。新增分成方（如 `{"party":"referrer","bps":...}`）= 往列表里加一项，**不改表/不改 schema**。
- `bps`：基点整数，1% = 100 bps；约束 `bps >= 0`。
- `rounding`：枚举，显式定义余数归属。Phase 落地仅实现 `"platform_absorbs"`（余数归 `party=="platform"` 的那一项）。
  字段设计成枚举 → 以后加 `"first_share_absorbs"` 等策略是加法式的。
- **party 是「角色」不是「账户」**：`party` 表达 creator/platform/referrer 这样的角色；具体收款账户（payee）在结算时映射（见 §3.3）。这样 `resolve_split` 能保持纯函数。

约束（在 schema + `validate_split_rule` 双层校验）：
- `shares` 非空；`party` 互不重复（否则 `platform_absorbs` 余数归属有歧义）。
- `sum(bps) == 10000`，**不满足直接抛错**，绝不默默分错。
- 若 `rounding == "platform_absorbs"`，`shares` 中必须存在 `party == "platform"`（否则余数无处安放，校验期就报错）。

### 1.2 平台级默认 + 单资产覆盖

- `SkillAsset.split_rule` 改为**可空**（`skill_asset.json` 里从 required 移出 / 允许 null）。
- 平台默认配置 = 一个模块常量，放新文件 `app/services/revenue_split.py`：

```python
PLATFORM_DEFAULT_SPLIT = {
    "rounding": "platform_absorbs",
    "shares": [
        {"party": "creator",  "bps": 7000},
        {"party": "platform", "bps": 3000},
    ],
}
```

- 解析时：`config = skill_asset["split_rule"] or PLATFORM_DEFAULT_SPLIT`。资产自带配置即覆盖默认。
- （不做 effective-dating / 版本表——明确范围外。默认值改了只影响「之后新建/未覆盖」资产，已快照的历史交易不受影响，见 §2.2。）

---

## 2. 接缝设计（seam）

### 2.1 唯一 chokepoint：纯函数 `resolve_split`

新文件 `app/services/revenue_split.py`。**所有需要分账的地方只走这一个函数**，禁止再在别处内联算分账。

```python
def resolve_split(skill_asset: dict, gross_amount: int) -> list[dict]:
    """把一笔 gross（整数·最小货币单位/分）按 skill_asset 的分账配置切给各方。
    纯函数：无 I/O、无副作用、完全确定性（同输入恒同输出）。
    返回有序列表，元素 {"party": str, "bps": int, "amount": int}，顺序同 shares。
    """
```

算法（全整数，零浮点）：
1. `config = skill_asset.get("split_rule") or PLATFORM_DEFAULT_SPLIT`。
2. 校验 `gross_amount` 是非负 `int`（拒 `bool`/`float`/负数 → `TypeError`/`ValueError`）。
3. 校验 config：`shares` 非空、`party` 唯一、各 `bps` 为非负 int、`sum(bps)==10000`；不满足 → 抛错（复用 `validate_split_rule`）。
4. 逐项地板除：`amount_i = gross_amount * bps_i // 10000`。
5. `remainder = gross_amount - sum(amount_i)`；按 `rounding` 把 remainder 加到吸收方
   （`platform_absorbs` → `party=="platform"` 那项）。`remainder` 恒满足 `0 <= remainder < len(shares)`。
6. **硬不变式**：`if sum(final amounts) != gross_amount: raise`（用显式 raise，不用 `assert`——`-O` 会被剥掉）。
7. 返回列表。

边界（与下方测试一一对应）：
- `gross=0` → 各方 0，余数 0，无需吸收方。
- 单方 100%（bps=10000）→ 该方拿全部，余数 0。
- 三方分账正常。
- `sum(bps) != 10000` → 抛错。
- 除不尽：`gross=100`，shares `creator 3333 / referrer 3333 / platform 3334`（和=10000）→ 33 / 33 / 33，余 1 归 platform → 33/33/34，和=100。

> 注：用户原文「333/333/334」之和=1000 不满足 `sum==10000`，会被规则拒。测试用等价的 3333/3333/3334 表达「三方近均分 + 余数」这一意图。

### 2.2 结算时快照冻结（applied_split）

结算（即 `record_agent_run`）时：
1. 调 `resolve_split(asset, gross)` 得到各方金额。
2. 把这份结果**整体快照**写进结算记录 `agent_runs.royalty_splits`（语义即 `applied_split`）：
   存「每方 party + bps + 已算好的 amount」+ 该笔的 `currency` / `chain` / `gross`。
   **存的是算好的数值，不是指向 SkillAsset 当前配置的引用。**
3. 据快照，为**每一方**写一行 `royalty_ledger`（见 §3）。

目的（用户硬约束）：以后改 `split_rule` 或改平台默认，只影响**未来**交易；
历史交易能凭快照原样重算、对账。

### 2.3 角色 → 收款账户映射（结算层，非纯函数）

`resolve_split` 只产出角色金额。结算层把角色映射到具体 payee：
- `creator` → `skill_asset.creator_id`
- `platform` → 平台账户 stub（如 config `PLATFORM_PAYEE_ID`，默认 `"hirenet_platform"`）
- 其它角色（referrer 等）→ Phase 暂无身份来源；若配置里出现而无法映射，结算层报错（不静默丢钱）。

把「纯计算」与「身份映射（有副作用/查配置）」分开，是保证 `resolve_split` 可穷举测试的关键。

---

## 3. 受影响文件与改动（ripple）

| 文件 | 改动 |
|---|---|
| `app/schemas/royalty_split.json` | 重写为 `{rounding, shares:[{party,bps}]}` 列表形状 |
| `app/schemas/skill_asset.json` | `split_rule` 改为可空（从 required 移出，允许 null）|
| `app/services/validation.py` | `validate_split_rule` 改为列表版：非空、party 唯一、bps 非负 int、和=10000、`platform_absorbs` 须含 platform 项 |
| `app/services/revenue_split.py`（新）| `PLATFORM_DEFAULT_SPLIT` + 纯函数 `resolve_split` |
| `app/services/agent_run_recording.py` | 删除内联 creator/platform 算法，改调 `resolve_split`；写 applied_split 快照；按快照对每一方写一行 ledger；做角色→payee 映射 |
| `app/storage/royalty_ledger.py` + `app/storage/db.py` | `royalty_ledger` 泛化为「每方一行」：新增 `party` 列（角色）；现 `creator_id` 语义改为 `payee_id`（收款账户）。`summarize_creator_earnings` 改按 `payee_id`（+可选 `party`）聚合 |
| `app/storage/agent_runs.py` | `royalty_splits` 仍是 JSON 列，存 applied_split 快照（结构变化，无需改列）|
| 现有 `tests/test_agent_run_recording.py` / `test_creator_earnings.py` | 跟随新 ledger 形状与新 split 配置更新 |

> U5 收益页（`app/routes/earnings.py` + 模板）只要 `summarize_creator_earnings` 的返回口径不变（按 payee 聚合 accrued），页面几乎不动。

---

## 4. 明确不做（范围边界，照用户）

- ❌ 后台编辑 UI
- ❌ 生效时间调度 / 策略版本化（effective-dating）
- ❌ 按交易量分档、条件分成、单笔协商覆盖
- ❌ 真实支付 / 链上结算（沿用 Phase 1：`ledger_only` / `accrued`）

数据结构已为以上预留**加法式**扩展空间（加 party 项、加 rounding 枚举值、将来加版本表都不推翻现表）。

---

## 5. 测试（确定性，零网络 / 零 LLM / 零外部依赖）

新文件 `tests/test_revenue_split.py`，对 `resolve_split` 穷举：
- `gross=0` → 各方 0。
- 单方 100%（bps=10000）→ 该方拿满。
- 三方分账，整除场景金额正确、和=gross。
- `sum(bps) != 10000` → 抛错（断言异常类型与信息）。
- 除不尽余数：`gross=100`、3333/3333/3334 → 33/33/34，余数归 platform，和=100。
- 补充：负数 / float / bool 的 `gross` 被拒；`platform_absorbs` 但无 platform 项 → 抛错；party 重复 → 抛错；resolve 后 `sum(amounts)==gross` 不变式对随机若干 (gross, 配置) 成立。

回归：`record_agent_run` / earnings 相关测试更新后 `pytest` 全绿。

## 6. 验收方式

1. `pytest tests/test_revenue_split.py -v` 全过（含上述全部边界）。
2. `pytest` 全绿（含被改动的 U4/U5 测试）。
3. 人工抽查一条结算记录：`agent_runs.royalty_splits` 是冻结快照；`royalty_ledger` 每方一行且金额之和 == `charge_amount`。
4. 改一次 `split_rule` 后跑新交易，旧交易的 ledger/快照金额不变（历史可重现）。

---

## 待用户确认的几个取舍（我已选默认，不同意请指出）

1. **ledger 粒度**：采「每方一行」（含 platform、referrer），取代旧「只记 creator」。这样每个分成方都有可对账的 accrued 余额。
2. **`creator_id` 列**：泛化重命名为 `payee_id`，并加 `party` 列。（测试阶段直接重建库。）
3. **rounding**：先只实现 `platform_absorbs`，前提是配置含 `platform` 角色；字段设计成枚举留扩展。
