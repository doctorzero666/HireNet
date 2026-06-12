#!/usr/bin/env bash
# Demo launcher: backend (5001) + MCP server (5002) + Vite dev (5173).
# Anvil (8545) is launched only when HIRENET_SETTLEMENT_PROVIDER=anvil.
#
# Port choice notes:
#   * ANVIL_PORT=8545 — Foundry default; .env's ANVIL_RPC_URL points at it.
#     We sleep 2s after launch so web3 has a node to dial when backend boots.
#   * APP_PORT=5001 — vite.config.js proxies /api → http://localhost:5001,
#     so the backend MUST listen on 5001 or the frontend can't reach it.
#     wsgi.py's default 3000 doesn't match; we override it here.
#   * MCP_PORT=5002 — the AgentRegister placeholder + demo wiring assume
#     this; change here and the placeholder together.
#
# Process lifecycle: backend + MCP (and optionally anvil) run in the
# background; Vite runs in the foreground. Ctrl-C kills Vite, the EXIT
# trap then reaps the children so nothing leaks across runs. Anvil logs
# go to a file because its block-mined chatter would otherwise drown out
# vite's dev output.
set -euo pipefail

trap 'kill $(jobs -p) 2>/dev/null || true' EXIT

export APP_PORT="${APP_PORT:-5001}"
export MCP_PORT="${MCP_PORT:-5002}"
export ANVIL_PORT="${ANVIL_PORT:-8545}"

# Only boot anvil when the backend is configured to use it. Other providers
# (mock / cobo) don't need a local chain, and an unconditional `anvil`
# launch would noisily fail on hosts that don't have Foundry installed.
if [ "${HIRENET_SETTLEMENT_PROVIDER:-mock}" = "anvil" ]; then
    if ! command -v anvil >/dev/null 2>&1; then
        echo "[start] ⚠️  anvil not found on PATH — install Foundry (curl -L https://foundry.paradigm.xyz | bash && foundryup) or unset HIRENET_SETTLEMENT_PROVIDER=anvil to fall back to mock."
        exit 1
    fi
    echo "[start] anvil    → http://localhost:${ANVIL_PORT} (logs: /tmp/hirenet-anvil.log)"
    anvil --port "${ANVIL_PORT}" > /tmp/hirenet-anvil.log 2>&1 &
    sleep 2
else
    echo "[start] anvil    → skipped (HIRENET_SETTLEMENT_PROVIDER=${HIRENET_SETTLEMENT_PROVIDER:-mock})"
fi

echo "[start] backend  → http://localhost:${APP_PORT}"
python wsgi.py &

echo "[start] MCP      → http://localhost:${MCP_PORT}"
python app/mcp_servers/customer_service.py &

echo "[start] frontend → http://localhost:5173 (vite, proxies /api → :${APP_PORT})"
cd frontend && npm run dev
