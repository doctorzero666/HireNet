"""Stage 2 / WP-C: the hand-rolled x402 v2 `exact`/EVM payer.

Three layers, all off the network:

  1. Unit — the signing math and the payload shapes, checked against the
     package's own pydantic models and against a re-implementation of the
     SDK's EIP-712 hashing algorithm (x402/mechanisms/evm/eip712.py), so a
     drift in either direction is a failure and not a silent mismatch.
  2. `pay_and_retry` — the 402 -> sign -> retry control flow against a scripted
     fake resource server (no Flask, no gate), including every refusal path.
  3. In-process end to end — the REAL WP-B gate on the REAL demo MCP server,
     with only the facilitator stubbed (`httpx.MockTransport`, reusing
     `tests/test_x402_gate.py`'s `FacilitatorStub`) and `requests` routed into
     the Flask app by a local adapter. Proves the bytes the payer signs are the
     bytes the gate forwards to `/verify`.

`no_real_network` (autouse) fails the test if anything opens a socket or uses a
real httpx transport.

NOT covered here, on purpose: whether a live facilitator accepts these payloads,
and whether any USDC moves. See the "WHAT IS NOT VERIFIED" block in
app/services/x402_payer.py. WP-F does the live run.
"""
import base64
import json
import json as _json          # alias for methods whose `json=` kwarg shadows it
import os
import socket
import tempfile
import uuid
from urllib.parse import urlparse

import httpx
import pytest
import requests
from eth_abi import encode as abi_encode
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak
from flask import Flask

from app.mcp_servers.customer_service import create_mcp_app
from app.services import mcp_client as mcp_client_module
from app.services.mcp_client import call_mcp_tool
from app.services.x402_gate import DEFAULT_USDC_ADDRESS, install_x402_gate
from app.services.x402_payer import (
    MAX_AMOUNT_ENV,
    PAYER_KEY_ENV,
    PAYMENT_REQUIRED_HEADER,
    PAYMENT_RESPONSE_HEADER,
    PAYMENT_SIGNATURE_HEADER,
    NoMatchingPaymentOption,
    PaymentFailed,
    PaymentOutcomeUnknown,
    PaymentRequiredError,
    SpendCapExceeded,
    build_authorization,
    build_payment_payload,
    build_typed_data,
    decode_payment_response,
    encode_header,
    enforce_spend_cap,
    parse_payment_required,
    pay_and_retry,
    select_option,
    sign_authorization,
)
from app.storage.db import init_db
from app.storage.skill_assets import insert_skill_asset
from tests.test_x402_gate import (  # WP-B stubs, reused verbatim
    CREATOR_WALLET,
    ENDPOINT_URL,
    NETWORK,
    TOOL,
    TX_HASH,
    FacilitatorStub,
)
from tests.test_x402_gate import PAYER as STUB_PAYER  # what the stub echoes back
from x402.schemas import PaymentPayload, PaymentRequired, PaymentRequirements

# A throwaway key. It is a TEST FIXTURE, not a wallet: it is a public constant
# in a public repo, it holds nothing, and it must never be funded.
TEST_PRIVATE_KEY = "0x" + "11" * 32
TEST_PAYER_ADDRESS = Account.from_key(TEST_PRIVATE_KEY).address

MCP_BASE_URL = "http://mcp.test"


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """Fail loudly if a test would touch the network."""
    def _boom(*args, **kwargs):
        raise AssertionError(
            "x402 payer tests must not make real network calls; the resource "
            "server and the facilitator are both stubbed in-process."
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _boom)
    monkeypatch.setattr(socket.socket, "connect", _boom)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _boom)


@pytest.fixture(autouse=True)
def clean_payer_env(monkeypatch):
    """Never inherit the operator's real key or cap from the environment."""
    monkeypatch.delenv(PAYER_KEY_ENV, raising=False)
    monkeypatch.delenv(MAX_AMOUNT_ENV, raising=False)


# ---------------------------------------------------------------------------
# Quote helpers
# ---------------------------------------------------------------------------

def make_option(amount="10000", **overrides) -> PaymentRequirements:
    """A quote shaped exactly like the one the WP-B gate emits."""
    fields = {
        "scheme": "exact",
        "network": NETWORK,
        "asset": DEFAULT_USDC_ADDRESS,
        "amount": amount,
        "pay_to": CREATOR_WALLET,
        "max_timeout_seconds": 300,
        "extra": {"name": "USDC", "version": "2"},
    }
    fields.update(overrides)
    return PaymentRequirements(**fields)


def make_402_header(option: PaymentRequirements) -> str:
    required = PaymentRequired(x402_version=2, accepts=[option])
    return base64.b64encode(
        required.model_dump_json(by_alias=True, exclude_none=True).encode()
    ).decode()


class FakeResponse:
    """Minimal stand-in for requests.Response for the parsing unit tests."""

    def __init__(self, status_code=402, headers=None, content=b""):
        self.status_code = status_code
        self.headers = requests.structures.CaseInsensitiveDict(headers or {})
        self.content = content
        self.text = content.decode() if isinstance(content, bytes) else str(content)

    def json(self):
        return json.loads(self.content)


# ---------------------------------------------------------------------------
# 1. Parsing the 402
# ---------------------------------------------------------------------------

def test_parse_payment_required_reads_the_header_and_ignores_the_empty_body():
    option = make_option()
    resp = FakeResponse(
        headers={PAYMENT_REQUIRED_HEADER: make_402_header(option)},
        content=b"{}",          # what the v2 middleware actually sends
    )

    required = parse_payment_required(resp)

    assert isinstance(required, PaymentRequired)
    assert required.x402_version == 2
    assert len(required.accepts) == 1
    assert required.accepts[0].amount == "10000"
    assert required.accepts[0].pay_to == CREATOR_WALLET


