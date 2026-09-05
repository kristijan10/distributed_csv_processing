# Thesis Implementation — Context for Evaluation

**Purpose of this document:** consolidated state-of-the-implementation brief for an agent evaluating this project against its thesis requirements. It complements — does not replace — [thesis-project-context.md](thesis-project-context.md), which is the original, professor-approved scope document. Read that first for *what was supposed to be built*; this document describes *what actually got built*, how, and what was found during testing.

---

## 1. Scope recap (see thesis-project-context.md for full detail)

**Topic:** Design and Implementation of a Cloud-Native Platform for Distributed Batch Processing Using Kubernetes.

**In scope (8 required capabilities):** CSV upload with configurable worker count; row-based partitioning; automatic Kubernetes Job/Pod creation; distributed execution of a (deliberately simple/generic) per-row processing task; status monitoring across Pending/Running/Completed/Failed; aggregation of partial results into one output; automatic cleanup of Jobs/Pods/temp files.

**Explicitly out of scope:** authentication, ZIP/multi-format input, per-job CPU/RAM configuration, and any Phase 2+ concept (plugin marketplace, scheduling, AI estimation, multi-cloud, SaaS verticals).

**Stack:** React (Vite) frontend, FastAPI backend, local Kubernetes via minikube (`docker` driver), SQLite for job metadata.

---

## 2. Implementation status: all 9 milestones complete

Built incrementally, one commit per milestone (`git log --oneline`):

```
4e0b041 Scaffold backend (FastAPI) and frontend (React/Vite) projects
f31347e Add CSV upload & job creation API
1b5bc30 Add CSV partitioner module
93f3031 Add Kubernetes Job orchestration and worker image
12e2d7b Add Kubernetes status reconciliation for Running jobs
743e43a Add result aggregation and download endpoint
4f81f3d Add automatic cleanup of Kubernetes Jobs and temporary files
c8f3ffd Build frontend: upload form, job status view, result download
89e5b9f Migrate frontend styling to Tailwind CSS
38e739f Fix edge cases found during systematic testing
1a2356d Fix CORS to allow any localhost port, not just 5173
0b02fd1 Add automated test suite and E2E demonstration script
```

Milestone 9 (testing/demonstration) is done: `backend/tests/` (pytest, 45 tests — partitioner/aggregator unit tests, upload-validation API tests, and job-lifecycle tests with Kubernetes mocked out, no cluster needed) plus `backend/scripts/e2e_demo.py` (a live demonstration script exercising the real stack — golden path, failure path, every validation edge case, state guards, concurrency). Verified 45/45 and 33/33 respectively. See §7 for what this replaced.

---

## 3. Architecture as built

```
React (Vite, Tailwind) ──HTTP──▶ FastAPI ──┬─▶ SQLite (job metadata)
   polls GET /api/jobs                      ├─▶ Kubernetes API (Job CRUD, via python client)
   every 3s                                 └─▶ local filesystem (backend/storage/)
                                                     │
                                          minikube mount (9p bridge)
                                                     │
                                          Kubernetes node (minikube, docker driver)
                                                     │
                                     1 Job (completionMode=Indexed) → N worker Pods
                                     each pod: reads its chunk, transforms rows,
                                     writes its partial result — all via a
                                     hostPath volume backed by the mount above
```

### Data flow per job
1. `POST /api/jobs` (multipart: CSV + `worker_count`) → validates, saves `storage/jobs/{id}/input.csv`, inserts a `Job` row with status `Pending`.
2. `POST /api/jobs/{id}/run` → partitions the CSV into `worker_count` chunk files, submits **one** Kubernetes `Job` object with `completions=parallelism=worker_count`, `completionMode: Indexed`, `backoffLimit: 0`. Status → `Running`.
3. Every subsequent `GET` (list or single) reconciles: if the job is `Running`, it reads the live K8s Job's `.status.conditions` — a `Failed` condition moves it to `Failed` (capturing the message); a `Complete` condition triggers aggregation (merge all `results/result_*.csv` into `output.csv`) and moves it to `Completed`.
4. Immediately after reaching `Completed`/`Failed`, cleanup runs: the K8s Job is deleted (`propagationPolicy=Background`, cascades to Pods), and the `chunks/`/`results/` directories are removed. `input.csv` and `output.csv` are kept.
5. `GET /api/jobs/{id}/result` streams `output.csv` as a download once `Completed`.

