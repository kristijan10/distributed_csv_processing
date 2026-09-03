# Thesis Project — Implementation Context Document

**Purpose of this document:** This is a consolidated brief for an implementation agent that will build the software described below. It merges the original broad product vision with the final, professor-approved (scoped-down) thesis requirements. **The final requirements section is authoritative for what to actually build.** The long-term vision is included only as context/background so the agent understands the architectural direction and doesn't paint itself into a corner — it is explicitly out of scope for implementation right now.

---

## 1. Official Thesis Topic (final, approved scope)

**Design and Implementation of a Cloud-Native Platform for Distributed Batch Processing Using Kubernetes**

**Goal:** Design and implement a platform that demonstrates distributed execution of batch data-processing jobs using Docker containers and Kubernetes orchestration. The focus is on the **infrastructure and execution model itself**, not on the specifics of data analysis (i.e., what happens to the data inside a worker is intentionally trivial/generic — the point is proving orchestration works).

---

## 2. What Must Be Built (in scope)

1. **Job submission with CSV file upload**
2. **Configuration of the number of worker pods** (user picks how many workers a job uses)
3. **Partitioning of the dataset by rows across workers** (split the uploaded CSV into row-chunks, one chunk per worker)
4. **Automatic creation and management of Kubernetes Jobs and Pods** (backend programmatically creates/manages K8s Job objects and their Pods — not manual kubectl)
5. **Distributed execution of a simple processing task across worker pods** (each pod processes its assigned chunk; the processing logic itself can be simple/generic — this is not the focus)
6. **Execution status monitoring** with these states: `Pending`, `Running`, `Completed`, `Failed`
7. **Aggregation of partial results into a final output** (backend collects all worker outputs and merges them into one downloadable result)
8. **Automatic cleanup** of Kubernetes Jobs, Pods, and temporary files after a run completes (success or failure)

### Architecture / stack (as specified)
- **Frontend:** React
- **Backend API:** FastAPI (Python) — "e.g." in source, but this is the intended default; treat as the choice unless the agent has a strong reason otherwise
- **Orchestration:** Local Kubernetes cluster — **minikube or kind** (this is a local/dev-cluster thesis project, not a managed cloud K8s deployment)
- **Data flow architecture:**
  ```
  Frontend → Backend API → Partitioner → Kubernetes (creates Job → N worker Pods) → Storage → Aggregator → Frontend
  ```

### High-level functional flow
```
1. User uploads a CSV file via the frontend.
2. User specifies the number of worker pods for this job.
3. Backend partitions the CSV by rows into N chunks (N = number of workers).
4. Backend creates a Kubernetes Job with N worker Pods, each pod assigned one chunk.
5. Each pod runs a simple processing task on its chunk and writes results to shared/temp storage.
6. Backend polls/watches pod & job status and exposes it to the frontend as Pending / Running / Completed / Failed.
7. Once all pods complete, backend aggregates the partial results into one final output.
8. Frontend allows the user to download/view the final aggregated result.
9. Backend automatically deletes the Kubernetes Job, its Pods, and any temporary files.
```

---

## 3. Explicit Constraints — Deliberately OUT of Scope

The thesis scope was intentionally narrowed for feasibility. **Do NOT implement these**, even though they appear in the broader product idea (Section 5 below). They should, at most, be mentioned in documentation/future-work notes, not built:

- ❌ **User authentication** (no login/registration/JWT — no auth layer needed for the thesis MVP)
- ❌ **ZIP or multi-format input support** — CSV is the only supported input format
- ❌ **Manual CPU/RAM configuration per job** — only the *number of workers* is configurable, not CPU/RAM resource requests/limits per pod
- ❌ Any Phase 2+ concepts from the original idea doc: generalized processing interfaces (validate/partition/execute plugin system), multiple input types (TXT/JSON/Images/Logs), a processing "marketplace," intelligent/priority scheduling, AI resource estimation, multi-cloud execution, or any vertical SaaS product (security logs, OCR, video encoding, etc.)

If the implementing agent is tempted to "future-proof" the code by adding hooks for these, that's acceptable **only if it doesn't add implementation complexity or scope creep** to the actual deliverable — the priority is a working, demonstrable, narrowly-scoped system.

---

## 4. Suggested Implementation Plan / Milestones

This is a reasonable build order; the implementing agent can adjust as needed but should keep the scope boundaries in Section 3.

1. **Project scaffolding**
   - Set up backend (FastAPI) and frontend (React) project skeletons.
   - Set up local Kubernetes cluster tooling (minikube or kind) and confirm `kubectl`/K8s API access from the backend (likely via the official Kubernetes Python client).