def test_parse_payment_required_falls_back_to_the_body():
    """Some servers put the quote in the body instead of the header."""
    option = make_option(amount="25000")
    body = PaymentRequired(x402_version=2, accepts=[option]).model_dump_json(
        by_alias=True, exclude_none=True
    )
    resp = FakeResponse(content=body.encode())

    assert parse_payment_required(resp).accepts[0].amount == "25000"


def test_parse_payment_required_rejects_a_v1_quote():
    resp = FakeResponse(content=json.dumps({"x402Version": 1, "accepts": []}).encode())
    with pytest.raises(PaymentRequiredError, match="unsupported x402 version"):
        parse_payment_required(resp)


def test_parse_payment_required_rejects_an_empty_402():
    with pytest.raises(PaymentRequiredError, match="no PAYMENT-REQUIRED header"):
        parse_payment_required(FakeResponse(content=b"{}"))


def test_parse_payment_required_rejects_a_non_base64_header():
    resp = FakeResponse(headers={PAYMENT_REQUIRED_HEADER: "not-base64-!!!"})
    with pytest.raises(PaymentRequiredError):
        parse_payment_required(resp)


# ---------------------------------------------------------------------------
# 2. Selecting an option
# ---------------------------------------------------------------------------

def test_select_option_picks_our_network_and_asset():
    wrong_network = make_option(network="eip155:1")
    wrong_asset = make_option(asset="0x0000000000000000000000000000000000000001")
    ours = make_option()
    required = PaymentRequired(x402_version=2, accepts=[wrong_network, wrong_asset, ours])

    picked = select_option(required, network=NETWORK, asset=DEFAULT_USDC_ADDRESS)
    assert picked is ours


def test_select_option_is_case_insensitive_on_the_asset_address():
    """EIP-55 checksum casing is cosmetic; a lowercase quote is the same token."""
    lowercased = make_option(asset=DEFAULT_USDC_ADDRESS.lower())
    required = PaymentRequired(x402_version=2, accepts=[lowercased])

    assert select_option(required, network=NETWORK, asset=DEFAULT_USDC_ADDRESS) is lowercased


def test_select_option_refuses_a_different_scheme():
    upto = make_option(scheme="upto")
    required = PaymentRequired(x402_version=2, accepts=[upto])

    with pytest.raises(NoMatchingPaymentOption, match="upto"):
        select_option(required, network=NETWORK, asset=DEFAULT_USDC_ADDRESS)


def test_select_option_error_names_what_was_offered():
    required = PaymentRequired(x402_version=2, accepts=[make_option(network="eip155:1")])

    with pytest.raises(NoMatchingPaymentOption) as excinfo:
        select_option(required, network=NETWORK, asset=DEFAULT_USDC_ADDRESS)
    assert "eip155:1" in str(excinfo.value)
    assert NETWORK in str(excinfo.value)


# ---------------------------------------------------------------------------
# 3. Building the authorization — the money numbers
# ---------------------------------------------------------------------------

def test_build_authorization_copies_the_quoted_value_verbatim():
    """THE invariant: we sign the string the server quoted. No float anywhere."""
    option = make_option(amount="10000")

    auth = build_authorization(option, TEST_PAYER_ADDRESS, now=1_700_000_000)

    assert auth["value"] == "10000"
    assert isinstance(auth["value"], str)
    assert auth["value"] is option.amount     # literally the same object


@pytest.mark.parametrize("amount", ["1", "10000", "40000000", "999999999999999999999"])
def test_build_authorization_never_reformats_the_amount(amount):
    auth = build_authorization(make_option(amount=amount), TEST_PAYER_ADDRESS)
    assert auth["value"] == amount


def test_build_authorization_fields_and_window():
    option = make_option(max_timeout_seconds=300)

    auth = build_authorization(option, TEST_PAYER_ADDRESS, now=1_700_000_000)

    assert auth["from"] == TEST_PAYER_ADDRESS
    assert auth["to"] == CREATOR_WALLET
    # SDK convention (mechanisms/evm/exact/client.py): validAfter is "0".
    assert auth["validAfter"] == "0"
    assert auth["validBefore"] == str(1_700_000_000 + 300)
    assert set(auth) == {"from", "to", "value", "validAfter", "validBefore", "nonce"}


def test_build_authorization_nonce_is_32_fresh_random_bytes():
    option = make_option()
    nonces = {build_authorization(option, TEST_PAYER_ADDRESS)["nonce"] for _ in range(50)}

    assert len(nonces) == 50                      # never reused
    for nonce in nonces:
        assert nonce.startswith("0x")
        assert len(bytes.fromhex(nonce[2:])) == 32


def test_build_authorization_falls_back_when_the_timeout_is_not_positive():
    auth = build_authorization(
        make_option(max_timeout_seconds=0), TEST_PAYER_ADDRESS, now=1_700_000_000
    )
    assert auth["validBefore"] == str(1_700_000_000 + 600)


# ---------------------------------------------------------------------------
# 4. Signing
# ---------------------------------------------------------------------------

def test_signature_recovers_to_the_payer_address():
    """The headline check: whoever verifies this sees OUR address."""
    option = make_option()
    auth = build_authorization(option, TEST_PAYER_ADDRESS)

    signature = sign_authorization(auth, option, TEST_PRIVATE_KEY)

    signable = encode_typed_data(full_message=build_typed_data(auth, option))
    assert Account.recover_message(signable, signature=signature) == TEST_PAYER_ADDRESS
    assert signature.startswith("0x")
    assert len(bytes.fromhex(signature[2:])) == 65     # r || s || v


