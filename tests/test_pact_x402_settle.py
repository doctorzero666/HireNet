"""Stage 2 / WP-E: /api/pact/settle when the settlement provider is x402.

Two rails, both driven through the real route:

  * provider = x402 — settle PAYS for the invocation and records the run
    afterwards. The REAL WP-B gate on the REAL demo MCP server, the REAL WP-C
    payer and the REAL WP-D pre-settled ledger path all run in process. Only
    the facilitator is stubbed (`tests/test_x402_gate.FacilitatorStub` behind an
    `httpx.MockTransport`), with `requests` routed into the gated Flask app by
    `tests/test_x402_payer.FlaskRequestsAdapter`. A handful of edge cases that
    a stubbed facilitator cannot produce (a payment that is not a whole number
    of cents; an endpoint that never asks to be paid) use an injected
    `MCP_CLIENT` instead — those are labelled where they appear.
  * provider = mock — the legacy post-hoc order, asserted directly: the
    agent_run row already exists when the MCP client is called, and the
    response carries none of the new keys.

`no_real_network` (autouse) fails the test if anything opens a socket, uses a
real httpx transport, or sends through a real requests adapter.

WHAT THESE TESTS DO NOT ESTABLISH: that a live facilitator accepts our payload,
that any USDC moved, or that a transaction exists on Base Sepolia. No
facilitator and no RPC endpoint is contacted anywhere in this file.
"""
import os
import socket
import sqlite3
import tempfile
import uuid
from contextlib import closing

import httpx
import pytest
import requests

from app.app import create_app
from app.mcp_servers.customer_service import create_mcp_app
from app.services.agent_run_recording import (
    USDC_ATOMIC_PER_CENT,
    X402_FEE_RECEIVABLE_METHOD,
    X402_METHOD,
)
from app.services.mcp_client import call_mcp_tool
from app.services.mock_settlement import MockSettlementProvider
from app.services.x402_gate import DEFAULT_USDC_ADDRESS, install_x402_gate
from app.services.x402_payer import MAX_AMOUNT_ENV, PAYER_KEY_ENV
from app.services.x402_settlement import X402SettlementProvider
from app.storage.agent_runs import get_agent_run
from app.storage.royalty_ledger import list_royalties_by_run
from app.storage.skill_assets import insert_skill_asset
from tests.test_x402_gate import (  # WP-B stubs, reused verbatim
    CREATOR_WALLET,
    NETWORK,
    PAYER,
    TOOL,
    TX_HASH,
    FacilitatorStub,
)
from tests.test_x402_payer import (  # WP-C in-process transport, reused verbatim
    TEST_PRIVATE_KEY,
    FlaskRequestsAdapter,
)

# The endpoint_url the SkillAsset registers. It is both what the pact invokes
# and what the gate resolves the payee from, so one row serves both sides.
MCP_ENDPOINT = "http://mcp.test"

TASK_ID = "task-x402-settle-1"
# "客服" routes pick_tool_for_task to generate_greeting — the tool the gate
# is installed for below.
AGENT_NAME = "客服话术生成器"


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """Fail loudly if a test would touch the network."""
    def _boom(*args, **kwargs):
        raise AssertionError(
            "WP-E settle tests must not make real network calls; the MCP "
            "server and the facilitator are both stubbed in-process."
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _boom)
    monkeypatch.setattr(socket.socket, "connect", _boom)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _boom)


@pytest.fixture(autouse=True)
def clean_x402_env(monkeypatch):
    """Never inherit the operator's key, cap or contract override."""
    monkeypatch.delenv(PAYER_KEY_ENV, raising=False)
    monkeypatch.delenv(MAX_AMOUNT_ENV, raising=False)
    monkeypatch.delenv("X402_USDC_ADDRESS", raising=False)
    monkeypatch.delenv("X402_EXPLORER_TX_URL", raising=False)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

