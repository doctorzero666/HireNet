"""
AnvilSettlementProvider unit tests.

Stubs the web3 boundary via the `w3_factory` constructor hook so these tests
never need a running Anvil node. They prove:
  - constructor validation fires loudly on missing / malformed env values;
  - settle() submits a signed tx, returns 0x-prefixed tx_hash, next_status=SETTLING;
  - settle() degrades gracefully on ConnectionError / Web3Exception;
  - check_status() maps receipt.status correctly across {1, 0, None};
  - TransactionNotFound / RPC errors degrade to SETTLING (not FAILED);
  - the settlement factory wires `anvil` correctly to env vars.

These tests do NOT prove the wire shape matches Anvil's real JSON-RPC. The
demo path covers that — `start.sh` boots a real Anvil and the e2e flow
fetches `cast receipt` for the returned tx_hash.
"""
import pytest

# If web3/eth_account aren't installed yet (e.g. pre `pip install`), skip
# this file entirely rather than erroring during collection — keeps the
# rest of the 500+ test suite green on a fresh checkout.
pytest.importorskip("web3")
pytest.importorskip("eth_account")

import os

import requests
from web3.exceptions import TransactionNotFound, Web3Exception

from app.services.anvil_settlement import (
    AnvilSettlementProvider,
    _encode_payment_data,
    _is_hex_prefixed_bytes,
)
from app.services.settlement import (
    SettlementProvider,
    SettlementStatus,
    get_provider,
)


# Anvil's default first account private key — publicly known, used by every
# Foundry user. Safe to commit to a test file; this is not a real-money key.
ANVIL_DEFAULT_KEY = (
    "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
)
ANVIL_DEFAULT_TO = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeHexBytes:
    """Mimics web3's HexBytes return from send_raw_transaction.

    Stores whatever the test gave it verbatim — including absent 0x prefix
    — so the provider's own normalisation path stays exercised.
    """
    def __init__(self, hex_str: str):
        self._hex = hex_str

    def hex(self) -> str:
        return self._hex


class FakeEth:
    """Captures every call made through `w3.eth.*` so tests can assert on
    nonce/gas/data shape and inject scripted responses.
    """

    def __init__(
        self,
        *,
        nonce: int = 0,
        gas_price: int = 1_000_000_000,
        send_returns=None,
        send_raises: Exception | None = None,
        receipt=None,  # dict, None (returns None), or "MISSING" (raises TransactionNotFound)
        receipt_raises: Exception | None = None,
    ):
        self.gas_price = gas_price
        self._nonce = nonce
        self._send_returns = send_returns or FakeHexBytes("0x" + "ab" * 32)
        self._send_raises = send_raises
        self._receipt = receipt
        self._receipt_raises = receipt_raises
        self.sent_raw_txs: list = []
        self.requested_addresses: list = []
        self.requested_tx_hashes: list = []

    def get_transaction_count(self, address):
        self.requested_addresses.append(address)
        return self._nonce

    def send_raw_transaction(self, raw):
        self.sent_raw_txs.append(raw)
        if self._send_raises is not None:
            raise self._send_raises
        return self._send_returns

    def get_transaction_receipt(self, tx_hash):
        self.requested_tx_hashes.append(tx_hash)
        if self._receipt_raises is not None:
            raise self._receipt_raises
        if self._receipt == "MISSING":
            raise TransactionNotFound(f"tx {tx_hash} not found")
        return self._receipt


class FakeWeb3:
    """Minimum surface AnvilSettlementProvider touches: just `.eth`."""
    def __init__(self, eth: FakeEth):
        self.eth = eth


def _make_provider(**overrides) -> AnvilSettlementProvider:
    base = dict(
        rpc_url="http://localhost:8545",
        from_key=ANVIL_DEFAULT_KEY,
        to_address=ANVIL_DEFAULT_TO,
        w3_factory=lambda url: FakeWeb3(FakeEth()),
    )
    base.update(overrides)
    return AnvilSettlementProvider(**base)


