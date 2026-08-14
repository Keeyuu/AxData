"""AxData → Qlib materialized provider export (AXI-060).

Reads catalogued AxData datasets through ``axdata_core.query_dataset`` and
writes a Qlib 0.9.7 provider directory (see :mod:`axdata_qlib.writer`).

Semantics:

- the exported calendar always extends at least one trading day past the
  research ``end_date`` (ADR-0001 backtest boundary), taken from the calendar
  dataset; if the calendar dataset has no such day the export fails loudly;
- halted days inside the window are forward-filled (then back-filled at the
  head), matching Skynet's verified writer semantics — the binary format has
  no missing-value encoding and ``close`` must be nonzero from day one;
- V1 writes adjustment metadata only, it never recomputes prices: with an
  adj-factor dataset present the export is recorded as backward-adjusted
  ("后复权" 口径, prices assumed already adjusted), otherwise as unadjusted;
- an existing non-empty ``output_dir`` is refused (rebuild-only artifacts).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from axdata_core.dataset_catalog import get_dataset_descriptor
from axdata_core.dataset_query import DatasetQueryError, query_dataset

from .calendar import normalize_date, resolve_export_calendar
from .errors import QlibExportError
from .validate import compute_content_hash, verify_layout
from .writer import write_qlib_dir

ADJUSTMENT_FACTOR_FIELD = "adj_factor"


@dataclass(frozen=True, slots=True)
class QlibExportSpec:
    """Configuration for one AxData → Qlib export (docs/plan/06 §3)."""

    instruments_dataset: str
    calendar_dataset: str
    bars_dataset: str
    adj_factor_dataset: str | None
    start_date: str
    end_date: str
    region: str = "cn"
    freq: str = "day"
    symbol_field: str = "instrument_id"
    date_field: str = "trade_date"
    fields: tuple[str, ...] = ("open", "high", "low", "close", "volume", "amount")


@dataclass(frozen=True, slots=True)
class QlibExportResult:
    """Summary of one successful export."""

    provider_uri: str
    content_hash: str
    start_date: str
    end_date: str
    calendar_end: str
    instrument_count: int
    fields: tuple[str, ...]
    price_basis: str
    adjustment: str
    source_datasets: Mapping[str, Mapping[str, Any]]
    warnings: tuple[str, ...]


def export_qlib_provider(
    spec: QlibExportSpec,
    *,
    data_root: str | Path,
    output_dir: str | Path,
) -> QlibExportResult:
    """Materialize the spec's datasets into a qlib provider directory."""
    warnings: list[str] = []
    start = normalize_date(spec.start_date)
    end = normalize_date(spec.end_date)
    data_root = Path(data_root)

    source_ids = _load_instruments(spec, data_root=data_root, warnings=warnings)
    calendar, calendar_end = _load_calendar(spec, data_root=data_root, start=start, end=end)
    bars, present_ids = _load_bars(spec, data_root=data_root, calendar=calendar, warnings=warnings)

    exported_ids = _exported_instruments(source_ids, present_ids, warnings)
    bars = {identifier: bars[identifier] for identifier in exported_ids}
    if not exported_ids:
        raise QlibExportError(
            f"No instrument of dataset {spec.instruments_dataset!r} has bars in [{start}, {end}]."
        )

    adjustment, price_basis, note = _adjustment_metadata(
        spec, data_root=data_root, warnings=warnings
    )
    source_datasets = _source_summary(spec, data_root=data_root)
    generated_at = datetime.now(UTC).isoformat()

    target = write_qlib_dir(
        output_dir,
        calendar=calendar,
        instruments=exported_ids,
        bars=bars,
        fields=spec.fields,
        region=spec.region,
        freq=spec.freq,
        start_date=start,
        end_date=end,
        calendar_end=calendar_end,
        price_basis=price_basis,
        adjustment=adjustment,
        adjustment_note=note,
        source=source_datasets,
        generated_at=generated_at,
    )
    verify_layout(target)
    return QlibExportResult(
        provider_uri=str(target.resolve()),
        content_hash=compute_content_hash(target),
        start_date=start,
        end_date=end,
        calendar_end=calendar_end,
        instrument_count=len(exported_ids),
        fields=spec.fields,
        price_basis=price_basis,
        adjustment=adjustment,
        source_datasets=source_datasets,
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# source loading
# ---------------------------------------------------------------------------


def _load_instruments(
    spec: QlibExportSpec,
    *,
    data_root: Path,
    warnings: list[str],
) -> list[str]:
    df = _query(
        spec.instruments_dataset,
        [spec.symbol_field],
        data_root=data_root,
        description="instruments dataset",
    )
    ids = [str(value).strip() for value in df[spec.symbol_field].tolist() if str(value).strip()]
    unique = list(dict.fromkeys(ids))
    if len(unique) != len(ids):
        warnings.append(
            f"instruments dataset {spec.instruments_dataset!r} contained "
            f"{len(ids) - len(unique)} duplicate rows; duplicates dropped."
        )
    if not unique:
        raise QlibExportError(f"Instruments dataset {spec.instruments_dataset!r} is empty.")
    return unique


def _load_calendar(
    spec: QlibExportSpec,
    *,
    data_root: Path,
    start: str,
    end: str,
) -> tuple[list[str], str]:
    df = _query(
        spec.calendar_dataset,
        [spec.date_field],
        data_root=data_root,
        description="calendar dataset",
    )
    return resolve_export_calendar(df[spec.date_field].tolist(), start, end)


def _load_bars(
    spec: QlibExportSpec,
    *,
    data_root: Path,
    calendar: Sequence[str],
    warnings: list[str],
) -> tuple[dict[str, dict[str, np.ndarray]], set[str]]:
    required = [spec.symbol_field, spec.date_field, *spec.fields]
    df = _query(
        spec.bars_dataset,
        required,
        data_root=data_root,
        start_date=calendar[0],
        end_date=spec.end_date,
        description="bars dataset",
    )
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise QlibExportError(
            f"Bars dataset {spec.bars_dataset!r} is missing required column(s): "
            f"{', '.join(missing)}."
        )
    if df.empty:
        raise QlibExportError(
            f"Bars dataset {spec.bars_dataset!r} has no rows in [{calendar[0]}, {spec.end_date}]."
        )

    frame = df.copy()
    frame[spec.symbol_field] = frame[spec.symbol_field].astype(str).str.strip()
    frame[spec.date_field] = pd.to_datetime(frame[spec.date_field]).dt.strftime("%Y-%m-%d")

    actual_end = frame[spec.date_field].max()
    requested_end = normalize_date(spec.end_date)
    if actual_end < requested_end:
        warnings.append(
            f"Bars dataset {spec.bars_dataset!r} has data only up to "
            f"{actual_end}, earlier than the requested end {requested_end}; "
            "the tail is forward-filled in the export."
        )

    bars: dict[str, dict[str, np.ndarray]] = {}
    dropped: list[str] = []
    for identifier, group in frame.groupby(spec.symbol_field):
        day = (
            group.drop_duplicates(subset=[spec.date_field]).set_index(spec.date_field).sort_index()
        )
        per_field: dict[str, np.ndarray] = {}
        viable = True
        for field in spec.fields:
            series = day[field].astype(np.float64)
            # Align to the full export calendar: halted days are
            # forward-filled, the head is back-filled; the binary format has
            # no missing-value encoding and close must be nonzero from day one.
            aligned = series.reindex(calendar).ffill().bfill()
            if field == "close":
                if aligned.isna().any():
                    viable = False
                    break
            elif field in ("volume", "amount"):
                aligned = aligned.fillna(0.0)
            per_field[field] = aligned.to_numpy()
        if not viable:
            dropped.append(str(identifier))
            continue
        bars[str(identifier)] = per_field
    if dropped:
        warnings.append(
            f"{len(dropped)} instrument(s) had no usable close in the research "
            f"window and were skipped: {', '.join(dropped)}."
        )
    return bars, set(bars)


def _exported_instruments(
    source_ids: Sequence[str],
    present_ids: set[str],
    warnings: list[str],
) -> list[str]:
    exported = [identifier for identifier in source_ids if identifier in present_ids]
    skipped = [identifier for identifier in source_ids if identifier not in present_ids]
    if skipped:
        warnings.append(
            f"{len(skipped)} instrument(s) from the instruments dataset have no "
            f"bars in the research window and were skipped: {', '.join(skipped)}."
        )
    extra = sorted(present_ids - set(source_ids))
    if extra:
        warnings.append(
            f"{len(extra)} instrument(s) have bars but are absent from the "
            f"instruments dataset and were ignored: {', '.join(extra)}."
        )
    return exported


def _adjustment_metadata(
    spec: QlibExportSpec,
    *,
    data_root: Path,
    warnings: list[str],
) -> tuple[str, str, str]:
    """V1: record adjustment semantics, never recompute prices."""
    if not spec.adj_factor_dataset:
        return (
            "none",
            "raw",
            "No adj-factor dataset configured; prices are exported as stored (unadjusted).",
        )
    df = _query(
        spec.adj_factor_dataset,
        [spec.symbol_field, spec.date_field, ADJUSTMENT_FACTOR_FIELD],
        data_root=data_root,
        limit=1,
        description="adj-factor dataset",
    )
    if df.empty:
        warnings.append(
            f"adj-factor dataset {spec.adj_factor_dataset!r} is declared but "
            "has no rows; the export is recorded as unadjusted."
        )
        return (
            "none",
            "raw",
            "adj-factor dataset declared but empty; prices are exported as stored (unadjusted).",
        )
    return (
        "backward",
        "adjusted",
        "adj-factor dataset present; prices are assumed backward-adjusted "
        "(后复权口径). V1 records the basis and does not recompute prices.",
    )


def _source_summary(spec: QlibExportSpec, *, data_root: Path) -> Mapping[str, Mapping[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for dataset_id in _all_dataset_ids(spec):
        try:
            descriptor = get_dataset_descriptor(dataset_id, data_root=data_root)
        except Exception:
            summary[dataset_id] = {"layer": None, "source_runs": ()}
            continue
        summary[dataset_id] = {
            "layer": descriptor.layer,
            "source_runs": list(descriptor.source_runs),
        }
    return summary


def _all_dataset_ids(spec: QlibExportSpec) -> list[str]:
    ids = [spec.instruments_dataset, spec.calendar_dataset, spec.bars_dataset]
    if spec.adj_factor_dataset:
        ids.append(spec.adj_factor_dataset)
    return ids


def _query(
    dataset_id: str,
    fields: Sequence[str],
    *,
    data_root: Path,
    description: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """query_dataset with the error surface normalized to QlibExportError."""
    try:
        return query_dataset(
            dataset_id,
            data_root=data_root,
            fields=list(fields),
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
    except DatasetQueryError as error:
        raise QlibExportError(f"Cannot read {description} {dataset_id!r}: {error}") from error
