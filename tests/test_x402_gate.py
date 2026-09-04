"""Stage 2 / WP-B: the x402 gate on the SkillAsset invocation endpoint.

Everything here runs against the REAL demo MCP app (`create_mcp_app()`), the
REAL x402 Flask middleware and the REAL pydantic schemas. Only one thing is
faked: the facilitator, stubbed at the httpx boundary with
`httpx.MockTransport`, so /supported, /verify and /settle answer from a script
in-process. `no_real_network` (autouse) fails the test if anything tries to
open a socket or use a real httpx transport, so a stub going missing shows up
as a failure rather than as a live call to https://x402.org/facilitator.

What these tests DO establish: request/response shapes, header names, who gets
paid, how much, and the order of facilitator calls.
What they do NOT establish: that a live facilitator accepts our requirements,
or that any USDC ever moves. See the module docstring of app/services/x402_gate.py.
"""
import base64
import json
import os
import socket
import tempfile
import uuid
from decimal import Decimal

import httpx
import pytest
from flask import Flask

from app.mcp_servers.customer_service import create_mcp_app
from app.services.x402_gate import (
    DEFAULT_USDC_ADDRESS,
    GATE_INSTALLED_CONFIG_KEY,
    asset_price_atomic,
    install_x402_gate,
    usd_to_atomic,
)
from app.storage.db import init_db
from app.storage.skill_assets import insert_skill_asset

NETWORK = "eip155:84532"
ENDPOINT_URL = "http://localhost:5002"
CREATOR_WALLET = "0xf2E28A84e8d51ca87CB50768a0Ebe0E29F53F7B7"
PAYER = "0x1111111111111111111111111111111111111111"
TX_HASH = "0xabc123def4567890abc123def4567890abc123def4567890abc123def4567890"

# The three tools app/mcp_servers/customer_service.py serves.
TOOL = "generate_greeting"


# ---------------------------------------------------------------------------
# Guards + fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """Fail loudly if a test would touch the network."""
    def _boom(*args, **kwargs):
        raise AssertionError(
            "x402 gate tests must not make real network calls; the facilitator "
            "is stubbed with httpx.MockTransport."
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _boom)
    monkeypatch.setattr(socket.socket, "connect", _boom)


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = path
    init_db(app)
    yield path
    os.unlink(path)


def _insert_asset(db_path, *, wallet=CREATOR_WALLET, price_amount=1,
                  price_currency="USD", endpoint_url=ENDPOINT_URL):
    """One SkillAsset row served by this MCP endpoint.

    price_amount=1 is 1 USD "基点" = $0.01 (app/app.py: price_amount / 100),
    which is 10_000 USDC atomic units — the number the 402 must quote.
    """
    return insert_skill_asset(db_path, {
        "creator_id": "zhang_ai",
        "name": "SEO 优化 Agent",
        "description": "test asset",
        "type": "agent",
        "endpoint_url": endpoint_url,
        "io_schema": {"input": {}, "output": {}},
        "price_amount": price_amount,
        "price_currency": price_currency,
        "price_chain": None,
        "split_rule": {"creator": 7000, "platform": 2000, "tax": 1000},
        "content_hash": uuid.uuid4().hex,
        "wallet_address": wallet,
    })


class FacilitatorStub:
    """Scripted facilitator behind an httpx.MockTransport. Records every call."""

    def __init__(self, *, verify_valid=True, settle_success=True,
                 invalid_reason="insufficient_funds"):
        self.verify_valid = verify_valid
        self.settle_success = settle_success
        self.invalid_reason = invalid_reason
        self.calls: list[str] = []
        self.verify_bodies: list[dict] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/supported"):
            self.calls.append("supported")
            return httpx.Response(200, json={
                "kinds": [{"x402Version": 2, "scheme": "exact", "network": NETWORK}],
                "extensions": [],
                "signers": {},
            })
        if path.endswith("/verify"):
            self.calls.append("verify")
            self.verify_bodies.append(json.loads(request.content))
            if self.verify_valid:
                return httpx.Response(200, json={"isValid": True, "payer": PAYER})
            return httpx.Response(200, json={
                "isValid": False, "invalidReason": self.invalid_reason, "payer": PAYER,
            })
        if path.endswith("/settle"):
            self.calls.append("settle")
            if self.settle_success:
                return httpx.Response(200, json={
                    "success": True, "transaction": TX_HASH,
                    "network": NETWORK, "payer": PAYER,
                })
            return httpx.Response(200, json={
                "success": False, "errorReason": "settlement_failed",
                "transaction": "", "network": NETWORK, "payer": PAYER,
            })
        raise AssertionError(f"unexpected facilitator path {path!r}")

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._handle))