2. **CSV upload & job creation API**
   - Endpoint to upload a CSV file and specify worker count.
   - Persist the job metadata (job id, status, worker count, file location) — a simple DB or even in-memory/JSON store is likely sufficient for thesis scope, but a lightweight DB (e.g., SQLite/Postgres) is safer for demonstrating "real" architecture.
3. **Partitioner module**
   - Splits the uploaded CSV by rows into N roughly-equal chunks (N = worker count), writes chunks to shared storage accessible by pods (e.g., a shared volume, or object storage / mounted hostPath for local dev).
4. **Kubernetes Job orchestration**
   - Backend logic to dynamically build and submit a Kubernetes Job spec with N Pods, each pod given a reference/path to its chunk (e.g., via env var, config map, or mounted volume) and a simple worker container image that processes its chunk (e.g., basic row-level computation — the specifics are intentionally not the focus) and writes output back to shared storage.
5. **Status monitoring**
   - Backend watches/polls Job & Pod status via the Kubernetes API and maps it to Pending / Running / Completed / Failed.
   - Expose a status endpoint (and/or websocket/polling) for the frontend to display live progress.
6. **Aggregation**
   - Once all pods report Completed, backend reads all partial result files and merges them into one final output file.
   - Expose a download endpoint for the aggregated result.
7. **Cleanup**
   - After aggregation (or on failure), automatically delete the Kubernetes Job (which cascades to Pods) and remove temporary chunk/result files from storage.
8. **Frontend**
   - Upload form (CSV + worker count input).
   - Job status view (polls backend, shows Pending/Running/Completed/Failed).
   - Result download once Completed.
9. **Testing / demonstration**
   - End-to-end test: upload a CSV, run with e.g. 3 workers, verify partition → distributed execution → aggregation → cleanup all work correctly, including a failure-path test (e.g., a pod fails) to confirm status reporting and cleanup still behave sensibly.

---

## 5. Background Context Only — NOT for Implementation

This broader vision explains *why* the architecture is being built this way (to support future extension), but none of it should be built now. Included purely so the implementing agent understands the direction and can make sensible naming/structuring choices (e.g., keeping the partitioner as its own module, keeping "processing logic" decoupled from orchestration) without actually implementing any of these future phases.

- **Product vision:** A cloud-native platform that executes data-processing pipelines on large datasets using distributed containerized workers — Kubernetes as the execution layer, workers as the compute layer, "plugins" as processing logic, and industry-specific SaaS products built on top.
- **Original (broader, pre-scoping) idea document** described a multi-phase roadmap:
  - Phase 1 (MFA/Graduate): roughly what's now the approved scope, but originally also included user auth, ZIP support, and manual CPU/RAM config — **these were cut in the final requirements.**
  - Phase 2: Generalized processing engine with a `validate()` / `partition()` / `execute()` plugin interface and support for TXT, JSON, Images, Logs.
  - Phase 3: "Processing Marketplace" — swappable worker images/processing modules (CSV Analyzer, Log Parser, Image Resize, OCR, Video Encoder, PDF Extractor, AI Inference).
  - Phase 4: Intelligent scheduling (priority, deadline, budget-aware).
  - Phase 5: AI-based resource estimation (recommends CPU/RAM/worker count/ETA from historical data).
  - Phase 6: Multi-cloud execution (local K8s, AWS, Azure, GCP).
  - Phase 7: Domain-specific SaaS verticals (security log analysis, AI dataset prep, media processing, document intelligence, scientific computing, industrial IoT, digital forensics).
- **Layered architecture rationale** (for future extensibility, not to be built now):
  ```
  SaaS Domain (Logs, OCR, AI, Video...)
        ↓
  Processing Modules (Validate/Partition/Execute)
        ↓
  Distributed Execution Engine (Kubernetes, Workers)
  ```
  The idea is that infrastructure stays constant while only the processing module and UI change per vertical. This is the motivating reason to keep the partitioner/execution logic cleanly separated from any specific processing task in the current implementation — good internal modularity now makes hypothetical future extension easier, without requiring the agent to build those extensions.

---

## 6. Summary for the Implementing Agent

- **Build:** CSV upload → configurable worker count → row-based partitioning → dynamic Kubernetes Job/Pod creation (local cluster via minikube/kind) → status monitoring (Pending/Running/Completed/Failed) → result aggregation → automatic cleanup. React frontend + FastAPI backend.
- **Do not build:** authentication, ZIP/multi-format support, per-job CPU/RAM configuration, or any Phase 2–7 feature (plugin marketplace, scheduling, AI estimation, multi-cloud, SaaS verticals).
- **Design sensibility:** keep the partitioning logic and worker processing logic modular/decoupled from the orchestration logic, since that separation is the whole architectural point of the thesis — but don't implement anything beyond what Section 2 lists.
