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
    TYPE_CHART_SAMPLING,
    TYPE_HISTORICAL_INTRADAY,
    TYPE_HISTORICAL_TRADES,
    TYPE_INDEX_INFO,
    TYPE_INDEX_MOMENTUM,
    TYPE_REFRESH_QUOTES,
    TYPE_SECURITY_LIST_OLD,
    TYPE_SERVER_INFO,
    TYPE_TOP_BOARD,
    TYPE_UNUSUAL,
    TYPE_VOLUME_PROFILE,
)
from axdata_source_tdx._tdx_wire.protocol.frame import ResponseFrame

if sys.path and sys.path[0] == _TDX_PROVIDER_SRC:
    sys.path.pop(0)


def _varint(value: int) -> bytes:
    negative = value < 0
    magnitude = -value if negative else value
    chunk = magnitude & 0x3F
    magnitude >>= 6
    flags = 0x40 if negative else 0x00
    out = bytearray()
    if magnitude:
        out.append(chunk | flags | 0x80)
        while True:
            byte = magnitude & 0x7F
            magnitude >>= 7
            out.append(byte | (0x80 if magnitude else 0))
            if not magnitude:
                break
    else:
        out.append(chunk | flags)
    return bytes(out)


def _response(payload: bytes, msg_type: int) -> ResponseFrame:
    return ResponseFrame(
        control=0,
        msg_id=1,
        msg_type=msg_type,
        zip_length=len(payload),
        length=len(payload),
        data=payload,
        raw=b"",
    )


# ---------------------------------------------------------------------------
# security_list_old (0x0450) — gotdx proto/get_security_list_old.go
# ---------------------------------------------------------------------------


def test_build_security_list_old_frame_uses_0450_payload():
    frame = build_command_frame(TYPE_SECURITY_LIST_OLD, {"market": "sh", "start": 100}, 7)

    assert frame.msg_type == TYPE_SECURITY_LIST_OLD
    assert frame.data.hex() == "01006400"


def test_parse_security_list_old_payload_decodes_legacy_records():
    record_1 = (
        b"600000"
        + (100).to_bytes(2, "little")
        + "浦发银行".encode("gbk")
        + (7).to_bytes(2, "little")
        + b"\x00\x00"
        + b"\x02"
        + struct.pack("<f", 10.5)
        + (3).to_bytes(2, "little")
        + (4).to_bytes(2, "little")
    )
    record_2 = (
        b"000001"
        + (200).to_bytes(2, "little")
        + "平安银行".encode("gbk")
        + (9).to_bytes(2, "little")
        + b"\x00\x00"
        + b"\x02"
        + struct.pack("<f", 12.25)
        + (5).to_bytes(2, "little")
        + (6).to_bytes(2, "little")
    )
    payload = (2).to_bytes(2, "little") + record_1 + record_2

    page = parse_command_response(
        TYPE_SECURITY_LIST_OLD,
        _response(payload, TYPE_SECURITY_LIST_OLD),
        {"market": "sh", "start": 100},
    )

    assert page.exchange == "sh"
    assert page.market_id == 1
    assert page.start == 100
    assert page.count == 2
    assert page.codes[0].code == "600000"
    assert page.codes[0].name == "浦发银行"
    assert page.codes[0].vol == 100
    assert page.codes[0].vol_unit == 100
    assert page.codes[0].unknown1 == 7.0
    assert page.codes[0].legacy_unknown1 == 7
    assert page.codes[0].decimal_point == 2
    assert page.codes[0].pre_close == 10.5
    assert page.codes[0].unknown2 == 3
    assert page.codes[0].unknown3 == 4
    assert page.codes[1].code == "000001"
    assert page.codes[1].pre_close == 12.25


# ---------------------------------------------------------------------------
# chart_sampling (0x0FD1) — gotdx proto/get_chart_sampling.go
# ---------------------------------------------------------------------------


def test_build_chart_sampling_frame_uses_0fd1_payload_with_default_reserved():
    frame = build_command_frame(TYPE_CHART_SAMPLING, {"code": "sz000001"}, 11)

    assert frame.msg_type == TYPE_CHART_SAMPLING
    assert frame.data.hex() == (
        "0000"
        "303030303031"
        "00000000000000000000000000000000"
        "0100140000000001"
        "00000000"
    )
    assert len(frame.data) == 36


