"""Offline tests for the full-market minute collection driver (plan 18).

Covers the driver's pure logic only: batch splitting, per-(table, period)
landed-set accounting over hand-written parquet fixtures, the duckdb verify
queries on fixtures that intentionally contain duplicates / shallow depth /
over-cap sessions, and the 5m -> 15m synthesis aggregation. No network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import collect_full_market_minute as minute  # noqa: E402


def _write_minute_file(root: Path, table: str, name: str, rows: list[tuple]) -> None:
    table_dir = root / "core" / f"table={table}" / "parquet"
    table_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        rows,
        columns=[
            "instrument_id",
            "symbol",
            "tdx_code",
            "exchange",
            "trade_time",
            "period",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
        ],
    )
    frame.to_parquet(table_dir / name, index=False)


def _bars(
    code: str,
    tdx_code: str,
    period: str,
    dates: list[str],
    bars_per_day: int,
) -> list[tuple]:
    rows: list[tuple] = []
    for day in dates:
        for index in range(bars_per_day):
            hour, minute_of_hour = divmod(index % 240, 60)
            trade_time = f"{day} {9 + hour:02d}:{minute_of_hour:02d}:00"
            rows.append(
                (
                    code,
                    "sym",
                    tdx_code,
                    "SSE",
                    trade_time,
                    period,
                    10.0,
                    10.0,
                    10.0,
                    10.0,
                    100.0,
                    1000.0,
                )
            )
    return rows


# ---------------------------------------------------------------- batch split


def test_chunks_splits_into_requested_batch_sizes() -> None:
    codes = [f"sz{n:06d}" for n in range(55)]
    chunks = minute._chunks(codes, 50)
    assert [len(chunk) for chunk in chunks] == [50, 5]
    assert [chunk[0] for chunk in chunks] == ["sz000000", "sz000050"]
    assert minute._chunks(codes, 10)[0] == codes[:10]
    assert minute._chunks([], 50) == []


# ------------------------------------------------ per-period landed accounting


def test_landed_codes_filters_by_period_across_files(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(minute, "DATA_ROOT", tmp_path)
    rows = []
    rows += _bars("000001.SZ", "sz000001", "1m", ["2026-07-01", "2026-07-02"], 240)
    rows += _bars("000001.SZ", "sz000001", "5m", ["2026-07-01", "2026-07-02"], 48)
    rows += _bars("600000.SH", "sh600000", "1m", ["2026-07-01"], 240)
    # split one batch across two files to prove per-file unioning
    _write_minute_file(tmp_path, "minute", "batch_1.parquet", rows[: len(rows) // 2])
    _write_minute_file(tmp_path, "minute", "batch_2.parquet", rows[len(rows) // 2 :])

    landed_1m = minute._landed_codes("minute", "1m")
    landed_5m = minute._landed_codes("minute", "5m")

    assert landed_1m == {"sz000001", "sh600000"}
    assert landed_5m == {"sz000001"}
    assert minute._landed_codes("minute", "15m") == set()


def test_landed_codes_skips_debris_file_without_period_column(
    monkeypatch, tmp_path, capsys
) -> None:
    monkeypatch.setattr(minute, "DATA_ROOT", tmp_path)
    _write_minute_file(
        tmp_path,
        "minute",
        "good.parquet",
        _bars("000001.SZ", "sz000001", "1m", ["2026-07-01"], 240),
    )
    table_dir = tmp_path / "core" / "table=minute" / "parquet"
    pd.DataFrame({"junk": [1, 2]}).to_parquet(table_dir / "debris.parquet", index=False)

    landed = minute._landed_codes("minute", "1m")
    captured = capsys.readouterr()

    assert landed == {"sz000001"}
    assert "debris.parquet" in captured.err


# ---------------------------------------------------- verify queries (duckdb)


def test_verify_fails_on_dup_shallow_and_overflow_fixture(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(minute, "DATA_ROOT", tmp_path)
    dates = ["2026-07-01", "2026-07-02", "2026-07-03"]
    rows = _bars("000001.SZ", "sz000001", "1m", dates, 240)
    # ② duplicate PK: same (instrument_id, trade_time, period) twice
    rows.append(rows[0])
    # ④ session overflow: one code-day with more bars than the 1m cap
    rows += _bars("000002.SZ", "sz000002", "1m", ["2026-07-01"], 250)
    _write_minute_file(tmp_path, "minute", "batch_1.parquet", rows)
    # shallow depth for index_minute (3 dates < 90)
    _write_minute_file(
        tmp_path,
        "index_minute",
        "batch_1.parquet",
        _bars("000001.SH", "sh000001", "1m", dates, 240),
    )

    monkeypatch.setattr(
        minute,
        "_expected_universe",
        lambda kind, problems: {"sz000001", "sz000002", "sz300001", "bj920059"},
    )

    assert minute._verify() == 1
    captured = capsys.readouterr()
    assert "duplicate PK" in captured.err
    assert "depth" in captured.err
    assert "over bar cap" in captured.err
    assert "codes missing" in captured.err


def test_verify_period_passes_on_clean_fixture(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(minute, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(minute, "DEPTH_MIN_TRADING_DAYS", {"1m": 2, "5m": 2})
    dates = ["2026-07-01", "2026-07-02", "2026-07-03"]
    rows = _bars("000001.SZ", "sz000001", "1m", dates, 240)
    rows += _bars("000001.SZ", "sz000001", "5m", dates, 48)
    _write_minute_file(tmp_path, "minute", "batch_1.parquet", rows)

    con = duckdb.connect()
    glob = str(tmp_path / "core" / "table=minute" / "parquet" / "*.parquet")
    problems: list[str] = []
    minute._verify_period(con, "minute", "stocks", "1m", glob, {"sz000001"}, problems)
    assert problems == []
    minute._verify_period(con, "minute", "stocks", "5m", glob, {"sz000001"}, problems)
    assert problems == []


# ------------------------------------------------- 5m -> 15m synthesis rule


def test_aggregate_5m_to_15m_ohlc_matches_hand_computed_bucket() -> None:
    rows = [
        (
            "000001.SZ",
            "sym",
            "sz000001",
            "SSE",
            "2026-07-01 10:00:00",
            "5m",
            1.0,
            1.5,
            0.5,
            1.2,
            100.0,
            1000.0,
        ),
        (
            "000001.SZ",
            "sym",
            "sz000001",
            "SSE",
            "2026-07-01 10:05:00",
            "5m",
            2.0,
            2.5,
            1.5,
            2.2,
            100.0,
            1000.0,
        ),
        (
            "000001.SZ",
            "sym",
            "sz000001",
            "SSE",
            "2026-07-01 10:10:00",
            "5m",
            3.0,
            3.5,
            2.5,
            3.2,
            100.0,
            1000.0,
        ),
        # bar starting 10:15 belongs to the next 15m bucket
        (
            "000001.SZ",
            "sym",
            "sz000001",
            "SSE",
            "2026-07-01 10:15:00",
            "5m",
            9.0,
            9.5,
            8.5,
            9.2,
            100.0,
            1000.0,
        ),
    ]
    frame = pd.DataFrame(
        rows,
        columns=[
            "instrument_id",
            "symbol",
            "tdx_code",
            "exchange",
            "trade_time",
            "period",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
        ],
    )
    aggregated = minute._aggregate_5m_to_15m(frame)
    bucket = pd.Timestamp("2026-07-01 10:00:00")
    assert list(aggregated.loc[bucket, ["open", "high", "low", "close"]]) == [1.0, 3.5, 0.5, 3.2]
    next_bucket = pd.Timestamp("2026-07-01 10:15:00")
    values = aggregated.loc[next_bucket, ["open", "high", "low", "close"]]
    assert list(values) == [9.0, 9.5, 8.5, 9.2]


class _FakeClient:
    """Serves the 5m tail as the 5m request and a precomputed 15m frame as the
    native 15m request, so the whole synthesize-check loop runs offline."""

    def __init__(self, five: pd.DataFrame, native15: pd.DataFrame) -> None:
        self._five = five
        self._native15 = native15

    def call(self, interface: str, **kwargs):
        return self._native15 if kwargs.get("period") == "15m" else self._five


def _synthetic_five_minute_frame(days: int = 4) -> pd.DataFrame:
    rows: list[tuple] = []
    for day_index in range(days):
        day = f"2026-07-{day_index + 1:02d}"
        for bar in range(48):
            hour, minute_of_hour = divmod(bar, 12)
            clock_hour = 9 + hour if hour < 2 else 12 + (hour - 2)
            trade_time = f"{day} {clock_hour:02d}:{minute_of_hour * 5:02d}:00"
            base = (day_index * 48 + bar) * 0.01
            rows.append(
                (
                    "000001.SZ",
                    "sym",
                    "sz000001",
                    "SSE",
                    trade_time,
                    "5m",
                    base + 10.0,
                    base + 10.2,
                    base + 9.9,
                    base + 10.1,
                    100.0,
                    1000.0,
                )
            )
    return pd.DataFrame(
        rows,
        columns=[
            "instrument_id",
            "symbol",
            "tdx_code",
            "exchange",
            "trade_time",
            "period",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
        ],
    )


def _native_15m_response(five: pd.DataFrame) -> pd.DataFrame:
    """Shape the aggregated 5m buckets back into a client-response 15m frame."""
    aggregated = minute._aggregate_5m_to_15m(five)
    return pd.DataFrame(
        {
            "instrument_id": "000001.SZ",
            "symbol": "sym",
            "tdx_code": "sz000001",
            "exchange": "SSE",
            "trade_time": [ts.strftime("%Y-%m-%d %H:%M:%S") for ts in aggregated.index],
            "period": "15m",
            "open": aggregated["open"].values,
            "high": aggregated["high"].values,
            "low": aggregated["low"].values,
            "close": aggregated["close"].values,
            "volume": 100.0,
            "amount": 1000.0,
        }
    )


def test_synthesize_check_passes_with_consistent_native_15m(monkeypatch, capsys) -> None:
    five = _synthetic_five_minute_frame()
    native15 = _native_15m_response(five)
    monkeypatch.setattr(minute, "_client", lambda: _FakeClient(five, native15))

    assert minute._synthesize_check() == 0
    assert "matches native 15m for all targets" in capsys.readouterr().out


def test_synthesize_check_fails_on_tampered_native_15m(monkeypatch, capsys) -> None:
    five = _synthetic_five_minute_frame()
    native15 = _native_15m_response(five)
    native15.loc[native15.index[-1], "close"] += 5.0
    monkeypatch.setattr(minute, "_client", lambda: _FakeClient(five, native15))

    assert minute._synthesize_check() == 1
    assert "FAILED" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("codes", "size", "expected"),
    [
        (["a", "b", "c"], 1, [["a"], ["b"], ["c"]]),
        (["a", "b", "c"], 2, [["a", "b"], ["c"]]),
        (["a", "b", "c"], 5, [["a", "b", "c"]]),
    ],
)
def test_chunks_parametrized(codes, size, expected) -> None:
    assert minute._chunks(codes, size) == expected
