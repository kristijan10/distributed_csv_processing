# Distributed Batch Processing Platform (Thesis Project)

Cloud-native platform demonstrating distributed batch data processing using Docker containers and Kubernetes orchestration. See [thesis-project-context.md](thesis-project-context.md) for full scope.

## Stack
- **Frontend:** React (Vite) — `frontend/`
- **Backend:** FastAPI (Python) — `backend/`
- **Orchestration:** local Kubernetes via minikube (Docker driver)

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