def _gated_client(db_path, monkeypatch, facilitator=None, tools=(TOOL,)):
    """The real MCP app with the gate installed and a stubbed facilitator."""
    facilitator = facilitator or FacilitatorStub()
    # Build the app with the flag OFF so create_mcp_app does NOT install its own
    # gate (that one would point at the operator's real ~/.hirenet DB and stack a
    # second paywall underneath ours). Then flip the flag and install the gate
    # ourselves, which is the only way to inject the stubbed facilitator client.
    monkeypatch.delenv("HIRENET_X402_GATE", raising=False)
    app = create_mcp_app()
    monkeypatch.setenv("HIRENET_X402_GATE", "1")
    installed = install_x402_gate(
        app,
        db_path=db_path,
        tool_endpoints={name: ENDPOINT_URL for name in tools},
        facilitator_url="https://facilitator.test",
        http_client=facilitator.client(),
    )
    assert installed is True
    return app.test_client(), facilitator


def _accepts(response):
    """The single accepted option out of the 402's PAYMENT-REQUIRED header."""
    header = response.headers["PAYMENT-REQUIRED"]
    body = json.loads(base64.b64decode(header))
    assert body["x402Version"] == 2
    return body["accepts"]


def _payment_header(accepts_entry):
    """A base64 v2 PaymentPayload echoing the server's own requirements.

    The inner `payload` is NOT a real EIP-3009 authorization — validating that
    is the facilitator's job, and the facilitator is stubbed here.
    """
    return base64.b64encode(json.dumps({
        "x402Version": 2,
        "payload": {"authorization": {"from": PAYER}, "signature": "0x" + "11" * 65},
        "accepted": accepts_entry,
    }).encode()).decode()


# ---------------------------------------------------------------------------
# 1. Gate OFF (the default) changes nothing
# ---------------------------------------------------------------------------

def test_gate_off_by_default_route_is_unchanged(monkeypatch):
    monkeypatch.delenv("HIRENET_X402_GATE", raising=False)
    app = create_mcp_app()
    assert app.config.get(GATE_INSTALLED_CONFIG_KEY, False) is False

    c = app.test_client()
    resp = c.post("/mcp/tools/call", json={"name": TOOL, "arguments": {"limit": 3}})
    assert resp.status_code == 200
    assert resp.get_json()["total"] == 3
    assert "PAYMENT-REQUIRED" not in resp.headers


def test_install_is_a_noop_without_the_env_flag(db_path, monkeypatch):
    monkeypatch.delenv("HIRENET_X402_GATE", raising=False)
    app = create_mcp_app()
    assert install_x402_gate(app, db_path=db_path,
                             tool_endpoints={TOOL: ENDPOINT_URL}) is False
    assert app.config[GATE_INSTALLED_CONFIG_KEY] is False
    # ...and the route is still free.
    resp = app.test_client().post("/mcp/tools/call", json={"name": TOOL})
    assert resp.status_code == 200


def test_create_mcp_app_installs_the_gate_when_the_flag_is_on(monkeypatch):
    """The wiring itself: env flag on -> create_mcp_app() gates the route.

    No request is issued, so no facilitator is contacted; this asserts only
    that the MCP server calls install_x402_gate at app creation.
    """
    monkeypatch.setenv("HIRENET_X402_GATE", "1")
    app = create_mcp_app()
    assert app.config[GATE_INSTALLED_CONFIG_KEY] is True


def test_data_analysis_server_is_gated_too(monkeypatch):
    """Both demo MCP servers are wired, not just customer_service."""
    from app.mcp_servers.data_analysis import create_app as create_data_analysis_app

    monkeypatch.delenv("HIRENET_X402_GATE", raising=False)
    assert create_data_analysis_app().config.get(GATE_INSTALLED_CONFIG_KEY, False) is False

    monkeypatch.setenv("HIRENET_X402_GATE", "1")
    assert create_data_analysis_app().config[GATE_INSTALLED_CONFIG_KEY] is True


# ---------------------------------------------------------------------------
# 2. Gate ON, no payment -> 402 quoting the creator's wallet and price
# ---------------------------------------------------------------------------

def test_no_payment_header_returns_402_with_our_single_option(db_path, monkeypatch):
    _insert_asset(db_path, price_amount=1)         # $0.01
    c, fac = _gated_client(db_path, monkeypatch)

    resp = c.post("/mcp/tools/call", json={"name": TOOL, "arguments": {}})

    assert resp.status_code == 402
    accepts = _accepts(resp)
    assert len(accepts) == 1
    option = accepts[0]
    assert option["scheme"] == "exact"
    assert option["network"] == NETWORK
    assert option["asset"] == DEFAULT_USDC_ADDRESS
    assert option["payTo"] == CREATOR_WALLET          # the creator's own wallet
    assert option["amount"] == "10000"                # $0.01 -> 10_000 atomic
    assert option["extra"]["name"] == "USDC"          # EIP-712 domain
    assert option["extra"]["version"] == "2"
    # Only /supported was needed; nothing was verified or settled.
    assert fac.calls == ["supported"]


