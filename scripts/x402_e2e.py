#!/usr/bin/env python
"""One real x402 payment on Base Sepolia, end to end (Stage 2 / WP-F, spec S10).

    python scripts/x402_e2e.py --mode direct --dry-run     # quote only, signs nothing
    python scripts/x402_e2e.py --mode direct               # ONE real 0.01 USDC payment
    python scripts/x402_e2e.py --mode pact                 # the same, through /api/pact/*

THIS SCRIPT SPENDS REAL (TESTNET) MONEY. Each non-dry run signs exactly one
EIP-3009 authorization for the quoted amount and hands it to the live
facilitator, which broadcasts a USDC transfer on Base Sepolia. `--dry-run`
does everything up to and including printing the quote and stops before
`payer_address` / `build_authorization` / `sign_authorization` are ever
reached.

────────────────────────────────────────────────────────────────────────────
WHAT IT BUILDS
────────────────────────────────────────────────────────────────────────────
  * a fresh temp SQLite DB (deleted on exit unless --keep-db) holding exactly
    ONE demo SkillAsset: `price_amount=1` (= $0.01 = 10_000 atomic USDC),
    `price_currency=USD`, `wallet_address=--payee`, `endpoint_url` = the
    local server below;
  * the REAL demo MCP server (`app/mcp_servers/customer_service.py`) with the
    REAL gate installed through its own `_install_x402_gate` (env
    `HIRENET_X402_GATE=1`), served by werkzeug on 127.0.0.1:<free port> in a
    background thread — so the payment crosses a real socket, not a test
    client;
  * `--mode pact`: additionally the REAL backend app with
    `HIRENET_SETTLEMENT_PROVIDER=x402`, driven through its Flask test client
    (create → approve → settle → royalty status poll).

Nothing is stubbed. The facilitator is `https://x402.org/facilitator` and the
RPC is `https://sepolia.base.org` unless the env says otherwise.

────────────────────────────────────────────────────────────────────────────
REFUSALS (all BEFORE anything is signed)
────────────────────────────────────────────────────────────────────────────
  * no payee (`--payee` / `X402_E2E_PAYEE`)          -> refuse
  * no `X402_PAYER_PRIVATE_KEY`                      -> refuse
  * payer USDC balance < the quoted price            -> refuse
  * the quote exceeds `--max-usdc`                   -> refuse
  * the quote's network / asset / payTo is not what we seeded -> refuse
The private key is read from the environment by `mcp_client`; this script
never prints it, never writes it and never puts it in an error message.

Exit code 0 means the payment reached SETTLED (confirmed on-chain by
`X402SettlementProvider.check_status`), or that a `--dry-run` produced a valid
quote. Anything else is non-zero.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from app.services.x402_gate import (  # noqa: E402
    DEFAULT_FACILITATOR_URL,
    DEFAULT_NETWORK,
    DEFAULT_USDC_ADDRESS,
    GATE_INSTALLED_CONFIG_KEY,
    USDC_DECIMALS,
    asset_price_atomic,
)
from app.services.x402_settlement import DEFAULT_RPC_URL  # noqa: E402

PAYEE_ENV = "X402_E2E_PAYEE"
KEY_ENV = "X402_PAYER_PRIVATE_KEY"

# The demo asset. price_amount is in cents: 1 -> $0.01 -> 10_000 atomic USDC.
DEMO_PRICE_AMOUNT = 1
DEMO_CREATOR_ID = "x402_e2e_creator"
DEMO_ASSET_NAME = "客服话术生成器 (x402 e2e)"
# "客服" is what routes pick_tool_for_task to generate_greeting on the pact
# rail; the direct rail names the tool explicitly.
DEMO_TOOL = "generate_greeting"

POLL_TIMEOUT_SECONDS = 180
POLL_INTERVAL_SECONDS = 5

# The route's own MCP timeout is 5s (app/services/mcp_client.py). A live
# facilitator round trip is verify + broadcast + (often) wait-for-inclusion, so
# the pact rail gets a longer one injected through the documented MCP_CLIENT
# seam. --pact-timeout 0 turns the injection off and uses the shipped default.
DEFAULT_PACT_TIMEOUT_SECONDS = 120.0
DEFAULT_DIRECT_TIMEOUT_SECONDS = 120.0


class E2ERefusal(Exception):
    """A refusal that must stop the run before anything is signed."""


# ---------------------------------------------------------------------------
# Small pure helpers (unit-tested in tests/test_x402_scripts.py)
# ---------------------------------------------------------------------------

def stamp() -> str:
    """UTC timestamp for the transition log."""
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def say(*parts) -> None:
    print(*parts, flush=True)


def usdc(atomic: int | str) -> str:
    """Atomic USDC -> a human decimal string. Exact (Decimal, never float)."""
    return str(Decimal(int(atomic)) / (Decimal(10) ** USDC_DECIMALS))


def resolve_payee(explicit: str | None, environ: dict | None = None) -> str:
    """`--payee`, else `X402_E2E_PAYEE`, else refuse.

    There is deliberately NO default. A default payee would send someone
    else's money to whatever address happened to be baked in here.
    """
    environ = os.environ if environ is None else environ
    candidate = (explicit or environ.get(PAYEE_ENV) or "").strip()
    if not candidate:
        raise E2ERefusal(
            f"no payee: pass --payee 0x… or set {PAYEE_ENV}. This script will not "
            "invent one — payTo is where real USDC goes."
        )
    from web3 import Web3

    if not Web3.is_address(candidate):
        raise E2ERefusal(f"--payee is not a valid EVM address: {candidate!r}")
    return Web3.to_checksum_address(candidate)


def max_usdc_atomic(max_usdc: str | Decimal) -> int:
    """`--max-usdc` (a dollar figure) -> atomic units. Rejects junk and < 0."""
    try:
        value = Decimal(str(max_usdc))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise E2ERefusal(f"--max-usdc is not a number: {max_usdc!r}") from exc
    if not value.is_finite() or value < 0:
        raise E2ERefusal(f"--max-usdc must be a finite, non-negative number, got {max_usdc!r}")
    scaled = value * (Decimal(10) ** USDC_DECIMALS)
    if scaled != scaled.to_integral_value():
        raise E2ERefusal(
            f"--max-usdc={max_usdc} is finer than one atomic USDC unit (10^-6)"
        )
    return int(scaled)


def free_port() -> int:
    """An ephemeral localhost port the OS just handed us."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def seed_demo_asset(db_path: str, *, endpoint_url: str, payee: str,
                    price_amount: int = DEMO_PRICE_AMOUNT) -> str:
    """Insert THE one SkillAsset this run pays. Returns its id.

    `wallet_address` is the payee and nothing else resolves it: the gate reads
    `payTo` straight off this row, so whatever is seeded here is exactly where
    the USDC goes.
    """
    from app.storage.skill_assets import insert_skill_asset

    return insert_skill_asset(db_path, {
        "creator_id": DEMO_CREATOR_ID,
        "name": DEMO_ASSET_NAME,
        "description": "WP-F end-to-end x402 demo asset (temporary database)",
        "type": "agent",
        "endpoint_url": endpoint_url,
        "io_schema": {"input": {}, "output": {}},
        "price_amount": price_amount,
        "price_currency": "USD",
        "price_chain": None,
        "split_rule": {"creator": 7000, "platform": 2000, "tax": 1000},
        "content_hash": uuid.uuid4().hex,
        "wallet_address": payee,
    })


