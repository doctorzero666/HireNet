import os
from app.app import create_app

# ⚠️ Demo deployment constraint:
# app.app.pact_sessions is an in-memory, per-process dict (see comment there).
# Run this WSGI app with a SINGLE worker only — e.g. `gunicorn --workers 1` —
# and avoid restarts during the demo, otherwise pacts created on one worker
# will 404 on another and any restart wipes pending pacts entirely.
# Migrate pact_sessions to SQLite in Phase 2 to lift this restriction.
app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("APP_PORT", 3000)))
    print(f"HireNet running on http://localhost:{port}")
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)
