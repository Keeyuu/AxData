"""Wire tests for the four MAC timeseries commands (Wave2-B slice B).

Golden values replicate gotdx ``proto/mac_protocol_test.go``
(TestMACQuotesBuildRequestAndParseResponse / TestMACQuotesBuildRequestWithDate
/ TestMACSymbolBarsBuildRequestAndParseResponse /
TestMACTransactionsBuildRequestAndParseResponse /
TestMACTickChartsBuildRequestAndParseResponse /
TestMACTickChartsParseResponseSupportsPartialLeadingDay /
TestCombineMACDateTimeOvernight). No network access.
"""

from __future__ import annotations

import struct
from datetime import datetime

import pytest
from axdata_source_tdx._tdx_wire.protocol.commands import (
    build_command_frame,
    parse_command_response,
)
from axdata_source_tdx._tdx_wire.protocol.commands.mac_symbol_bars import (
    _combine_mac_datetime,
)
from axdata_source_tdx._tdx_wire.protocol.constants import (
    TYPE_MAC_QUOTES,
    TYPE_MAC_SYMBOL_BARS,
    TYPE_MAC_TICK_CHARTS,
    TYPE_MAC_TRANSACTIONS,
)
from axdata_source_tdx._tdx_wire.protocol.frame import ResponseFrame

MAC_EX_PREFIX = 0x01


def _u16(value: int) -> bytes:
    return struct.pack("<H", value)


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _f32(value: float) -> bytes:
    return struct.pack("<f", value)


def _code22(symbol: str) -> bytes:
    return symbol.encode("ascii").ljust(22, b"\x00")


def _response(body: bytes, msg_type: int = 0) -> ResponseFrame:
    return ResponseFrame(
        control=0,
        msg_id=1,
        msg_type=msg_type,
        zip_length=len(body),
        length=len(body),
        data=body,
        raw=b"",
    )


def _mac_summary(
    *,
    name: str = "PingAn Bank",
    date_raw: int = 20260418,
    time_raw: int = 93005,
    pre_close: float = 9.9,
    open_: float = 10.0,
    high: float = 10.8,
    low: float = 9.8,
    close: float = 10.5,
    momentum: float = 1.1,
    vol: int = 9988,
    amount: float = 123456.5,
    turnover: float = 2.5,
    avg: float = 10.2,
    industry: int = 83005,
) -> bytes:
    """120-byte summary block shared by quotes/bars/tick-charts responses."""

    return (
        name.encode("ascii").ljust(44, b"\x00")
        + bytes([2])  # decimal
        + _u16(6)  # category
        + _f32(100)  # vol_unit
        + b"\x00" * 5
        + _u32(date_raw)
        + _u32(time_raw)
        + _f32(pre_close)
        + _f32(open_)
        + _f32(high)
        + _f32(low)
        + _f32(close)
        + _f32(momentum)
        + _u32(vol)
        + _f32(amount)
        + b"\x00" * 12
        + _f32(turnover)
        + _f32(avg)
        + _u32(industry)
    )


# ---------------------------------------------------------------- mac_quotes


def test_build_mac_quotes_frame_exact_bytes():
    frame = build_command_frame(TYPE_MAC_QUOTES, {"code": "600000.SH"}, 7)

    expected = (
        _u16(1)  # market
        + _code22("600000")
        + _u16(0)  # zero1
        + _u16(0)  # zero2
        + _u16(1)  # one
        + _u16(0) * 4  # zero3..zero6
    )
    assert frame.msg_type == TYPE_MAC_QUOTES
    assert frame.head == MAC_EX_PREFIX
    assert frame.data == expected
    assert len(frame.data) == 38
    raw = frame.to_bytes()
    assert raw[0] == MAC_EX_PREFIX
    assert len(raw) == 12 + 38


def test_build_mac_quotes_frame_with_date_splits_query_date():
    frame = build_command_frame(
        TYPE_MAC_QUOTES, {"code": "600000.SH", "query_date": 20260418}, 0
    )

    assert frame.data[24:26] == _u16(20260418 & 0xFFFF)
    assert frame.data[26:28] == _u16(20260418 >> 16)


