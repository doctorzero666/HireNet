from flask import Blueprint, current_app, render_template

from app.storage.royalty_ledger import summarize_creator_earnings

earnings_bp = Blueprint("earnings", __name__)


@earnings_bp.route("/creator/earnings", methods=["GET"])
def creator_earnings():
    # Phase 1 stub: creator identity comes from server config, not the request.
    # Real per-user authentication is deferred to Phase 2.
    creator_id = current_app.config["PHASE1_CREATOR_ID"]
    summary = summarize_creator_earnings(current_app.config["DATABASE_PATH"], creator_id)
    return render_template("creator_earnings.html", summary=summary)
