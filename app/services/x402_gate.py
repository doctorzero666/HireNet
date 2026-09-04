"""x402 resource-server gate for the SkillAsset invocation endpoint.

Stage 2 / WP-B. Puts the MCP servers' `POST /mcp/tools/call` route behind an
x402 v2 paywall so the CALLER pays the SkillAsset's creator in USDC on Base
Sepolia before the tool result is returned. HireNet is the *resource server*
here: it never signs, never holds a key, never touches a chain. Verification
and on-chain execution are done by a remote facilitator over HTTP.

────────────────────────────────────────────────────────────────────────────
WHAT IS VERIFIED BY TESTS (tests/test_x402_gate.py)
────────────────────────────────────────────────────────────────────────────
With the facilitator stubbed at the httpx boundary (`httpx.MockTransport`) and
a guard that fails the test if any real socket/HTTP egress is attempted:
  * gate OFF (default) -> the route behaves byte-for-byte as before;
  * gate ON, no payment header -> 402 whose `PAYMENT-REQUIRED` header carries
    exactly one accepted option: our network, our USDC address, the CREATOR's
    `wallet_address` as `payTo`, and the atomic price derived from the asset row;
  * asset with no `wallet_address` -> 503, facilitator never called;
  * undecodable payment header -> 402, facilitator never called;
  * facilitator says invalid -> 402, `/settle` never called;
  * facilitator says valid -> handler runs -> `/settle` -> 200 + `PAYMENT-RESPONSE`
    carrying the transaction hash, with the tool result body unchanged;
  * verify ok but settle fails -> 402 (NOT the handler's 200), `PAYMENT-RESPONSE`
    with `success: false`;
  * the dollars -> USDC-atomic conversion (exact numbers, rounding, rejections).

────────────────────────────────────────────────────────────────────────────
WHAT IS *NOT* VERIFIED — DO NOT READ THE GREEN SUITE AS PROOF OF THESE
────────────────────────────────────────────────────────────────────────────
  * No request has ever been made to a live facilitator (https://x402.org/facilitator)
    from this code. The stub's request/response shapes come from the package's
    own pydantic models, not from an observed live exchange.
  * No USDC has moved on Base Sepolia. Nothing here has been confirmed on-chain.
  * The EIP-3009 signature itself is never checked here — that is the
    facilitator's job, and our tests stub the facilitator's answer.
  * Whether the public facilitator accepts *our* PaymentRequirements (e.g. our
    `extra` EIP-712 domain fields) is unknown until a live run.
WP-F performs the live run and reports the tx hash. Until then, treat this
module as "shape-correct and control-flow-correct", not "settles money".

────────────────────────────────────────────────────────────────────────────
CONTINGENCY TAKEN: why we define our own `SchemeNetworkServer` here
────────────────────────────────────────────────────────────────────────────
Spec S2 says to use `x402.mechanisms.evm.exact.ExactEvmServerScheme`. Under
this repo's pinned `web3>=6.0,<7` that class is UNIMPORTABLE:

    >>> from x402.mechanisms.evm.exact import ExactEvmServerScheme
    ImportError: cannot import name 'ExtraDataToPOAMiddleware' from 'web3.middleware'
    ...
    ImportError: EVM signers require eth_account and web3. Install with: pip install x402[evm]

`x402/mechanisms/evm/__init__.py` eagerly imports `.signers`, which needs
web3 7. Importing ANY submodule under `x402.mechanisms.evm` therefore fails,
so the official server scheme cannot be reached without bumping web3 (which
would break the existing anvil/sepolia settlement providers).

The upstream *server-side* scheme is a pure-data object — it holds no keys and
does no crypto; it only (a) normalises a price into an `AssetAmount` and
(b) stamps the EIP-712 domain fields onto the requirements. `SchemeNetworkServer`
(`x402/interfaces.py`) is a structural `Protocol`, so we implement those two
methods locally in `_ExactEvmServerSchemeShim` below and register it.

Everything else stays official: `payment_middleware` (Flask WSGI), the 402
construction, header names/encoding, `HTTPFacilitatorClientSync` (/verify,
/settle, /supported over httpx) and all the pydantic schemas. We did NOT
hand-roll the facilitator HTTP calls.

────────────────────────────────────────────────────────────────────────────
PROTOCOL / WIRE FACTS (x402 v2, package 2.22.0)
────────────────────────────────────────────────────────────────────────────
  * request header : `PAYMENT-SIGNATURE`  (base64 JSON `PaymentPayload`)
  * 402 response   : body `{}`, options in the `PAYMENT-REQUIRED` header
                     (base64 JSON `PaymentRequired`, key `accepts`)
  * success header : `PAYMENT-RESPONSE`   (base64 JSON `SettleResponse`)
  * `x402Version`  : 2
The V1 names (`X-PAYMENT` / `X-PAYMENT-RESPONSE`, network `base-sepolia`) are
deprecated upstream and are NOT what this gate emits.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Callable, Iterable

from app.storage.skill_assets import list_skill_assets

# ---------------------------------------------------------------------------
# Constants / env defaults (Stage 2 spec S1)
# ---------------------------------------------------------------------------

# CAIP-2 id for Base Sepolia (chain id 84532). x402 v2 uses CAIP-2, not the v1
# plain string "base-sepolia".
DEFAULT_NETWORK = "eip155:84532"

# USDC on Base Sepolia. Cross-checked against Circle's docs, the x402 package's
# own `default_assets.py`, Google's AP2 sample constants, and a live
# `decimals()` / `symbol()` eth_call to https://sepolia.base.org (research B.1).
DEFAULT_USDC_ADDRESS = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
USDC_DECIMALS = 6

# EIP-712 domain of that USDC contract's `transferWithAuthorization`. The payer
# signs against these exact strings, so they travel in the 402's `extra`.
# NOTE: they are pinned to the DEFAULT_USDC_ADDRESS above. Overriding
# X402_USDC_ADDRESS with a different token WITHOUT changing these would make us
# advertise a domain the payer cannot sign correctly — see _asset_extra().
USDC_EIP712_NAME = "USDC"
USDC_EIP712_VERSION = "2"

# Free public facilitator; no API key needed for Base Sepolia (research A.4).
DEFAULT_FACILITATOR_URL = "https://x402.org/facilitator"

# The single route the demo MCP servers expose for invoking a tool.
DEFAULT_ROUTE_PATTERNS: tuple[str, ...] = ("POST /mcp/tools/call",)

# Flask config key set to True once the gate is installed (lets callers and
# tests assert the wiring without issuing a request).
GATE_INSTALLED_CONFIG_KEY = "HIRENET_X402_GATE_INSTALLED"

# Env flag. The gate is OFF unless this is exactly "1", so every existing demo,
# script and test keeps working unchanged.
GATE_ENV_FLAG = "HIRENET_X402_GATE"

# WSGI environ key carrying the resolved asset row from the pre-flight guard to
# the pay_to / price callbacks. Set once per request; the callbacks never re-read
# the request body (see _make_preflight for why that matters).
_ENVIRON_ASSET_KEY = "hirenet.x402.asset"


# ---------------------------------------------------------------------------
# Money: dollars -> USDC atomic units. THE conversion, defined once.
# ---------------------------------------------------------------------------

def usd_to_atomic(dollars: Decimal | int | str | float) -> int:
    """Convert a USD amount to USDC atomic units (6 decimals).

    Rule (single source of truth for the x402 boundary):
        atomic = round_half_up(dollars * 10**6)

    * Everything goes through `Decimal`; a `float` input is converted via
      `str()` first so 0.07 means 0.07 and not 0.070000000000000007.
    * ROUND_HALF_UP (not banker's rounding) because that is what a human
      reading "$0.0000005 -> 1 unit" expects; the choice only ever matters
      below a millionth of a dollar.
    * Rejects negative, NaN and Infinity. There is no such thing as a negative
      price on this path, and a silent 0 would let a caller pay nothing.

    Raises:
        TypeError: input is a bool (bools are ints in Python; never a price).
        ValueError: input is not a finite, non-negative number.
    """
    if isinstance(dollars, bool):
        raise TypeError(f"dollars must be a number, got bool: {dollars!r}")
    try:
        value = Decimal(str(dollars)) if isinstance(dollars, float) else Decimal(dollars)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"dollars is not a valid decimal amount: {dollars!r}") from exc

    if not value.is_finite():
        raise ValueError(f"dollars must be finite, got {dollars!r}")
    if value < 0:
        raise ValueError(f"dollars must be >= 0, got {dollars!r}")

    scaled = value * (10 ** USDC_DECIMALS)
    return int(scaled.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def asset_price_atomic(asset: dict) -> int:
    """USDC atomic units for one invocation of `asset`.

    `skill_assets.price_amount` is an integer in USD "基点" as this repo uses
    the word: hundredths of a dollar. The authority for that reading is
    `app/app.py` (`"price_per_hour": asset["price_amount"] / 100`) and
    `app/services/demo_bootstrap.py` ("$40 = 4000 bp"). So:

        dollars = price_amount / 100
        atomic  = usd_to_atomic(dollars)          # x 10**6

    e.g. price_amount=1 -> $0.01 -> 10_000 atomic; price_amount=100 -> $1 ->
    1_000_000 atomic; the demo data analyst's 4000 -> $40 -> 40_000_000 atomic.

    The division is done in `Decimal`, never in float.
    """
    price_amount = asset.get("price_amount")
    if isinstance(price_amount, bool) or not isinstance(price_amount, int):
        raise ValueError(f"price_amount must be an int, got {price_amount!r}")
    return usd_to_atomic(Decimal(price_amount) / Decimal(100))


# ---------------------------------------------------------------------------
# Asset resolution: tool name -> SkillAsset row -> creator wallet
# ---------------------------------------------------------------------------

def resolve_asset_for_tool(
    db_path: str,
    tool_endpoints: dict[str, str],
    tool_name: str | None,
) -> dict | None:
    """Return the `skill_assets` row that gets paid for invoking `tool_name`.

    `skill_assets` has no tool-name column: a SkillAsset is identified by the
    MCP server that serves it (`endpoint_url`). `tool_endpoints` is therefore
    the per-server map the MCP app hands us — {tool name: endpoint_url of the
    SkillAsset that owns it} — and we look the row up through the DAO. Today
    every tool on a server maps to that server's one endpoint, but the seam is
    per-tool so one process can host several assets later.

    Returns None when the tool is unknown to this gate, or when no registered
    SkillAsset claims that endpoint_url. Callers decide what that means; this
    function never invents a payee.

    AMBIGUITY, observed and NOT fixed here: nothing in the schema makes
    endpoint_url unique. `list_skill_assets` orders by `created_at DESC`, so if
    two rows claim the same endpoint (demo_bootstrap warns this happens after a
    DB upgrade re-registers an asset) the NEWEST row is paid. That is a
    deliberate, documented choice, not an accident — but the real fix is a
    uniqueness constraint or an explicit tool->asset table.
    """
    if not tool_name or tool_name not in tool_endpoints:
        return None
    endpoint_url = tool_endpoints[tool_name]
    for row in list_skill_assets(db_path):
        if row.get("endpoint_url") == endpoint_url:
            return row
    return None


def default_db_path() -> str:
    """Same DB the backend uses. Mirrors `create_app` in app/app.py.

    Duplicated (not imported) so the standalone MCP servers do not have to
    import the whole backend app just to find the database.
    """
    fallback = os.path.join(os.path.expanduser("~"), ".hirenet", "hirenet.db")
    return os.getenv("HIRENET_DB_PATH", fallback)


# ---------------------------------------------------------------------------
# The local server-side scheme (see the CONTINGENCY note at the top)
# ---------------------------------------------------------------------------

class _ExactEvmServerSchemeShim:
    """Stand-in for `x402.mechanisms.evm.exact.ExactEvmServerScheme`.

    Implements the `SchemeNetworkServer` structural Protocol from
    `x402/interfaces.py`. Deliberately does LESS than upstream:

    * `parse_price` only accepts an explicit `AssetAmount`. We always hand the
      middleware exact atomic units computed by `asset_price_atomic`, so the
      upstream Money-string path ("$0.01" -> decimals lookup) is dead weight
      here — and refusing it loudly is better than silently guessing decimals
      for an asset we did not configure.
    * `enhance_payment_requirements` only fills in the EIP-712 domain fields if
      the price did not already carry them. Upstream additionally looks up the
      asset in its bundled `default_assets.py` table and can convert decimal
      amounts; we do neither, because our amount is already atomic.

    `payment_flows` / `default_asset_transfer_method` mirror upstream exactly:
    USDC uses EIP-3009 `transferWithAuthorization`, and the "authorization"
    flow means verify-before-handler + settle-after-handler.
    """

    scheme = "exact"
    default_asset_transfer_method = "eip3009"
    payment_flows = {
        "eip3009": {"supported": ("authorization", "upfront"), "default": "authorization"},
    }

    def parse_price(self, price: Any, network: str) -> Any:
        from x402.schemas import AssetAmount

        if isinstance(price, AssetAmount):
            if not price.asset:
                raise ValueError(f"x402 gate: price is missing an asset address on {network}")
            return price
        raise TypeError(
            "x402 gate: price must be an AssetAmount in atomic units, got "
            f"{type(price).__name__}. Money strings are not supported here on purpose."
        )

    def enhance_payment_requirements(
        self,
        requirements: Any,
        supported_kind: Any,
        extensions: list[str],
    ) -> Any:
        # The payer signs EIP-712 over domain {name, version, chainId,
        # verifyingContract}; name/version must reach it in `extra`.
        if requirements.extra is None:
            requirements.extra = {}
        requirements.extra.setdefault("name", USDC_EIP712_NAME)
        requirements.extra.setdefault("version", USDC_EIP712_VERSION)
        return requirements


def _asset_extra() -> dict[str, str]:
    """EIP-712 domain fields advertised alongside the price.

    Correct only for DEFAULT_USDC_ADDRESS; `install_x402_gate` refuses to boot
    against any other token rather than advertise a domain we guessed.
    """
    return {"name": USDC_EIP712_NAME, "version": USDC_EIP712_VERSION}


# ---------------------------------------------------------------------------
# Pre-flight WSGI guard
# ---------------------------------------------------------------------------

def _json_wsgi_response(start_response: Callable[..., Any], status: str, body: dict) -> list[bytes]:
    payload = json.dumps(body).encode("utf-8")
    start_response(status, [("Content-Type", "application/json"),
                            ("Content-Length", str(len(payload)))])
    return [payload]


def _read_body_once(environ: dict) -> bytes:
    """Read the request body and put it back so the real handler still sees it.

    The x402 Flask middleware runs at WSGI level in its OWN request context,
    then calls the inner WSGI app with the SAME `environ`. `wsgi.input` is a
    single-pass stream: if we (or a dynamic pay_to callback) read it and do not
    restore it, the inner Flask request reads 0 bytes against a non-zero
    Content-Length and werkzeug raises ClientDisconnected -> a bare
    `400 Bad Request` instead of the tool result. Observed, then fixed here by
    replacing `wsgi.input` with a fresh BytesIO over the bytes we consumed.
    """
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        length = 0
    stream = environ.get("wsgi.input")
    raw = stream.read(length) if (stream is not None and length > 0) else b""
    environ["wsgi.input"] = io.BytesIO(raw)
    return raw


def _make_preflight(
    gated_wsgi: Callable[..., Any],
    ungated_wsgi: Callable[..., Any],
    *,
    db_path: str,
    tool_endpoints: dict[str, str],
    route_patterns: tuple[str, ...],
) -> Callable[..., Any]:
    """Wrap the x402-gated WSGI app with HireNet's payee pre-checks.

    Runs OUTSIDE the x402 middleware, so it can answer before any facilitator
    call happens. Three outcomes on a gated route:

      * tool unknown to this server -> hand the request to the UNGATED app so
        the tool handler returns its usual 400 "Unknown tool". We do not charge
        for a call that produces no result, and no result can be obtained this
        way, so it is not a paywall bypass.
      * no asset row / no wallet_address / non-USD price -> 503 JSON. There is
        no payee, so there is nothing honest to charge. We never substitute a
        platform address: that would silently redirect a creator's money.
      * otherwise -> stash the resolved row on the environ and continue into
        the x402 middleware, whose pay_to/price callbacks read it back.
    """

    def preflight(environ: dict, start_response: Callable[..., Any]):
        method = environ.get("REQUEST_METHOD", "")
        path = environ.get("PATH_INFO", "")
        if f"{method} {path}" not in route_patterns:
            return gated_wsgi(environ, start_response)

        raw = _read_body_once(environ)
        try:
            body = json.loads(raw or b"{}")
        except (ValueError, TypeError):
            body = {}
        tool_name = body.get("name") if isinstance(body, dict) else None

        if not tool_name or tool_name not in tool_endpoints:
            # Unknown tool: let the handler 400 for free.
            return ungated_wsgi(environ, start_response)

        try:
            asset = resolve_asset_for_tool(db_path, tool_endpoints, tool_name)
        except sqlite3.Error as exc:
            # Missing / unreadable DB is an operator problem, not a payment
            # problem. Refuse loudly rather than letting a traceback escape the
            # outermost WSGI callable.
            return _json_wsgi_response(
                start_response, "503 Service Unavailable",
                {"error": f"skill_assets lookup failed: {exc.__class__.__name__}"},
            )
        if asset is None:
            return _json_wsgi_response(
                start_response, "503 Service Unavailable",
                {"error": "no SkillAsset registered for this MCP endpoint"},
            )
        if not asset.get("wallet_address"):
            # The exact contract WP-C's payer and the demo rely on.
            return _json_wsgi_response(
                start_response, "503 Service Unavailable",
                {"error": "asset has no payout wallet"},
            )
        if asset.get("price_currency") != "USD":
            # We settle in USDC. Treating e.g. CNY as USDC 1:1 would misprice
            # the call; refuse rather than guess an FX rate.
            return _json_wsgi_response(
                start_response, "503 Service Unavailable",
                {"error": "asset price currency is not USD; the x402 gate settles in USDC"},
            )

        environ[_ENVIRON_ASSET_KEY] = asset
        return gated_wsgi(environ, start_response)

    return preflight


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def install_x402_gate(
    app,
    *,
    db_path: str | None = None,
    tool_endpoints: dict[str, str],
    network: str | None = None,
    usdc_address: str | None = None,
    facilitator_url: str | None = None,
    route_patterns: Iterable[str] | None = None,
    http_client: Any = None,
) -> bool:
    """Put `route_patterns` on `app` behind an x402 v2 paywall. Returns whether
    the gate was installed.

    No-ops (returns False) unless env `HIRENET_X402_GATE == "1"`. That default
    is what keeps every existing demo, script and test byte-for-byte unchanged.

    Args:
        app: the Flask app to wrap (its `wsgi_app` is replaced).
        db_path: SQLite path holding `skill_assets`; defaults to the backend's.
        tool_endpoints: {tool name: endpoint_url of the SkillAsset that owns it}.
            The ONLY place a tool is mapped to a payee. No addresses here.
        network / usdc_address / facilitator_url: default from env
            `X402_NETWORK` / `X402_USDC_ADDRESS` / `X402_FACILITATOR_URL`,
            then from the Base Sepolia constants above.
        route_patterns: "METHOD /path" strings; must match what the x402
            middleware is given (it does its own glob match on the same keys).
        http_client: TEST SEAM ONLY — an `httpx.Client` handed to the
            facilitator client so tests can serve /supported, /verify and
            /settle from an `httpx.MockTransport` without any network. Leave
            None in production; the SDK then creates its own client.

    Nothing here holds or reads a private key, and no PAYEE address is
    hardcoded: `payTo` is read from `skill_assets.wallet_address` per request.
    (The one hardcoded address is the USDC *token* contract, which is public.)
    """
    if os.getenv(GATE_ENV_FLAG) != "1":
        app.config[GATE_INSTALLED_CONFIG_KEY] = False
        return False

    # Imported lazily: `x402` is only needed when the gate is on, and the
    # standalone `python app/mcp_servers/*.py` entrypoints should not pay the
    # import cost (nor fail) when it is off.
    from x402.http.facilitator_client import FacilitatorConfig, HTTPFacilitatorClientSync
    from x402.http.middleware.flask import payment_middleware
    from x402.http.types import PaymentOption, RouteConfig
    from x402.schemas import AssetAmount
    from x402.server import x402ResourceServerSync

    db_path = db_path or default_db_path()
    network = network or os.getenv("X402_NETWORK", DEFAULT_NETWORK)
    usdc_address = usdc_address or os.getenv("X402_USDC_ADDRESS", DEFAULT_USDC_ADDRESS)
    facilitator_url = facilitator_url or os.getenv("X402_FACILITATOR_URL", DEFAULT_FACILITATOR_URL)
    patterns = tuple(route_patterns) if route_patterns else DEFAULT_ROUTE_PATTERNS

    if usdc_address.lower() != DEFAULT_USDC_ADDRESS.lower():
        # We advertise USDC's EIP-712 domain (name="USDC", version="2") in the
        # 402. For any other token that domain is wrong, the payer's signature
        # would not verify, and we would be quoting a price in a token whose
        # decimals we never read. Fail at boot instead of at settle time.
        raise ValueError(
            f"x402 gate: X402_USDC_ADDRESS={usdc_address!r} is not the Base Sepolia "
            f"USDC contract ({DEFAULT_USDC_ADDRESS}). Supporting another token needs "
            "its own EIP-712 domain name/version and decimals; unsupported here."
        )

    facilitator = HTTPFacilitatorClientSync(
        FacilitatorConfig(url=facilitator_url, http_client=http_client)
    )
    server = x402ResourceServerSync(facilitator)
    server.register(network, _ExactEvmServerSchemeShim())

    def _asset_from_request() -> dict:
        """The row the pre-flight guard already resolved for THIS request.

        Reading it back off the environ (instead of re-parsing the body here)
        is deliberate: the body stream may only be read once, and the guard has
        already checked wallet/currency, so these callbacks cannot fail.
        """
        from flask import request

        asset = request.environ.get(_ENVIRON_ASSET_KEY)
        if asset is None:  # pragma: no cover - the guard always sets it
            raise RuntimeError("x402 gate: no SkillAsset resolved for this request")
        return asset

    def dynamic_pay_to(ctx) -> str:
        """`payTo` = the creator's own wallet, per request. Never a fallback."""
        return _asset_from_request()["wallet_address"]

    def dynamic_price(ctx):
        """Price in USDC atomic units derived from the asset's own price row."""
        asset = _asset_from_request()
        return AssetAmount(
            amount=str(asset_price_atomic(asset)),
            asset=usdc_address,
            extra=_asset_extra(),
        )

    routes = {
        pattern: RouteConfig(
            accepts=[
                PaymentOption(
                    scheme="exact",
                    pay_to=dynamic_pay_to,
                    price=dynamic_price,
                    network=network,
                )
            ],
            mime_type="application/json",
            description="Invoke a HireNet SkillAsset (MCP tool call)",
        )
        for pattern in patterns
    }

    ungated_wsgi = app.wsgi_app          # captured BEFORE the middleware wraps it
    payment_middleware(app, routes=routes, server=server)
    app.wsgi_app = _make_preflight(
        app.wsgi_app,
        ungated_wsgi,
        db_path=db_path,
        tool_endpoints=dict(tool_endpoints),
        route_patterns=patterns,
    )
    app.config[GATE_INSTALLED_CONFIG_KEY] = True
    return True