def quote_problems(option, *, network: str, asset: str, payee: str,
                   price_atomic: int) -> list[str]:
    """Everything about the 402 quote that is not what we seeded.

    Returned rather than raised so the caller can print them all at once; an
    empty list means the quote is exactly the one this run intends to pay.
    """
    problems = []
    if option.scheme != "exact":
        problems.append(f"scheme is {option.scheme!r}, expected 'exact'")
    if option.network != network:
        problems.append(f"network is {option.network!r}, expected {network!r}")
    if option.asset.lower() != asset.lower():
        problems.append(f"asset is {option.asset!r}, expected {asset!r}")
    if option.pay_to.lower() != payee.lower():
        problems.append(f"payTo is {option.pay_to!r}, expected the seeded payee {payee!r}")
    if str(option.amount) != str(price_atomic):
        problems.append(f"amount is {option.amount!r}, expected {price_atomic!r} atomic units")
    return problems


def ensure_affordable(usdc_atomic: int, price_atomic: int, address: str) -> None:
    """Refuse before signing when the wallet cannot cover the quote."""
    if usdc_atomic < price_atomic:
        raise E2ERefusal(
            f"payer {address} holds {usdc(usdc_atomic)} USDC but the quote is "
            f"{usdc(price_atomic)} USDC. Fund it at https://faucet.circle.com "
            "(network Base Sepolia, token USDC)."
        )


