import csv
import os
import time
from pathlib import Path

DATA_ROOT = Path(os.environ.get("DATA_ROOT", "/data"))
JOB_ID = os.environ["JOB_ID"]
WORKER_INDEX = int(os.environ["JOB_COMPLETION_INDEX"])

job_dir = DATA_ROOT / "jobs" / JOB_ID
chunk_path = job_dir / "chunks" / f"chunk_{WORKER_INDEX:03d}.csv"
results_dir = job_dir / "results"
result_path = results_dir / f"result_{WORKER_INDEX:03d}.csv"


def process() -> None:
    with chunk_path.open(newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    # Intentionally simple/generic row-level work - the thesis focus is the
    # orchestration model, not the processing logic itself.
    time.sleep(1)

    results_dir.mkdir(parents=True, exist_ok=True)
    with result_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([*header, "processed_by_worker"])
        for row in rows:
            writer.writerow([*row, WORKER_INDEX])

    print(f"worker {WORKER_INDEX}: processed {len(rows)} rows from {chunk_path} -> {result_path}")


if __name__ == "__main__":
    process()
