#!/usr/bin/env bash
# Runs scripts/worker_sweep.py in both --mode baseline and --mode noop back
# to back, restarting the backend with NOOP_TRANSFORM between the two runs -
# the one manual step worker_sweep.py's docstring otherwise requires. Useful
# for pulling both sets of sweep_results/ charts for the thesis in one go.
#
# This script owns the backend process for its duration: it starts it twice
# (plain, then with NOOP_TRANSFORM=1) and stops it when done or on Ctrl+C.
# It does NOT manage the cluster/mount/worker image - have those up first
# (see README.md), and make sure nothing is already listening on :8000.
#
# Usage: cd backend && scripts/sweep_both_modes.sh

set -euo pipefail
set -m # own process group per background job, so stop_backend can kill
       # uvicorn's whole group rather than just the shell wrapper.

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$BACKEND_DIR/../.demo-logs"
mkdir -p "$LOG_DIR"

BACKEND_PID=""

stop_backend() {
  if [ -n "$BACKEND_PID" ]; then
    kill -TERM "-$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
    BACKEND_PID=""
  fi
}
trap stop_backend EXIT INT TERM

log() { echo "==> $*"; }

if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
  echo "error: something is already answering on http://localhost:8000 - stop it first (this script starts and stops its own backend process)." >&2
  exit 1
fi

if ! kubectl get nodes >/dev/null 2>&1; then
  echo "error: kubectl can't reach a cluster - start minikube first (see README.md)." >&2
  exit 1
fi

cd "$BACKEND_DIR"
if [ ! -d .venv ]; then
  echo "error: backend/.venv not found - set it up first (see README.md's Backend setup)." >&2
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

start_backend() {
  local label="$1" noop="$2"
  log "Starting backend ($label)..."
  NOOP_TRANSFORM="$noop" uvicorn app.main:app --port 8000 >"$LOG_DIR/sweep-backend-$label.log" 2>&1 &
  BACKEND_PID=$!
  for _ in $(seq 1 30); do
    if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "error: backend ($label) did not become healthy - see $LOG_DIR/sweep-backend-$label.log" >&2
  exit 1
}

start_backend baseline 0
log "Sweeping baseline..."
python scripts/worker_sweep.py --mode baseline
stop_backend

start_backend noop 1
log "Sweeping noop..."
python scripts/worker_sweep.py --mode noop
stop_backend

log "Both sweeps complete - results in scripts/sweep_results/"
log "(No backend is running now - start one normally, e.g. via ../scripts/start_demo.sh, to use the app again.)"
