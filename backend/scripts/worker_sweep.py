#!/usr/bin/env python3
"""Worker-count sweep for the I/O-vs-compute isolation experiment.

Drives the real stack (like e2e_demo.py) through each CSV found in
scripts/sweep_input/ (e.g. a 1M-row and a 10M-row file) at increasing
worker counts, and records total wall-clock time plus the per-pod
read/compute/write split (from worker/main.py's timing JSON files) for
each worker count.

Drop one or more CSVs into scripts/sweep_input/ first (any header + a
uniform column count the backend accepts - the id/value/payload shape used
by earlier synthetic runs works fine, but isn't required). Every file found
there gets swept across all worker counts, smallest first.

Run once with the backend started normally (baseline), and once with the
backend started with NOOP_TRANSFORM=1 (worker skips its per-row transform
and echoes the chunk back unchanged) - the --mode flag only labels the
output files, it does not itself flip that setting.

    python scripts/worker_sweep.py --mode baseline
    # restart the backend with NOOP_TRANSFORM=1, then:
    python scripts/worker_sweep.py --mode noop

Results land in scripts/sweep_results/<mode>_<row_count>_sweep.csv, one
file per input file swept.
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import httpx

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
STORAGE_DIR = Path(os.environ.get("E2E_STORAGE_DIR", Path(__file__).resolve().parent.parent / "storage"))
INPUT_DIR = Path(os.environ.get("SWEEP_INPUT_DIR", Path(__file__).resolve().parent / "sweep_input"))
RESULTS_DIR = Path(os.environ.get("SWEEP_RESULTS_DIR", Path(__file__).resolve().parent / "sweep_results"))

WORKER_COUNTS = [1, 2, 4, 8, 10, 12, 14, 16, 20, 24, 32]
WATCH_DELAY_S = float(os.environ.get("SWEEP_WATCH_DELAY", "5"))
POLL_INTERVAL = 1.0
POLL_TIMEOUT = 180.0


def discover_input_files() -> list[Path]:
    files = sorted(INPUT_DIR.glob("*.csv"), key=lambda p: p.stat().st_size)
    if not files:
        raise SystemExit(f"No .csv files found in {INPUT_DIR} - drop your sweep input file(s) there first.")
    return files


def count_csv_rows(path: Path) -> int:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)  # header
        return sum(1 for _ in reader)


def upload(client: httpx.Client, content: bytes, worker_count: int) -> str:
    resp = client.post(
        "/api/jobs",
        files={"file": ("sweep_input.csv", content, "text/csv")},
        data={"worker_count": str(worker_count)},
    )
    resp.raise_for_status()
    return resp.json()["id"]


def poll_until_terminal(client: httpx.Client, job_id: str) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT
    while time.monotonic() < deadline:
        resp = client.get(f"/api/jobs/{job_id}")
        resp.raise_for_status()
        job = resp.json()
        if job["status"] in ("Completed", "Failed"):
            return job
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"job {job_id} did not reach a terminal status within {POLL_TIMEOUT}s")


def read_timings(job_id: str, worker_count: int) -> list[dict]:
    timings_dir = STORAGE_DIR / "jobs" / job_id / "timings"
    files = sorted(timings_dir.glob("timing_*.json"))
    if len(files) != worker_count:
        print(f"  warning: expected {worker_count} timing files, found {len(files)} in {timings_dir}")
    return [json.loads(f.read_text()) for f in files]


def summarize(values: list[float]) -> tuple[float, float, float]:
    return (sum(values) / len(values), min(values), max(values)) if values else (0.0, 0.0, 0.0)


def sweep_one_file(client: httpx.Client, mode: str, input_path: Path) -> bool:
    dataset = input_path.read_bytes()
    row_count = count_csv_rows(input_path)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{mode}_{row_count}_sweep.csv"

    print(f"\n### {input_path.name}: {row_count} rows ###")
    print(f"  Worker counts: {WORKER_COUNTS}")
    print(f"  Results -> {out_path}")

    all_ok = True
    with out_path.open("w", newline="") as out_f:
        fieldnames = [
            "worker_count",
            "row_count",
            "wall_s",
            "avg_read_s",
            "avg_compute_s",
            "avg_write_s",
            "max_read_s",
            "max_compute_s",
            "max_write_s",
        ]
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        writer.writeheader()

        for worker_count in WORKER_COUNTS:
            print(f"\n== worker_count={worker_count} ==")
            job_id = upload(client, dataset, worker_count)

            if worker_count == 24:
                print(
                    f"### starting the 24-worker run in {WATCH_DELAY_S:.0f}s - start your "
                    "vmstat/top watch now ###"
                )
                time.sleep(WATCH_DELAY_S)

            t_submit = time.monotonic()
            resp = client.post(f"/api/jobs/{job_id}/run")
            resp.raise_for_status()
            try:
                job = poll_until_terminal(client, job_id)
            except TimeoutError as exc:
                print(f"  FAILED: {exc}")
                all_ok = False
                continue
            wall_s = time.monotonic() - t_submit

            if job["status"] != "Completed":
                print(f"  FAILED: job resolved to {job['status']}: {job.get('error_message')}")
                all_ok = False
                continue

            timings = read_timings(job_id, worker_count)
            avg_read, _, max_read = summarize([t["read_s"] for t in timings])
            avg_compute, _, max_compute = summarize([t["compute_s"] for t in timings])
            avg_write, _, max_write = summarize([t["write_s"] for t in timings])

            print(
                f"  wall={wall_s:.3f}s  read(avg/max)={avg_read:.3f}/{max_read:.3f}s  "
                f"compute(avg/max)={avg_compute:.3f}/{max_compute:.3f}s  "
                f"write(avg/max)={avg_write:.3f}/{max_write:.3f}s"
            )

            writer.writerow(
                {
                    "worker_count": worker_count,
                    "row_count": row_count,
                    "wall_s": round(wall_s, 4),
                    "avg_read_s": round(avg_read, 4),
                    "avg_compute_s": round(avg_compute, 4),
                    "avg_write_s": round(avg_write, 4),
                    "max_read_s": round(max_read, 4),
                    "max_compute_s": round(max_compute, 4),
                    "max_write_s": round(max_write, 4),
                }
            )
            out_f.flush()

    return all_ok


def run_sweep(mode: str) -> bool:
    print(f"Mode: {mode}")
    if mode == "noop":
        print("  Make sure the backend was (re)started with NOOP_TRANSFORM=1 before continuing.")
    else:
        print("  Make sure the backend was started WITHOUT NOOP_TRANSFORM (or with it unset/0).")

    input_files = discover_input_files()
    print(f"  Input files ({len(input_files)}): {', '.join(p.name for p in input_files)}")

    all_ok = True
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        for input_path in input_files:
            all_ok = sweep_one_file(client, mode, input_path) and all_ok

    return all_ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["baseline", "noop"], required=True, help="labels the output CSV only")
    args = parser.parse_args()

    ok = run_sweep(args.mode)
    if not ok:
        print("\nOne or more worker counts failed - see FAILED lines above.")
        sys.exit(1)
    print("\nSweep complete.")


if __name__ == "__main__":
    main()
