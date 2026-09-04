"""Demo MCP server: customer service script generator.

Standalone Flask app on :5002. Three tools, 120 lines of canned demo
scripts (presale 40 + after-sale 50 + complaint 30). Importable as a Python
module for tests; runnable as `python app/mcp_servers/customer_service.py`
for end-to-end demo.

Wire shape mirrors the MCP tool-call convention so the main backend can
talk to a real MCP server later without rewriting the client.
"""
from __future__ import annotations

import os

from flask import Flask, jsonify, request
from flask_cors import CORS

# The endpoint_url this server is registered under in `skill_assets`
# (app/services/demo_bootstrap.py: DEMO_SEO_AGENT). The x402 gate uses it to
# find which SkillAsset — and therefore which creator wallet — gets paid.
ASSET_ENDPOINT_URL = os.getenv("HIRENET_MCP_ENDPOINT_URL", "http://localhost:5002")


_GREETINGS = [
    "您好，欢迎光临！请问有什么可以帮您？",
    "亲，欢迎咨询，我是您的专属客服小助手~",
    "您好，今天想了解我们的哪款产品呢？",
    "欢迎光临本店！有任何问题随时告诉我哦。",
    "亲爱的顾客您好，我能为您做些什么？",
    "您好，感谢您的关注，请问有什么疑问？",
    "Hi~ 我是客服小诺，很高兴为您服务！",
    "欢迎咨询，请告诉我您的需求，我会立刻处理。",
    "您好，请问您是想了解产品功能还是价格？",
    "亲，欢迎光临！下单前有什么想确认的吗？",
    "您好，我们正在做活动，要不要了解一下？",
    "亲，您是回头客吗？有专属老客优惠哦~",
    "您好，新会员注册即送 50 元券，了解一下？",
    "欢迎光临，请告诉我您的预算，我帮您挑选。",
    "亲，看到您浏览了很久，有什么疑问可以问我。",
    "您好，本店所有商品支持 7 天无理由退换。",
    "亲爱的，请问您是第一次购买这款产品吗？",
    "您好，需要我为您介绍一下店铺爆款吗？",
    "亲，今天下单还能享受满 200 减 30 哦~",
    "您好，您看中的款式我们都有现货，可以发顺丰。",
    "欢迎光临，请稍等，我马上为您查询库存。",
    "您好，我们已为您预留商品 30 分钟。",
    "亲，加入购物车后立刻下单可锁定折扣价。",
    "您好，请问您希望发什么快递？",
    "亲，需要我帮您备注礼品包装吗？",
    "您好，咨询截止 23:59，今晚下单明早发货。",
    "亲爱的，这款是本月销量冠军，强烈推荐。",
    "您好，您关注的颜色今天补货了，要锁定吗？",
    "亲，这款赠品仅限今日，下单送同款替换装。",
    "您好，可以告诉我您的使用场景吗？我推荐合适的尺码。",
    "亲，店铺会员还能享受免邮特权哦~",
    "您好，请问您是想送礼还是自用？",
    "亲，您留意一下购物车，我已为您选好了优惠券。",
    "您好，今天直播间还有更低价，可以前往看看。",
    "亲，需要我帮您查询历史订单或物流吗？",
    "您好，本店承诺正品保障，假一赔十。",
    "亲，您可以先收藏，活动开始时我提醒您。",
    "您好，本套餐限时仅 198 元，原价 358 元。",
    "亲，需要我把详情链接发给您吗？",
    "您好，感谢光临，无论是否下单都欢迎多咨询。",
]

_FAQ = [
    "Q：发货时间多久？A：付款后 24 小时内发货，节假日除外。",
    "Q：支持哪些快递？A：默认顺丰，偏远地区中通。",
    "Q：如何退换货？A：7 天无理由，运费券补贴。",
    "Q：会员等级怎么算？A：累计消费 500 元升级银卡。",
    "Q：是否开发票？A：支持电子发票，下单备注即可。",
    "Q：付款方式？A：微信、支付宝、信用卡、花呗分期。",
    "Q：能否分期？A：支持 3/6/12 期免息（部分商品）。",
    "Q：尺码是否偏小？A：偏小一码，建议拍大一号。",
    "Q：是否支持改地址？A：发货前皆可修改。",
    "Q：是否包邮？A：满 99 包邮，偏远地区除外。",
    "Q：质保期多久？A：主体一年，配件三个月。",
    "Q：如何申请保修？A：联系客服上传订单号 + 视频。",
    "Q：是否有实体店？A：北京、上海、深圳均有体验店。",
    "Q：能否到店自提？A：支持，下单选择门店自提。",
    "Q：缺货怎么办？A：可预约补货，到货立即发出。",
    "Q：能否预定？A：预定需付 30% 定金。",
    "Q：积分如何使用？A：100 积分抵 1 元，下单时勾选。",
    "Q：优惠券能否叠加？A：满减券与折扣券可叠加。",
    "Q：怎么参加抽奖？A：下单后会自动获得抽奖券。",
    "Q：发现质量问题怎么办？A：拍照联系客服，先行赔付。",
    "Q：可以代发货吗？A：可以，下单时备注收件人即可。",
    "Q：礼盒包装收费吗？A：免费提供基础礼盒。",
    "Q：能否开企业发票？A：可以，提供税号即可。",
    "Q：购买后多久能收到？A：北上广深次日达。",
    "Q：可以同城配送吗？A：北京、上海支持闪送。",
    "Q：是否提供安装？A：上海地区可预约安装。",
    "Q：退货是否包邮？A：质量问题包邮，无理由由买家承担。",
    "Q：会员卡如何激活？A：下单后系统自动激活。",
    "Q：怎样查物流？A：登录账号 → 我的订单 → 物流跟踪。",
    "Q：商品断码怎么办？A：可加入心愿单，补货优先通知。",
    "Q：能否补开发票？A：可以，最长支持 90 天内补开。",
    "Q：会员日是哪天？A：每月 18 号会员日双倍积分。",
    "Q：积分是否过期？A：积分自获取起 12 个月内有效。",
    "Q：售后客服时间？A：每日 9:00-22:00。",
    "Q：是否提供试用？A：部分商品支持 30 天试用退款。",
    "Q：怎样成为分销商？A：累计购买 5000 元可申请。",
    "Q：能否定制商品？A：可定制刻字、礼盒、贺卡。",
    "Q：是否提供英文客服？A：工作日提供英文支持。",
    "Q：海外能否发货？A：港澳台、东南亚已开通。",
    "Q：怎么参加团购？A：发起 3 人成团享 8 折。",
    "Q：物流延迟怎么办？A：超 7 天未达可申请补偿券。",
    "Q：怎么参加新人活动？A：注册后 7 天内享新人专属价。",
    "Q：能否多件混发？A：同一订单最多拆 3 包。",
    "Q：是否支持货到付款？A：仅限部分地区。",
    "Q：套餐能否拆分？A：套餐价不可拆，建议单独下单。",
    "Q：拼团失败怎么办？A：自动原路退款，24 小时到账。",
    "Q：礼品卡能否退？A：未激活前 7 天内可退。",
    "Q：是否提供陪送服务？A：北京、上海可预约。",
    "Q：是否提供旧物回收？A：部分品类支持以旧换新。",
    "Q：会员有何特权？A：免邮、专属客服、生日礼。",
]

