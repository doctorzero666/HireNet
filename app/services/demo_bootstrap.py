"""
Demo bootstrap：在 create_app 时预填一份"数据分析助手"SkillAsset（创作者 zhao_design）
以及 li_boss 调用它的两条历史记录（一条 settled+tx_hash、一条 accrued），让 Demo 现场
一上来就能在 zhao_design 的收益账本看到内容、ExecutionPage 也能展示真实链上 tx_hash。

⚠️ 这里直接写 royalty_ledger — TIER 1 §2 / §3 双重红线：
  - 复用既有 U4 / 状态机路径（record_agent_run + claim_settlement + confirm_settlement），
    不绕过任何 split 校验、不重写 ledger 逻辑。
  - 预设 tx_hash / settlement_method 均带 "demo-preset" 前缀，明显可辨，绝不冒充
    anvil / cobo / mock 任何真实结算凭证 (CLAUDE.md §3)。
  - 仅在 create_app 的 `not TESTING` 分支调用 — 532 个测试都通过 conftest 的
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

# zhao_design 的数据分析 Agent — 字段集与 U3 注册路径接受的形状一致；split_rule 三方
# 求和 = 10000 bp（U2 校验）。price 用 USD 基点（$40 = 4000 bp/单位时长），与
# Pact modal 的"$40 / 小时"显示一致。
#
# endpoint_url 指向本地 data_analysis MCP（:5003）—— Agent 世界靠它把这张
# 卡显示为"🔗 MCP 已连接"。注意：升级既有 .hirenet/hirenet.db 时旧行的
# endpoint_url 为 None，bootstrap 的 content_hash + expected 字段都不会匹配，
# 会再插一条；想干净启动请 `rm ~/.hirenet/hirenet.db` 一次。content_hash 是
# provenance 凭证（CLAUDE.md TIER 1 §2），不在 bootstrap 里 in-place 改写。
# Two demo Agent wallets — each preset Agent gets its own recipient address
# so the Sepolia path actually moves ETH between distinct accounts (no more
# self-transfers). Addresses below are throwaway test wallets; the private
# keys live ONLY on the operator's machine (we never need them server-side
# — only the Sepolia FROM_ADDRESS key signs txs).
#
# TODO(operator): regenerate via `cast wallet new` and paste the address
# string in here. The placeholders below are valid EIP-55 EVM addresses
# (well-known Anvil accounts #1 and #2) so the schema accepts the row, but
# they are NOT controlled by us — replace before any real Sepolia demo.
DEMO_DATA_ANALYST_WALLET = "0xf2E28A84e8d51ca87CB50768a0Ebe0E29F53F7B7"
DEMO_SEO_AGENT_WALLET    = "0x03aaE40b6FCA16CDB48b66d4841e99eEF588B78a"


DEMO_DATA_ANALYST: dict = {
    "name": "数据分析助手",
    "description": (
        "zhao_design 的数据分析 Agent：上传业务数据，自动产出关键指标、趋势"
        "与异常告警，附简明洞察摘要供决策参考。"
    ),
    "type": "agent",
    "endpoint_url": "http://localhost:5003",
    "io_schema": {
        "input": {
            "dataset_url": "string",        # CSV / Parquet URL
            "questions": "array",            # 关心的问题
        },
        "output": {
            "metrics": "array",              # 关键指标
            "insights": "array",             # 摘要洞察
        },
    },
    "price_amount": 4000,        # $40 / 单位时长，USD 基点
    "price_currency": "USD",
    "price_chain": None,
    "split_rule": {"creator": 7000, "platform": 2000, "tax": 1000},
    "wallet_address": DEMO_DATA_ANALYST_WALLET,
}


# zhang_ai 的 SEO 优化 Agent —— endpoint_url 复用真实跑着的 customer_service MCP
# (:5002)。endpoint 是真的；不算 CLAUDE.md TIER 1 §3 的"假实现冒充真实功能"。
# 价格 $25 / 单位时长。
DEMO_SEO_AGENT: dict = {
    "name": "SEO 优化 Agent",
    "description": (
        "zhang_ai 的 SEO Agent：输入目标关键词与页面 URL，输出标题、Meta 描述、"
        "H1/H2 结构与内链建议，照抄即用。"
    ),
    "type": "agent",
    "endpoint_url": "http://localhost:5002",
    "io_schema": {
        "input": {
            "keywords": "array",
            "page_url": "string",
        },
        "output": {
            "title": "string",
            "meta_description": "string",
            "structure_suggestions": "array",
        },
    },
    "price_amount": 2500,
    "price_currency": "USD",
    "price_chain": None,
    "split_rule": {"creator": 7000, "platform": 2000, "tax": 1000},
    "wallet_address": DEMO_SEO_AGENT_WALLET,
}

# (Agent 数据, 创作者 id) 元组列表 —— bootstrap_demo_extra_assets 直接迭代。
# 数据分析 Agent 不在这里（它由 bootstrap_demo_data_analyst_asset 单独管，因为还要
# 绑历史调用）。
_DEMO_EXTRA_ASSETS: list[tuple[dict, str]] = [
    (DEMO_SEO_AGENT, "zhang_ai"),
]

# 固定 task_id — bootstrap_demo_runs 用它判幂等，重启不会重复插。
_SETTLED_TASK_ID = "demo-data-task-settled"
_ACCRUED_TASK_ID = "demo-data-task-accrued"

# 预设 tx_hash 明显可辨，绝不冒充真实链上凭证（CLAUDE.md §3）。
_DEMO_TX_HASH = "demo-preset-0xa3f9b8c7d2e15e6f4c1a8b9d3e7f0a1b2c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f"
_DEMO_SETTLEMENT_METHOD = "demo-preset"


def bootstrap_demo_data_analyst_asset(db_path: str, creator_id: str = "zhao_design") -> str:
    """幂等注册 zhao_design 的数据分析 Agent，返回 asset_id。

    复用 bootstrap_job_design_asset 的"全字段匹配再复用"模式 — content_hash 只覆盖
    内容字段，经济条款（price / split_rule）必须额外匹配；否则被篡改过的同内容资产
    会被误选，下次结算金额就改了。
    """
    content_hash = compute_content_hash(
        name=DEMO_DATA_ANALYST["name"],
        description=DEMO_DATA_ANALYST["description"],
        asset_type=DEMO_DATA_ANALYST["type"],
        io_schema=DEMO_DATA_ANALYST["io_schema"],
        endpoint_url=DEMO_DATA_ANALYST.get("endpoint_url"),
    )
    expected = {
        "content_hash": content_hash,
        "creator_id": creator_id,
        "name": DEMO_DATA_ANALYST["name"],
        "type": DEMO_DATA_ANALYST["type"],
        "price_amount": DEMO_DATA_ANALYST["price_amount"],
        "price_currency": DEMO_DATA_ANALYST["price_currency"],
        "price_chain": DEMO_DATA_ANALYST.get("price_chain"),
        "split_rule": DEMO_DATA_ANALYST["split_rule"],
        "endpoint_url": DEMO_DATA_ANALYST.get("endpoint_url"),
        # wallet_address feeds the Sepolia recipient — a swap silently
        # redirects ETH, so include it in the "still the same asset" match.
        "wallet_address": DEMO_DATA_ANALYST.get("wallet_address"),
    }
    for existing in list_skill_assets(db_path):
        if all(existing.get(key) == value for key, value in expected.items()):
            return existing["id"]

    result = register_skill_asset(db_path, dict(DEMO_DATA_ANALYST), creator_id)
    return result["skill_id"]


def bootstrap_demo_extra_assets(db_path: str) -> list[str]:
    """幂等注册除主 Agent 外的预设 Agent。返回新注册或复用的 asset_id 列表。

    复用 bootstrap_demo_data_analyst_asset 的"内容字段哈希 + 经济条款全字段"匹配
    模式 —— name/desc/io_schema/endpoint_url 任一改动都会被 content_hash 反映，
    price/split_rule 改动则被 expected dict 拦下。任一项被篡改就视为新资产，
    避免静默替换让 Demo 的分账金额改变。
    """
    asset_ids: list[str] = []
    for asset_dict, creator_id in _DEMO_EXTRA_ASSETS:
        content_hash = compute_content_hash(
            name=asset_dict["name"],
            description=asset_dict["description"],
            asset_type=asset_dict["type"],
            io_schema=asset_dict["io_schema"],
            endpoint_url=asset_dict.get("endpoint_url"),
        )
        expected = {
            "content_hash": content_hash,
            "creator_id": creator_id,
            "name": asset_dict["name"],
            "type": asset_dict["type"],
            "price_amount": asset_dict["price_amount"],
            "price_currency": asset_dict["price_currency"],
            "price_chain": asset_dict.get("price_chain"),
            "split_rule": asset_dict["split_rule"],
            "endpoint_url": asset_dict.get("endpoint_url"),
            # Same posture as the data-analyst bootstrap: a wallet swap
            # silently redirects on-chain settlement, so include it in the
            # idempotency match.
            "wallet_address": asset_dict.get("wallet_address"),
        }
        existing = next(
            (a for a in list_skill_assets(db_path)
             if all(a.get(key) == value for key, value in expected.items())),
            None,
        )
        if existing is not None:
            asset_ids.append(existing["id"])
            continue
        result = register_skill_asset(db_path, dict(asset_dict), creator_id)
        asset_ids.append(result["skill_id"])
    return asset_ids


def bootstrap_demo_runs(db_path: str, asset_id: str, caller_id: str = "li_boss") -> None:
    """幂等预填两条 agent_run + royalty_ledger 历史记录。

    幂等判据：caller_id 名下已有 task_id == _SETTLED_TASK_ID 的 agent_run 即跳过。
    任意一条都不补写 — 任一条存在说明 bootstrap 跑过，避免半截覆盖。
    """
    existing = list_agent_runs_by_caller(db_path, caller_id)
    if any(run["task_id"] == _SETTLED_TASK_ID for run in existing):
        return

    # 1. 已结算单：1 小时单价 → charge_amount = price_amount * 1 = 4000 (USD 基点)
    # 走完整状态机：accrued → settling → settled。confirm_settlement 同事务里
    # 翻 royalty_ledger 三行（creator / platform / tax）为 settled，invariant 保持。
    settled = record_agent_run(
        db_path,
        agent_name=DEMO_DATA_ANALYST["name"],
        caller_id=caller_id,
        task_id=_SETTLED_TASK_ID,
        asset_id=asset_id,
        charge_amount=DEMO_DATA_ANALYST["price_amount"],
        charge_currency=DEMO_DATA_ANALYST["price_currency"],
        charge_chain=DEMO_DATA_ANALYST.get("price_chain"),
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

    # 2. 待结算单：2 小时单价 → charge_amount = 8000
    record_agent_run(
        db_path,
        agent_name=DEMO_DATA_ANALYST["name"],
        caller_id=caller_id,
        task_id=_ACCRUED_TASK_ID,
        asset_id=asset_id,
        charge_amount=DEMO_DATA_ANALYST["price_amount"] * 2,
        charge_currency=DEMO_DATA_ANALYST["price_currency"],
        charge_chain=DEMO_DATA_ANALYST.get("price_chain"),
        success=True,
    )
