"""
WP-I18N-2 / D-F — the MCP demo servers answer in the caller's language.

This is the most visible Chinese left in an English demo: `pact_settle` invokes
one of these tools and `ExecutionPage.jsx` renders `mcp_result.preview[]`
verbatim as the "Agent Output Preview" — the climax of the pact-settle flow.

Three things are pinned:

1. `tools/call` with `lang=en` -> not one CJK character in the response;
   without it -> byte-identical to the pre-change canned set.
2. `tools/list?lang=en` -> English tool and parameter descriptions; without it
   -> the original Chinese ones.
3. The plumbing: `call_mcp_tool(..., lang="en")` puts `lang` in the outgoing
   `arguments`, and both pact-settle rails pass the request's language —
   asserted through the injected fake client, which is the seam the settle
   routes read from `current_app.config["MCP_CLIENT"]`.

The English sets are TRANSLATIONS of the Chinese ones, not a different demo,
so the "same number of lines" assertions are meaningful.
"""
import pytest

from app.mcp_servers.customer_service import (
    _COMPLAINTS,
    _COMPLAINTS_EN,
    _FAQ,
    _FAQ_EN,
    _GREETINGS,
    _GREETINGS_EN,
    create_mcp_app,
)
from app.mcp_servers.data_analysis import (
    _ANOMALIES,
    _ANOMALIES_EN,
    _REPORTS,
    _REPORTS_EN,
    _TRENDS,
    _TRENDS_EN,
)
from app.mcp_servers.data_analysis import create_app as create_data_app
from app.services.mcp_client import call_mcp_tool, pick_tool_for_task
from tests.test_i18n_helpers import CJK_PATTERN, assert_no_cjk


@pytest.fixture
def cs_client():
    with create_mcp_app().test_client() as c:
        yield c


@pytest.fixture
def da_client():
    with create_data_app().test_client() as c:
        yield c


# ─── The canned sets themselves ──────────────────────────────────────────────


class TestCannedSets:
    @pytest.mark.parametrize("zh, en, label", [
        (_GREETINGS, _GREETINGS_EN, "greetings"),
        (_FAQ, _FAQ_EN, "faq"),
        (_COMPLAINTS, _COMPLAINTS_EN, "complaints"),
        (_TRENDS, _TRENDS_EN, "trends"),
        (_ANOMALIES, _ANOMALIES_EN, "anomalies"),
        (_REPORTS, _REPORTS_EN, "reports"),
    ])
    def test_the_english_set_matches_the_chinese_one_line_for_line(self, zh, en, label):
        assert len(en) == len(zh), f"{label}: the two sets must stay comparable"
        assert_no_cjk(en, f"{label} (en)")

    def test_the_chinese_sets_still_hold_their_promised_counts(self):
        """The pre-existing guard in tests/test_mcp_server_demo.py, restated
        here so a careless edit to the EN sets cannot quietly shrink them."""
        assert (len(_GREETINGS), len(_FAQ), len(_COMPLAINTS)) == (40, 50, 30)
        assert (len(_GREETINGS_EN), len(_FAQ_EN), len(_COMPLAINTS_EN)) == (40, 50, 30)

    def test_the_chinese_sets_are_still_chinese(self):
        for text in (_GREETINGS[0], _FAQ[0], _COMPLAINTS[0], _TRENDS[0]):
            assert CJK_PATTERN.search(text)


# ─── tools/call ──────────────────────────────────────────────────────────────


CS_TOOLS = ["generate_greeting", "generate_faq", "generate_complaint_response"]
DA_TOOLS = ["analyze_trend", "detect_anomaly", "generate_report"]


class TestCustomerServiceToolsCall:
    @pytest.mark.parametrize("tool", CS_TOOLS)
    def test_lang_en_returns_no_cjk(self, cs_client, tool):
        res = cs_client.post("/mcp/tools/call", json={
            "name": tool, "arguments": {"task_id": "t1", "lang": "en"},
        })
        assert res.status_code == 200
        assert_no_cjk(res.get_json(), f"{tool}?lang=en")

    @pytest.mark.parametrize("tool, expected", list(zip(CS_TOOLS, (_GREETINGS, _FAQ, _COMPLAINTS))))
    def test_lang_absent_is_byte_identical_to_today(self, cs_client, tool, expected):
        res = cs_client.post("/mcp/tools/call", json={
            "name": tool, "arguments": {"task_id": "t1"},
        })
        assert res.get_json() == {
            "name": tool, "task_id": "t1", "items": expected, "total": len(expected),
        }

    @pytest.mark.parametrize("tool, expected", list(zip(CS_TOOLS, (_GREETINGS, _FAQ, _COMPLAINTS))))
    def test_lang_zh_is_the_same_as_absent(self, cs_client, tool, expected):
        res = cs_client.post("/mcp/tools/call", json={
            "name": tool, "arguments": {"task_id": "t1", "lang": "zh"},
        })
        assert res.get_json()["items"] == expected

    def test_limit_still_applies_in_english(self, cs_client):
        res = cs_client.post("/mcp/tools/call", json={
            "name": "generate_greeting", "arguments": {"limit": 3, "lang": "en"},
        })
        body = res.get_json()
        assert body["items"] == _GREETINGS_EN[:3]
        assert body["total"] == 3

    def test_query_param_lang_works_too(self, cs_client):
        res = cs_client.post("/mcp/tools/call?lang=en", json={
            "name": "generate_greeting", "arguments": {"limit": 1},
        })
        assert res.get_json()["items"] == _GREETINGS_EN[:1]

    def test_an_unknown_lang_falls_back_to_chinese(self, cs_client):
        res = cs_client.post("/mcp/tools/call", json={
            "name": "generate_greeting", "arguments": {"limit": 1, "lang": "fr"},
        })
        assert res.get_json()["items"] == _GREETINGS[:1]

    def test_unknown_tool_is_still_a_400(self, cs_client):
        res = cs_client.post("/mcp/tools/call", json={"name": "nope", "arguments": {"lang": "en"}})
        assert res.status_code == 400