def test_mac_quotes_with_date_frame_equals_base_except_query_field():
    base = build_command_frame(TYPE_MAC_QUOTES, {"code": "600000.SH"}, 0)
    dated = build_command_frame(
        TYPE_MAC_QUOTES, {"code": "600000.SH", "query_date": 20260418}, 0
    )

    assert base.msg_type == dated.msg_type == TYPE_MAC_QUOTES
    assert base.head == dated.head == MAC_EX_PREFIX
    # Same command, same frame: only the zero1/zero2 slot [24:28] carries the
    # query date (zero when absent) - the N/A-equivalence evidence.
    assert base.data[:24] == dated.data[:24]
    assert base.data[28:] == dated.data[28:]
    assert base.data[24:28] == b"\x00" * 4
    assert dated.data[24:28] == (20260418).to_bytes(4, "little")


def test_parse_mac_quotes_payload_full_fields():
    body = (
        _u16(1)
        + _code22("600000")
        + _u32(20260418)  # date
        + bytes([7])  # unknown
        + _f32(10.5)  # price
        + _u16(2)  # count
        + _u16(570) + _f32(10.1) + _f32(10.0) + _u32(1234) + _f32(0.5)
        + _u16(571) + _f32(10.2) + _f32(10.1) + _u32(2234) + _f32(0.8)
        + _mac_summary()
    )

    snapshot = parse_command_response(
        TYPE_MAC_QUOTES, _response(body), {"code": "600000.SH"}
    )

    assert snapshot.full_code == "600000.SH"
    assert snapshot.market == 1
    assert snapshot.code == "600000"
    assert snapshot.date == 20260418
    assert snapshot.unknown == 7
    assert snapshot.price == pytest.approx(10.5, abs=1e-6)
    assert snapshot.count == 2
    assert len(snapshot.chart) == 2
    assert snapshot.chart[0].time == "09:30:00"
    assert snapshot.chart[0].price == pytest.approx(10.1, abs=1e-3)
    assert snapshot.chart[0].avg == pytest.approx(10.0, abs=1e-6)
    assert snapshot.chart[0].vol == 1234
    assert snapshot.chart[0].momentum == pytest.approx(0.5, abs=1e-6)
    assert snapshot.chart[1].time == "09:31:00"
    assert snapshot.chart[1].vol == 2234
    assert snapshot.chart[1].momentum == pytest.approx(0.8, abs=1e-6)
    assert snapshot.name == "PingAn Bank"
    assert snapshot.decimal == 2
    assert snapshot.category == 6
    assert snapshot.vol_unit == pytest.approx(100, abs=1e-6)
    assert snapshot.datetime == datetime(2026, 4, 18, 9, 30, 5)
    assert snapshot.pre_close == pytest.approx(9.9, abs=1e-6)
    assert snapshot.open == pytest.approx(10.0, abs=1e-6)
    assert snapshot.high == pytest.approx(10.8, abs=1e-6)
    assert snapshot.low == pytest.approx(9.8, abs=1e-6)
    assert snapshot.close == pytest.approx(10.5, abs=1e-6)
    assert snapshot.momentum == pytest.approx(1.1, abs=1e-6)
    assert snapshot.vol == 9988
    assert snapshot.amount == pytest.approx(123456.5, abs=1e-3)
    assert snapshot.turnover == pytest.approx(2.5, abs=1e-6)
    assert snapshot.avg == pytest.approx(10.2, abs=1e-6)
    assert snapshot.industry == 83005
    assert snapshot.industry_code == "881282"
    assert snapshot.raw_payload == b""


def test_parse_mac_quotes_keeps_raw_payload_on_request():
    body = (
        _u16(1)
        + _code22("600000")
        + _u32(0)
        + bytes([0])
        + _f32(0)
        + _u16(0)
        + _mac_summary()
    )

    snapshot = parse_command_response(
        TYPE_MAC_QUOTES, _response(body), {"code": "600000.SH", "include_raw": True}
    )

    assert snapshot.raw_payload == body