class Harness:
    """One backend app + (optionally) one gated MCP server over the same DB."""

    def __init__(self, client, db_path, asset_id, facilitator=None, probe=None):
        self.client = client
        self.db_path = db_path
        self.asset_id = asset_id
        self.facilitator = facilitator
        self.probe = probe

    def agent_run_count(self) -> int:
        with closing(sqlite3.connect(self.db_path)) as conn:
            return conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0]

    def royalty_row_count(self) -> int:
        with closing(sqlite3.connect(self.db_path)) as conn:
            return conn.execute("SELECT COUNT(*) FROM royalty_ledger").fetchone()[0]

    def pact(self, pact_id) -> dict:
        resp = self.client.get(f"/api/pact/status/{pact_id}")
        assert resp.status_code == 200, resp.get_json()
        return resp.get_json()

    def create_and_approve(self, *, amount=1.0, amount_cap=None, asset_id=None) -> str:
        payload = {
            "task_id": TASK_ID,
            "agent_name": AGENT_NAME,
            "asset_id": asset_id or self.asset_id,
            "amount": amount,
            "currency": "USD",
        }
        if amount_cap is not None:
            payload["amount_cap"] = amount_cap
        resp = self.client.post("/api/pact/create", json=payload)
        assert resp.status_code == 201, resp.get_json()
        pact_id = resp.get_json()["pact_id"]
        approve = self.client.post(f"/api/pact/approve/{pact_id}")
        assert approve.status_code == 200, approve.get_json()
        return pact_id

    def settle(self, pact_id):
        return self.client.post(f"/api/pact/settle/{pact_id}")


def _x402_provider() -> X402SettlementProvider:
    """A real provider. Its Web3 handle is lazy, so constructing it dials nothing."""
    return X402SettlementProvider(
        rpc_url="http://rpc.test",          # never used: check_status is not called here
        usdc_address=DEFAULT_USDC_ADDRESS,
        network=NETWORK,
    )


def _insert_asset(db_path, *, price_amount=1, wallet=CREATOR_WALLET,
                  endpoint_url=MCP_ENDPOINT, name="客服话术 Agent"):
    """One SkillAsset. price_amount is in cents: 1 -> $0.01 -> 10_000 atomic."""
    return insert_skill_asset(db_path, {
        "creator_id": "zhang_ai",
        "name": name,
        "description": "WP-E settle test asset",
        "type": "agent",
        "endpoint_url": endpoint_url,
        "io_schema": {"input": {}, "output": {}},
        "price_amount": price_amount,
        "price_currency": "USD",
        "price_chain": None,
        "split_rule": {"creator": 7000, "platform": 2000, "tax": 1000},
        "content_hash": uuid.uuid4().hex,
        "wallet_address": wallet,
    })


@pytest.fixture
def boot(monkeypatch):
    """Factory: build a backend (+ gated MCP server) over one temp DB."""
    paths = []

    def _boot(*, provider, price_amount=1, facilitator=None, mcp_client=None,
              gated=True, wallet=CREATOR_WALLET, endpoint_url=MCP_ENDPOINT,
              session_wrapper=None):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        paths.append(db_path)

        # Backend first: create_app runs init_db, so the schema exists before
        # the asset row and before the gate ever reads it.
        backend = create_app(config={
            "TESTING": True,
            "DATABASE_PATH": db_path,
            "SETTLEMENT_PROVIDER": provider,
        })
        asset_id = _insert_asset(
            db_path, price_amount=price_amount, wallet=wallet,
            endpoint_url=endpoint_url,
        )

        facilitator_stub = None
        if mcp_client is not None:
            backend.config["MCP_CLIENT"] = mcp_client
        elif gated:
            facilitator_stub = facilitator or FacilitatorStub()
            monkeypatch.delenv("HIRENET_X402_GATE", raising=False)
            mcp_app = create_mcp_app()
            monkeypatch.setenv("HIRENET_X402_GATE", "1")
            assert install_x402_gate(
                mcp_app,
                db_path=db_path,
                tool_endpoints={TOOL: endpoint_url},
                facilitator_url="https://facilitator.test",
                http_client=facilitator_stub.client(),
            ) is True

            session = requests.Session()
            session.mount(MCP_ENDPOINT, FlaskRequestsAdapter(mcp_app))
            # WP-R: lets a test damage the RESPONSE (e.g. drop the settlement
            # header) without touching the gate, the payer or the facilitator.
            if session_wrapper is not None:
                session = session_wrapper(session)

            # The REAL call_mcp_tool, with only its transport redirected into
            # the in-process MCP app. **kwargs forwards the WP-E `max_amount`.
            def _client(endpoint, tool_name, arguments=None, **kwargs):
                return call_mcp_tool(
                    endpoint, tool_name, arguments, session=session, **kwargs
                )

            backend.config["MCP_CLIENT"] = _client

        return Harness(
            backend.test_client(), db_path, asset_id, facilitator_stub,
            probe=mcp_client,
        )

    yield _boot
    for path in paths:
        os.unlink(path)


