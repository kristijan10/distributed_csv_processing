import pytest

from app.services.partitioner import PartitionError, partition_csv
from tests.conftest import make_csv


def _read(path):
    return path.read_text(encoding="utf-8")


def test_uneven_split_distributes_remainder_to_first_chunks(tmp_path):
    csv_path = make_csv(
        tmp_path / "input.csv",
        ["id", "name"],
        [[i, f"row{i}"] for i in range(1, 8)],  # 7 rows
    )
    chunks = partition_csv(csv_path, tmp_path / "chunks", worker_count=3)

    assert [c.name for c in chunks] == ["chunk_000.csv", "chunk_001.csv", "chunk_002.csv"]
    sizes = [len(_read(c).splitlines()) - 1 for c in chunks]  # minus header
    assert sizes == [3, 2, 2]


def test_worker_count_equals_row_count_gives_one_row_each(tmp_path):
    csv_path = make_csv(tmp_path / "input.csv", ["id"], [[i] for i in range(1, 6)])
    chunks = partition_csv(csv_path, tmp_path / "chunks", worker_count=5)
    for c in chunks:
        assert len(_read(c).splitlines()) - 1 == 1


def test_single_worker_gets_all_rows(tmp_path):
    csv_path = make_csv(tmp_path / "input.csv", ["id"], [[i] for i in range(1, 6)])
    chunks = partition_csv(csv_path, tmp_path / "chunks", worker_count=1)
    assert len(chunks) == 1
    assert len(_read(chunks[0]).splitlines()) - 1 == 5


def test_header_repeated_in_every_chunk(tmp_path):
    csv_path = make_csv(tmp_path / "input.csv", ["id", "name"], [[1, "a"], [2, "b"], [3, "c"]])
    chunks = partition_csv(csv_path, tmp_path / "chunks", worker_count=3)
    for c in chunks:
        assert _read(c).splitlines()[0] == "id,name"


def test_empty_file_raises(tmp_path):
    csv_path = tmp_path / "input.csv"
    csv_path.write_text("")
    with pytest.raises(PartitionError, match="empty"):
        partition_csv(csv_path, tmp_path / "chunks", worker_count=1)


def test_header_only_raises(tmp_path):
    csv_path = make_csv(tmp_path / "input.csv", ["id", "name"], [])
    with pytest.raises(PartitionError, match="no data rows"):
        partition_csv(csv_path, tmp_path / "chunks", worker_count=1)


def test_worker_count_less_than_one_raises(tmp_path):
    csv_path = make_csv(tmp_path / "input.csv", ["id"], [[1]])
    with pytest.raises(PartitionError, match="at least 1"):
        partition_csv(csv_path, tmp_path / "chunks", worker_count=0)


def test_worker_count_exceeds_row_count_raises(tmp_path):
    csv_path = make_csv(tmp_path / "input.csv", ["id"], [[1], [2]])
    with pytest.raises(PartitionError, match="cannot exceed"):
        partition_csv(csv_path, tmp_path / "chunks", worker_count=3)


def test_ragged_row_raises_with_row_number(tmp_path):
    csv_path = tmp_path / "input.csv"
    csv_path.write_text("id,name,value\n1,Alice,10\n2,Bob\n3,Carol,30\n")
    with pytest.raises(PartitionError, match="Row 3 has 2 columns, expected 3"):
        partition_csv(csv_path, tmp_path / "chunks", worker_count=3)


def test_bom_is_stripped_from_header(tmp_path):
    csv_path = tmp_path / "input.csv"
    csv_path.write_bytes("﻿id,name\n1,Alice\n2,Bob\n".encode("utf-8"))
    chunks = partition_csv(csv_path, tmp_path / "chunks", worker_count=2)
    assert _read(chunks[0]).splitlines()[0] == "id,name"


def test_quoted_field_with_embedded_comma_preserved(tmp_path):
    csv_path = tmp_path / "input.csv"
    csv_path.write_text('id,note\n1,"hello, world"\n2,plain\n')
    chunks = partition_csv(csv_path, tmp_path / "chunks", worker_count=2)
    contents = "".join(_read(c) for c in chunks)
    assert "hello, world" in contents


def test_quoted_field_with_embedded_newline_preserved(tmp_path):
    csv_path = tmp_path / "input.csv"
    csv_path.write_text('id,note\n1,"multi\nline"\n2,plain\n')
    chunks = partition_csv(csv_path, tmp_path / "chunks", worker_count=2)
    contents = "".join(_read(c) for c in chunks)
    assert "multi\nline" in contents
