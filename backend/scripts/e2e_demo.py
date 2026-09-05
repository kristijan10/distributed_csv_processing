#!/usr/bin/env python3
"""End-to-end demonstration / test script for the distributed batch
processing platform.

Unlike the pytest suite (tests/), this exercises the REAL stack: a running
backend talking to a REAL Kubernetes cluster (minikube). Bring everything
up first (see README.md), then from backend/ with the venv active:

    python scripts/e2e_demo.py

Each check prints PASS/FAIL as it runs; a summary and a non-zero exit code
follow if anything failed. Safe to re-run - every scenario creates its own
fresh job(s).
"""

import concurrent.futures
import csv
import io
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
STORAGE_DIR = Path(os.environ.get("E2E_STORAGE_DIR", Path(__file__).resolve().parent.parent / "storage"))
POLL_INTERVAL = 1.0
POLL_TIMEOUT = 60.0

_results: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = "") -> bool:
    _results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    suffix = f" — {detail}" if detail and not passed else ""
    print(f"[{mark}] {name}{suffix}")
    return passed


def make_csv_bytes(rows, header=("id", "value")) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def upload(client: httpx.Client, content: bytes, worker_count: int, filename: str = "input.csv") -> httpx.Response:
    return client.post(
        "/api/jobs",
        files={"file": (filename, content, "text/csv")},
        data={"worker_count": str(worker_count)},
    )


def poll_until_terminal(client: httpx.Client, job_id: str, timeout: float = POLL_TIMEOUT) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/api/jobs/{job_id}")
        resp.raise_for_status()
        job = resp.json()
        if job["status"] in ("Completed", "Failed"):
            return job
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"job {job_id} did not reach a terminal status within {timeout}s")


def k8s_job_gone(job_id: str) -> bool:
    result = subprocess.run(["kubectl", "get", "job", f"batch-job-{job_id}"], capture_output=True, text=True)
    return result.returncode != 0


def check_prerequisites(client: httpx.Client) -> bool:
    ok = True
    try:
        resp = client.get("/api/health", timeout=5)
        ok = record("backend reachable", resp.status_code == 200) and ok
    except httpx.HTTPError as exc:
        ok = record("backend reachable", False, str(exc)) and ok

    kubectl = subprocess.run(["kubectl", "get", "nodes"], capture_output=True, text=True)
    ok = record("kubectl cluster reachable", kubectl.returncode == 0, kubectl.stderr.strip()) and ok

    ok = (
        record(
            "storage dir visible (needed for the failure-path test)",
            STORAGE_DIR.exists(),
            f"expected {STORAGE_DIR}",
        )
        and ok
    )
    return ok


def scenario_golden_path(client: httpx.Client) -> None:
    rows = [[i, i * 10] for i in range(1, 8)]  # 7 rows
    resp = upload(client, make_csv_bytes(rows), worker_count=3)
    if not record("golden path: upload accepted", resp.status_code == 201, resp.text):
        return
    job_id = resp.json()["id"]

    resp = client.post(f"/api/jobs/{job_id}/run")
    if not record("golden path: run accepted", resp.status_code == 200, resp.text):
        return

    try:
        job = poll_until_terminal(client, job_id)
    except TimeoutError as exc:
        record("golden path: reaches a terminal status", False, str(exc))
        return
    if not record("golden path: resolves to Completed", job["status"] == "Completed", str(job)):
        return

    resp = client.get(f"/api/jobs/{job_id}/result")
    if record("golden path: result downloadable", resp.status_code == 200, resp.text):
        lines = resp.text.strip().splitlines()
        record("golden path: result has header + 7 rows", len(lines) == 8, f"got {len(lines)} lines")
        record(
            "golden path: header carries processed_by_worker column",
            "processed_by_worker" in lines[0],
            lines[0],
        )

    record("golden path: Kubernetes Job cleaned up", k8s_job_gone(job_id))


def scenario_failure_path(client: httpx.Client) -> None:
    rows = [[i, i * 10] for i in range(1, 8)]
    resp = upload(client, make_csv_bytes(rows), worker_count=3)
    if not record("failure path: upload accepted", resp.status_code == 201, resp.text):
        return
    job_id = resp.json()["id"]

    resp = client.post(f"/api/jobs/{job_id}/run")
    if not record("failure path: run accepted", resp.status_code == 200, resp.text):
        return

    # Partitioning happens synchronously inside /run, before pods are
    # scheduled - deleting a chunk right after /run returns reliably beats
    # the pod to it, forcing that worker to crash.
    chunk_path = STORAGE_DIR / "jobs" / job_id / "chunks" / "chunk_001.csv"
    sabotaged = chunk_path.exists()
    if sabotaged:
        chunk_path.unlink()
    record("failure path: chunk file reachable to sabotage", sabotaged, f"expected {chunk_path}")

    try:
        job = poll_until_terminal(client, job_id)
    except TimeoutError as exc:
        record("failure path: reaches a terminal status", False, str(exc))
        return
    record("failure path: resolves to Failed", job["status"] == "Failed", str(job))
    record("failure path: error_message populated", bool(job.get("error_message")), str(job))

    resp = client.get(f"/api/jobs/{job_id}/result")
    record("failure path: result correctly unavailable (409)", resp.status_code == 409, resp.text)

    record("failure path: Kubernetes Job cleaned up", k8s_job_gone(job_id))


