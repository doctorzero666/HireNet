"""
U4: record a single SkillAsset invocation.

Given a charge_amount (integer basis points) and the asset that was used,
compute the creator / platform split per the asset's split_rule and
atomically write both an agent_runs row and a royalty_ledger row.

Phase 1 invariants enforced here:
- charge_amount is INTEGER basis points; floor goes to creator, residual to platform.
  creator_amt + platform_amt == charge_amount always.
- agent_runs and royalty_ledger are written in a single SQLite transaction:
  either both rows land, or neither.
- Only the creator gets a royalty_ledger row. The platform share lives in
  agent_runs.royalty_splits JSON. (Per Phase 1 decision: ledger == "what is
  owed to a creator".)
- charge_currency must match the asset's price_currency. Cross-currency
  settlement is Phase 2.
"""
from contextlib import closing

from app.services.validation import validate, validate_split_rule
from app.storage.agent_runs import _INSERT_AGENT_RUN_SQL, _build_agent_run_row
from app.storage.db import _open
from app.storage.royalty_ledger import _INSERT_ROYALTY_ENTRY_SQL, _build_royalty_entry_row
from app.storage.skill_assets import get_skill_asset


def record_agent_run(
    db_path: str,
    *,
    agent_name: str,
    caller_id: str,
    task_id: str,
    asset_id: str,
    charge_amount: int,
    charge_currency: str,
    success: bool,
    charge_chain: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    llm_cost_usd: str | None = None,
    time_ms: int | None = None,
) -> dict:
    """Record one SkillAsset invocation: write agent_runs + royalty_ledger atomically.

    Returns:
        {
          "run_id": <uuid>,
          "royalty_splits": {"creator": {...}, "platform": {...}},
          "ledger_entry_id": <uuid>,
        }

    Raises:
        ValueError: unknown asset_id, currency mismatch, corrupted split_rule
            in DB, or negative charge_amount.
        TypeError: charge_amount is not a plain non-negative int (float / bool rejected).
        jsonschema.ValidationError: assembled agent_run or royalty_entry fails its schema.
    """
    # U4 only supports single-asset runs. Reject multi-asset / wrong-type inputs
    # explicitly here, before any DB I/O — so callers get a clear domain error
    # instead of a low-level sqlite3.ProgrammingError from the parameter binding.
    if isinstance(asset_id, (list, tuple, set)):
        raise ValueError(
            "U4 supports exactly one asset_id; multi-asset runs are not supported"
        )
    if not isinstance(asset_id, str):
        raise TypeError(
            f"asset_id must be a non-empty string, got {type(asset_id).__name__!r}"
        )
    if not asset_id:
        raise ValueError("asset_id must be a non-empty string")

    asset = get_skill_asset(db_path, asset_id)
    if asset is None:
        raise ValueError(f"Unknown asset_id: {asset_id!r}")

    # Defensive: registration validated this, but DB rows can be hand-edited.
    validate_split_rule(asset["split_rule"])

    if charge_currency != asset["price_currency"]:
        raise ValueError(
            f"charge_currency {charge_currency!r} does not match "
            f"asset.price_currency {asset['price_currency']!r}; "
            f"cross-currency settlement is out of scope in Phase 1"
        )

    if isinstance(charge_amount, bool) or not isinstance(charge_amount, int):
        raise TypeError(
            f"charge_amount must be a non-negative int (basis points), "
            f"got {type(charge_amount).__name__!r}"
        )
    if charge_amount < 0:
        raise ValueError(f"charge_amount must be >= 0, got {charge_amount}")

    creator_bp = asset["split_rule"]["creator"]
    creator_amt = charge_amount * creator_bp // 10000
    platform_amt = charge_amount - creator_amt

    royalty_splits = {
        "creator": {
            "creator_id": asset["creator_id"],
            "asset_id": asset_id,
            "amount": creator_amt,
            "currency": charge_currency,
            "chain": charge_chain,
        },
        "platform": {
            "amount": platform_amt,
            "currency": charge_currency,
            "chain": charge_chain,
        },
    }

    # Build the agent_run row first so its run_id is available for the ledger entry's FK.
    agent_run = {
        "agent_name": agent_name,
        "caller_id": caller_id,
        "task_id": task_id,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "llm_cost_usd": llm_cost_usd,
        "time_ms": time_ms,
        "success": success,
        "asset_ids": [asset_id],
        "royalty_splits": royalty_splits,
        "charge_amount": charge_amount,
        "charge_currency": charge_currency,
        "charge_chain": charge_chain,
        "payment_method": "ledger_only",
        "settlement_status": "accrued",
    }
    run_id, run_params = _build_agent_run_row(agent_run)

    royalty_entry = {
        "run_id": run_id,
        "creator_id": asset["creator_id"],
        "asset_id": asset_id,
        "amount": creator_amt,
        "currency": charge_currency,
        "chain": charge_chain,
        "status": "accrued",
    }
    entry_id, entry_params = _build_royalty_entry_row(royalty_entry)

    # Schema validation just before persistence: catches any drift between
    # the dicts we assembled and what the schemas accept.
    validate({**agent_run, "run_id": run_id, "created_at": "1970-01-01T00:00:00+00:00"}, "agent_run")
    validate(
        {**royalty_entry, "id": entry_id, "created_at": "1970-01-01T00:00:00+00:00"},
        "royalty_entry",
    )

    # Single transaction: either both rows land or neither.
    with closing(_open(db_path)) as conn:
        with conn:
            conn.execute(_INSERT_AGENT_RUN_SQL, run_params)
            conn.execute(_INSERT_ROYALTY_ENTRY_SQL, entry_params)

    return {
        "run_id": run_id,
        "royalty_splits": royalty_splits,
        "ledger_entry_id": entry_id,
    }
