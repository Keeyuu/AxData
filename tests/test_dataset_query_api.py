"""Tests for the dataset query API routes (AXI-030).

Covers the ``POST /v1/data/datasets/{dataset_id}/query`` contract from
docs/plan/axdata-integration/04-axdata-core-contracts.md §6: JSON records,
the ``AXDATA_API_MAX_QUERY_ROWS`` cap with exact ``truncated`` metadata, and
the 404 / 400 / 413 / 503 status-code mapping. The catalog listing/inspect
GET routes keep serving Web Data Browser summary payloads and are only
checked here for fixture visibility.
"""

from __future__ import annotations

import pandas as pd
import pytest
from axdata_core import query_dataset
from fastapi.testclient import TestClient

from apps.api.main import app
from tests.dataset_fixture import (
    DEMO_ROWS,
    write_demo_dataset,
    write_demo_declaration_log,
    write_demo_parquet,
    write_demo_run,
    write_hive_date_partitioned_dataset,
    write_scan_only_dataset,
)

TRICKY_TRACK_ID = "O'Neil; DROP TABLE demo--"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AXDATA_DATA_DIR", str(tmp_path / "data"))
    return TestClient(app)


def _post(client, dataset_id: str, **payload) -> object:
    return client.post(f"/v1/data/datasets/{dataset_id}/query", json=payload)


def test_dataset_query_returns_json_records_with_fields_filters_dates(client, tmp_path) -> None:
    write_demo_dataset(tmp_path / "data")

    response = _post(
        client,
        "demo.track_strength",
        fields=["date", "track_id", "strength"],
        filters={"track_id": "AI"},
        start_date="2026-01-02",
        end_date="2026-01-31",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"] == [
        {"date": "2026-01-02", "track_id": "AI", "strength": 1.5},
        {"date": "2026-01-03", "track_id": "AI", "strength": 1.7},
    ]
    assert payload["meta"] == {
        "dataset": "demo.track_strength",
        "count": 2,
        "limit": 100000,
        "truncated": False,
        "columns": ["date", "track_id", "strength"],
    }


def test_dataset_query_reads_multiple_parquet_files(client, tmp_path) -> None:
    write_demo_dataset(tmp_path / "data", file_count=2)

    response = _post(client, "demo.track_strength")

    assert response.status_code == 200
    assert response.json()["meta"]["count"] == len(DEMO_ROWS)
    assert {row["track_id"] for row in response.json()["data"]} == {"AI", "BK"}


def test_dataset_query_applies_cap_and_marks_truncated(client, tmp_path, monkeypatch) -> None:
    write_demo_dataset(tmp_path / "data")
    monkeypatch.setenv("AXDATA_API_MAX_QUERY_ROWS", "2")

    response = _post(client, "demo.track_strength")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["data"]) == 2
    assert payload["meta"]["truncated"] is True
    assert payload["meta"]["count"] == 2
    assert payload["meta"]["limit"] == 2


def test_dataset_query_cap_no_truncation_when_fits(client, tmp_path, monkeypatch) -> None:
    write_demo_dataset(tmp_path / "data")
    monkeypatch.setenv("AXDATA_API_MAX_QUERY_ROWS", "5")

    response = _post(client, "demo.track_strength")

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["truncated"] is False
    assert payload["meta"]["count"] == 3
    assert payload["meta"]["limit"] == 5


def test_dataset_query_explicit_limit_within_cap(client, tmp_path, monkeypatch) -> None:
    write_demo_dataset(tmp_path / "data")
    monkeypatch.setenv("AXDATA_API_MAX_QUERY_ROWS", "5")

    response = _post(client, "demo.track_strength", limit=1)

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["data"]) == 1
    assert payload["meta"]["truncated"] is False
    assert payload["meta"]["limit"] == 1


def test_dataset_query_explicit_limit_over_cap_returns_413(client, tmp_path, monkeypatch) -> None:
    write_demo_dataset(tmp_path / "data")
    monkeypatch.setenv("AXDATA_API_MAX_QUERY_ROWS", "2")

    response = _post(client, "demo.track_strength", limit=3)

    assert response.status_code == 413
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "QUERY_LIMIT_EXCEEDED"
    assert payload["meta"]["max_limit"] == 2
    assert payload["meta"]["requested_limit"] == 3


def test_dataset_query_invalid_cap_env_falls_back_to_default(client, tmp_path, monkeypatch) -> None:
    write_demo_dataset(tmp_path / "data")
    monkeypatch.setenv("AXDATA_API_MAX_QUERY_ROWS", "not-a-number")

    response = _post(client, "demo.track_strength")

    assert response.status_code == 200
    assert response.json()["meta"]["limit"] == 100000

    over = _post(client, "demo.track_strength", limit=100001)
    assert over.status_code == 413


def test_dataset_query_unknown_dataset_returns_404(client, tmp_path) -> None:
    response = _post(client, "no.such.dataset")

    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "DATASET_NOT_FOUND"
    assert "no.such.dataset" in payload["error"]["message"]


def test_dataset_query_missing_output_files_returns_404(client, tmp_path) -> None:
    write_demo_declaration_log(tmp_path / "data")

    response = _post(client, "demo.track_strength")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DATASET_NOT_FOUND"


def test_dataset_query_unknown_field_returns_400(client, tmp_path) -> None:
    write_demo_dataset(tmp_path / "data")

    response = _post(client, "demo.track_strength", fields=["date", "no.such"])

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "DATASET_QUERY_ERROR"
    assert "no.such" in payload["error"]["message"]


def test_dataset_query_unknown_filter_field_returns_400(client, tmp_path) -> None:
    write_demo_dataset(tmp_path / "data")

    response = _post(client, "demo.track_strength", filters={"no.such": 1})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "DATASET_QUERY_ERROR"