class TestDataAnalysisToolsCall:
    @pytest.mark.parametrize("tool", DA_TOOLS)
    def test_lang_en_returns_no_cjk(self, da_client, tool):
        res = da_client.post("/mcp/tools/call", json={
            "name": tool, "arguments": {"task_id": "t1", "lang": "en"},
        })
        assert res.status_code == 200
        assert_no_cjk(res.get_json(), f"{tool}?lang=en")

    @pytest.mark.parametrize("tool, expected", list(zip(DA_TOOLS, (_TRENDS, _ANOMALIES, _REPORTS))))
    def test_lang_absent_is_byte_identical_to_today(self, da_client, tool, expected):
        res = da_client.post("/mcp/tools/call", json={
            "name": tool, "arguments": {"task_id": "t1"},
        })
        assert res.get_json() == {
            "name": tool, "task_id": "t1", "items": expected, "total": len(expected),
        }


# ─── tools/list ──────────────────────────────────────────────────────────────


class TestToolsList:
    def test_customer_service_descriptions_in_english(self, cs_client):
        res = cs_client.post("/mcp/tools/list?lang=en")
        assert res.status_code == 200
        tools = res.get_json()["tools"]
        assert {t["name"] for t in tools} == set(CS_TOOLS)
        assert_no_cjk(tools, "customer_service tools/list?lang=en")

    def test_customer_service_descriptions_default_to_chinese(self, cs_client):
        tools = cs_client.post("/mcp/tools/list").get_json()["tools"]
        by_name = {t["name"]: t for t in tools}
        assert by_name["generate_greeting"]["description"] == "生成客服欢迎语 / 售前话术。"
        assert by_name["generate_faq"]["description"] == "生成售后 / 常见问题话术。"
        assert by_name["generate_complaint_response"]["description"] == "生成投诉回复话术。"
        assert by_name["generate_greeting"]["input_schema"]["properties"]["task_id"][
            "description"] == "任务 ID（用于去重 / 审计）"

    def test_data_analysis_descriptions_in_english(self, da_client):
        tools = da_client.post("/mcp/tools/list?lang=en").get_json()["tools"]
        assert {t["name"] for t in tools} == set(DA_TOOLS)
        assert_no_cjk(tools, "data_analysis tools/list?lang=en")

    def test_data_analysis_descriptions_default_to_chinese(self, da_client):
        tools = da_client.post("/mcp/tools/list").get_json()["tools"]
        by_name = {t["name"]: t for t in tools}
        assert by_name["analyze_trend"]["description"] == "分析数据趋势，输出关键指标变化方向"
        assert by_name["detect_anomaly"]["description"] == "检测数据中的异常值"
        assert by_name["generate_report"]["description"] == "生成数据分析报告摘要"

    def test_the_tool_table_is_not_mutated_by_localising_it(self, cs_client):
        cs_client.post("/mcp/tools/list?lang=en")
        from app.mcp_servers.customer_service import _TOOLS
        assert _TOOLS[0]["description"] == {
            "zh": "生成客服欢迎语 / 售前话术。",
            "en": "Generate customer-service greetings and pre-sales scripts.",
        }


# ─── call_mcp_tool forwards lang ─────────────────────────────────────────────


class _RecordingSession:
    """Minimal stand-in for `requests`: records the request, returns 200 JSON."""

    def __init__(self, payload=None):
        self.requests = []
        self.payload = payload or {"items": ["a"], "total": 1}

    def request(self, method, url, json=None, **kwargs):
        self.requests.append({"method": method, "url": url, "json": json})
        session = self

        class _Resp:
            status_code = 200
            text = ""

            def json(self):
                return session.payload

        return _Resp()


