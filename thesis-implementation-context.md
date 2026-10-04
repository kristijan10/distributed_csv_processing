# Thesis Implementation — Context for Evaluation

**Purpose of this document:** consolidated state-of-the-implementation brief for an agent evaluating this project against its thesis requirements, or drafting the thesis paper itself. It complements — does not replace — [thesis-project-context.md](thesis-project-context.md), which is the original, professor-approved scope document. Read that first for *what was supposed to be built*; this document describes *what actually got built*, how, what was found during testing, and — in §10 — the benchmarking experiment and the metrics it produces. Refreshed 2026-09-08 against the code as of commit `26575a8`; see [AGENT_CONTEXT.md](AGENT_CONTEXT.md) for a shorter, engineering-oriented version of the same state.

---

## 1. Scope recap (see thesis-project-context.md for full detail)

**Topic:** Design and Implementation of a Cloud-Native Platform for Distributed Batch Processing Using Kubernetes.

**In scope (8 required capabilities):** CSV upload with configurable worker count; row-based partitioning; automatic Kubernetes Job/Pod creation; distributed execution of a (deliberately simple/generic) per-row processing task; status monitoring across Pending/Running/Completed/Failed; aggregation of partial results into one output; automatic cleanup of Jobs/Pods/temp files.

**Explicitly out of scope:** authentication, ZIP/multi-format input, per-job CPU/RAM configuration, and any Phase 2+ concept (plugin marketplace, scheduling, AI estimation, multi-cloud, SaaS verticals).

**Stack:** React (Vite) frontend, FastAPI backend, local Kubernetes via minikube (`docker` driver), SQLite for job metadata.

---

## 2. Implementation status: all 9 original milestones complete, plus a later benchmarking phase

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

Milestone 9 (testing/demonstration) established the automated suite; it has since grown well past the original 45 tests as later work (watcher, batched reconciliation, sweep/metrics) added its own coverage — see [AGENT_CONTEXT.md](AGENT_CONTEXT.md)'s Testing table for the current count and per-file breakdown (82 tests across 7 files as of this pass) rather than re-deriving it here, since that table is kept current on every session.

After the milestone list above, a second, unlisted phase of commits (not individually enumerated here — see `git log --oneline` for the full history) added: watch-based push reconciliation alongside the original poll path, a proportional per-job deadline, streaming partitioning, per-job queue/execution-time/throughput tracking, and the worker-count sweep benchmarking system (§10) culminating in commit `26575a8`. §3, §5, §6, §8, and §10 below describe the system as it stands after that phase, not just the original 9 milestones.

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
3. Status reconciliation is dual-path (see below): a background watcher reacts to K8s Job events immediately, and every subsequent `GET` (list or single) also reconciles as a fallback — if the job is `Running`, it reads the live K8s Job's `.status.conditions` — a `Failed` condition moves it to `Failed` (capturing the message); a `Complete` condition triggers aggregation (merge all `results/result_*.csv` into `output.csv`) and moves it to `Completed`.
4. Immediately after reaching `Completed`/`Failed`, cleanup runs: the K8s Job is deleted (`propagationPolicy=Background`, cascades to Pods), and the `chunks/`/`results/` directories are removed. `input.csv` and `output.csv` are kept.
5. `GET /api/jobs/{id}/result` streams `output.csv` as a download once `Completed`.

