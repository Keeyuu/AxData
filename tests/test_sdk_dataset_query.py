"""Tests for the SDK dataset methods in local and API modes (AXI-030).

The demo.track_strength fixture (absent from the core ``SCHEMAS``) is queried
through :class:`axdata.AxDataClient.datasets` / ``dataset`` / ``query_dataset``
in both backends. API mode uses a FastAPI TestClient as the requests session;
local mode talks directly to ``axdata_core``. The tests prove the two backends
return identical rows, treat fields/date bounds/empty results the same way,
and translate failures into the same :class:`axdata.AxDataError` categories.
"""

from __future__ import annotations

import axdata as ax
import pandas as pd
import pytest
from axdata_core import query_dataset
from fastapi.testclient import TestClient

from apps.api.main import app
from tests.dataset_fixture import (
    DEMO_ROWS,
    write_demo_dataset,
    write_scan_only_dataset,
)

TRICKY_TRACK_ID = "O'Neil; DROP TABLE demo--"


class NoHttpSession:
    def get(self, *args, **kwargs):
        raise AssertionError("local SDK backend must not issue HTTP GET requests")

    def post(self, *args, **kwargs):
        raise AssertionError("local SDK backend must not issue HTTP POST requests")


@pytest.fixture
def api_session(tmp_path, monkeypatch):
    monkeypatch.setenv("AXDATA_DATA_DIR", str(tmp_path / "data"))
    return TestClient(app)


def _local_client(root):
    return ax.AxDataClient(data_root=root, session=NoHttpSession())


def _api_client(api_session):
    return ax.AxDataClient(api_base="http://testserver", session=api_session)


def test_sdk_query_dataset_local_matches_core_query(tmp_path) -> None:
    root = tmp_path / "data"
    write_demo_dataset(root)

    sdk = _local_client(root)
    frame = sdk.query_dataset(
        "demo.track_strength",
        fields=["date", "track_id", "strength"],
        filters={"track_id": "AI"},
        start_date="2026-01-02",
        end_date="2026-01-31",
    )
    core_frame = query_dataset(
        "demo.track_strength",
        data_root=root,
        fields=["date", "track_id", "strength"],
        filters={"track_id": "AI"},
        start_date="2026-01-02",
        end_date="2026-01-31",
    )

    assert frame.to_dict(orient="records") == core_frame.to_dict(orient="records")


def test_sdk_query_dataset_api_matches_local_row_by_row(tmp_path, api_session) -> None:
    root = tmp_path / "data"
    write_demo_dataset(root)
    local = _local_client(root)
    api = _api_client(api_session)
    fields = ["track_id", "strength", "date"]

    local_frame = local.query_dataset(
        "demo.track_strength",
        fields=fields,
        filters={"track_id": ["AI", "BK"]},
        start_date="2026-01-02",
        end_date="2026-01-03",
    )
    api_frame = api.query_dataset(
        "demo.track_strength",
        fields=fields,
        filters={"track_id": ["AI", "BK"]},
        start_date="2026-01-02",
        end_date="2026-01-03",
    )

    assert api_frame.to_dict(orient="records") == local_frame.to_dict(orient="records")
    assert list(api_frame.columns) == fields


def test_sdk_query_dataset_api_string_fields_form(tmp_path, api_session) -> None:
    root = tmp_path / "data"
    write_demo_dataset(root)
    local = _local_client(root)
    api = _api_client(api_session)

    local_frame = local.query_dataset(
        "demo.track_strength", fields="date,track_id,strength", limit=1
    )
    api_frame = api.query_dataset(
        "demo.track_strength", fields="date,track_id,strength", limit=1
    )

    assert api_frame.to_dict(orient="records") == local_frame.to_dict(orient="records")
    assert list(api_frame.columns) == ["date", "track_id", "strength"]


def test_sdk_query_dataset_empty_result_same_columns_both_modes(tmp_path, api_session) -> None:
    root = tmp_path / "data"
    write_demo_dataset(root)
    local = _local_client(root)
    api = _api_client(api_session)

    local_frame = local.query_dataset(
        "demo.track_strength",
        start_date="2027-01-01",
        end_date="2027-01-31",
    )
    api_frame = api.query_dataset(
        "demo.track_strength",
        start_date="2027-01-01",
        end_date="2027-01-31",
    )

    assert local_frame.empty and api_frame.empty
    assert list(api_frame.columns) == list(local_frame.columns)


def test_sdk_query_dataset_binds_sql_injection_values_both_modes(tmp_path, api_session) -> None:
    root = tmp_path / "data"
    write_demo_dataset(
        root,
        rows=[
            {"date": "2026-01-02", "track_id": TRICKY_TRACK_ID, "strength": 9.9, "source": "demo"},
            *DEMO_ROWS,
        ],
    )
    local = _local_client(root)
    api = _api_client(api_session)

    for client in (local, api):
        matched = client.query_dataset(
            "demo.track_strength",
            fields=["track_id"],
            filters={"track_id": TRICKY_TRACK_ID},
        )
        assert matched.to_dict(orient="records") == [{"track_id": TRICKY_TRACK_ID}]
        injected = client.query_dataset(
            "demo.track_strength",
            fields=["track_id"],
            filters={"track_id": "AI' OR '1'='1"},
        )
        assert injected.empty


