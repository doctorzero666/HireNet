"""Smoke tests for the demo MCP server (app/mcp_servers/customer_service.py).

Drives the Flask app via test_client so we don't bind :5002 in CI.
"""
import pytest

from app.mcp_servers.customer_service import (
    _COMPLAINTS,
    _FAQ,
    _GREETINGS,
    create_mcp_app,
)


@pytest.fixture
def mcp_client():
    app = create_mcp_app()
    with app.test_client() as c:
        yield c


def test_dataset_has_120_canned_lines():
    """Phase 1 demo promises 40 + 50 + 30 = 120; guard against silent edits."""
    assert len(_GREETINGS) == 40
    assert len(_FAQ) == 50
    assert len(_COMPLAINTS) == 30


def test_list_tools_returns_three_tool_specs(mcp_client):
    resp = mcp_client.post("/mcp/tools/list")
    assert resp.status_code == 200
    tools = resp.get_json()["tools"]
    names = {t["name"] for t in tools}
    assert names == {
        "generate_greeting",
        "generate_faq",
        "generate_complaint_response",
    }


def test_call_generate_greeting_returns_items(mcp_client):
    resp = mcp_client.post(
        "/mcp/tools/call",
        json={"name": "generate_greeting", "arguments": {"task_id": "task-001"}},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["name"] == "generate_greeting"
    assert body["total"] == 40
    assert len(body["items"]) == 40
    assert body["task_id"] == "task-001"


def test_call_respects_limit_argument(mcp_client):
    resp = mcp_client.post(
        "/mcp/tools/call",
        json={"name": "generate_faq", "arguments": {"limit": 3}},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total"] == 3
    assert len(body["items"]) == 3


def test_call_unknown_tool_returns_400(mcp_client):
    resp = mcp_client.post(
        "/mcp/tools/call",
        json={"name": "does_not_exist", "arguments": {}},
    )
    assert resp.status_code == 400
    assert "Unknown tool" in resp.get_json()["error"]


def test_health_endpoint_returns_200(mcp_client):
    resp = mcp_client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}
