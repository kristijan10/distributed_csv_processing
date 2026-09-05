import csv
import json
import os
import time
from pathlib import Path

DATA_ROOT = Path(os.environ.get("DATA_ROOT", "/data"))
JOB_ID = os.environ["JOB_ID"]
WORKER_INDEX = int(os.environ["JOB_COMPLETION_INDEX"])
NOOP_TRANSFORM = os.environ.get("NOOP_TRANSFORM", "0") == "1"

job_dir = DATA_ROOT / "jobs" / JOB_ID
chunk_path = job_dir / "chunks" / f"chunk_{WORKER_INDEX:03d}.csv"
results_dir = job_dir / "results"
result_path = results_dir / f"result_{WORKER_INDEX:03d}.csv"
timings_dir = job_dir / "timings"
timing_path = timings_dir / f"timing_{WORKER_INDEX:03d}.json"


def process() -> None:
    t0 = time.monotonic()
    with chunk_path.open(newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    t1 = time.monotonic()

    if not NOOP_TRANSFORM:
        # Intentionally simple/generic row-level work - the thesis focus is the
        # orchestration model, not the processing logic itself.
        time.sleep(1)
    t2 = time.monotonic()

    results_dir.mkdir(parents=True, exist_ok=True)
    with result_path.open("w", newline="") as f:
        writer = csv.writer(f)
        if NOOP_TRANSFORM:
            writer.writerow(header)
            writer.writerows(rows)
        else:
            writer.writerow([*header, "processed_by_worker"])
            for row in rows:
                writer.writerow([*row, WORKER_INDEX])
        # Force the write through the 9p mount before exiting - a closed
        # file isn't guaranteed to be visible on the host side yet.
        f.flush()
        os.fsync(f.fileno())
    t3 = time.monotonic()

    timing = {
        "worker_index": WORKER_INDEX,
        "rows": len(rows),
        "noop_transform": NOOP_TRANSFORM,
        "read_s": round(t1 - t0, 4),
        "compute_s": round(t2 - t1, 4),
        "write_s": round(t3 - t2, 4),
        "total_s": round(t3 - t0, 4),
    }
    timings_dir.mkdir(parents=True, exist_ok=True)
    with timing_path.open("w") as f:
        json.dump(timing, f)
        f.flush()
        os.fsync(f.fileno())

    print(
        f"worker {WORKER_INDEX}: processed {len(rows)} rows from {chunk_path} -> {result_path} "
        f"(read={timing['read_s']}s compute={timing['compute_s']}s write={timing['write_s']}s)"
    )


if __name__ == "__main__":
    process()
