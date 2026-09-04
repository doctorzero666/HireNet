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

Stage 2 / WP-D addition (pay-at-invocation rails):
- `presettled=` records a run whose money ALREADY moved before we were called
  (x402: the caller signed an EIP-3009 authorization at invocation time and a
  facilitator broadcast the transfer). See `_validate_presettled` and
  `_PRESETTLED_DOC` below for exactly what is and is not claimed by such a row.
  Passing nothing leaves every byte of the legacy path untouched.
"""
import os
from contextlib import closing

from app.services.validation import validate, validate_split_rule
from app.storage.agent_runs import _INSERT_AGENT_RUN_SQL, _build_agent_run_row
from app.storage.audit_log import _insert_audit_event_conn
from app.storage.db import _open
from app.storage.royalty_ledger import _INSERT_ROYALTY_ENTRY_SQL, _build_royalty_entry_row
from app.storage.skill_assets import get_skill_asset


# ─── Stage 2 / WP-D: pay-at-invocation (x402) constants ──────────────────────

_PRESETTLED_DOC = """
WHAT A PRE-SETTLED RUN ROW ASSERTS, AND WHAT IT DOES NOT
--------------------------------------------------------
Asserts: a facilitator accepted a signed payment authorization for this
invocation and handed us a transaction hash on `network`.
Does NOT assert: that the transaction is mined, succeeded, or moved the right
amount to the right payee. That is why the run lands in `settling`, not
`settled` — only X402SettlementProvider.check_status(), reading the receipt
and the USDC Transfer log, may promote it. Nothing on this path talks to a
chain.
"""

# settlement_method written on the run + the creator's ledger row.
X402_METHOD = "x402"

# settlement_method written on the platform / tax ledger rows. x402's `exact`
# scheme moves money to exactly ONE payee (the creator), so the platform fee
# and tax share were NOT transferred on-chain — they are a receivable FROM the
# creator. Spelling that in the column (rather than silently leaving these rows
# looking like an ordinary accrual) is the whole point: an operator running
# `SELECT ... WHERE settlement_method = 'x402-fee-receivable'` sees exactly
# what the platform is owed and by whom.
# Phase 4 fixes this properly with a splitter contract or a second transfer;
# see docs + spec S5. Until then this is an IOU, not a payment.
X402_FEE_RECEIVABLE_METHOD = "x402-fee-receivable"

# 1 USD cent = 10**6 / 100 USDC atomic units (USDC has 6 decimals).
# `charge_amount` and royalty_ledger.amount are integers in USD cents (the repo
# also calls them "基点"); x402 amounts are USDC atomic units. This factor is
# the ONLY bridge between the two and it is asserted, never assumed — see
# _validate_presettled.
USDC_ATOMIC_PER_CENT = 10_000

# The pre-settled path is defined only where 1 unit of `charge_currency` is
# 1 unit of the on-chain asset, i.e. USD priced and USDC paid.
_PRESETTLED_CURRENCIES = frozenset({"USD", "USDC"})


def _expected_usdc_address() -> str:
    """The USDC contract this deployment accepts payment in.

    Imported lazily from the x402 gate so the address (and its env override)
    has exactly one definition in the codebase.
    """
    from app.services.x402_gate import DEFAULT_USDC_ADDRESS

    return os.getenv("X402_USDC_ADDRESS", DEFAULT_USDC_ADDRESS)


def _require_str(presettled: dict, key: str) -> str:
    value = presettled.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"presettled.{key} must be a non-empty string, got {value!r}"
        )
    return value.strip()


def _validate_presettled(
    presettled: dict, charge_amount: int, charge_currency: str
) -> dict:
    """Check a `presettled` payload and return it normalised.

    Every failure here is a ValueError, and every one of them means "the
    payment we are being asked to record does not match the run we are being
    asked to bill". There is no lenient branch: recording a mismatched pair
    would put a number in the royalty ledger that no transaction backs.

    Checks, in order:
      1. shape — a dict with method == "x402" and the six required fields;
      2. currency — charge_currency must be USD or USDC (see
         _PRESETTLED_CURRENCIES); anything else has no defined cents↔atomic rate;
      3. asset — must be the configured USDC contract. A different token may
         have different decimals, which would silently break check 4;
      4. units — amount_atomic == charge_amount * USDC_ATOMIC_PER_CENT, exactly.
    """
    if not isinstance(presettled, dict):
        raise TypeError(
            f"presettled must be a dict, got {type(presettled).__name__!r}"
        )

    method = presettled.get("method")
    if method != X402_METHOD:
        raise ValueError(
            f"presettled.method must be {X402_METHOD!r}; got {method!r}. "
            "No other pay-at-invocation rail is implemented."
        )

    tx_hash = _require_str(presettled, "tx_hash")
    network = _require_str(presettled, "network")
    payer = _require_str(presettled, "payer")
    payee = _require_str(presettled, "payee")
    asset = _require_str(presettled, "asset")

    if charge_currency.upper() not in _PRESETTLED_CURRENCIES:
        raise ValueError(
            f"presettled runs require a USD/USDC-compatible charge_currency "
            f"(one of {sorted(_PRESETTLED_CURRENCIES)}), got {charge_currency!r}"
        )

    expected_asset = _expected_usdc_address()
    if asset.lower() != expected_asset.lower():
        raise ValueError(
            f"presettled.asset {asset!r} is not the configured USDC contract "
            f"{expected_asset!r}; the cents→atomic conversion is only defined "
            "for 6-decimal USDC"
        )

    raw_amount = presettled.get("amount_atomic")
    # The payer module carries amount_atomic verbatim off the wire, where it is
    # a decimal string. Accept int or a digits-only string; reject float/bool
    # outright — a rounded float here is exactly how a payment and a ledger row
    # drift apart.
    if isinstance(raw_amount, bool):
        raise ValueError("presettled.amount_atomic must not be a bool")
    if isinstance(raw_amount, int):
        amount_atomic = raw_amount
    elif isinstance(raw_amount, str) and raw_amount.strip().isdigit():
        amount_atomic = int(raw_amount.strip())
    else:
        raise ValueError(
            "presettled.amount_atomic must be a non-negative integer (or a "
            f"digits-only string), got {raw_amount!r}"
        )

    expected_atomic = charge_amount * USDC_ATOMIC_PER_CENT
    if amount_atomic != expected_atomic:
        raise ValueError(
            f"presettled.amount_atomic {amount_atomic} does not match "
            f"charge_amount {charge_amount} cents "
            f"(expected {expected_atomic} atomic USDC units at "
            f"{USDC_ATOMIC_PER_CENT} per cent). Refusing to record a ledger "
            "entry the on-chain payment does not back."
        )

    return {
        "method": X402_METHOD,
        "tx_hash": tx_hash,
        "network": network,
        "payer": payer,
        "payee": payee,
        "amount_atomic": amount_atomic,
        "asset": asset,
    }


def _fee_receivable_note(party: str, presettled: dict) -> str:
    """Why a non-creator share is still accrued after an x402 payment."""
    return (
        f"{party} share is a receivable from the creator: x402 'exact' pays a "
        f"single payee ({presettled['payee']}), so tx {presettled['tx_hash']} "
        f"on {presettled['network']} moved the creator's share only. Not paid "
        "on-chain. Phase 4: splitter contract or a second transfer."
    )


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
    presettled: dict | None = None,
) -> dict:
    """Record one SkillAsset invocation: write agent_runs + royalty_ledger atomically.

    Args:
        presettled: Stage 2 / WP-D. When None (every pre-WP-D caller) the row
            written is byte-for-byte what it always was. When given, it is the
            `payment` dict produced by app/services/x402_payer.pay_and_retry —
            `{method, tx_hash, network, payer, payee, amount_atomic, asset}` —
            i.e. the caller already paid the creator on-chain before this
            invocation returned. Effects:
              * run: payment_method='on_chain', settlement_method='x402',
                settlement_status='settling', tx_hash set, settlement_meta
                carrying the payment dict (what check_status must find on-chain);
              * ledger: identical amounts to the ledger-only path — the split
                math does not change — but the CREATOR row is 'settling' with
                the tx_hash, and the platform / tax rows stay 'accrued' and are
                stamped as receivables (X402_FEE_RECEIVABLE_METHOD + a note);
              * audit_log: one 'submit' event (status_from=None → 'settling')
                carrying the tx_hash and the network.
            See _PRESETTLED_DOC for what such a row does and does not assert.

    Returns:
        {
          "run_id": <uuid>,
          "royalty_splits": {"creator": {...}, "platform": {...}, "tax": {...}},
          "ledger_entry_ids": [<creator_uuid>, <platform_uuid>, <tax_uuid>],
        }

    Raises:
        ValueError: unknown asset_id, currency mismatch, corrupted split_rule
            in DB, negative charge_amount, or a `presettled` payload that does
            not match this run (wrong method / currency / asset, or an
            amount_atomic that is not charge_amount * 10_000).
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

    # Validate the pay-at-invocation payload BEFORE any split math or I/O, so a
    # unit mismatch can never leave a half-written run behind.
    settlement = (
        _validate_presettled(presettled, charge_amount, charge_currency)
        if presettled is not None
        else None
    )

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
    if settlement is not None:
        # 'on_chain' (not 'ledger_only') because real USDC moved for this run;
        # 'settling' (not 'settled') because we have a facilitator's word, not
        # a receipt. Both values were already legal in the agent_runs CHECK and
        # the agent_run schema — nothing widens here.
        agent_run.update({
            "payment_method": "on_chain",
            "settlement_status": "settling",
            "settlement_method": X402_METHOD,
            "tx_hash": settlement["tx_hash"],
            "settlement_meta": settlement,
        })
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
    if settlement is not None:
        # Amounts are untouched — only the settlement columns differ, and only
        # in the direction of "say less than you can prove":
        #   creator  -> 'settling' + the tx that pays it, awaiting confirmation;
        #   platform -> stays 'accrued', flagged as a receivable (see
        #   tax          X402_FEE_RECEIVABLE_METHOD). No tx_hash on these rows;
        #               claiming one would imply an on-chain payment that x402
        #               'exact' structurally cannot have made.
        for entry in royalty_entries:
            if entry["party"] == "creator":
                entry["status"] = "settling"
                entry["settlement_method"] = X402_METHOD
                entry["tx_hash"] = settlement["tx_hash"]
            else:
                entry["settlement_method"] = X402_FEE_RECEIVABLE_METHOD
                entry["note"] = _fee_receivable_note(entry["party"], settlement)

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
            if settlement is not None:
                # Same transaction as the rows it documents. 'submit' is the
                # existing event for "tx_hash recorded, still settling" (see
                # app/storage/audit_log.py); status_from is None because this
                # run has no prior state — it was BORN settling, it never sat
                # in 'accrued' and was never claimed by us.
                _insert_audit_event_conn(
                    conn, run_id, "submit",
                    status_from=None,
                    status_to="settling",
                    method=X402_METHOD,
                    tx_hash=settlement["tx_hash"],
                    network=settlement["network"],
                )

    return {
        "run_id": run_id,
        "royalty_splits": royalty_splits,
        "ledger_entry_ids": [entry_id for entry_id, _ in built_entries],
    }