def test_dataset_query_dates_without_date_field_returns_400(client, tmp_path) -> None:
    write_scan_only_dataset(
        tmp_path / "data",
        dataset="demo.symbols",
        rows=[{"symbol": "000001.SZ", "name": "平安银行"}],
    )

    response = _post(
        client,
        "demo.symbols",
        start_date="2026-01-01",
        end_date="2026-01-31",
    )

    assert response.status_code == 400
    assert "date_field" in response.json()["error"]["message"]


def test_dataset_query_malformed_date_returns_400(client, tmp_path) -> None:
    write_demo_dataset(tmp_path / "data")

    response = _post(client, "demo.track_strength", start_date="01/02/2026")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "DATASET_QUERY_ERROR"


def test_dataset_query_negative_limit_returns_400(client, tmp_path) -> None:
    write_demo_dataset(tmp_path / "data")

    response = _post(client, "demo.track_strength", limit=-1)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "DATASET_QUERY_ERROR"


def test_dataset_query_catalog_conflict_returns_400(client, tmp_path) -> None:
    data_root = tmp_path / "data"
    parquet_dir = write_demo_parquet(data_root)
    write_demo_run(
        data_root,
        run_id="run_conflict_a",
        parquet_path=parquet_dir,
        primary_key=["date", "track_id"],
        finished_at="2026-01-31T10:00:00+00:00",
    )
    write_demo_run(
        data_root,
        run_id="run_conflict_b",
        parquet_path=parquet_dir,
        primary_key=["date", "symbol"],
        finished_at="2026-01-31T11:00:00+00:00",
    )

    response = _post(client, "demo.track_strength")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "DATASET_QUERY_ERROR"


def test_dataset_query_non_parquet_dataset_returns_400(client, tmp_path) -> None:
    csv_dir = tmp_path / "data" / "snapshot" / "demo.csvdata" / "csv"
    csv_dir.mkdir(parents=True)
    pd.DataFrame([{"symbol": "000001.SZ"}]).to_csv(csv_dir / "part-0.csv", index=False)

    response = _post(client, "demo.csvdata")

    assert response.status_code == 400
    assert "only Parquet" in response.json()["error"]["message"]


def test_dataset_query_binds_sql_injection_filter_values(client, tmp_path) -> None:
    write_demo_dataset(
        tmp_path / "data",
        rows=[
            {"date": "2026-01-02", "track_id": TRICKY_TRACK_ID, "strength": 9.9, "source": "demo"},
            *DEMO_ROWS,
        ],
    )

    matched = _post(
        client,
        "demo.track_strength",
        fields=["track_id"],
        filters={"track_id": TRICKY_TRACK_ID},
    )
    assert matched.status_code == 200
    assert matched.json()["data"] == [{"track_id": TRICKY_TRACK_ID}]

    injected = _post(
        client,
        "demo.track_strength",
        fields=["track_id"],
        filters={"track_id": "AI' OR '1'='1"},
    )
    assert injected.status_code == 200
    assert injected.json()["data"] == []


def test_dataset_query_empty_result_returns_empty_list_with_columns(client, tmp_path) -> None:
    write_demo_dataset(tmp_path / "data")

    response = _post(
        client,
        "demo.track_strength",
        start_date="2027-01-01",
        end_date="2027-01-31",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"] == []
    assert payload["meta"]["count"] == 0
    assert payload["meta"]["truncated"] is False
    assert payload["meta"]["columns"] == ["date", "track_id", "strength", "source"]


def test_dataset_query_hive_date_partition_empty_result(client, tmp_path) -> None:
    write_hive_date_partitioned_dataset(tmp_path / "data")

    response = _post(
        client,
        "demo.hive_daily",
        fields=["date", "track_id", "strength"],
        start_date="2026-01-05",
        end_date="2026-01-31",
    )

    assert response.status_code == 200
    assert response.json()["data"] == []
    assert response.json()["meta"]["columns"] == ["date", "track_id", "strength"]


def test_dataset_query_core_unavailable_returns_503(client, tmp_path, monkeypatch) -> None:
    write_demo_dataset(tmp_path / "data")

    def missing_core(*args, **kwargs):
        raise ImportError("duckdb is not installed")

    import axdata_core

    monkeypatch.setattr(axdata_core, "query_dataset", missing_core)

    response = _post(client, "demo.track_strength")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CORE_UNAVAILABLE"


def test_dataset_query_matches_local_core_query(client, tmp_path) -> None:
    data_root = tmp_path / "data"
    write_demo_dataset(data_root)

    response = _post(
        client,
        "demo.track_strength",
        fields=["track_id", "strength", "date"],
        filters={"track_id": ["AI", "BK"]},
        start_date="20260102",
        end_date="20260103",
        limit=2,
    )
    frame = query_dataset(
        "demo.track_strength",
        data_root=data_root,
        fields=["track_id", "strength", "date"],
        filters={"track_id": ["AI", "BK"]},
        start_date="20260102",
        end_date="20260103",
        limit=2,
    )

    assert response.status_code == 200
    assert response.json()["data"] == frame.to_dict(orient="records")


def test_dataset_list_and_inspect_routes_expose_fixture_dataset(client, tmp_path) -> None:
    write_demo_dataset(tmp_path / "data")

    list_response = client.get("/v1/data/datasets")
    inspect_response = client.get("/v1/data/datasets/demo.track_strength")

    assert list_response.status_code == 200
    datasets = list_response.json()["data"]
    assert any(item["dataset"] == "demo.track_strength" for item in datasets)
    assert inspect_response.status_code == 200
    assert inspect_response.json()["data"]["dataset"] == "demo.track_strength"
