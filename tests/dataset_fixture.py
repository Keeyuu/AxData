"""Shared dataset fixture helpers for catalog/query/API/SDK tests.

Fixture follows docs/plan/axdata-integration/13-coding-entrypoint.md §2: a
dataset completely absent from the core ``SCHEMAS``, written as

    data/factor/dataset=demo.track_strength/parquet/year=2026/part-0.parquet

with columns ``date | track_id | strength | source``, plus a Collector
declaration persisted in the same JSON run-log shape the collector engine
writes next to outputs (``DownloadMetadataWriter.write_run_log``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from axdata_core.collector_scheduler import CollectorRun, CollectorSchedulerStore

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


def write_demo_parquet(
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


def write_demo_declaration_log(
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


def write_demo_dataset(data_root: Path, **kwargs) -> Path:
    parquet_dir = write_demo_parquet(data_root, **kwargs)
    write_demo_declaration_log(data_root)
    return parquet_dir


def write_hive_date_partitioned_dataset(data_root: Path) -> Path:
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


def write_scan_only_dataset(data_root: Path, *, dataset: str, rows: list[dict]) -> Path:
    """Write a plain parquet dataset with no declaration (catalog scan source)."""

    parquet_dir = data_root / "snapshot" / dataset / "parquet"
    parquet_dir.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(parquet_dir / "part-0.parquet", engine="pyarrow", index=False)
    return parquet_dir


def write_demo_run(
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
