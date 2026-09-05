# Distributed batch processing system in the cloud (Thesis Project)

Cloud-native platform demonstrating distributed batch data processing using Docker containers and Kubernetes orchestration. See [thesis-project-context.md](thesis-project-context.md) for full scope.

## Stack
- **Frontend:** React (Vite) — `frontend/`
- **Backend:** FastAPI (Python) — `backend/`
- **Orchestration:** local Kubernetes via minikube (Docker driver)

## Quick start (demo script)

`scripts/start_demo.sh` automates everything below this section — cluster,
storage mount, worker image, backend, frontend — in one command:
```bash
./scripts/start_demo.sh
```
It builds/loads the worker image, starts minikube and the storage mount if
they aren't already running, waits for the backend's health check, then
tails the backend/frontend logs in your terminal. Open http://localhost:5173
once it prints "Demo is up".

**To stop it:** press `Ctrl+C` in the terminal it's running in. This stops
the backend, frontend, and `minikube mount` processes it started, but
deliberately leaves the minikube cluster itself running (it's slow to
restart, and the script didn't start it if it was already up) — run
`minikube stop` separately if you want to tear that down too.

Logs land in `.demo-logs/{backend,frontend,mount}.log` if you need to check
something after the terminal output has scrolled past.

The manual steps below are what the script automates — use them directly if
you want to run just one piece (e.g. only the frontend against an
already-running backend).

## Backend setup
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```
API available at http://localhost:8000, health check at `/api/health`.

## Frontend setup
```bash
cd frontend
npm install
npm run dev
```
App available at http://localhost:5173.

## Local Kubernetes cluster
```bash
minikube start --driver=docker
kubectl get nodes
```

### Shared storage mount (required for job execution)
Worker pods need to see the CSV chunks the backend writes to `backend/storage/`.
minikube's only live mount mechanism is a 9p filesystem bridge; start it and
leave it running in the background whenever you want to run jobs:
```bash
minikube mount backend/storage:/data
```
This must stay running for `POST /api/jobs/{id}/run` to work — worker pods
mount `/data` as a hostPath volume and read/write under it.

### Worker image
The worker container (`worker/`) is built on the host and imported into the
cluster's image store (minikube here runs containerd, not Docker, so
`docker-env` doesn't apply):
```bash
docker build -t batch-worker:latest worker/
minikube image load batch-worker:latest
```
Rebuild and reload after any change to `worker/main.py`.

## Testing

Two layers:

**Unit / API tests** (`backend/tests/`) — fast, no cluster required. Cover
the partitioner and aggregator directly, upload validation via the FastAPI
`TestClient`, and the job lifecycle (state transitions, the double-`/run`
race, cleanup) with the Kubernetes calls mocked out.
```bash
cd backend
source .venv/bin/activate
pip install -r requirements-dev.txt   # once
pytest
```

**Live end-to-end demonstration** (`backend/scripts/e2e_demo.py`) — exercises
the real stack: golden path (upload → run → Completed → download →
cleanup), a failure path (a chunk is deleted mid-flight, forcing a pod to
fail, verifying it resolves to `Failed` with cleanup still happening),
every upload-validation edge case, state-transition guards (re-running a
job, downloading before completion, unknown job ids), and concurrency
(the double-`/run` race, several jobs running at once). Requires the full
stack up (cluster, mount, worker image, backend):
```bash
cd backend
source .venv/bin/activate
python scripts/e2e_demo.py
```
Prints PASS/FAIL per check and exits non-zero if anything failed.

## Cleaning up jobs

A `Completed`/`Failed` job's Kubernetes Job/Pods and intermediate
`chunks/`/`results/` files are deleted automatically right after it
finishes. Its `input.csv`, `output.csv`, and database row are kept forever
(so `/result` keeps working), and a `Pending` job that was created but
never run is never cleaned up on its own — `backend/scripts/cleanup_jobs.py`
deletes all of that on demand:
```bash
cd backend
source .venv/bin/activate
python scripts/cleanup_jobs.py --dry-run          # preview, no changes
python scripts/cleanup_jobs.py                    # all Pending/Completed/Failed jobs, asks to confirm
python scripts/cleanup_jobs.py --job-id <id> -y    # one job, no prompt
```
It also re-attempts deleting the job's Kubernetes Job as a safety net (in
case the automatic cleanup failed), never touches `Running` jobs, and never
touches a job's `timings/` directory — `backend/scripts/worker_sweep.py`
reads those for benchmark analysis.

## Troubleshooting

**`POST /api/jobs/{id}/run` (or any job action) returns 503 "Could not
reach the Kubernetes cluster"** — the backend can talk to the API but the
cluster isn't there. Most common cause: `minikube stop` can leave
`~/.kube/config`'s `current-context` empty. Fix: `minikube start` (safe to
re-run; it also restores the kubeconfig entry), then `kubectl get nodes` to
confirm.

**Browser console shows a CORS error alongside a `500`** — this is almost
always a red herring: an unhandled backend exception produced a `500`
whose response didn't carry CORS headers, and the browser reports that as
a CORS failure instead of showing the real error. Check the backend's own
logs/terminal for the actual traceback rather than chasing CORS config.
