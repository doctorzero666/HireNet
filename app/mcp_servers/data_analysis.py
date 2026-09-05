"""Demo MCP server: data analysis agent.

Standalone Flask app on :5003. Three tools for demo, with a Chinese and an
English canned set for each.

WP-I18N-2 / D-F: the language is chosen by an optional `lang` —
`arguments.lang` (or `?lang=`) on `POST /mcp/tools/call`, `?lang=` on
`POST /mcp/tools/list`. Absent means Chinese, and the Chinese content below is
byte-identical to what it was. `_pick` is local rather than imported from
`app.agents.lang_support` because this file is a standalone Flask app that is
also run as a script, where `app.*` is not importable until the `sys.path`
fix-up at the bottom has run.
"""
import os

from flask import Flask, jsonify, request
from flask_cors import CORS

# The endpoint_url this server is registered under in `skill_assets`
# (app/services/demo_bootstrap.py: DEMO_DATA_ANALYST). The x402 gate uses it to
# find which SkillAsset — and therefore which creator wallet — gets paid.
ASSET_ENDPOINT_URL = os.getenv("HIRENET_MCP_ENDPOINT_URL", "http://localhost:5003")

#: `{"zh": ..., "en": ...}` -> the requested side. See the module docstring
#: for why this is not `app.agents.lang_support.pick`.
def _pick(node, lang):
    if isinstance(node, dict) and "zh" in node:
        return node.get(lang if lang == "en" else "zh", node["zh"])
    return node


def _request_lang(args=None):
    """`arguments.lang`, else `?lang=`, else None (Chinese)."""
    raw = (args or {}).get("lang") or request.args.get("lang")
    return "en" if raw == "en" else None


_TOOLS = [
    {
        "name": "analyze_trend",
        "description": {
            "zh": "分析数据趋势，输出关键指标变化方向",
            "en": "Analyse data trends and report which way the key metrics are moving",
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "metric": {
                    "type": "string",
                    "description": {"zh": "要分析的指标名", "en": "Name of the metric to analyse"},
                },
                "lang": {"type": "string", "enum": ["zh", "en"]},
            },
        },
    },
    {
        "name": "detect_anomaly",
        "description": {
            "zh": "检测数据中的异常值",
            "en": "Detect outliers in the data",
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "threshold": {
                    "type": "number",
                    "description": {
                        "zh": "异常阈值（标准差倍数）",
                        "en": "Anomaly threshold, in multiples of the standard deviation",
                    },
                },
                "lang": {"type": "string", "enum": ["zh", "en"]},
            },
        },
    },
    {
        "name": "generate_report",
        "description": {
            "zh": "生成数据分析报告摘要",
            "en": "Generate a data-analysis report summary",
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "format": {
                    "type": "string",
                    "description": {
                        "zh": "报告格式：summary / full",
                        "en": "Report format: summary / full",
                    },
                },
                "lang": {"type": "string", "enum": ["zh", "en"]},
            },
        },
    },
]


def _localized_tools(lang):
    """`_TOOLS` with every bilingual `description` resolved for `lang`."""
    tools = []
    for tool in _TOOLS:
        properties = {
            key: ({**spec, "description": _pick(spec["description"], lang)}
                  if isinstance(spec.get("description"), dict) else spec)
            for key, spec in tool["input_schema"]["properties"].items()
        }
        tools.append({
            **tool,
            "description": _pick(tool["description"], lang),
            "input_schema": {**tool["input_schema"], "properties": properties},
        })
    return tools

_TRENDS = [
    "📈 销售额环比增长 12.3%，连续 3 个月上升，建议加大营销投入。",
    "📉 客户流失率从 5.2% 降至 3.8%，留存策略见效。",
    "📊 用户活跃度同比增长 23%，峰值出现在晚间 20:00-22:00。",
    "📈 客单价从 $42 提升至 $58，受促销活动影响显著。",
    "📉 退货率下降 1.5 个百分点，品控改善成果明显。",
]

_ANOMALIES = [
    "⚠️ 检测到 3 个异常点：订单 ID #8823 / #9012 / #9156 金额超出 3σ 范围，建议人工复核。",
    "⚠️ 用户 'wang_dev' 登录 IP 突然从上海跳变到境外，触发安全告警。",
    "✅ 数据分布正常，无显著异常值（p > 0.05）。",
    "⚠️ 系统响应延迟在 14:30-15:00 期间飙升到 8.2s（正常 < 1s），怀疑数据库慢查询。",
    "⚠️ 检测到异常退款模式：3 个账户在 10 分钟内发起 12 次退款请求。",
]