def test_402_price_tracks_the_asset_row(db_path, monkeypatch):
    _insert_asset(db_path, price_amount=4000)         # $40, the demo analyst price
    c, _ = _gated_client(db_path, monkeypatch)

    resp = c.post("/mcp/tools/call", json={"name": TOOL})
    assert _accepts(resp)[0]["amount"] == "40000000"  # 40 * 10**6


def test_unknown_tool_is_not_charged_and_still_400s(db_path, monkeypatch):
    """A call that yields no tool result is not a paywall bypass."""
    _insert_asset(db_path)
    c, fac = _gated_client(db_path, monkeypatch)

    resp = c.post("/mcp/tools/call", json={"name": "does_not_exist"})
    assert resp.status_code == 400
    assert "Unknown tool" in resp.get_json()["error"]
    assert fac.calls == []


def test_health_route_is_not_gated(db_path, monkeypatch):
    _insert_asset(db_path)
    c, fac = _gated_client(db_path, monkeypatch)

    resp = c.get("/health")
    assert resp.status_code == 200
    assert fac.calls == []


# ---------------------------------------------------------------------------
# 3. No payee -> 503, and the facilitator is never involved
# ---------------------------------------------------------------------------

def test_asset_without_wallet_returns_503_and_never_calls_the_facilitator(db_path, monkeypatch):
    _insert_asset(db_path, wallet=None)
    c, fac = _gated_client(db_path, monkeypatch)

    resp = c.post("/mcp/tools/call", json={"name": TOOL})

    assert resp.status_code == 503
    assert resp.get_json() == {"error": "asset has no payout wallet"}
    assert fac.calls == []
    # And no tool result leaked out of the refusal.
    assert "items" not in (resp.get_json() or {})


def test_no_registered_asset_for_the_endpoint_returns_503(db_path, monkeypatch):
    _insert_asset(db_path, endpoint_url="http://localhost:9999")
    c, fac = _gated_client(db_path, monkeypatch)

    resp = c.post("/mcp/tools/call", json={"name": TOOL})
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "no SkillAsset registered for this MCP endpoint"
    assert fac.calls == []


def test_non_usd_price_is_refused_rather_than_treated_as_usdc(db_path, monkeypatch):
    _insert_asset(db_path, price_currency="CNY")
    c, fac = _gated_client(db_path, monkeypatch)

    resp = c.post("/mcp/tools/call", json={"name": TOOL})
    assert resp.status_code == 503
    assert "not USD" in resp.get_json()["error"]
    assert fac.calls == []


# ---------------------------------------------------------------------------
# 4. Bad payment headers
# ---------------------------------------------------------------------------

def test_garbage_payment_header_returns_402_without_reaching_the_facilitator(db_path, monkeypatch):
    """Observed behaviour, deliberately asserted.

    The brief expected `verify` to be called for a garbage header. The x402
    middleware instead fails to decode it locally and answers 402 with a fresh
    quote — strictly better (no facilitator round-trip on junk). The
    facilitator-rejects case below is what exercises the verify path.
    """
    _insert_asset(db_path)
    c, fac = _gated_client(db_path, monkeypatch)

    resp = c.post("/mcp/tools/call", json={"name": TOOL},
                  headers={"PAYMENT-SIGNATURE": "not-base64-!!!"})

    assert resp.status_code == 402
    assert fac.calls == ["supported"]
    assert "PAYMENT-RESPONSE" not in resp.headers


def test_facilitator_rejects_payment_402_and_settle_is_not_called(db_path, monkeypatch):
    _insert_asset(db_path)
    fac = FacilitatorStub(verify_valid=False)
    c, fac = _gated_client(db_path, monkeypatch, facilitator=fac)

    quote = _accepts(c.post("/mcp/tools/call", json={"name": TOOL}))[0]
    resp = c.post("/mcp/tools/call", json={"name": TOOL},
                  headers={"PAYMENT-SIGNATURE": _payment_header(quote)})

    assert resp.status_code == 402
    assert fac.calls == ["supported", "verify"]     # settle NOT called
    assert "PAYMENT-RESPONSE" not in resp.headers
    # The tool result must not leak on a rejected payment.
    assert b"generate_greeting" not in resp.data


# ---------------------------------------------------------------------------
# 5. Happy path: verify -> handler -> settle -> 200 + PAYMENT-RESPONSE
# ---------------------------------------------------------------------------

