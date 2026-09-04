"""
Phase 3 — Anvil-based settlement provider (local-chain demo).

Sends a 0-ETH transaction on a local Anvil node so the demo flow gets a real
on-chain `tx_hash`. Payment metadata (payee_id, amount, currency, chain) is
stuffed into `tx.data` as a single utf-8 blob — the receipt is verifiable
via `cast receipt <hash>` or a JSON-RPC `eth_getTransactionReceipt`.

⚠️ DEMO ONLY — does not move real funds and does not pay creators on-chain.
Concrete stubs you must remove before any real-money deployment:

  - `payee_id` is a string (creator_id from the royalty ledger), NOT an ETH
    address. Every tx goes to the single, env-configured `ANVIL_TO_ADDRESS`.
    A production rail needs an identity → wallet-address registry.

  - `value=0`. The integer `amount` (in cents) is written into `tx.data`
    as a label only. Moving real funds needs an ERC-20 transfer with the
    correct token decimal scaling (USDC=6, not 0).

What this provider IS good for: proving the SettlementProvider abstraction
works against a real chain (real signatures, real nonces, real receipts),
without testnet credentials or rate limits.

Same SettlementProvider contract as mock + cobo, so swap is a single env
var: `HIRENET_SETTLEMENT_PROVIDER=anvil`.
"""
from typing import Callable, Optional

import requests
from eth_account import Account
from web3 import Web3
from web3.exceptions import TransactionNotFound, Web3Exception

from app.services.settlement import (
    SettlementProvider,
    SettlementResult,
    SettlementStatus,
)


# Anvil / Foundry default chain id. Overridable via constructor for tests
# that want to assert the signed tx carries the expected chainId field.
ANVIL_DEFAULT_CHAIN_ID = 31337

# Flat gas budget for a 0-ETH data-carrying tx. ~21000 base + per-byte
# data cost; 100k is comfortably above the worst-case payload here
# (`hirenet:<creator_id>:<amount>:<currency>:<chain>` is well under 200 B).
# Anvil doesn't care about under/over-estimation in the demo, but keeping
# the value explicit makes the signed tx deterministic for unit tests.
_DEMO_GAS_LIMIT = 100_000


