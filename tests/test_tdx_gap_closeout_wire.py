"""计划 19 收口 wire 真缺口四命令：announcement 0x000A / exchange_announcement
0x0002 / historical_trades_basic 0x0FB5 / klines_0523 0x0523。

gotdx 规格注意：``KMSG_EXCHANGEANNOUNCE`` = 0x0002（交易所公告）、
``KMSG_ANNOUNCEMENT`` = 0x000A（服务商公告）——任务描述里的两个码互为写反，
此处按 gotdx ``proto/proto.go`` 事实落码。
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

_TDX_PROVIDER_SRC = str(
    Path(__file__).resolve().parents[1] / "packages" / "axdata-source-tdx" / "src"
)
sys.path.insert(0, _TDX_PROVIDER_SRC)

from axdata_source_tdx._tdx_wire.protocol.commands import (
    build_command_frame,
    parse_command_response,
)
from axdata_source_tdx._tdx_wire.protocol.constants import (
    TYPE_ANNOUNCEMENT,
    TYPE_EXCHANGE_ANNOUNCEMENT,
    TYPE_HISTORICAL_TRADES,
    TYPE_HISTORICAL_TRADES_BASIC,
    TYPE_KLINES_0523,
)
from axdata_source_tdx._tdx_wire.protocol.frame import ResponseFrame

if sys.path and sys.path[0] == _TDX_PROVIDER_SRC:
    sys.path.pop(0)


def _response(body: bytes, msg_type: int) -> ResponseFrame:
    return ResponseFrame(
        control=0,
        msg_id=1,
        msg_type=msg_type,
        zip_length=len(body),
        length=len(body),
        data=body,
        raw=b"",
    )


def _signed_varint(value: int) -> bytes:
    negative = value < 0
    remaining = -value if negative else value
    first = remaining & 0x3F
    remaining >>= 6
    out = [first | (0x40 if negative else 0)]
    if remaining:
        out[0] |= 0x80
    while remaining:
        byte = remaining & 0x7F
        remaining >>= 7
        if remaining:
            byte |= 0x80
        out.append(byte)
    return bytes(out)


# ---------------------------------------------------------------- announcement


def test_build_announcement_frame_uses_54_zero_bytes():
    frame = build_command_frame(TYPE_ANNOUNCEMENT, {}, 13)

    assert frame.msg_type == TYPE_ANNOUNCEMENT == 0x000A
    assert frame.data == b"\x00" * 54


def test_parse_announcement_payload_decodes_notice():
    title = "系统升级公告".encode("gbk")
    author = "通达信".encode("gbk")
    content = "今晚 22:00 维护".encode("gbk")
    payload = (
        b"\x01"
        + (20260630).to_bytes(4, "little")
        + len(title).to_bytes(2, "little")
        + len(author).to_bytes(2, "little")
        + len(content).to_bytes(2, "little")
        + title
        + author
        + content
    )

    notice = parse_command_response(
        TYPE_ANNOUNCEMENT, _response(payload, TYPE_ANNOUNCEMENT)
    )

    assert notice.has_content is True
    assert notice.expire_date_raw == 20260630
    assert notice.expire_date.isoformat() == "2026-06-30"
    assert notice.title == "系统升级公告"
    assert notice.author == "通达信"
    assert notice.content == "今晚 22:00 维护"


def test_parse_announcement_payload_without_content_flag_returns_empty_notice():
    notice = parse_command_response(
        TYPE_ANNOUNCEMENT, _response(b"\x00\x02\x03", TYPE_ANNOUNCEMENT)
    )

    assert notice.has_content is False
    assert notice.expire_date is None
    assert (notice.title, notice.author, notice.content) == ("", "", "")


# -------------------------------------------------------- exchange_announcement


def test_build_exchange_announcement_frame_has_empty_body():
    frame = build_command_frame(TYPE_EXCHANGE_ANNOUNCEMENT, {}, 13)

    assert frame.msg_type == TYPE_EXCHANGE_ANNOUNCEMENT == 0x0002
    assert frame.data == b""


def test_parse_exchange_announcement_payload_decodes_version_and_content():
    content = "节假日休市安排".encode("gbk")
    info = parse_command_response(
        TYPE_EXCHANGE_ANNOUNCEMENT,
        _response(b"\x03" + content, TYPE_EXCHANGE_ANNOUNCEMENT),
    )

    assert info.version == 3
    assert info.content == "节假日休市安排"


# ------------------------------------------------------ historical_trades_basic


def test_build_historical_trades_basic_frame_matches_0fb5_and_shares_0fc6_body():
    payload = {"code": "000001.SZ", "trade_date": "20260511", "start": 0, "count": 900}

    frame = build_command_frame(TYPE_HISTORICAL_TRADES_BASIC, payload, 13)
    sibling = build_command_frame(TYPE_HISTORICAL_TRADES, payload, 13)

    # gotdx：0x0FB5 与 0x0FC6 共用 GetHistoryTransactionDataRequest，请求体逐字节相同。
    assert frame.msg_type == TYPE_HISTORICAL_TRADES_BASIC == 0x0FB5
    assert frame.data == sibling.data
    assert frame.data.hex() == "9f263501000030303030303100008403"


def test_parse_historical_trades_basic_payload_decodes_delta_prices_and_side():
    def record(time_minutes, price_delta, volume, buyorsell, unknown):
        return (
            time_minutes.to_bytes(2, "little")
            + _signed_varint(price_delta)
            + _signed_varint(volume)
            + _signed_varint(buyorsell)
            + _signed_varint(unknown)
        )

    payload = (
        (2).to_bytes(2, "little")
        + b"\xde\xad\xbe\xef"  # gotdx 跳过 4 字节（0x0FC6 同位置为 f32 昨收）
        + record(14 * 60 + 8, 1086, 89, 0, 3)
        + record(14 * 60 + 9, -100, 22, 1, 0)
    )

    series = parse_command_response(
        TYPE_HISTORICAL_TRADES_BASIC,
        _response(payload, TYPE_HISTORICAL_TRADES_BASIC),
        {"code": "sz000001", "trade_date": "20260511", "start": 40, "count": 900},
    )

    assert series.full_code == "sz000001"
    assert series.trade_date.isoformat() == "2026-05-11"
    assert series.skipped_head_raw == b"\xde\xad\xbe\xef"
    assert series.price_base_unit == 100.0  # 前缀 00 → gotdx baseUnit 100
    assert series.count == 2
    assert [r.absolute_index for r in series.records] == [40, 41]
    assert [r.trade_datetime.isoformat(timespec="seconds") for r in series.records] == [
        "2026-05-11T14:08:00+08:00",
        "2026-05-11T14:09:00+08:00",
    ]
    assert [r.price for r in series.records] == [10.86, 9.86]
    assert [r.volume for r in series.records] == [89, 22]
    assert [r.buyorsell_raw for r in series.records] == [0, 1]
    assert [r.side for r in series.records] == ["buy", "sell"]
    assert [r.unknown_raw for r in series.records] == [3, 0]


def test_parse_historical_trades_basic_uses_etf_base_unit():
    record = (
        (9 * 60 + 30).to_bytes(2, "little")
        + _signed_varint(10001)
        + _signed_varint(5)
        + _signed_varint(2)
        + _signed_varint(0)
    )
    payload = (1).to_bytes(2, "little") + b"\x00\x00\x00\x00" + record

    series = parse_command_response(
        TYPE_HISTORICAL_TRADES_BASIC,
        _response(payload, TYPE_HISTORICAL_TRADES_BASIC),
        {"code": "sz159915", "trade_date": "20260511"},
    )

    # gotdx baseUnit：深交所 ETF 前缀 15 → 1000（三位小数）。
    assert series.price_base_unit == 1000.0
    assert series.records[0].price == 10.001
    assert series.records[0].side == "neutral"


# ------------------------------------------------------------------ klines_0523


def test_build_klines_0523_frame_uses_gotdx_26_byte_layout_with_count_plus_one():
    frame = build_command_frame(
        TYPE_KLINES_0523,
        {"code": "000001.SZ", "period": "day", "start": 0, "count": 10},
        5,
    )

    # <u16 market=0><"000001"><u16 category=4><u16 times=1><u16 start=0>
    # <u16 count=11（10+1，gotdx NewGetSecurityBars 多取一条推昨收）>
    # <u16 adjust=0><reserved[8]>
    assert frame.msg_type == TYPE_KLINES_0523 == 0x0523
    assert frame.data.hex() == "00003030303030310400010000000b0000000000000000000000"


def test_parse_klines_0523_payload_decodes_absolute_prices_and_drops_head_bar():
    def bar(date_raw, open_raw, close_raw, high_raw, low_raw, vol, amount):
        return (
            date_raw.to_bytes(4, "little")
            + _signed_varint(open_raw)
            + _signed_varint(close_raw)
            + _signed_varint(high_raw)
            + _signed_varint(low_raw)
            + struct.pack("<ff", vol, amount)
        )

    payload = (
        (3).to_bytes(2, "little")
        + bar(20260605, 10860, 10900, 11000, 10800, 12345.0, 5678900.0)
        + bar(20260608, 10900, 10880, 10950, 10870, 10000.0, 5000000.0)
        + bar(20260609, 10880, 10960, 10980, 10860, 9900.0, 4950000.0)
    )

    series = parse_command_response(
        TYPE_KLINES_0523,
        _response(payload, TYPE_KLINES_0523),
        {"code": "sz000001", "period": "day", "start": 0, "count": 2},
    )

    assert series.wire_count == 3
    assert series.count == 2  # 首条（多请求的那条）被丢弃，用于补 pre_close
    assert series.bars[0].time.isoformat() == "2026-06-08T15:00:00+08:00"
    assert series.bars[0].pre_close == 10.9  # 被丢弃首条的收盘 10900/1000
    assert (series.bars[0].open, series.bars[0].close) == (10.9, 10.88)
    assert (series.bars[0].high, series.bars[0].low) == (10.95, 10.87)
    assert series.bars[0].vol == 10000.0
    assert series.bars[0].amount == 5000000.0
    assert series.bars[0].rise_price == 10.88 - 10.9
    assert round(series.bars[0].rise_rate, 6) == round((10.88 - 10.9) / 10.9 * 100, 6)
    assert series.bars[1].pre_close == 10.88
    assert series.bars[1].rise_price == 10.96 - 10.88
    # gotdx 嗅探分支为死代码，0x0523 不读取 breadth 字段。
    assert series.bars[0].up_count is None
    assert series.bars[0].down_count is None


def test_parse_klines_0523_minute_period_uses_packed_datetime():
    def minute_bar(date_packed, minute_of_day, prices, vol, amount):
        return (
            date_packed.to_bytes(2, "little")
            + minute_of_day.to_bytes(2, "little")
            + b"".join(_signed_varint(p) for p in prices)
            + struct.pack("<ff", vol, amount)
        )

    # 2026-06-08 09:35：zipData = (2026-2004)<<11 | 6*100+8 = 45664
    payload = (
        (2).to_bytes(2, "little")
        + minute_bar(45664, 9 * 60 + 35, (10860, 10870, 10880, 10850), 100.0, 1000.0)
        + minute_bar(45664, 9 * 60 + 40, (10870, 10875, 10890, 10865), 120.0, 1200.0)
    )

    series = parse_command_response(
        TYPE_KLINES_0523,
        _response(payload, TYPE_KLINES_0523),
        {"code": "sz000001", "period": "5m", "start": 0, "count": 1},
    )

    assert series.count == 1
    assert series.period_raw == 0
    assert series.bars[0].time.isoformat() == "2026-06-08T09:40:00+08:00"
    assert series.bars[0].open == 10.87
