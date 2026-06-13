"""
Phase 3 / U3 — settlement audit + reconciliation HTTP surface.

One read-only endpoint that joins both halves of U3 (audit trail + ledger
reconciliation) into a single response, so the demo UI / future admin
tooling can render a run's full lifecycle from one fetch instead of
chaining /royalty/status, /audit/run/:id, /royalty/split.

Auth: @login_required gates the endpoint behind a valid JWT — anonymous
callers get 401, same posture as /api/auth/me. Per-caller IDOR (only the
run's caller can view its audit) is still TODO and tracked with the
broader Phase 2 IDOR cleanup on the settlement surface; until then any
authenticated user can read any run's audit data, which is acceptable on
the dev network but MUST be tightened before this is exposed publicly.
"""
from flask import Blueprint, current_app, jsonify

from app.services.audit import get_audit_trail, reconcile
from app.services.auth import login_required

audit_bp = Blueprint("audit", __name__)


@audit_bp.route("/api/audit/run/<run_id>", methods=["GET"])
@login_required
def audit_run(run_id: str):
    """Return the run's audit trail + the chain-vs-ledger reconciliation.

    Body shape:
        {
          "run_id": <str>,
          "events": [                    # oldest first
            {
              "id": <uuid>,
              "event": "claim"|"submit"|"confirm"|"fail",
              "status_from": <str|None>,
              "status_to":   <str>,
              "method":      <str|None>,
              "tx_hash":     <str|None>,
              "error":       <str|None>,
              "created_at":  <ISO-8601>,
              "run_id":      <str>,
            },
            ...
          ],
          "reconcile": {
            "matched":        <bool>,
            "onchain_amount": <int>,
            "ledger_amount":  <int>,            # matching (currency,chain) bucket
            "currency":       <str|None>,
            "chain":          <str|None>,
            "groups": [                         # per (currency,chain) breakdown
                {"currency": <str>, "chain": <str|None>, "amount": <int>},
                ...
            ],
            "settlement_status": <str>,
            "tx_hash":           <str|None>,
            "run_id":            <str>,
          }
        }

    404 on unknown run_id — reconcile() raises LookupError which we map
    to a clean JSON error. (Catching here, not in the service, so the
    service stays Flask-free and reusable from a scheduled reconciler.)
    """
    db_path = current_app.config["DATABASE_PATH"]
    try:
        recon = reconcile(db_path, run_id)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    events = get_audit_trail(db_path, run_id)
    return jsonify({
        "run_id": run_id,
        "events": events,
        "reconcile": recon,
    })