class _McpProbe:
    """Injected MCP client that records WHEN it was called and with what.

    `runs_at_call_time` is the number of agent_runs rows that existed at the
    moment the client was invoked — that single integer is what distinguishes
    the legacy order (row first, then invoke) from the x402 order (invoke, i.e.
    pay, then row).
    """

    def __init__(self, *, payment=None, status="ok"):
        # Filled in by the caller once `boot` has created the database.
        self.db_path = None
        self.payment = payment
        self.status = status
        self.calls = []
        self.kwargs = []
        self.runs_at_call_time = None

    def __call__(self, endpoint_url, tool_name, arguments=None, **kwargs):
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.runs_at_call_time = conn.execute(
                "SELECT COUNT(*) FROM agent_runs"
            ).fetchone()[0]
        self.calls.append((endpoint_url, tool_name, arguments))
        self.kwargs.append(dict(kwargs))
        return {
            "status": self.status,
            "tool": tool_name,
            "total": 1,
            "preview": ["probe"],
            "endpoint_url": endpoint_url,
            "payment": self.payment,
        }


def _payment(**overrides) -> dict:
    """The dict x402_payer.pay_and_retry returns after a settled payment."""
    payment = {
        "method": "x402",
        "tx_hash": TX_HASH,
        "network": NETWORK,
        "payer": PAYER,
        "payee": CREATOR_WALLET,
        "amount_atomic": "10000",       # $0.01, verbatim off the wire
        "asset": DEFAULT_USDC_ADDRESS,
        "settle_success": True,
    }
    payment.update(overrides)
    return payment


# ---------------------------------------------------------------------------
# 1. The happy path: pay, then record
# ---------------------------------------------------------------------------

def test_x402_settle_pays_for_the_invocation_and_returns_the_tx(boot, monkeypatch):
    monkeypatch.setenv(PAYER_KEY_ENV, TEST_PRIVATE_KEY)
    h = boot(provider=_x402_provider())

    pact_id = h.create_and_approve(amount=1.0)      # authorises up to $1.00
    resp = h.settle(pact_id)

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["status"] == "settled"
    assert body["tx_hash"] == TX_HASH
    assert body["explorer_url"] == f"https://sepolia.basescan.org/tx/{TX_HASH}"
    assert body["run_id"]
    assert body["royalty_splits"]
    # Paid the asset's price ($0.01), not the pact's ceiling ($1.00). `amount`
    # still says what the pact was created for.
    assert body["settled_amount"] == 0.01
    assert body["amount"] == 1.0
    # The tool actually ran behind the paywall.
    assert body["mcp_result"]["status"] == "ok"
    assert body["mcp_result"]["payment"]["tx_hash"] == TX_HASH
    # verify then settle, once each — nothing else was asked of the facilitator.
    assert h.facilitator.calls == ["supported", "verify", "settle"]


def test_x402_settle_writes_a_presettled_run(boot, monkeypatch):
    monkeypatch.setenv(PAYER_KEY_ENV, TEST_PRIVATE_KEY)
    h = boot(provider=_x402_provider())

    body = h.settle(h.create_and_approve()).get_json()
    run = get_agent_run(h.db_path, body["run_id"])

    assert run["settlement_status"] == "settling"   # paid; chain not yet checked
    assert run["settlement_method"] == X402_METHOD
    assert run["tx_hash"] == TX_HASH
    assert run["payment_method"] == "on_chain"
    # charge_amount comes from what was PAID, not from the pact's amount.
    assert run["charge_amount"] == 10_000 // USDC_ATOMIC_PER_CENT == 1
    assert run["settlement_meta"]["amount_atomic"] == 10_000