class TestCallMcpToolForwardsLang:
    def test_lang_en_is_added_to_the_arguments(self):
        session = _RecordingSession()
        call_mcp_tool("http://mcp.test", "generate_greeting", {"task_id": "t1"},
                      session=session, lang="en")
        assert session.requests[0]["json"]["arguments"] == {"task_id": "t1", "lang": "en"}

    @pytest.mark.parametrize("lang", [None, "zh"])
    def test_the_wire_body_is_unchanged_without_en(self, lang):
        session = _RecordingSession()
        call_mcp_tool("http://mcp.test", "generate_greeting", {"task_id": "t1"},
                      session=session, lang=lang)
        assert session.requests[0]["json"] == {
            "name": "generate_greeting", "arguments": {"task_id": "t1"},
        }

    def test_an_explicit_argument_lang_wins(self):
        session = _RecordingSession()
        call_mcp_tool("http://mcp.test", "generate_greeting",
                      {"task_id": "t1", "lang": "zh"}, session=session, lang="en")
        assert session.requests[0]["json"]["arguments"]["lang"] == "zh"

    def test_the_callers_arguments_dict_is_not_mutated(self):
        session = _RecordingSession()
        arguments = {"task_id": "t1"}
        call_mcp_tool("http://mcp.test", "generate_greeting", arguments,
                      session=session, lang="en")
        assert arguments == {"task_id": "t1"}


class TestToolRoutingKeywords:
    """English hints must route as well as the Chinese ones — an English
    session's `agent_name` carries no Chinese for the table to match on."""

    @pytest.mark.parametrize("hint, expected", [
        ("投诉处理", "generate_complaint_response"),
        ("handle a complaint", "generate_complaint_response"),
        ("常见问题", "generate_faq"),
        ("FAQ script", "generate_faq"),
        ("after-sales scripts", "generate_faq"),
        ("客服话术", "generate_greeting"),
        ("Customer Service Script Generator", "generate_greeting"),
        ("pre-sale greeting", "generate_greeting"),
        ("something unrelated", "generate_greeting"),
    ])
    def test_routing(self, hint, expected):
        assert pick_tool_for_task(None, hint, None) == expected


# ─── The settle path passes the request's language ───────────────────────────


class _McpProbe:
    """Injected `MCP_CLIENT`; records the kwargs the settle route passes."""

    def __init__(self):
        self.calls = []

    def __call__(self, endpoint_url, tool_name, arguments=None, **kwargs):
        self.calls.append({"endpoint_url": endpoint_url, "tool_name": tool_name,
                           "arguments": arguments, **kwargs})
        return {"status": "ok", "tool": tool_name, "total": 1,
                "preview": ["Hello and welcome!"], "endpoint_url": endpoint_url,
                "payment": None}


@pytest.fixture
def settle_client(tmp_path):
    """A backend whose MCP client is the probe above."""
    from app.app import create_app
    from app.services.mock_settlement import MockSettlementProvider

    probe = _McpProbe()
    app = create_app(config={
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "settle.db"),
        "SETTLEMENT_PROVIDER": MockSettlementProvider(),
        "MCP_CLIENT": probe,
    })
    with app.test_client() as c:
        yield c, probe, app.config["DATABASE_PATH"]


def _asset_with_endpoint(db_path):
    from app.services.skill_registration import register_skill_asset

    return register_skill_asset(db_path, {
        "name": "Customer Service Script Generator",
        "description": "demo MCP-backed asset",
        "type": "skill",
        "endpoint_url": "http://localhost:5002",
        "io_schema": {"input": {"task_id": "string"}, "output": {"items": "list"}},
        "price_amount": 100,
        "price_currency": "USD",
        "split_rule": {"creator": 7000, "platform": 2000, "tax": 1000},
    }, "zhang_ai")["skill_id"]


class TestPactSettlePassesLang:
    def _settle(self, client, asset_id, query=""):
        created = client.post("/api/pact/create", json={
            "task_id": "task-greeting", "agent_name": "Customer Service Script Generator",
            "asset_id": asset_id, "amount": 1, "currency": "USD",
        })
        assert created.status_code == 201, created.get_data(as_text=True)
        pact_id = created.get_json()["pact_id"]
        assert client.post(f"/api/pact/approve/{pact_id}").status_code == 200
        return client.post(f"/api/pact/settle/{pact_id}{query}")

    def test_lang_en_reaches_the_mcp_client(self, settle_client):
        client, probe, db_path = settle_client
        res = self._settle(client, _asset_with_endpoint(db_path), "?lang=en")
        assert res.status_code == 200, res.get_data(as_text=True)
        assert probe.calls[0]["lang"] == "en"

    def test_lang_absent_passes_the_default(self, settle_client):
        client, probe, db_path = settle_client
        res = self._settle(client, _asset_with_endpoint(db_path))
        assert res.status_code == 200, res.get_data(as_text=True)
        # "zh" is the documented default; `call_mcp_tool` does not put it on
        # the wire, so the request body an MCP server sees is unchanged.
        assert probe.calls[0]["lang"] == "zh"
