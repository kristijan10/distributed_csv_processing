"""API-level tests for everything reachable without a live Kubernetes
cluster: upload validation, job lookup, and the guards on /run and
/result that don't require actually submitting a Kubernetes Job.
"""

import io


def upload(client, content: bytes, filename: str = "input.csv", worker_count: int | str = 3, content_type="text/csv"):
    return client.post(
        "/api/jobs",
        files={"file": (filename, io.BytesIO(content), content_type)},
        data={"worker_count": worker_count},
    )


def test_valid_upload_returns_pending(client):
    resp = upload(client, b"id,name\n1,Alice\n2,Bob\n3,Carol\n", worker_count=2)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "Pending"
    assert body["row_count"] == 3
    assert body["worker_count"] == 2
    assert body["error_message"] is None


def test_non_csv_extension_rejected(client):
    resp = upload(client, b"id,name\n1,Alice\n", filename="input.txt")
    assert resp.status_code == 422
    assert "Only .csv files" in resp.json()["detail"]


def test_uppercase_csv_extension_accepted(client):
    resp = upload(client, b"id,name\n1,Alice\n", filename="input.CSV", worker_count=1)
    assert resp.status_code == 201


def test_empty_file_rejected(client):
    resp = upload(client, b"")
    assert resp.status_code == 422
    assert "empty" in resp.json()["detail"]


def test_header_only_rejected(client):
    resp = upload(client, b"id,name\n")
    assert resp.status_code == 422
    assert "no data rows" in resp.json()["detail"]


def test_ragged_rows_rejected(client):
    resp = upload(client, b"id,name,value\n1,Alice,10\n2,Bob\n3,Carol,30\n")
    assert resp.status_code == 422
    assert "Row 3 has 2 columns, expected 3" in resp.json()["detail"]


def test_worker_count_zero_rejected(client):
    resp = upload(client, b"id\n1\n2\n", worker_count=0)
    assert resp.status_code == 422
    assert "at least 1" in resp.json()["detail"]


def test_worker_count_negative_rejected(client):
    resp = upload(client, b"id\n1\n2\n", worker_count=-1)
    assert resp.status_code == 422


def test_worker_count_over_max_rejected(client):
    resp = upload(client, b"id\n1\n2\n", worker_count=33)
    assert resp.status_code == 422
    assert "at most 32" in resp.json()["detail"]


def test_worker_count_exceeding_row_count_rejected(client):
    resp = upload(client, b"id\n1\n2\n", worker_count=5)
    assert resp.status_code == 422
    assert "cannot exceed the number of data rows" in resp.json()["detail"]


def test_worker_count_equal_to_row_count_accepted(client):
    resp = upload(client, b"id\n1\n2\n3\n", worker_count=3)
    assert resp.status_code == 201


def test_missing_file_field_returns_422(client):
    resp = client.post("/api/jobs", data={"worker_count": 1})
    assert resp.status_code == 422


def test_missing_worker_count_field_returns_422(client):
    resp = client.post("/api/jobs", files={"file": ("input.csv", io.BytesIO(b"id\n1\n"), "text/csv")})
    assert resp.status_code == 422


def test_worker_count_non_numeric_returns_422(client):
    resp = upload(client, b"id\n1\n2\n", worker_count="abc")
    assert resp.status_code == 422


def test_get_nonexistent_job_returns_404(client):
    resp = client.get("/api/jobs/does-not-exist")
    assert resp.status_code == 404


def test_run_nonexistent_job_returns_404(client):
    resp = client.post("/api/jobs/does-not-exist/run")
    assert resp.status_code == 404


def test_download_nonexistent_job_returns_404(client):
    resp = client.get("/api/jobs/does-not-exist/result")
    assert resp.status_code == 404


def test_download_before_run_returns_409(client):
    created = upload(client, b"id\n1\n2\n", worker_count=1).json()
    resp = client.get(f"/api/jobs/{created['id']}/result")
    assert resp.status_code == 409
    assert "status=Pending" in resp.json()["detail"]


def test_list_jobs_includes_created_job(client):
    created = upload(client, b"id\n1\n2\n", worker_count=1).json()
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    ids = [j["id"] for j in resp.json()]
    assert created["id"] in ids