def test_x402_settle_splits_creator_settling_platform_receivable(boot, monkeypatch):
    monkeypatch.setenv(PAYER_KEY_ENV, TEST_PRIVATE_KEY)
    h = boot(provider=_x402_provider(), price_amount=100)   # $1.00 -> 1_000_000

    body = h.settle(h.create_and_approve(amount=1.0)).get_json()
    rows = {r["party"]: r for r in list_royalties_by_run(h.db_path, body["run_id"])}

    creator = rows["creator"]
    assert creator["status"] == "settling"
    assert creator["settlement_method"] == X402_METHOD
    assert creator["tx_hash"] == TX_HASH

    platform = rows["platform"]
    assert platform["status"] == "accrued"
    assert platform["settlement_method"] == X402_FEE_RECEIVABLE_METHOD
    assert platform["tx_hash"] is None
    assert "receivable from the creator" in platform["note"]

    assert body["settled_amount"] == 1.0


# ---------------------------------------------------------------------------
# 2. Refusals — nothing paid, nothing recorded, mandate still approved
# ---------------------------------------------------------------------------

def test_a_quote_above_the_mandate_cap_is_refused_before_signing(boot, monkeypatch):
    """$40 asset against a $0.02 mandate: 409, no signature, no rows."""
    monkeypatch.setenv(PAYER_KEY_ENV, TEST_PRIVATE_KEY)
    # Operator brake set high so the refusal can only come from the mandate.
    monkeypatch.setenv(MAX_AMOUNT_ENV, "100000000")
    h = boot(provider=_x402_provider(), price_amount=4000)   # $40.00

    pact_id = h.create_and_approve(amount=0.02, amount_cap=0.02)
    resp = h.settle(pact_id)

    assert resp.status_code == 409
    assert resp.get_json() == {"error": "amount exceeds cap"}
    assert h.pact(pact_id)["status"] == "approved"
    assert h.agent_run_count() == 0
    assert h.royalty_row_count() == 0
    # Never verified, never settled: the cap runs before anything is signed.
    assert h.facilitator.calls == ["supported"]


def test_the_operator_brake_still_applies_when_it_is_tighter(boot, monkeypatch):
    """A generous mandate cannot raise X402_MAX_AMOUNT_PER_PAYMENT."""
    monkeypatch.setenv(PAYER_KEY_ENV, TEST_PRIVATE_KEY)
    monkeypatch.setenv(MAX_AMOUNT_ENV, "20000")             # $0.02 brake
    h = boot(provider=_x402_provider(), price_amount=4000)   # $40.00 asset

    pact_id = h.create_and_approve(amount=40.0, amount_cap=40.0)
    resp = h.settle(pact_id)

    assert resp.status_code == 409
    assert resp.get_json() == {"error": "amount exceeds cap"}
    assert h.pact(pact_id)["status"] == "approved"
    assert h.agent_run_count() == 0
    assert h.facilitator.calls == ["supported"]


def test_a_failed_settlement_records_nothing_and_keeps_the_pact_approved(boot, monkeypatch):
    monkeypatch.setenv(PAYER_KEY_ENV, TEST_PRIVATE_KEY)
    h = boot(provider=_x402_provider(),
             facilitator=FacilitatorStub(settle_success=False))

    pact_id = h.create_and_approve()
    resp = h.settle(pact_id)

    assert resp.status_code == 502
    error = resp.get_json()["error"]
    assert "PaymentFailed" in error
    assert "settlement_failed" in error
    assert h.pact(pact_id)["status"] == "approved"
    assert h.pact(pact_id).get("tx_hash") is None
    assert h.agent_run_count() == 0
    assert h.royalty_row_count() == 0


def test_without_a_payer_key_settle_reports_the_configuration_problem(boot, monkeypatch):
    monkeypatch.delenv(PAYER_KEY_ENV, raising=False)
    h = boot(provider=_x402_provider())

    pact_id = h.create_and_approve()
    resp = h.settle(pact_id)

    assert resp.status_code == 502
    error = resp.get_json()["error"]
    assert "PaymentRequiredError" in error
    assert PAYER_KEY_ENV in error
    assert h.pact(pact_id)["status"] == "approved"
    assert h.agent_run_count() == 0
    # Nothing was signed, so the facilitator never got past /supported.
    assert h.facilitator.calls == ["supported"]


def test_an_asset_without_an_endpoint_cannot_settle_on_this_rail(boot, monkeypatch):
    """No endpoint to invoke means no way to pay; refused before the claim."""
    monkeypatch.setenv(PAYER_KEY_ENV, TEST_PRIVATE_KEY)
    h = boot(provider=_x402_provider(), gated=False)
    endpointless = _insert_asset(h.db_path, endpoint_url=None)

    pact_id = h.create_and_approve(asset_id=endpointless)
    resp = h.settle(pact_id)

    assert resp.status_code == 502
    assert "endpoint_url" in resp.get_json()["error"]
    assert h.pact(pact_id)["status"] == "approved"
    assert h.agent_run_count() == 0


