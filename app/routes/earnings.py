from flask import Blueprint, current_app, render_template, request

from app.storage.royalty_ledger import summarize_creator_earnings

earnings_bp = Blueprint("earnings", __name__)


@earnings_bp.route("/creator/earnings", methods=["GET"])
def creator_earnings():
    # Phase 1: creator_id is a freeform string. Explicit ?creator_id= wins;
    # default falls back to the Phase 1 stub creator (same convention as
    # app/routes/skills.py). Real per-user auth is deferred to Phase 2.
    creator_id = request.args.get("creator_id") or current_app.config["PHASE1_CREATOR_ID"]
    summary = summarize_creator_earnings(current_app.config["DATABASE_PATH"], creator_id)
    return render_template("creator_earnings.html", summary=summary)
