"""
LLM price table and cost estimation (Stage 1 / D8).

`agent_runs` has had `input_tokens` / `output_tokens` / `llm_cost_usd` /
`time_ms` columns since Phase 1 and they have always been NULL, because
`resp.usage` was never read anywhere in `app/` (audit §4, risk 9). The v2
`TaskAnalysisAgent` reads usage off every response; this module turns that into
money.

Honesty rules for this file:

* An **unknown model returns `None`, never a guessed price.** A wrong number in
  a cost report is worse than a missing one — `None` shows up as "unknown" in
  the WP4 comparison instead of quietly moving the v1-vs-v2 verdict.
* The numbers below are **list prices, not measured invoices**. Verify them
  against the current Zhipu price page before quoting any total externally.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

#: Env var holding a JSON object that is merged over `MODEL_PRICES_USD_PER_1M`,
#: e.g. `HIRENET_MODEL_PRICE_JSON='{"glm-4-plus": {"input": 6.5, "output": 6.5}}'`.
#: Use it to correct a stale entry or price a model this table does not know,
#: without a code change.
PRICE_OVERRIDE_ENV = "HIRENET_MODEL_PRICE_JSON"

#: CNY→USD rate used to convert Zhipu's published CNY list prices below.
#: An assumption, not a quote: change it (or override the table via
#: PRICE_OVERRIDE_ENV) if you need accuracy better than "right order of magnitude".
CNY_PER_USD = 7.15

#: model id → {"input": USD per 1M input tokens, "output": USD per 1M output tokens}
#:
#: Zhipu publishes these in CNY per 1K tokens; the USD figures are that price
#: × 1000 ÷ CNY_PER_USD, rounded to 2 decimals.
#:
#: list price as of 2026-09, verify
MODEL_PRICES_USD_PER_1M: dict[str, dict[str, float]] = {
    # glm-4-plus: ¥0.05 / 1K tokens → ¥50 / 1M → $6.99 / 1M, same both directions.
    # This is `get_model()`'s default (`app/agents/agents.py:23`), so it is the
    # entry that actually prices the Stage 1 runs.
    "glm-4-plus": {"input": 6.99, "output": 6.99},
    # glm-4: ¥0.1 / 1K tokens → ¥100 / 1M → $13.99 / 1M, same both directions.
    "glm-4": {"input": 13.99, "output": 13.99},
}

#: Cache of the parsed override, keyed by the raw env string, so a per-call
#: `os.getenv` stays cheap without going stale when a test monkeypatches the env.
_override_cache: dict[str, dict[str, dict[str, float]]] = {}


def _load_overrides() -> dict[str, dict[str, float]]:
    """Parse `HIRENET_MODEL_PRICE_JSON`. A malformed value is logged and ignored."""
    raw = os.getenv(PRICE_OVERRIDE_ENV)
    if not raw:
        return {}
    if raw in _override_cache:
        return _override_cache[raw]
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")
    except (json.JSONDecodeError, ValueError) as exc:
        # A bad price override must not take the analysis pipeline down; it just
        # means we fall back to the built-in table (or to "unknown").
        logger.warning("%s is not a usable JSON object (%s); ignoring it", PRICE_OVERRIDE_ENV, exc)
        return {}
    _override_cache[raw] = parsed
    return parsed


def get_price(model: str | None) -> dict[str, float] | None:
    """Return `{"input": ..., "output": ...}` USD per 1M tokens, or None if unknown.

    The env override is merged over the built-in table per model id, so an
    override may both correct a known model and add an unknown one.
    """
    if not model:
        return None
    overrides = _load_overrides()
    if model in overrides:
        entry = overrides[model]
        if isinstance(entry, dict) and "input" in entry and "output" in entry:
            return {"input": float(entry["input"]), "output": float(entry["output"])}
        logger.warning(
            "%s[%s] must be an object with numeric 'input' and 'output'; ignoring it",
            PRICE_OVERRIDE_ENV,
            model,
        )
    return MODEL_PRICES_USD_PER_1M.get(model)


def estimate_cost_usd(
    model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
) -> float | None:
    """Estimate the USD cost of one LLM call.

    Returns None when the model is unknown (no guessed price) or when the
    provider reported no usage at all (both token counts None — 0 and "we do
    not know" are different facts, and `agent_runs` stores them differently).

    When exactly one of the two counts is missing, the missing side is priced as
    0 and the result is therefore a lower bound.
    """
    price = get_price(model)
    if price is None:
        return None
    if input_tokens is None and output_tokens is None:
        return None
    cost = (
        (input_tokens or 0) * price["input"] + (output_tokens or 0) * price["output"]
    ) / 1_000_000
    return round(cost, 8)
