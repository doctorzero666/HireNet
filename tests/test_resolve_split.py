"""Phase 2 U1: resolve_split pure-function tests.

TIER-1 (钱 / 分账): exhaustive coverage of normal path, remainder allocation,
validation errors, and the accounting invariant. No I/O, no fixtures, no LLM
— this file runs in milliseconds and must never flake.
"""
import copy
import random

import pytest

from app.services.split import RemainderStrategy, resolve_split


def _classic_three_way():
    """7000/2000/1000 with platform NOT first so remainder allocation is visible."""
    return [
        {"payee_id": "creator_a", "bps": 7000},
        {"payee_id": "platform", "bps": 2000},
        {"payee_id": "tax", "bps": 1000},
    ]


# ── Normal path ────────────────────────────────────────────────────────

def test_charge_zero_returns_all_zero_amounts():
    result = resolve_split(0, _classic_three_way())
    assert [r["amount"] for r in result] == [0, 0, 0]
    assert sum(r["amount"] for r in result) == 0


def test_single_payee_takes_everything():
    rule = [{"payee_id": "platform", "bps": 10000}]
    result = resolve_split(1234, rule)
    assert result == [{"payee_id": "platform", "bps": 10000, "amount": 1234}]


def test_classic_three_way_clean_division():
    result = resolve_split(1000, _classic_three_way())
    amounts = {r["payee_id"]: r["amount"] for r in result}
    assert amounts == {"creator_a": 700, "platform": 200, "tax": 100}
    assert sum(amounts.values()) == 1000


def test_legacy_two_way_no_tax():
    rule = [
        {"payee_id": "creator_a", "bps": 7000},
        {"payee_id": "platform", "bps": 3000},
    ]
    result = resolve_split(1000, rule)
    amounts = {r["payee_id"]: r["amount"] for r in result}
    assert amounts == {"creator_a": 700, "platform": 300}


def test_many_payees_five_way():
    rule = [
        {"payee_id": f"creator_{i}", "bps": 2000} for i in range(4)
    ] + [{"payee_id": "platform", "bps": 2000}]
    result = resolve_split(10_000, rule)
    assert all(r["amount"] == 2000 for r in result)
    assert sum(r["amount"] for r in result) == 10_000


# ── Remainder / rounding ───────────────────────────────────────────────

def test_remainder_charge_1_goes_to_platform():
    """7000/2000/1000, charge=1: floor gives 0/0/0, residue 1 → platform."""
    result = resolve_split(1, _classic_three_way())
    amounts = {r["payee_id"]: r["amount"] for r in result}
    assert amounts == {"creator_a": 0, "platform": 1, "tax": 0}
    assert sum(amounts.values()) == 1


def test_remainder_charge_999_residue_2_goes_to_platform():
    # 999 * 7000 // 10000 = 699
    # 999 * 2000 // 10000 = 199
    # 999 * 1000 // 10000 =  99
    # sum = 997, residue = 2 → platform 201
    result = resolve_split(999, _classic_three_way())
    amounts = {r["payee_id"]: r["amount"] for r in result}
    assert amounts == {"creator_a": 699, "platform": 201, "tax": 99}
    assert sum(amounts.values()) == 999


def test_near_equal_three_way_with_remainder():
    """3333/3333/3334, charge=100: 33/33/33, residue 1 → platform."""
    rule = [
        {"payee_id": "creator_a", "bps": 3333},
        {"payee_id": "platform", "bps": 3333},
        {"payee_id": "creator_b", "bps": 3334},
    ]
    result = resolve_split(100, rule)
    amounts = {r["payee_id"]: r["amount"] for r in result}
    assert amounts == {"creator_a": 33, "platform": 34, "creator_b": 33}
    assert sum(amounts.values()) == 100


def test_extreme_split_9999_1_no_remainder():
    rule = [
        {"payee_id": "creator_a", "bps": 9999},
        {"payee_id": "platform", "bps": 1},
    ]
    result = resolve_split(10_000, rule)
    amounts = {r["payee_id"]: r["amount"] for r in result}
    assert amounts == {"creator_a": 9999, "platform": 1}