def test_parse_mac_quotes_rejects_truncations():
    with pytest.raises(Exception, match="invalid mac quotes payload length"):
        parse_command_response(TYPE_MAC_QUOTES, _response(b"\x00" * 30), {})
    header = _u16(1) + _code22("600000") + _u32(0) + bytes([0]) + _f32(0) + _u16(1)
    with pytest.raises(Exception, match="truncated mac quote chart item"):
        parse_command_response(TYPE_MAC_QUOTES, _response(header + b"\x00" * 10), {})
    two_items_header = _u16(1) + _code22("600000") + _u32(0) + bytes([0]) + _f32(0) + _u16(2)
    two_items = two_items_header + (_u16(570) + _f32(1) + _f32(1) + _u32(1) + _f32(1)) * 2
    with pytest.raises(Exception, match="invalid mac quotes summary length"):
        parse_command_response(TYPE_MAC_QUOTES, _response(two_items + b"\x00" * 119), {})


# ----------------------------------------------------------- mac_symbol_bars


def test_build_mac_symbol_bars_frame_exact_bytes():
    frame = build_command_frame(
        TYPE_MAC_SYMBOL_BARS, {"code": "600000.SH", "period": 4, "count": 1}, 3
    )

    expected = (
        _u16(1)  # market
        + _code22("600000")
        + _u16(4)  # period
        + _u16(1)  # times
        + _u32(0)  # start
        + _u16(2)  # count+1 (gotdx applyRequest adds one unconditionally)
        + _u16(0)  # adjust
        + bytes([1, 1, 0, 1])  # flag1, flag2, flag3, flag4
        + _u16(0)  # zero
        + b"\x00" * 4  # reserved
    )
    assert frame.msg_type == TYPE_MAC_SYMBOL_BARS
    assert frame.head == MAC_EX_PREFIX
    assert frame.data == expected
    assert len(frame.data) == 46


def test_build_mac_symbol_bars_frame_defaults():
    frame = build_command_frame(TYPE_MAC_SYMBOL_BARS, {"code": "600000.SH"}, 0)

    data = frame.data
    assert len(data) == 46
    assert data[24:26] == _u16(4)  # period defaults to daily
    assert data[26:28] == _u16(1)  # times default 1
    assert data[28:32] == _u32(0)  # start
    assert data[32:34] == _u16(801)  # count default 800 + 1
    assert data[34:36] == _u16(0)  # adjust
    assert data[36:40] == bytes([1, 1, 0, 1])
    assert data[40:42] == _u16(0)
    assert data[42:46] == b"\x00" * 4


def _symbol_bar(
    ymd: int, seconds: int, open_: float, high: float, low: float, close: float
) -> bytes:
    return (
        _u32(ymd)
        + _u32(seconds)
        + _f32(open_)
        + _f32(high)
        + _f32(low)
        + _f32(close)
        + _f32(12345.6)  # amount
        + _f32(789.0)  # vol
        + _f32(456.0)  # float_shares
    )


def test_parse_mac_symbol_bars_payload_drops_first_bar_and_chains_pre_close():
    body = (
        _u16(1)
        + b"600000" + b"\x00" * 16  # code[2:24]; parser reads [2:14]
        + bytes([4])  # period (daily -> no TDX-time rollover)
        + _u16(1)  # unknown
        + _u16(2)  # count: request asked for 2 bars
        + _u32(0)  # start
        + _symbol_bar(20260331, 34200, 10.1, 10.8, 9.9, 10.5)  # seed, discarded
        + _symbol_bar(20260331, 34200, 10.6, 11.0, 10.3, 10.9)
        + _mac_summary(date_raw=20260331, time_raw=150005)
    )

    page = parse_command_response(
        TYPE_MAC_SYMBOL_BARS, _response(body), {"code": "600000.SH"}
    )

    assert page.full_code == "600000.SH"
    assert page.market == 1
    assert page.code == "600000"
    assert page.period == 4
    assert page.unknown == 1
    assert page.count == 1
    assert page.start == 0
    assert len(page.bars) == 1
    bar = page.bars[0]
    assert bar.datetime == datetime(2026, 3, 31, 9, 30)
    assert bar.open == pytest.approx(10.6, abs=1e-6)
    assert bar.high == pytest.approx(11.0, abs=1e-6)
    assert bar.low == pytest.approx(10.3, abs=1e-6)
    assert bar.close == pytest.approx(10.9, abs=1e-6)
    assert bar.amount == pytest.approx(12345.6, abs=1e-3)
    assert bar.vol == pytest.approx(789.0, abs=1e-6)
    assert bar.float_shares == pytest.approx(456.0, abs=1e-6)
    assert bar.turnover == 0.0
    # PreClose chain: previous bar's close; first bar's rise uses open fallback.
    assert bar.pre_close == pytest.approx(10.5, abs=1e-6)
    assert bar.last_close == pytest.approx(10.5, abs=1e-6)
    assert bar.rise_price == pytest.approx(10.9 - 10.5, abs=1e-6)
    assert bar.rise_rate == pytest.approx((10.9 - 10.5) / 10.5 * 100, abs=1e-3)
    assert page.name == "PingAn Bank"
    assert page.datetime == datetime(2026, 3, 31, 15, 0, 5)
    assert page.close == pytest.approx(10.5, abs=1e-6)
    assert page.industry == 83005
    assert page.industry_code == "881282"
    assert page.raw_payload == b""


