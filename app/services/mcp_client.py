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
app/services/mock_settlement.py.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import requests


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


def call_mcp_tool(
    endpoint_url: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """POST to the MCP server, return a small summary safe to put on a pact.

    Output shape on success:
        {"status": "ok", "tool": <name>, "total": <int>,
         "preview": [<first N items>], "endpoint_url": <url>}

    Output shape on any failure (timeout, non-200, bad JSON, missing url):
        {"status": "error", "tool": <name>, "error": <str>,
         "endpoint_url": <url>}

    Never raises. pact_settle already committed royalty rows before we get
    here; bubbling exceptions up would either roll those back (wrong) or
    surface as a 500 with the user blocked at "settling" forever (worse).
    """
    if not endpoint_url:
        return {
            "status": "error",
            "tool": tool_name,
            "error": "endpoint_url is empty",
            "endpoint_url": endpoint_url,
        }

    # SSRF posture: scheme allowlist + no redirects. See the module-level
    # comment for what's intentionally NOT enforced (loopback / RFC1918
    # blocking is off for the Phase 1 demo loop against localhost:5002).
    parsed = urlparse(endpoint_url)
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.netloc:
        return {
            "status": "error",
            "tool": tool_name,
            "error": f"endpoint_url scheme must be http or https, got {parsed.scheme!r}",
            "endpoint_url": endpoint_url,
        }

    target = endpoint_url.rstrip("/") + "/mcp/tools/call"
    payload = {"name": tool_name, "arguments": arguments or {}}

    try:
        resp = requests.post(target, json=payload, timeout=timeout, allow_redirects=False)
    except requests.RequestException as exc:
        return {
            "status": "error",
            "tool": tool_name,
            "error": f"request failed: {exc.__class__.__name__}: {exc}",
            "endpoint_url": endpoint_url,
        }

    if resp.status_code != 200:
        return {
            "status": "error",
            "tool": tool_name,
            "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            "endpoint_url": endpoint_url,
        }

    try:
        data = resp.json()
    except ValueError as exc:
        return {
            "status": "error",
            "tool": tool_name,
            "error": f"invalid JSON: {exc}",
            "endpoint_url": endpoint_url,
        }

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
    }
