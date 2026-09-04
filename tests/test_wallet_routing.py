"""
Wallet routing tests — /api/royalty/settle hands the billed Agent's
``skill_assets.wallet_address`` to the Sepolia provider as ``to_address``.

We don't run a real Sepolia tx here. The provider is a recording stub that
captures every ``settle`` kwarg, so the assertions are pure interface checks:

  - When the bound asset has a wallet_address, the route passes it as
    ``to_address`` to a sepolia-named provider.
  - When the asset's wallet_address is NULL, the route passes
    ``to_address=None`` so the provider falls back to its env default /
    self.from_address.
  - When the provider is NOT sepolia (mock here), the route MUST NOT pass
    ``to_address`` at all — that's the "don't touch the mock/anvil
    signatures" guarantee.
"""
import os
import tempfile

import pytest

from app.app import create_app
from app.services.settlement import (
    SettlementProvider,
    SettlementResult,
    SettlementStatus,
)


class _RecordingProvider(SettlementProvider):
    """Records every settle() kwarg dict so tests can inspect what the route
    layer actually passed in. Returns SETTLED synchronously so the run flips
    to settled and the route-handling branch we care about runs."""

    def __init__(self, name: str = "sepolia"):
        self.name = name
        self.calls: list[dict] = []

    def settle(self, **kwargs) -> SettlementResult:
        self.calls.append(kwargs)
        return SettlementResult(
            success=True,
            tx_hash=f"0x{'aa' * 32}",
            next_status=SettlementStatus.SETTLED,
        )

    def check_status(self, tx_hash: str) -> SettlementStatus:
        return SettlementStatus.SETTLED


# Anvil account #1 — well-known throwaway, safe to use in tests.
_AGENT_WALLET = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


def _make_client(provider):
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app(config={
        "TESTING": True,
        "DATABASE_PATH": db_path,
        "SETTLEMENT_PROVIDER": provider,
    })
    return app.test_client(), db_path


def _register_asset(client, *, wallet_address=None):
    payload = {
        "name": "Wallet Routing Test Agent",
        "description": "Agent under test for wallet routing",
        "type": "agent",
        "io_schema": {"input": {"q": "string"}, "output": {"a": "string"}},
        "price_amount": 1000,
        "price_currency": "USD",
        "split_rule": {"creator": 7000, "platform": 2000, "tax": 1000},
    }
    if wallet_address is not None:
        payload["wallet_address"] = wallet_address
    resp = client.post("/api/skills/register", json=payload)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["skill_id"]


def _create_pact_and_settle(client, asset_id):
    """Walk a pact through create → approve → settle. Returns the JSON body
    of the settle call. /api/royalty/settle is what actually invokes
    provider.settle(), driven off the recorded agent_run.
    """
    pact_resp = client.post("/api/pact/create", json={
        "task_id": "t-wallet-routing",
        "agent_name": "Wallet Routing Test Agent",
        "amount": 10.0,
        "currency": "USD",
        "asset_id": asset_id,
    })
    assert pact_resp.status_code == 201, pact_resp.get_json()
    pact_id = pact_resp.get_json()["pact_id"]

    assert client.post(f"/api/pact/approve/{pact_id}").status_code == 200
    settle_resp = client.post(f"/api/pact/settle/{pact_id}")
    assert settle_resp.status_code == 200, settle_resp.get_json()
    run_id = settle_resp.get_json()["run_id"]

    # Now invoke royalty/settle which is the call path that triggers
    # provider.settle() — pact_settle alone only records the agent_run.
    royalty_resp = client.post("/api/royalty/settle", json={"run_id": run_id})
    return royalty_resp.get_json(), run_id


def test_sepolia_provider_receives_agent_wallet_as_to_address():
    """The whole point: register an Agent with a wallet_address, settle a
    pact billed to it, and confirm the Sepolia-named provider got that
    same address as the to_address kwarg."""
    provider = _RecordingProvider(name="sepolia")
    client, db_path = _make_client(provider)
    try:
        asset_id = _register_asset(client, wallet_address=_AGENT_WALLET)
        _create_pact_and_settle(client, asset_id)
    finally:
        os.unlink(db_path)

    assert len(provider.calls) == 1
    assert provider.calls[0].get("to_address") == _AGENT_WALLET


def test_sepolia_provider_receives_none_when_asset_has_no_wallet():
    """Asset registered without a wallet → route still sniffs sepolia and
    passes to_address=None so the provider falls back to env default /
    self.from_address. The KEY must be present so the contract is
    explicit, not silently absent."""
    provider = _RecordingProvider(name="sepolia")
    client, db_path = _make_client(provider)
    try:
        asset_id = _register_asset(client)  # no wallet_address
        _create_pact_and_settle(client, asset_id)
    finally:
        os.unlink(db_path)

    assert len(provider.calls) == 1
    assert "to_address" in provider.calls[0]
    assert provider.calls[0]["to_address"] is None


def test_non_sepolia_provider_does_not_receive_to_address():
    """Mock/anvil providers MUST NOT see the to_address kwarg — the
    route's sniff is what protects their unchanged signatures. If this
    test ever fails, mock.settle() will TypeError on the new kwarg.
    """
    provider = _RecordingProvider(name="mock")
    client, db_path = _make_client(provider)
    try:
        asset_id = _register_asset(client, wallet_address=_AGENT_WALLET)
        _create_pact_and_settle(client, asset_id)
    finally:
        os.unlink(db_path)

    assert len(provider.calls) == 1
    assert "to_address" not in provider.calls[0]
