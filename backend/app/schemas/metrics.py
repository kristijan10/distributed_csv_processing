from pydantic import BaseModel


class SweepRun(BaseModel):
    mode: str
    row_count: int


class SweepPoint(BaseModel):
    worker_count: int
    row_count: int | None
    wall_s: float
    avg_read_s: float
    avg_compute_s: float
    avg_write_s: float
    max_read_s: float
    max_compute_s: float
    max_write_s: float

    # Derived relative to the worker_count=1 row in the same sweep.
    speedup: float
    efficiency: float
    ideal_speedup: float
    throughput_rows_per_s: float | None
