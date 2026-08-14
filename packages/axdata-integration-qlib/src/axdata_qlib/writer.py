"""Qlib 0.9.7 provider directory writer.

Format verified against ``qlib.data.storage.file_storage`` (pyqlib 0.9.7):

- ``features/<inst>/<field>.day.bin``: little-endian float32 array, first
  element is the calendar start index (``0`` for a fresh export), followed by
  one value per calendar day — exactly ``np.hstack([0, values]).astype("<f")``;
- ``calendars/day.txt``: one ``YYYY-MM-DD`` per line;
- ``instruments/all.txt``: tab-separated ``<symbol>\\t<start>\\t<end>`` rows.

The exporter never mutates an existing export in place: a non-empty
``output_dir`` is refused, so a snapshot's qlib directory is rebuild-only.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from .errors import QlibExportError
from .normalize import build_instrument_map

QLIB_EXPORT_FILENAME = "qlib_export.json"
INSTRUMENT_MAP_FILENAME = "instrument_map.json"


def write_qlib_dir(
    output_dir: str | Path,
    *,
    calendar: Sequence[str],
    instruments: Sequence[str],
    bars: Mapping[str, Mapping[str, Sequence[float]]],
    fields: Sequence[str],
    region: str,
    freq: str,
    start_date: str,
    end_date: str,
    calendar_end: str,
    price_basis: str,
    adjustment: str,
    adjustment_note: str,
    source: Mapping[str, Any],
    generated_at: str,
) -> Path:
    """Write the qlib provider directory and return its path.

    Args:
        calendar: Trading days of the export, ``YYYY-MM-DD``, ascending.
        instruments: AxData source instrument ids (``000001.SZ`` form).
        bars: ``instrument -> field -> values`` aligned to ``calendar``.
        fields: Export field order (``open``, ``high``, ...).
        source: Provenance payload embedded in ``qlib_export.json``
            (source datasets / runs of the export).
    """
    target = Path(output_dir)
    if target.exists() and any(target.iterdir()):
        raise QlibExportError(
            f"Refusing to export into non-empty directory {target}; "
            "qlib provider directories are rebuild-only, never incrementally "
            "modified in place."
        )
    target.mkdir(parents=True, exist_ok=True)

    _write_calendar(target, calendar)
    _write_instruments(target, instruments, calendar)
    _write_features(target, instruments, bars, fields)

    instrument_map = build_instrument_map(instruments)
    _write_json(
        target / INSTRUMENT_MAP_FILENAME,
        {
            "version": 1,
            "mapping": instrument_map,
        },
    )

    from .validate import compute_content_hash  # function-level import: writer ↔ validate cycle

    content_hash = compute_content_hash(target)
    _write_json(
        target / QLIB_EXPORT_FILENAME,
        {
            "schema_version": 1,
            "provider_uri": str(target),
            "region": region,
            "freq": freq,
            "fields": list(fields),
            "start_date": start_date,
            "end_date": end_date,
            "calendar_end": calendar_end,
            "price_basis": price_basis,
            "adjustment": adjustment,
            "adjustment_note": adjustment_note,
            "source": dict(source),
            "generated_at": generated_at,
            "content_hash": content_hash,
        },
    )
    return target


def _write_calendar(target: Path, calendar: Sequence[str]) -> None:
    calendar_dir = target / "calendars"
    calendar_dir.mkdir(parents=True, exist_ok=True)
    (calendar_dir / "day.txt").write_text(
        "".join(f"{day}\n" for day in calendar),
        encoding="utf-8",
    )


def _write_instruments(target: Path, instruments: Sequence[str], calendar: Sequence[str]) -> None:
    instruments_dir = target / "instruments"
    instruments_dir.mkdir(parents=True, exist_ok=True)
    instrument_map = build_instrument_map(instruments)
    with (instruments_dir / "all.txt").open("w", encoding="utf-8") as fp:
        for identifier in instruments:
            symbol = instrument_map["source_to_qlib"][identifier]
            fp.write(f"{symbol}\t{calendar[0]}\t{calendar[-1]}\n")


def _write_features(
    target: Path,
    instruments: Sequence[str],
    bars: Mapping[str, Mapping[str, Sequence[float]]],
    fields: Sequence[str],
) -> None:
    instrument_map = build_instrument_map(instruments)
    for identifier in instruments:
        symbol = instrument_map["source_to_qlib"][identifier]
        inst_bars = bars.get(identifier)
        if inst_bars is None:
            raise QlibExportError(f"Missing bars for instrument {identifier!r}.")
        inst_dir = target / "features" / symbol.lower()
        inst_dir.mkdir(parents=True, exist_ok=True)
        for field in fields:
            values = inst_bars.get(field)
            if values is None:
                raise QlibExportError(f"Missing field {field!r} for instrument {identifier!r}.")
            array = np.asarray(values, dtype=np.float64)
            if array.ndim != 1:
                raise QlibExportError(
                    f"Field {field!r} of instrument {identifier!r} must be a "
                    "1-D array aligned to the export calendar."
                )
            np.hstack([0, array]).astype("<f").tofile(inst_dir / f"{field}.day.bin")


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