def test_sdk_query_dataset_unknown_dataset_same_error(tmp_path, api_session) -> None:
    root = tmp_path / "data"
    write_demo_dataset(root)
    local = _local_client(root)
    api = _api_client(api_session)

    for client in (local, api):
        with pytest.raises(ax.AxDataError) as exc_info:
            client.query_dataset("no.such.dataset")
        assert exc_info.value.status_code == 404
        assert exc_info.value.code == "DATASET_NOT_FOUND"


def test_sdk_query_dataset_unknown_field_same_error(tmp_path, api_session) -> None:
    root = tmp_path / "data"
    write_demo_dataset(root)
    local = _local_client(root)
    api = _api_client(api_session)

    for client in (local, api):
        with pytest.raises(ax.AxDataError) as exc_info:
            client.query_dataset("demo.track_strength", fields=["date", "no.such"])
        assert exc_info.value.status_code == 400
        assert exc_info.value.code == "DATASET_QUERY_ERROR"


def test_sdk_query_dataset_dates_without_date_field_raise_same_error_both_modes(
    tmp_path, api_session
) -> None:
    root = tmp_path / "data"
    write_scan_only_dataset(
        root,
        dataset="demo.symbols",
        rows=[{"symbol": "000001.SZ", "name": "平安银行"}],
    )
    local = _local_client(root)
    api = _api_client(api_session)

    for client in (local, api):
        with pytest.raises(ax.AxDataError) as exc_info:
            client.query_dataset(
                "demo.symbols",
                start_date="2026-01-01",
                end_date="2026-01-31",
            )
        assert exc_info.value.status_code == 400
        assert exc_info.value.code == "DATASET_QUERY_ERROR"


def test_sdk_query_dataset_local_ignores_api_cap(tmp_path, api_session, monkeypatch) -> None:
    root = tmp_path / "data"
    write_demo_dataset(root)
    monkeypatch.setenv("AXDATA_API_MAX_QUERY_ROWS", "2")

    local_frame = _local_client(root).query_dataset("demo.track_strength")
    api_frame = _api_client(api_session).query_dataset("demo.track_strength")

    assert len(local_frame) == 3
    assert len(api_frame) == 2


def test_sdk_query_dataset_api_limit_over_cap_413(tmp_path, api_session, monkeypatch) -> None:
    root = tmp_path / "data"
    write_demo_dataset(root)
    monkeypatch.setenv("AXDATA_API_MAX_QUERY_ROWS", "2")
    local = _local_client(root)
    api = _api_client(api_session)

    with pytest.raises(ax.AxDataError) as exc_info:
        api.query_dataset("demo.track_strength", limit=3)
    assert exc_info.value.status_code == 413
    assert exc_info.value.code == "QUERY_LIMIT_EXCEEDED"

    local_frame = local.query_dataset("demo.track_strength", limit=3)
    assert len(local_frame) == 3


def test_sdk_datasets_lists_same_dataset_ids_in_both_modes(tmp_path, api_session) -> None:
    root = tmp_path / "data"
    write_demo_dataset(root)
    local = _local_client(root)
    api = _api_client(api_session)

    local_ids = {item["dataset_id"] for item in local.datasets()}
    api_ids = {item["dataset"] for item in api.datasets()}

    assert "demo.track_strength" in local_ids
    assert "demo.track_strength" in api_ids


def test_sdk_datasets_local_returns_stable_descriptor_dicts(tmp_path) -> None:
    root = tmp_path / "data"
    write_demo_dataset(root)
    sdk = _local_client(root)

    datasets = {item["dataset_id"]: item for item in sdk.datasets()}

    demo = datasets["demo.track_strength"]
    assert demo["layer"] == "factor"
    assert demo["format"] == "parquet"
    assert demo["columns"] == ["date", "track_id", "strength", "source"]
    assert demo["primary_key"] == ["date", "track_id"]
    assert demo["date_field"] == "date"
    assert demo["partition_by"] == ["year"]
    assert demo["write_mode"] == "append"
    assert demo["paths"] == [
        str((root / "factor" / "dataset=demo.track_strength" / "parquet").resolve())
    ]
    assert isinstance(demo["declaration"], dict)


def test_sdk_dataset_local_and_api_expose_the_same_dataset(tmp_path, api_session) -> None:
    root = tmp_path / "data"
    write_demo_dataset(root)

    local = _local_client(root).dataset("demo.track_strength")
    api = _api_client(api_session).dataset("demo.track_strength")

    assert local["dataset_id"] == "demo.track_strength"
    assert api["dataset"] == "demo.track_strength"
    assert local["date_field"] == api["date_field"] == "date"
    assert local["primary_key"] == api["primary_key"] == ["date", "track_id"]


def test_sdk_dataset_unknown_raises_same_error_both_modes(tmp_path, api_session) -> None:
    root = tmp_path / "data"
    write_demo_dataset(root)
    local = _local_client(root)
    api = _api_client(api_session)

    for client in (local, api):
        with pytest.raises(ax.AxDataError) as exc_info:
            client.dataset("no.such.dataset")
        assert exc_info.value.status_code == 404
        assert exc_info.value.code == "DATASET_NOT_FOUND"


def test_sdk_query_dataset_returns_dataframe(tmp_path, api_session) -> None:
    root = tmp_path / "data"
    write_demo_dataset(root)

    for client in (_local_client(root), _api_client(api_session)):
        frame = client.query_dataset("demo.track_strength", limit=2)
        assert isinstance(frame, pd.DataFrame)
        assert len(frame) == 2