### Why these specific choices (not directly stated in the original scope doc)
- **Single Indexed Job instead of N separate Job/Pod specs.** Each pod gets `JOB_COMPLETION_INDEX` via the downward API (`metadata.annotations['batch.kubernetes.io/job-completion-index']`), which it uses to compute its own chunk/result filename (`chunk_{index:03d}.csv`). This maps directly onto "backend creates a Kubernetes Job with N worker Pods" from the spec without needing a ConfigMap or per-pod manifests.
- **hostPath + `minikube mount` for shared storage**, not a ConfigMap-and-logs approach. Considered and rejected the alternative of passing chunk data via ConfigMaps and reading results back from pod logs (avoids the mount dependency entirely) — rejected because it's a poorer fit for a thesis about K8s storage/orchestration primitives, and because `minikube mount` is the standard, driver-agnostic mechanism. Trade-off accepted: **the mount must be running (`minikube mount backend/storage:/data`) for any job execution to work**, and it's a separate long-lived process the user must keep alive.
- **Worker image built locally, imported via `minikube image load`.** `minikube docker-env` doesn't work here because this minikube profile runs the `containerd` runtime, not Docker, inside the node.
- **Status reconciliation is poll-on-read, not a background watcher.** Every `GET` on a `Running` job triggers a live K8s API check; there is no continuously-running watch/reconciliation loop. This matches the spec's "polls/watches ... and exposes it as a status endpoint" language and avoids background-task lifecycle complexity, at the cost of status only updating when *something* polls (the frontend's 3s interval is what actually drives it in practice).
- **`activeDeadlineSeconds` (300s default) on every Job.** Added after testing found that a Job whose pods never reach a terminal phase (e.g. `ImagePullBackOff`) has no path to a `Failed` condition otherwise — Kubernetes only fails a Job when `backoffLimit` is exceeded by actual pod failures, not by stuck/pending pods. Without this, such a job stays `Running` forever.

---

## 4. API surface

| Method | Path | Purpose | Key error responses |
|---|---|---|---|
| POST | `/api/jobs` | Upload CSV + `worker_count` (multipart) | 422: bad extension, empty/header-only/ragged CSV, worker_count out of bounds or > row count |
| GET | `/api/jobs` | List all jobs (reconciles Running ones first) | — |
| GET | `/api/jobs/{id}` | Get one job (reconciles if Running) | 404 |
| POST | `/api/jobs/{id}/run` | Partition + submit to Kubernetes | 404; 409 if not Pending (includes the double-submit race case) |
| GET | `/api/jobs/{id}/result` | Download aggregated CSV | 404; 409 if not Completed |
| GET | `/api/health` | Liveness | — |

## 5. Data model (`Job`, SQLite)

`id` (uuid4 hex) · `status` (Pending/Running/Completed/Failed) · `worker_count` · `row_count` · `original_filename` · `input_path` · `result_path` (nullable) · `error_message` (nullable) · `created_at` · `updated_at`.

## 6. Key config (`backend/app/core/config.py`, all overridable via env/`.env`)

`storage_dir=./storage` · `database_url=sqlite:///./app.db` · `max_workers_per_job=32` · `worker_image=batch-worker:latest` · `data_mount_path=/data` · `job_active_deadline_seconds=300` · `kube_namespace=default` · `kube_context=None` (uses current kubeconfig context, expected to be `minikube`).

---

## 7. Testing performed and bugs found

A systematic edge-case pass was run manually against the live stack first (full detail in the `38e739f` and `1a2356d` commit messages); the same coverage was then formalized into the checked-in suite described in §2 (`backend/tests/` + `backend/scripts/e2e_demo.py`), so these scenarios are now regression-tested rather than one-off. Summary of what was found:

**4 real bugs found and fixed:**
1. A Job whose pods never reach a terminal phase (bad image, unschedulable) stayed `Running` forever — fixed with `activeDeadlineSeconds`.
2. Concurrent double `POST /run` on the same job crashed the loser with an unhandled 500 (unhandled K8s 409 on duplicate Job name) — now a clean 409.
3. A UTF-8 BOM in an uploaded CSV silently corrupted the header field name — fixed via `utf-8-sig` decoding.
4. Ragged CSV rows (inconsistent column count vs. header) produced silently misaligned output — now rejected at upload time with a precise error, re-validated in the partitioner too.
5. CORS was hardcoded to `http://localhost:5173`; Vite's fallback ports (5174, ...) were blocked entirely — fixed with a regex allowing any localhost port.

**Confirmed correct (no fix needed):** non-CSV extension, empty file, header-only file, `worker_count` <1 / >32 / exceeding row count, missing/malformed multipart fields, quoted commas/embedded newlines in CSV fields, CRLF line endings, no trailing newline, duplicate header names, re-running an already-Completed/Failed/nonexistent job, a never-run Pending job (no crash on reconcile), 9 jobs executing concurrently without interference, and 32 workers (the configured ceiling) against a 40-row file.

## 8. Known limitations / things an evaluator should weigh

- **Operational fragility of the storage bridge:** `minikube mount` must be kept running as a separate background process for job execution to work at all; if it dies mid-job, in-flight pods will fail with `FileNotFoundError` (this exact failure mode was tested and confirmed to resolve to a clean `Failed` status, but the mount itself has no supervision/auto-restart).
- **`activeDeadlineSeconds` is a blunt instrument** — a genuinely slow-but-healthy job (e.g. a very large CSV on constrained hardware) would be force-failed at 300s with no distinction from a truly stuck job.
- **CSV content is otherwise unvalidated** — non-UTF-8 bytes are replaced (`errors="replace"`), and binary garbage with a `.csv` extension is accepted and "processed" (each garbage line becomes a "row"); this was a deliberate choice not to over-validate content, since the thesis's own framing states data-analysis correctness is not the focus.
- **No auth, single-writer SQLite** — matches explicit scope exclusion, but means job state has no per-user isolation (not required by scope).
- **Row-count-based validation ties worker_count ≤ row_count** — a design choice (each worker guaranteed ≥1 row) not explicitly mandated by the spec, worth noting as an interpretation.
- **`e2e_demo.py`'s failure-path test relies on direct filesystem access** to `backend/storage/` (to delete a chunk file mid-flight) rather than being purely black-box HTTP — reasonable for a script meant to run on the same machine as the stack, but worth noting it isn't a fully API-only test.

## 9. Current environment state (as of last session)

Everything is **stopped**: no backend/frontend dev servers running, `minikube mount` process killed, minikube cluster stopped (not deleted — `minikube start` restores it, worker image included, without re-doing setup). To resume: `minikube start` → `minikube mount backend/storage:/data` (background) → backend (`uvicorn app.main:app --reload` from `backend/` with venv active) → frontend (`npm run dev` from `frontend/`). Full instructions in [README.md](README.md).

The automated suite (`pytest`, no cluster needed) and the live E2E script (`python scripts/e2e_demo.py`, needs the full stack up) were both last run clean: 45/45 and 33/33 respectively.

## 10. I/O vs. compute isolation experiment

The thesis asserts the pipeline is I/O-bound (dominated by the `minikube mount` 9p bridge) rather than compute-bound. Two pieces of evidence back this up:

**Per-pod timing instrumentation.** `worker/main.py` records three `time.monotonic()` deltas around the read, transform, and write+fsync steps, and writes them to `storage/jobs/{job_id}/timings/timing_{worker_index:03d}.json` (a sibling of `chunks/`/`results/` that job cleanup never touches, so it survives past job completion). Schema: `{worker_index, rows, noop_transform, read_s, compute_s, write_s, total_s}`. This is the most direct evidence: it measures the actual split per pod, per job, rather than inferring it indirectly.

