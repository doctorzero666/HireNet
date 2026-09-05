"""Demo MCP server: customer service script generator.

Standalone Flask app on :5002. Three tools, 120 lines of canned demo
scripts (presale 40 + after-sale 50 + complaint 30) in EACH language.
Importable as a Python module for tests; runnable as
`python app/mcp_servers/customer_service.py` for end-to-end demo.

Wire shape mirrors the MCP tool-call convention so the main backend can
talk to a real MCP server later without rewriting the client.

WP-I18N-2 / D-F — language selection
────────────────────────────────────
This is the most visible Chinese left in an English demo: `pact_settle` calls
one of these tools and `ExecutionPage.jsx` renders the returned items verbatim
as the "Agent Output Preview" — the climax of the pact-settle flow. So each
canned set has an English twin, chosen by an optional `lang`:

  * `POST /mcp/tools/call` — `arguments.lang`, or `?lang=` on the URL;
  * `POST /mcp/tools/list` — `?lang=`.

Absent (every existing caller) means Chinese, and the Chinese lists below are
byte-identical to what they were. `_pick` is four lines rather than an import
of `app.agents.lang_support` on purpose: this file is a STANDALONE Flask app
that is also run as a script, where `app.*` is not importable until the
`sys.path` fix-up at the bottom has run.
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


#: Same 40 / 50 / 30 scripts, written for an English-speaking shop. A
#: translation of the demo content, not a different demo: the offers, numbers
#: and policies match line for line, so the two sets stay comparable.
_GREETINGS_EN = [
    "Hello and welcome! How can I help you today?",
    "Hi there, thanks for reaching out — I'm your personal support assistant~",
    "Hello! Which of our products would you like to hear about today?",
    "Welcome to our store! Just tell me any time if you have a question.",
    "Hello dear customer, what can I do for you?",
    "Hello, thanks for following us — do you have any questions?",
    "Hi~ I'm Nora from support, happy to help!",
    "Thanks for getting in touch — tell me what you need and I'll handle it right away.",
    "Hello, are you looking for product features or for pricing?",
    "Hi, welcome! Anything you'd like to confirm before you order?",
    "Hello, we have a promotion running — would you like to hear about it?",
    "Hi, are you a returning customer? There's a loyalty discount for you~",
    "Hello, new members get a 50 yuan voucher on sign-up — shall I tell you more?",
    "Welcome! Tell me your budget and I'll help you pick.",
    "Hi, I noticed you've been browsing a while — ask me anything.",
    "Hello, every item in our store comes with 7-day no-questions-asked returns.",
    "Hi there, is this your first time buying this product?",
    "Hello, would you like me to walk you through our best sellers?",
    "Hi, order today and you still get 30 off when you spend 200~",
    "Hello, the style you're looking at is in stock and can ship by SF Express.",
    "Welcome — one moment, I'll check stock for you right away.",
    "Hello, we've held the item for you for 30 minutes.",
    "Hi, add it to your cart and check out now to lock in the discounted price.",
    "Hello, which courier would you like us to use?",
    "Hi, would you like me to add a gift-wrap note?",
    "Hello, support is open until 23:59 — order tonight and it ships tomorrow morning.",
    "Hi there, this one is our best seller this month — highly recommended.",
    "Hello, the colour you were watching is back in stock today — shall I reserve it?",
    "Hi, today only: order this one and get a refill of the same item free.",
    "Hello, could you tell me how you'll use it? I'll recommend the right size.",
    "Hi, store members get free shipping as well~",
    "Hello, is this a gift or for yourself?",
    "Hi, take a look in your cart — I've already picked out a coupon for you.",
    "Hello, today's livestream has an even lower price — worth a look.",
    "Hi, would you like me to look up your past orders or your tracking?",
    "Hello, we guarantee authenticity — ten times your money back if it isn't genuine.",
    "Hi, save it for now and I'll remind you when the promotion starts.",
    "Hello, this bundle is 198 yuan for a limited time, down from 358.",
    "Hi, would you like me to send you the details link?",
    "Hello and thanks for visiting — do ask, whether or not you order.",
]

_FAQ_EN = [
    "Q: How soon do you ship? A: Within 24 hours of payment, public holidays excepted.",
    "Q: Which couriers do you use? A: SF Express by default, ZTO for remote areas.",
    "Q: How do I return or exchange? A: 7 days, no reason needed, with a voucher towards postage.",
    "Q: How are member tiers calculated? A: Spend 500 yuan in total to reach Silver.",
    "Q: Do you issue invoices? A: Yes, e-invoices — just add a note to your order.",
    "Q: What payment methods do you take? A: WeChat Pay, Alipay, credit card, Huabei instalments.",
    "Q: Can I pay in instalments? A: Yes — 3/6/12 months interest-free on selected items.",
    "Q: Do the sizes run small? A: One size small; we suggest ordering a size up.",
    "Q: Can I change the delivery address? A: Any time before it ships.",
    "Q: Is shipping free? A: Free over 99 yuan, remote areas excepted.",
    "Q: How long is the warranty? A: One year on the main unit, three months on accessories.",
    "Q: How do I claim warranty? A: Contact support with your order number and a video.",
    "Q: Do you have physical stores? A: Experience stores in Beijing, Shanghai and Shenzhen.",
    "Q: Can I collect in store? A: Yes — choose in-store pickup at checkout.",
    "Q: What if it's out of stock? A: Reserve a restock and we ship the moment it arrives.",
    "Q: Can I pre-order? A: Yes, with a 30% deposit.",
    "Q: How do I use points? A: 100 points is worth 1 yuan — tick the box at checkout.",
    "Q: Can coupons be combined? A: Spend-and-save coupons stack with discount coupons.",
    "Q: How do I enter the prize draw? A: You get an entry automatically when you order.",
    "Q: What if there's a quality problem? A: Send a photo to support and we compensate you first.",
    "Q: Can you drop-ship? A: Yes — just note the recipient when you order.",
    "Q: Is gift wrapping charged? A: Basic gift boxes are free.",
    "Q: Can I get a business invoice? A: Yes, just give us your tax number.",
    "Q: How fast is delivery? A: Next-day in Beijing, Shanghai, Guangzhou and Shenzhen.",
    "Q: Do you do same-city delivery? A: Instant courier is available in Beijing and Shanghai.",
    "Q: Do you offer installation? A: Installation can be booked in the Shanghai area.",
    "Q: Who pays return postage? A: We do for quality issues; the buyer does for change of mind.",
    "Q: How do I activate my membership card? A: It activates automatically after your order.",
    "Q: How do I track my parcel? A: Log in → My Orders → Track shipment.",
    "Q: What if my size is sold out? A: Add it to your wishlist for first notice on restock.",
    "Q: Can I request an invoice later? A: Yes, up to 90 days after purchase.",
    "Q: When is member day? A: The 18th of every month — double points.",
    "Q: Do points expire? A: Points are valid for 12 months from the date earned.",
    "Q: What are the support hours? A: 9:00-22:00, every day.",
    "Q: Is there a trial? A: Selected items come with a 30-day money-back trial.",
    "Q: How do I become a reseller? A: Apply once your total purchases reach 5000 yuan.",
    "Q: Can items be customised? A: Engraving, gift boxes and greeting cards are available.",
    "Q: Is there English-language support? A: Yes, on weekdays.",
    "Q: Do you ship overseas? A: Hong Kong, Macau, Taiwan and Southeast Asia are open.",
    "Q: How does group buying work? A: Start a group of 3 and everyone gets 20% off.",
    "Q: What if delivery is late? A: Not arrived after 7 days? Claim a compensation voucher.",
    "Q: How do I get the new-customer offer? A: New-customer pricing applies for 7 days after sign-up.",
    "Q: Can one order ship in several parcels? A: One order can be split into at most 3 parcels.",
    "Q: Is cash on delivery available? A: In selected areas only.",
    "Q: Can a bundle be split? A: Bundle pricing can't be split — order the items separately.",
    "Q: What if the group buy doesn't fill? A: Automatic refund to the original method within 24 hours.",
    "Q: Can gift cards be refunded? A: Yes, within 7 days while still unactivated.",
    "Q: Do you offer accompanied delivery? A: Bookable in Beijing and Shanghai.",
    "Q: Do you take trade-ins? A: Trade-in is supported for some categories.",
    "Q: What do members get? A: Free shipping, a dedicated agent and a birthday gift.",
]

_COMPLAINTS_EN = [
    "I'm very sorry for the trouble. Let me verify this for you right away — one moment.",
    "Hello, I've logged your feedback; a specialist will reply within 30 minutes.",
    "My sincere apologies for the disruption; I'm starting the after-sales process now.",
    "Thank you for the patient feedback — we'll fix the process straight away.",
    "I'm really sorry. Send me the order number and I'll coordinate with the warehouse at once.",
    "I'm sorry — I've moved you into the VIP priority queue, please hold.",
    "Your feedback matters. It's with a supervisor now, with a reply expected within the hour.",
    "Thank you for flagging this — we've credited you a 50 yuan voucher with no minimum spend.",
    "I completely understand how you feel; I'll stay on this until it is resolved.",
    "I've opened a return/exchange request for you; it should complete within 3 working days.",
    "I'm very sorry — we cover the postage on quality issues, so please do send it back.",
    "I've booked an on-site service visit for you; you'll get the time by text.",
    "My sincere apologies — we'll compensate your loss up front.",
    "It's with the QC team for review; you'll hear the outcome within 24 hours.",
    "Thanks for the heads-up — we're pulling the affected batch from sale immediately.",
    "Please send a photo of the problem and I'll come back with a plan within 10 minutes.",
    "Hello, the store manager is handling your case personally — please hold.",
    "Again, I'm very sorry; extra compensation has been prepared for you, please check.",
    "You've been moved into the priority queue; expect a reply within 30 minutes.",
    "We've logged the issue and are working through it with the supplier.",
    "Thank you very much for the feedback — we've upgraded you to lifetime VIP.",
    "I'm sorry about this experience; we're fixing the logistics step right now.",
    "A replacement of the same item is on its way — and no need to send the original back.",
    "Please share the specifics and we'll come back with an outcome within the hour.",
    "Thank you for the chance to put this right — compensation doubled, and an agent assigned.",
    "I'm truly sorry — we've reshipped the same item and added a gift.",
    "Hello, I've opened a fast-track case; it will be resolved within 24 hours.",
    "We sincerely apologise for the trouble caused, and we take full responsibility.",
    "Your case is now expedited after-sales and will be closed within 1 working day.",
    "Your feedback matters a great deal; the issue has been raised with the quality committee.",
]


#: `{"zh": ..., "en": ...}` -> the requested side. Local rather than imported
#: from `app.agents.lang_support` — see the module docstring.
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
        "name": "generate_greeting",
        "description": {
            "zh": "生成客服欢迎语 / 售前话术。",
            "en": "Generate customer-service greetings and pre-sales scripts.",
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": {
                        "zh": "任务 ID（用于去重 / 审计）",
                        "en": "Task ID (used for de-duplication / audit)",
                    },
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 40},
                "lang": {"type": "string", "enum": ["zh", "en"]},
            },
        },
    },
    {
        "name": "generate_faq",
        "description": {
            "zh": "生成售后 / 常见问题话术。",
            "en": "Generate after-sales and FAQ scripts.",
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                "lang": {"type": "string", "enum": ["zh", "en"]},
            },
        },
    },
    {
        "name": "generate_complaint_response",
        "description": {
            "zh": "生成投诉回复话术。",
            "en": "Generate complaint-response scripts.",
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 30},
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


_DATA = {
    "generate_greeting": {"zh": _GREETINGS, "en": _GREETINGS_EN},
    "generate_faq": {"zh": _FAQ, "en": _FAQ_EN},
    "generate_complaint_response": {"zh": _COMPLAINTS, "en": _COMPLAINTS_EN},
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
        return jsonify({"tools": _localized_tools(_request_lang())}), 200

    @app.post("/mcp/tools/call")
    def call_tool():
        body = request.get_json(silent=True) or {}
        name = body.get("name")
        args = body.get("arguments") or {}
        if name not in _DATA:
            return jsonify({"error": f"Unknown tool: {name!r}"}), 400

        items = _pick(_DATA[name], _request_lang(args))
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
