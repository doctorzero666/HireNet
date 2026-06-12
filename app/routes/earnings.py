from flask import Blueprint, current_app, jsonify, render_template

from app.app import get_current_identity
from app.storage.royalty_ledger import summarize_creator_earnings

earnings_bp = Blueprint("earnings", __name__)


@earnings_bp.route("/creator/earnings", methods=["GET"])
def creator_earnings():
    # Demo: creator identity comes from the X-Demo-Identity header / cookie
    # via get_current_identity(). When no demo identity is set, falls back
    # to PHASE1_CREATOR_ID — the historical Phase 1 stub. Real per-user
    # authentication is deferred to Phase 2; the IDOR guard from U5 still
    # applies — callers cannot spoof a different creator id via query param.
    creator_id = get_current_identity(
        default_id=current_app.config["PHASE1_CREATOR_ID"]
    )["id"]
    summary = summarize_creator_earnings(current_app.config["DATABASE_PATH"], creator_id)
    return render_template("creator_earnings.html", summary=summary)


@earnings_bp.route("/api/creator/earnings", methods=["GET"])
def creator_earnings_json():
    # Same identity rule as the HTML route: demo identity wins, PHASE1_CREATOR_ID
    # is the fallback, request query params ignored (Phase 1 IDOR guard, retained).
    creator_id = get_current_identity(
        default_id=current_app.config["PHASE1_CREATOR_ID"]
    )["id"]
    summary = summarize_creator_earnings(current_app.config["DATABASE_PATH"], creator_id)
    return jsonify(summary)