def test_parse_chart_sampling_payload_reads_count_preclose_and_prices():
    payload = (
        (1).to_bytes(2, "little")
        + b"000001"
        + b"\x00" * 26
        + (3).to_bytes(2, "little")
        + struct.pack("<f", 10.5)
        + b"\x00\x00"
        + struct.pack("<f", 10.4)
        + struct.pack("<f", 10.6)
        + struct.pack("<f", 10.8)
    )

    series = parse_command_response(
        TYPE_CHART_SAMPLING,
        _response(payload, TYPE_CHART_SAMPLING),
        {"code": "sh000001"},
    )

    assert series.market_id == 1
    assert series.exchange == "sh"
    assert series.code == "000001"
    assert series.full_code == "sh000001"
    assert series.count == 3
    assert series.pre_close == 10.5
    assert [round(price, 3) for price in series.prices] == [10.4, 10.6, 10.8]


# ---------------------------------------------------------------------------
# index_info (0x051D) — gotdx proto/get_index_info.go
# ---------------------------------------------------------------------------


def test_build_index_info_frame_uses_051d_payload():
    frame = build_command_frame(TYPE_INDEX_INFO, {"code": "sh000001"}, 3)

    assert frame.msg_type == TYPE_INDEX_INFO
    assert frame.data.hex() == "010030303030303100000000"
    assert len(frame.data) == 12


def test_parse_index_info_payload_decodes_snapshot_and_orders():
    payload = (
        (2).to_bytes(4, "little")
        + b"\x01"
        + b"000001"
        + (77).to_bytes(2, "little")
        + _varint(2999)
        + _varint(15)
        + _varint(-10)
        + _varint(21)
        + _varint(-25)
        + _varint(93500)
        + _varint(0)
        + _varint(123456)
        + _varint(789)
        + struct.pack("<f", 4567.5)
        + _varint(0)
        + _varint(0)
        + _varint(321)
        + _varint(0) * 4
        + _varint(1200)
        + _varint(1100)
        + _varint(0) * 9
        + _varint(2999)
        + _varint(0)
        + _varint(500)
        + _varint(1)
        + _varint(2)
        + _varint(300)
    )

    snapshot = parse_command_response(
        TYPE_INDEX_INFO,
        _response(payload, TYPE_INDEX_INFO),
        {"code": "sh000001"},
    )

    assert snapshot.order_count == 2
    assert snapshot.market_id == 1
    assert snapshot.full_code == "sh000001"
    assert snapshot.active == 77
    assert snapshot.close == 29.99
    assert snapshot.pre_close == 30.14
    assert snapshot.diff == -0.15
    assert snapshot.open == 29.89
    assert snapshot.high == 30.20
    assert snapshot.low == 29.74
    assert snapshot.server_time == "00:09:21.000"
    assert snapshot.after_hour == 0
    assert snapshot.vol == 123456
    assert snapshot.cur_vol == 789
    assert snapshot.amount == 4567.5
    assert snapshot.open_amount == 321
    assert snapshot.up_count == 1200
    assert snapshot.down_count == 1100
    assert [(order.price, order.unknown, order.vol) for order in snapshot.orders] == [
        (29.99, 0, 500),
        (30.00, 2, 300),
    ]


# ---------------------------------------------------------------------------
# index_momentum (0x051C) — gotdx proto/get_index_momentum.go
# ---------------------------------------------------------------------------


def test_build_index_momentum_frame_uses_051c_payload():
    frame = build_command_frame(TYPE_INDEX_MOMENTUM, {"code": "sh000001"}, 4)

    assert frame.msg_type == TYPE_INDEX_MOMENTUM
    assert frame.data.hex() == "0100303030303031"
    assert len(frame.data) == 8


def test_parse_index_momentum_payload_accumulates_varint_deltas():
    payload = (3).to_bytes(2, "little") + _varint(1) + _varint(-1) + _varint(2)

    series = parse_command_response(
        TYPE_INDEX_MOMENTUM,
        _response(payload, TYPE_INDEX_MOMENTUM),
        {"code": "sh000001"},
    )

    assert series.full_code == "sh000001"
    assert series.count == 3
    assert list(series.values) == [1, 0, 2]


# ---------------------------------------------------------------------------
# top_board (0x053F) — gotdx proto/get_top_board.go
# ---------------------------------------------------------------------------


def test_build_top_board_frame_uses_053f_payload_with_gotdx_defaults():
    frame = build_command_frame(TYPE_TOP_BOARD, {"category": 1}, 6)

    assert frame.msg_type == TYPE_TOP_BOARD
    assert frame.data.hex() == "01050000000001000014"
    assert len(frame.data) == 10


