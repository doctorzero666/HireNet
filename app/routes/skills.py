import jsonschema
from flask import Blueprint, current_app, jsonify, request

from app.app import get_current_identity
from app.services.skill_registration import register_skill_asset

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
