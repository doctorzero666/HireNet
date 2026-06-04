import jsonschema
from flask import Blueprint, current_app, jsonify, request

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
    # Phase 1 stub: creator identity comes from server config, not the request.
    # Real per-user authentication is deferred to Phase 2.
    creator_id = current_app.config["PHASE1_CREATOR_ID"]
    try:
        result = register_skill_asset(db_path, payload, creator_id)
    except KeyError as exc:
        return jsonify({"error": f"Missing required field: {exc}"}), 400
    except TypeError as exc:
        return jsonify({"error": f"Invalid field type: {exc}"}), 400
    except (jsonschema.ValidationError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(result), 201