def ensure_within_cap(price_atomic: int, cap_atomic: int) -> None:
    """Refuse before signing when the quote is above `--max-usdc`."""
    if price_atomic > cap_atomic:
        raise E2ERefusal(
            f"quote of {usdc(price_atomic)} USDC exceeds --max-usdc="
            f"{usdc(cap_atomic)}; nothing was signed"
        )


# ---------------------------------------------------------------------------
# Chain reads (no keys, no writes)
# ---------------------------------------------------------------------------

def _erc20_abi() -> list:
    from scripts.x402_wallet import ERC20_READ_ABI

    return ERC20_READ_ABI


def make_w3(rpc_url: str):
    from web3 import Web3

    return Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))


def usdc_balance(w3, usdc_address: str, address: str) -> int:
    from web3 import Web3

    token = w3.eth.contract(
        address=Web3.to_checksum_address(usdc_address), abi=_erc20_abi()
    )
    return token.functions.balanceOf(Web3.to_checksum_address(address)).call()


def _to_bytes(value) -> bytes:
    """web3 6 hands log fields back as HexBytes OR as a 0x string; take both."""
    if isinstance(value, str):
        return bytes.fromhex(value[2:] if value.startswith("0x") else value)
    return bytes(value)


def transfer_logs(w3, usdc_address: str, tx_hash: str) -> dict:
    """Receipt status + the USDC Transfer logs it carries. Read-only.

    Uses the same topic0 constant the settlement provider verifies against, so
    "what the script printed" and "what check_status matched on" cannot drift.
    Decoding is done by hand rather than through a contract event ABI so this
    stays a pure read with no ABI-dependent behaviour.
    """
    from app.services.x402_settlement import ERC20_TRANSFER_TOPIC0

    receipt = w3.eth.get_transaction_receipt(tx_hash)
    out = []
    for log in receipt["logs"]:
        topics = [_to_bytes(t) for t in log["topics"]]
        if not topics or topics[0] != ERC20_TRANSFER_TOPIC0:
            continue
        if log["address"].lower() != usdc_address.lower():
            continue
        if len(topics) < 3:
            continue
        data = _to_bytes(log["data"])
        out.append({
            "from": "0x" + topics[1].hex()[-40:],
            "to": "0x" + topics[2].hex()[-40:],
            "value": int.from_bytes(data, "big") if data else 0,
        })
    return {"status": receipt["status"], "block": receipt["blockNumber"],
            "gas_used": receipt["gasUsed"], "transfers": out}


# ---------------------------------------------------------------------------
# The in-process gated MCP server
# ---------------------------------------------------------------------------

class GatedServer:
    """The real demo MCP server + real gate, on a real localhost socket."""

    def __init__(self, port: int, db_path: str):
        self.port = port
        self.db_path = db_path
        self.url = f"http://127.0.0.1:{port}"
        self._server = None
        self._thread = None

    def start(self) -> None:
        # Both env vars are read at IMPORT time by customer_service (its
        # ASSET_ENDPOINT_URL) and at install time by the gate (its db path), so
        # they must be set before the module is first imported.
        os.environ["HIRENET_X402_GATE"] = "1"
        os.environ["HIRENET_MCP_ENDPOINT_URL"] = self.url
        os.environ["HIRENET_DB_PATH"] = self.db_path

        from werkzeug.serving import make_server

        from app.mcp_servers.customer_service import ASSET_ENDPOINT_URL, create_mcp_app

        if ASSET_ENDPOINT_URL != self.url:
            raise E2ERefusal(
                "app.mcp_servers.customer_service was imported before this script "
                f"set HIRENET_MCP_ENDPOINT_URL (it points at {ASSET_ENDPOINT_URL!r}, "
                f"not {self.url!r}); the gate would resolve the wrong SkillAsset"
            )
        app = create_mcp_app()
        if app.config.get(GATE_INSTALLED_CONFIG_KEY) is not True:
            raise E2ERefusal(
                "the x402 gate did not install on the MCP server; refusing to run "
                "an 'end-to-end paid invocation' against an unpaywalled endpoint"
            )
        self._server = make_server("127.0.0.1", self.port, app, threaded=True)
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="x402-e2e-mcp", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False


