"""
SepoliaSettlementProvider unit tests.

Same shape as test_anvil_settlement.py — w3 boundary is stubbed via the
`w3_factory` constructor hook, so these tests never need network access.

Specific to Sepolia vs Anvil:
  - constructor validates SEPOLIA_FROM_ADDRESS matches the address derived
    from SEPOLIA_PRIVATE_KEY (Anvil instead takes an arbitrary to-address);
  - settle() submits a non-zero `value` (the demo 0.0001 ETH transfer);
  - check_status enforces a configurable confirmation depth before
    promoting status==1 to SETTLED;
  - factory under name="sepolia" reads SEPOLIA_* env vars.
"""
import pytest

# Skip cleanly if web3/eth_account aren't installed yet — same posture as
# tests/test_anvil_settlement.py, keeps the rest of the suite green on a
# fresh checkout.
pytest.importorskip("web3")
pytest.importorskip("eth_account")

import requests
from eth_account import Account
from web3.exceptions import TransactionNotFound, Web3Exception

from app.services.sepolia_settlement import (
    SEPOLIA_CHAIN_ID,
    SepoliaSettlementProvider,
    _encode_payment_data,
    _is_hex_prefixed_bytes,
)
from app.services.settlement import (
    SettlementProvider,
    SettlementStatus,
    get_provider,
)


# Anvil's default first account private key — publicly known, used by every
# Foundry user. Safe to commit; not a real-money key. We re-use it as a
# Sepolia "test wallet" here purely because the tests stub the RPC away.
TEST_PRIVATE_KEY = (
    "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
)
TEST_FROM_ADDRESS = Account.from_key(TEST_PRIVATE_KEY).address


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeHexBytes:
    """Mimics web3's HexBytes return from send_raw_transaction."""
    def __init__(self, hex_str: str):
        self._hex = hex_str

    def hex(self) -> str:
        return self._hex


class FakeEth:
    """Captures every call made through `w3.eth.*` so tests can assert on
    nonce/gas/value/data shape and inject scripted responses.
    """

    def __init__(
        self,
        *,
        nonce: int = 0,
        gas_price: int = 1_000_000_000,
        block_number: int = 100,
        send_returns=None,
        send_raises: Exception | None = None,
        receipt=None,
        receipt_raises: Exception | None = None,
        block_number_raises: Exception | None = None,
    ):
        self.gas_price = gas_price
        self._block_number = block_number
        self._block_number_raises = block_number_raises
        self._nonce = nonce
        self._send_returns = send_returns or FakeHexBytes("0x" + "ab" * 32)
        self._send_raises = send_raises
        self._receipt = receipt
        self._receipt_raises = receipt_raises
        self.sent_raw_txs: list = []
        self.requested_addresses: list = []
        self.requested_tx_hashes: list = []
        self.last_tx_payload = None

    @property
    def block_number(self):
        if self._block_number_raises is not None:
            raise self._block_number_raises
        return self._block_number

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
    """Minimum surface SepoliaSettlementProvider touches: just `.eth`."""
    def __init__(self, eth: FakeEth):
        self.eth = eth


def _make_provider(**overrides) -> SepoliaSettlementProvider:
    base = dict(
        rpc_url="https://eth-sepolia.test/rpc",
        from_key=TEST_PRIVATE_KEY,
        from_address=TEST_FROM_ADDRESS,
        w3_factory=lambda url: FakeWeb3(FakeEth()),
    )
    base.update(overrides)
    return SepoliaSettlementProvider(**base)


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_init_requires_rpc_url():
    with pytest.raises(ValueError, match="SEPOLIA_RPC_URL"):
        _make_provider(rpc_url="")


def test_init_requires_private_key():
    with pytest.raises(ValueError, match="SEPOLIA_PRIVATE_KEY"):
        _make_provider(from_key="")