def test_parse_top_board_payload_decodes_nine_boards():
    item = (
        b"\x01"
        + b"600000"
        + struct.pack("<f", 12.5)
        + struct.pack("<f", 3.25)
    )
    payload = b"\x01" + item * 9

    page = parse_command_response(TYPE_TOP_BOARD, _response(payload, TYPE_TOP_BOARD), {})

    assert page.size == 1
    assert page.increase[0].full_code == "sh600000"
    assert page.increase[0].price == 12.5
    assert page.increase[0].value == 3.25
    assert page.decrease[0].code == "600000"
    assert page.turnover[0].market_id == 1
    assert [len(items) for items in page.boards.values()] == [1] * 9
    assert tuple(page.boards) == (
        "increase",
        "decrease",
        "amplitude",
        "rise_speed",
        "fall_speed",
        "vol_ratio",
        "pos_commission_ratio",
        "neg_commission_ratio",
        "turnover",
    )


# ---------------------------------------------------------------------------
# unusual (0x0563) — gotdx proto/get_unusual.go
# ---------------------------------------------------------------------------


def test_build_unusual_frame_uses_0563_payload_with_default_count():
    frame = build_command_frame(TYPE_UNUSUAL, {"market": "sh", "start": 0}, 8)

    assert frame.msg_type == TYPE_UNUSUAL
    assert frame.data.hex() == "01000000000058020000"
    assert len(frame.data) == 10


def test_parse_unusual_payload_decodes_records_and_event_types():
    record = (
        (0).to_bytes(2, "little")
        + b"600000"
        + b"\x00"
        + b"\x04"
        + b"\x00"
        + (5).to_bytes(2, "little")
        + b"\x00\x00"
        + b"\x00"
        + struct.pack("<f", 1.5)
        + struct.pack("<f", 0.0)
        + struct.pack("<f", 0.0)
        + b"\x00"
        + b"\x09"
        + (3059).to_bytes(2, "little")
    )
    assert len(record) == 32
    payload = (1).to_bytes(2, "little") + record

    page = parse_command_response(
        TYPE_UNUSUAL,
        _response(payload, TYPE_UNUSUAL),
        {"market": "sz", "start": 0, "count": 600},
    )

    assert page.exchange == "sz"
    assert page.request_count == 600
    assert page.count == 1
    entry = page.records[0]
    assert entry.index == 5
    assert entry.market_id == 0
    assert entry.code == "600000"
    assert entry.unusual_type == 0x04
    assert entry.desc == "加速拉升"
    assert entry.value == "150.00%"
    assert entry.time == "09:30:59"


# ---------------------------------------------------------------------------
# volume_profile (0x051A) — gotdx proto/get_volume_profile.go
# ---------------------------------------------------------------------------


def test_build_volume_profile_frame_uses_051a_payload():
    frame = build_command_frame(TYPE_VOLUME_PROFILE, {"code": "sz000001"}, 9)

    assert frame.msg_type == TYPE_VOLUME_PROFILE
    assert frame.data.hex() == "0000303030303031"
    assert len(frame.data) == 8


def test_parse_volume_profile_payload_decodes_snapshot_levels_and_profiles():
    payload = (
        (2).to_bytes(2, "little")
        + b"\x00"
        + b"000001"
        + (55).to_bytes(2, "little")
        + _varint(1500)
        + _varint(10)
        + _varint(-5)
        + _varint(20)
        + _varint(-10)
        + _varint(0)
        + _varint(0)
        + _varint(9000)
        + _varint(100)
        + struct.pack("<f", 12345.5)
        + _varint(4000)
        + _varint(5000)
        + _varint(12)
        + _varint(34)
        + (_varint(-10) + _varint(10) + _varint(100) + _varint(200)) * 3
        + (7).to_bytes(2, "little")
        + _varint(1500)
        + _varint(100)
        + _varint(60)
        + _varint(40)
        + _varint(-100)
        + _varint(50)
        + _varint(20)
        + _varint(30)
    )

    snapshot = parse_command_response(
        TYPE_VOLUME_PROFILE,
        _response(payload, TYPE_VOLUME_PROFILE),
        {"code": "sz000001"},
    )

    assert snapshot.full_code == "sz000001"
    assert snapshot.count == 2
    assert snapshot.market_id == 0
    assert snapshot.active == 55
    assert snapshot.close == 15.00
    assert snapshot.pre_close == 15.10
    assert snapshot.open == 14.95
    assert snapshot.high == 15.20
    assert snapshot.low == 14.90
    assert snapshot.server_time == "00:00:00.000"
    assert snapshot.neg_price == 0.0
    assert snapshot.vol == 9000
    assert snapshot.cur_vol == 100
    assert snapshot.amount == 12345.5
    assert snapshot.in_vol == 4000
    assert snapshot.out_vol == 5000
    assert snapshot.s_amount == 12
    assert snapshot.open_amount == 34
    assert snapshot.bid_levels[0].price == 14.90
    assert snapshot.bid_levels[0].vol == 100
    assert snapshot.ask_levels[0].price == 15.10
    assert snapshot.ask_levels[0].vol == 200
    assert len(snapshot.bid_levels) == 3
    assert len(snapshot.ask_levels) == 3
    assert snapshot.unknown == 7
    assert [(item.price, item.vol, item.buy, item.sell) for item in snapshot.vol_profiles] == [
        (15.00, 100, 60, 40),
        (14.00, 50, 20, 30),
    ]


