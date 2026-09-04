"""
Stage 1 / WP3a — unit tests for the LLM price table (D8).

The point of these tests is not the arithmetic (that is one multiplication);
it is the two honesty rules: an unknown model must price as `None` rather than
as a guess, and "the provider told us nothing" must not be reported as "$0".
"""
import pytest

from app.agents import pricing
from app.agents.pricing import (
    MODEL_PRICES_USD_PER_1M,
    PRICE_OVERRIDE_ENV,
    estimate_cost_usd,
    get_price,
)


@pytest.fixture(autouse=True)
def _guard_no_real_llm(no_real_llm_client):
    """No test in this module may construct the real OpenAI client."""


@pytest.fixture(autouse=True)
def _no_ambient_override(monkeypatch):
    """A price override in the developer's real env must not steer these tests."""
    monkeypatch.delenv(PRICE_OVERRIDE_ENV, raising=False)
    pricing._override_cache.clear()
    yield
    pricing._override_cache.clear()


# ─── The built-in table ───────────────────────────────────────────────────────

def test_default_model_is_priced():
    """`get_model()` defaults to glm-4-plus (agents.py:23) — it must be in the table."""
    assert "glm-4-plus" in MODEL_PRICES_USD_PER_1M


@pytest.mark.parametrize("model", sorted(MODEL_PRICES_USD_PER_1M))
def test_every_entry_has_positive_input_and_output_prices(model):
    entry = MODEL_PRICES_USD_PER_1M[model]
    assert set(entry) == {"input", "output"}
    assert entry["input"] > 0 and entry["output"] > 0


def test_cost_is_tokens_times_price_per_million():
    price = MODEL_PRICES_USD_PER_1M["glm-4-plus"]
    expected = (1000 * price["input"] + 500 * price["output"]) / 1_000_000
    assert estimate_cost_usd("glm-4-plus", 1000, 500) == pytest.approx(expected)


def test_zero_tokens_costs_zero():
    assert estimate_cost_usd("glm-4-plus", 0, 0) == 0.0


# ─── Unknown model: None, never a guess ───────────────────────────────────────

def test_unknown_model_returns_none():
    assert estimate_cost_usd("gpt-5-turbo-imaginary", 1000, 500) is None
    assert get_price("gpt-5-turbo-imaginary") is None


@pytest.mark.parametrize("model", [None, ""])
def test_missing_model_returns_none(model):
    assert estimate_cost_usd(model, 1000, 500) is None
    assert get_price(model) is None


# ─── Missing usage: None, never $0 ────────────────────────────────────────────

def test_no_usage_at_all_returns_none():
    assert estimate_cost_usd("glm-4-plus", None, None) is None


def test_one_missing_count_is_priced_as_a_lower_bound():
    price = MODEL_PRICES_USD_PER_1M["glm-4-plus"]
    assert estimate_cost_usd("glm-4-plus", 1000, None) == pytest.approx(
        1000 * price["input"] / 1_000_000
    )
    assert estimate_cost_usd("glm-4-plus", None, 500) == pytest.approx(
        500 * price["output"] / 1_000_000
    )


# ─── Env override ─────────────────────────────────────────────────────────────

def test_override_corrects_a_known_model(monkeypatch):
    monkeypatch.setenv(PRICE_OVERRIDE_ENV, '{"glm-4-plus": {"input": 100.0, "output": 200.0}}')
    assert estimate_cost_usd("glm-4-plus", 1_000_000, 1_000_000) == pytest.approx(300.0)


def test_override_adds_a_model_the_table_does_not_know(monkeypatch):
    monkeypatch.setenv(PRICE_OVERRIDE_ENV, '{"local-llama": {"input": 0.0, "output": 1.0}}')
    assert estimate_cost_usd("local-llama", 1_000_000, 2_000_000) == pytest.approx(2.0)


def test_override_merges_rather_than_replaces_the_table(monkeypatch):
    monkeypatch.setenv(PRICE_OVERRIDE_ENV, '{"local-llama": {"input": 1.0, "output": 1.0}}')
    assert get_price("glm-4-plus") == MODEL_PRICES_USD_PER_1M["glm-4-plus"]


def test_changing_the_override_takes_effect_immediately(monkeypatch):
    monkeypatch.setenv(PRICE_OVERRIDE_ENV, '{"m": {"input": 1.0, "output": 1.0}}')
    assert estimate_cost_usd("m", 1_000_000, 0) == pytest.approx(1.0)
    monkeypatch.setenv(PRICE_OVERRIDE_ENV, '{"m": {"input": 2.0, "output": 2.0}}')
    assert estimate_cost_usd("m", 1_000_000, 0) == pytest.approx(2.0)


def test_malformed_override_is_logged_and_ignored(monkeypatch, caplog):
    monkeypatch.setenv(PRICE_OVERRIDE_ENV, "not json at all")
    with caplog.at_level("WARNING"):
        assert get_price("glm-4-plus") == MODEL_PRICES_USD_PER_1M["glm-4-plus"]
    assert PRICE_OVERRIDE_ENV in caplog.text


def test_non_object_override_is_ignored(monkeypatch, caplog):
    monkeypatch.setenv(PRICE_OVERRIDE_ENV, "[1, 2, 3]")
    with caplog.at_level("WARNING"):
        assert get_price("glm-4-plus") == MODEL_PRICES_USD_PER_1M["glm-4-plus"]


def test_override_entry_missing_a_side_is_ignored_with_a_warning(monkeypatch, caplog):
    monkeypatch.setenv(PRICE_OVERRIDE_ENV, '{"glm-4-plus": {"input": 1.0}}')
    with caplog.at_level("WARNING"):
        assert get_price("glm-4-plus") == MODEL_PRICES_USD_PER_1M["glm-4-plus"]
    assert PRICE_OVERRIDE_ENV in caplog.text


def test_empty_override_env_is_a_no_op(monkeypatch):
    monkeypatch.setenv(PRICE_OVERRIDE_ENV, "")
    assert get_price("glm-4-plus") == MODEL_PRICES_USD_PER_1M["glm-4-plus"]