def test_settle_is_still_single_shot(boot, monkeypatch):
    monkeypatch.setenv(PAYER_KEY_ENV, TEST_PRIVATE_KEY)
    h = boot(provider=_x402_provider())

    pact_id = h.create_and_approve()
    assert h.settle(pact_id).status_code == 200

    second = h.settle(pact_id)
    assert second.status_code == 400
    assert "must be approved" in second.get_json()["error"]
    # One payment, one run.
    assert h.agent_run_count() == 1
    assert h.facilitator.calls == ["supported", "verify", "settle"]


# ---------------------------------------------------------------------------
# 3. Order of operations + the guards a stubbed facilitator cannot produce
#    (injected MCP_CLIENT — see the module docstring)
# ---------------------------------------------------------------------------

def test_x402_invokes_before_any_ledger_write(boot, monkeypatch):
    """The invocation IS the payment, so it must precede the row."""
    probe = _McpProbe(payment=_payment())
    h = boot(provider=_x402_provider(), mcp_client=probe)
    probe.db_path = h.db_path

    pact_id = h.create_and_approve(amount=0.50)   # cap $0.50 -> 500_000 atomic
    resp = h.settle(pact_id)

    assert resp.status_code == 200, resp.get_json()
    assert probe.runs_at_call_time == 0           # nothing billed yet when we paid
    assert h.agent_run_count() == 1               # …and exactly one row after
    # The mandate's ceiling reached the payer, in USDC atomic units.
    assert probe.kwargs[0]["max_amount"] == 500_000
    assert h.pact(pact_id)["status"] == "settled"


def test_a_payment_that_is_not_whole_cents_is_not_recorded(boot, monkeypatch):
    """A gate/payer bug must not become a rounded royalty row."""
    probe = _McpProbe(payment=_payment(amount_atomic="10001"))
    h = boot(provider=_x402_provider(), mcp_client=probe)
    probe.db_path = h.db_path

    pact_id = h.create_and_approve()
    resp = h.settle(pact_id)

    assert resp.status_code == 500
    assert "whole number of cents" in resp.get_json()["error"]
    assert resp.get_json()["tx_hash"] == TX_HASH
    assert h.agent_run_count() == 0
    assert h.royalty_row_count() == 0
    # The creator WAS paid, so the pact must not fall back to `approved` —
    # a retry would sign a second authorization for the same mandate.
    stuck = h.pact(pact_id)
    assert stuck["status"] == "settling"
    assert stuck["tx_hash"] == TX_HASH


def test_an_endpoint_that_never_asks_for_payment_settles_nothing(boot, monkeypatch):
    """No 402 means no payment; we do not quietly fall back to an accrual."""
    probe = _McpProbe(payment=None)
    h = boot(provider=_x402_provider(), mcp_client=probe)
    probe.db_path = h.db_path

    pact_id = h.create_and_approve()
    resp = h.settle(pact_id)

    assert resp.status_code == 502
    assert "did not ask to be paid" in resp.get_json()["error"]
    assert h.pact(pact_id)["status"] == "approved"
    assert h.agent_run_count() == 0


# ---------------------------------------------------------------------------
# 4. The legacy rail is untouched
# ---------------------------------------------------------------------------

def test_mock_provider_keeps_the_legacy_order_and_shape(boot):
    """Row first, then invoke — and none of the WP-E keys appear."""
    probe = _McpProbe(payment=None)
    h = boot(provider=MockSettlementProvider(), mcp_client=probe)
    probe.db_path = h.db_path

    pact_id = h.create_and_approve()
    resp = h.settle(pact_id)

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["status"] == "settled"
    # The agent_run row was already committed when the MCP client ran.
    assert probe.runs_at_call_time == 1
    # …and the legacy call keeps its 3-argument shape.
    assert probe.calls[0] == (MCP_ENDPOINT, TOOL, {"task_id": TASK_ID})
    assert probe.kwargs == [{}]
    # charge_amount still comes from the pact's own amount (dollars -> cents).
    assert get_agent_run(h.db_path, body["run_id"])["charge_amount"] == 100
    # Additive keys are x402-only: the legacy body is unchanged.
    for key in ("tx_hash", "explorer_url", "settled_amount"):
        assert key not in body