def test_combine_mac_datetime_overnight():
    # gotdx TestCombineMACDateTimeOvernight: 20260331 + 60s with TDX-time
    # formatting rolls past midnight to 2026-04-01 00:01:00.
    assert _combine_mac_datetime(20260331, 60, True) == datetime(2026, 4, 1, 0, 1)
    assert _combine_mac_datetime(20260331, 34200, True) == datetime(2026, 3, 31, 9, 30)
    # Without TDX-time formatting the hour stays as-is.
    assert _combine_mac_datetime(20260331, 60, False) == datetime(2026, 3, 31, 0, 1)


def test_parse_mac_symbol_bars_rejects_truncations():
    with pytest.raises(Exception, match="invalid mac symbol bars payload length"):
        parse_command_response(TYPE_MAC_SYMBOL_BARS, _response(b"\x00" * 30), {})
    header = _u16(1) + b"600000" + b"\x00" * 16 + bytes([4]) + _u16(1) + _u16(5) + _u32(0)
    with pytest.raises(Exception, match="truncated mac symbol bar item"):
        parse_command_response(TYPE_MAC_SYMBOL_BARS, _response(header + b"\x00" * 36), {})


# ---------------------------------------------------------- mac_transactions


def test_build_mac_transactions_frame_exact_bytes():
    frame = build_command_frame(
        TYPE_MAC_TRANSACTIONS, {"code": "600000.SH", "query_date": 20260418, "start": 5}, 2
    )

    expected = (
        _u16(1)
        + _code22("600000")
        + _u32(20260418)
        + _u32(5)
        + _u16(1000)  # default count
        + b"\x00" * 10
    )
    assert frame.msg_type == TYPE_MAC_TRANSACTIONS
    assert frame.head == MAC_EX_PREFIX
    assert frame.data == expected
    assert len(frame.data) == 44


def test_mac_transactions_with_date_frame_equals_base_except_query_field():
    base = build_command_frame(
        TYPE_MAC_TRANSACTIONS, {"code": "600000.SH", "start": 5}, 0
    )
    dated = build_command_frame(
        TYPE_MAC_TRANSACTIONS,
        {"code": "600000.SH", "start": 5, "query_date": 20260418},
        0,
    )

    assert base.msg_type == dated.msg_type == TYPE_MAC_TRANSACTIONS
    assert base.head == dated.head == MAC_EX_PREFIX
    # QueryDate is an explicit field of the base request struct; the with-date
    # frame differs only in that 4-byte slot - the N/A-equivalence evidence.
    assert base.data[:24] == dated.data[:24]
    assert base.data[28:] == dated.data[28:]
    assert base.data[24:28] == b"\x00" * 4
    assert dated.data[24:28] == (20260418).to_bytes(4, "little")