def test_init_requires_from_address():
    with pytest.raises(ValueError, match="SEPOLIA_FROM_ADDRESS"):
        _make_provider(from_address="")


def test_init_rejects_malformed_private_key():
    with pytest.raises(ValueError, match="SEPOLIA_PRIVATE_KEY"):
        _make_provider(from_key="not-hex")


def test_init_rejects_unprefixed_private_key():
    with pytest.raises(ValueError, match="SEPOLIA_PRIVATE_KEY"):
        _make_provider(from_key=TEST_PRIVATE_KEY[2:])


def test_init_rejects_bad_from_address():
    with pytest.raises(ValueError, match="SEPOLIA_FROM_ADDRESS"):
        _make_provider(from_address="0xnotanaddress")


def test_init_rejects_mismatched_from_address():
    # Valid-shape address but it isn't the one derived from the private key
    # — the boot-time check should refuse to start.
    other_address = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
    assert other_address.lower() != TEST_FROM_ADDRESS.lower()
    with pytest.raises(ValueError, match="does not match"):
        _make_provider(from_address=other_address)


def test_provider_satisfies_abc():
    p = _make_provider()
    assert isinstance(p, SettlementProvider)
    assert p.name == "sepolia"
    assert p.chain_id == SEPOLIA_CHAIN_ID


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
        chain="SEPOLIA",
    )

    assert result.success is True
    assert result.error is None
    assert result.tx_hash.startswith("0x")
    assert len(result.tx_hash) == 66  # 0x + 64 hex chars
    assert result.next_status == SettlementStatus.SETTLING


def test_settle_uses_correct_nonce_for_derived_address():
    eth = FakeEth(nonce=42)
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    provider.settle("alice", 100, "USDC", None)

    # Nonce is read for the address derived from the private key, which is
    # also what we stored as from_address after the match check.
    assert eth.requested_addresses == [provider.from_address]
    assert len(eth.sent_raw_txs) == 1


def test_settle_normalises_tx_hash_to_0x_prefix():
    eth = FakeEth(send_returns=FakeHexBytes("aa" * 32))
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    result = provider.settle("alice", 100, "USDC", "SEPOLIA")

    assert result.tx_hash.startswith("0x")


def test_settle_value_is_nonzero_demo_amount():
    # 0.0001 ETH = 10^14 wei. The demo specifically wants a non-zero value
    # so Etherscan shows ETH actually moved. Guard against a refactor that
    # accidentally reverts to a 0-value tx.
    p = _make_provider()
    assert p.value_wei == 100_000_000_000_000


# ---------------------------------------------------------------------------
# settle() error handling — never raise into the route layer
# ---------------------------------------------------------------------------


def test_settle_degrades_on_connection_error():
    eth = FakeEth(send_raises=requests.exceptions.ConnectionError("sepolia rpc down"))
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    result = provider.settle("alice", 100, "USDC", "SEPOLIA")

    assert result.success is False
    assert "Sepolia RPC unreachable" in result.error


def test_settle_degrades_on_web3_exception():
    eth = FakeEth(send_raises=Web3Exception("nonce too low"))
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    result = provider.settle("alice", 100, "USDC", "SEPOLIA")

    assert result.success is False
    assert "Sepolia tx rejected" in result.error


def test_settle_degrades_on_unexpected_exception():
    eth = FakeEth(send_raises=RuntimeError("kaboom"))
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    result = provider.settle("alice", 100, "USDC", "SEPOLIA")

    assert result.success is False
    assert "Sepolia unexpected error" in result.error


# ---------------------------------------------------------------------------
# check_status() — receipt + confirmations mapping
# ---------------------------------------------------------------------------


def test_check_status_settled_when_confirmations_met():
    # status==1, receipt at block 95, head at block 100 → 6 confirmations,
    # well above required=1.
    eth = FakeEth(receipt={"status": 1, "blockNumber": 95}, block_number=100)
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    assert provider.check_status("0xabc") == SettlementStatus.SETTLED


