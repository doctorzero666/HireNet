"""
Stage 2 / WP-D — settlement provider for x402 pre-settled runs (spec S6).

x402 inverts the settlement direction every other provider in this package
assumes. Mock / Anvil / Sepolia are PUSH rails: the platform holds a key, the
route calls `settle()`, money leaves. x402 is a PULL-at-invocation rail: the
CALLER signed an EIP-3009 authorization before the tool ran and a facilitator
broadcast the USDC transfer (WP-C). By the time a run row exists the money is
already in flight, so:

  * `settle()` REFUSES. There is nothing for the platform to submit, and a
    provider that quietly "succeeded" here would let /api/royalty/settle mark
    a run paid on the strength of nothing at all.
  * `check_status()` is the only thing this provider really does, and it is
    the only place in HireNet that turns "a facilitator said so" into "the
    chain says so".

────────────────────────────────────────────────────────────────────────────
WHAT check_status() ACTUALLY VERIFIES
────────────────────────────────────────────────────────────────────────────
SETTLED requires ALL of:
  1. a receipt exists for the tx hash;
  2. receipt.status == 1 (the tx did not revert);
  3. the receipt contains an ERC-20 `Transfer` log EMITTED BY THE CONFIGURED
     USDC CONTRACT (log.address is checked — a Transfer from some other token
     is ignored) whose `to` is the payee we expected and whose `value` is the
     atomic amount we expected.

Expectations come from `expected_lookup(tx_hash) -> (payee, amount_atomic)`,
which by default reads `agent_runs.settlement_meta` for the run carrying that
tx hash — i.e. what WP-D commit 1 recorded at invocation time. If the
expectation cannot be resolved we return SETTLING, never SETTLED: an
unverifiable payment is not a confirmed one.

Deliberately NOT verified (say less than we can prove):
  * the `from` address. The facilitator broadcasts, so the tx sender is the
    facilitator's relayer, not the payer; EIP-3009 moves funds from the
    authorizer, which appears as the Transfer log's `from`. We record the
    payer for audit but do not gate settlement on it — WP-F's live run is what
    would let us assert the real shape.
  * confirmation depth. `SepoliaSettlementProvider` takes a
    `required_confirmations` knob; this provider does not, so a reorg after a
    single-block confirmation would leave a run marked settled. Base Sepolia
    is a testnet demo; a mainnet deployment must add the depth check.
  * that the payee address is the creator's registered wallet. That binding is
    established by the WP-B gate, which is what put `pay_to` on the wire.

────────────────────────────────────────────────────────────────────────────
WHAT IS AND IS NOT EXECUTED
────────────────────────────────────────────────────────────────────────────
No code path in this module has ever contacted a live RPC endpoint. The unit
tests inject a fake `w3` and a guard makes constructing a real
`Web3.HTTPProvider` an error, so a green suite proves the receipt/log decoding
and the branch table — not that Base Sepolia behaves as assumed. WP-F does the
live run.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

import requests
from web3 import Web3
from web3.exceptions import TransactionNotFound, Web3Exception

from app.services.settlement import (
    SettlementProvider,
    SettlementResult,
    SettlementStatus,
)

logger = logging.getLogger(__name__)


# keccak256("Transfer(address,address,uint256)") — the ERC-20 Transfer event's
# topic0. Cross-checked two ways: it is the constant the x402 package's own
# facilitator-side `eip3009_utils.verify_eip3009_transfer_event` uses, and it
# was recomputed independently in this session with
# `eth_utils.keccak(text="Transfer(address,address,uint256)")`.
ERC20_TRANSFER_TOPIC0 = bytes.fromhex(
    "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)

# Public Base Sepolia RPC (spec S1). Overridable via X402_RPC_URL.
DEFAULT_RPC_URL = "https://sepolia.base.org"

# Explorer link template. `{tx_hash}` is substituted; a template without the
# placeholder gets the hash appended as a path segment.
EXPLORER_TX_URL_ENV = "X402_EXPLORER_TX_URL"
DEFAULT_EXPLORER_TX_URL = "https://sepolia.basescan.org/tx/{tx_hash}"

_SETTLE_REFUSAL = (
    "x402 runs are settled by the payer at invocation time; "
    "nothing for the platform to settle"
)

_DEFAULT_TIMEOUT_SECONDS = 15


def explorer_url(tx_hash: str) -> str:
    """Block-explorer URL for a tx hash, from X402_EXPLORER_TX_URL.

    Module-level (not just a method) because the royalty status route needs it
    for x402 runs whether or not the app's configured provider happens to be
    this one.
    """
    template = os.getenv(EXPLORER_TX_URL_ENV, DEFAULT_EXPLORER_TX_URL)
    normalized = _normalize_tx_hash(tx_hash)
    if "{tx_hash}" in template:
        return template.replace("{tx_hash}", normalized)
    return f"{template.rstrip('/')}/{normalized}"


def _normalize_tx_hash(tx_hash: str) -> str:
    return tx_hash if tx_hash.startswith("0x") else f"0x{tx_hash}"


def _chain_id_for(network: str) -> int:
    """`eip155:84532` -> 84532; anything else is a ValueError.

    Delegates to the payer's parser so the CAIP-2 rule has one definition;
    its refusal type is re-raised as ValueError because provider constructors
    in this package signal misconfiguration with ValueError (see the anvil /
    sepolia providers, whose __init__ does the same for bad env fields).
    """
    from app.services.x402_payer import chain_id_for

    try:
        return chain_id_for(network)
    except Exception as exc:
        raise ValueError(f"X402_NETWORK is not a supported network: {exc}") from exc


def _as_bytes(value: Any) -> bytes | None:
    """Coerce a web3 log field to bytes.

    web3 6.x hands back `HexBytes` for `topics[i]` and `data` (see
    web3._utils.method_formatters.LOG_ENTRY_FORMATTERS), and HexBytes is a
    bytes subclass — so the isinstance branch is the real one. The str branch
    exists because a hand-built receipt (a test fixture, a cached JSON-RPC
    response replayed from disk) may carry plain hex strings, and silently
    mis-decoding one of those would be a correctness bug in money code.
    Returns None for anything undecodable; callers treat that as "not a
    Transfer log I can read", never as a match.
    """
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        text = value[2:] if value.startswith(("0x", "0X")) else value
        try:
            return bytes.fromhex(text)
        except ValueError:
            return None
    return None


def _log_field(log: Any, key: str) -> Any:
    """Read `key` off a receipt log that may be a dict or an attribute object."""
    if isinstance(log, dict):
        return log.get(key)
    return getattr(log, key, None)


def _decode_transfer(log: Any) -> tuple[str, int] | None:
    """Decode one ERC-20 `Transfer` log into (to_address_lowercase, value).

    Layout of `Transfer(address indexed from, address indexed to, uint256 value)`:
        topics[0] = keccak("Transfer(address,address,uint256)")   (32 bytes)
        topics[1] = `from`, left-padded to 32 bytes  -> not used, see module docstring
        topics[2] = `to`,   left-padded to 32 bytes  -> last 20 bytes are the address
        data      = `value`, a single big-endian uint256 (32 bytes)

    Returns None (never a partial match) if the log is not a well-formed
    Transfer: wrong topic0, fewer than 3 topics, or a data blob that is not
    exactly 32 bytes. A `to` shorter than 32 bytes is also refused rather than
    right-aligned by guesswork.
    """
    topics = _log_field(log, "topics")
    if not isinstance(topics, (list, tuple)) or len(topics) < 3:
        return None

    topic0 = _as_bytes(topics[0])
    if topic0 != ERC20_TRANSFER_TOPIC0:
        return None

    to_topic = _as_bytes(topics[2])
    if to_topic is None or len(to_topic) != 32:
        return None
    to_address = "0x" + to_topic[-20:].hex()

    data = _as_bytes(_log_field(log, "data"))
    if data is None or len(data) != 32:
        return None
    value = int.from_bytes(data, "big")

    return to_address.lower(), value


class X402SettlementProvider(SettlementProvider):
    """Confirm an x402 pre-settled run against the chain. Never pays anything.

    Constructor reads no env vars — `get_provider("x402")` in
    app/services/settlement.py does that and passes values in, matching the
    anvil / sepolia providers.

    The `w3` handle is built LAZILY on first use rather than in __init__.
    That is a deliberate difference from the other on-chain providers: it
    means constructing the provider (which `create_app` does at import-ish
    time, for every process and every test that boots the app with
    HIRENET_SETTLEMENT_PROVIDER=x402) touches no HTTP machinery at all, and it
    lets the test suite assert that no real `Web3.HTTPProvider` is ever
    constructed. Inject `w3=` to bypass it entirely.
    """

    name = "x402"

    def __init__(
        self,
        rpc_url: str,
        usdc_address: str,
        network: str,
        *,
        w3: Optional[Web3] = None,
        expected_lookup: Optional[Callable[[str], tuple[str, int] | None]] = None,
        db_path: Optional[str] = None,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ):
        if not rpc_url:
            raise ValueError("X402_RPC_URL is required")
        if not usdc_address:
            raise ValueError("X402_USDC_ADDRESS is required")
        if not Web3.is_address(usdc_address):
            raise ValueError(
                f"X402_USDC_ADDRESS is not a valid EVM address: {usdc_address!r}"
            )
        if not network:
            raise ValueError("X402_NETWORK is required")

        # Refuse an unknown network at construction time rather than at the
        # first poll: the chain id is what makes an address meaningful, and a
        # typo'd network in .env should be loud at startup.
        self.chain_id = _chain_id_for(network)

        self.rpc_url = rpc_url
        self.network = network
        self.timeout = timeout_seconds
        # Lower-cased for log comparison; the checksum form is kept for
        # anything that wants to display it.
        self.usdc_address = Web3.to_checksum_address(usdc_address)
        self._usdc_lower = self.usdc_address.lower()

        self._w3 = w3
        self._db_path = db_path
        self._expected_lookup = expected_lookup or self._lookup_expected_from_run

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
        """Always refuses — see the module docstring.

        This is not a stub or a TODO: for this rail there is genuinely nothing
        to submit. /api/royalty/settle turns the refusal into a 502 + a
        'failed' run, which is the correct outcome for "someone asked the
        platform to pay a bill the caller already paid".
        """
        return SettlementResult(success=False, error=_SETTLE_REFUSAL)

    def check_status(self, tx_hash: str) -> SettlementStatus:
        """Receipt + USDC Transfer log -> SETTLING / SETTLED / FAILED.

        Transport and RPC errors degrade to SETTLING, matching the posture of
        AnvilSettlementProvider.check_status: a flaky endpoint must not poison
        an in-flight run, and the caller can always poll again. Only evidence
        promotes (a matching Transfer) or condemns (a reverted receipt, or a
        successful receipt with no matching Transfer).
        """
        normalized = _normalize_tx_hash(tx_hash)

        try:
            receipt = self.w3.eth.get_transaction_receipt(normalized)
        except TransactionNotFound:
            # Not mined yet (or dropped from this node's view). Still pending.
            return SettlementStatus.SETTLING
        except (requests.exceptions.RequestException, Web3Exception, ConnectionError):
            return SettlementStatus.SETTLING
        except Exception:
            logger.exception("x402 check_status: receipt lookup failed for %s", normalized)
            return SettlementStatus.SETTLING

        if receipt is None:
            return SettlementStatus.SETTLING

        status_field = _log_field(receipt, "status")
        if status_field == 0:
            logger.warning("x402 tx %s reverted on-chain (receipt.status=0)", normalized)
            return SettlementStatus.FAILED
        if status_field != 1:
            # Pre-Byzantium receipts have no status field. We cannot tell
            # success from failure, so we do not guess.
            return SettlementStatus.SETTLING

        try:
            expected = self._expected_lookup(normalized)
        except Exception:
            logger.exception(
                "x402 check_status: expected-payment lookup failed for %s", normalized
            )
            return SettlementStatus.SETTLING

        if expected is None:
            # A successful receipt we cannot connect to an expectation proves
            # only that SOME transaction succeeded. Not enough to pay a
            # creator on.
            logger.warning(
                "x402 tx %s has a successful receipt but no recorded expectation "
                "(payee/amount); refusing to mark it settled",
                normalized,
            )
            return SettlementStatus.SETTLING

        expected_payee, expected_amount = expected
        expected_payee_lower = expected_payee.lower()

        logs = _log_field(receipt, "logs") or []
        seen: list[tuple[str, int]] = []
        for log in logs:
            log_address = _log_field(log, "address")
            if not isinstance(log_address, str):
                continue
            if log_address.lower() != self._usdc_lower:
                # A Transfer of some other token is not payment.
                continue
            decoded = _decode_transfer(log)
            if decoded is None:
                continue
            seen.append(decoded)
            to_address, value = decoded
            if to_address == expected_payee_lower and value == expected_amount:
                return SettlementStatus.SETTLED

        logger.warning(
            "x402 tx %s succeeded but carries no USDC(%s) Transfer of %s atomic "
            "units to %s; observed transfers: %s. Marking FAILED.",
            normalized, self.usdc_address, expected_amount, expected_payee, seen,
        )
        return SettlementStatus.FAILED

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def w3(self) -> Web3:
        """The RPC handle, built on first use (see the class docstring)."""
        if self._w3 is None:
            self._w3 = Web3(
                Web3.HTTPProvider(
                    self.rpc_url, request_kwargs={"timeout": self.timeout}
                )
            )
        return self._w3

    def explorer_url(self, tx_hash: str) -> str:
        """Block-explorer URL for this tx (thin wrapper over the module fn)."""
        return explorer_url(tx_hash)

    def _lookup_expected_from_run(self, tx_hash: str) -> tuple[str, int] | None:
        """Default expectation source: the run WP-D commit 1 recorded.

        Reads agent_runs.settlement_meta for the row carrying this tx_hash and
        returns its (payee, amount_atomic). The DB path comes from the
        constructor when given, otherwise from the live Flask app — the
        provider is a long-lived app-config singleton built before any request,
        so resolving the path at call time (inside a request) rather than at
        construction is what keeps `get_provider("x402")` env-only.

        Returns None — meaning "no expectation on file", which check_status
        treats as unverifiable — when there is no app context, no matching
        run, or no usable settlement_meta.
        """
        db_path = self._db_path
        if db_path is None:
            try:
                from flask import current_app

                db_path = current_app.config["DATABASE_PATH"]
            except Exception:
                logger.warning(
                    "x402 expected_lookup: no db_path and no Flask app context; "
                    "cannot verify tx %s", tx_hash,
                )
                return None

        from contextlib import closing

        from app.storage.db import _open

        with closing(_open(db_path)) as conn:
            row = conn.execute(
                "SELECT run_id, settlement_meta FROM agent_runs "
                "WHERE tx_hash = ? AND settlement_method = ?",
                (tx_hash, self.name),
            ).fetchone()

        if row is None or row["settlement_meta"] is None:
            return None

        import json

        try:
            meta = json.loads(row["settlement_meta"])
        except (TypeError, ValueError):
            logger.error(
                "x402 expected_lookup: run %s has unparseable settlement_meta",
                row["run_id"],
            )
            return None

        payee = meta.get("payee")
        amount_atomic = meta.get("amount_atomic")
        if not isinstance(payee, str) or not payee:
            return None
        if isinstance(amount_atomic, bool) or not isinstance(amount_atomic, int):
            # Recorded by _validate_presettled as a plain int. Anything else
            # means the row was hand-edited; do not guess a value to compare.
            logger.error(
                "x402 expected_lookup: run %s settlement_meta.amount_atomic is "
                "%r, not an int", row["run_id"], amount_atomic,
            )
            return None
        return payee, amount_atomic
