"""End-to-end tests for MCP wiring in pact_settle.

Covers:
  - pick_tool_for_task picks the right tool for each keyword family.
  - settle on an asset WITH endpoint_url calls the configured MCP client
    and surfaces preview/total/tool on the pact.
  - settle on an asset WITHOUT endpoint_url leaves mcp_result == None and
    royalty rows still land — proving MCP wiring is gated, not mandatory.
  - When the MCP client returns a wrapped error, royalty is unaffected
    (we never roll back the just-committed agent_run).

The real call_mcp_tool wraps every failure into a status="error" dict (so
it never raises), so we exercise the failure path by injecting a fake
client that does the same.
"""
import os
import tempfile

import pytest

from app.app import create_app
from app.services.mcp_client import call_mcp_tool, pick_tool_for_task
from app.services.skill_registration import register_skill_asset
from app.storage.royalty_ledger import list_royalties_by_run


# ---------------------------------------------------------------------------
# pick_tool_for_task — pure unit
# ---------------------------------------------------------------------------

class TestPickToolForTask:
    def test_complaint_keyword_picks_complaint_tool(self):
        assert pick_tool_for_task("task-001", "投诉处理 Agent", None) == "generate_complaint_response"

    def test_english_complaint_keyword(self):
        assert pick_tool_for_task("handle-complaint", "support bot", None) == "generate_complaint_response"

    def test_faq_keyword_picks_faq_tool(self):
        assert pick_tool_for_task("task-faq-001", "售后 Agent", None) == "generate_faq"

    def test_chinese_faq_keyword(self):
        assert pick_tool_for_task("task-001", "常见问题机器人", None) == "generate_faq"

    def test_default_falls_through_to_greeting(self):
        assert pick_tool_for_task("task-001", "客服机器人", None) == "generate_greeting"

    def test_empty_hints_returns_default(self):
        assert pick_tool_for_task(None, None, None) == "generate_greeting"

    def test_complaint_takes_precedence_over_faq(self):
        # First match wins per the keyword table order.
        assert pick_tool_for_task("complaint-faq", None, None) == "generate_complaint_response"

    def test_asset_name_also_consulted(self):
        assert pick_tool_for_task("task-x", "agent-y", "投诉话术资产") == "generate_complaint_response"


# ---------------------------------------------------------------------------
# call_mcp_tool — SSRF surface
# ---------------------------------------------------------------------------

class TestCallMcpToolSsrfDefenses:
    """Phase 1 keeps loopback usable but blocks scheme-confusion + redirects."""

    def test_rejects_file_scheme_without_network_call(self):
        result = call_mcp_tool("file:///etc/passwd", "generate_greeting")
        assert result["status"] == "error"
        assert "scheme" in result["error"]

    def test_rejects_gopher_scheme(self):
        result = call_mcp_tool("gopher://internal:6379/_SET%20foo%20bar", "generate_greeting")
        assert result["status"] == "error"
        assert "scheme" in result["error"]

    def test_rejects_url_with_no_netloc(self):
        result = call_mcp_tool("http://", "generate_greeting")
        assert result["status"] == "error"

    def test_empty_endpoint_url_rejected(self):
        result = call_mcp_tool("", "generate_greeting")
        assert result["status"] == "error"
        assert "empty" in result["error"]


# ---------------------------------------------------------------------------
# Fakes used for MCP injection
# ---------------------------------------------------------------------------

class _RecordingMcpClient:
    """Captures every call, returns a deterministic ok payload."""

    def __init__(self):
        self.calls = []

    def __call__(self, endpoint_url, tool_name, arguments=None, timeout=5.0, **kwargs):
        # **kwargs absorbs the keyword-only extensions the settle paths pass
        # (`max_amount` on the x402 rail, `lang` since WP-I18N-2) — recorded
        # so a test can assert on them.
        self.calls.append({
            "endpoint_url": endpoint_url,
            "tool_name": tool_name,
            "arguments": arguments,
            **kwargs,
        })
        return {
            "status": "ok",
            "tool": tool_name,
            "total": 3,
            "preview": ["a", "b", "c"],
            "endpoint_url": endpoint_url,
        }


def _failing_mcp_client(endpoint_url, tool_name, arguments=None, timeout=5.0, **kwargs):
    """Mirrors call_mcp_tool's behaviour when the remote refuses — never raises."""
    return {
        "status": "error",
        "tool": tool_name,
        "error": "injected: connection refused",
        "endpoint_url": endpoint_url,
    }


# ---------------------------------------------------------------------------
# Integration fixtures
# ---------------------------------------------------------------------------

