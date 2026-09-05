import pytest

from app.services.aggregator import AggregationError, aggregate_csv
from tests.conftest import make_csv


def test_merges_files_in_order_with_single_header(tmp_path):
    r0 = make_csv(tmp_path / "result_000.csv", ["id", "val"], [[1, "a"], [2, "b"]])
    r1 = make_csv(tmp_path / "result_001.csv", ["id", "val"], [[3, "c"]])
    r2 = make_csv(tmp_path / "result_002.csv", ["id", "val"], [[4, "d"], [5, "e"]])

    output = aggregate_csv([r0, r1, r2], tmp_path / "output.csv")
    lines = output.read_text().splitlines()

    assert lines[0] == "id,val"
    assert lines.count("id,val") == 1
    assert lines[1:] == ["1,a", "2,b", "3,c", "4,d", "5,e"]


def test_empty_result_paths_list_raises(tmp_path):
    with pytest.raises(AggregationError, match="No result files"):
        aggregate_csv([], tmp_path / "output.csv")


def test_missing_result_file_raises(tmp_path):
    missing = tmp_path / "result_000.csv"
    with pytest.raises(AggregationError, match="Missing result file"):
        aggregate_csv([missing], tmp_path / "output.csv")


def test_mismatched_header_raises(tmp_path):
    r0 = make_csv(tmp_path / "result_000.csv", ["id", "val"], [[1, "a"]])
    r1 = make_csv(tmp_path / "result_001.csv", ["id", "different"], [[2, "b"]])
    with pytest.raises(AggregationError, match="mismatched header"):
        aggregate_csv([r0, r1], tmp_path / "output.csv")


def test_empty_result_file_raises(tmp_path):
    empty = tmp_path / "result_000.csv"
    empty.write_text("")
    with pytest.raises(AggregationError, match="is empty"):
        aggregate_csv([empty], tmp_path / "output.csv")
