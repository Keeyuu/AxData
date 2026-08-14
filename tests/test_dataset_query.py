"""Tests for the generic dataset query engine (AXI-020).

Fixture follows docs/plan/axdata-integration/13-coding-entrypoint.md §2: a
dataset completely absent from the core ``SCHEMAS``, written as

    data/factor/dataset=demo.track_strength/parquet/year=2026/part-0.parquet

with columns ``date | track_id | strength | source``, plus a Collector
declaration persisted in the same JSON run-log shape the collector engine
writes next to outputs (``DownloadMetadataWriter.write_run_log``). The core
tests prove the dataset is queryable through the dynamic catalog without any
static ``SCHEMAS`` entry.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from axdata_core import get_schema, query_dataset
from axdata_core.collector_scheduler import CollectorRun, CollectorSchedulerStore
from axdata_core.data_browser import preview_dataset
from axdata_core.dataset_catalog import DatasetCatalogError, DatasetNotFoundError
from axdata_core.dataset_query import DatasetQueryError

DEMO_DECLARATION = {
    "dataset_id": "demo.track_strength",
    "layer": "factor",
    "formats": ["parquet"],
    "primary_key": ["date", "track_id"],
    "date_field": "date",
    "partition_by": ["year"],
    "write_mode": "append",
}

DEMO_ROWS = [
    {"date": "2026-01-02", "track_id": "AI", "strength": 1.5, "source": "demo"},
    {"date": "2026-01-03", "track_id": "AI", "strength": 1.7, "source": "demo"},
    {"date": "2026-01-02", "track_id": "BK", "strength": 0.8, "source": "demo"},
]

DEMO_LOG_JOB_ID = "run_demo_track_strength_20260131_abcdef12"


def _write_demo_parquet(
    data_root: Path,
    *,
    rows: list[dict] | None = None,
    file_count: int = 1,
) -> Path:
    """Write the demo fixture parquet file(s) and return the format directory."""

    parquet_dir = data_root / "factor" / "dataset=demo.track_strength" / "parquet"
    partition_dir = parquet_dir / "year=2026"
    partition_dir.mkdir(parents=True)
    records = rows if rows is not None else DEMO_ROWS
    per_file = max((len(records) + file_count - 1) // file_count, 1)
    for index in range(file_count):
        chunk = records[index * per_file : (index + 1) * per_file]
        if chunk:
            pd.DataFrame(chunk).to_parquet(
                partition_dir / f"part-{index}.parquet",
                engine="pyarrow",
                index=False,
            )
    return parquet_dir


def _write_demo_declaration_log(
    data_root: Path,
    *,
    parquet_path: str | None = None,
) -> Path:
    """Write a Collector declaration in the engine run-log JSON format."""

    log_dir = data_root / "factor" / "dataset=demo.track_strength" / "logs"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "demo.track_strength_20260131_202601.json"
    default_parquet = str(data_root / "factor" / "dataset=demo.track_strength" / "parquet")
    payload = {
        "job_id": DEMO_LOG_JOB_ID,
        "interface_name": "demo.track_strength",
        "collector_id": "demo.track_strength.snapshot",
        "collector_plugin_id": "axdata.collector.demo",
        "dataset_id": "demo.track_strength",
        "runner_entry": "demo.collectors:track_strength",
        "status": "success",
        "row_count": len(DEMO_ROWS),
        "output_paths": {"parquet": parquet_path if parquet_path is not None else default_parquet},
        "output": dict(DEMO_DECLARATION),
        "write_metadata": {
            "write_mode": "append",
            "partition_by": ["year"],
            "primary_key": ["date", "track_id"],
            "date_field": "date",
        },
        "quality": {
            "quality_status": "ok",
            "row_count_value": len(DEMO_ROWS),
            "schema_columns": ["date", "track_id", "strength", "source"],
            "write_primary_key": ["date", "track_id"],
            "write_date_field": "date",
            "write_mode": "append",
            "partition_by": ["year"],
        },
        "started_at": "2026-01-31T09:00:00+00:00",
        "finished_at": "2026-01-31T10:00:00+00:00",
        "log_path": str(log_path),
    }
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return log_path


def _write_demo_dataset(data_root: Path, **kwargs) -> Path:
    parquet_dir = _write_demo_parquet(data_root, **kwargs)
    _write_demo_declaration_log(data_root)
    return parquet_dir


def _write_hive_date_partitioned_dataset(data_root: Path) -> Path:
    """Write a dataset partitioned on its date_field (hive ``date=`` dirs)."""

    parquet_dir = data_root / "factor" / "dataset=demo.hive_daily" / "parquet"
    partition_dir = parquet_dir / "date=2026-01-03"
    partition_dir.mkdir(parents=True)
    pd.DataFrame(
        [{"track_id": "AI", "strength": 1.5}, {"track_id": "BK", "strength": 0.8}]
    ).to_parquet(partition_dir / "part-0.parquet", engine="pyarrow", index=False)
    log_dir = data_root / "factor" / "dataset=demo.hive_daily" / "logs"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "demo.hive_daily_20260131_202601.json"
    payload = {
        "job_id": "run_demo_hive_daily_20260131_abcdef12",
        "interface_name": "demo.hive_daily",
        "collector_id": "demo.hive_daily.snapshot",
        "collector_plugin_id": "axdata.collector.demo",
        "dataset_id": "demo.hive_daily",
        "status": "success",
        "row_count": 2,
        "output_paths": {"parquet": str(parquet_dir)},
        "output": {
            "dataset_id": "demo.hive_daily",
            "layer": "factor",
            "formats": ["parquet"],
            "primary_key": ["date", "track_id"],
            "date_field": "date",
            "partition_by": ["date"],
            "write_mode": "append",
        },
        "write_metadata": {
            "write_mode": "append",
            "partition_by": ["date"],
            "primary_key": ["date", "track_id"],
            "date_field": "date",
        },
        "quality": {
            "quality_status": "ok",
            "row_count_value": 2,
            "schema_columns": ["date", "track_id", "strength"],
            "write_primary_key": ["date", "track_id"],
            "write_date_field": "date",
            "write_mode": "append",
            "partition_by": ["date"],
        },
        "started_at": "2026-01-31T09:00:00+00:00",
        "finished_at": "2026-01-31T10:00:00+00:00",
        "log_path": str(log_dir / "demo.hive_daily_20260131_202601.json"),
    }
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return parquet_dir


def _write_scan_only_dataset(data_root: Path, *, dataset: str, rows: list[dict]) -> Path:
    """Write a plain parquet dataset with no declaration (catalog scan source)."""

    parquet_dir = data_root / "snapshot" / dataset / "parquet"
    parquet_dir.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(parquet_dir / "part-0.parquet", engine="pyarrow", index=False)
    return parquet_dir


def test_dynamic_plugin_dataset_is_queryable_without_core_schema(tmp_path) -> None:
    data_root = tmp_path / "data"
    _write_demo_dataset(data_root)

    frame = query_dataset(
        "demo.track_strength",
        data_root=data_root,
        fields=["date", "track_id", "strength"],
        filters={"track_id": "AI"},
        start_date="2026-01-02",
        end_date="2026-01-31",
    )

    assert list(frame.columns) == ["date", "track_id", "strength"]
    assert set(frame["track_id"]) == {"AI"}
    assert set(frame["date"]) == {"2026-01-02", "2026-01-03"}
    with pytest.raises(KeyError):
        get_schema("demo.track_strength")


def test_query_dataset_returns_all_columns_and_rows_by_default(tmp_path) -> None:
    data_root = tmp_path / "data"
    _write_demo_dataset(data_root)

    frame = query_dataset("demo.track_strength", data_root=data_root)

    assert list(frame.columns) == ["date", "track_id", "strength", "source"]
    assert len(frame) == 3


def test_query_dataset_reads_multiple_parquet_files_and_hive_partitions(tmp_path) -> None:
    data_root = tmp_path / "data"
    parquet_dir = _write_demo_dataset(data_root, file_count=2)
    other_year = parquet_dir / "year=2025"
    other_year.mkdir(parents=True)
    pd.DataFrame(
        [{"date": "2025-12-31", "track_id": "AI", "strength": 0.5, "source": "demo"}]
    ).to_parquet(other_year / "part-0.parquet", engine="pyarrow", index=False)

    frame = query_dataset("demo.track_strength", data_root=data_root)

    assert len(frame) == 4
    assert set(frame["date"]) == {"2025-12-31", "2026-01-02", "2026-01-03"}

    hive = query_dataset("demo.track_strength", data_root=data_root, fields=["date", "year"])
    assert list(hive.columns) == ["date", "year"]
    assert set(hive["year"]) == {2025, 2026}


def test_query_dataset_union_by_name_fills_missing_columns_with_null(tmp_path) -> None:
    data_root = tmp_path / "data"
    parquet_dir = _write_demo_dataset(data_root)
    other_year = parquet_dir / "year=2025"
    other_year.mkdir(parents=True)
    pd.DataFrame([{"date": "2025-12-31", "track_id": "AI", "strength": 0.5}]).to_parquet(
        other_year / "part-0.parquet", engine="pyarrow", index=False
    )

    frame = query_dataset(
        "demo.track_strength",
        data_root=data_root,
        fields=["date", "track_id", "source"],
        filters={"track_id": "AI"},
    )

    assert len(frame) == 3
    assert set(frame["source"]) == {"demo", None}


def test_query_dataset_returns_columns_in_requested_order(tmp_path) -> None:
    data_root = tmp_path / "data"
    _write_demo_dataset(data_root)

    frame = query_dataset(
        "demo.track_strength",
        data_root=data_root,
        fields=["strength", "track_id", "date"],
        limit=1,
    )

    assert list(frame.columns) == ["strength", "track_id", "date"]


def test_query_dataset_filters_by_date_range_dashed_and_compact(tmp_path) -> None:
    data_root = tmp_path / "data"
    _write_demo_dataset(data_root)

    dashed = query_dataset(
        "demo.track_strength",
        data_root=data_root,
        start_date="2026-01-03",
        end_date="2026-01-31",
    )
    assert set(dashed["date"]) == {"2026-01-03"}

    compact = query_dataset(
        "demo.track_strength",
        data_root=data_root,
        start_date="20260103",
        end_date="20260131",
    )
    assert list(compact["date"]) == ["2026-01-03"]

    end_only = query_dataset(
        "demo.track_strength",
        data_root=data_root,
        end_date="2026-01-02",
    )
    assert set(end_only["date"]) == {"2026-01-02"}

    no_match = query_dataset(
        "demo.track_strength",
        data_root=data_root,
        start_date="2027-01-01",
        end_date="2027-01-31",
    )
    assert no_match.empty
    assert list(no_match.columns) == ["date", "track_id", "strength", "source"]


def test_query_dataset_combines_filters_and_supports_in_lists(tmp_path) -> None:
    data_root = tmp_path / "data"
    _write_demo_dataset(data_root)

    combined = query_dataset(
        "demo.track_strength",
        data_root=data_root,
        filters={"track_id": "AI", "strength": 1.5},
    )
    assert len(combined) == 1
    assert combined.iloc[0]["date"] == "2026-01-02"

    in_list = query_dataset(
        "demo.track_strength",
        data_root=data_root,
        filters={"track_id": ["AI", "BK"]},
    )
    assert len(in_list) == 3

    empty_list = query_dataset(
        "demo.track_strength",
        data_root=data_root,
        filters={"track_id": []},
    )
    assert empty_list.empty
    assert list(empty_list.columns) == ["date", "track_id", "strength", "source"]


def test_query_dataset_limit_bounds_rows_and_none_means_no_truncation(tmp_path) -> None:
    data_root = tmp_path / "data"
    _write_demo_dataset(data_root)

    limited = query_dataset(
        "demo.track_strength", data_root=data_root, fields=["track_id"], limit=2
    )
    assert len(limited) == 2

    unlimited = query_dataset("demo.track_strength", data_root=data_root)
    assert len(unlimited) == 3


def test_query_dataset_rejects_unknown_fields_and_filter_fields(tmp_path) -> None:
    data_root = tmp_path / "data"
    _write_demo_dataset(data_root)

    with pytest.raises(DatasetQueryError, match="Unknown field"):
        query_dataset("demo.track_strength", data_root=data_root, fields=["date", "no.such"])
    with pytest.raises(DatasetQueryError, match="Unknown filter field"):
        query_dataset("demo.track_strength", data_root=data_root, filters={"no.such": 1})


def test_query_dataset_rejects_dates_without_date_field(tmp_path) -> None:
    data_root = tmp_path / "data"
    _write_demo_dataset(data_root)
    _write_scan_only_dataset(
        data_root,
        dataset="demo.symbols",
        rows=[{"symbol": "000001.SZ", "name": "平安银行"}],
    )

    with pytest.raises(DatasetQueryError, match="does not define a date_field"):
        query_dataset(
            "demo.symbols",
            data_root=data_root,
            start_date="2026-01-01",
            end_date="2026-01-31",
        )
    with pytest.raises(DatasetQueryError, match="YYYY-MM-DD"):
        query_dataset("demo.track_strength", data_root=data_root, start_date="01/02/2026")


def test_query_dataset_binds_filter_values_with_sql_characters(tmp_path) -> None:
    data_root = tmp_path / "data"
    tricky_id = "O'Neil; DROP TABLE demo--"
    _write_demo_dataset(
        data_root,
        rows=[
            {"date": "2026-01-02", "track_id": tricky_id, "strength": 9.9, "source": "demo"},
            {"date": "2026-01-02", "track_id": 'A"B', "strength": 1.1, "source": "demo"},
            *DEMO_ROWS,
        ],
    )

    matched = query_dataset(
        "demo.track_strength",
        data_root=data_root,
        fields=["track_id"],
        filters={"track_id": tricky_id},
    )
    assert set(matched["track_id"]) == {tricky_id}

    quoted = query_dataset(
        "demo.track_strength",
        data_root=data_root,
        fields=["track_id"],
        filters={"track_id": 'A"B'},
    )
    assert set(quoted["track_id"]) == {'A"B'}

    injected = query_dataset(
        "demo.track_strength",
        data_root=data_root,
        fields=["track_id"],
        filters={"track_id": "AI' OR '1'='1"},
    )
    assert injected.empty

    comment = query_dataset(
        "demo.track_strength",
        data_root=data_root,
        fields=["track_id"],
        filters={"track_id": "AI --'"},
    )
    assert comment.empty

    intact = query_dataset("demo.track_strength", data_root=data_root)
    assert len(intact) == 5


def test_query_dataset_empty_partition_match_returns_empty_frame_with_columns(tmp_path) -> None:
    data_root = tmp_path / "data"
    _write_hive_date_partitioned_dataset(data_root)

    empty = query_dataset(
        "demo.hive_daily",
        data_root=data_root,
        fields=["date", "track_id", "strength"],
        start_date="2026-01-05",
        end_date="2026-01-31",
    )
    assert empty.empty
    assert list(empty.columns) == ["date", "track_id", "strength"]

    matched = query_dataset(
        "demo.hive_daily",
        data_root=data_root,
        fields=["track_id"],
        start_date="2026-01-01",
        end_date="2026-01-04",
    )
    assert set(matched["track_id"]) == {"AI", "BK"}


def test_preview_dataset_matches_query_dataset_limit_100(tmp_path) -> None:
    data_root = tmp_path / "data"
    _write_demo_dataset(data_root)

    preview = preview_dataset("demo.track_strength", data_root=data_root, limit=100)
    frame = query_dataset("demo.track_strength", data_root=data_root, limit=100)

    assert preview.limit == 100
    assert preview.columns == list(frame.columns)
    assert preview.rows == frame.to_dict(orient="records")

    filtered_preview = preview_dataset(
        "demo.track_strength",
        data_root=data_root,
        filters={"track_id": "AI"},
        start="2026-01-03",
        end="2026-01-31",
        limit=100,
    )
    filtered_frame = query_dataset(
        "demo.track_strength",
        data_root=data_root,
        filters={"track_id": "AI"},
        start_date="2026-01-03",
        end_date="2026-01-31",
        limit=100,
    )
    assert filtered_preview.rows == filtered_frame.to_dict(orient="records")


def test_query_dataset_rejects_non_parquet_dataset(tmp_path) -> None:
    data_root = tmp_path / "data"
    csv_dir = data_root / "snapshot" / "demo.csvdata" / "csv"
    csv_dir.mkdir(parents=True)
    pd.DataFrame([{"symbol": "000001.SZ"}]).to_csv(csv_dir / "part-0.csv", index=False)

    with pytest.raises(DatasetQueryError, match="only Parquet datasets"):
        query_dataset("demo.csvdata", data_root=data_root)


def test_query_dataset_raises_for_unknown_dataset(tmp_path) -> None:
    with pytest.raises(DatasetNotFoundError):
        query_dataset("no.such.dataset", data_root=tmp_path / "data")


def test_query_dataset_raises_when_declared_output_files_are_missing(tmp_path) -> None:
    data_root = tmp_path / "data"
    _write_demo_declaration_log(data_root)

    with pytest.raises(FileNotFoundError):
        query_dataset("demo.track_strength", data_root=data_root)


def test_query_dataset_rejects_paths_escaping_data_root(tmp_path) -> None:
    data_root = tmp_path / "data"
    _write_demo_parquet(data_root)
    store = CollectorSchedulerStore(data_root=data_root)
    store.create_run(
        CollectorRun(
            run_id="run_escape",
            task_id="demo_task",
            collector_name="evil.collector",
            trigger_type="manual",
            status="success",
            output_paths={"parquet": "../../evil.parquet"},
            result={
                "download_result": {
                    "dataset_id": "evil.dataset",
                    "interface_name": "evil.dataset",
                    "output_paths": {"parquet": "../../evil.parquet"},
                },
            },
        )
    )

    with pytest.raises(DatasetCatalogError):
        query_dataset("evil.dataset", data_root=data_root)


def test_query_dataset_rejects_fields_declared_but_missing_from_files(tmp_path) -> None:
    data_root = tmp_path / "data"
    parquet_dir = data_root / "factor" / "dataset=demo.track_strength" / "parquet"
    parquet_dir.mkdir(parents=True)
    pd.DataFrame([{"date": "2026-01-02", "track_id": "AI", "strength": 1.5}]).to_parquet(
        parquet_dir / "part-0.parquet", engine="pyarrow", index=False
    )
    _write_demo_declaration_log(data_root)

    with pytest.raises(DatasetQueryError, match="missing from the actual Parquet schema"):
        query_dataset(
            "demo.track_strength",
            data_root=data_root,
            fields=["date", "track_id", "source"],
        )

    core_columns = query_dataset(
        "demo.track_strength",
        data_root=data_root,
        fields=["date", "track_id", "strength"],
    )
    assert len(core_columns) == 1


def test_query_dataset_end_date_includes_final_day_for_datetime64_column(tmp_path) -> None:
    """datetime64[ns] date columns must not lose the end_date day.

    Casting a timestamp to VARCHAR appends " 00:00:00"; without taking
    the date part the same-day end bound compares greater and silently
    drops the final row (defect found by the AXI-060 exporter).
    """

    data_root = tmp_path / "data"
    parquet_dir = data_root / "factor" / "dataset=demo.track_strength" / "parquet"
    parquet_dir.mkdir(parents=True)
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-09"]),
            "track_id": ["AI", "AI", "AI"],
            "strength": [1.0, 2.0, 3.0],
            "source": ["demo", "demo", "demo"],
        }
    )
    frame.to_parquet(parquet_dir / "part-0.parquet", engine="pyarrow", index=False)
    _write_demo_declaration_log(data_root)

    result = query_dataset(
        "demo.track_strength",
        data_root=data_root,
        start_date="2026-01-01",
        end_date="2026-01-09",
    )
    assert len(result) == 3, "end_date bound must include the final datetime64 day"
    assert str(result["date"].iloc[-1]).startswith("2026-01-09")