def test_check_status_settling_when_below_required_confirmations():
    # Bump the bar to 5 confirmations; head exactly equals block → 1
    # confirmation, which is < 5.
    eth = FakeEth(receipt={"status": 1, "blockNumber": 100}, block_number=100)
    provider = _make_provider(
        w3_factory=lambda url: FakeWeb3(eth),
        required_confirmations=5,
    )

    assert provider.check_status("0xabc") == SettlementStatus.SETTLING


def test_check_status_settled_when_exactly_required_confirmations():
    # required=1 + head==block → confirmations = 1, just meets the bar.
    eth = FakeEth(receipt={"status": 1, "blockNumber": 100}, block_number=100)
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    assert provider.check_status("0xabc") == SettlementStatus.SETTLED


def test_check_status_failed_on_status_0():
    eth = FakeEth(receipt={"status": 0, "blockNumber": 100}, block_number=100)
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


def test_check_status_settling_when_block_number_unreadable():
    # We have a successful receipt but the head-block read blows up.
    # Don't downgrade a truly-settled run to FAILED on a blip — stay SETTLING.
    eth = FakeEth(
        receipt={"status": 1, "blockNumber": 95},
        block_number_raises=requests.exceptions.ConnectionError("rpc blip"),
    )
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    assert provider.check_status("0xabc") == SettlementStatus.SETTLING