def test_parse_mac_transactions_payload_full_fields():
    body = (
        _u16(1)
        + _code22("600000")
        + _u32(20260418)
        + bytes([0])  # reserved byte 28, skipped by the parser
        + _u16(2)  # count
        + _u32(5)  # start
        + _u32(20)  # total
        + _u32(34215) + _f32(10.5) + _u32(100) + _u32(2) + _u16(0)
        + _u32(55800) + _f32(10.8) + _u32(80) + _u32(1) + _u16(1)
    )

    page = parse_command_response(
        TYPE_MAC_TRANSACTIONS, _response(body), {"code": "600000.SH"}
    )

    assert page.full_code == "600000.SH"
    assert page.market == 1
    assert page.code == "600000"
    assert page.query_date == 20260418
    assert page.count == 2
    assert page.start == 5
    assert page.total == 20
    assert len(page.items) == 2
    assert page.items[0].time == "09:30:15"
    assert page.items[0].price == pytest.approx(10.5, abs=1e-6)
    assert page.items[0].vol == 100
    assert page.items[0].trade_count == 2
    assert page.items[0].buy_or_sell == 0
    assert page.items[1].time == "15:30:00"
    assert page.items[1].price == pytest.approx(10.8, abs=1e-6)
    assert page.items[1].vol == 80
    assert page.items[1].trade_count == 1
    assert page.items[1].buy_or_sell == 1
    assert page.raw_payload == b""


def test_parse_mac_transactions_rejects_truncations():
    with pytest.raises(Exception, match="invalid mac transactions payload length"):
        parse_command_response(TYPE_MAC_TRANSACTIONS, _response(b"\x00" * 38), {})
    header = _u16(1) + _code22("600000") + _u32(0) + bytes([0]) + _u16(2) + _u32(0) + _u32(0)
    with pytest.raises(Exception, match="truncated mac transactions item"):
        parse_command_response(TYPE_MAC_TRANSACTIONS, _response(header + b"\x00" * 10), {})


# ----------------------------------------------------------- mac_tick_charts


def test_build_mac_tick_charts_frame_exact_bytes():
    frame = build_command_frame(
        TYPE_MAC_TICK_CHARTS, {"code": "600000.SH", "query_date": 20260418, "days": 2}, 5
    )

    expected = (
        _u16(1)
        + _code22("600000")
        + _u32(20260418)
        + _u16(2)  # days
        + _u16(1)  # one
        + b"\x00" * 6
    )
    assert frame.msg_type == TYPE_MAC_TICK_CHARTS
    assert frame.head == MAC_EX_PREFIX
    assert frame.data == expected
    assert len(frame.data) == 38


def test_build_mac_tick_charts_frame_defaults():
    frame = build_command_frame(TYPE_MAC_TICK_CHARTS, {"code": "600000.SH"}, 0)

    data = frame.data
    assert len(data) == 38
    assert data[24:28] == _u32(0)  # query_date default 0
    assert data[28:30] == _u16(5)  # days default 5
    assert data[30:32] == _u16(1)  # one default 1
    assert data[32:38] == b"\x00" * 6


def _tick(minutes: int, price: float, avg: float, vol: int, unknown: int) -> bytes:
    return _u16(minutes) + _f32(price) + _f32(avg) + _u16(vol) + _u16(unknown)


def test_parse_mac_tick_charts_payload_splits_days():
    body = (
        _u16(1)
        + _code22("600000")
        + _u32(20260418) + _u32(20260417) + _u32(0) + _u32(0) + _u32(0)
        + _f32(10.0) + _f32(9.8) + _f32(0) + _f32(0) + _f32(0)
        + _u16(2)  # count
        + bytes([1])  # send_last
        + _u16(2)  # page_size
        + _u16(4)  # total
        + _tick(570, 10.1, 10.05, 100, 7)
        + _tick(571, 10.2, 10.10, 120, 8)
        + _tick(570, 9.9, 9.85, 90, 9)
        + _tick(571, 10.0, 9.90, 110, 10)
        + _mac_summary(time_raw=150005)
    )

    page = parse_command_response(
        TYPE_MAC_TICK_CHARTS, _response(body), {"code": "600000.SH"}
    )

    assert page.full_code == "600000.SH"
    assert page.market == 1
    assert page.code == "600000"
    assert page.count == 2
    assert page.send_last == 1
    assert page.page_size == 2
    assert page.total == 4
    assert len(page.charts) == 2
    assert page.charts[0].date == "2026-04-18"
    assert page.charts[0].pre_close == pytest.approx(10.0, abs=1e-6)
    assert len(page.charts[0].ticks) == 2
    assert page.charts[0].ticks[0].time == "09:30:00"
    assert page.charts[0].ticks[0].price == pytest.approx(10.1, abs=1e-6)
    assert page.charts[0].ticks[0].avg == pytest.approx(10.05, abs=1e-3)
    assert page.charts[0].ticks[0].vol == 100
    assert page.charts[0].ticks[0].unknown == 7
    assert page.charts[1].date == "2026-04-17"
    assert page.charts[1].pre_close == pytest.approx(9.8, abs=1e-6)
    assert page.charts[1].ticks[1].unknown == 10
    assert page.name == "PingAn Bank"
    assert page.datetime == datetime(2026, 4, 18, 15, 0, 5)
    assert page.close == pytest.approx(10.5, abs=1e-6)
    assert page.industry == 83005
    assert page.industry_code == "881282"
    assert page.raw_payload == b""