# ---------------------------------------------------------------------------
# Constructor validation — each missing/invalid field must fail loudly
# ---------------------------------------------------------------------------


def test_init_requires_rpc_url():
    with pytest.raises(ValueError, match="ANVIL_RPC_URL"):
        _make_provider(rpc_url="")


def test_init_requires_from_key():
    with pytest.raises(ValueError, match="ANVIL_FROM_KEY"):
        _make_provider(from_key="")


def test_init_requires_to_address():
    with pytest.raises(ValueError, match="ANVIL_TO_ADDRESS"):
        _make_provider(to_address="")


def test_init_rejects_malformed_from_key():
    with pytest.raises(ValueError, match="ANVIL_FROM_KEY"):
        _make_provider(from_key="not-hex")


def test_init_rejects_unprefixed_from_key():
    # Same key bytes but missing 0x prefix should be loud, not silent.
    with pytest.raises(ValueError, match="ANVIL_FROM_KEY"):
        _make_provider(from_key=ANVIL_DEFAULT_KEY[2:])


def test_init_rejects_bad_to_address():
    with pytest.raises(ValueError, match="ANVIL_TO_ADDRESS"):
        _make_provider(to_address="0xnotanaddress")


def test_provider_satisfies_abc():
    # If SettlementProvider's contract grows a new abstractmethod, this
    # construction will fail — that's the regression we want.
    p = _make_provider()
    assert isinstance(p, SettlementProvider)
    assert p.name == "anvil"


# ---------------------------------------------------------------------------
# settle() happy path
# ---------------------------------------------------------------------------


def test_settle_returns_success_and_settling_status():
    eth = FakeEth(nonce=7, send_returns=FakeHexBytes("0x" + "cd" * 32))
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    result = provider.settle(
        payee_id="creator-job-design",
        amount=5400,
        currency="USDC",
        chain="ANVIL",
    )

    assert result.success is True
    assert result.error is None
    assert result.tx_hash.startswith("0x")
    assert len(result.tx_hash) == 66  # 0x + 64 hex chars
    assert result.next_status == SettlementStatus.SETTLING


def test_settle_uses_correct_nonce_and_signs_tx():
    eth = FakeEth(nonce=42)
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    provider.settle("alice", 100, "USDC", None)

    # Provider must read the nonce for the from_address derived from from_key.
    assert eth.requested_addresses == [provider._account.address]
    # And submit exactly one signed raw tx (bytes shape, not the dict).
    assert len(eth.sent_raw_txs) == 1
    raw = eth.sent_raw_txs[0]
    assert isinstance(raw, (bytes, bytearray)) or hasattr(raw, "hex")


def test_settle_normalises_tx_hash_to_0x_prefix():
    # Even if HexBytes.hex() returned without 0x, the provider should patch it.
    eth = FakeEth(send_returns=FakeHexBytes("aa" * 32))
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    result = provider.settle("alice", 100, "USDC", "ANVIL")

    assert result.tx_hash.startswith("0x")


# ---------------------------------------------------------------------------
# settle() error handling — provider must never raise into the route layer
# ---------------------------------------------------------------------------


def test_settle_degrades_on_connection_error():
    eth = FakeEth(send_raises=requests.exceptions.ConnectionError("anvil down"))
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    result = provider.settle("alice", 100, "USDC", "ANVIL")

    assert result.success is False
    assert "Anvil RPC unreachable" in result.error


def test_settle_degrades_on_web3_exception():
    eth = FakeEth(send_raises=Web3Exception("nonce too low"))
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    result = provider.settle("alice", 100, "USDC", "ANVIL")

    assert result.success is False
    assert "Anvil tx rejected" in result.error


def test_settle_degrades_on_unexpected_exception():
    # A surprise — e.g. signing helper raises something we didn't anticipate.
    # The provider's last-resort guard must still return a SettlementResult
    # so the route layer can flip the run to `failed` cleanly.
    eth = FakeEth(send_raises=RuntimeError("kaboom"))
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    result = provider.settle("alice", 100, "USDC", "ANVIL")

    assert result.success is False
    assert "Anvil unexpected error" in result.error