# ---------------------------------------------------------------------------
# 6. Stage 2 / WP-R (review F2): a signed authorization with an unknown outcome
#    never resets the pact.
#
# The gate settles through the facilitator and only THEN writes the
# PAYMENT-RESPONSE header. Losing that header on the way back is the one
# failure where the creator may already have been paid and we cannot tell —
# and before WP-R it walked the pact back to `approved`, so a retry signed a
# second authorization with a fresh nonce against a payment that had settled.
# ---------------------------------------------------------------------------

class _LosesTheSettlementHeader:
    """A session that drops PAYMENT-RESPONSE from the gate's answer.

    The facilitator DID settle — `facilitator.calls` proves it — and the payer
    simply never learns. Produced without changing a line of the gate, the
    payer or the facilitator stub.
    """

    def __init__(self, inner):
        self.inner = inner

    def request(self, method, url, **kwargs):
        response = self.inner.request(method, url, **kwargs)
        response.headers.pop("PAYMENT-RESPONSE", None)
        return response


def _unknown_outcome_harness(boot, monkeypatch):
    monkeypatch.setenv(PAYER_KEY_ENV, TEST_PRIVATE_KEY)
    return boot(provider=_x402_provider(),
                session_wrapper=_LosesTheSettlementHeader)


def test_an_unknown_outcome_leaves_the_pact_settling_with_a_502(boot, monkeypatch):
    h = _unknown_outcome_harness(boot, monkeypatch)
    pact_id = h.create_and_approve(amount=1.0)

    resp = h.settle(pact_id)

    assert resp.status_code == 502
    assert resp.get_json() == {
        "error": "payment outcome unknown; manual reconciliation required",
        "pact_id": pact_id,
    }
    # The claim is what stops a second signature: NOT back to `approved`.
    assert h.pact(pact_id)["status"] == "settling"
    # The facilitator really did settle — that is the whole danger.
    assert h.facilitator.calls == ["supported", "verify", "settle"]


def test_the_unknown_outcome_is_written_down_for_reconciliation(boot, monkeypatch):
    h = _unknown_outcome_harness(boot, monkeypatch)
    pact_id = h.create_and_approve(amount=1.0)

    h.settle(pact_id)
    pact = h.pact(pact_id)

    pending = pact["payment_pending"]
    # The nonce is the token's replay key: it is what an operator looks up
    # on-chain to find out whether this authorization was redeemed.
    assert pending["nonce"].startswith("0x")
    assert len(pending["nonce"]) == 66
    assert pending["payee"] == CREATOR_WALLET
    assert pending["amount_atomic"] == "10000"
    assert "PAYMENT-RESPONSE" in pending["error"]
    assert "PaymentOutcomeUnknown" in pact["last_error"]
    # Nothing is claimed as settled: no run, no ledger rows, no tx hash.
    assert h.agent_run_count() == 0
    assert h.royalty_row_count() == 0
    assert pact.get("tx_hash") is None


def test_a_retry_after_an_unknown_outcome_cannot_sign_again(boot, monkeypatch):
    """The double-pay the review found. One authorization, and only one."""
    h = _unknown_outcome_harness(boot, monkeypatch)
    pact_id = h.create_and_approve(amount=1.0)

    assert h.settle(pact_id).status_code == 502
    second = h.settle(pact_id)

    assert second.status_code == 400
    assert "must be approved" in second.get_json()["error"]
    # One verify, one settle: the payer was never asked to sign a second time.
    assert h.facilitator.calls == ["supported", "verify", "settle"]
    assert h.agent_run_count() == 0


def test_a_pre_signing_refusal_still_returns_the_pact_to_approved(boot, monkeypatch):
    """The other side of the line: nothing was signed, so the mandate is free
    to be retried. Same 502, opposite pact state."""
    monkeypatch.delenv(PAYER_KEY_ENV, raising=False)
    h = boot(provider=_x402_provider())

    pact_id = h.create_and_approve()
    resp = h.settle(pact_id)

    assert resp.status_code == 502
    assert "PaymentRequiredError" in resp.get_json()["error"]
    assert h.pact(pact_id)["status"] == "approved"
    assert "payment_pending" not in h.pact(pact_id)
