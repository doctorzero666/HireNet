"""HTTP client for talking to an external MCP server during pact settlement.

Two responsibilities:
1. `pick_tool_for_task` — choose which canned tool fits a given task using
   keyword hints on task_id / agent_name / asset_name. Pure function; no I/O.
2. `call_mcp_tool` — POST to `{endpoint_url}/mcp/tools/call`, return a dict
   that pact_settle can stash on the pact object. Never raises — every
   failure (timeout, non-200, invalid JSON, missing endpoint) returns a
   structured `{"status": "error", ...}` so the caller doesn't need a
   try/except. This keeps the royalty path (which already ran) untouched.

Designed to be injectable: pact_settle reads
`current_app.config.get("MCP_CLIENT", call_mcp_tool)`, so tests pass a fake
without touching the network. Mirrors the SETTLEMENT_PROVIDER pattern in
app/services/mock_settlement.py. Note the two call shapes: the legacy settle
path calls the injected client with three positional arguments, while the WP-E
x402 path also passes `max_amount=` — a fake used on that path must accept it.

────────────────────────────────────────────────────────────────────────────
Stage 2 / WP-C: paying for the invocation (x402)
────────────────────────────────────────────────────────────────────────────
When the target SkillAsset sits behind the x402 gate (`x402_gate.py`) the
first POST comes back 402. Two modes, decided ONLY by whether the payer key is
configured:

  * `X402_PAYER_PRIVATE_KEY` set   -> the request goes through
    `x402_payer.pay_and_retry`, which signs one EIP-3009 authorization and
    retries once. On success the returned dict carries `payment` (tx hash,
    payee, atomic amount, …).
  * key not set                    -> unchanged behaviour, except a 402 is
    reported as a `PaymentRequiredError` instead of an opaque "HTTP 402". No
    silent fallback, no unpaid retry (spec S4).

Return shape is unchanged apart from ONE ADDITIVE KEY, `payment`, present on
every result and None whenever no payment happened. Callers checked:
`app/app.py` (pact settle, stashes the whole dict on `pact["mcp_result"]`),
`frontend/src/services/api.js` + `ExecutionPage.jsx` (pass the object through),
`tests/test_mcp_integration.py` (asserts individual keys, no dict equality).

`call_mcp_tool` still NEVER raises: on the legacy settle path `app/app.py`
calls it after the royalty rows are committed and relies on that; on the WP-E
x402 path it calls it BEFORE any ledger write and reads the folded error to
decide that nothing may be recorded. Payment failures are therefore folded into
the same `{"status": "error", ...}` dict, with the exception class name kept in
the message so "PaymentFailed" / "SpendCapExceeded" stay visible.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import requests

from app.services.x402_payer import (
    PAYER_KEY_ENV,
    PaymentOutcomeUnknown,
    PaymentRequiredError,
    X402PayerError,
    pay_and_retry,
)


# Phase 1 SSRF posture — read before relaxing or tightening.
#
# endpoint_url is user-supplied (AgentRegister has no real auth) and we POST
# to it from the server during pact_settle. That is a textbook SSRF surface.
# Defensive layers we DO apply here:
#   * scheme allow-list (http / https) — blocks file://, gopher://, ftp://
#     and the protocol-confusion variants that smuggle in cloud-metadata
#     style attacks.
#   * allow_redirects=False — blocks the "302 → http://169.254.169.254/..."
#     redirect-based SSRF where a "safe" host hands the client to an
#     internal target.
#   * pact_settle calls this AFTER record_agent_run commits, so a bad
#     endpoint cannot influence billing / royalty rows.
#
# Defensive layers we deliberately DO NOT apply (Phase 1 demo posture):
#   * Loopback / RFC1918 / link-local IP blocking. The whole demo loop runs
#     against http://localhost:5002; blocking private hosts would break it.
#   * DNS-rebinding pin (resolve → check → pass IP). Same reason.
#   * Operator-configured host allowlist.
# TODO(Phase 2): gate this behind MCP_BLOCK_PRIVATE_HOSTS and add an
# MCP_ALLOWED_HOSTS allowlist when real auth lands. Once anyone-can-register
# goes away, the attack surface here changes shape.
_ALLOWED_SCHEMES = {"http", "https"}


# Order matters: first match wins, so the more specific keywords come first.
# Default falls through to "generate_greeting" — the most generic of the
# three demo tools.
_TOOL_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("投诉", "complaint", "complain"), "generate_complaint_response"),
    (("faq", "问答", "常见问题", "售后"), "generate_faq"),
    (("greeting", "欢迎", "售前", "客服"), "generate_greeting"),
]

_DEFAULT_TOOL = "generate_greeting"
_PREVIEW_SIZE = 5


def pick_tool_for_task(task_id: str | None, agent_name: str | None, asset_name: str | None = None) -> str:
    """Return the demo tool name that best fits the task.

    Joins the three hints into a lowercase haystack and runs the keyword
    table top-to-bottom. Pure / deterministic so settle stays reproducible.
    """
    parts = [p for p in (task_id, agent_name, asset_name) if p]
    if not parts:
        return _DEFAULT_TOOL
    haystack = " ".join(parts).lower()
    for keywords, tool in _TOOL_KEYWORDS:
        if any(kw in haystack for kw in keywords):
            return tool
    return _DEFAULT_TOOL


def _mcp_error(
    tool_name: str,
    endpoint_url: str,
    error: str,
    payment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The one error shape.

    `payment` is None for every failure that happened before or instead of a
    settlement. It is deliberately NOT forced to None afterwards: if the
    facilitator settled and the handler then returned a 500, the creator has
    been paid and the tx hash must survive into the pact — losing it is how a
    real payment turns into an unexplained missing USDC.
    """
    return {
        "status": "error",
        "tool": tool_name,
        "error": error,
        "endpoint_url": endpoint_url,
        "payment": payment,
    }


