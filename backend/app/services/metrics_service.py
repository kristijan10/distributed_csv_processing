import csv
import re
from pathlib import Path

from app.core.config import Settings
from app.schemas.metrics import SweepPoint, SweepRun

SWEEP_MODES = ("baseline", "noop")

_SWEEP_FILE_RE = re.compile(r"^(baseline|noop)_(\d+)_sweep\.csv$")


class SweepNotFoundError(Exception):
    pass


class SweepMissingBaselineError(Exception):
    pass


def _sweep_path(settings: Settings, mode: str, row_count: int) -> Path:
    return Path(settings.sweep_results_dir) / f"{mode}_{row_count}_sweep.csv"


def list_available_runs(settings: Settings) -> list[SweepRun]:
    runs = []
    for path in Path(settings.sweep_results_dir).glob("*_sweep.csv"):
        m = _SWEEP_FILE_RE.match(path.name)
        if m:
            runs.append(SweepRun(mode=m.group(1), row_count=int(m.group(2))))
    runs.sort(key=lambda r: (r.mode, r.row_count))
    return runs


def read_sweep(settings: Settings, mode: str, row_count: int) -> list[SweepPoint]:
    path = _sweep_path(settings, mode, row_count)
    if not path.is_file():
        raise SweepNotFoundError(
            f"No sweep results for mode={mode!r}, row_count={row_count!r}. Run "
            f"`python scripts/worker_sweep.py --mode {mode}` with that input file first."
        )

    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))

    baseline_wall_s = next(
        (float(row["wall_s"]) for row in rows if int(row["worker_count"]) == 1),
        None,
    )
    if baseline_wall_s is None:
        raise SweepMissingBaselineError(
            f"Sweep for mode={mode!r} has no worker_count=1 row to use as the speedup baseline."
        )

    points = []
    for row in rows:
        worker_count = int(row["worker_count"])
        wall_s = float(row["wall_s"])
        row_count = int(row["row_count"]) if row.get("row_count") else None
        speedup = baseline_wall_s / wall_s
        points.append(
            SweepPoint(
                worker_count=worker_count,
                row_count=row_count,
                wall_s=wall_s,
                avg_read_s=float(row["avg_read_s"]),
                avg_compute_s=float(row["avg_compute_s"]),
                avg_write_s=float(row["avg_write_s"]),
                max_read_s=float(row["max_read_s"]),
                max_compute_s=float(row["max_compute_s"]),
                max_write_s=float(row["max_write_s"]),
                speedup=speedup,
                efficiency=speedup / worker_count,
                ideal_speedup=float(worker_count),
                throughput_rows_per_s=(row_count / wall_s) if row_count else None,
            )
        )
    points.sort(key=lambda p: p.worker_count)
    return points