def test_extreme_split_9999_1_with_remainder():
    rule = [
        {"payee_id": "creator_a", "bps": 9999},
        {"payee_id": "platform", "bps": 1},
    ]
    # 1 * 9999 // 10000 = 0; 1 * 1 // 10000 = 0; residue 1 → platform
    result = resolve_split(1, rule)
    amounts = {r["payee_id"]: r["amount"] for r in result}
    assert amounts == {"creator_a": 0, "platform": 1}


def test_large_charge_no_overflow():
    """10^9 cents (10 million USD) — Python ints are unbounded, sanity check."""
    rule = _classic_three_way()
    result = resolve_split(10**9, rule)
    assert sum(r["amount"] for r in result) == 10**9


# ── Validation: split_rule structure ──────────────────────────────────

def test_sum_bps_below_10000_rejected():
    rule = [
        {"payee_id": "creator_a", "bps": 7000},
        {"payee_id": "platform", "bps": 2999},
    ]
    with pytest.raises(ValueError, match="sum to 10000"):
        resolve_split(1000, rule)


def test_sum_bps_above_10000_rejected():
    rule = [
        {"payee_id": "creator_a", "bps": 7001},
        {"payee_id": "platform", "bps": 3000},
    ]
    with pytest.raises(ValueError, match="sum to 10000"):
        resolve_split(1000, rule)


def test_empty_split_rule_rejected():
    with pytest.raises(ValueError, match="non-empty"):
        resolve_split(1000, [])


def test_non_list_split_rule_rejected():
    """Legacy {creator,platform,tax} dict must be rejected — not auto-converted."""
    with pytest.raises(ValueError, match="non-empty list"):
        resolve_split(1000, {"creator": 7000, "platform": 3000})


def test_negative_bps_rejected():
    rule = [
        {"payee_id": "creator_a", "bps": -1},
        {"payee_id": "platform", "bps": 10001},
    ]
    with pytest.raises(ValueError, match="non-negative"):
        resolve_split(1000, rule)


def test_float_bps_rejected():
    rule = [
        {"payee_id": "creator_a", "bps": 7000.0},
        {"payee_id": "platform", "bps": 3000},
    ]
    with pytest.raises(ValueError, match="bps must be an int"):
        resolve_split(1000, rule)


def test_bool_bps_rejected():
    """bool is an int subclass — must explicitly reject so True doesn't sneak in as 1 bp."""
    rule = [
        {"payee_id": "creator_a", "bps": True},
        {"payee_id": "platform", "bps": 9999},
    ]
    with pytest.raises(ValueError, match="bps"):
        resolve_split(1000, rule)


def test_duplicate_payee_id_rejected():
    rule = [
        {"payee_id": "platform", "bps": 5000},
        {"payee_id": "platform", "bps": 5000},
    ]
    with pytest.raises(ValueError, match="duplicate"):
        resolve_split(1000, rule)


def test_empty_payee_id_rejected():
    rule = [
        {"payee_id": "", "bps": 7000},
        {"payee_id": "platform", "bps": 3000},
    ]
    with pytest.raises(ValueError, match="payee_id"):
        resolve_split(1000, rule)


def test_non_string_payee_id_rejected():
    rule = [
        {"payee_id": 42, "bps": 7000},
        {"payee_id": "platform", "bps": 3000},
    ]
    with pytest.raises(ValueError, match="payee_id"):
        resolve_split(1000, rule)


def test_missing_payee_id_rejected():
    rule = [
        {"bps": 7000},
        {"payee_id": "platform", "bps": 3000},
    ]
    with pytest.raises(ValueError, match="payee_id"):
        resolve_split(1000, rule)


def test_missing_bps_rejected():
    rule = [
        {"payee_id": "creator_a"},
        {"payee_id": "platform", "bps": 3000},
    ]
    with pytest.raises(ValueError, match="bps"):
        resolve_split(1000, rule)