def _mcp_unknown(
    tool_name: str,
    endpoint_url: str,
    exc: PaymentOutcomeUnknown,
) -> dict[str, Any]:
    """The THIRD status, for "we signed and transmitted, and never found out".

    Stage 2 / WP-R (review F2). `status: "error"` is wrong here and is what the
    review found: the caller reads it as "nothing happened" and releases its
    claim, so a retry signs a SECOND authorization for a payment that may
    already have settled. This status exists so the caller can tell the two
    apart and freeze instead.

    Additive: `payment` stays present and None (no CONFIRMED payment), the
    error/tool/endpoint_url keys are unchanged, and `payment_pending` is the
    one new key — the identity of the authorization now in limbo, so an
    operator can look the nonce up on-chain.
    """
    return {
        "status": "unknown",
        "tool": tool_name,
        "error": f"{exc.__class__.__name__}: {exc}",
        "endpoint_url": endpoint_url,
        "payment": None,
        "payment_pending": {
            "nonce": exc.nonce,
            "payee": exc.payee,
            "amount_atomic": exc.amount_atomic,
            "error": str(exc),
        },
    }


def call_mcp_tool(
    endpoint_url: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    timeout: float = 5.0,
    *,
    session: Any = None,
    max_amount: int | None = None,
) -> dict[str, Any]:
    """POST to the MCP server, return a small summary safe to put on a pact.

    Output shape on success:
        {"status": "ok", "tool": <name>, "total": <int>,
         "preview": [<first N items>], "endpoint_url": <url>,
         "payment": <dict|None>}

    Output shape on any failure (timeout, non-200, bad JSON, missing url,
    refused or failed payment):
        {"status": "error", "tool": <name>, "error": <str>,
         "endpoint_url": <url>, "payment": <dict|None>}

    Output shape when an authorization was signed and transmitted and the
    server never said what became of it (Stage 2 / WP-R, review F2):
        {"status": "unknown", "tool": <name>, "error": <str>,
         "endpoint_url": <url>, "payment": None,
         "payment_pending": {"nonce", "payee", "amount_atomic", "error"}}
    A caller seeing this MUST NOT retry the invocation: retrying signs a
    second authorization for a payment that may already have settled.

    `payment` is None unless an x402 payment actually settled; then it is
    `{"method": "x402", "tx_hash", "network", "payer", "payee",
      "amount_atomic", "asset", "settle_success"}` (see x402_payer). It stays
    populated on a post-settlement failure (settled, then the handler 500'd)
    so the tx hash is never dropped.

    `session` is a TEST SEAM: any object with `.request(method, url, json=,
    headers=, **kwargs)`. Defaults to the `requests` module, i.e. real HTTP.

    `max_amount` is a per-invocation spend ceiling in USDC atomic units, applied
    at the signing point instead of the `X402_MAX_AMOUNT_PER_PAYMENT` default.
    None (every pre-WP-E caller) keeps that env-configured default. Stage 2 /
    WP-E: pact settle passes the mandate's own amount_cap here — already reduced
    to the tighter of the mandate cap and the operator's brake — so a quote
    above what the enterprise authorized is refused before anything is signed.

    Never raises. On the legacy settle path pact_settle has already committed
    royalty rows before we get here; bubbling exceptions up would either roll
    those back (wrong) or surface as a 500 with the user blocked at "settling"
    forever (worse). On the WP-E x402 path nothing is committed yet, and the
    folded `{"status": "error", ...}` is what tells the route to record nothing
    and leave the mandate approved.
    """
    if not endpoint_url:
        return _mcp_error(tool_name, endpoint_url, "endpoint_url is empty")

    # SSRF posture: scheme allowlist + no redirects. See the module-level
    # comment for what's intentionally NOT enforced (loopback / RFC1918
    # blocking is off for the Phase 1 demo loop against localhost:5002).
    parsed = urlparse(endpoint_url)
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.netloc:
        return _mcp_error(
            tool_name,
            endpoint_url,
            f"endpoint_url scheme must be http or https, got {parsed.scheme!r}",
        )

    target = endpoint_url.rstrip("/") + "/mcp/tools/call"
    payload = {"name": tool_name, "arguments": arguments or {}}
    http = session if session is not None else requests

    # Read the key here and pass it down as an argument; x402_payer never keeps
    # it. An empty/whitespace value counts as "not configured" so a blank line
    # in .env cannot half-enable payments.
    private_key = (os.getenv(PAYER_KEY_ENV) or "").strip()
    payment: dict[str, Any] | None = None

    try:
        if private_key:
            # Pays at most once, and only if the server actually 402s.
            # allow_redirects/timeout are forwarded to BOTH attempts.
            resp, payment = pay_and_retry(
                http,
                "POST",
                target,
                json=payload,
                private_key=private_key,
                # None → x402_payer falls back to X402_MAX_AMOUNT_PER_PAYMENT.
                max_amount=max_amount,
                timeout=timeout,
                allow_redirects=False,
            )
        else:
            resp = http.request(
                "POST", target, json=payload, timeout=timeout, allow_redirects=False
            )
            if resp.status_code == 402:
                # Deliberately NOT retried and NOT downgraded to a generic HTTP
                # error: the creator asked to be paid and we cannot pay.
                raise PaymentRequiredError(
                    f"x402 payment required but {PAYER_KEY_ENV} is not configured"
                )
    except PaymentOutcomeUnknown as exc:
        # MUST precede the X402PayerError clause below — PaymentOutcomeUnknown
        # is a PaymentFailed, and folding it into `status: "error"` is exactly
        # the double-pay exposure review F2 found.
        return _mcp_unknown(tool_name, endpoint_url, exc)
    except X402PayerError as exc:
        # Class name kept in the message: PaymentFailed / SpendCapExceeded /
        # NoMatchingPaymentOption / PaymentRequiredError are meaningfully
        # different failures for whoever reads the pact afterwards.
        return _mcp_error(tool_name, endpoint_url, f"{exc.__class__.__name__}: {exc}")
    except requests.RequestException as exc:
        return _mcp_error(
            tool_name, endpoint_url, f"request failed: {exc.__class__.__name__}: {exc}"
        )
    except Exception as exc:  # noqa: BLE001 - the never-raises contract, on purpose
        # The payment path can also raise plain ValueErrors (a malformed
        # X402_MAX_AMOUNT_PER_PAYMENT, a non-integer quoted amount). Letting one
        # escape would 500 the settle route AFTER the royalty rows committed —
        # exactly what this function exists to prevent. Nothing is swallowed:
        # the message lands on the pact and in the UI. The private key is not
        # reachable from any of these messages (x402_payer scrubs the two calls
        # that hold it).
        return _mcp_error(
            tool_name, endpoint_url, f"payment path failed: {exc.__class__.__name__}: {exc}"
        )

    if resp.status_code != 200:
        return _mcp_error(
            tool_name, endpoint_url, f"HTTP {resp.status_code}: {resp.text[:200]}", payment
        )

    try:
        data = resp.json()
    except ValueError as exc:
        return _mcp_error(tool_name, endpoint_url, f"invalid JSON: {exc}", payment)

    items = data.get("items") or []
    total = data.get("total")
    if not isinstance(total, int):
        total = len(items)

    return {
        "status": "ok",
        "tool": tool_name,
        "total": total,
        "preview": list(items[:_PREVIEW_SIZE]),
        "endpoint_url": endpoint_url,
        "payment": payment,
    }
