"""Acceptance tests for the qlib exporter (docs/plan/06 §7, AXI-060).

Tests not marked ``framework`` run without pyqlib; the two Qlib-backed tests
(``test_qlib_init_and_features``, ``test_exchange_can_read_export``) are
marked ``@pytest.mark.framework`` and need ``pyqlib==0.9.7``.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from axdata_qlib import QlibExportError, QlibExportSpec, export_qlib_provider
from axdata_qlib.normalize import from_qlib_symbol, to_qlib_symbol
from axdata_qlib.validate import verify_layout
from conftest import (
    CALENDAR_DATES,
    INSTRUMENT_IDS,
    WINDOW_END,
    WINDOW_START,
    make_tiny_data_root,
    tiny_spec,
)

FIELDS = ("open", "high", "low", "close", "volume", "amount")


def run_export(tmp_path: Path, data_root: Path, spec: QlibExportSpec, name: str = "qlib"):
    out_dir = tmp_path / name
    return export_qlib_provider(spec, data_root=data_root, output_dir=out_dir), out_dir


def read_bin(path: Path) -> np.ndarray:
    return np.fromfile(path, dtype="<f")


def load_export_meta(out_dir: Path) -> dict:
    return json.loads((out_dir / "qlib_export.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# layout / mapping / calendar
# ---------------------------------------------------------------------------


def test_export_layout(tmp_path: Path, tiny_data_root: Path) -> None:
    result, out = run_export(tmp_path, tiny_data_root, tiny_spec())

    assert (out / "calendars" / "day.txt").is_file()
    assert (out / "instruments" / "all.txt").is_file()
    for symbol in ("sz000001", "sh600000"):
        for field in FIELDS:
            assert (out / "features" / symbol / f"{field}.day.bin").is_file(), (
                f"missing features/{symbol}/{field}.day.bin"
            )
    assert (out / "instrument_map.json").is_file()
    assert (out / "qlib_export.json").is_file()

    calendar = [
        line.strip()
        for line in (out / "calendars" / "day.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert calendar == [*CALENDAR_DATES[:5], "2026-01-12"]  # window + one margin day

    rows = [
        line.split("\t")
        for line in (out / "instruments" / "all.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows == [
        ["SZ000001", "2026-01-05", "2026-01-12"],
        ["SH600000", "2026-01-05", "2026-01-12"],
    ]

    # qlib bin format: float32 array, header 0 = calendar start index, then
    # one value per calendar day (matches tests/fixtures/qlib_dir.py).
    close = read_bin(out / "features" / "sz000001" / "close.day.bin")
    assert close.dtype == np.float32
    assert close[0] == 0.0
    assert close[1:] == pytest.approx([10.0, 10.2, 10.1, 10.3, 10.5, 10.5])  # ffill margin day

    assert result.instrument_count == 2
    assert result.fields == FIELDS
    assert result.start_date == WINDOW_START
    assert result.end_date == WINDOW_END
    assert result.calendar_end == "2026-01-12"
    assert len(result.content_hash) == 64


def test_instrument_mapping_round_trip(tmp_path: Path, tiny_data_root: Path) -> None:
    for source_id in INSTRUMENT_IDS:
        symbol = to_qlib_symbol(source_id)
        assert from_qlib_symbol(symbol) == source_id
        assert to_qlib_symbol(symbol) == symbol  # idempotent

    assert to_qlib_symbol("000001.SZ") == "SZ000001"
    assert to_qlib_symbol("600000.SH") == "SH600000"
    with pytest.raises(QlibExportError):
        to_qlib_symbol("not-an-instrument")
    with pytest.raises(QlibExportError):
        from_qlib_symbol("000001.SZ")

    result, out = run_export(tmp_path, tiny_data_root, tiny_spec())
    mapping = json.loads((out / "instrument_map.json").read_text(encoding="utf-8"))
    assert mapping["version"] == 1
    assert mapping["mapping"]["source_to_qlib"] == {
        "000001.SZ": "SZ000001",
        "600000.SH": "SH600000",
    }
    assert mapping["mapping"]["qlib_to_source"] == {
        "SZ000001": "000001.SZ",
        "SH600000": "600000.SH",
    }
    # the qlib directory is readable under the mapped symbols
    assert result.instrument_count == 2
    verify_layout(out)


def test_calendar_has_backtest_margin(tmp_path: Path, tiny_data_root: Path) -> None:
    _, out = run_export(tmp_path, tiny_data_root, tiny_spec())
    calendar = [
        line.strip()
        for line in (out / "calendars" / "day.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # the calendar must extend strictly past the research end (ADR-0001:
    # qlib reads calendar[end + 1])
    assert calendar[-1] > WINDOW_END

    # without a margin day the export must fail loudly, not truncate silently
    truncated_root = make_tiny_data_root(
        tmp_path / "truncated",
        calendar_dates=CALENDAR_DATES[:5],
    )
    with pytest.raises(QlibExportError, match="no trading day after"):
        export_qlib_provider(
            tiny_spec(), data_root=truncated_root, output_dir=tmp_path / "no_margin"
        )


# ---------------------------------------------------------------------------
# determinism / provenance
# ---------------------------------------------------------------------------


def test_same_inputs_same_export_hash(tmp_path: Path, tiny_data_root: Path) -> None:
    first, out_a = run_export(tmp_path, tiny_data_root, tiny_spec(), name="a")
    second, out_b = run_export(tmp_path, tiny_data_root, tiny_spec(), name="b")

    assert first.content_hash == second.content_hash
    # generated_at is excluded from the hash but still recorded
    meta_a, meta_b = load_export_meta(out_a), load_export_meta(out_b)
    assert meta_a["generated_at"] != meta_b["generated_at"]
    assert meta_a["content_hash"] == first.content_hash == second.content_hash
    assert (out_a / "instrument_map.json").read_bytes() == (
        out_b / "instrument_map.json"
    ).read_bytes()
    assert (
        read_bin(out_a / "features" / "sz000001" / "close.day.bin").tobytes()
        == read_bin(out_b / "features" / "sz000001" / "close.day.bin").tobytes()
    )


def test_source_change_changes_hash(tmp_path: Path) -> None:
    data_root = make_tiny_data_root(tmp_path / "root")
    first, _ = run_export(tmp_path, data_root, tiny_spec(), name="before")

    # mutate one close price in the source bars dataset
    bars_path = data_root / "snapshot" / "dataset=tiny.bars" / "parquet" / "part-0.parquet"
    bars = pd.read_parquet(bars_path)
    mask = (bars["instrument_id"] == "000001.SZ") & (
        pd.to_datetime(bars["trade_date"]) == pd.Timestamp("2026-01-07")
    )
    assert mask.any(), "fixture mutation target row not found"
    bars.loc[mask, "close"] = 9.99
    bars.to_parquet(bars_path, engine="pyarrow", index=False)

    second, _ = run_export(tmp_path, data_root, tiny_spec(), name="after")
    assert second.content_hash != first.content_hash


def test_missing_required_bar_field_fails(tmp_path: Path) -> None:
    data_root = make_tiny_data_root(tmp_path / "root", drop_bars_field="amount")
    with pytest.raises(QlibExportError, match="amount"):
        export_qlib_provider(tiny_spec(), data_root=data_root, output_dir=tmp_path / "qlib")


def test_adjustment_metadata_is_explicit(tmp_path: Path, tiny_data_root: Path) -> None:
    _, out = run_export(tmp_path, tiny_data_root, tiny_spec())
    meta = load_export_meta(out)
    assert meta["price_basis"] == "adjusted"
    assert meta["adjustment"] == "backward"  # adj-factor present → 后复权口径
    assert "tiny.adj_factor" in meta["source"]

    # without an adj-factor dataset the export is recorded as unadjusted
    no_adj_root = make_tiny_data_root(tmp_path / "no_adj_data", has_adj_factor=False)
    result, out_no_adj = run_export(
        tmp_path, no_adj_root, tiny_spec(adj_factor_dataset=None), name="no_adj_out"
    )
    meta = load_export_meta(out_no_adj)
    assert meta["price_basis"] == "raw"
    assert meta["adjustment"] == "none"
    assert "tiny.adj_factor" not in meta["source"]

    # declared but empty adj-factor dataset degrades to unadjusted + warning
    empty_root = make_tiny_data_root(tmp_path / "empty_adj_data")
    adj_parquet = empty_root / "snapshot" / "dataset=tiny.adj_factor" / "parquet" / "part-0.parquet"
    pd.DataFrame(columns=["instrument_id", "trade_date", "adj_factor"]).to_parquet(
        adj_parquet, engine="pyarrow", index=False
    )
    result, out_empty = run_export(tmp_path, empty_root, tiny_spec(), name="empty_adj_out")
    meta = load_export_meta(out_empty)
    assert meta["price_basis"] == "raw"
    assert meta["adjustment"] == "none"
    assert any("has no rows" in warning for warning in result.warnings)


# ---------------------------------------------------------------------------
# Qlib-backed acceptance (pyqlib required)
# ---------------------------------------------------------------------------


@pytest.mark.framework
def test_qlib_init_and_features(tmp_path: Path, tiny_data_root: Path) -> None:
    import qlib
    from qlib.data import D

    _, out = run_export(tmp_path, tiny_data_root, tiny_spec())
    qlib.init(provider_uri=str(out), region="cn", auto_mount=False)

    frame = D.features(
        ["SZ000001", "SH600000"],
        ["$close"],
        start_time=WINDOW_START,
        end_time=WINDOW_END,
        freq="day",
    )
    assert sorted(set(frame.index.get_level_values("instrument"))) == [
        "SH600000",
        "SZ000001",
    ]
    close = frame["$close"]
    assert list(close.xs("SZ000001", level="instrument")) == pytest.approx(
        [10.0, 10.2, 10.1, 10.3, 10.5]
    )
    assert list(close.xs("SH600000", level="instrument")) == pytest.approx(
        [20.0, 20.4, 20.3, 20.6, 20.8]
    )


@pytest.mark.framework
def test_exchange_can_read_export(tmp_path: Path, tiny_data_root: Path) -> None:
    import qlib
    from qlib.backtest import Exchange

    _, out = run_export(tmp_path, tiny_data_root, tiny_spec())
    qlib.init(provider_uri=str(out), region="cn", auto_mount=False)

    exchange = Exchange(
        freq="day",
        start_time=WINDOW_START,
        end_time=WINDOW_END,
        codes=["SZ000001", "SH600000"],
        deal_price="close",
        open_cost=0.0,
        close_cost=0.0,
        min_cost=0.0,
    )
    get_close = exchange.get_close
    get_volume = exchange.get_volume
    day_06 = pd.Timestamp("2026-01-06")
    day_07 = pd.Timestamp("2026-01-07")
    day_08 = pd.Timestamp("2026-01-08")
    day_09 = pd.Timestamp("2026-01-09")
    assert get_close("SZ000001", day_06, day_06) == pytest.approx(10.2)
    assert get_close("SH600000", day_07, day_07) == pytest.approx(20.3)
    assert get_volume("SH600000", day_08, day_08) == pytest.approx(2_200_000.0)
    assert get_volume("SZ000001", day_09, day_09) == pytest.approx(1_300_000.0)
