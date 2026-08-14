"""Tiny deterministic AxData data-root fixture for the qlib exporter tests.

Layout follows the catalog contract (see tests/test_dataset_catalog.py in the
AxData repo): each dataset is a Parquet directory plus a Collector run-log
JSON that declares layer / primary key / date field. No network, no real
data, no pyqlib required.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from axdata_qlib import QlibExportSpec  # noqa: E402

WINDOW_START = "2026-01-05"
WINDOW_END = "2026-01-09"
#: Calendar dataset range; the first day after WINDOW_END is 2026-01-12.
CALENDAR_END = "2026-01-14"
CALENDAR_DATES = [
    "2026-01-05",
    "2026-01-06",
    "2026-01-07",
    "2026-01-08",
    "2026-01-09",
    "2026-01-12",
    "2026-01-13",
    "2026-01-14",
]

BARS = {
    "000001.SZ": [
        ("2026-01-05", 9.9, 10.3, 9.8, 10.0, 1_000_000),
        ("2026-01-06", 10.1, 10.4, 10.0, 10.2, 1_100_000),
        ("2026-01-07", 10.2, 10.3, 10.0, 10.1, 1_050_000),
        ("2026-01-08", 10.0, 10.4, 9.9, 10.3, 1_200_000),
        ("2026-01-09", 10.4, 10.6, 10.2, 10.5, 1_300_000),
    ],
    "600000.SH": [
        ("2026-01-05", 19.8, 20.2, 19.7, 20.0, 2_000_000),
        ("2026-01-06", 20.1, 20.6, 20.0, 20.4, 2_100_000),
        ("2026-01-07", 20.5, 20.5, 20.2, 20.3, 2_050_000),
        ("2026-01-08", 20.2, 20.8, 20.1, 20.6, 2_200_000),
        ("2026-01-09", 20.7, 20.9, 20.5, 20.8, 2_300_000),
    ],
}

INSTRUMENT_IDS = ["000001.SZ", "600000.SH"]


def make_tiny_data_root(
    tmp_path: Path,
    *,
    has_adj_factor: bool = True,
    calendar_dates: list[str] | None = None,
    drop_bars_field: str | None = None,
) -> Path:
    """Build the tiny AxData data root and return it."""
    root = tmp_path / "axdata_data"

    bars_rows = []
    for identifier, rows in BARS.items():
        for date, open_, high, low, close, volume in rows:
            amount = round(close * volume / 100.0, 2)
            row = {
                "instrument_id": identifier,
                "trade_date": pd.Timestamp(date).date(),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "amount": amount,
            }
            if drop_bars_field is not None:
                row.pop(drop_bars_field, None)
            bars_rows.append(row)
    _write_dataset(
        root,
        "tiny.bars",
        pd.DataFrame(bars_rows),
        primary_key=["instrument_id", "trade_date"],
        date_field="trade_date",
    )

    _write_dataset(
        root,
        "tiny.calendar",
        pd.DataFrame(
            {"trade_date": [pd.Timestamp(day).date() for day in calendar_dates or CALENDAR_DATES]}
        ),
        primary_key=["trade_date"],
        date_field="trade_date",
    )

    _write_dataset(
        root,
        "tiny.instruments",
        pd.DataFrame({"instrument_id": INSTRUMENT_IDS}),
        primary_key=["instrument_id"],
        date_field=None,
    )

    if has_adj_factor:
        adj_rows = []
        for identifier, rows in BARS.items():
            for date, *_rest in rows:
                adj_rows.append(
                    {
                        "instrument_id": identifier,
                        "trade_date": pd.Timestamp(date).date(),
                        "adj_factor": 1.0,
                    }
                )
        _write_dataset(
            root,
            "tiny.adj_factor",
            pd.DataFrame(adj_rows),
            primary_key=["instrument_id", "trade_date"],
            date_field="trade_date",
        )
    return root


def tiny_spec(*, adj_factor_dataset: str | None = "tiny.adj_factor") -> QlibExportSpec:
    return QlibExportSpec(
        instruments_dataset="tiny.instruments",
        calendar_dataset="tiny.calendar",
        bars_dataset="tiny.bars",
        adj_factor_dataset=adj_factor_dataset,
        start_date=WINDOW_START,
        end_date=WINDOW_END,
    )


@pytest.fixture
def tiny_data_root(tmp_path: Path) -> Path:
    return make_tiny_data_root(tmp_path)


def _write_dataset(
    root: Path,
    dataset_id: str,
    frame: pd.DataFrame,
    *,
    primary_key: list[str],
    date_field: str | None,
) -> None:
    """Write one catalogued dataset: Parquet output + Collector run log."""
    dataset_dir = root / "snapshot" / f"dataset={dataset_id}"
    parquet_dir = dataset_dir / "parquet"
    parquet_dir.mkdir(parents=True)
    frame.to_parquet(parquet_dir / "part-0.parquet", engine="pyarrow", index=False)

    log_dir = dataset_dir / "logs"
    log_dir.mkdir(parents=True)
    log_path = log_dir / f"{dataset_id}_20260110_000000.json"
    output = {
        "layer": "snapshot",
        "formats": ["parquet"],
        "primary_key": primary_key,
        "partition_by": [],
        "write_mode": "replace",
    }
    if date_field is not None:
        output["date_field"] = date_field
    write_metadata = dict(output)
    quality = {
        "quality_status": "ok",
        "row_count_value": len(frame),
        "schema_columns": list(frame.columns),
        "write_primary_key": primary_key,
        "write_mode": "replace",
        "partition_by": [],
    }
    if date_field is not None:
        quality["write_date_field"] = date_field
    payload = {
        "job_id": f"run_{dataset_id}_20260110_000000",
        "interface_name": dataset_id,
        "collector_id": f"{dataset_id}.snapshot",
        "collector_plugin_id": "axdata.collector.tiny",
        "dataset_id": dataset_id,
        "runner_entry": "tiny.collectors:collect",
        "status": "success",
        "row_count": len(frame),
        "output_paths": {"parquet": str(parquet_dir)},
        "output": output,
        "write_metadata": write_metadata,
        "quality": quality,
        "started_at": "2026-01-10T09:00:00+00:00",
        "finished_at": "2026-01-10T10:00:00+00:00",
        "log_path": str(log_path),
    }
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
