"""Phase 2 U1: pure-function chokepoint for splitting a charge across payees.

Generalises the old fixed-three-slot {creator, platform, tax} shape (see
app/schemas/royalty_split.json) into a generic payee list
[{payee_id, bps}, ...]. `resolve_split` is the sole point where per-payee
amounts get computed — nothing else inlines its own split math.

TIER-1 (钱 / 分账): requires per-line human review. CLAUDE.md §TIER-1 rule 2.

Scope per docs/phase-2-spec.md U1:
  - In:  schema + pure function + validation + unit tests.
  - Out: DB, persistence, wiring. The legacy three-slot path
         (app/services/agent_run_recording.py:104-111 and
         app/services/validation.py:69 validate_split_rule) stays in place
         until U3 migrates the wiring.

Pure-function contract:
  - No I/O, no module-level mutable state, no randomness.
  - Same (charge, split_rule, strategy) → identical output, always.
  - Input split_rule is NOT mutated.
  - sum(amount) == charge holds always (hard RuntimeError if not).
"""
from enum import Enum
from typing import Any


class RemainderStrategy(str, Enum):
    """How to allocate the integer-division remainder so amounts sum to charge."""

    PLATFORM_ABSORBS = "platform_absorbs"


_PLATFORM_PAYEE_ID = "platform"


def resolve_split(
    charge: int,
    split_rule: list[dict[str, Any]],
    strategy: RemainderStrategy = RemainderStrategy.PLATFORM_ABSORBS,
) -> list[dict[str, Any]]:
    """Split `charge` (basis-point integer) across payees per `split_rule`.

    Args:
        charge: Non-negative int in the smallest currency unit. bool is
                rejected — it subclasses int, so `True * 7000 // 10000 == 0`
                would otherwise be a silent zero-bill.
        split_rule: Ordered list of {"payee_id": str, "bps": int}. bps must
                    sum to exactly 10000. payee_id must be unique (otherwise
                    PLATFORM_ABSORBS residue is ambiguous and downstream
                    ledger rows would collide).
        strategy: Where the floor-division remainder goes. Only
                  PLATFORM_ABSORBS is implemented in U1; the strategy
                  precondition is checked up-front so an unwired enum value
                  fails at validation time, not silently in the math.

    Returns:
        Ordered list of {"payee_id", "bps", "amount"} in the same order as
        the input. sum(amount) == charge is guaranteed.

    Raises:
        ValueError: any input shape / value violation. Loud and immediate —
                    money code never silently mis-accounts.
        RuntimeError: defensive — would only fire if the algorithm itself
                      were broken. `raise`, not `assert`, because `python -O`
                      strips asserts.
    """
    # ── Validate charge ────────────────────────────────────────────────
    # bool first: isinstance(True, int) is True, so the int check below
    # would let bool through and True silently becomes 1 cent.
    if isinstance(charge, bool) or not isinstance(charge, int):
        raise ValueError(
            f"charge must be a non-negative int, got {type(charge).__name__}: {charge!r}"
        )
    if charge < 0:
        raise ValueError(f"charge must be non-negative, got {charge}")

    # ── Validate split_rule structure ─────────────────────────────────
    if not isinstance(split_rule, list) or not split_rule:
        raise ValueError("split_rule must be a non-empty list")

    seen_ids: set[str] = set()
    total_bps = 0
    for i, entry in enumerate(split_rule):
        if not isinstance(entry, dict):
            raise ValueError(
                f"split_rule[{i}] must be a dict, got {type(entry).__name__}"
            )
        payee_id = entry.get("payee_id")
        if not isinstance(payee_id, str) or not payee_id:
            raise ValueError(
                f"split_rule[{i}].payee_id must be a non-empty string, got {payee_id!r}"
            )
        bps = entry.get("bps")
        if isinstance(bps, bool) or not isinstance(bps, int):
            raise ValueError(
                f"split_rule[{i}].bps must be an int, got {type(bps).__name__}: {bps!r}"
            )
        if bps < 0:
            raise ValueError(
                f"split_rule[{i}].bps must be non-negative, got {bps}"
            )
        if payee_id in seen_ids:
            raise ValueError(f"split_rule has duplicate payee_id: {payee_id!r}")
        seen_ids.add(payee_id)
        total_bps += bps

    if total_bps != 10000:
        raise ValueError(f"split_rule bps must sum to 10000, got {total_bps}")

    # ── Strategy precondition ─────────────────────────────────────────
    # PLATFORM_ABSORBS needs a "platform" payee to take the residue.
    # Checking up-front (not after compute) keeps the failure loud.
    if strategy == RemainderStrategy.PLATFORM_ABSORBS:
        if _PLATFORM_PAYEE_ID not in seen_ids:
            raise ValueError(
                f"strategy={strategy.value} requires a payee_id=={_PLATFORM_PAYEE_ID!r} entry"
            )

    # ── Computation (integer-only, deterministic) ─────────────────────
    # Floor-divide so per-payee amounts never exceed their bps share.
    # Remainder satisfies 0 <= r < len(split_rule) by construction.
    result = [
        {
            "payee_id": entry["payee_id"],
            "bps": entry["bps"],
            "amount": charge * entry["bps"] // 10000,
        }
        for entry in split_rule
    ]
    remainder = charge - sum(r["amount"] for r in result)

    if remainder and strategy == RemainderStrategy.PLATFORM_ABSORBS:
        for r in result:
            if r["payee_id"] == _PLATFORM_PAYEE_ID:
                r["amount"] += remainder
                break

    # ── Hard accounting invariant ─────────────────────────────────────
    # Explicit raise (not assert): `python -O` strips asserts, and TIER-1
    # money code must never silently mis-account.
    total_out = sum(r["amount"] for r in result)
    if total_out != charge:
        raise RuntimeError(
            f"resolve_split internal error: sum(amount)={total_out} != charge={charge}; "
            f"strategy={strategy.value}, split_rule={split_rule}"
        )

    return result