# ---------------------------------------------------------------------------
# check_status() — receipt mapping + degrade-to-SETTLING posture
# ---------------------------------------------------------------------------


def test_check_status_settled_on_status_1():
    eth = FakeEth(receipt={"status": 1})
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    assert provider.check_status("0xabc") == SettlementStatus.SETTLED


def test_check_status_failed_on_status_0():
    eth = FakeEth(receipt={"status": 0})
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    assert provider.check_status("0xabc") == SettlementStatus.FAILED


def test_check_status_settling_when_receipt_missing():
    eth = FakeEth(receipt="MISSING")
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    assert provider.check_status("0xabc") == SettlementStatus.SETTLING


def test_check_status_settling_on_rpc_error():
    eth = FakeEth(receipt_raises=requests.exceptions.ConnectionError("rpc down"))
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    # Transient outage must NOT poison the run — keep it polling.
    assert provider.check_status("0xabc") == SettlementStatus.SETTLING


def test_check_status_settling_on_web3_exception():
    eth = FakeEth(receipt_raises=Web3Exception("rpc weirdness"))
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    assert provider.check_status("0xabc") == SettlementStatus.SETTLING


def test_check_status_normalises_unprefixed_tx_hash():
    eth = FakeEth(receipt={"status": 1})
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    provider.check_status("abcdef")

    assert eth.requested_tx_hashes == ["0xabcdef"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_encode_payment_data_shape():
    blob = _encode_payment_data("alice", 100, "USDC", "ANVIL")
    assert blob == b"hirenet:alice:100:USDC:ANVIL"


def test_encode_payment_data_handles_none_chain():
    blob = _encode_payment_data("alice", 100, "USDC", None)
    assert blob == b"hirenet:alice:100:USDC:"


def test_is_hex_prefixed_bytes():
    assert _is_hex_prefixed_bytes("0x" + "ab" * 32, 32) is True
    assert _is_hex_prefixed_bytes("ab" * 32, 32) is False  # no 0x
    assert _is_hex_prefixed_bytes("0x" + "ab" * 31, 32) is False  # wrong len
    assert _is_hex_prefixed_bytes("0x" + "zz" * 32, 32) is False  # not hex
    assert _is_hex_prefixed_bytes("", 32) is False
    assert _is_hex_prefixed_bytes(None, 32) is False


# ---------------------------------------------------------------------------
# Factory wiring — get_provider("anvil") reads env, fails loudly on missing
# ---------------------------------------------------------------------------


def test_factory_builds_anvil_provider_when_env_complete(monkeypatch):
    monkeypatch.setenv("ANVIL_RPC_URL", "http://localhost:8545")
    monkeypatch.setenv("ANVIL_FROM_KEY", ANVIL_DEFAULT_KEY)
    monkeypatch.setenv("ANVIL_TO_ADDRESS", ANVIL_DEFAULT_TO)

    provider = get_provider("anvil")

    assert isinstance(provider, AnvilSettlementProvider)
    assert provider.rpc_url == "http://localhost:8545"
    assert provider.name == "anvil"


def test_factory_anvil_missing_from_key_raises(monkeypatch):
    monkeypatch.setenv("ANVIL_RPC_URL", "http://localhost:8545")
    monkeypatch.delenv("ANVIL_FROM_KEY", raising=False)
    monkeypatch.setenv("ANVIL_TO_ADDRESS", ANVIL_DEFAULT_TO)

    with pytest.raises(ValueError, match="ANVIL_FROM_KEY"):
        get_provider("anvil")


def test_factory_anvil_missing_to_address_raises(monkeypatch):
    monkeypatch.setenv("ANVIL_RPC_URL", "http://localhost:8545")
    monkeypatch.setenv("ANVIL_FROM_KEY", ANVIL_DEFAULT_KEY)
    monkeypatch.delenv("ANVIL_TO_ADDRESS", raising=False)

    with pytest.raises(ValueError, match="ANVIL_TO_ADDRESS"):
        get_provider("anvil")