def test_parse_mac_tick_charts_partial_leading_day():
    # gotdx TestMACTickChartsParseResponseSupportsPartialLeadingDay:
    # 1/4/4 day split with a single leading tick.
    body = (
        _u16(1)
        + _code22("600000")
        + _u32(20260506) + _u32(20260430) + _u32(20260429) + _u32(0) + _u32(0)
        + _f32(10.0) + _f32(9.8) + _f32(9.6) + _f32(0) + _f32(0)
        + _u16(3)  # count
        + bytes([1])  # send_last
        + _u16(4)  # page_size
        + _u16(9)  # total
        + _tick(570, 10.1, 10.1, 1, 1)
        + _tick(570, 9.9, 9.9, 2, 2)
        + _tick(571, 10.0, 9.95, 3, 3)
        + _tick(572, 10.1, 10.0, 4, 4)
        + _tick(573, 10.2, 10.05, 5, 5)
        + _tick(570, 9.7, 9.7, 6, 6)
        + _tick(571, 9.8, 9.75, 7, 7)
        + _tick(572, 9.9, 9.80, 8, 8)
        + _tick(573, 10.0, 9.85, 9, 9)
        + _mac_summary(date_raw=20260506, time_raw=93000)
    )

    page = parse_command_response(
        TYPE_MAC_TICK_CHARTS, _response(body), {"code": "600000.SH"}
    )

    assert page.total == 9
    assert page.page_size == 4
    assert len(page.charts) == 3
    assert [len(day.ticks) for day in page.charts] == [1, 4, 4]
    assert [day.date for day in page.charts] == [
        "2026-05-06",
        "2026-04-30",
        "2026-04-29",
    ]
    assert [day.pre_close for day in page.charts] == pytest.approx([10.0, 9.8, 9.6])
    assert page.charts[1].ticks[0].time == "09:30:00"
    assert page.charts[2].ticks[3].unknown == 9


def test_parse_mac_tick_charts_pads_missing_tail_days():
    # count=5 with a single day of ticks: gotdx pads the remaining slots with
    # empty days (date="" / pre_close=0.0).
    body = (
        _u16(1)
        + _code22("600000")
        + _u32(20260418) + _u32(0) + _u32(0) + _u32(0) + _u32(0)
        + _f32(10.0) + _f32(0) + _f32(0) + _f32(0) + _f32(0)
        + _u16(5)
        + bytes([0])
        + _u16(1)
        + _u16(1)
        + _tick(570, 10.1, 10.05, 100, 7)
        + _mac_summary()
    )

    page = parse_command_response(
        TYPE_MAC_TICK_CHARTS, _response(body), {"code": "600000.SH"}
    )

    assert len(page.charts) == 5
    assert len(page.charts[0].ticks) == 1
    assert page.charts[0].date == "2026-04-18"
    for day in page.charts[1:]:
        assert day.date == ""
        assert day.pre_close == 0.0
        assert day.ticks == ()


def test_parse_mac_tick_charts_rejects_truncations():
    with pytest.raises(Exception, match="invalid mac tick charts payload length"):
        parse_command_response(TYPE_MAC_TICK_CHARTS, _response(b"\x00" * 70), {})
    header = (
        _u16(1)
        + _code22("600000")
        + _u32(0) * 5
        + _f32(0) * 5
        + _u16(1)
        + bytes([0])
        + _u16(1)
        + _u16(2)
    )
    with pytest.raises(Exception, match="truncated mac tick charts item"):
        parse_command_response(TYPE_MAC_TICK_CHARTS, _response(header + b"\x00" * 10), {})
