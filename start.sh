#!/usr/bin/env bash
# Demo launcher: backend (5001) + MCP server (5002) + Vite dev (5173).
#
# Port choice notes:
#   * APP_PORT=5001 — vite.config.js proxies /api → http://localhost:5001,
#     so the backend MUST listen on 5001 or the frontend can't reach it.
#     wsgi.py's default 3000 doesn't match; we override it here.
#   * MCP_PORT=5002 — the AgentRegister placeholder + demo wiring assume
#     this; change here and the placeholder together.
#
# Process lifecycle: backend + MCP run in the background; Vite runs in the
# foreground. Ctrl-C kills Vite, the EXIT trap then reaps the children so
# nothing leaks across runs.
set -euo pipefail

trap 'kill $(jobs -p) 2>/dev/null || true' EXIT

export APP_PORT="${APP_PORT:-5001}"
export MCP_PORT="${MCP_PORT:-5002}"

echo "[start] backend  → http://localhost:${APP_PORT}"
python wsgi.py &

echo "[start] MCP      → http://localhost:${MCP_PORT}"
python app/mcp_servers/customer_service.py &

echo "[start] frontend → http://localhost:5173 (vite, proxies /api → :${APP_PORT})"
cd frontend && npm run dev
