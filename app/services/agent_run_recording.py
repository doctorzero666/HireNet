"""
U4: record a single SkillAsset invocation.

Given a charge_amount (integer basis points) and the asset that was used,
compute the creator / platform / tax split per the asset's split_rule and
atomically write both the agent_runs row and the royalty_ledger rows.

Phase 1 invariants enforced here:
- charge_amount is INTEGER basis points; floor goes to creator and tax, residual to platform.
  creator_amt + tax_amt + platform_amt == charge_amount always.
- agent_runs and royalty_ledger are written in a single SQLite transaction:
  either every row lands, or none.
- charge_currency must match the asset's price_currency. Cross-currency
  settlement is Phase 2.

Phase 2 / U1 addition:
- split_rule may carry an optional `tax` basis-points field. When absent,
  tax_amt is 0 and platform absorbs the residual exactly as in Phase 1 —
  so legacy 2-way rules behave identically.

Phase 2 / U2 change (ledger granularity):
- royalty_ledger now records ONE row per payee per run, not just the creator.
  Each run produces three rows — party='creator' (payee_id=asset.creator_id),
  party='platform' (payee_id='platform'), party='tax' (payee_id='tax') —
  written inside the same transaction. The agent_runs.royalty_splits JSON is
  unchanged so the existing /api/royalty/split shape stays stable.
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
          "royalty_splits": {"creator": {...}, "platform": {...}, "tax": {...}},
          "ledger_entry_ids": [<creator_uuid>, <platform_uuid>, <tax_uuid>],
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
    tax_bp = asset["split_rule"].get("tax", 0)
    creator_amt = charge_amount * creator_bp // 10000
    tax_amt = charge_amount * tax_bp // 10000
    # Platform absorbs the rounding residual so the three shares sum to charge_amount
    # exactly. With tax_bp=0 this collapses to the Phase 1 behaviour (tax_amt=0,
    # platform_amt = charge_amount - creator_amt).
    platform_amt = charge_amount - creator_amt - tax_amt

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
        "tax": {
            "amount": tax_amt,
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

    # Phase 2 / U2: one ledger row per payee. The platform and tax shares are
    # not "external" payees in Phase 1 sense, but they are persisted as their
    # own rows so a downstream settlement layer can pay them out by payee_id
    # without re-parsing agent_runs.royalty_splits JSON. The creator_id column
    # stays on every row (set == payee_id when party=='creator'; pinned to the
    # asset's creator on the platform/tax rows for join-friendliness).
    creator_id = asset["creator_id"]
    royalty_entries = [
        {
            "run_id": run_id,
            "creator_id": creator_id,
            "payee_id": creator_id,
            "party": "creator",
            "asset_id": asset_id,
            "amount": creator_amt,
            "currency": charge_currency,
            "chain": charge_chain,
            "status": "accrued",
        },
        {
            "run_id": run_id,
            "creator_id": creator_id,
            "payee_id": "platform",
            "party": "platform",
            "asset_id": asset_id,
            "amount": platform_amt,
            "currency": charge_currency,
            "chain": charge_chain,
            "status": "accrued",
        },
        {
            "run_id": run_id,
            "creator_id": creator_id,
            "payee_id": "tax",
            "party": "tax",
            "asset_id": asset_id,
            "amount": tax_amt,
            "currency": charge_currency,
            "chain": charge_chain,
            "status": "accrued",
        },
    ]
    built_entries = [_build_royalty_entry_row(entry) for entry in royalty_entries]

    # Schema validation just before persistence: catches any drift between
    # the dicts we assembled and what the schemas accept. Every persisted row
    # must pass royalty_entry validation, so all 3 are checked here.
    validate({**agent_run, "run_id": run_id, "created_at": "1970-01-01T00:00:00+00:00"}, "agent_run")
    for entry, (entry_id, _) in zip(royalty_entries, built_entries):
        validate(
            {**entry, "id": entry_id, "created_at": "1970-01-01T00:00:00+00:00"},
            "royalty_entry",
        )

    # Single transaction: either the agent_run row and ALL 3 ledger rows land,
    # or none do. A partial 3-way split would break the per-payee accounting
    # invariant (creator + platform + tax == charge_amount).
    with closing(_open(db_path)) as conn:
        with conn:
            conn.execute(_INSERT_AGENT_RUN_SQL, run_params)
            for _, entry_params in built_entries:
                conn.execute(_INSERT_ROYALTY_ENTRY_SQL, entry_params)

    return {
        "run_id": run_id,
        "royalty_splits": royalty_splits,
        "ledger_entry_ids": [entry_id for entry_id, _ in built_entries],
    }
