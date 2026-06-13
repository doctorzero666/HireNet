"""
Demo bootstrap：在 create_app 时预填一份"客服话术生成器"SkillAsset（创作者 zhang_ai）
以及 li_boss 调用它的两条历史记录（一条 settled+tx_hash、一条 accrued），让 Demo 现场
一上来就能在 zhang_ai 的收益账本看到内容、ExecutionPage 也能展示真实链上 tx_hash。

⚠️ 这里直接写 royalty_ledger — TIER 1 §2 / §3 双重红线：
  - 复用既有 U4 / 状态机路径（record_agent_run + claim_settlement + confirm_settlement），
    不绕过任何 split 校验、不重写 ledger 逻辑。
  - 预设 tx_hash / settlement_method 均带 "demo-preset" 前缀，明显可辨，绝不冒充
    anvil / cobo / mock 任何真实结算凭证 (CLAUDE.md §3)。
  - 仅在 create_app 的 `not TESTING` 分支调用 — 526 个测试都通过 conftest 的
    `TESTING=True` 路径跳过本模块，不会被预设数据污染。
"""
from app.services.agent_run_recording import record_agent_run
from app.services.skill_registration import compute_content_hash, register_skill_asset
from app.storage.agent_runs import (
    claim_settlement,
    confirm_settlement,
    list_agent_runs_by_caller,
)
from app.storage.skill_assets import list_skill_assets

# zhang_ai 的客服话术 Agent — 字段集与 U3 注册路径接受的形状一致；split_rule 三方
# 求和 = 10000 bp（U2 校验）。price 用 USD 基点（$30 = 3000 bp/单位时长），与
# Pact modal 的"$30 / 小时"显示一致。
DEMO_CS_AGENT: dict = {
    "name": "客服话术生成器",
    "description": (
        "zhang_ai 创作的客服话术生成 Agent：输入业务场景、品牌语气、常见客诉，"
        "输出可直接复用的客服回应模板与升级路径建议。"
    ),
    "type": "agent",
    "io_schema": {
        "input": {
            "scenario": "string",          # 业务场景 / 客诉类型
            "brand_tone": "string",         # 品牌语气
            "common_complaints": "array",   # 常见客诉清单
        },
        "output": {
            "scripts": "array",             # 标准话术
            "escalation_paths": "array",    # 升级路径
        },
    },
    "price_amount": 3000,        # $30 / 单位时长，USD 基点
    "price_currency": "USD",
    "price_chain": None,
    "split_rule": {"creator": 7000, "platform": 2000, "tax": 1000},
}

# 固定 task_id — bootstrap_demo_runs 用它判幂等，重启不会重复插。
_SETTLED_TASK_ID = "demo-cs-task-settled"
_ACCRUED_TASK_ID = "demo-cs-task-accrued"

# 预设 tx_hash 明显可辨，绝不冒充真实链上凭证（CLAUDE.md §3）。
_DEMO_TX_HASH = "demo-preset-0xa3f9b8c7d2e15e6f4c1a8b9d3e7f0a1b2c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f"
_DEMO_SETTLEMENT_METHOD = "demo-preset"


def bootstrap_demo_cs_asset(db_path: str, creator_id: str = "zhang_ai") -> str:
    """幂等注册 zhang_ai 的客服话术 Agent，返回 asset_id。

    复用 bootstrap_job_design_asset 的"全字段匹配再复用"模式 — content_hash 只覆盖
    内容字段，经济条款（price / split_rule）必须额外匹配；否则被篡改过的同内容资产
    会被误选，下次结算金额就改了。
    """
    content_hash = compute_content_hash(
        name=DEMO_CS_AGENT["name"],
        description=DEMO_CS_AGENT["description"],
        asset_type=DEMO_CS_AGENT["type"],
        io_schema=DEMO_CS_AGENT["io_schema"],
        endpoint_url=DEMO_CS_AGENT.get("endpoint_url"),
    )
    expected = {
        "content_hash": content_hash,
        "creator_id": creator_id,
        "name": DEMO_CS_AGENT["name"],
        "type": DEMO_CS_AGENT["type"],
        "price_amount": DEMO_CS_AGENT["price_amount"],
        "price_currency": DEMO_CS_AGENT["price_currency"],
        "price_chain": DEMO_CS_AGENT.get("price_chain"),
        "split_rule": DEMO_CS_AGENT["split_rule"],
        "endpoint_url": DEMO_CS_AGENT.get("endpoint_url"),
    }
    for existing in list_skill_assets(db_path):
        if all(existing.get(key) == value for key, value in expected.items()):
            return existing["id"]

    result = register_skill_asset(db_path, dict(DEMO_CS_AGENT), creator_id)
    return result["skill_id"]


def bootstrap_demo_runs(db_path: str, asset_id: str, caller_id: str = "li_boss") -> None:
    """幂等预填两条 agent_run + royalty_ledger 历史记录。

    幂等判据：caller_id 名下已有 task_id == _SETTLED_TASK_ID 的 agent_run 即跳过。
    任意一条都不补写 — 任一条存在说明 bootstrap 跑过，避免半截覆盖。
    """
    existing = list_agent_runs_by_caller(db_path, caller_id)
    if any(run["task_id"] == _SETTLED_TASK_ID for run in existing):
        return

    # 1. 已结算单：1 小时单价 → charge_amount = price_amount * 1 = 3000 (USD 基点)
    # 走完整状态机：accrued → settling → settled。confirm_settlement 同事务里
    # 翻 royalty_ledger 三行（creator / platform / tax）为 settled，invariant 保持。
    settled = record_agent_run(
        db_path,
        agent_name=DEMO_CS_AGENT["name"],
        caller_id=caller_id,
        task_id=_SETTLED_TASK_ID,
        asset_id=asset_id,
        charge_amount=DEMO_CS_AGENT["price_amount"],
        charge_currency=DEMO_CS_AGENT["price_currency"],
        charge_chain=DEMO_CS_AGENT.get("price_chain"),
        success=True,
    )
    if not claim_settlement(db_path, settled["run_id"]):
        # 理论不会发生 — record_agent_run 刚把状态写成 accrued。出现即说明有
        # 并发污染，宁可让 bootstrap 失败暴露，也不静默吞掉。
        raise RuntimeError(
            f"demo bootstrap: failed to claim settlement for {settled['run_id']!r}"
        )
    flipped = confirm_settlement(
        db_path,
        settled["run_id"],
        tx_hash=_DEMO_TX_HASH,
        method=_DEMO_SETTLEMENT_METHOD,
    )
    if flipped != 3:
        raise RuntimeError(
            f"demo bootstrap: expected 3 ledger rows flipped, got {flipped}"
        )

    # 2. 待结算单：2 小时单价 → charge_amount = 6000
    record_agent_run(
        db_path,
        agent_name=DEMO_CS_AGENT["name"],
        caller_id=caller_id,
        task_id=_ACCRUED_TASK_ID,
        asset_id=asset_id,
        charge_amount=DEMO_CS_AGENT["price_amount"] * 2,
        charge_currency=DEMO_CS_AGENT["price_currency"],
        charge_chain=DEMO_CS_AGENT.get("price_chain"),
        success=True,
    )
