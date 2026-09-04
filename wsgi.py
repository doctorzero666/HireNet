import os
from app.app import create_app

# ⚠️ Demo deployment constraint:
# app.app still keeps analysis_sessions / career_sessions / published_jobs /
# user_profile_state in in-memory, per-process dicts (see comments there).
# Run this WSGI app with a SINGLE worker only — e.g. `gunicorn --workers 1` —
# and avoid restarts during the demo, otherwise an analysis started on one
# worker will 404 on another and any restart wipes that state entirely.
# Pacts no longer impose this: Stage 2 / WP-G moved them to SQLite (table
# `pacts`), so they survive restarts and are shared across workers.
app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("APP_PORT", 3000)))
    print(f"HireNet running on http://localhost:{port}")
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)
