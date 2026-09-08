import csv


def write_sweep_csv(path, rows):
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
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def base_row(**overrides):
    row = {
        "worker_count": 1,
        "row_count": 1000,
        "wall_s": 10.0,
        "avg_read_s": 1.0,
        "avg_compute_s": 8.0,
        "avg_write_s": 1.0,
        "max_read_s": 1.0,
        "max_compute_s": 8.0,
        "max_write_s": 1.0,
    }
    row.update(overrides)
    return row


def test_sweep_modes_empty_when_no_csvs(client, settings, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sweep_results_dir", str(tmp_path))
    resp = client.get("/api/metrics/sweep/modes")
    assert resp.status_code == 200
    assert resp.json() == []


def test_sweep_modes_lists_existing_files(client, settings, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sweep_results_dir", str(tmp_path))
    write_sweep_csv(tmp_path / "baseline_sweep.csv", [base_row()])

    resp = client.get("/api/metrics/sweep/modes")
    assert resp.status_code == 200
    assert resp.json() == ["baseline"]


def test_get_sweep_returns_404_when_missing(client, settings, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sweep_results_dir", str(tmp_path))
    resp = client.get("/api/metrics/sweep", params={"mode": "baseline"})
    assert resp.status_code == 404


def test_get_sweep_computes_speedup_efficiency_and_throughput(client, settings, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sweep_results_dir", str(tmp_path))
    write_sweep_csv(
        tmp_path / "baseline_sweep.csv",
        [
            base_row(worker_count=1, row_count=1000, wall_s=10.0),
            base_row(worker_count=4, row_count=1000, wall_s=4.0),
        ],
    )

    resp = client.get("/api/metrics/sweep", params={"mode": "baseline"})
    assert resp.status_code == 200
    points = resp.json()
    assert [p["worker_count"] for p in points] == [1, 4]

    one, four = points
    assert one["speedup"] == 1.0
    assert one["efficiency"] == 1.0
    assert one["throughput_rows_per_s"] == 100.0

    assert four["speedup"] == 2.5  # 10.0 / 4.0
    assert four["efficiency"] == 0.625  # 2.5 / 4
    assert four["ideal_speedup"] == 4.0
    assert four["throughput_rows_per_s"] == 250.0  # 1000 / 4.0


def test_get_sweep_rejects_missing_baseline_row(client, settings, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sweep_results_dir", str(tmp_path))
    write_sweep_csv(tmp_path / "baseline_sweep.csv", [base_row(worker_count=2, wall_s=5.0)])

    resp = client.get("/api/metrics/sweep", params={"mode": "baseline"})
    assert resp.status_code == 422