def test_entry_not_dict_rejected():
    rule = [
        ("creator_a", 7000),
        {"payee_id": "platform", "bps": 3000},
    ]
    with pytest.raises(ValueError, match="must be a dict"):
        resolve_split(1000, rule)


# ── Validation: strategy precondition ─────────────────────────────────

def test_platform_absorbs_requires_platform_entry():
    """PLATFORM_ABSORBS with no platform payee → fail at validation, not after compute."""
    rule = [
        {"payee_id": "creator_a", "bps": 7000},
        {"payee_id": "creator_b", "bps": 3000},
    ]
    with pytest.raises(ValueError, match="platform"):
        resolve_split(1000, rule, strategy=RemainderStrategy.PLATFORM_ABSORBS)


# ── Validation: charge ────────────────────────────────────────────────

def test_negative_charge_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        resolve_split(-1, _classic_three_way())


def test_float_charge_rejected():
    with pytest.raises(ValueError, match="charge"):
        resolve_split(100.0, _classic_three_way())


def test_bool_charge_rejected():
    """bool subclasses int — reject explicitly so True doesn't silently become 1 cent."""
    with pytest.raises(ValueError, match="charge"):
        resolve_split(True, _classic_three_way())


def test_string_charge_rejected():
    with pytest.raises(ValueError, match="charge"):
        resolve_split("100", _classic_three_way())


def test_none_charge_rejected():
    with pytest.raises(ValueError, match="charge"):
        resolve_split(None, _classic_three_way())


# ── Accounting invariant (property-style, deterministic) ──────────────

def test_invariant_sum_equals_charge_randomised():
    """30 randomised inputs: sum(amount) == charge holds always. seed=42 → no flakes."""
    rng = random.Random(42)
    for _ in range(30):
        charge = rng.randint(0, 10**9)
        n = rng.randint(2, 5)
        # Pick n-1 distinct cut points in [1, 9999], slice [0, 10000] into n
        # positive integer pieces summing to 10000.
        cuts = sorted(rng.sample(range(1, 10000), n - 1))
        bps_list = (
            [cuts[0]]
            + [cuts[i] - cuts[i - 1] for i in range(1, n - 1)]
            + [10000 - cuts[-1]]
        )
        assert sum(bps_list) == 10000  # sanity on the test setup itself
        platform_idx = rng.randint(0, n - 1)
        rule = [
            {
                "payee_id": "platform" if i == platform_idx else f"creator_{i}",
                "bps": bps,
            }
            for i, bps in enumerate(bps_list)
        ]
        result = resolve_split(charge, rule)
        assert sum(r["amount"] for r in result) == charge, (
            f"invariant broken: charge={charge}, rule={rule}, result={result}"
        )


# ── Pure function / determinism / output shape ────────────────────────

def test_determinism_same_input_same_output():
    rule = _classic_three_way()
    assert resolve_split(12345, rule) == resolve_split(12345, rule)


def test_output_preserves_input_order():
    """Even if platform is not first, output order matches input order."""
    rule = [
        {"payee_id": "tax", "bps": 1000},
        {"payee_id": "creator_a", "bps": 7000},
        {"payee_id": "platform", "bps": 2000},
    ]
    result = resolve_split(1000, rule)
    assert [r["payee_id"] for r in result] == ["tax", "creator_a", "platform"]


def test_input_split_rule_not_mutated():
    """resolve_split must NOT mutate caller's list or dict entries."""
    rule = _classic_three_way()
    original = copy.deepcopy(rule)
    resolve_split(999, rule)
    assert rule == original


def test_output_structure_payee_id_bps_amount_only():
    """Output entries carry exactly {payee_id, bps, amount} — no party, no extras."""
    for entry in resolve_split(1000, _classic_three_way()):
        assert set(entry.keys()) == {"payee_id", "bps", "amount"}
