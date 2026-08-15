"""Tests for the dynamic dataset catalog (AXI-010).

Fixture follows docs/plan/axdata-integration/13-coding-entrypoint.md §2: a
dataset that is completely absent from the core ``SCHEMAS``, written as

    data/factor/dataset=demo.track_strength/parquet/year=2026/part-0.parquet

with columns ``date | track_id | strength | source``, plus a Collector
declaration persisted in the same JSON run-log shape the collector engine
writes next to outputs (``DownloadMetadataWriter.write_run_log``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from axdata_core import get_dataset_descriptor, get_schema, list_dataset_descriptors
from axdata_core.collector_scheduler import CollectorRun, CollectorSchedulerStore
from axdata_core.dataset_catalog import (
    CatalogConflictError,
    DatasetCatalogError,
    DatasetNotFoundError,
)

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


def _write_demo_parquet(data_root: Path, *, rows: list[dict] | None = None) -> Path:
    """Write the demo fixture parquet and return the format directory."""

    parquet_dir = data_root / "factor" / "dataset=demo.track_strength" / "parquet"
    partition_dir = parquet_dir / "year=2026"
    partition_dir.mkdir(parents=True)
    pd.DataFrame(rows if rows is not None else DEMO_ROWS).to_parquet(
        partition_dir / "part-0.parquet",
        engine="pyarrow",
        index=False,
    )
    return parquet_dir


def _write_demo_declaration_log(
    data_root: Path,
    *,
    parquet_path: str | None = None,
    declaration: dict | None = None,
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
        "output": declaration if declaration is not None else dict(DEMO_DECLARATION),
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


def _write_demo_run(
    data_root: Path,
    *,
    run_id: str,
    parquet_path: Path,
    primary_key: list[str],
    finished_at: str,
) -> None:
    """Persist one successful Collector run through the scheduler store."""

    store = CollectorSchedulerStore(data_root=data_root)
    store.create_run(
        CollectorRun(
            run_id=run_id,
            task_id="demo_task",
            collector_name="demo.track_strength.snapshot",
            trigger_type="manual",
            status="success",
            provider_id="axdata.collector.demo",
            output_paths={"parquet": str(parquet_path)},
            result={
                "download_result": {
                    "dataset_id": "demo.track_strength",
                    "interface_name": "demo.track_strength",
                    "output_paths": {"parquet": str(parquet_path)},
                    "output": {
                        "layer": "factor",
                        "formats": ["parquet"],
                        "primary_key": primary_key,
                        "date_field": "date",
                        "partition_by": ["year"],
                        "write_mode": "append",
                    },
                    "quality": {
                        "quality_status": "ok",
                        "write_primary_key": primary_key,
                        "write_date_field": "date",
                        "write_mode": "append",
                        "partition_by": ["year"],
                    },
                },
            },
            finished_at=finished_at,
            created_at=finished_at,
            updated_at=finished_at,
        )
    )


def test_dynamic_plugin_dataset_has_descriptor_without_core_schema(tmp_path) -> None:
    data_root = tmp_path / "data"
    _write_demo_parquet(data_root)
    _write_demo_declaration_log(data_root)

    descriptor = get_dataset_descriptor("demo.track_strength", data_root=data_root)

    assert descriptor.dataset_id == "demo.track_strength"
    assert descriptor.layer == "factor"
    assert descriptor.format == "parquet"
    assert descriptor.primary_key == ("date", "track_id")
    assert descriptor.date_field == "date"
    assert descriptor.partition_by == ("year",)
    assert descriptor.write_mode == "append"
    assert descriptor.columns == ("date", "track_id", "strength", "source")
    assert descriptor.paths == (
        (data_root / "factor" / "dataset=demo.track_strength" / "parquet").resolve(),
    )
    assert descriptor.source_runs == (DEMO_LOG_JOB_ID,)
    assert descriptor.updated_at == "2026-01-31T10:00:00+00:00"
    assert descriptor.declaration.get("dataset_id") == "demo.track_strength"

    with pytest.raises(KeyError):
        get_schema("demo.track_strength")


def test_list_dataset_descriptors_returns_declared_scan_and_core_datasets(tmp_path) -> None:
    data_root = tmp_path / "data"
    _write_demo_parquet(data_root)
    _write_demo_declaration_log(data_root)
    scan_dir = data_root / "snapshot" / "demo.symbols" / "parquet"
    scan_dir.mkdir(parents=True)
    pd.DataFrame([{"symbol": "000001.SZ", "name": "平安银行"}]).to_parquet(
        scan_dir / "part-0.parquet",
        engine="pyarrow",
        index=False,
    )

    descriptors = {item.dataset_id: item for item in list_dataset_descriptors(data_root=data_root)}

    assert "demo.track_strength" in descriptors
    assert descriptors["demo.track_strength"].primary_key == ("date", "track_id")
    assert "demo.symbols" in descriptors
    assert descriptors["demo.symbols"].layer == "snapshot"
    assert descriptors["demo.symbols"].paths == (scan_dir.resolve(),)
    assert descriptors["demo.symbols"].columns == ("symbol", "name")
    assert "daily" in descriptors
    assert descriptors["daily"].primary_key == ("instrument_id", "trade_time", "period")
    assert descriptors["daily"].date_field == "trade_time"
    assert descriptors["daily"].paths == ()


def test_get_descriptor_raises_for_unknown_dataset(tmp_path) -> None:
    with pytest.raises(DatasetNotFoundError):
        get_dataset_descriptor("no.such.dataset", data_root=tmp_path / "data")


def test_get_descriptor_raises_when_declared_output_files_are_missing(tmp_path) -> None:
    data_root = tmp_path / "data"
    _write_demo_declaration_log(data_root)

    with pytest.raises(FileNotFoundError):
        get_dataset_descriptor("demo.track_strength", data_root=data_root)


def test_incompatible_successful_run_declarations_raise_catalog_conflict(tmp_path) -> None:
    data_root = tmp_path / "data"
    parquet_dir = _write_demo_parquet(data_root)
    _write_demo_run(
        data_root,
        run_id="run_conflict_a",
        parquet_path=parquet_dir,
        primary_key=["date", "track_id"],
        finished_at="2026-01-31T10:00:00+00:00",
    )
    _write_demo_run(
        data_root,
        run_id="run_conflict_b",
        parquet_path=parquet_dir,
        primary_key=["date", "symbol"],
        finished_at="2026-01-31T11:00:00+00:00",
    )

    with pytest.raises(CatalogConflictError):
        list_dataset_descriptors(data_root=data_root)
    with pytest.raises(CatalogConflictError):
        get_dataset_descriptor("demo.track_strength", data_root=data_root)


def test_compatible_successful_runs_merge_without_conflict(tmp_path) -> None:
    data_root = tmp_path / "data"
    parquet_dir = _write_demo_parquet(data_root)
    for index in range(2):
        _write_demo_run(
            data_root,
            run_id=f"run_ok_{index}",
            parquet_path=parquet_dir,
            primary_key=["date", "track_id"],
            finished_at=f"2026-01-31T1{index}:00:00+00:00",
        )

    descriptor = get_dataset_descriptor("demo.track_strength", data_root=data_root)

    assert set(descriptor.source_runs) == {"run_ok_0", "run_ok_1"}
    assert descriptor.primary_key == ("date", "track_id")
    assert descriptor.date_field == "date"
    assert descriptor.updated_at == "2026-01-31T11:00:00+00:00"


def test_catalog_rejects_paths_escaping_data_root(tmp_path) -> None:
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
        list_dataset_descriptors(data_root=data_root)


def test_catalog_rejects_unknown_path_scheme(tmp_path) -> None:
    data_root = tmp_path / "data"
    store = CollectorSchedulerStore(data_root=data_root)
    store.create_run(
        CollectorRun(
            run_id="run_scheme",
            task_id="demo_task",
            collector_name="evil.collector",
            trigger_type="manual",
            status="success",
            output_paths={"parquet": "s3://bucket/demo.parquet"},
            result={
                "download_result": {
                    "dataset_id": "evil.dataset",
                    "interface_name": "evil.dataset",
                    "output_paths": {"parquet": "s3://bucket/demo.parquet"},
                },
            },
        )
    )

    with pytest.raises(DatasetCatalogError):
        get_dataset_descriptor("evil.dataset", data_root=data_root)


def test_declared_primary_key_missing_from_actual_parquet_raises_conflict(tmp_path) -> None:
    data_root = tmp_path / "data"
    parquet_dir = data_root / "factor" / "dataset=demo.track_strength" / "parquet"
    parquet_dir.mkdir(parents=True)
    pd.DataFrame([{"date": "2026-01-02", "strength": 1.5, "source": "demo"}]).to_parquet(
        parquet_dir / "part-0.parquet", engine="pyarrow", index=False
    )
    _write_demo_declaration_log(data_root)

    with pytest.raises(CatalogConflictError):
        get_dataset_descriptor("demo.track_strength", data_root=data_root)


def test_declared_schema_wins_over_actual_parquet_columns(tmp_path) -> None:
    data_root = tmp_path / "data"
    parquet_dir = data_root / "factor" / "dataset=demo.track_strength" / "parquet"
    parquet_dir.mkdir(parents=True)
    pd.DataFrame(
        [{"date": "2026-01-02", "track_id": "AI", "strength": 1.5, "source": "demo", "extra": 1}]
    ).to_parquet(parquet_dir / "part-0.parquet", engine="pyarrow", index=False)
    _write_demo_declaration_log(data_root)

    descriptor = get_dataset_descriptor("demo.track_strength", data_root=data_root)

    assert descriptor.columns == ("date", "track_id", "strength", "source")
    assert descriptor.primary_key == ("date", "track_id")
    assert descriptor.date_field == "date"


def test_core_schema_table_gets_compat_descriptor(tmp_path) -> None:
    data_root = tmp_path / "data"
    partition = data_root / "core" / "table=daily" / "trade_time=20240102"
    partition.mkdir(parents=True)
    pd.DataFrame(
        [{"instrument_id": "000001.SZ", "open": 10.0, "close": 10.2, "period": "day"}]
    ).to_parquet(partition / "part-0.parquet", engine="pyarrow", index=False)

    descriptor = get_dataset_descriptor("daily", data_root=data_root)

    assert descriptor.layer == "core"
    assert descriptor.format == "parquet"
    assert descriptor.primary_key == ("instrument_id", "trade_time", "period")
    assert descriptor.date_field == "trade_time"
    assert descriptor.paths == ((data_root / "core" / "table=daily").resolve(),)
    assert {"instrument_id", "open", "close", "period", "trade_time"} <= set(descriptor.columns)


def test_data_browser_lists_dynamic_plugin_dataset(tmp_path) -> None:
    from axdata_core.data_browser import list_datasets

    data_root = tmp_path / "data"
    _write_demo_parquet(data_root)
    _write_demo_declaration_log(data_root)

    datasets = {item.dataset: item for item in list_datasets(data_root=data_root)}

    summary = datasets["demo.track_strength"]
    assert summary.layer == "factor"
    assert summary.primary_key == ["date", "track_id"]
    assert summary.date_field == "date"
    assert summary.partition_by == ["year"]
    assert summary.write_mode == "append"
    assert summary.columns == ["date", "track_id", "strength", "source"]
    assert summary.row_count == 3
    assert summary.quality_status == "ok"
    assert summary.latest_run_id == DEMO_LOG_JOB_ID
    assert summary.latest_run_status == "success"
    assert summary.output_paths == {
        "parquet": str((data_root / "factor" / "dataset=demo.track_strength" / "parquet").resolve())
    }