_COMPLAINTS = [
    "非常抱歉给您带来不便，我立刻为您核实问题，请稍等。",
    "您好，我已记录您的反馈，由专员在 30 分钟内回复。",
    "对此造成的困扰深表歉意，将立即为您启动售后流程。",
    "感谢您的耐心反馈，我们会立即改进相关流程。",
    "实在抱歉，请告知订单号，我立刻协调仓库为您处理。",
    "对不起，已为您升级为 VIP 加急通道，请稍候。",
    "您的反馈非常重要，已转交主管处理，预计 1 小时内回复。",
    "感谢您指出问题，我们已为您补偿 50 元无门槛券。",
    "非常理解您的心情，我会全程跟进直到问题解决。",
    "已为您发起退换货申请，预计 3 个工作日内完成。",
    "实在抱歉，质量问题我们承担运费，请放心退回。",
    "已为您预约售后上门服务，时间会短信通知。",
    "深表歉意，您的损失我们将先行赔付。",
    "已提交质检团队复核，结果将在 24 小时内同步。",
    "感谢提醒，我们立即下架问题批次商品。",
    "请您提供问题照片，我会在 10 分钟内给出处理方案。",
    "您好，店长亲自跟进您的诉求，请稍候。",
    "非常抱歉的同时，我们已为您准备额外补偿，请查收。",
    "已为您升级到优先处理队列，预计 30 分钟内回复。",
    "我们已记录该问题，正在与供应商沟通处理。",
    "非常感谢您的反馈，已为您升级为终身 VIP。",
    "对此次体验深表歉意，我们正在改进物流环节。",
    "已为您新发同款商品，请勿担心，原件无需寄回。",
    "请您提供具体细节，我们将在 1 小时内回复处理结果。",
    "感谢您给我们改进的机会，已加倍补偿并安排专人跟进。",
    "实在不好意思，已为您补发同款 + 赠送精美礼品。",
    "您好，已为您启动绿色通道，将在 24 小时内完成处理。",
    "对此次给您带来的困扰，我们诚挚道歉并承担全部责任。",
    "已为您升级为加急售后，将在 1 个工作日内完成。",
    "您的反馈对我们极为重要，问题已上报至质量委员会。",
]


_TOOLS = [
    {
        "name": "generate_greeting",
        "description": "生成客服欢迎语 / 售前话术。",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务 ID（用于去重 / 审计）"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 40},
            },
        },
    },
    {
        "name": "generate_faq",
        "description": "生成售后 / 常见问题话术。",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
        },
    },
    {
        "name": "generate_complaint_response",
        "description": "生成投诉回复话术。",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 30},
            },
        },
    },
]


_DATA = {
    "generate_greeting": _GREETINGS,
    "generate_faq": _FAQ,
    "generate_complaint_response": _COMPLAINTS,
}


def create_mcp_app() -> Flask:
    """Build the standalone MCP Flask app.

    Factored so tests can grab a `test_client()` without booting :5002.
    """
    app = Flask(__name__)
    CORS(app)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"}), 200

    @app.post("/mcp/tools/list")
    def list_tools():
        return jsonify({"tools": _TOOLS}), 200

    @app.post("/mcp/tools/call")
    def call_tool():
        body = request.get_json(silent=True) or {}
        name = body.get("name")
        args = body.get("arguments") or {}
        if name not in _DATA:
            return jsonify({"error": f"Unknown tool: {name!r}"}), 400

        items = _DATA[name]
        # caller may cap the size; default returns the full canned set so
        # downstream "total" reflects what the asset can actually produce.
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

    Off by default, so the existing demo and the 929-test suite see this server
    exactly as before. The env check is repeated here (install_x402_gate checks
    it again, authoritatively) only so the `x402` import is not paid for — and
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
    # Run as a script (`python app/mcp_servers/customer_service.py`, as start.sh
    # does) sys.path[0] is THIS directory, so `import app.services...` would fail
    # once the gate is on. Put the repo root first, before create_mcp_app() runs.
    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

app = create_mcp_app()


if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", 5002))
    print(f"[MCP] customer_service running on http://localhost:{port}")
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)
