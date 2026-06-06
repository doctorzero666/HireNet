# 接真实支付前必做（红线清单）

> Phase 1 的钱是**账本数字**（`settlement_status='accrued'`、`payment_method='ledger_only'`），
> 没有真实资金流动。下列各项在「接入任何真实支付 / 钱包 / 链上结算」之前**必须**逐条解决，
> 否则会造成真实资金错算或重复支付。每项注明发现来源与代码位置。

## 必做项

### R1. 结算幂等键（settlement idempotency）— 来自 U6 code-review
- **问题**：当前计费路径「每次成功调用计一次费」，无幂等键。`record_agent_run` 每次生成新 `run_id`，
  没有按业务身份去重。同一雇主重复提交 / 浏览器重试 `POST /api/analyze/quick`（或 `/api/analyze/decide`）
  会写入第二条 `royalty_ledger` 行，导致 creator 被重复计提。
- **Phase 1 现状（已知并接受）**：明确接受「每次成功调用 = 一次计费」，不固化为幂等；账本仅 accrued，无真实资金，
  风险可控。已加测试 `test_two_human_tasks_bill_per_task` 固化「每 task 各计一次」的预期语义。
- **接真实支付前必做**：引入结算幂等键——例如由 task 身份（caller_id + task_id + asset_id + 计费周期等）
  派生确定性 `run_id`，并对 `agent_runs` / `royalty_ledger` 加 UNIQUE 约束，保证同一笔逻辑结算只落一次。
- **代码位置**：`app/services/asset_bootstrap.py` `build_job_design_recorder.on_design`（TODO ①）；
  `app/services/agent_run_recording.py::record_agent_run`；`app/storage/agent_runs.py::_build_agent_run_row`。
- **归属阶段**：作为 Phase 2 独立工作单元，现在不做。

## 观察项（非红线，但接支付前应复核）

### O1. bootstrap 并发安全 — 来自 U6 code-review
- check-then-insert，无 `UNIQUE(content_hash)` 兜底；多进程（gunicorn worker）同时首启可能重复插入资产。
- Phase 1 单进程启动安全。多 worker 部署前用 DB 唯一约束 / 启动锁解决。
- 代码位置：`app/services/asset_bootstrap.py::bootstrap_job_design_asset`（TODO ③）。

### O2. bootstrap 资产匹配对类型漂移脆弱 — 来自 U6 code-review
- 复用判定用 `==` 全字段比较，依赖 `list_skill_assets` 把 `split_rule` 解为 dict、`price_amount` round-trip 为 int。
  若存储序列化方式将来改变，匹配会**静默失败**→ 注册重复资产，而非报错。
- 代码位置：`app/services/asset_bootstrap.py::bootstrap_job_design_asset` 的 `expected` 比较（TODO ⑤）。

### O3. 无真实鉴权 — Phase 1 已知延后
- `creator_id` / `caller_id` 来自服务端 stub 配置；任何人都能经 `register_skill_asset` 注册任意经济条款的资产
  （bootstrap 已能避开篡改资产、选中正确资产，但被篡改的行仍留在表中）。真实 auth 是 Phase 2。
