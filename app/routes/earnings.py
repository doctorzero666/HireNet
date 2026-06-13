from flask import Blueprint, current_app, jsonify, render_template

from app.app import get_current_identity
from app.storage.royalty_ledger import (
    list_creator_ledger,
    summarize_creator_earnings,
)

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


@earnings_bp.route("/api/creator/ledger", methods=["GET"])
def creator_ledger_json():
    """Per-run ledger feed for the creator earnings page.

    Same identity rule as /api/creator/earnings — the caller's resolved
    identity is the creator filter, query params are ignored so a Demo user
    cannot read another creator's rows (IDOR guard, retained from Phase 1).

    Returns { creator_id, entries: [...], settled_totals, accrued_totals }.
    """
    db_path = current_app.config["DATABASE_PATH"]
    creator_id = get_current_identity(
        default_id=current_app.config["PHASE1_CREATOR_ID"]
    )["id"]
    entries = list_creator_ledger(db_path, creator_id)

    # Group settled / accrued totals so the metric cards render without a
    # second pass over `entries` on the client.
    settled_buckets: dict[tuple[str, str | None], int] = {}
    accrued_buckets: dict[tuple[str, str | None], int] = {}
    for e in entries:
        key = (e["currency"], e["chain"])
        bucket = settled_buckets if e["status"] == "settled" else accrued_buckets
        bucket[key] = bucket.get(key, 0) + e["amount"]

    def _flatten(buckets):
        return [
            {"currency": c, "chain": ch, "amount": amt}
            for (c, ch), amt in buckets.items()
        ]

    return jsonify({
        "creator_id": creator_id,
        "entries": entries,
        "settled_totals": _flatten(settled_buckets),
        "accrued_totals": _flatten(accrued_buckets),
    })
