"""
Phase 3 — Sepolia testnet settlement provider.

Mirrors `AnvilSettlementProvider` 1:1 but talks to the public Sepolia testnet
via an HTTP RPC (Alchemy / Infura / your-favourite-provider) and submits a
tiny *real* ETH transfer (default 0.0001 ETH) carrying the royalty metadata
in `tx.data`. The receipt is verifiable on https://sepolia.etherscan.io.

Why a non-zero `value` here when Anvil uses 0?
  Anvil is a local sandbox — a 0-ETH metadata tx is enough to demonstrate the
  pipeline. Sepolia is a public testnet, and we want the demo to look like
  a real settlement: a faucet-funded wallet pays a faucet-funded sink, and
  Etherscan shows the value move. The amount is hard-coded at 0.0001 ETH so
  one faucet drip funds ~5000 demos.

Same SettlementProvider contract as mock / anvil / cobo, so swap is a single
env var: `HIRENET_SETTLEMENT_PROVIDER=sepolia`.

⚠️ Testnet ONLY. The royalty `amount` (in cents) is still written into
`tx.data` as a label; the ETH `value` is a fixed demo constant, not the
ledger amount. Production rails (Cobo / x402) move real funds and translate
ledger amount → token amount with the correct decimals.

Sender-address note: `SEPOLIA_FROM_ADDRESS` is validated to match the address
derived from `SEPOLIA_PRIVATE_KEY` at construction time. This catches the
"copy-pasted the wrong account" misconfig at boot, not at first settle().
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


# EIP-155 chain id for Sepolia. Hard-coded — there is no scenario where a
# provider called "sepolia" should sign for any other network.
SEPOLIA_CHAIN_ID = 11155111

# 0.0001 ETH per demo tx — small enough that a single Sepolia faucet drip
# (~0.5 ETH) funds thousands of runs, big enough to show a non-zero "Value"
# column on Etherscan so the demo reads as a real transfer.
_DEMO_VALUE_WEI = 100_000_000_000_000  # 0.0001 ETH = 10^14 wei

# Gas budget for a value-transfer with a short utf-8 data blob. 21000 base
# + per-byte data cost; 100k is comfortably above worst-case payload
# (`hirenet:<creator_id>:<amount>:<currency>:<chain>` is well under 200 B).
_DEMO_GAS_LIMIT = 100_000

# Minimum block depth before we call a tx settled. Sepolia reorgs are rare
# at any depth, so 1 confirmation is the right knob for demo latency. Bump
# this if you ever wire this provider into a real-money flow.
SEPOLIA_REQUIRED_CONFIRMATIONS = 1


class SepoliaSettlementProvider(SettlementProvider):
    """Submit a small ETH transfer carrying royalty metadata on Sepolia testnet.

    Constructor reads no env vars — the factory in `app.services.settlement`
    does that and passes values in. This mirrors `AnvilSettlementProvider`
    and lets tests build a provider with a stubbed `w3_factory` cleanly.
    """

    name = "sepolia"

    def __init__(
        self,
        rpc_url: str,
        from_key: str,
        from_address: str,
        *,
        chain_id: int = SEPOLIA_CHAIN_ID,
        value_wei: int = _DEMO_VALUE_WEI,
        required_confirmations: int = SEPOLIA_REQUIRED_CONFIRMATIONS,
        timeout_seconds: int = 30,
        w3_factory: Optional[Callable[[str], Web3]] = None,
    ):
        if not rpc_url:
            raise ValueError("SEPOLIA_RPC_URL is required")
        if not from_key:
            raise ValueError("SEPOLIA_PRIVATE_KEY is required")
        if not from_address:
            raise ValueError("SEPOLIA_FROM_ADDRESS is required")

        # Validate hex shape up front so a misconfigured env fails at app
        # startup (loud, with the offending field named) rather than at
        # first settle() with a cryptic eth_account error mid-route.
        if not _is_hex_prefixed_bytes(from_key, expected_bytes=32):
            raise ValueError(
                "SEPOLIA_PRIVATE_KEY must be a 0x-prefixed 32-byte hex string "
                f"(66 chars total): got {len(from_key)} chars"
            )
        if not Web3.is_address(from_address):
            raise ValueError(
                f"SEPOLIA_FROM_ADDRESS is not a valid EVM address: {from_address!r}"
            )

        self.rpc_url = rpc_url
        self.from_key = from_key
        self.chain_id = chain_id
        self.value_wei = value_wei
        self.required_confirmations = required_confirmations
        self.timeout = timeout_seconds

        # Derive sender address once. Account.from_key validates the curve
        # point — a malformed key past the hex check above still raises here.
        self._account = Account.from_key(from_key)

        # Reject a SEPOLIA_FROM_ADDRESS that doesn't match the key. Without
        # this, a typoed FROM_ADDRESS still "works" (we sign with the key's
        # actual address) but the tx leaves the wrong wallet and the operator
        # is left wondering why their faucet drip didn't get spent.
        derived = Web3.to_checksum_address(self._account.address)
        declared = Web3.to_checksum_address(from_address)
        if derived != declared:
            raise ValueError(
                "SEPOLIA_FROM_ADDRESS does not match the address derived from "
                f"SEPOLIA_PRIVATE_KEY (declared {declared}, derived {derived})"
            )
        self.from_address = derived

        factory = w3_factory or (
            lambda url: Web3(
                Web3.HTTPProvider(url, request_kwargs={"timeout": timeout_seconds})
            )
        )
        self._w3 = factory(rpc_url)

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
            nonce = self._w3.eth.get_transaction_count(self.from_address)
            tx = {
                "to": self.from_address,
                "value": self.value_wei,
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
                success=False, error=f"Sepolia RPC unreachable: {exc}"
            )
        except (Web3Exception, ValueError) as exc:
            return SettlementResult(
                success=False, error=f"Sepolia tx rejected: {exc}"
            )
        except Exception as exc:
            # Last-resort guard: provider must never raise into the route
            # layer — the agent_runs state machine relies on settle() always
            # returning a SettlementResult so it can flip to failed.
            return SettlementResult(
                success=False, error=f"Sepolia unexpected error: {exc}"
            )

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

        Returns SETTLED only when the receipt has `status == 1` AND the
        confirmation depth (head_block - receipt_block + 1) meets
        `required_confirmations`. With the default of 1 that boils down to
        "receipt exists and succeeded", but the knob lets a future caller
        ask for deeper finality without re-shaping the provider.

        Degrades to SETTLING (not FAILED) on transport / RPC errors so a
        transient outage can't poison an in-flight run. Only an explicit
        `receipt.status == 0` flips to FAILED.
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
        if status_field == 0:
            return SettlementStatus.FAILED
        if status_field != 1:
            return SettlementStatus.SETTLING

        # status==1 path: check confirmation depth.
        block_number = receipt.get("blockNumber") if isinstance(receipt, dict) else getattr(receipt, "blockNumber", None)
        if block_number is None:
            return SettlementStatus.SETTLING
        try:
            head = self._w3.eth.block_number
        except (requests.exceptions.RequestException, Web3Exception, ConnectionError, Exception):
            # We have a successful receipt but can't read the head; treat as
            # still-settling so the next poll can confirm. Don't downgrade a
            # truly-settled run to FAILED on a transient RPC blip.
            return SettlementStatus.SETTLING

        confirmations = head - block_number + 1
        if confirmations >= self.required_confirmations:
            return SettlementStatus.SETTLED
        return SettlementStatus.SETTLING


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _encode_payment_data(
    payee_id: str, amount: int, currency: str, chain: str | None
) -> bytes:
    """Serialize the royalty metadata into `tx.data` bytes.

    Same wire format as the Anvil provider: `hirenet:<payee_id>:<amount>:
    <currency>:<chain or "">`. A verifier on Etherscan can decode the input
    data as utf-8 and read which run this tx settled.
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
