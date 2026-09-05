#!/usr/bin/env bash
# One-shot startup for a live demo of the distributed batch processing
# platform: minikube cluster, shared storage mount, worker image, backend,
# frontend. Sequences exactly the manual steps documented in README.md.
#
# Usage: ./scripts/start_demo.sh
# Stop with Ctrl+C - this kills the backend/frontend/mount processes it
# started, but leaves the minikube cluster itself running (slow to restart,
# and not something this script started).

set -euo pipefail
set -m # give each backgrounded command its own process group, so the
       # cleanup trap can kill a whole group (e.g. uvicorn's reload
       # subprocess, vite's child process) rather than just the shell wrapper.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/.demo-logs"
mkdir -p "$LOG_DIR"

PIDS=()

cleanup() {
  echo
  echo "Stopping demo processes..."
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] && kill -TERM "-$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

log() { echo "==> $*"; }

require() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "error: '$1' is required but not found on PATH" >&2
    exit 1
  fi
}

require minikube
require kubectl
require docker
require npm

# 1. Kubernetes cluster
if ! minikube status >/dev/null 2>&1; then
  log "Starting minikube..."
  minikube start --driver=docker
fi
log "Cluster nodes:"
kubectl get nodes

# 2. Shared storage mount (worker pods read/write backend/storage via this)
mkdir -p "$ROOT_DIR/backend/storage"
if ! pgrep -f "minikube mount $ROOT_DIR/backend/storage:/data" >/dev/null 2>&1; then
  log "Starting minikube mount (backend/storage -> /data)..."
  minikube mount "$ROOT_DIR/backend/storage:/data" >"$LOG_DIR/mount.log" 2>&1 &
  PIDS+=("$!")
  sleep 2
else
  log "minikube mount already running, reusing it."
fi

# 3. Worker image
log "Building worker image..."
docker build -t batch-worker:latest "$ROOT_DIR/worker"
log "Loading worker image into the cluster..."
minikube image load batch-worker:latest

# 4. Backend
log "Starting backend..."
cd "$ROOT_DIR/backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt
uvicorn app.main:app --reload --port 8000 >"$LOG_DIR/backend.log" 2>&1 &
PIDS+=("$!")
deactivate

log "Waiting for backend health check..."
for _ in $(seq 1 30); do
  if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if ! curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
  echo "error: backend did not become healthy - see $LOG_DIR/backend.log" >&2
  exit 1
fi

# 5. Frontend
log "Starting frontend..."
cd "$ROOT_DIR/frontend"
if [ ! -d node_modules ]; then
  npm install
fi
npm run dev -- --port 5173 >"$LOG_DIR/frontend.log" 2>&1 &
PIDS+=("$!")

cd "$ROOT_DIR"
echo
log "Demo is up:"
echo "    Backend:  http://localhost:8000/api/health"
echo "    Frontend: http://localhost:5173"
echo "    Logs:     $LOG_DIR/{backend,frontend,mount}.log"
echo "Press Ctrl+C to stop."
echo

tail -f "$LOG_DIR/backend.log" "$LOG_DIR/frontend.log"
