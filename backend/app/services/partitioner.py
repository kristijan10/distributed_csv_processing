import csv
from pathlib import Path


class PartitionError(Exception):
    pass


def partition_csv(input_path: str | Path, output_dir: str | Path, worker_count: int) -> list[Path]:
    """Split a CSV file's data rows into `worker_count` roughly-equal chunk
    files under output_dir, each a standalone CSV with the original header.
    Returns the chunk file paths in worker order (chunk i -> worker i).
    """
    input_path = Path(input_path)
    output_dir = Path(output_dir)

    with input_path.open(newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            raise PartitionError("CSV file is empty") from None
        rows = list(reader)

    row_count = len(rows)
    if worker_count < 1:
        raise PartitionError("worker_count must be at least 1")
    if row_count == 0:
        raise PartitionError("CSV file has a header but no data rows")
    if worker_count > row_count:
        raise PartitionError(f"worker_count ({worker_count}) cannot exceed the number of data rows ({row_count})")

    output_dir.mkdir(parents=True, exist_ok=True)

    base, remainder = divmod(row_count, worker_count)
    chunk_paths = []
    start = 0
    for i in range(worker_count):
        size = base + (1 if i < remainder else 0)
        chunk_rows = rows[start : start + size]
        start += size

        chunk_path = output_dir / f"chunk_{i:03d}.csv"
        with chunk_path.open("w", newline="", encoding="utf-8") as out:
            writer = csv.writer(out)
            writer.writerow(header)
            writer.writerows(chunk_rows)
        chunk_paths.append(chunk_path)

    return chunk_paths