def _make_client(mcp_client_fn=None):
    """Build a Flask test client with an isolated DB and (optionally) injected MCP."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    config = {"TESTING": True, "DATABASE_PATH": path}
    if mcp_client_fn is not None:
        config["MCP_CLIENT"] = mcp_client_fn
    app = create_app(config=config)
    return app, app.test_client(), path


def _register_mcp_asset(db_path, *, endpoint_url, name="客服话术 Agent"):
    payload = {
        "name": name,
        "description": "demo MCP-backed asset for integration tests",
        "type": "skill",
        "endpoint_url": endpoint_url,
        "io_schema": {"input": {"task_id": "string"}, "output": {"items": "list"}},
        "price_amount": 100,
        "price_currency": "USD",
        "split_rule": {"creator": 7000, "platform": 2000, "tax": 1000},
    }
    return register_skill_asset(db_path, payload, "creator-mcp-1")["skill_id"]


def _settle_pact_with_asset(client, asset_id, *, task_id="task-greeting", agent_name="客服话术生成器"):
    """create → approve → settle, return the settle JSON body."""
    create_resp = client.post("/api/pact/create", json={
        "task_id": task_id,
        "agent_name": agent_name,
        "asset_id": asset_id,
        "amount": 1,
        "currency": "USD",
    })
    assert create_resp.status_code == 201, create_resp.get_json()
    pact_id = create_resp.get_json()["pact_id"]

    approve_resp = client.post(f"/api/pact/approve/{pact_id}")
    assert approve_resp.status_code == 200, approve_resp.get_json()

    settle_resp = client.post(f"/api/pact/settle/{pact_id}")
    assert settle_resp.status_code == 200, settle_resp.get_json()
    return settle_resp.get_json()


# ---------------------------------------------------------------------------
# Integration: settle WITH endpoint_url
# ---------------------------------------------------------------------------

def test_settle_with_endpoint_url_invokes_mcp_client():
    recorder = _RecordingMcpClient()
    app, client, db_path = _make_client(mcp_client_fn=recorder)
    try:
        asset_id = _register_mcp_asset(db_path, endpoint_url="http://demo-mcp.local")
        body = _settle_pact_with_asset(
            client, asset_id, task_id="task-greeting-9", agent_name="售前客服 Agent",
        )

        assert body["status"] == "settled"
        # Royalty side effects: still landed.
        assert body["run_id"]
        assert body["royalty_splits"]

        # MCP invocation: exactly once, with the chosen tool.
        assert len(recorder.calls) == 1
        call = recorder.calls[0]
        assert call["endpoint_url"] == "http://demo-mcp.local"
        # "客服" / "售前" routes to greeting per the keyword table.
        assert call["tool_name"] == "generate_greeting"
        assert call["arguments"] == {"task_id": "task-greeting-9"}

        # Pact carries the fake client's preview/total/tool.
        assert body["mcp_result"]["status"] == "ok"
        assert body["mcp_result"]["tool"] == "generate_greeting"
        assert body["mcp_result"]["preview"] == ["a", "b", "c"]
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Integration: settle WITHOUT endpoint_url — Job Design fallback path
# ---------------------------------------------------------------------------

def test_settle_without_endpoint_url_leaves_mcp_result_none():
    """Default Job Design asset has no endpoint_url; mcp_result must be None."""
    recorder = _RecordingMcpClient()
    app, client, db_path = _make_client(mcp_client_fn=recorder)
    try:
        # Don't pass asset_id — falls back to bootstrap Job Design asset.
        create_resp = client.post("/api/pact/create", json={
            "task_id": "task-design-1",
            "agent_name": "Job Design Agent",
            "amount": 1,
            "currency": "USD",
        })
        assert create_resp.status_code == 201, create_resp.get_json()
        pact_id = create_resp.get_json()["pact_id"]
        assert client.post(f"/api/pact/approve/{pact_id}").status_code == 200
        settle_resp = client.post(f"/api/pact/settle/{pact_id}")
        assert settle_resp.status_code == 200
        body = settle_resp.get_json()

        assert body["status"] == "settled"
        assert body["run_id"]
        assert body["royalty_splits"]
        # No MCP call attempted.
        assert recorder.calls == []
        assert body["mcp_result"] is None
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Integration: MCP failure must NOT roll back royalty
# ---------------------------------------------------------------------------

def test_mcp_failure_keeps_pact_settled_and_royalty_intact():
    app, client, db_path = _make_client(mcp_client_fn=_failing_mcp_client)
    try:
        asset_id = _register_mcp_asset(db_path, endpoint_url="http://broken-mcp.local")
        body = _settle_pact_with_asset(
            client, asset_id, task_id="task-complaint-7", agent_name="投诉处理 Agent",
        )

        # Settlement stuck through despite MCP failure.
        assert body["status"] == "settled"
        run_id = body["run_id"]
        assert run_id

        # Royalty rows present in the ledger — proof the money path didn't roll back.
        rows = list_royalties_by_run(db_path, run_id)
        assert len(rows) >= 1
        # Split shape unchanged (creator + platform + tax).
        parties = {r["party"] for r in rows}
        assert parties == {"creator", "platform", "tax"}

        # mcp_result surfaces the error so the UI can display it.
        assert body["mcp_result"]["status"] == "error"
        assert body["mcp_result"]["tool"] == "generate_complaint_response"
        assert "injected" in body["mcp_result"]["error"]
    finally:
        os.unlink(db_path)