def test_check_status_normalises_unprefixed_tx_hash():
    eth = FakeEth(receipt={"status": 1, "blockNumber": 100}, block_number=100)
    provider = _make_provider(w3_factory=lambda url: FakeWeb3(eth))

    provider.check_status("abcdef")

    assert eth.requested_tx_hashes == ["0xabcdef"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_encode_payment_data_shape():
    blob = _encode_payment_data("alice", 100, "USDC", "SEPOLIA")
    assert blob == b"hirenet:alice:100:USDC:SEPOLIA"


def test_encode_payment_data_handles_none_chain():
    blob = _encode_payment_data("alice", 100, "USDC", None)
    assert blob == b"hirenet:alice:100:USDC:"


def test_is_hex_prefixed_bytes():
    assert _is_hex_prefixed_bytes("0x" + "ab" * 32, 32) is True
    assert _is_hex_prefixed_bytes("ab" * 32, 32) is False
    assert _is_hex_prefixed_bytes("0x" + "ab" * 31, 32) is False
    assert _is_hex_prefixed_bytes("0x" + "zz" * 32, 32) is False
    assert _is_hex_prefixed_bytes("", 32) is False
    assert _is_hex_prefixed_bytes(None, 32) is False


# ---------------------------------------------------------------------------
# Factory wiring — get_provider("sepolia") reads env, fails loudly on missing
# ---------------------------------------------------------------------------


def test_factory_builds_sepolia_provider_when_env_complete(monkeypatch):
    monkeypatch.setenv("SEPOLIA_RPC_URL", "https://eth-sepolia.test/rpc")
    monkeypatch.setenv("SEPOLIA_PRIVATE_KEY", TEST_PRIVATE_KEY)
    monkeypatch.setenv("SEPOLIA_FROM_ADDRESS", TEST_FROM_ADDRESS)

    provider = get_provider("sepolia")

    assert isinstance(provider, SepoliaSettlementProvider)
    assert provider.rpc_url == "https://eth-sepolia.test/rpc"
    assert provider.name == "sepolia"
    assert provider.chain_id == SEPOLIA_CHAIN_ID


def test_factory_sepolia_missing_private_key_raises(monkeypatch):
    monkeypatch.setenv("SEPOLIA_RPC_URL", "https://eth-sepolia.test/rpc")
    monkeypatch.delenv("SEPOLIA_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("SEPOLIA_FROM_ADDRESS", TEST_FROM_ADDRESS)

    with pytest.raises(ValueError, match="SEPOLIA_PRIVATE_KEY"):
        get_provider("sepolia")


def test_factory_sepolia_missing_from_address_raises(monkeypatch):
    monkeypatch.setenv("SEPOLIA_RPC_URL", "https://eth-sepolia.test/rpc")
    monkeypatch.setenv("SEPOLIA_PRIVATE_KEY", TEST_PRIVATE_KEY)
    monkeypatch.delenv("SEPOLIA_FROM_ADDRESS", raising=False)

    with pytest.raises(ValueError, match="SEPOLIA_FROM_ADDRESS"):
        get_provider("sepolia")


def test_factory_sepolia_missing_rpc_url_raises(monkeypatch):
    monkeypatch.delenv("SEPOLIA_RPC_URL", raising=False)
    monkeypatch.setenv("SEPOLIA_PRIVATE_KEY", TEST_PRIVATE_KEY)
    monkeypatch.setenv("SEPOLIA_FROM_ADDRESS", TEST_FROM_ADDRESS)

    with pytest.raises(ValueError, match="SEPOLIA_RPC_URL"):
        get_provider("sepolia")


# ---------------------------------------------------------------------------
# MCP wallet integration — to_address routing in settle()
# ---------------------------------------------------------------------------


# A second valid EVM address distinct from the test sender. Anvil account #1's
# public address — well-known throwaway, safe to commit. Used as a stand-in
# for "the SkillAsset's wallet_address".
_AGENT_WALLET = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
_ENV_DEFAULT_WALLET = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"  # Anvil #2


class _CapturingEth(FakeEth):
    """FakeEth that surfaces the last signed tx's `to` field so we can assert
    on it. send_raw_transaction's raw bytes don't expose the decoded payload,
    so we hook before signing by intercepting send_raw_transaction's tx dict
    on the account-level signer instead."""

    def send_raw_transaction(self, raw):
        # The actual signed tx isn't easily decoded without recovering it.
        # Tests inspect `last_tx_payload` set by a wrapper around sign.
        return super().send_raw_transaction(raw)


def _patch_account_capture(monkeypatch):
    """Install a wrapper around eth_account.LocalAccount.sign_transaction that
    records each invocation's tx dict on a module-level list, so tests can
    assert on the `to` field of the signed tx without decoding raw bytes.

    Patching LocalAccount (not Account) because that's the instance method
    settle() actually invokes via `self._account.sign_transaction(tx)`; the
    instance binding gives the wrapper a clean (instance, tx_dict) shape.
    """
    from eth_account.signers.local import LocalAccount
    original = LocalAccount.sign_transaction
    captured: list[dict] = []

    def wrapper(self, tx, *args, **kwargs):
        captured.append(dict(tx))
        return original(self, tx, *args, **kwargs)

    monkeypatch.setattr(LocalAccount, "sign_transaction", wrapper)
    return captured


def test_settle_uses_explicit_to_address_override(monkeypatch):
    """Per-call to_address (Agent's registered wallet) wins over env default and self."""
    captured = _patch_account_capture(monkeypatch)
    provider = _make_provider(default_to_address=_ENV_DEFAULT_WALLET)

    result = provider.settle(
        payee_id="creator-x", amount=100, currency="USDC", chain=None,
        to_address=_AGENT_WALLET,
    )
    assert result.success is True
    assert len(captured) == 1
    # to_address arg must override default_to_address
    assert captured[0]["to"].lower() == _AGENT_WALLET.lower()


def test_settle_uses_default_to_address_when_no_override(monkeypatch):
    """No per-call override → SEPOLIA_TO_ADDRESS env default is used."""
    captured = _patch_account_capture(monkeypatch)
    provider = _make_provider(default_to_address=_ENV_DEFAULT_WALLET)

    result = provider.settle("creator-x", 100, "USDC", None)
    assert result.success is True
    assert captured[0]["to"].lower() == _ENV_DEFAULT_WALLET.lower()


def test_settle_falls_back_to_from_address_when_no_default(monkeypatch):
    """No per-call override AND no env default → self.from_address.
    Preserves the pre-wallet-integration self-transfer demo so misconfigs
    don't break the existing flow."""
    captured = _patch_account_capture(monkeypatch)
    provider = _make_provider()  # no default_to_address

    result = provider.settle("creator-x", 100, "USDC", None)
    assert result.success is True
    assert captured[0]["to"].lower() == provider.from_address.lower()


def test_settle_explicit_to_address_none_is_same_as_omitted(monkeypatch):
    """Caller passing to_address=None (e.g. asset.wallet_address was NULL)
    must behave identically to not passing it at all."""
    captured = _patch_account_capture(monkeypatch)
    provider = _make_provider(default_to_address=_ENV_DEFAULT_WALLET)

    result = provider.settle("creator-x", 100, "USDC", None, to_address=None)
    assert result.success is True
    assert captured[0]["to"].lower() == _ENV_DEFAULT_WALLET.lower()


def test_settle_rejects_garbage_to_address():
    """A corrupted skill_assets row that leaked a non-address through validation
    must surface as a settlement error, not a chain-level exception."""
    provider = _make_provider()
    result = provider.settle(
        "creator-x", 100, "USDC", None,
        to_address="0xnotanaddress",
    )
    assert result.success is False
    assert "Invalid recipient address" in result.error


def test_init_rejects_malformed_default_to_address():
    """Misconfigured SEPOLIA_TO_ADDRESS env must fail at app boot, not at
    first settle() with a cryptic web3 error."""
    with pytest.raises(ValueError, match="SEPOLIA_TO_ADDRESS"):
        _make_provider(default_to_address="not-an-address")


def test_init_accepts_none_default_to_address():
    """Operator can leave SEPOLIA_TO_ADDRESS unset — provider boots fine,
    settle() falls through to self.from_address."""
    provider = _make_provider(default_to_address=None)
    assert provider.default_to_address is None


def test_init_normalises_default_to_address_to_checksum():
    """Lowercase env input is normalised to EIP-55 checksum so signed-tx
    `to` field stays consistent regardless of how the operator typed it."""
    provider = _make_provider(default_to_address=_ENV_DEFAULT_WALLET.lower())
    assert provider.default_to_address == _ENV_DEFAULT_WALLET


def test_factory_reads_sepolia_to_address_env(monkeypatch):
    """The factory wires SEPOLIA_TO_ADDRESS through to default_to_address."""
    monkeypatch.setenv("SEPOLIA_RPC_URL", "https://eth-sepolia.test/rpc")
    monkeypatch.setenv("SEPOLIA_PRIVATE_KEY", TEST_PRIVATE_KEY)
    monkeypatch.setenv("SEPOLIA_FROM_ADDRESS", TEST_FROM_ADDRESS)
    monkeypatch.setenv("SEPOLIA_TO_ADDRESS", _ENV_DEFAULT_WALLET)

    provider = get_provider("sepolia")
    assert provider.default_to_address == _ENV_DEFAULT_WALLET


def test_factory_empty_sepolia_to_address_means_no_default(monkeypatch):
    """An operator who set SEPOLIA_TO_ADDRESS= (empty) in .env must not
    crash the boot — empty string normalises to None so self.from_address
    remains the fallback."""
    monkeypatch.setenv("SEPOLIA_RPC_URL", "https://eth-sepolia.test/rpc")
    monkeypatch.setenv("SEPOLIA_PRIVATE_KEY", TEST_PRIVATE_KEY)
    monkeypatch.setenv("SEPOLIA_FROM_ADDRESS", TEST_FROM_ADDRESS)
    monkeypatch.setenv("SEPOLIA_TO_ADDRESS", "")

    provider = get_provider("sepolia")
    assert provider.default_to_address is None