**No-op-transform worker-count sweep.** `backend/app/core/config.py`'s `noop_transform` setting (env var `NOOP_TRANSFORM`) is plumbed through `job_builder.py` into every worker pod. When set, `worker/main.py` skips its per-row step entirely (which today is a fixed `time.sleep(1)` placeholder, not real per-row work — see caveat below) and echoes the chunk back unchanged instead of appending `processed_by_worker`. `backend/scripts/worker_sweep.py` runs the same fixed dataset (`SWEEP_ROWS` rows, default 4000) across worker counts `[1, 2, 4, 8, 10, 12, 14, 16, 20, 24, 32]` and records wall-clock time plus the avg/max read/compute/write split, to `backend/scripts/sweep_results/{baseline,noop}_sweep.csv`.

Procedure:
1. Start the stack normally (`NOOP_TRANSFORM` unset) → `python scripts/worker_sweep.py --mode baseline`.
2. Restart the backend with `NOOP_TRANSFORM=1` → `python scripts/worker_sweep.py --mode noop`.
3. Compare the two CSVs: if the curve barely changes, I/O dominates; if it flattens substantially, compute was contributing more than assumed.

**Caveat:** the current "compute" step is a hardcoded `time.sleep(1)`, a fixed placeholder per the code's own comment ("the thesis focus is the orchestration model, not the processing logic itself"), not work that scales with chunk size. Removing it therefore shifts the wall-clock curve down by a roughly constant amount at every worker count, rather than by an amount proportional to data volume the way real per-row compute would. The no-op sweep is corroborating evidence; the timing instrumentation's `compute_s` numbers (which measure this same `sleep(1)`, directly) are the more defensible artifact to cite in the defense, precisely because they don't require interpreting a curve shift.

**Mount-process monitoring (manual, during the sweep's 24-worker point).** `worker_sweep.py` prints a banner and pauses for `SWEEP_WATCH_DELAY` seconds (default 5s) right before submitting the 24-worker job, to give a window to start:
- Host side (macOS): find the `minikube mount` process and sample it — `pgrep -f "minikube mount"` then `top -l 30 -s 2 -pid <pid> -stats pid,cpu,mem`.
- Inside the minikube VM: `minikube ssh -- vmstat 1 30`, watching `us`/`sy` (CPU busy) vs. `wa` (I/O wait) vs. `id` (idle). Check the VM's actual allocated CPU count first (`minikube config view`, or whatever `--cpus` was passed to `minikube start`) so "cores maxed" is judged against the real ceiling, not assumed to be 8.
- Interpretation: CPU well below saturated with non-trivial `wa` → confirms cores are idle waiting on I/O, not the bottleneck. CPU near-saturated → compute (or the mount process itself) is a bigger factor than assumed.

## 11. File structure (implementation only, excludes `node_modules`/`.venv`/`__pycache__`)

```
backend/app/
  main.py                  FastAPI app, CORS, router mounting, table creation
  core/config.py           Settings (env-overridable)
  core/db.py               SQLAlchemy engine/session
  models/job.py            Job ORM model + JobStatus enum
  schemas/job.py           Pydantic response schema
  api/jobs.py              All /api/jobs* endpoints
  services/job_service.py  Job lifecycle: create, run, reconcile, cleanup
  services/partitioner.py  partition_csv() - pure, decoupled
  services/aggregator.py   aggregate_csv() - pure, decoupled
  k8s/client.py            kubeconfig loading, API client factories
  k8s/job_builder.py       V1Job manifest construction (Indexed completion)
  k8s/orchestrator.py      submit/get/delete against the K8s API
backend/tests/             pytest suite (partitioner, aggregator, upload
                            validation, job lifecycle w/ K8s mocked)
backend/scripts/e2e_demo.py live demonstration script against the real cluster
worker/
  main.py                  Per-pod script: read chunk, transform, write result
  Dockerfile               python:3.12-slim, stdlib only
frontend/src/
  App.jsx                  Top-level layout, polling loop
  api.js                   fetch wrappers for the job endpoints
  components/UploadForm.jsx, JobList.jsx, StatusBadge.jsx, PipelineOverview.jsx
```