### Why these specific choices (not directly stated in the original scope doc)
- **Single Indexed Job instead of N separate Job/Pod specs.** Each pod gets `JOB_COMPLETION_INDEX` via the downward API (`metadata.annotations['batch.kubernetes.io/job-completion-index']`), which it uses to compute its own chunk/result filename (`chunk_{index:03d}.csv`). This maps directly onto "backend creates a Kubernetes Job with N worker Pods" from the spec without needing a ConfigMap or per-pod manifests.
- **hostPath + `minikube mount` for shared storage**, not a ConfigMap-and-logs approach. Considered and rejected the alternative of passing chunk data via ConfigMaps and reading results back from pod logs (avoids the mount dependency entirely) — rejected because it's a poorer fit for a thesis about K8s storage/orchestration primitives, and because `minikube mount` is the standard, driver-agnostic mechanism. Trade-off accepted: **the mount must be running (`minikube mount backend/storage:/data`) for any job execution to work**, and it's a separate long-lived process the user must keep alive.
- **Worker image built locally, imported via `minikube image load`.** `minikube docker-env` doesn't work here because this minikube profile runs the `containerd` runtime, not Docker, inside the node.
- **Status reconciliation is dual-path: a background watcher plus poll-on-read as a fallback.** `k8s/watcher.py` runs a background `asyncio` task (started in `main.py`'s lifespan) that opens a `kubernetes.watch.Watch()` stream over our Jobs (label-selected, reconnecting on drop/error) and pushes each event straight into `job_service.reconcile_from_k8s_job` — so status updates as soon as Kubernetes reports them, not only when something happens to poll. This replaced an earlier poll-only design: a pure watch isn't sufficient on its own because a watch connection only sees events from the moment it opens (e.g. a backend restart misses everything that finished while it was down), so every `GET /api/jobs` / `GET /api/jobs/{id}` still reconciles Running jobs as a fallback (`reconcile_jobs_batch` does this as **one** `list_namespaced_job` call for all Running jobs, not one per job). Both paths funnel through the same `apply_k8s_job_status`, serialized by a per-job `threading.Lock` (`job_service._lock_for`) so a watch event racing a poll — or two overlapping frontend polls — can't double-aggregate or double-cleanup the same job.
- **`activeDeadlineSeconds`, scaled per job rather than a flat constant.** Originally a flat 300s (see below for why a deadline exists at all), later changed to `job_deadline_base_seconds` (60) + `job_deadline_seconds_per_row` (0.5) × ceil(rows_per_worker) (`k8s/job_builder.py::_active_deadline_seconds`), because a flat deadline force-fails a large-but-healthy job at the same threshold as a genuinely stuck tiny one — scaling it with how much work each worker actually has lets a large job run longer while still failing a stuck small job fast. Still a blunt instrument in the sense that it's a fixed formula rather than derived from observed throughput — see §8's "what would remove each limitation" for the natural next step.
  - *Why a deadline exists at all:* testing found that a Job whose pods never reach a terminal phase (e.g. `ImagePullBackOff`) has no path to a `Failed` condition otherwise — Kubernetes only fails a Job when `backoffLimit` is exceeded by actual pod failures, not by stuck/pending pods. Without any deadline, such a job stays `Running` forever.

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

`id` (uuid4 hex) · `status` (Pending/Running/Completed/Failed) · `worker_count` · `row_count` · `original_filename` · `input_path` · `result_path` (nullable) · `error_message` (nullable) · `worker_snapshot` (JSON, nullable — per-worker pod statuses captured just before cleanup deletes the pods, so the detail view still has something to show after termination) · `created_at` · `updated_at` · `started_at` (nullable — set when the job moves to Running; together with `created_at`/`finished_at` this splits what used to be one "duration" into `queue_time_s` and `execution_time_s`, see §10) · `finished_at` (nullable).

## 6. Key config (`backend/app/core/config.py`, all overridable via env/`.env`)

`storage_dir=./storage` · `database_url=sqlite:///./app.db` · `max_workers_per_job=32` · `worker_image=batch-worker:latest` · `data_mount_path=/data` · `job_deadline_base_seconds=60` / `job_deadline_seconds_per_row=0.5` (replaced the old flat `job_active_deadline_seconds=300`, see §3) · `kube_namespace=default` · `kube_context=None` (uses current kubeconfig context, expected to be `minikube`) · `noop_transform=False` (worker benchmark switch, see §10) · `compute_fixed_s=0.3` / `compute_per_row_s=0.000001` (simulated per-row worker compute cost, see §10) · `sweep_results_dir=./scripts/sweep_results`.

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

- **Operational fragility of the storage bridge:** `minikube mount` must be kept running as a separate background process for job execution to work at all; if it dies mid-job, in-flight pods will fail with `FileNotFoundError` (this exact failure mode was tested and confirmed to resolve to a clean `Failed` status, but the mount itself has no supervision/auto-restart). Worth noting the mount can go **stale without exiting** — the host process keeps running (so a naive liveness check passes) while the underlying 9p session to the VM is dead, leaving `/data` readable-but-empty inside the cluster; `backend/scripts/sweep_both_modes.sh` had to add an explicit check for this (round-trips a marker file through the mount via a throwaway `busybox` pod) before starting a benchmark run, since process-liveness alone can't catch it.
- **`activeDeadlineSeconds` is still a blunt instrument, just a less blunt one.** It now scales with rows-per-worker instead of being a flat constant (§3), so a large-but-healthy job gets more time than a small one — but the scaling formula is a fixed constant (`job_deadline_seconds_per_row=0.5`), not derived from how fast the system actually processes rows, so it can still misjudge a job running on unusually slow hardware or an unusually large one on fast hardware.
- **CSV content is otherwise unvalidated** — non-UTF-8 bytes are replaced (`errors="replace"`), and binary garbage with a `.csv` extension is accepted and "processed" (each garbage line becomes a "row"); this was a deliberate choice not to over-validate content, since the thesis's own framing states data-analysis correctness is not the focus.
- **No auth, single-writer SQLite** — matches explicit scope exclusion, but means job state has no per-user isolation (not required by scope), and rules out multiple backend instances writing concurrently.
- **Row-count-based validation ties worker_count ≤ row_count** — a design choice (each worker guaranteed ≥1 row) not explicitly mandated by the spec, worth noting as an interpretation.
- **`e2e_demo.py`'s failure-path test relies on direct filesystem access** to `backend/storage/` (to delete a chunk file mid-flight) rather than being purely black-box HTTP — reasonable for a script meant to run on the same machine as the stack, but worth noting it isn't a fully API-only test.
- **No pod retries** — `backoff_limit=0` on every Job, so a single transient pod failure (e.g. a flaky image pull) fails the whole job rather than retrying just that chunk.
- **Single-machine / minikube only** — no real multi-node cluster, no cloud deployment; storage is a local hostPath bind-mount, not network-attached storage.
- **Simulated, not real, compute** — the worker's "processing" is a `time.sleep()` formula (§10), not actual per-row computation, by deliberate scope choice (the thesis is about the orchestration model, not data-analysis logic).
- **No frontend test runner** — the React app (including the polling-pause logic in `App.jsx` and the chart components) is verified only via `vite build` + `oxlint`, not automated browser/unit tests.
- **`k8s/orchestrator.list_k8s_jobs` has no direct test** against a mocked kubernetes client — it's covered only indirectly, through `job_service.reconcile_jobs_batch` tests that mock `list_k8s_jobs` itself rather than the client call underneath it.

### What would remove each limitation

A future iteration (beyond current thesis scope) could address each of the above:

- **Mount fragility** → a supervised/auto-restarting mount process, or drop `hostPath` + `minikube mount` entirely in favor of a CSI-backed PersistentVolume or object storage, removing the 9p dependency altogether.
- **Deadline still a fixed formula** → derive the per-row constant from observed throughput (e.g. from sweep baseline data, §10) instead of a hardcoded `0.5`, or recompute it periodically as the system's actual processing rate is measured.
- **No pod retries** → allow a bounded `backoff_limit` for transient failures (e.g. image pull errors) while keeping chunk assignment deterministic via the completion index, so a retried pod reprocesses the same chunk rather than a different one.
- **Single-machine / minikube only** → run against a real multi-node cluster (a multi-node `kind` cluster, or a managed K8s service) to exercise actual network-attached storage and cross-node scheduling, which a single-node local cluster can't meaningfully test.
- **SQLite single-writer, no migrations** → move to Postgres + a real migration tool (e.g. Alembic) if multiple backend instances or concurrent writers become relevant.
- **No frontend test runner** → add one (e.g. Vitest) targeting `App.jsx`'s polling-pause/resume logic and the chart components, which currently have no regression coverage beyond a successful build.
- **`list_k8s_jobs` untested against a mocked client** → add a direct unit test for it (parallel to how `list_worker_pods` or the other orchestrator functions are tested), rather than relying on it being exercised transitively.
- **Simulated compute** → replace `worker/main.py`'s `time.sleep()` formula with actual per-row computation if a future iteration wants to validate the architecture against a real workload rather than an orchestration-focused proxy for one.

## 9. Current environment state (as of last session)

Everything is **stopped**: no backend/frontend dev servers running, `minikube mount` process killed, minikube cluster stopped (not deleted — `minikube start` restores it, worker image included, without re-doing setup). To resume: `minikube start` → `minikube mount backend/storage:/data` (background) → backend (`uvicorn app.main:app --reload` from `backend/` with venv active) → frontend (`npm run dev` from `frontend/`). Full instructions in [README.md](README.md).

The automated suite (`pytest`, no cluster needed) and the live E2E script (`python scripts/e2e_demo.py`, needs the full stack up) were both clean when last run: the suite has since grown to 82 tests (see [AGENT_CONTEXT.md](AGENT_CONTEXT.md)'s Testing table for the current per-file breakdown), and the E2E script was last verified 33/33 as of milestone 9.

## 10. I/O vs. compute isolation experiment

The thesis asserts the pipeline is I/O-bound (dominated by the `minikube mount` 9p bridge) rather than compute-bound, and separately asks how wall-clock execution time scales with worker count. The worker-count sweep benchmark tests both.

**Per-pod timing instrumentation.** `worker/main.py` records three `time.monotonic()` deltas around the read, transform, and write+fsync steps, and writes them to `storage/jobs/{job_id}/timings/timing_{worker_index:03d}.json` (a sibling of `chunks/`/`results/` that job cleanup never touches, so it survives past job completion). Schema: `{worker_index, rows, noop_transform, read_s, compute_s, write_s, total_s}`. This is the most direct evidence: it measures the actual split per pod, per job, rather than inferring it indirectly.

**Compute cost model.** The simulated "processing" step is `time.sleep(compute_fixed_s + compute_per_row_s * rows_in_chunk)`, defaults `compute_fixed_s=0.3`, `compute_per_row_s=0.000001` (both env-overridable via `COMPUTE_FIXED_S`/`COMPUTE_PER_ROW_S`, plumbed through `job_builder.py`; see `worker/main.py` and `core/config.py`). This replaced an earlier fixed `time.sleep(1)` placeholder in commit `26575a8` — the old flat-sleep model meant compute time per pod never shrank as `worker_count` grew (only I/O did, since chunks got smaller), which biased the sweep by keeping a compute floor that never moved regardless of parallelism. The fixed+per-row model shrinks genuinely as chunks get smaller, producing a real parallelism-vs-overhead trade-off instead of that artificial floor — this is a **methodology fix**, not just a refactor, and resolves the caveat this section used to carry about the old model undermining the experiment's validity.

**No-op-transform worker-count sweep.** `backend/app/core/config.py`'s `noop_transform` setting (env var `NOOP_TRANSFORM`) is plumbed through `job_builder.py` into every worker pod. When set, `worker/main.py` skips its per-row compute step entirely and echoes the chunk back unchanged instead of appending `processed_by_worker`. `backend/scripts/worker_sweep.py`:
- Discovers every `*.csv` dropped into `backend/scripts/sweep_input/` (gitignored — populated manually with real files, e.g. 100,000-row and 10,000,000-row CSVs), sorted smallest-first.
- For each input file, sweeps a fixed worker-count list: `WORKER_COUNTS = [1, 2, 4, 8, 10, 12, 14, 16, 20, 24, 32]`.
- For each `(input file, worker_count)` pair: uploads via `POST /api/jobs`, submits via `POST /api/jobs/{id}/run`, polls `GET /api/jobs/{id}` (1s interval, 180s timeout) until terminal, timing wall-clock from submit to terminal status; reads back each pod's timing JSON and computes avg/min/max of `read_s`/`compute_s`/`write_s` across workers.
- Writes one CSV per input file to `backend/scripts/sweep_results/{mode}_{row_count}_sweep.csv` (columns: `worker_count, row_count, wall_s, avg_read_s, avg_compute_s, avg_write_s, max_read_s, max_compute_s, max_write_s`). `--mode {baseline,noop}` only labels the output filename — it does not itself toggle `NOOP_TRANSFORM`; that still requires restarting the backend with the env var set. Each `(mode, row_count, worker_count)` combination runs exactly once per sweep invocation (no built-in repeated trials at the script level; the Jobs-tab chart, below, separately averages repeated *manual* runs through the UI).

`backend/scripts/sweep_both_modes.sh` automates the two-mode procedure: verifies nothing is already on port 8000 and the cluster/mount are reachable and live (see §8's mount-staleness note), clears stale `*_sweep.csv` files, starts the backend, runs `worker_sweep.py --mode baseline`, stops the backend — and would do the same for `--mode noop` with `NOOP_TRANSFORM=1`, except that half is **currently commented out** in the script. So as of this pass, only the baseline sweep is automated end-to-end; a noop run still needs the manual two-terminal procedure below. This is a gap in the automation, not in the underlying methodology.

Manual procedure (documented in `README.md`'s "Benchmarking / worker-count sweep" section):
1. Start the stack normally (`NOOP_TRANSFORM` unset) → `python scripts/worker_sweep.py --mode baseline`.
2. Restart the backend with `NOOP_TRANSFORM=1` → `python scripts/worker_sweep.py --mode noop`.
3. Compare the two CSVs for the same row count: if the wall-clock curve barely changes between modes, I/O dominates; if it flattens substantially in noop mode, compute was contributing more than assumed.

**Metrics used.** Three layers, each computed and surfaced differently:

| Metric | Computed from | Where computed | Where shown |
|---|---|---|---|
| `read_s`, `compute_s`, `write_s`, `total_s` | `time.monotonic()` deltas per pod | `worker/main.py`, written to `timing_{index}.json` | aggregated (avg/max) into the sweep CSV by `worker_sweep.py` |
| `wall_s` | submit→terminal wall-clock time per sweep point | `worker_sweep.py` | `sweep_results/{mode}_{row_count}_sweep.csv` |
| `speedup` | `wall_s(worker_count=1) / wall_s` | `backend/app/services/metrics_service.py::read_sweep` | `GET /api/metrics/sweep` → frontend Metrics tab (Speedup chart) |
| `efficiency` | `speedup / worker_count` | same | same (Efficiency chart, with a y=1 "ideal linear scaling" reference line) |
| `ideal_speedup` | `worker_count` (i.e. the linear-scaling reference value) | same | same |
| `throughput_rows_per_s` (sweep) | `row_count / wall_s` | same | same (Throughput chart) |
| `queue_time_s` | `started_at − created_at` | `backend/app/schemas/job.py::JobRead` | Jobs tab (per-job) |
| `execution_time_s` | `finished_at − started_at` | same | Jobs tab (per-job), and `JobDurationChart` (execution time by worker count, averaged over repeated completed runs at the same worker count for a given row count — real organic job data, corroborating the sweep script's results rather than duplicating them) |
| `throughput_rows_per_s` (per-job) | `row_count / execution_time_s` | same | Jobs tab (per-job) |

API surface for the sweep-derived metrics: `GET /api/metrics/sweep/runs` lists every available `(mode, row_count)` pair found in `sweep_results/`; `GET /api/metrics/sweep?mode=&row_count=` returns the full `SweepPoint` series for one run (404 if that file doesn't exist, 422 if it exists but has no `worker_count=1` row to key `speedup` off of). The frontend's `MetricsPanel` (Metrics tab) fetches every available run and overlays them all as separate colored series on the same four charts, labeled e.g. "Baseline · 1,000,000 rows" / "No-op transform (I/O only) · 1,000,000 rows" — so different dataset sizes and modes are directly comparable rather than viewed one at a time.

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
  schemas/job.py           Pydantic response schema (JobRead: queue/execution
                            time, throughput)
  schemas/metrics.py       SweepRun/SweepPoint response schemas
  api/jobs.py              All /api/jobs* endpoints
  api/metrics.py           /api/metrics/sweep(/runs) endpoints
  services/job_service.py  Job lifecycle: create, run, reconcile, cleanup
  services/partitioner.py  partition_csv() - pure, decoupled
  services/aggregator.py   aggregate_csv() - pure, decoupled
  services/metrics_service.py  reads sweep_results/*.csv, derives
                            speedup/efficiency/throughput
  k8s/client.py            kubeconfig loading, API client factories
  k8s/job_builder.py       V1Job manifest construction (Indexed completion)
  k8s/orchestrator.py      submit/get/delete against the K8s API
  k8s/watcher.py           background watch task, push reconciliation
backend/tests/             pytest suite (partitioner, aggregator, upload
                            validation, job lifecycle, watcher w/ K8s mocked)
backend/scripts/
  e2e_demo.py              live demonstration script against the real cluster
  worker_sweep.py          worker-count sweep benchmark driver
  sweep_both_modes.sh      automates baseline (+ noop, currently disabled)
                            sweep runs back-to-back
  cleanup_jobs.py          on-demand cleanup of finished/never-run jobs
worker/
  main.py                  Per-pod script: read chunk, transform (fixed+
                            per-row simulated cost), write result + timing
  Dockerfile               python:3.12-slim, stdlib only
frontend/src/
  App.jsx                  Top-level layout, polling loop, Jobs/Metrics tabs
  api.js                   fetch wrappers for the job + metrics endpoints
  components/UploadForm.jsx, JobList.jsx, JobDetailModal.jsx, StatusBadge.jsx,
             PipelineOverview.jsx, JobDurationChart.jsx, MetricsPanel.jsx
  utils/format.js, chartSeries.js
```
