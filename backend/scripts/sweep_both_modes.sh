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
# Clears every *_sweep.csv already in sweep_results/ before sweeping, so a
# row_count whose input file you've since removed from sweep_input/ doesn't
# linger as a stale result (worker_sweep.py only overwrites files for a
# row_count it actually re-sweeps - it never deletes on its own).
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

# `minikube mount` can go stale without exiting - e.g. the laptop sleeps, the
# 9p session to the VM dies, but the host-side process keeps running and
# `ps` still shows it alive. That leaves /data readable-but-empty inside the
# cluster, so every worker pod fails immediately with a chunk-file-not-found
# error instead of anything mount-related. A process-liveness check can't
# catch this - only an actual write-then-read through the mount can - so
# round-trip a marker file through it before sweeping.
check_data_mount() {
  local marker="mount_check_$$"
  local token="ok-$$"
  mkdir -p "$BACKEND_DIR/storage"
  printf '%s' "$token" >"$BACKEND_DIR/storage/$marker"

  local output
  output=$(kubectl run "mount-check-$$" --rm -i --restart=Never --image=busybox --quiet \
    --overrides="{\"spec\":{\"containers\":[{\"name\":\"mount-check\",\"image\":\"busybox\",\"command\":[\"cat\",\"/data/$marker\"],\"volumeMounts\":[{\"name\":\"shared-storage\",\"mountPath\":\"/data\"}]}],\"volumes\":[{\"name\":\"shared-storage\",\"hostPath\":{\"path\":\"/data\",\"type\":\"Directory\"}}],\"restartPolicy\":\"Never\"}}" \
    2>&1) || true

  rm -f "$BACKEND_DIR/storage/$marker"
  [[ "$output" == *"$token"* ]]
}

if ! check_data_mount; then
  echo "error: the cluster's /data doesn't see backend/storage - the minikube mount bridge is down or stale." >&2
  echo "       Run (from backend/): minikube mount ./storage:/data   and keep it running, then retry." >&2
  exit 1
fi

cd "$BACKEND_DIR"
if [ ! -d .venv ]; then
  echo "error: backend/.venv not found - set it up first (see README.md's Backend setup)." >&2
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

RESULTS_DIR="${SWEEP_RESULTS_DIR:-$BACKEND_DIR/scripts/sweep_results}"
if [ -d "$RESULTS_DIR" ] && compgen -G "$RESULTS_DIR/*_sweep.csv" >/dev/null; then
  log "Clearing previous results in $RESULTS_DIR..."
  rm -f "$RESULTS_DIR"/*_sweep.csv
fi

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

# start_backend noop 1
# log "Sweeping noop..."
# python scripts/worker_sweep.py --mode noop
# stop_backend

log "Both sweeps complete - results in scripts/sweep_results/"
log "(No backend is running now - start one normally, e.g. via ../scripts/start_demo.sh, to use the app again.)"