def test_typed_data_domain_is_built_from_the_quote():
    option = make_option()
    auth = build_authorization(option, TEST_PAYER_ADDRESS)

    typed = build_typed_data(auth, option)

    assert typed["primaryType"] == "TransferWithAuthorization"
    assert typed["domain"] == {
        "name": "USDC",
        "version": "2",
        "chainId": 84532,                       # parsed out of "eip155:84532"
        "verifyingContract": DEFAULT_USDC_ADDRESS,
    }
    assert typed["types"]["TransferWithAuthorization"] == [
        {"name": "from", "type": "address"},
        {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"},
        {"name": "validAfter", "type": "uint256"},
        {"name": "validBefore", "type": "uint256"},
        {"name": "nonce", "type": "bytes32"},
    ]
    # Numeric fields are hashed as ints and the nonce as raw bytes32, per
    # x402/mechanisms/evm/eip712.py:build_typed_data_for_signing.
    assert typed["message"]["value"] == 10000
    assert isinstance(typed["message"]["nonce"], bytes)


def test_signing_refuses_a_quote_without_the_eip712_domain():
    """No guessing: an unadvertised domain is how you sign something the token
    contract will reject."""
    option = make_option(extra={})
    auth = build_authorization(option, TEST_PAYER_ADDRESS)

    with pytest.raises(NoMatchingPaymentOption, match="EIP-712 domain"):
        sign_authorization(auth, option, TEST_PRIVATE_KEY)


def test_signing_refuses_a_non_eip155_network():
    option = make_option(network="solana:mainnet")
    auth = build_authorization(option, TEST_PAYER_ADDRESS)

    with pytest.raises(NoMatchingPaymentOption, match="eip155"):
        sign_authorization(auth, option, TEST_PRIVATE_KEY)


# --- cross-check against the SDK's own hashing algorithm --------------------

def _sdk_hash_struct(type_name, types, data):
    """Re-implementation of x402/mechanisms/evm/eip712.py `hash_struct`.

    Transcribed (not imported — `x402.mechanisms.evm` needs web3 7) so that our
    EIP-712 encoding is checked against the SDK's algorithm rather than against
    itself.
    """
    fields = types[type_name]
    field_strs = [f"{f['type']} {f['name']}" for f in fields]
    encoded = [keccak(text=f"{type_name}({','.join(field_strs)})")]
    for field in fields:
        value = data[field["name"]]
        ftype = field["type"]
        if ftype == "string":
            encoded.append(keccak(text=str(value)))
        elif ftype == "bytes32":
            encoded.append(value if isinstance(value, bytes) else bytes.fromhex(str(value).removeprefix("0x")))
        elif ftype == "address":
            encoded.append(abi_encode(["address"], [value]))
        elif ftype.startswith("uint"):
            encoded.append(abi_encode([ftype], [int(value)]))
        else:  # pragma: no cover - unused by these two structs
            raise AssertionError(f"unsupported field type {ftype}")
    return keccak(b"".join(encoded))


def test_our_eip712_encoding_matches_the_sdk_algorithm_byte_for_byte():
    option = make_option()
    auth = build_authorization(option, TEST_PAYER_ADDRESS, now=1_700_000_000)
    typed = build_typed_data(auth, option)

    sdk_domain_separator = _sdk_hash_struct(
        "EIP712Domain", typed["types"], typed["domain"]
    )
    sdk_struct_hash = _sdk_hash_struct(
        "TransferWithAuthorization", typed["types"], typed["message"]
    )

    signable = encode_typed_data(full_message=typed)
    # SignableMessage: version=b"\x01", header=domainSeparator, body=structHash.
    assert signable.header == sdk_domain_separator
    assert signable.body == sdk_struct_hash
    assert keccak(b"\x19\x01" + sdk_domain_separator + sdk_struct_hash) == keccak(
        b"\x19\x01" + signable.header + signable.body
    )


# ---------------------------------------------------------------------------
# 5. Payload shape + base64 round trip
# ---------------------------------------------------------------------------

def test_payload_validates_against_the_package_model_and_round_trips():
    option = make_option()
    auth = build_authorization(option, TEST_PAYER_ADDRESS, now=1_700_000_000)
    signature = sign_authorization(auth, option, TEST_PRIVATE_KEY)

    payload = build_payment_payload(option, auth, signature)
    assert isinstance(payload, PaymentPayload)

    header = encode_header(payload)
    decoded = json.loads(base64.b64decode(header))

    # Key names on the wire (ExactEIP3009Payload.to_dict + PaymentPayload).
    assert set(decoded) == {"x402Version", "payload", "accepted"}
    assert decoded["x402Version"] == 2
    assert set(decoded["payload"]) == {"authorization", "signature"}
    assert set(decoded["payload"]["authorization"]) == {
        "from", "to", "value", "validAfter", "validBefore", "nonce",
    }
    assert decoded["payload"]["authorization"]["value"] == "10000"
    assert decoded["accepted"]["payTo"] == CREATOR_WALLET
    assert decoded["accepted"]["maxTimeoutSeconds"] == 300

    # …and it survives a full round trip through the package's own model.
    assert PaymentPayload.model_validate(decoded) == payload


def test_accepted_is_the_servers_requirement_unmodified():
    """x402/server_base.py compares these fields for exact equality."""
    option = make_option(amount="40000000")
    auth = build_authorization(option, TEST_PAYER_ADDRESS)
    payload = build_payment_payload(
        option, auth, sign_authorization(auth, option, TEST_PRIVATE_KEY)
    )

    assert payload.accepted == option


def test_decode_payment_response_parses_a_settle_response():
    settle = decode_payment_response(base64.b64encode(json.dumps({
        "success": True, "transaction": TX_HASH, "network": NETWORK,
        "payer": TEST_PAYER_ADDRESS,
    }).encode()).decode())

    assert settle.success is True
    assert settle.transaction == TX_HASH


def test_decode_payment_response_rejects_garbage():
    with pytest.raises(PaymentFailed):
        decode_payment_response(base64.b64encode(b"{}").decode())


# ---------------------------------------------------------------------------
# 6. Spend cap
# ---------------------------------------------------------------------------

def test_spend_cap_default_is_one_usdc():
    assert enforce_spend_cap("1000000") == 1_000_000
    with pytest.raises(SpendCapExceeded, match="1000001"):
        enforce_spend_cap("1000001")


def test_spend_cap_reads_the_env_var(monkeypatch):
    monkeypatch.setenv(MAX_AMOUNT_ENV, "50000")
    assert enforce_spend_cap("50000") == 50_000
    with pytest.raises(SpendCapExceeded):
        enforce_spend_cap("50001")


def test_spend_cap_rejects_a_malformed_env_var(monkeypatch):
    monkeypatch.setenv(MAX_AMOUNT_ENV, "one dollar")
    with pytest.raises(ValueError, match=MAX_AMOUNT_ENV):
        enforce_spend_cap("1")


def test_spend_cap_rejects_a_non_integer_quote():
    with pytest.raises(ValueError, match="atomic units"):
        enforce_spend_cap("0.01")


# ---------------------------------------------------------------------------
# 7. pay_and_retry against a scripted fake resource server
# ---------------------------------------------------------------------------

class FakeResourceServer:
    """402 on the first call, then a scripted answer to the paid retry."""

    # `settle=None` means "send NO PAYMENT-RESPONSE header"; omitting the arg
    # means "send the default success". They are different scenarios, hence the
    # sentinel rather than a None default.
    _DEFAULT_SETTLE = object()

    def __init__(self, option=None, *, paid_status=200, settle=_DEFAULT_SETTLE,
                 paid_body=None):
        self.option = option or make_option()
        self.paid_status = paid_status
        self.settle = {
            "success": True, "transaction": TX_HASH,
            "network": NETWORK, "payer": TEST_PAYER_ADDRESS,
        } if settle is self._DEFAULT_SETTLE else settle
        self.paid_body = paid_body if paid_body is not None else {"items": ["a"], "total": 1}
        self.requests: list[dict] = []

    # NB: the kwarg is named `json` to match requests/httpx, which shadows the
    # stdlib module inside this method — hence `_json` below.
    def request(self, method, url, *, json=None, headers=None, **kwargs):
        headers = dict(headers or {})
        self.requests.append({"method": method, "url": url, "json": json,
                              "headers": headers, "kwargs": kwargs})
        payment_header = headers.get(PAYMENT_SIGNATURE_HEADER)
        if not payment_header:
            return FakeResponse(
                402,
                headers={PAYMENT_REQUIRED_HEADER: make_402_header(self.option)},
                content=b"{}",
            )
        resp_headers = {}
        if self.settle is not None:
            resp_headers[PAYMENT_RESPONSE_HEADER] = base64.b64encode(
                _json.dumps(self.settle).encode()
            ).decode()
        return FakeResponse(
            self.paid_status,
            headers=resp_headers,
            content=_json.dumps(self.paid_body).encode(),
        )

    def signed_payload(self) -> dict:
        header = self.requests[-1]["headers"][PAYMENT_SIGNATURE_HEADER]
        return json.loads(base64.b64decode(header))


def test_pay_and_retry_pays_once_and_returns_payment_info():
    server = FakeResourceServer()

    response, payment = pay_and_retry(
        server, "POST", f"{MCP_BASE_URL}/mcp/tools/call",
        json={"name": TOOL}, private_key=TEST_PRIVATE_KEY,
    )

    assert response.status_code == 200
    assert len(server.requests) == 2                 # exactly one retry
    assert PAYMENT_SIGNATURE_HEADER not in server.requests[0]["headers"]
    assert payment == {
        "method": "x402",
        "tx_hash": TX_HASH,
        "network": NETWORK,
        "payer": TEST_PAYER_ADDRESS,
        "payee": CREATOR_WALLET,
        "amount_atomic": "10000",
        "asset": DEFAULT_USDC_ADDRESS,
        "settle_success": True,
    }


def test_pay_and_retry_forwards_the_body_and_kwargs_to_both_attempts():
    server = FakeResourceServer()

    pay_and_retry(
        server, "POST", f"{MCP_BASE_URL}/mcp/tools/call",
        json={"name": TOOL, "arguments": {"limit": 3}},
        private_key=TEST_PRIVATE_KEY, timeout=5.0, allow_redirects=False,
    )

    for call in server.requests:
        assert call["json"] == {"name": TOOL, "arguments": {"limit": 3}}
        assert call["kwargs"] == {"timeout": 5.0, "allow_redirects": False}


def test_pay_and_retry_does_not_pay_when_there_is_no_402():
    class Free:
        def __init__(self):
            self.calls = 0

        def request(self, method, url, **kwargs):
            self.calls += 1
            return FakeResponse(200, content=b'{"items": [], "total": 0}')

    free = Free()
    response, payment = pay_and_retry(
        free, "POST", MCP_BASE_URL, json={}, private_key=TEST_PRIVATE_KEY
    )

    assert response.status_code == 200
    assert payment is None
    assert free.calls == 1


def test_pay_and_retry_without_a_key_raises_payment_required():
    server = FakeResourceServer()

    with pytest.raises(PaymentRequiredError, match=PAYER_KEY_ENV):
        pay_and_retry(server, "POST", MCP_BASE_URL, json={}, private_key="")

    assert len(server.requests) == 1                 # nothing was retried


def test_pay_and_retry_refuses_an_over_cap_quote_without_signing():
    server = FakeResourceServer(option=make_option(amount="2000000"))   # $2

    with pytest.raises(SpendCapExceeded, match="2000000"):
        pay_and_retry(server, "POST", MCP_BASE_URL, json={}, private_key=TEST_PRIVATE_KEY)

    assert len(server.requests) == 1                 # never signed, never retried


def test_pay_and_retry_honours_an_explicit_max_amount():
    server = FakeResourceServer(option=make_option(amount="10000"))

    with pytest.raises(SpendCapExceeded):
        pay_and_retry(server, "POST", MCP_BASE_URL, json={},
                      private_key=TEST_PRIVATE_KEY, max_amount=9_999)


def test_pay_and_retry_raises_on_a_failed_settlement():
    server = FakeResourceServer(
        paid_status=402,
        settle={"success": False, "errorReason": "insufficient_funds",
                "transaction": "", "network": NETWORK, "payer": TEST_PAYER_ADDRESS},
    )

    with pytest.raises(PaymentFailed) as excinfo:
        pay_and_retry(server, "POST", MCP_BASE_URL, json={}, private_key=TEST_PRIVATE_KEY)

    assert "insufficient_funds" in str(excinfo.value)
    assert len(server.requests) == 2                 # and no third attempt


def test_pay_and_retry_raises_on_a_second_402_with_no_settle_header():
    server = FakeResourceServer(paid_status=402, settle=None)

    with pytest.raises(PaymentFailed, match="still requires payment"):
        pay_and_retry(server, "POST", MCP_BASE_URL, json={}, private_key=TEST_PRIVATE_KEY)


def test_pay_and_retry_raises_when_a_200_carries_no_settlement_proof():
    """We handed over a redeemable authorization; "unpaid" would be a lie."""
    server = FakeResourceServer(paid_status=200, settle=None)

    with pytest.raises(PaymentFailed, match="unconfirmed"):
        pay_and_retry(server, "POST", MCP_BASE_URL, json={}, private_key=TEST_PRIVATE_KEY)


# ---------------------------------------------------------------------------
# 7b. Stage 2 / WP-R (review F2 + F8): "signed and transmitted" is not the same
# failure as "refused before signing".
#
# The line: an authorization that LEFT this process and got no decodable answer
# is PaymentOutcomeUnknown, and the caller must freeze rather than re-sign. A
# server that explicitly says "I am not paid" (402, or a decodable
# success=false) is a plain PaymentFailed and stays retriable.
# ---------------------------------------------------------------------------

class _GarbageSettleHeaderServer(FakeResourceServer):
    """200 on the paid retry, with a PAYMENT-RESPONSE that will not decode."""

    def request(self, method, url, **kwargs):
        response = super().request(method, url, **kwargs)
        if response.status_code != 402:
            response.headers[PAYMENT_RESPONSE_HEADER] = "not%%%base64"
        return response


class _RaisesOnThePaidRetry:
    """402 first, then the transport blows up carrying our signature."""

    def __init__(self, exc=None):
        self.option = make_option()
        self.exc = exc or requests.ConnectionError("connection reset by peer")
        self.requests = []

    def request(self, method, url, *, json=None, headers=None, **kwargs):
        headers = dict(headers or {})
        self.requests.append(headers)
        if not headers.get(PAYMENT_SIGNATURE_HEADER):
            return FakeResponse(
                402,
                headers={PAYMENT_REQUIRED_HEADER: make_402_header(self.option)},
                content=b"{}",
            )
        raise self.exc


def _assert_names_the_authorization(exc, server=None):
    """The exception must carry enough to find the authorization on-chain."""
    assert exc.payee == CREATOR_WALLET
    assert exc.amount_atomic == "10000"
    assert exc.nonce.startswith("0x") and len(exc.nonce) == 66
    if server is not None:
        signed = server.signed_payload()["payload"]["authorization"]
        assert exc.nonce == signed["nonce"]      # the one actually signed


def test_a_200_with_no_settlement_proof_is_outcome_unknown():
    """Review F2. The authorization is redeemable and we never heard back."""
    server = FakeResourceServer(paid_status=200, settle=None)

    with pytest.raises(PaymentOutcomeUnknown) as excinfo:
        pay_and_retry(server, "POST", MCP_BASE_URL, json={},
                      private_key=TEST_PRIVATE_KEY)

    assert "unconfirmed" in str(excinfo.value)
    _assert_names_the_authorization(excinfo.value, server)
    assert len(server.requests) == 2             # and no third attempt


def test_an_unreadable_settlement_header_is_outcome_unknown():
    server = _GarbageSettleHeaderServer(paid_status=200)

    with pytest.raises(PaymentOutcomeUnknown) as excinfo:
        pay_and_retry(server, "POST", MCP_BASE_URL, json={},
                      private_key=TEST_PRIVATE_KEY)

    assert "unreadable" in str(excinfo.value)
    _assert_names_the_authorization(excinfo.value, server)


def test_a_transport_error_on_the_paid_retry_is_outcome_unknown():
    """The signature was already on the wire; a reset says nothing about it."""
    server = _RaisesOnThePaidRetry()

    with pytest.raises(PaymentOutcomeUnknown) as excinfo:
        pay_and_retry(server, "POST", MCP_BASE_URL, json={},
                      private_key=TEST_PRIVATE_KEY)

    assert "ConnectionError" in str(excinfo.value)
    _assert_names_the_authorization(excinfo.value)
    assert len(server.requests) == 2             # signed once, never re-signed


def test_a_success_with_an_empty_transaction_is_outcome_unknown():
    """Review F8. `SettleResponse.transaction` is a str with no min_length, so
    success=true + "" is schema-valid — and would settle a run with no hash."""
    server = FakeResourceServer(
        paid_status=200,
        settle={"success": True, "transaction": "",
                "network": NETWORK, "payer": TEST_PAYER_ADDRESS},
    )

    with pytest.raises(PaymentOutcomeUnknown) as excinfo:
        pay_and_retry(server, "POST", MCP_BASE_URL, json={},
                      private_key=TEST_PRIVATE_KEY)

    assert "empty transaction" in str(excinfo.value)
    _assert_names_the_authorization(excinfo.value, server)


def test_an_explicit_settlement_failure_is_not_outcome_unknown():
    """The facilitator said it did not settle. That IS an answer: retriable."""
    server = FakeResourceServer(
        paid_status=402,
        settle={"success": False, "errorReason": "insufficient_funds",
                "transaction": "", "network": NETWORK,
                "payer": TEST_PAYER_ADDRESS},
    )

    with pytest.raises(PaymentFailed) as excinfo:
        pay_and_retry(server, "POST", MCP_BASE_URL, json={},
                      private_key=TEST_PRIVATE_KEY)

    assert not isinstance(excinfo.value, PaymentOutcomeUnknown)


def test_a_402_on_the_retry_is_not_outcome_unknown():
    """402 is the server stating 'I am not paid'. The gate reaches it only via
    a failed verify (settle never called) or a failed settle — neither moved
    money, so the caller may retry."""
    server = FakeResourceServer(paid_status=402, settle=None)

    with pytest.raises(PaymentFailed) as excinfo:
        pay_and_retry(server, "POST", MCP_BASE_URL, json={},
                      private_key=TEST_PRIVATE_KEY)

    assert not isinstance(excinfo.value, PaymentOutcomeUnknown)


@pytest.mark.parametrize("server,key,expected", [
    (FakeResourceServer(option=make_option(amount="2000000")), TEST_PRIVATE_KEY,
     SpendCapExceeded),
    (FakeResourceServer(), "", PaymentRequiredError),
    (FakeResourceServer(option=make_option(network="eip155:1")), TEST_PRIVATE_KEY,
     NoMatchingPaymentOption),
])
def test_pre_signing_refusals_are_never_outcome_unknown(server, key, expected):
    """Nothing was signed, so there is nothing in limbo — the caller is free to
    fix the cause and retry."""
    with pytest.raises(expected) as excinfo:
        pay_and_retry(server, "POST", MCP_BASE_URL, json={}, private_key=key)

    assert not isinstance(excinfo.value, PaymentOutcomeUnknown)
    assert len(server.requests) == 1             # never retried


def test_pay_and_retry_refuses_a_quote_on_another_network():
    server = FakeResourceServer(option=make_option(network="eip155:1"))

    with pytest.raises(NoMatchingPaymentOption):
        pay_and_retry(server, "POST", MCP_BASE_URL, json={}, private_key=TEST_PRIVATE_KEY)


def test_the_signed_payload_the_server_receives_recovers_to_our_payer():
    server = FakeResourceServer()
    pay_and_retry(server, "POST", MCP_BASE_URL, json={}, private_key=TEST_PRIVATE_KEY)

    sent = server.signed_payload()
    option = PaymentRequirements.model_validate(sent["accepted"])
    auth = sent["payload"]["authorization"]

    signable = encode_typed_data(full_message=build_typed_data(auth, option))
    recovered = Account.recover_message(signable, signature=sent["payload"]["signature"])
    assert recovered == TEST_PAYER_ADDRESS
    assert auth["from"] == TEST_PAYER_ADDRESS
    assert auth["to"] == CREATOR_WALLET
    assert auth["value"] == "10000"


# ---------------------------------------------------------------------------
# 8. In-process end to end: real gate + real MCP server + real mcp_client
# ---------------------------------------------------------------------------

class FlaskRequestsAdapter(requests.adapters.BaseAdapter):
    """Routes `requests` traffic into a Flask app, in process, no sockets.

    Lets the REAL `mcp_client.call_mcp_tool` (which speaks `requests`) drive the
    REAL gated MCP app, so the end-to-end test exercises production code paths
    rather than a re-implementation of them.
    """

    def __init__(self, app):
        super().__init__()
        self.client = app.test_client()

    def send(self, request, **kwargs):
        parsed = urlparse(request.url)
        rv = self.client.open(
            method=request.method,
            path=parsed.path,
            query_string=parsed.query,
            data=request.body,
            headers=dict(request.headers),
        )
        response = requests.Response()
        response.status_code = rv.status_code
        response._content = rv.data
        response.headers.update({k: v for k, v in rv.headers.items()})
        response.url = request.url
        response.request = request
        return response

    def close(self):
        pass


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = path
    init_db(app)
    yield path
    os.unlink(path)


def _insert_asset(db_path, *, price_amount=1):
    """One SkillAsset priced at $0.01 -> 10_000 USDC atomic units."""
    return insert_skill_asset(db_path, {
        "creator_id": "zhang_ai",
        "name": "客服话术 Agent",
        "description": "e2e asset",
        "type": "agent",
        "endpoint_url": ENDPOINT_URL,
        "io_schema": {"input": {}, "output": {}},
        "price_amount": price_amount,
        "price_currency": "USD",
        "price_chain": None,
        "split_rule": {"creator": 7000, "platform": 2000, "tax": 1000},
        "content_hash": uuid.uuid4().hex,
        "wallet_address": CREATOR_WALLET,
    })


def _gated_session(db_path, monkeypatch, facilitator):
    """A requests.Session wired to the real, gated demo MCP app."""
    monkeypatch.delenv("HIRENET_X402_GATE", raising=False)
    app = create_mcp_app()
    monkeypatch.setenv("HIRENET_X402_GATE", "1")
    assert install_x402_gate(
        app,
        db_path=db_path,
        tool_endpoints={TOOL: ENDPOINT_URL},
        facilitator_url="https://facilitator.test",
        http_client=facilitator.client(),
    ) is True

    session = requests.Session()
    session.mount(MCP_BASE_URL, FlaskRequestsAdapter(app))
    return session


def _ungated_preview(limit):
    """What the SAME tool call returns with no paywall in front of it.

    Read straight off the demo server's canned data rather than by building a
    second app, because `HIRENET_X402_GATE` is already "1" at this point and a
    fresh `create_mcp_app()` would gate itself against the operator's real DB.
    """
    from app.mcp_servers.customer_service import _GREETINGS

    return _GREETINGS[:limit][:5]


def test_end_to_end_paid_invocation(db_path, monkeypatch):
    """402 -> payer signs -> 200, with the tool result byte-identical."""
    _insert_asset(db_path)
    facilitator = FacilitatorStub()
    session = _gated_session(db_path, monkeypatch, facilitator)
    monkeypatch.setenv(PAYER_KEY_ENV, TEST_PRIVATE_KEY)

    result = call_mcp_tool(
        MCP_BASE_URL, TOOL, {"task_id": "t-1", "limit": 3}, session=session
    )

    assert result["status"] == "ok", result
    assert result["tool"] == TOOL
    # Byte-identical to what the ungated server returns for the same arguments.
    assert result["total"] == 3
    assert result["preview"] == _ungated_preview(3)

    payment = result["payment"]
    assert payment["method"] == "x402"
    assert payment["tx_hash"] == TX_HASH
    assert payment["network"] == NETWORK
    assert payment["payee"] == CREATOR_WALLET        # the creator, not us
    # `payer` is whatever the facilitator recovered from the signature. The
    # WP-B stub always echoes its own fixed PAYER constant, so this asserts the
    # plumbing, not the recovery; the test below does the real recovery check.
    assert payment["payer"] == STUB_PAYER
    assert payment["amount_atomic"] == "10000"       # $0.01, verbatim
    assert payment["asset"] == DEFAULT_USDC_ADDRESS
    assert payment["settle_success"] is True

    # verify then settle, once each.
    assert facilitator.calls == ["supported", "verify", "settle"]


def test_end_to_end_the_facilitator_sees_a_signature_from_our_payer(db_path, monkeypatch):
    """The shapes the gate forwards are the shapes we signed."""
    _insert_asset(db_path)
    facilitator = FacilitatorStub()
    session = _gated_session(db_path, monkeypatch, facilitator)
    monkeypatch.setenv(PAYER_KEY_ENV, TEST_PRIVATE_KEY)

    assert call_mcp_tool(MCP_BASE_URL, TOOL, session=session)["status"] == "ok"

    body = facilitator.verify_bodies[0]
    forwarded = body["paymentPayload"]
    option = PaymentRequirements.model_validate(forwarded["accepted"])
    auth = forwarded["payload"]["authorization"]

    signable = encode_typed_data(full_message=build_typed_data(auth, option))
    recovered = Account.recover_message(
        signable, signature=forwarded["payload"]["signature"]
    )
    assert recovered == TEST_PAYER_ADDRESS

    # …and it authorises exactly what the server asked for.
    assert body["paymentRequirements"]["payTo"] == CREATOR_WALLET
    assert body["paymentRequirements"]["amount"] == "10000"
    assert auth["to"] == CREATOR_WALLET
    assert auth["value"] == "10000"


def test_end_to_end_failed_settlement_records_no_payment(db_path, monkeypatch):
    """Negative twin: settle says success=false -> no result, no payment."""
    _insert_asset(db_path)
    facilitator = FacilitatorStub(settle_success=False)
    session = _gated_session(db_path, monkeypatch, facilitator)
    monkeypatch.setenv(PAYER_KEY_ENV, TEST_PRIVATE_KEY)

    result = call_mcp_tool(MCP_BASE_URL, TOOL, session=session)

    assert result["status"] == "error"
    assert result["payment"] is None
    assert "PaymentFailed" in result["error"]
    assert "settlement_failed" in result["error"]
    assert facilitator.calls == ["supported", "verify", "settle"]


def test_end_to_end_without_a_key_reports_payment_required(db_path, monkeypatch):
    _insert_asset(db_path)
    facilitator = FacilitatorStub()
    session = _gated_session(db_path, monkeypatch, facilitator)
    monkeypatch.delenv(PAYER_KEY_ENV, raising=False)

    result = call_mcp_tool(MCP_BASE_URL, TOOL, session=session)

    assert result["status"] == "error"
    assert result["payment"] is None
    assert "PaymentRequiredError" in result["error"]
    assert PAYER_KEY_ENV in result["error"]
    # Nothing was signed, so the facilitator never got past /supported.
    assert facilitator.calls == ["supported"]


def test_end_to_end_over_cap_price_is_refused(db_path, monkeypatch):
    """A $40 asset against the default $1 cap: refused before signing."""
    _insert_asset(db_path, price_amount=4000)        # $40 -> 40_000_000 atomic
    facilitator = FacilitatorStub()
    session = _gated_session(db_path, monkeypatch, facilitator)
    monkeypatch.setenv(PAYER_KEY_ENV, TEST_PRIVATE_KEY)

    result = call_mcp_tool(MCP_BASE_URL, TOOL, session=session)

    assert result["status"] == "error"
    assert "SpendCapExceeded" in result["error"]
    assert "40000000" in result["error"]
    assert result["payment"] is None
    assert facilitator.calls == ["supported"]        # never verified


def test_ungated_server_still_works_and_reports_no_payment(db_path, monkeypatch):
    """Key configured, but the route is free: no payment, unchanged result."""
    monkeypatch.delenv("HIRENET_X402_GATE", raising=False)
    app = create_mcp_app()
    session = requests.Session()
    session.mount(MCP_BASE_URL, FlaskRequestsAdapter(app))
    monkeypatch.setenv(PAYER_KEY_ENV, TEST_PRIVATE_KEY)

    result = call_mcp_tool(MCP_BASE_URL, TOOL, {"limit": 3}, session=session)

    assert result["status"] == "ok"
    assert result["total"] == 3
    assert result["payment"] is None


def test_a_malformed_spend_cap_does_not_escape_as_an_exception(db_path, monkeypatch):
    """call_mcp_tool must never raise: app.py calls it after committing royalty."""
    _insert_asset(db_path)
    facilitator = FacilitatorStub()
    session = _gated_session(db_path, monkeypatch, facilitator)
    monkeypatch.setenv(PAYER_KEY_ENV, TEST_PRIVATE_KEY)
    monkeypatch.setenv(MAX_AMOUNT_ENV, "one dollar")

    result = call_mcp_tool(MCP_BASE_URL, TOOL, session=session)

    assert result["status"] == "error"
    assert MAX_AMOUNT_ENV in result["error"]
    assert result["payment"] is None


def test_existing_error_shapes_still_carry_the_new_key():
    """The additive `payment` key is on every result, including old failures."""
    result = call_mcp_tool("file:///etc/passwd", TOOL)
    assert result["status"] == "error"
    assert result["payment"] is None
    assert set(result) == {"status", "tool", "error", "endpoint_url", "payment"}


def test_the_private_key_never_reaches_a_result_or_a_message(db_path, monkeypatch):
    """Nothing that leaves this module may contain the key."""
    _insert_asset(db_path)
    facilitator = FacilitatorStub()
    session = _gated_session(db_path, monkeypatch, facilitator)
    monkeypatch.setenv(PAYER_KEY_ENV, TEST_PRIVATE_KEY)

    paid = call_mcp_tool(MCP_BASE_URL, TOOL, session=session)
    monkeypatch.setenv(MAX_AMOUNT_ENV, "1")          # now the same call is refused
    refused = call_mcp_tool(MCP_BASE_URL, TOOL, session=session)

    assert paid["status"] == "ok"
    assert "SpendCapExceeded" in refused["error"]
    for result in (paid, refused):
        blob = json.dumps(result)
        assert TEST_PRIVATE_KEY not in blob
        assert TEST_PRIVATE_KEY.removeprefix("0x") not in blob


def test_mcp_client_reads_the_key_from_the_environment_only(monkeypatch):
    """No module-level key cache: the env var is read per call."""
    assert not hasattr(mcp_client_module, "PRIVATE_KEY")
    source = open(mcp_client_module.__file__).read()
    assert TEST_PRIVATE_KEY not in source
    assert "X402_PAYER_PRIVATE_KEY" in source


# ---------------------------------------------------------------------------
# 9. Stage 2 / WP-R (review F2): the mcp_client fold for an unknown outcome.
# ---------------------------------------------------------------------------

class _LosesTheSettlementHeader:
    """Session wrapper that drops PAYMENT-RESPONSE from the gate's answer.

    Everything upstream is real and untouched: the facilitator settled, the
    gate wrote the header, and only the payer's view of it is lost.
    """

    def __init__(self, inner):
        self.inner = inner

    def request(self, method, url, **kwargs):
        response = self.inner.request(method, url, **kwargs)
        response.headers.pop(PAYMENT_RESPONSE_HEADER, None)
        return response


def test_an_unknown_outcome_is_folded_as_unknown_not_error(db_path, monkeypatch):
    """`status: "error"` here is the double-pay exposure: it reads as "nothing
    happened", and the only sane response to that is to sign again."""
    _insert_asset(db_path)
    facilitator = FacilitatorStub()
    session = _LosesTheSettlementHeader(
        _gated_session(db_path, monkeypatch, facilitator)
    )
    monkeypatch.setenv(PAYER_KEY_ENV, TEST_PRIVATE_KEY)

    result = call_mcp_tool(MCP_BASE_URL, TOOL, session=session)

    assert result["status"] == "unknown"
    assert "PaymentOutcomeUnknown" in result["error"]
    # No CONFIRMED payment — the additive key keeps its meaning.
    assert result["payment"] is None
    pending = result["payment_pending"]
    assert pending["payee"] == CREATOR_WALLET
    assert pending["amount_atomic"] == "10000"
    assert pending["nonce"].startswith("0x") and len(pending["nonce"]) == 66
    assert PAYMENT_RESPONSE_HEADER in pending["error"]
    # …and the facilitator really did settle it.
    assert facilitator.calls == ["supported", "verify", "settle"]
