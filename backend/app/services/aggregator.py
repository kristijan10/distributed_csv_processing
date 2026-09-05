import csv
from pathlib import Path


class AggregationError(Exception):
    pass


def aggregate_csv(result_paths: list[Path], output_path: Path) -> Path:
    """Merge per-worker partial result CSVs (in worker order) into one
    output CSV: the header is taken from the first file and written once,
    followed by every file's data rows in order.
    """
    if not result_paths:
        raise AggregationError("No result files to aggregate")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")

    header: list[str] | None = None
    try:
        with tmp_path.open("w", newline="", encoding="utf-8") as out:
            writer = csv.writer(out)
            for path in result_paths:
                if not path.exists():
                    raise AggregationError(f"Missing result file: {path.name}")
                with path.open(newline="", encoding="utf-8", errors="replace") as f:
                    reader = csv.reader(f)
                    try:
                        file_header = next(reader)
                    except StopIteration:
                        raise AggregationError(f"Result file {path} is empty") from None
                    if header is None:
                        header = file_header
                        writer.writerow(header)
                    elif file_header != header:
                        raise AggregationError(f"Result file {path} has a mismatched header")
                    writer.writerows(reader)
    except AggregationError:
        tmp_path.unlink(missing_ok=True)
        raise

    tmp_path.replace(output_path)
    return output_path
