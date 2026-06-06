"""
U6: bootstrap the first SkillAsset and wire its invocation to billing.

This module does NOT introduce any new royalty / ledger / schema mechanism.
It only "wires" existing Phase 1 parts together:
  - registers HireNet's existing Job Design Agent as the first SkillAsset via the
    U3 registration path (`register_skill_asset` — server-side creator_id,
    server-computed content_hash);
  - hands routes a recorder closure that, on each successful job-design generation,
    bills one invocation through the U4 path (`record_agent_run` — single asset,
    creator-only royalty_ledger row, platform share in agent_runs.royalty_splits JSON).

Nothing here recomputes splits or touches the DB schema.
"""
from app.services.agent_run_recording import record_agent_run
from app.services.skill_registration import compute_content_hash, register_skill_asset
from app.storage.skill_assets import get_skill_asset, list_skill_assets

# The existing Job Design Agent (app/agents/job_design.py) described as a SkillAsset.
# Field set is exactly what the U3 registration path accepts; split_rule keeps the
# existing fixed-field shape unchanged (creator/platform basis points summing to 10000).
JOB_DESIGN_ASSET: dict = {
    "name": "Job Design Agent",
    "description": (
        "HireNet 的岗位设计 Agent：基于澄清后的真实需求生成「去水」的岗位定义，"
        "并对原始模糊描述与最终 JD 做对比，给出 JD 水分评分。"
    ),
    "type": "agent",
    "io_schema": {
        "input": {
            "requirement": "object",          # 结构化需求
            "task": "object",                  # 需要人来做的具体任务
            "original_description": "string",  # 原始描述，用于水分对比
        },
        "output": {
            "job_title": "string",
            "core_responsibilities": "array",
            "required_skills": "array",
            "nice_to_have_skills": "array",
            "experience_range": "object",
            "salary_range": "object",
            "work_type": "string",
            "water_score": "integer",
        },
    },
    "price_amount": 100,
    "price_currency": "USD",
    "price_chain": None,
    "split_rule": {"creator": 7000, "platform": 3000},
}


def bootstrap_job_design_asset(db_path: str, creator_id: str) -> str:
    """Idempotently register the Job Design Agent as a SkillAsset; return its id.

    Idempotent across restarts, but it ONLY reuses an asset that matches the Job
    Design bootstrap's FULL key config — not just content_hash. content_hash (per
    U3, unchanged here) covers only name/description/type/io_schema/endpoint_url,
    NOT the economic terms (price / split_rule / creator). So matching on
    content_hash alone would let an unrelated asset with the same content but a
    tampered price (e.g. price_amount=999, split_rule 10000/0) get selected after
    a restart — silently changing what the Job Design Agent bills.

    We therefore require content_hash AND creator_id AND name AND type AND the full
    pricing triple AND split_rule AND endpoint_url to all match. An asset that
    collides on content_hash but differs on any economic term is ignored; we keep
    scanning, and only if no exact match exists do we register a fresh, fully
    matching asset via the U3 path (which sets the server-side creator_id and
    recomputes content_hash itself).
    """
    content_hash = compute_content_hash(
        name=JOB_DESIGN_ASSET["name"],
        description=JOB_DESIGN_ASSET["description"],
        asset_type=JOB_DESIGN_ASSET["type"],
        io_schema=JOB_DESIGN_ASSET["io_schema"],
        endpoint_url=JOB_DESIGN_ASSET.get("endpoint_url"),
    )
    # The full set of fields that must match for safe reuse. content_hash pins the
    # asset's *content*; the rest pin its *economic terms* + server-side identity.
    # TODO(⑤ type-drift): this `==` match assumes list_skill_assets round-trips
    # split_rule as a dict and price_amount as int. If a storage change ever alters
    # how these columns serialize, the match silently fails and we register a
    # duplicate instead of erroring. Add a reuse-path test guarding the types.
    expected = {
        "content_hash": content_hash,
        "creator_id": creator_id,
        "name": JOB_DESIGN_ASSET["name"],
        "type": JOB_DESIGN_ASSET["type"],
        "price_amount": JOB_DESIGN_ASSET["price_amount"],
        "price_currency": JOB_DESIGN_ASSET["price_currency"],
        "price_chain": JOB_DESIGN_ASSET.get("price_chain"),
        "split_rule": JOB_DESIGN_ASSET["split_rule"],
        "endpoint_url": JOB_DESIGN_ASSET.get("endpoint_url"),
    }
    for existing in list_skill_assets(db_path):
        if all(existing.get(key) == value for key, value in expected.items()):
            return existing["id"]

    # TODO(③ concurrency): this is a check-then-insert with no UNIQUE(content_hash)
    # backstop. Two processes (e.g. gunicorn workers) booting on a fresh DB can both
    # scan empty and both insert, creating duplicate assets. Safe for Phase 1's
    # single-process startup; revisit (DB unique constraint / advisory lock) before
    # multi-worker deploy.
    result = register_skill_asset(db_path, dict(JOB_DESIGN_ASSET), creator_id)
    return result["skill_id"]


def build_job_design_recorder(db_path: str, asset_id: str, caller_id: str):
    """Return an `on_design(task, job_design)` callback that bills one invocation.

    Each call writes one agent_run + one creator royalty_ledger row through the
    existing U4 service. Lives in the service layer so routes stay thin and the
    agents layer never has to import storage/services (avoids a circular import).

    The asset is read once here (price/currency/chain are fixed per asset); the
    returned closure performs the per-invocation write. Billing errors are NOT
    swallowed — they propagate so a recording failure is loud, not a silently
    lost royalty.
    """
    asset = get_skill_asset(db_path, asset_id)
    if asset is None:
        raise ValueError(f"Unknown asset_id for billing: {asset_id!r}")

    def on_design(task: dict, job_design: dict) -> None:
        # TODO(① settlement idempotency — RED LINE before real payments): this bills
        # one invocation per SUCCESSFUL design_job. It is intentionally NOT idempotent
        # for Phase 1 (accepted decision: "each successful invocation = one charge").
        # A repeated/retried POST therefore writes a second royalty_ledger row. This is
        # account-ledger-only (accrued) today, but MUST gain a settlement idempotency
        # key (e.g. run_id derived from task identity + a UNIQUE constraint) before any
        # real payout. Tracked in docs/pre-payment-redline-checklist.md.
        record_agent_run(
            db_path,
            agent_name="job_design",
            caller_id=caller_id,
            task_id=task.get("id", ""),
            asset_id=asset_id,
            charge_amount=asset["price_amount"],
            charge_currency=asset["price_currency"],
            charge_chain=asset["price_chain"],
            success=True,
        )

    return on_design