# ---------------------------------------------------------------------------
# Shared prologue
# ---------------------------------------------------------------------------

class Setup:
    """Everything both modes need, after every refusal has passed."""

    def __init__(self, args):
        self.args = args
        self.network = os.getenv("X402_NETWORK", DEFAULT_NETWORK)
        self.usdc_address = os.getenv("X402_USDC_ADDRESS", DEFAULT_USDC_ADDRESS)
        self.facilitator = os.getenv("X402_FACILITATOR_URL", DEFAULT_FACILITATOR_URL)
        self.rpc_url = os.getenv("X402_RPC_URL", DEFAULT_RPC_URL)
        self.payee = resolve_payee(args.payee)
        self.cap_atomic = max_usdc_atomic(args.max_usdc)
        self.price_atomic = asset_price_atomic({"price_amount": DEMO_PRICE_AMOUNT})

        key = (os.getenv(KEY_ENV) or "").strip()
        if not key:
            raise E2ERefusal(
                f"{KEY_ENV} is not set. Put it in .env (untracked) — see "
                "scripts/x402_wallet.py new --write-env .env"
            )
        from app.services.x402_payer import payer_address

        # The address is public; the key it came from is never printed.
        self.payer = payer_address(key)

        self.db_path = None
        self.asset_id = None
        self.server = None
        self.backend = None

    def banner(self) -> None:
        say("=" * 74)
        say(f"x402 end-to-end — mode={self.args.mode}"
            f"{'  (DRY RUN: nothing will be signed)' if self.args.dry_run else ''}")
        say("=" * 74)
        say(f"network      : {self.network}")
        say(f"asset (USDC) : {self.usdc_address}")
        say(f"facilitator  : {self.facilitator}")
        say(f"rpc          : {self.rpc_url}")
        say(f"payer        : {self.payer}")
        say(f"payee        : {self.payee}")
        say(f"price        : {usdc(self.price_atomic)} USDC "
            f"({self.price_atomic} atomic, price_amount={DEMO_PRICE_AMOUNT} cents)")
        say(f"--max-usdc   : {usdc(self.cap_atomic)} USDC ({self.cap_atomic} atomic)")

    def check_balance(self) -> int:
        w3 = make_w3(self.rpc_url)
        balance = usdc_balance(w3, self.usdc_address, self.payer)
        say(f"payer USDC   : {usdc(balance)} ({balance} atomic)")
        ensure_within_cap(self.price_atomic, self.cap_atomic)
        ensure_affordable(balance, self.price_atomic, self.payer)
        return balance

    def build_world(self):
        """Temp DB + backend (schema) + seeded asset + the gated MCP server."""
        fd, self.db_path = tempfile.mkstemp(prefix="hirenet-x402-e2e-", suffix=".db")
        os.close(fd)
        port = free_port()
        url = f"http://127.0.0.1:{port}"
        os.environ["HIRENET_DB_PATH"] = self.db_path

        # create_app runs init_db, so the schema exists before anything reads it.
        # TESTING=True keeps the demo bootstrap out of this database: the only
        # asset with an endpoint_url must be the one we seed.
        #
        # The provider comes from the env exactly as it would in production —
        # `pact` needs x402 (nothing else may confirm an x402 run), `direct`
        # never touches the app's provider at all.
        from app.app import create_app

        os.environ["HIRENET_SETTLEMENT_PROVIDER"] = (
            "x402" if self.args.mode == "pact" else "mock"
        )
        self.backend = create_app(config={
            "TESTING": True,
            "DATABASE_PATH": self.db_path,
        })
        self.asset_id = seed_demo_asset(
            self.db_path, endpoint_url=url, payee=self.payee
        )
        say(f"database     : {self.db_path}")
        say(f"asset_id     : {self.asset_id}")
        self.server = GatedServer(port, self.db_path)
        self.server.start()
        say(f"MCP server   : {url}  (gate installed, tool {DEMO_TOOL!r})")
        return url

    def cleanup(self) -> None:
        if self.server is not None:
            self.server.stop()
        if self.db_path and not self.args.keep_db:
            try:
                os.unlink(self.db_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# The quote (an unpaid probe — signs nothing, costs nothing)
# ---------------------------------------------------------------------------

def fetch_quote(setup: Setup, endpoint_url: str):
    """POST once WITHOUT a payment header and decode the 402 we get back."""
    import requests

    from app.services.x402_payer import parse_payment_required, select_option

    target = endpoint_url.rstrip("/") + "/mcp/tools/call"
    resp = requests.post(
        target,
        json={"name": DEMO_TOOL, "arguments": {"task_id": "quote-probe", "limit": 1}},
        timeout=30,
    )
    say("")
    say(f"[{stamp()}] unpaid probe -> HTTP {resp.status_code}")
    if resp.status_code != 402:
        raise E2ERefusal(
            f"the gated endpoint answered HTTP {resp.status_code}, not 402: "
            f"{resp.text[:300]}"
        )
    required = parse_payment_required(resp)
    option = select_option(required, network=setup.network, asset=setup.usdc_address)
    say("402 quote (PAYMENT-REQUIRED, decoded):")
    say(json.dumps(json.loads(option.model_dump_json(by_alias=True)), indent=2,
                   ensure_ascii=False))
    problems = quote_problems(
        option, network=setup.network, asset=setup.usdc_address,
        payee=setup.payee, price_atomic=setup.price_atomic,
    )
    if problems:
        raise E2ERefusal("the 402 quote is not the one we seeded:\n  - "
                         + "\n  - ".join(problems))
    say("quote matches the seeded asset: network, asset, payTo and amount all as expected.")
    ensure_within_cap(int(option.amount), setup.cap_atomic)
    return option


# ---------------------------------------------------------------------------
# On-chain confirmation
# ---------------------------------------------------------------------------

def poll_check_status(setup: Setup, tx_hash: str, *, payee: str,
                      amount_atomic: int) -> bool:
    """Poll X402SettlementProvider.check_status until it leaves SETTLING.

    The expectation is injected explicitly (`expected_lookup`) rather than read
    off an agent_runs row, because the direct mode never writes one. It is the
    same tuple the recorder would have stored: (payee, atomic amount).
    """
    from app.services.settlement import SettlementStatus
    from app.services.x402_settlement import X402SettlementProvider

    provider = X402SettlementProvider(
        rpc_url=setup.rpc_url,
        usdc_address=setup.usdc_address,
        network=setup.network,
        expected_lookup=lambda _h: (payee, amount_atomic),
    )
    deadline = time.time() + POLL_TIMEOUT_SECONDS
    last = None
    while time.time() < deadline:
        status = provider.check_status(tx_hash)
        if status != last:
            say(f"[{stamp()}] check_status -> {status.value}")
            last = status
        if status == SettlementStatus.SETTLED:
            return True
        if status == SettlementStatus.FAILED:
            return False
        time.sleep(POLL_INTERVAL_SECONDS)
    say(f"[{stamp()}] check_status timed out after {POLL_TIMEOUT_SECONDS}s "
        f"(last: {last.value if last else 'none'})")
    return False


def print_receipt(setup: Setup, tx_hash: str) -> None:
    """Independent verification: the receipt and its USDC Transfer logs."""
    w3 = make_w3(setup.rpc_url)
    try:
        info = transfer_logs(w3, setup.usdc_address, tx_hash)
    except Exception as exc:  # noqa: BLE001 - a read failure is not a payment failure
        say(f"receipt read failed: {exc.__class__.__name__}: {exc}")
        return
    say(f"receipt      : status={info['status']} block={info['block']} "
        f"gasUsed={info['gas_used']}")
    for transfer in info["transfers"]:
        say(f"  USDC Transfer  from={transfer['from']}  to={transfer['to']}  "
            f"value={transfer['value']} ({usdc(transfer['value'])} USDC)")
    if not info["transfers"]:
        say("  (no USDC Transfer log in this receipt)")


# ---------------------------------------------------------------------------
# Mode: direct
# ---------------------------------------------------------------------------

def run_direct(setup: Setup, endpoint_url: str) -> int:
    """Pay for one tool call straight through mcp_client. No pact, no ledger."""
    from app.services.mcp_client import call_mcp_tool
    from app.services.x402_settlement import explorer_url

    say("")
    say(f"[{stamp()}] calling the gated tool with the payer key set — "
        "this signs ONE authorization")
    started = time.time()
    result = call_mcp_tool(
        endpoint_url,
        DEMO_TOOL,
        {"task_id": "x402-e2e-direct", "limit": 3},
        timeout=setup.args.direct_timeout,
        max_amount=setup.cap_atomic,
    )
    elapsed = time.time() - started
    say(f"[{stamp()}] call_mcp_tool returned in {elapsed:.1f}s with "
        f"status={result.get('status')!r}")
    payment = result.get("payment") or {}
    say(json.dumps(
        {k: v for k, v in result.items() if k != "preview"},
        indent=2, ensure_ascii=False,
    ))

    if result.get("status") == "unknown":
        say("")
        say("OUTCOME UNKNOWN: an authorization was signed and transmitted and the "
            "server never said what became of it. DO NOT re-run: that would sign a "
            "second authorization. Reconcile the nonce above on-chain first.")
        return 3
    if payment.get("settle_success") is not True:
        say("")
        say(f"PAYMENT DID NOT SETTLE: {result.get('error')}")
        return 4

    tx_hash = payment["tx_hash"]
    say("")
    say(f"tx_hash      : {tx_hash}")
    say(f"network      : {payment.get('network')}")
    say(f"payer        : {payment.get('payer')}")
    say(f"payee        : {payment.get('payee')}")
    say(f"amount       : {payment.get('amount_atomic')} atomic "
        f"({usdc(payment.get('amount_atomic'))} USDC)")
    say(f"explorer     : {explorer_url(tx_hash)}")
    say("")

    settled = poll_check_status(
        setup, tx_hash, payee=payment["payee"],
        amount_atomic=int(payment["amount_atomic"]),
    )
    print_receipt(setup, tx_hash)
    if not settled:
        say("")
        say("check_status never reached SETTLED.")
        return 5
    say("")
    say("SETTLED — the USDC transfer is confirmed on Base Sepolia.")
    return 0


# ---------------------------------------------------------------------------
# Mode: pact
# ---------------------------------------------------------------------------

def _rows(db_path: str, sql: str, params: tuple = ()) -> list[dict]:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def run_pact(setup: Setup, endpoint_url: str) -> int:
    """The whole product path: create -> approve -> settle -> royalty status."""
    backend = setup.backend
    provider = backend.config["SETTLEMENT_PROVIDER"]
    provider_name = getattr(provider, "name", provider.__class__.__name__)
    if provider_name != "x402":
        raise E2ERefusal(
            f"the backend resolved settlement provider {provider_name!r}; the pact "
            "rail only pays at invocation time under 'x402'"
        )
    say(f"provider     : {provider_name}")

    if setup.args.pact_timeout > 0:
        # The ONLY deviation from the shipped path: mcp_client's default
        # timeout is 5s, which a live facilitator round trip can exceed — and a
        # timeout on the PAID retry is PaymentOutcomeUnknown, i.e. money in
        # limbo. Injected through the documented MCP_CLIENT seam; everything
        # else (payer, gate, facilitator, recorder) is the real thing.
        from app.services.mcp_client import call_mcp_tool

        def _client(endpoint, tool_name, arguments=None, **kwargs):
            kwargs.setdefault("timeout", setup.args.pact_timeout)
            return call_mcp_tool(endpoint, tool_name, arguments, **kwargs)

        backend.config["MCP_CLIENT"] = _client
        say(f"mcp timeout  : {setup.args.pact_timeout}s (injected; shipped default is 5s)")
    else:
        say("mcp timeout  : shipped default (5s) — no MCP_CLIENT injection")

    client = backend.test_client()
    task_id = f"x402-e2e-pact-{uuid.uuid4().hex[:8]}"

    say("")
    say(f"[{stamp()}] POST /api/pact/create")
    created = client.post("/api/pact/create", json={
        "task_id": task_id,
        "agent_name": "客服话术生成器",
        "asset_id": setup.asset_id,
        "amount": 0.01,
        "amount_cap": 0.01,
        "currency": "USD",
    })
    if created.status_code != 201:
        say(f"create failed: HTTP {created.status_code} {created.get_json()}")
        return 6
    pact = created.get_json()
    pact_id = pact["pact_id"]
    say(json.dumps(pact, indent=2, ensure_ascii=False))

    say("")
    say(f"[{stamp()}] POST /api/pact/approve/{pact_id}")
    approved = client.post(f"/api/pact/approve/{pact_id}")
    if approved.status_code != 200:
        say(f"approve failed: HTTP {approved.status_code} {approved.get_json()}")
        return 6

    say("")
    say(f"[{stamp()}] POST /api/pact/settle/{pact_id} — this signs ONE authorization")
    started = time.time()
    settled = client.post(f"/api/pact/settle/{pact_id}")
    say(f"[{stamp()}] settle returned HTTP {settled.status_code} in "
        f"{time.time() - started:.1f}s")
    body = settled.get_json()
    say(json.dumps(body, indent=2, ensure_ascii=False))
    if settled.status_code != 200:
        say("")
        say("SETTLE FAILED. If the pact is still 'settling' an authorization may "
            "have been transmitted — reconcile before re-running.")
        return 7

    tx_hash = body.get("tx_hash")
    say("")
    say(f"tx_hash        : {tx_hash}")
    say(f"explorer_url   : {body.get('explorer_url')}")
    say(f"settled_amount : {body.get('settled_amount')}")
    run_id = body.get("run_id")

    say("")
    say("agent_runs:")
    for row in _rows(setup.db_path, "SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)):
        say(json.dumps(row, indent=2, ensure_ascii=False, default=str))
    say("royalty_ledger:")
    for row in _rows(setup.db_path, "SELECT * FROM royalty_ledger WHERE run_id = ?", (run_id,)):
        say(json.dumps(row, indent=2, ensure_ascii=False, default=str))

    say("")
    say(f"[{stamp()}] polling GET /api/royalty/status/{run_id} until settled")
    deadline = time.time() + POLL_TIMEOUT_SECONDS
    last = None
    status_body = None
    while time.time() < deadline:
        resp = client.get(f"/api/royalty/status/{run_id}")
        status_body = resp.get_json()
        state = status_body.get("settlement_status")
        if state != last:
            say(f"[{stamp()}] settlement_status -> {state}")
            last = state
        if state in ("settled", "failed"):
            break
        time.sleep(POLL_INTERVAL_SECONDS)

    say(json.dumps(status_body, indent=2, ensure_ascii=False))
    say("")
    say("royalty_ledger after confirmation:")
    for row in _rows(setup.db_path, "SELECT * FROM royalty_ledger WHERE run_id = ?", (run_id,)):
        say(json.dumps(row, indent=2, ensure_ascii=False, default=str))

    if tx_hash:
        print_receipt(setup, tx_hash)
    if last != "settled":
        say("")
        say(f"the run did not reach 'settled' (last: {last!r})")
        return 5
    say("")
    say("SETTLED — the pact, the run and the creator's royalty row are all "
        "confirmed against Base Sepolia.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="x402_e2e.py",
        description="Run one real x402 payment on Base Sepolia, end to end.",
    )
    parser.add_argument("--mode", choices=("direct", "pact"), default="direct",
                        help="direct: mcp_client only. pact: the /api/pact/* flow.")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the 402 quote and stop; signs nothing")
    parser.add_argument("--max-usdc", default="0.01",
                        help="per-payment ceiling in USDC (default 0.01)")
    parser.add_argument("--payee", default=None,
                        help=f"payTo address; defaults to ${PAYEE_ENV}")
    parser.add_argument("--keep-db", action="store_true",
                        help="do not delete the temp SQLite database on exit")
    parser.add_argument("--pact-timeout", type=float,
                        default=DEFAULT_PACT_TIMEOUT_SECONDS,
                        help="pact mode: MCP timeout in seconds; 0 = shipped 5s default")
    parser.add_argument("--direct-timeout", type=float,
                        default=DEFAULT_DIRECT_TIMEOUT_SECONDS,
                        help="direct mode: MCP timeout in seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from dotenv import load_dotenv

    load_dotenv(os.path.join(_REPO_ROOT, ".env"))

    try:
        setup = Setup(args)
    except E2ERefusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    setup.banner()
    try:
        setup.check_balance()
        endpoint_url = setup.build_world()
        fetch_quote(setup, endpoint_url)
        if args.dry_run:
            say("")
            say("DRY RUN complete: the quote is valid and nothing was signed, "
                "transmitted or spent.")
            return 0
        if args.mode == "direct":
            return run_direct(setup, endpoint_url)
        return run_pact(setup, endpoint_url)
    except E2ERefusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    finally:
        setup.cleanup()


if __name__ == "__main__":  # pragma: no cover - exercised by the live run
    raise SystemExit(main())