class AnvilSettlementProvider(SettlementProvider):
    """Submit a 0-ETH metadata tx to a local Anvil node.

    Constructor reads no env vars — the factory in `app.services.settlement`
    does that and passes values in. This mirrors `CoboSettlementProvider`
    and lets tests build a provider with stubbed `w3_factory` cleanly.
    """

    name = "anvil"

    def __init__(
        self,
        rpc_url: str,
        from_key: str,
        to_address: str,
        *,
        chain_id: int = ANVIL_DEFAULT_CHAIN_ID,
        timeout_seconds: int = 15,
        w3_factory: Optional[Callable[[str], Web3]] = None,
    ):
        if not rpc_url:
            raise ValueError("ANVIL_RPC_URL is required")
        if not from_key:
            raise ValueError("ANVIL_FROM_KEY is required")
        if not to_address:
            raise ValueError("ANVIL_TO_ADDRESS is required")

        # Validate hex shape up front so a misconfigured env fails at app
        # startup (loud, with the offending field named) rather than at
        # first settle() with a cryptic eth_account error mid-route.
        if not _is_hex_prefixed_bytes(from_key, expected_bytes=32):
            raise ValueError(
                "ANVIL_FROM_KEY must be a 0x-prefixed 32-byte hex string "
                f"(66 chars total): got {len(from_key)} chars"
            )
        if not Web3.is_address(to_address):
            raise ValueError(
                f"ANVIL_TO_ADDRESS is not a valid EVM address: {to_address!r}"
            )

        self.rpc_url = rpc_url
        self.from_key = from_key
        self.to_address = Web3.to_checksum_address(to_address)
        self.chain_id = chain_id
        self.timeout = timeout_seconds

        # w3_factory injection point: tests pass a fake that returns a
        # stub-Web3 object so the unit tests don't need a running node.
        factory = w3_factory or (
            lambda url: Web3(
                Web3.HTTPProvider(url, request_kwargs={"timeout": timeout_seconds})
            )
        )
        self._w3 = factory(rpc_url)
        # Derive sender address once. Account.from_key validates the curve
        # point — a malformed key past the hex check above still raises here.
        self._account = Account.from_key(from_key)

    # ------------------------------------------------------------------
    # SettlementProvider contract
    # ------------------------------------------------------------------

    def settle(
        self,
        payee_id: str,
        amount: int,
        currency: str,
        chain: str | None,
    ) -> SettlementResult:
        try:
            data_blob = _encode_payment_data(payee_id, amount, currency, chain)
            nonce = self._w3.eth.get_transaction_count(self._account.address)
            tx = {
                "to": self.to_address,
                "value": 0,
                "data": data_blob,
                "gas": _DEMO_GAS_LIMIT,
                "gasPrice": self._w3.eth.gas_price,
                "nonce": nonce,
                "chainId": self.chain_id,
            }
            signed = self._account.sign_transaction(tx)
            # web3 6.x exposes `rawTransaction`; web3 7.x renames it to
            # `raw_transaction`. Tolerate both so a future upgrade doesn't
            # silently break the demo path.
            raw_tx = getattr(signed, "rawTransaction", None)
            if raw_tx is None:
                raw_tx = getattr(signed, "raw_transaction", None)
            if raw_tx is None:
                return SettlementResult(
                    success=False,
                    error="Signed tx missing raw bytes (web3 API surface changed?)",
                )
            tx_hash_bytes = self._w3.eth.send_raw_transaction(raw_tx)
        except (requests.exceptions.ConnectionError, ConnectionError) as exc:
            return SettlementResult(
                success=False, error=f"Anvil RPC unreachable: {exc}"
            )
        except (Web3Exception, ValueError) as exc:
            return SettlementResult(
                success=False, error=f"Anvil tx rejected: {exc}"
            )
        except Exception as exc:
            # Last-resort guard: provider must never raise into the route
            # layer — the agent_runs state machine relies on settle() always
            # returning a SettlementResult so it can flip to failed.
            return SettlementResult(
                success=False, error=f"Anvil unexpected error: {exc}"
            )

        # `tx_hash_bytes` is HexBytes in normal web3; `.hex()` gives the
        # 0x-prefixed string the rest of the system stores in `agent_runs`.
        tx_hash_str = tx_hash_bytes.hex() if hasattr(tx_hash_bytes, "hex") else str(tx_hash_bytes)
        if not tx_hash_str.startswith("0x"):
            tx_hash_str = "0x" + tx_hash_str
        return SettlementResult(
            success=True,
            tx_hash=tx_hash_str,
            next_status=SettlementStatus.SETTLING,
        )

    def check_status(self, tx_hash: str) -> SettlementStatus:
        """Read the receipt and translate to SettlementStatus.

        Degrades to SETTLING (not FAILED) on transport / RPC errors — same
        posture as `CoboSettlementProvider.check_status`: a transient outage
        shouldn't poison an in-flight run, and the route layer can keep
        polling. Only an explicit `receipt.status == 0` flips to FAILED.
        """
        normalized = tx_hash if tx_hash.startswith("0x") else f"0x{tx_hash}"
        try:
            receipt = self._w3.eth.get_transaction_receipt(normalized)
        except TransactionNotFound:
            return SettlementStatus.SETTLING
        except (requests.exceptions.RequestException, Web3Exception, ConnectionError):
            return SettlementStatus.SETTLING
        except Exception:
            return SettlementStatus.SETTLING

        if receipt is None:
            return SettlementStatus.SETTLING

        status_field = receipt.get("status") if isinstance(receipt, dict) else getattr(receipt, "status", None)
        if status_field == 1:
            return SettlementStatus.SETTLED
        if status_field == 0:
            return SettlementStatus.FAILED
        return SettlementStatus.SETTLING


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _encode_payment_data(
    payee_id: str, amount: int, currency: str, chain: str | None
) -> bytes:
    """Serialize the royalty metadata into `tx.data` bytes.

    Format: `hirenet:<payee_id>:<amount>:<currency>:<chain or "">`. Plain
    utf-8, no escaping — payee_id / currency / chain are expected to be
    ascii-clean (creator_id is a slug, currency is "USDC", chain is short).
    The blob is purely a demo affordance: a verifier running
    `cast receipt --decode` sees what was settled, but on-chain semantics
    are unaware of it.
    """
    chain_part = chain or ""
    text = f"hirenet:{payee_id}:{amount}:{currency}:{chain_part}"
    return text.encode("utf-8")


def _is_hex_prefixed_bytes(value: str, expected_bytes: int) -> bool:
    """Return True iff `value` is `0x` + exactly `2*expected_bytes` hex chars."""
    if not isinstance(value, str) or not value.startswith("0x"):
        return False
    if len(value) != 2 + 2 * expected_bytes:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True