def test_valid_payment_runs_the_handler_and_settles(db_path, monkeypatch):
    _insert_asset(db_path)
    c, fac = _gated_client(db_path, monkeypatch)

    quote = _accepts(c.post("/mcp/tools/call", json={"name": TOOL}))[0]
    resp = c.post("/mcp/tools/call",
                  json={"name": TOOL, "arguments": {"task_id": "t-1", "limit": 3}},
                  headers={"PAYMENT-SIGNATURE": _payment_header(quote)})

    assert resp.status_code == 200
    assert fac.calls == ["supported", "verify", "settle"]

    # The tool result is exactly what the ungated server returns.
    body = resp.get_json()
    assert body["name"] == TOOL
    assert body["task_id"] == "t-1"
    assert body["total"] == 3
    assert len(body["items"]) == 3

    settled = json.loads(base64.b64decode(resp.headers["PAYMENT-RESPONSE"]))
    assert settled["success"] is True
    assert settled["transaction"] == TX_HASH
    assert settled["network"] == NETWORK
    assert settled["payer"] == PAYER

    # The facilitator was asked to move exactly the quoted amount to the creator.
    requirements = fac.verify_bodies[0]["paymentRequirements"]
    assert requirements["payTo"] == CREATOR_WALLET
    assert requirements["amount"] == "10000"
    assert requirements["asset"] == DEFAULT_USDC_ADDRESS


def test_settle_failure_is_not_reported_as_success(db_path, monkeypatch):
    """verify ok, handler ran, settle failed -> the client must NOT see a 200.

    Observed middleware behaviour, asserted rather than wrapped: it discards
    the handler's 200 and answers 402 with a `success: false` PAYMENT-RESPONSE.
    That is the behaviour we want, because the creator was NOT paid — billing a
    caller (or, worse, letting them keep a result) for an unsettled payment is
    exactly the failure this gate exists to prevent.
    """
    _insert_asset(db_path)
    fac = FacilitatorStub(settle_success=False)
    c, fac = _gated_client(db_path, monkeypatch, facilitator=fac)

    quote = _accepts(c.post("/mcp/tools/call", json={"name": TOOL}))[0]
    resp = c.post("/mcp/tools/call", json={"name": TOOL},
                  headers={"PAYMENT-SIGNATURE": _payment_header(quote)})

    assert resp.status_code != 200
    assert resp.status_code == 402
    assert fac.calls == ["supported", "verify", "settle"]
    settled = json.loads(base64.b64decode(resp.headers["PAYMENT-RESPONSE"]))
    assert settled["success"] is False
    assert settled["transaction"] == ""
    # No tool result reaches a caller who did not actually pay.
    assert b"generate_greeting" not in resp.data


# ---------------------------------------------------------------------------
# 6. The money conversion, in isolation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dollars,expected", [
    ("0.01", 10_000),
    ("1", 1_000_000),
    (1, 1_000_000),
    (Decimal("40"), 40_000_000),
    ("0.005", 5_000),          # 6 decimals: exact, no rounding involved
    ("0", 0),
    ("0.000001", 1),           # one atomic unit
    (0.01, 10_000),            # float input goes through str() first
])
def test_usd_to_atomic_exact_values(dollars, expected):
    assert usd_to_atomic(dollars) == expected


@pytest.mark.parametrize("dollars,expected", [
    ("0.0000005", 1),          # half -> up
    ("0.0000004", 0),
    ("0.0000015", 2),          # half -> up (banker's rounding would give 2 too)
    ("0.0000025", 3),          # half -> up (banker's rounding would give 2)
])
def test_usd_to_atomic_rounds_half_up(dollars, expected):
    assert usd_to_atomic(dollars) == expected


@pytest.mark.parametrize("bad", ["-0.01", -1, "NaN", "Infinity", "-Infinity", "abc", None])
def test_usd_to_atomic_rejects_bad_amounts(bad):
    with pytest.raises(ValueError):
        usd_to_atomic(bad)


def test_usd_to_atomic_rejects_bools():
    with pytest.raises(TypeError):
        usd_to_atomic(True)


@pytest.mark.parametrize("price_amount,expected", [
    (1, 10_000),          # $0.01
    (100, 1_000_000),     # $1
    (2500, 25_000_000),   # $25 (demo SEO agent)
    (4000, 40_000_000),   # $40 (demo data analyst)
    (0, 0),
])
def test_asset_price_atomic_reads_price_amount_as_hundredths_of_a_dollar(price_amount, expected):
    assert asset_price_atomic({"price_amount": price_amount}) == expected


@pytest.mark.parametrize("bad", [None, "100", 1.5, True])
def test_asset_price_atomic_rejects_non_int_price(bad):
    with pytest.raises(ValueError):
        asset_price_atomic({"price_amount": bad})