# ---------------------------------------------------------------------------
# server_info (0x0015) — gotdx proto/server.go Info/InfoReply
# ---------------------------------------------------------------------------


def test_build_server_info_frame_uses_empty_payload():
    frame = build_command_frame(TYPE_SERVER_INFO, {}, 10)

    assert frame.msg_type == TYPE_SERVER_INFO
    assert frame.data == b""


def test_parse_server_info_payload_decodes_fixed_offset_block():
    buf = bytearray(427)
    buf[0:4] = (12).to_bytes(4, "little")
    buf[4:6] = (1).to_bytes(2, "little")
    buf[6:14] = b"\xab" * 8
    buf[14:16] = (2).to_bytes(2, "little")
    buf[16:71] = "TDX行情服务器".encode("gbk").ljust(55, b"\x00")
    buf[81:336] = b"hello world".ljust(255, b"\x00")
    buf[336:356] = b"tdx-server-sign-01".ljust(20, b"\x00")
    buf[360:362] = (3).to_bytes(2, "little")
    buf[362:364] = (4).to_bytes(2, "little")
    buf[364:370] = b"\xcd" * 6
    buf[389:391] = (86).to_bytes(2, "little")
    buf[391:393] = (99).to_bytes(2, "little")
    buf[395:397] = (1).to_bytes(2, "little")
    buf[397:401] = (20260814).to_bytes(4, "little")
    buf[401:405] = (93500).to_bytes(4, "little")

    info = parse_command_response(TYPE_SERVER_INFO, _response(bytes(buf), TYPE_SERVER_INFO))

    assert info.delay == 12
    assert info.info == "TDX行情服务器"
    assert info.content == "hello world"
    assert info.server_sign == "tdx-server-sign-01"
    assert info.time_now == "2026-08-14 09:35:00"
    assert info.region == 86
    assert info.maybe_switch == 1
    assert info.unknown1 == ("1", "2", "ab" * 8)
    assert info.unknown2 == ("3", "4", "cd" * 6)
    assert info.unknown3 == (86, 99, 1)


# ---------------------------------------------------------------------------
# N/A 判定（计划 19 §4.1 P2 行 11 项中的 3 项）：gotdx 命令与我方已注册命令
# 是同一 wire 命令（同码 + 同请求布局），按码分发的注册表不允许二次注册，
# 故落 N/A 并以字节级等价测试钉住。
# ---------------------------------------------------------------------------


def test_quotes_encrypt_na_matches_refresh_quotes_request_layout():
    # gotdx get_quotes_encrypt.go: u16 count + [u8 market + code[6] + u16 22234 + u16 2]
    gotdx_expected = (
        (1).to_bytes(2, "little")
        + b"\x00"
        + b"000001"
        + (22234).to_bytes(2, "little")
        + (2).to_bytes(2, "little")
    )
    frame = build_command_frame(
        TYPE_REFRESH_QUOTES,
        {"items": [("sz", "000001", 22234 | (2 << 16))]},
        9,
    )

    assert frame.msg_type == TYPE_REFRESH_QUOTES
    assert frame.data == gotdx_expected


def test_history_orders_na_matches_historical_intraday_request_layout():
    # gotdx get_history_orders.go: u32 date + u8 market + code[6]
    gotdx_expected = (20240419).to_bytes(4, "little") + b"\x00" + b"000001"
    frame = build_command_frame(
        TYPE_HISTORICAL_INTRADAY,
        {"code": "sz000001", "trade_date": 20240419},
        5,
    )

    assert frame.msg_type == TYPE_HISTORICAL_INTRADAY
    assert frame.data == gotdx_expected


def test_historical_trades_with_trans_na_matches_historical_trades_request_layout():
    # gotdx get_history_transaction_data_trans.go request struct:
    # u32 date + u16 market + code[6] + u16 start + u16 count
    gotdx_expected = (
        (20240419).to_bytes(4, "little")
        + (0).to_bytes(2, "little")
        + b"000001"
        + (0).to_bytes(2, "little")
        + (900).to_bytes(2, "little")
    )
    frame = build_command_frame(
        TYPE_HISTORICAL_TRADES,
        {"code": "sz000001", "trade_date": 20240419, "start": 0, "count": 900},
        5,
    )

    assert frame.msg_type == TYPE_HISTORICAL_TRADES
    assert frame.data == gotdx_expected
