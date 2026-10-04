# Agent context: distributed batch processing platform

Handoff doc for another agent picking up this repo. Describes what's implemented, how it's tested, and where things live. For the narrative/thesis framing (why decisions were made, what was tested manually against a live cluster), see `thesis-project-context.md` and `thesis-implementation-context.md` — this file is the current, code-verified state, kept shorter and agent-oriented.

## What the system does

Upload a CSV → split it into `worker_count` chunks → run one Kubernetes `Job` with `worker_count` Indexed pods, each processing one chunk → reconcile the Job's status back into a SQLite-backed job record → aggregate per-worker results into one output CSV → serve it for download. A React frontend polls/display job state.

## Architecture / file map

**Backend** (`backend/app/`, FastAPI + SQLAlchemy + kubernetes-client, Python 3.11):
- `main.py` — app + CORS setup; `lifespan` starts/stops the background watch task (see below).
- `api/jobs.py` — REST endpoints (`POST /api/jobs`, `POST /api/jobs/{id}/run`, `GET /api/jobs`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/workers`, `GET /api/jobs/{id}/result`, `GET /api/health`).
- `api/metrics.py` — `GET /api/metrics/sweep/runs` (lists available `(mode, row_count)` sweep result pairs), `GET /api/metrics/sweep?mode=&row_count=` (derived per-worker-count metrics for one sweep run; 404 if missing, 422 if no `worker_count=1` baseline row to key speedup off of).
- `models/job.py` — `Job` SQLAlchemy model (`id`, `status` enum Pending/Running/Completed/Failed, `worker_count`, `row_count`, `original_filename`, `input_path`, `result_path`, `error_message`, `worker_snapshot` JSON, timestamps incl. `started_at`).
- `schemas/job.py` — Pydantic `JobRead`/`WorkerStatus` response models; `JobRead` also computes `queue_time_s` (created→started), `execution_time_s` (started→finished), `throughput_rows_per_s` (row_count/execution_time_s).
- `schemas/metrics.py` — `SweepRun{mode, row_count}`, `SweepPoint{worker_count, row_count, wall_s, avg/max_read_s, avg/max_compute_s, avg/max_write_s, speedup, efficiency, ideal_speedup, throughput_rows_per_s}`.
- `services/metrics_service.py` — reads `scripts/sweep_results/{mode}_{row_count}_sweep.csv` files, derives `speedup = wall_s(worker_count=1) / wall_s`, `efficiency = speedup / worker_count`, `ideal_speedup = worker_count`, `throughput_rows_per_s = row_count / wall_s`.
- `core/config.py` — `Settings` (pydantic-settings, env/`.env`-overridable): `storage_dir`, `database_url`, `max_workers_per_job`, `worker_image`, `data_mount_path`, `kube_namespace`, `kube_context`, `job_deadline_base_seconds`, `job_deadline_seconds_per_row`, `noop_transform`, `compute_fixed_s`, `compute_per_row_s`, `sweep_results_dir`.
- `core/db.py` — SQLAlchemy engine/session setup; `sync_sqlite_schema` diffs each mapped table's columns against `PRAGMA table_info` and `ALTER TABLE ADD COLUMN`s whatever's missing (SQLite-only; other backends are a no-op), so a stale local `app.db` from before a column was added to a model self-heals on next startup instead of raising `sqlite3.OperationalError`. Raises instead of altering if a new column is `NOT NULL` with no default (unsafe to backfill blindly). Called from `main.py` right after `create_all`.
- `services/job_service.py` — the core orchestration logic: `create_job`, `run_job`, `partition_job`, `aggregate_job`, `cleanup_job`, `reconcile_status` (single job), `reconcile_jobs_batch` (list of jobs, one K8s call), `reconcile_from_k8s_job` (watch-event entry point), `apply_k8s_job_status` (shared terminal-state transition logic used by both the poll and watch paths), `get_job_workers`.
- `services/partitioner.py` — `partition_csv`: splits an input CSV into per-worker chunk files, streaming.
- `services/aggregator.py` — `aggregate_csv`: streams per-worker result files into one output CSV.
- `k8s/job_builder.py` — builds the `V1Job` manifest (Indexed completion mode, hostPath volume, per-pod deadline calculation). Owns the shared labels/selector constants (`JOB_ID_LABEL`, `JOB_LABEL_SELECTOR`).
- `k8s/orchestrator.py` — thin wrapper over the kubernetes client: `submit_job`, `get_k8s_job`, `list_k8s_jobs` (batched), `list_worker_pods`, `delete_k8s_job`. Raises `KubernetesUnavailableError` (cluster unreachable) vs letting normal 404s through as `None`.
- `k8s/watcher.py` — background `asyncio` task (started in `main.py`'s lifespan) that runs `kubernetes.watch.Watch()` over our Jobs (label-selected) on a worker thread, reconnecting on drop/error, and pushes each event into `job_service.reconcile_from_k8s_job`.
- `k8s/client.py` — kubeconfig loading + cached `batch_v1_api()`/`core_v1_api()` clients.

**Worker** (`worker/main.py`): standalone script run inside each pod. Reads `JOB_ID`/`JOB_COMPLETION_INDEX`/`DATA_ROOT`/`NOOP_TRANSFORM`/`COMPUTE_FIXED_S`/`COMPUTE_PER_ROW_S` from env, reads its chunk, does a per-row transform costed as `sleep(compute_fixed_s + compute_per_row_s * rows_in_chunk)` (or echoes the chunk back unchanged in `NOOP_TRANSFORM` mode, used for I/O-vs-compute benchmarking), writes its result + a timing JSON (`read_s`/`compute_s`/`write_s`/`total_s`), fsyncs (required because storage is a `minikube mount` 9p bridge).

**Frontend** (`frontend/src/`, React + Vite + Tailwind + Recharts):
- `App.jsx` — top-level state, polls `GET /api/jobs`, two-tab nav (Jobs / Metrics).
- `api.js` — fetch wrappers for the backend REST API, incl. `getSweepRuns`/`getSweepMetrics`.
- `components/UploadForm.jsx`, `JobList.jsx`, `JobDetailModal.jsx` (per-worker pod status, itself polling `GET /api/jobs/{id}/workers` every 3s while open), `StatusBadge.jsx`, `PipelineOverview.jsx` (static 5-step diagram).
- `components/JobDurationChart.jsx` — Jobs-tab chart: execution time by worker count, grouped by `row_count`, averaged across repeated completed runs at the same worker count (real job data, not sweep-script data).
- `components/MetricsPanel.jsx` — Metrics-tab: fetches every available sweep run and overlays them all (one series per `(mode, row_count)`) across four charts — Speedup, Efficiency (with an ideal-linear-scaling reference line at y=1), Wall-clock time, Throughput.
- `utils/format.js` — duration/time formatting helpers.
- `utils/chartSeries.js` — shared chart helpers: fixed categorical color palette, `mergeByWorkerCount` (pivots per-series point arrays into one array keyed by `worker_count` for Recharts).

**Scripts** (`backend/scripts/`):
- `e2e_demo.py` — black-box smoke test against a *real* running backend + minikube cluster (not part of the pytest suite).
- `worker_sweep.py` — worker-count sweep benchmark: for every CSV in `sweep_input/`, sweeps worker counts `[1,2,4,8,10,12,14,16,20,24,32]`, uploads/runs/polls each via the real HTTP API, aggregates per-pod timing JSONs, writes `sweep_results/{mode}_{row_count}_sweep.csv`. `--mode {baseline,noop}` only labels the output file — actually toggling `noop` requires restarting the backend with `NOOP_TRANSFORM=1`.
- `sweep_both_modes.sh` — runs `worker_sweep.py --mode baseline` (the `--mode noop` half is present but currently commented out), restarting the backend with the right env between modes; checks the minikube mount is actually live (round-trips a marker file through a throwaway pod, since a dead 9p session doesn't show up as a dead process) before sweeping.
- `cleanup_jobs.py` — deletes finished/never-run jobs' DB rows, files, and any leftover K8s Job as a safety net; never touches `timings/`, so sweep data survives.

## Request flow (current implementation)

1. `POST /api/jobs` — validates extension/row structure, counts rows once (`row_count` persisted on the `Job`), saves `storage/jobs/{id}/input.csv`, status `Pending`.
2. `POST /api/jobs/{id}/run` — `partition_csv` streams `input.csv` into `worker_count` chunk files (single pass, using the already-known `row_count`); submits one Indexed `V1Job` (`completions=parallelism=worker_count`, `backoffLimit=0`, `activeDeadlineSeconds` computed per-job — see below). Status → `Running`.
3. Status reconciliation is **dual-path**, both funneling into `apply_k8s_job_status` under a per-job lock (`services/job_service.py`'s `_lock_for`) so a race can't double-aggregate/double-cleanup:
   - **Push**: `k8s/watcher.py`'s background watch stream reacts to Job events immediately.
   - **Pull (fallback)**: any `GET /api/jobs` or `GET /api/jobs/{id}` also reconciles Running jobs — needed because a watch connection only sees events from when it opened (e.g. right after a backend restart, a job that already finished). `GET /api/jobs` (list) does this as **one** `list_namespaced_job` call for all Running jobs (`reconcile_jobs_batch`), not one call per job.
4. On `Complete`: per-worker pod status snapshotted (for the detail view, since pods get deleted on cleanup), `aggregate_csv` streams `results/result_*.csv` → `output.csv`, status → `Completed`. On `Failed`: snapshot taken, `error_message` set from the Job's `Failed` condition, status → `Failed`.
5. Either terminal transition triggers `cleanup_job`: deletes the K8s Job (cascades to pods) and the `chunks/`/`results/` directories; `input.csv`/`output.csv` are kept.
6. `GET /api/jobs/{id}/result` streams `output.csv` once `Completed`.
7. Frontend polls `GET /api/jobs` every 3s, but skips the request while the tab is hidden (`visibilitychange`) or once every job is in a terminal state, and catches up immediately when the tab regains visibility.

## Recently changed (this session)

Working from a pasted code review of `k8s/watcher.py` and related concurrency/testing concerns. Checked each claim against the actual code before acting:

- **Verified as non-issues (review was wrong, or already handled)** — worth knowing so a future review doesn't re-raise them without re-checking:
  - **Locking**: `_lock_for` (`services/job_service.py`) is a plain `threading.Lock`, not `asyncio.Lock`. The watcher runs via `asyncio.to_thread` and FastAPI's sync routes run via `run_in_threadpool` — both are real OS threads, so `threading.Lock` is the *correct* primitive, not a bug.
  - **Frontend polling on submit**: `App.jsx`'s `handleSubmit` calls `await refresh()` directly right after submitting a job — it does not depend on the visibility-based resume path, so a user who submits without switching tabs still sees the UI update.
  - **DB session concurrency**: reduces to the same locking answer above — reconcile paths are already serialized by `threading.Lock`, sessions are per-call, `check_same_thread=False` is set correctly for SQLite.
- **Fixed this session**: generalized the SQLite schema-migration guard — see the `core/db.py` entry above (`sync_sqlite_schema`). Replaces two hand-maintained `if "col" not in existing_columns` blocks in `main.py` with a generic diff, so adding a model column no longer requires remembering to add a matching guard.
- **Confirmed still-open gap, no action taken**: `k8s/orchestrator.list_k8s_jobs` has no test against a mocked kubernetes client — see Known gaps below (unchanged from before this session).

Previous session's changes (watch-based push reconciliation, batched `reconcile_jobs_batch`, streaming `partitioner.py`, proportional `activeDeadlineSeconds`, frontend polling pause/resume) are already folded into the Architecture/Request-flow sections above rather than repeated here. `thesis-implementation-context.md` predated those changes; a documentation pass (2026-09-08) reconciled it with the current code, so both docs now agree as of commit `26575a8` (the fixed+per-row worker compute cost model).

## Configuration (`backend/app/core/config.py`, env/`.env`-overridable)

`storage_dir=./storage` · `database_url=sqlite:///./app.db` · `max_workers_per_job=32` · `worker_image=batch-worker:latest` · `data_mount_path=/data` · `job_deadline_base_seconds=60` · `job_deadline_seconds_per_row=0.5` · `kube_namespace=default` · `kube_context=None` (current kubeconfig context, expected `minikube`) · `noop_transform=False` (worker benchmark switch) · `compute_fixed_s=0.3` / `compute_per_row_s=0.000001` (simulated per-row worker compute cost, see worker/main.py) · `sweep_results_dir=./scripts/sweep_results`.

## Testing

All in `backend/tests/`, run with `cd backend && python -m pytest` (venv at `backend/.venv`). Kubernetes is mocked throughout (`unittest.mock.patch` on `job_service`'s imported names) — no live cluster needed. 82 tests, all passing as of this session.

| File | Covers |
|---|---|
| `test_job_service.py` (20) | `run_job` state transitions/races, `reconcile_status` (single-job pull path: skip non-Running, no-op when K8s Job missing, K8s-unavailable fallback, Failed/Completed transitions incl. cleanup), `reconcile_jobs_batch` (batched list path: skips the K8s call when nothing's Running, one call for many Running jobs, matches/transitions by job id, leaves unmatched/unreachable-cluster cases unchanged), `get_job_workers`, `cleanup_job`. |
| `test_watcher.py` (17) | `_job_id_from_k8s_job` label parsing, `_handle_event` (incl. an end-to-end event → Completed test with no mocking of `reconcile_from_k8s_job`), `job_service.reconcile_from_k8s_job` directly (unknown id, non-Running skip, Failed transition, no double-apply when racing an already-terminal job), `_stream_events` (dispatch, early stop, one bad event doesn't abort the stream, connection error returns False), `run_job_watcher` (reconnect timing/backoff). |
| `test_partitioner.py` (14) | Uneven-split remainder distribution, worker_count == row_count, single worker, header repeated per chunk, empty/header-only file, worker_count bounds, ragged-row error with row number, BOM stripping, quoted commas/embedded newlines, and (new) that passing an explicit `row_count` hint produces the same split and still validates ragged rows. |
| `test_aggregator.py` (5) | Header-once merge across files, header-mismatch error, missing-file error, empty-result-file error. |
| `test_job_builder.py` (4) | `_active_deadline_seconds` grows with rows-per-worker, shrinks as worker_count increases for fixed rows, never drops below the base, and `build_job_manifest` actually wires the computed value into the manifest. |
| `test_upload_validation.py` (20) | `POST /api/jobs` edge cases via `TestClient`: extension checks, empty/header-only/ragged CSV, worker_count bounds, malformed multipart, etc. |
| `test_db_schema_sync.py` (2, new) | `sync_sqlite_schema` adds missing nullable columns to a stale on-disk table (simulating a pre-`finished_at`/`worker_snapshot` `app.db`), and is a no-op when the table already matches the model. |

`conftest.py` points the app at an isolated temp SQLite DB + storage dir for the whole session, and wipes all `Job` rows + `storage/jobs/` after every test (`_isolate_job_state` autouse fixture) so tests can't see each other's state. `make_csv(path, header, rows)` is the shared CSV-writing test helper.

Not covered by pytest (deliberately, per `e2e_demo.py`'s own docstring): real-cluster behavior — that's `backend/scripts/e2e_demo.py` (black-box HTTP against a live backend + minikube) and `backend/scripts/worker_sweep.py` (benchmark, not correctness).

## Known gaps / things to check before relying on them

- No test directly exercises `k8s/orchestrator.list_k8s_jobs` against a mocked kubernetes client (it's covered indirectly through `job_service.reconcile_jobs_batch` tests, which mock `list_k8s_jobs` itself rather than the client underneath).
- Frontend polling change (`App.jsx`) has no automated test (no frontend test runner is set up in this repo) — verified via `vite build` + `oxlint` only, not a browser smoke test.
