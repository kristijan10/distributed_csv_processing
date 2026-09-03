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