_REPORTS = [
    """📋 周报摘要（2026-W23）

核心指标：
· GMV: $128,450（+8.2% WoW）
· 订单量: 3,421（+5.1%）
· 新用户: 892（+12.7%）
· 复购率: 34.2%（+1.3pp）

亮点：新用户增长强劲，主要来自短视频渠道
风险：客服响应时长从 2.1min → 4.8min，需关注""",
    """📋 月报摘要（2026-05）

核心指标：
· 月 GMV: $542,000（+15.3% MoM）
· 月活用户: 28,400（+9.1%）
· 平均客单价: $55.80（+6.2%）
· 退货率: 4.1%（-0.8pp）

TOP 3 增长品类：智能家居(+32%)、运动户外(+28%)、美妆(+22%)
建议：增加客服团队应对增长，预计 Q3 咨询量翻倍""",
]

_TRENDS_EN = [
    "📈 Revenue is up 12.3% month over month, rising for 3 months straight — consider spending more on marketing.",
    "📉 Churn fell from 5.2% to 3.8%; the retention strategy is working.",
    "📊 User activity is up 23% year over year, peaking between 20:00 and 22:00.",
    "📈 Average order value rose from $42 to $58, driven largely by the promotion.",
    "📉 The return rate fell 1.5 percentage points — quality control is clearly paying off.",
]

_ANOMALIES_EN = [
    "⚠️ 3 outliers detected: orders #8823 / #9012 / #9156 fall outside 3σ on amount — manual review recommended.",
    "⚠️ User 'wang_dev' jumped from a Shanghai login IP to an overseas one, raising a security alert.",
    "✅ The distribution looks normal, with no significant outliers (p > 0.05).",
    "⚠️ Response latency spiked to 8.2s between 14:30 and 15:00 (normally < 1s) — a slow database query is the likely cause.",
    "⚠️ Unusual refund pattern: 3 accounts filed 12 refund requests within 10 minutes.",
]

_REPORTS_EN = [
    """📋 Weekly summary (2026-W23)

Key metrics:
· GMV: $128,450 (+8.2% WoW)
· Orders: 3,421 (+5.1%)
· New users: 892 (+12.7%)
· Repeat-purchase rate: 34.2% (+1.3pp)

Highlight: strong new-user growth, mostly from short-video channels
Risk: support response time went from 2.1min to 4.8min — worth watching""",
    """📋 Monthly summary (2026-05)

Key metrics:
· Monthly GMV: $542,000 (+15.3% MoM)
· Monthly active users: 28,400 (+9.1%)
· Average order value: $55.80 (+6.2%)
· Return rate: 4.1% (-0.8pp)

Top 3 growth categories: smart home (+32%), sports & outdoors (+28%), beauty (+22%)
Recommendation: grow the support team ahead of demand — enquiries are projected to double in Q3""",
]

_DATA = {
    "analyze_trend": {"zh": _TRENDS, "en": _TRENDS_EN},
    "detect_anomaly": {"zh": _ANOMALIES, "en": _ANOMALIES_EN},
    "generate_report": {"zh": _REPORTS, "en": _REPORTS_EN},
}


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"}), 200

    @app.post("/mcp/tools/list")
    def list_tools():
        return jsonify({"tools": _localized_tools(_request_lang())}), 200

    @app.post("/mcp/tools/call")
    def call_tool():
        body = request.get_json(silent=True) or {}
        name = body.get("name")
        args = body.get("arguments") or {}
        if name not in _DATA:
            return jsonify({"error": f"Unknown tool: {name!r}"}), 400
        items = _pick(_DATA[name], _request_lang(args))
        limit = args.get("limit")
        if isinstance(limit, int) and limit > 0:
            items = items[:limit]
        return jsonify({
            "name": name,
            "task_id": args.get("task_id"),
            "items": items,
            "total": len(items),
        }), 200

    _install_x402_gate(app)
    return app


def _install_x402_gate(app: Flask) -> bool:
    """Put `POST /mcp/tools/call` behind x402 when HIRENET_X402_GATE=1.

    Off by default, so the existing demo and test suite see this server exactly
    as before. The env check is repeated here (install_x402_gate checks it
    again, authoritatively) only so the `x402` import is not paid for — and
    cannot fail — on the default path.
    """
    if os.getenv("HIRENET_X402_GATE") != "1":
        return False
    from app.services.x402_gate import install_x402_gate

    return install_x402_gate(
        app,
        # Every tool this server serves belongs to the SkillAsset registered at
        # ASSET_ENDPOINT_URL; the creator's wallet is read from that row.
        tool_endpoints={name: ASSET_ENDPOINT_URL for name in _DATA},
    )


if __name__ == "__main__":
    # Run as a script sys.path[0] is THIS directory, so `import app.services...`
    # would fail once the gate is on. Put the repo root first, before create_app().
    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", 5003))
    print(f"[MCP] data_analysis running on http://localhost:{port}")
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)