def scenario_validation_edge_cases(client: httpx.Client) -> None:
    cases = [
        ("non-CSV extension", b"id\n1\n", "input.txt", 1, 422),
        ("empty file", b"", "input.csv", 1, 422),
        ("header only, no rows", b"id,name\n", "input.csv", 1, 422),
        ("ragged rows", b"id,name,value\n1,Alice,10\n2,Bob\n", "input.csv", 1, 422),
        ("worker_count 0", b"id\n1\n2\n", "input.csv", 0, 422),
        ("worker_count exceeds row count", b"id\n1\n2\n", "input.csv", 5, 422),
        ("worker_count over max (33)", b"id\n1\n2\n", "input.csv", 33, 422),
    ]
    for name, content, filename, workers, expected_status in cases:
        resp = upload(client, content, worker_count=workers, filename=filename)
        record(f"validation: {name} -> {expected_status}", resp.status_code == expected_status, resp.text)

    bom_content = "﻿id,name\n1,Alice\n2,Bob\n3,Carol\n".encode("utf-8")
    resp = upload(client, bom_content, worker_count=3)
    if record("validation: BOM file accepted", resp.status_code == 201, resp.text):
        job_id = resp.json()["id"]
        client.post(f"/api/jobs/{job_id}/run")
        try:
            poll_until_terminal(client, job_id)
            resp = client.get(f"/api/jobs/{job_id}/result")
            header = resp.text.splitlines()[0] if resp.status_code == 200 else ""
            record("validation: BOM stripped from output header", header.startswith("id,"), repr(header))
        except TimeoutError as exc:
            record("validation: BOM job completes", False, str(exc))


def scenario_state_guards(client: httpx.Client) -> None:
    resp = upload(client, make_csv_bytes([[1, 1], [2, 2]]), worker_count=1)
    job_id = resp.json()["id"]

    resp = client.post("/api/jobs/does-not-exist/run")
    record("guards: run nonexistent job -> 404", resp.status_code == 404, resp.text)

    resp = client.get("/api/jobs/does-not-exist")
    record("guards: get nonexistent job -> 404", resp.status_code == 404, resp.text)

    resp = client.get(f"/api/jobs/{job_id}/result")
    record("guards: download before run -> 409", resp.status_code == 409, resp.text)

    client.post(f"/api/jobs/{job_id}/run")
    resp = client.post(f"/api/jobs/{job_id}/run")
    record("guards: re-run an already-Running job -> 409", resp.status_code == 409, resp.text)

    poll_until_terminal(client, job_id)
    resp = client.post(f"/api/jobs/{job_id}/run")
    record("guards: re-run a Completed job -> 409", resp.status_code == 409, resp.text)


def scenario_concurrency(client: httpx.Client) -> None:
    resp = upload(client, make_csv_bytes([[i, i] for i in range(1, 8)]), worker_count=3)
    job_id = resp.json()["id"]

    # Separate short-lived requests (not the shared client) to keep this
    # check independent of httpx.Client's cross-thread behavior.
    def fire():
        return httpx.post(f"{BASE_URL}/api/jobs/{job_id}/run")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        responses = [f.result() for f in [pool.submit(fire), pool.submit(fire)]]
    codes = sorted(r.status_code for r in responses)
    record("concurrency: double /run -> exactly one 200 and one 409 (never 500)", codes == [200, 409], str(codes))
    poll_until_terminal(client, job_id)

    job_ids = []
    for _ in range(3):
        resp = upload(client, make_csv_bytes([[i, i] for i in range(1, 8)]), worker_count=2)
        job_ids.append(resp.json()["id"])
    for jid in job_ids:
        client.post(f"/api/jobs/{jid}/run")

    all_completed = True
    for jid in job_ids:
        try:
            job = poll_until_terminal(client, jid)
            all_completed = all_completed and job["status"] == "Completed"
        except TimeoutError:
            all_completed = False
    record("concurrency: 3 independent jobs run simultaneously without interference", all_completed)


def main() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        print(f"== Prerequisites (backend: {BASE_URL}) ==")
        if not check_prerequisites(client):
            print("\nPrerequisites failed - see README.md for how to start the stack.")
            sys.exit(2)

        print("\n== Golden path ==")
        scenario_golden_path(client)

        print("\n== Failure path ==")
        scenario_failure_path(client)

        print("\n== Validation edge cases ==")
        scenario_validation_edge_cases(client)

        print("\n== State-transition guards ==")
        scenario_state_guards(client)

        print("\n== Concurrency ==")
        scenario_concurrency(client)

    passed = sum(1 for _, ok, _ in _results if ok)
    total = len(_results)
    print(f"\n{passed}/{total} checks passed")
    if passed != total:
        print("\nFailures:")
        for name, ok, detail in _results:
            if not ok:
                print(f"  - {name}: {detail}")
        sys.exit(1)


if __name__ == "__main__":
    main()
