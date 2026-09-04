"""x402 v2 `exact`/EVM payer — the CALLER side of a paid SkillAsset invocation.

Stage 2 / WP-C. This is the counterpart of `app/services/x402_gate.py`: the gate
is HireNet acting as the resource server (it quotes a price and asks a
facilitator to settle); this module is HireNet acting as the *payer* (it signs
an EIP-3009 `TransferWithAuthorization` over USDC and hands it to the resource
server in the `PAYMENT-SIGNATURE` header).

It signs money. Read the two lists below before trusting it.

────────────────────────────────────────────────────────────────────────────
WHY HAND-ROLLED (and what was copied from where)
────────────────────────────────────────────────────────────────────────────
The official client is `x402.mechanisms.evm.exact.ExactEvmScheme`, driven by
`x402ClientSync` + `x402_requests(...)`. Under this repo's pinned `web3>=6,<7`
that whole subtree is UNIMPORTABLE — `x402/mechanisms/evm/__init__.py` eagerly
imports `.signers`, which needs web3 7 (the same wall WP-B hit on the server
side; see the CONTINGENCY note in `x402_gate.py`). So the *shapes and the
signing math* are transcribed here from the installed package source, which was
read but not imported:

  * `x402/mechanisms/evm/exact/client.py`
      `ExactEvmScheme.create_payment_payload` -> the authorization fields, the
      `validAfter = "0"` / `validBefore = now + maxTimeoutSeconds` convention,
      the 32-byte random nonce, and `_sign_authorization` -> the EIP-712 domain
      built from `extra.name` / `extra.version` with `verifyingContract = asset`.
  * `x402/mechanisms/evm/types.py`
      `AUTHORIZATION_TYPES` (the `TransferWithAuthorization` type, field order
      included — EIP-712 hashes the order), `DOMAIN_TYPES`, and
      `ExactEIP3009Payload.to_dict()` -> the exact JSON key names
      (`from`/`to`/`value`/`validAfter`/`validBefore`/`nonce`, `signature`).
  * `x402/mechanisms/evm/eip712.py`
      `build_typed_data_for_signing` -> `value`/`validAfter`/`validBefore` are
      hashed as uint256 ints and `nonce` as raw bytes32, not as strings.
  * `x402/mechanisms/evm/utils.py`
      `get_evm_chain_id` (`eip155:<id>` -> int) and `create_nonce` (32 random
      bytes, hex, `0x`-prefixed).
  * `x402/client_base.py:794` -> how the inner payload is wrapped into a v2
      `PaymentPayload` (`x402Version`, `payload`, `accepted` = the *server's
      own* requirement echoed back verbatim).
  * `x402/http/utils.py` + `x402/http/constants.py` -> header names and the
      base64-of-JSON encoding, and `x402/http/x402_http_client_base.py`
      (`get_payment_required_response`) -> read the 402 from the
      `PAYMENT-REQUIRED` header first, fall back to the body.
  * `x402/server_base.py:244` `_payment_requirements_match_accepted` -> why
      `accepted` MUST be the server's requirement unmodified: the resource
      server compares scheme/network/amount/asset/payTo/maxTimeoutSeconds for
      exact equality and refuses anything else.

Everything the package *can* still give us is used rather than re-implemented:
the pydantic models `PaymentRequired` / `PaymentRequirements` / `PaymentPayload`
/ `SettleResponse` (importable: they pull no web3), so every object we build and
every object we read is schema-validated.

────────────────────────────────────────────────────────────────────────────
WHAT IS VERIFIED BY TESTS (tests/test_x402_payer.py)
────────────────────────────────────────────────────────────────────────────
  * the signature recovers to the payer's own address, and our EIP-712 encoding
    hashes byte-for-byte identically to the algorithm in the SDK's `eip712.py`;
  * the payload validates against the package's v2 `PaymentPayload` model and
    survives the base64 round-trip;
  * the quoted `amount` is copied verbatim into `value` — no float, no re-derived
    price, `"10000"` stays `"10000"`;
  * the spend cap refuses an over-cap quote BEFORE anything is signed;
  * no matching option / no key / second 402 / `success: false` settle all fail
    loudly;
  * end to end in one process against the real WP-B gate (`HIRENET_X402_GATE=1`)
    with the facilitator stubbed at the httpx boundary: 402 -> sign -> retry ->
    200, and the payload the gate forwarded to `/verify` carries a signature
    that recovers to our payer.

────────────────────────────────────────────────────────────────────────────
WHAT IS *NOT* VERIFIED — DO NOT READ THE GREEN SUITE AS PROOF OF THESE
────────────────────────────────────────────────────────────────────────────
  * No live facilitator has ever seen one of these payloads. Whether
    https://x402.org/facilitator accepts our `extra` domain, our `validAfter`,
    or our nonce is unknown until WP-F runs it for real.
  * No USDC has moved on Base Sepolia. Nothing here is confirmed on-chain, and
    a green test says nothing about the payer wallet's balance.
  * The signature is never checked against the USDC contract's own
    `transferWithAuthorization` — a domain mismatch (wrong token `name`,
    `version`, or chain id) would still produce a well-formed signature that a
    real facilitator rejects. WP-F is what turns "well-formed" into "accepted".

────────────────────────────────────────────────────────────────────────────
KEY HANDLING
────────────────────────────────────────────────────────────────────────────
The private key is a function argument, read by callers from the env var
`X402_PAYER_PRIVATE_KEY`. It is never stored on a module global, never written
to a log, and never interpolated into an exception message — the helpers below
that touch it re-raise with a scrubbed message on purpose.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import time
from typing import Any

from eth_account import Account
from eth_account.messages import encode_typed_data

from x402.schemas import (
    PaymentPayload,
    PaymentRequired,
    PaymentRequirements,
    SettleResponse,
)

# One source of truth for the chain constants: the gate already owns them (and
# already refuses to boot against a non-USDC token). Importing keeps payer and
# resource server from drifting apart.
from app.services.x402_gate import DEFAULT_NETWORK, DEFAULT_USDC_ADDRESS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# x402/http/constants.py — v2 names. The V1 names (X-PAYMENT /
# X-PAYMENT-RESPONSE) are deprecated upstream and are not used here.
PAYMENT_SIGNATURE_HEADER = "PAYMENT-SIGNATURE"
PAYMENT_REQUIRED_HEADER = "PAYMENT-REQUIRED"
PAYMENT_RESPONSE_HEADER = "PAYMENT-RESPONSE"

X402_VERSION = 2
SCHEME_EXACT = "exact"

# Env var holding the payer's key. Absent = HireNet cannot pay; a 402 is then
# surfaced as an error instead of being silently swallowed (spec S4).
PAYER_KEY_ENV = "X402_PAYER_PRIVATE_KEY"

# Spend control (spec S3). Atomic units, i.e. 1_000_000 = 1.000000 USDC.
MAX_AMOUNT_ENV = "X402_MAX_AMOUNT_PER_PAYMENT"
DEFAULT_MAX_AMOUNT_ATOMIC = 1_000_000

# Only used when a quote somehow carries no positive maxTimeoutSeconds. The v2
# `PaymentRequirements` model makes the field mandatory, so this is a dead
# branch for any schema-valid 402; it exists so a server sending 0 cannot
# produce an already-expired authorization. Upstream's fallback in
# `mechanisms/evm/exact/client.py` is 3600; the Stage 2 spec picked 600, and a
# shorter window is the safer direction for a signed authorization.
DEFAULT_VALID_WINDOW_SECONDS = 600

# EIP-712 type definitions, copied verbatim from
# x402/mechanisms/evm/types.py (AUTHORIZATION_TYPES / DOMAIN_TYPES).
# Field ORDER is part of the EIP-712 type hash: do not reorder.
TRANSFER_WITH_AUTHORIZATION_TYPE: list[dict[str, str]] = [
    {"name": "from", "type": "address"},
    {"name": "to", "type": "address"},
    {"name": "value", "type": "uint256"},
    {"name": "validAfter", "type": "uint256"},
    {"name": "validBefore", "type": "uint256"},
    {"name": "nonce", "type": "bytes32"},
]
EIP712_DOMAIN_TYPE: list[dict[str, str]] = [
    {"name": "name", "type": "string"},
    {"name": "version", "type": "string"},
    {"name": "chainId", "type": "uint256"},
    {"name": "verifyingContract", "type": "address"},
]
PRIMARY_TYPE = "TransferWithAuthorization"


# ---------------------------------------------------------------------------
# Errors. All money failures are loud; none of them are recoverable by retrying
# the same quote, so callers should surface them rather than loop.
# ---------------------------------------------------------------------------

class X402PayerError(Exception):
    """Base class for every failure on the paying side."""


class PaymentRequiredError(X402PayerError):
    """The resource asked for payment and we are not able (or allowed) to pay."""


class NoMatchingPaymentOption(X402PayerError):
    """The 402 quoted nothing we can pay: wrong scheme, network or asset."""


class SpendCapExceeded(X402PayerError):
    """The quote is above X402_MAX_AMOUNT_PER_PAYMENT. Nothing was signed."""


class PaymentFailed(X402PayerError):
    """We paid (or tried to) and the settlement did not succeed."""


# ---------------------------------------------------------------------------
# Env-backed configuration
# ---------------------------------------------------------------------------

def payer_network() -> str:
    """CAIP-2 network we are willing to pay on. Default: Base Sepolia."""
    return os.getenv("X402_NETWORK", DEFAULT_NETWORK)


def payer_asset() -> str:
    """Token contract we are willing to pay in. Default: Base Sepolia USDC."""
    return os.getenv("X402_USDC_ADDRESS", DEFAULT_USDC_ADDRESS)


def max_amount_per_payment() -> int:
    """Per-payment spend cap in atomic units (6 decimals for USDC).

    Raises:
        ValueError: the env var is set to something that is not a
            non-negative integer. Refusing to boot beats silently falling back
            to the default cap when an operator typo'd the number.
    """
    raw = os.getenv(MAX_AMOUNT_ENV)
    if raw is None or raw.strip() == "":
        return DEFAULT_MAX_AMOUNT_ATOMIC
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{MAX_AMOUNT_ENV} must be an integer number of atomic units, got {raw!r}"
        ) from exc
    if value < 0:
        raise ValueError(f"{MAX_AMOUNT_ENV} must be >= 0, got {value}")
    return value


# ---------------------------------------------------------------------------
# 1. Reading the 402
# ---------------------------------------------------------------------------

def parse_payment_required(response: Any) -> PaymentRequired:
    """Decode a 402 into the package's validated v2 `PaymentRequired`.

    Mirrors `x402HTTPClientBase.get_payment_required_response`
    (x402/http/x402_http_client_base.py): the v2 quote travels in the
    base64 `PAYMENT-REQUIRED` header and the body is an empty `{}`, but some
    servers put the JSON in the body instead, so the body is tried second.

    Works with any response object exposing case-insensitive `.headers` and
    `.content` — `requests.Response` and `httpx.Response` both qualify.

    Raises:
        PaymentRequiredError: nothing decodable was found, or what was found
            does not validate as a v2 quote (a v1 `x402Version: 1` body is
            explicitly rejected rather than half-understood).
    """
    header = None
    headers = getattr(response, "headers", None)
    if headers is not None:
        try:
            header = headers.get(PAYMENT_REQUIRED_HEADER)
        except Exception:  # pragma: no cover - exotic header container
            header = None

    if header:
        try:
            data = json.loads(base64.b64decode(header))
        except Exception as exc:
            raise PaymentRequiredError(
                f"{PAYMENT_REQUIRED_HEADER} header is not base64-encoded JSON: {exc}"
            ) from exc
        return _validate_payment_required(data)

    body = getattr(response, "content", None)
    if body:
        try:
            data = json.loads(body)
        except Exception:
            data = None
        if isinstance(data, dict) and data:
            return _validate_payment_required(data)

    raise PaymentRequiredError(
        f"402 response carries no {PAYMENT_REQUIRED_HEADER} header and no JSON quote in the body"
    )


def _validate_payment_required(data: Any) -> PaymentRequired:
    if not isinstance(data, dict):
        raise PaymentRequiredError(f"402 quote is not a JSON object: {type(data).__name__}")
    version = data.get("x402Version", data.get("x402_version", X402_VERSION))
    if version != X402_VERSION:
        raise PaymentRequiredError(
            f"unsupported x402 version in the 402 quote: {version!r} (this payer speaks v2 only)"
        )
    try:
        return PaymentRequired.model_validate(data)
    except Exception as exc:
        raise PaymentRequiredError(f"402 quote failed v2 schema validation: {exc}") from exc


def select_option(
    required: PaymentRequired,
    *,
    network: str,
    asset: str,
) -> PaymentRequirements:
    """Pick the one `exact` option we are configured to pay.

    Matching is on scheme + network + asset. Asset addresses are compared
    case-insensitively (EIP-55 checksum casing is cosmetic); nothing else is
    normalised, and no option is "close enough".

    Raises:
        NoMatchingPaymentOption: with the options that WERE offered, so the
            operator can see whether it is a network or an asset mismatch.
    """
    for option in required.accepts:
        if option.scheme != SCHEME_EXACT:
            continue
        if option.network != network:
            continue
        if option.asset.lower() != asset.lower():
            continue
        return option

    offered = [
        f"{opt.scheme}/{opt.network}/{opt.asset}" for opt in required.accepts
    ] or ["<none>"]
    raise NoMatchingPaymentOption(
        f"no {SCHEME_EXACT} option for network={network} asset={asset}; server offered: "
        + ", ".join(offered)
    )


# ---------------------------------------------------------------------------
# 2. Building and signing the authorization
# ---------------------------------------------------------------------------

def build_authorization(
    option: PaymentRequirements,
    payer_address: str,
    *,
    now: int | None = None,
) -> dict[str, str]:
    """Build the EIP-3009 authorization for `option`, as wire-shaped strings.

    Key names and the all-strings representation come from
    `ExactEIP3009Payload.to_dict()` (x402/mechanisms/evm/types.py).

    Values:
      * `value` is `option.amount` COPIED VERBATIM. The server quoted atomic
        units; we never re-derive, re-round or float-convert a price we did not
        compute. If the quote says "10000" we sign "10000".
      * `validAfter` is "0", which is what the official client sends
        (x402/mechanisms/evm/exact/client.py: `valid_after = "0"`). The Stage 2
        brief suggested `now - 60` as a clock-skew allowance; "0" is the SDK's
        convention and is strictly safer — an authorization that is already
        valid can never be rejected by a node whose clock runs behind ours.
      * `validBefore` is `now + option.max_timeout_seconds`, as upstream
        (falling back to DEFAULT_VALID_WINDOW_SECONDS only for a non-positive
        timeout, which a schema-valid quote cannot contain).
      * `nonce` is 32 fresh random bytes (upstream `create_nonce()`), hex with
        an `0x` prefix. It is the token's replay guard: the USDC contract
        records `authorizationState[from][nonce]`, so reusing one would make
        the second payment revert.

    `now` is injectable purely so tests can pin the window.
    """
    now = int(time.time()) if now is None else int(now)
    timeout = option.max_timeout_seconds
    window = timeout if isinstance(timeout, int) and timeout > 0 else DEFAULT_VALID_WINDOW_SECONDS

    return {
        "from": payer_address,
        "to": option.pay_to,
        "value": option.amount,           # verbatim from the quote
        "validAfter": "0",
        "validBefore": str(now + window),
        "nonce": "0x" + secrets.token_bytes(32).hex(),
    }


def chain_id_for(network: str) -> int:
    """`eip155:84532` -> 84532. Same rule as `get_evm_chain_id`
    (x402/mechanisms/evm/utils.py); anything else is refused rather than
    guessed, because the chain id is inside the signature.
    """
    if not network.startswith("eip155:"):
        raise NoMatchingPaymentOption(
            f"unsupported network format: {network!r} (expected eip155:<chain id>)"
        )
    try:
        return int(network.split(":", 1)[1])
    except (IndexError, ValueError) as exc:
        raise NoMatchingPaymentOption(f"invalid CAIP-2 network: {network!r}") from exc


def build_typed_data(auth: dict[str, str], option: PaymentRequirements) -> dict[str, Any]:
    """The full EIP-712 message that gets signed.

    Domain comes from the quote itself, as upstream `_sign_authorization` does:
        name    <- option.extra["name"]        (USDC advertises "USDC")
        version <- option.extra["version"]     ("2" for this token)
        chainId <- int(option.network after "eip155:")
        verifyingContract <- option.asset      (the token being transferred)

    Upstream falls back to its bundled `default_assets.py` table when `extra`
    has no name; we deliberately do NOT — signing against a domain the server
    never advertised is exactly how you produce a valid-looking signature that
    the token contract rejects. Missing domain fields are an error.

    Types are hashed per `build_typed_data_for_signing`
    (x402/mechanisms/evm/eip712.py): the three numeric fields as uint256 ints
    and the nonce as raw bytes32, NOT as the strings that go on the wire.
    """
    extra = option.extra or {}
    name = extra.get("name")
    version = extra.get("version")
    if not name or not version:
        raise NoMatchingPaymentOption(
            "the 402 quote is missing the EIP-712 domain fields "
            f"(extra.name / extra.version); got extra={extra!r}"
        )

    nonce_hex = str(auth["nonce"]).removeprefix("0x")
    nonce_bytes = bytes.fromhex(nonce_hex)
    if len(nonce_bytes) != 32:
        raise ValueError(f"nonce must be 32 bytes, got {len(nonce_bytes)}")

    return {
        "types": {
            "EIP712Domain": EIP712_DOMAIN_TYPE,
            PRIMARY_TYPE: TRANSFER_WITH_AUTHORIZATION_TYPE,
        },
        "primaryType": PRIMARY_TYPE,
        "domain": {
            "name": name,
            "version": version,
            "chainId": chain_id_for(option.network),
            "verifyingContract": option.asset,
        },
        "message": {
            "from": auth["from"],
            "to": auth["to"],
            "value": int(auth["value"]),
            "validAfter": int(auth["validAfter"]),
            "validBefore": int(auth["validBefore"]),
            "nonce": nonce_bytes,
        },
    }


def sign_authorization(
    auth: dict[str, str],
    option: PaymentRequirements,
    private_key: str,
) -> str:
    """Sign the authorization; return a 65-byte ECDSA signature as `0x…` hex.

    Upstream returns `"0x" + sig_bytes.hex()` from its signer protocol; we get
    the same bytes out of `eth_account`.

    The key never appears in a message raised from here.
    """
    typed_data = build_typed_data(auth, option)
    signable = encode_typed_data(full_message=typed_data)
    try:
        signed = Account.sign_message(signable, private_key=private_key)
    except Exception as exc:
        # Scrubbed on purpose: eth_account's own messages are key-free today,
        # but this is the one call that has the key in hand.
        raise X402PayerError(
            f"failed to sign the payment authorization ({exc.__class__.__name__}); "
            "check X402_PAYER_PRIVATE_KEY"
        ) from None
    return "0x" + bytes(signed.signature).hex()


def payer_address(private_key: str) -> str:
    """Checksummed address for a private key. Never logs or echoes the key."""
    try:
        return Account.from_key(private_key).address
    except Exception as exc:
        raise X402PayerError(
            f"X402_PAYER_PRIVATE_KEY is not a valid private key ({exc.__class__.__name__})"
        ) from None


# ---------------------------------------------------------------------------
# 3. Wrapping, encoding, decoding
# ---------------------------------------------------------------------------

def build_payment_payload(
    option: PaymentRequirements,
    auth: dict[str, str],
    signature: str,
) -> PaymentPayload:
    """Wrap the signed authorization into a v2 `PaymentPayload`.

    Structure from `x402/client_base.py:794`. `accepted` is the server's own
    requirement echoed back UNMODIFIED — `_payment_requirements_match_accepted`
    (x402/server_base.py:244) compares scheme, network, amount, asset, payTo and
    maxTimeoutSeconds for exact equality, so anything we "improve" here is a
    402 later.

    The returned object is validated by the package's own model, so a shape
    error surfaces here rather than at the facilitator.
    """
    return PaymentPayload(
        x402_version=X402_VERSION,
        payload={"authorization": dict(auth), "signature": signature},
        accepted=option,
    )


def encode_header(payload: PaymentPayload) -> str:
    """base64(JSON) for the `PAYMENT-SIGNATURE` header.

    Same serialisation as `encode_payment_signature_header`
    (x402/http/utils.py): `model_dump_json(by_alias=True, exclude_none=True)`,
    i.e. camelCase keys and no nulls.
    """
    return base64.b64encode(
        payload.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8")
    ).decode("utf-8")


def decode_payment_response(header: str) -> SettleResponse:
    """Decode a `PAYMENT-RESPONSE` header into the package's `SettleResponse`.

    Mirrors `decode_payment_response_header` (x402/http/utils.py).
    """
    try:
        raw = base64.b64decode(header)
    except Exception as exc:
        raise PaymentFailed(
            f"{PAYMENT_RESPONSE_HEADER} header is not valid base64: {exc}"
        ) from exc
    try:
        return SettleResponse.model_validate_json(raw)
    except Exception as exc:
        raise PaymentFailed(
            f"{PAYMENT_RESPONSE_HEADER} header failed schema validation: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# 4. Spend control
# ---------------------------------------------------------------------------

def enforce_spend_cap(amount_atomic: str | int, max_amount: int | None = None) -> int:
    """Refuse a quote above the per-payment cap. Called BEFORE anything is signed.

    This is the only automatic brake between a compromised/greedy resource
    server and the payer's wallet, so it runs on the number the SERVER quoted,
    not on anything we derived from it.

    Raises:
        SpendCapExceeded: the quote is over the cap.
        ValueError: the quoted amount is not a non-negative integer string.
    """
    cap = max_amount_per_payment() if max_amount is None else int(max_amount)
    try:
        value = int(amount_atomic)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"quoted amount is not an integer number of atomic units: {amount_atomic!r}"
        ) from exc
    if value < 0:
        raise ValueError(f"quoted amount must be >= 0, got {value}")
    if value > cap:
        raise SpendCapExceeded(
            f"quote of {value} atomic units exceeds {MAX_AMOUNT_ENV}={cap}; nothing was signed"
        )
    return value


# ---------------------------------------------------------------------------
# 5. The one-shot pay-and-retry flow
# ---------------------------------------------------------------------------

def pay_and_retry(
    session_or_client: Any,
    method: str,
    url: str,
    *,
    json: Any = None,
    private_key: str,
    network: str | None = None,
    asset: str | None = None,
    max_amount: int | None = None,
    headers: dict[str, str] | None = None,
    **request_kwargs: Any,
) -> tuple[Any, dict[str, Any] | None]:
    """Perform `method url`; if it 402s, pay once and retry. Never loops.

    Args:
        session_or_client: anything with
            `.request(method, url, json=..., headers=..., **kwargs)` — the
            `requests` module, a `requests.Session`, or an `httpx.Client`.
        private_key: the payer's key (from `X402_PAYER_PRIVATE_KEY`). Used, not
            stored, not logged.
        network / asset: what we are willing to pay on / in; default to the env
            configuration (Base Sepolia USDC).
        max_amount: per-payment cap in atomic units; defaults to
            `X402_MAX_AMOUNT_PER_PAYMENT`.
        headers / **request_kwargs: passed through to BOTH attempts, so a
            caller's timeout and `allow_redirects=False` still apply to the
            paid retry.

    Returns:
        `(response, payment_info)`. `payment_info` is None when no payment
        happened (the first response was not a 402). Otherwise:
            {"method": "x402", "tx_hash", "network", "payer", "payee",
             "amount_atomic", "asset", "settle_success"}
        `amount_atomic` is the quoted string, unmodified.

    Raises:
        NoMatchingPaymentOption / SpendCapExceeded / PaymentFailed /
        PaymentRequiredError — every one of them means no usable result. This
        function deliberately raises instead of returning a soft error: the
        caller has just signed (or refused to sign) a transfer, and that is not
        a condition to paper over.

    EXACTLY ONE retry. If the server 402s again we stop: signing a second
    authorization against the same resource is how a buggy or hostile server
    drains a wallet one nonce at a time.
    """
    network = network or payer_network()
    asset = asset or payer_asset()
    base_headers = dict(headers or {})

    response = session_or_client.request(
        method, url, json=json, headers=base_headers or None, **request_kwargs
    )
    if response.status_code != 402:
        return response, None

    if not private_key:
        raise PaymentRequiredError(
            f"x402 payment required but {PAYER_KEY_ENV} is not configured"
        )

    required = parse_payment_required(response)
    option = select_option(required, network=network, asset=asset)

    # Cap first: nothing is signed for a quote we would refuse.
    enforce_spend_cap(option.amount, max_amount)

    address = payer_address(private_key)
    auth = build_authorization(option, address)
    signature = sign_authorization(auth, option, private_key)
    payload = build_payment_payload(option, auth, signature)

    paid_headers = dict(base_headers)
    paid_headers[PAYMENT_SIGNATURE_HEADER] = encode_header(payload)

    paid_response = session_or_client.request(
        method, url, json=json, headers=paid_headers, **request_kwargs
    )

    settle_header = paid_response.headers.get(PAYMENT_RESPONSE_HEADER)
    settle = decode_payment_response(settle_header) if settle_header else None

    if paid_response.status_code == 402:
        # The gate answers a failed settlement with 402 + a success:false
        # PAYMENT-RESPONSE (see tests/test_x402_gate.py). Either way we did not
        # get the resource, so this is a failure — with the reason the server
        # gave, not a guess.
        raise PaymentFailed(_settle_failure_reason(settle))

    if settle is None:
        # We handed over a signed, redeemable authorization and the server
        # answered without confirming settlement. Reporting "unpaid" here would
        # be a lie: the authorization may still be settled out of band.
        raise PaymentFailed(
            f"server returned HTTP {paid_response.status_code} after our payment but no "
            f"{PAYMENT_RESPONSE_HEADER} header; settlement is unconfirmed"
        )

    if not settle.success:
        raise PaymentFailed(_settle_failure_reason(settle))

    payment_info = {
        "method": "x402",
        "tx_hash": settle.transaction,
        "network": settle.network,
        # The facilitator echoes the payer it recovered from the signature; if
        # it does not, fall back to the address we signed with.
        "payer": settle.payer or address,
        "payee": option.pay_to,
        "amount_atomic": option.amount,   # verbatim, still a string
        "asset": option.asset,
        "settle_success": settle.success,
    }
    return paid_response, payment_info


def _settle_failure_reason(settle: SettleResponse | None) -> str:
    """Human-readable reason for a refused/failed payment."""
    if settle is None:
        return (
            "the resource still requires payment after our signed authorization "
            f"and sent no {PAYMENT_RESPONSE_HEADER} (payment was rejected before settlement)"
        )
    parts = [f"settlement did not succeed (success={settle.success})"]
    if settle.error_reason:
        parts.append(f"reason={settle.error_reason}")
    if settle.error_message:
        parts.append(f"message={settle.error_message}")
    if settle.transaction:
        parts.append(f"transaction={settle.transaction}")
    return "; ".join(parts)
