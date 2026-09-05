import jsonschema
from flask import Blueprint, current_app, jsonify, request

from app.agents.lang_support import pick, resolve_request_lang
from app.app import (
    DEMO_IDENTITIES,
    asset_display_field,
    get_current_identity,
    user_display_name,
)
from app.services.skill_registration import register_skill_asset
from app.storage.agent_runs import count_runs_by_asset
from app.storage.skill_assets import list_skill_assets
from app.storage.users import get_user

skills_bp = Blueprint("skills", __name__)


@skills_bp.route("/api/skills/register", methods=["POST"])
def register_skill():
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "Request body must be JSON"}), 400
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object, not an array or primitive"}), 400

    db_path = current_app.config["DATABASE_PATH"]
    # Demo: creator identity resolves through get_current_identity() so the
    # active Demo user is the one credited as the asset creator. Falls back
    # to PHASE1_CREATOR_ID for legacy callers without a demo identity. Real
    # per-user auth is deferred to Phase 2.
    creator_id = get_current_identity(
        default_id=current_app.config["PHASE1_CREATOR_ID"]
    )["id"]
    try:
        result = register_skill_asset(db_path, payload, creator_id)
    except KeyError as exc:
        return jsonify({"error": f"Missing required field: {exc}"}), 400
    except TypeError as exc:
        return jsonify({"error": f"Invalid field type: {exc}"}), 400
    except (jsonschema.ValidationError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(result), 201


def _resolve_creator_name(
    db_path: str, creator_id: str, cache: dict[str, str], lang: str | None = None
) -> str:
    """Best-effort creator display name. Falls back to creator_id when unknown.

    Lookup order: in-request cache → DEMO_IDENTITIES (Demo identities don't
    necessarily have a users row) → users table → raw id. Cache is mutated so
    one /api/skills/list call reads each user/identity at most once — it is
    per-request, so caching a language-specific name is safe.
    """
    if creator_id in cache:
        return cache[creator_id]
    demo = DEMO_IDENTITIES.get(creator_id)
    if demo is not None:
        cache[creator_id] = pick(demo["name"], lang)
        return cache[creator_id]
    row = get_user(db_path, creator_id)
    name = user_display_name(row, lang) if row is not None else creator_id
    cache[creator_id] = name
    return name


@skills_bp.route("/api/skills/list", methods=["GET"])
def list_skills():
    """Public Agent World index — every registered SkillAsset + per-asset call count.

    Only exposes display-safe fields: id, name, description, type, creator_id,
    creator_name, price_amount / currency, mcp_endpoint (renamed from
    endpoint_url for frontend semantics), call_count, created_at. Internals
    like split_rule, content_hash, io_schema, price_chain stay server-side —
    nothing on the index page needs them, and exposing the split rule would
    leak the creator's commercial terms.
    """
    db_path = current_app.config["DATABASE_PATH"]
    lang = resolve_request_lang(request)
    assets = list_skill_assets(db_path)
    counts = count_runs_by_asset(db_path)
    name_cache: dict[str, str] = {}
    skills = [
        {
            "id": asset["id"],
            # WP-I18N-2 / D-C: the English side lives in the nullable
            # name_en / description_en columns; NULL falls back to the
            # original text, so an asset registered by a user is unaffected.
            "name": asset_display_field(asset, "name", lang),
            "description": asset_display_field(asset, "description", lang),
            "type": asset["type"],
            "creator_id": asset["creator_id"],
            "creator_name": _resolve_creator_name(db_path, asset["creator_id"], name_cache, lang),
            "price_amount": asset["price_amount"],
            "price_currency": asset["price_currency"],
            "mcp_endpoint": asset.get("endpoint_url"),
            "call_count": counts.get(asset["id"], 0),
            "created_at": asset["created_at"],
        }
        for asset in assets
    ]
    return jsonify({"skills": skills})
