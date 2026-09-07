import csv
from pathlib import Path


class PartitionError(Exception):
    pass


def _validate_row(row: list[str], header: list[str], line_num: int) -> None:
    if len(row) != len(header):
        raise PartitionError(
            f"Row {line_num} has {len(row)} columns, expected {len(header)} (based on the header)"
        )


def _validate_row_count(row_count: int, worker_count: int) -> None:
    if row_count == 0:
        raise PartitionError("CSV file has a header but no data rows")
    if worker_count > row_count:
        raise PartitionError(f"worker_count ({worker_count}) cannot exceed the number of data rows ({row_count})")


def _chunk_sizes(row_count: int, worker_count: int) -> list[int]:
    base, remainder = divmod(row_count, worker_count)
    return [base + (1 if i < remainder else 0) for i in range(worker_count)]


def _write_chunks(rows, header: list[str], chunk_paths: list[Path], sizes: list[int], validate: bool) -> None:
    chunk_index = 0
    remaining = sizes[0]
    out = chunk_paths[0].open("w", newline="", encoding="utf-8")
    writer = csv.writer(out)
    writer.writerow(header)
    try:
        for line_num, row in enumerate(rows, start=2):
            if validate:
                _validate_row(row, header, line_num)
            while remaining == 0:
                out.close()
                chunk_index += 1
                remaining = sizes[chunk_index]
                out = chunk_paths[chunk_index].open("w", newline="", encoding="utf-8")
                writer = csv.writer(out)
                writer.writerow(header)
            writer.writerow(row)
            remaining -= 1
    finally:
        out.close()


def partition_csv(
    input_path: str | Path,
    output_dir: str | Path,
    worker_count: int,
    row_count: int | None = None,
) -> list[Path]:
    """Split a CSV file's data rows into `worker_count` roughly-equal chunk
    files under output_dir, each a standalone CSV with the original header.
    Returns the chunk file paths in worker order (chunk i -> worker i).

    Streams rows straight from the reader into their target chunk file
    rather than materializing the whole input in memory. Sizing each chunk
    up front (base row count, plus one for the first `row_count % worker_count`
    chunks) needs the total row count before the first row can be written,
    so a caller that already knows it (job_service, from the row count
    validated at upload) should pass `row_count` for a true single pass;
    without it, a first pass counts and validates rows (still one row at a
    time, never the whole file at once) before the write pass runs.
    """
    input_path = Path(input_path)
    output_dir = Path(output_dir)

    if worker_count < 1:
        raise PartitionError("worker_count must be at least 1")

    single_pass = row_count is not None

    with input_path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            raise PartitionError("CSV file is empty") from None

        if row_count is None:
            row_count = 0
            for line_num, row in enumerate(reader, start=2):
                _validate_row(row, header, line_num)
                row_count += 1
            _validate_row_count(row_count, worker_count)

            f.seek(0)
            reader = csv.reader(f)
            next(reader)  # re-skip the header; already captured above
        else:
            _validate_row_count(row_count, worker_count)

        output_dir.mkdir(parents=True, exist_ok=True)
        chunk_paths = [output_dir / f"chunk_{i:03d}.csv" for i in range(worker_count)]
        _write_chunks(reader, header, chunk_paths, _chunk_sizes(row_count, worker_count), validate=single_pass)

    return chunk_paths
