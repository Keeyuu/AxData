"""Wire tests for the MAC misc commands (server_info / kline_offset / file /
symbol_info / symbol_belong_board), ported from gotdx proto/mac_protocol_test.go.

Golden values replicate the gotdx tests verbatim (TestMACServerInfo...,
TestMACKLineOffset..., TestMACFileList..., TestMACFileDownload...,
TestMACSymbolInfo..., TestMACSymbolBelongBoard...); request bytes are
hand-constructed with head=0x01 (MAC_EX_PREFIX).
"""

from __future__ import annotations

import struct
from datetime import datetime

import pytest
from axdata_source_tdx._tdx_wire.protocol.commands import (
    build_command_frame,
    parse_command_response,
)
from axdata_source_tdx._tdx_wire.protocol.constants import (
    TYPE_MAC_CAPITAL_FLOW,
    TYPE_MAC_FILE_DOWNLOAD,
    TYPE_MAC_FILE_LIST,
    TYPE_MAC_KLINE_OFFSET,
    TYPE_MAC_SERVER_INFO,
    TYPE_MAC_SYMBOL_BELONG_BOARD,
    TYPE_MAC_SYMBOL_INFO,
)
from axdata_source_tdx._tdx_wire.protocol.frame import ResponseFrame


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


# ---------------------------------------------------------------- server info


def _server_info_body() -> bytes:
    body = bytearray()
    body += struct.pack("<H", 1)
    body += bytes([1, 2, 3, 4, 5, 6, 7, 8])
    body += b"-1\x00"
    body += b"\x00" * 9
    body += struct.pack("<I", 20260516)
    body += struct.pack("<I", 93000)
    body += struct.pack("<8H", 570, 690, 780, 900, 0, 0, 0, 0)
    body += struct.pack("<8H", 540, 660, 1260, 1380, 0, 0, 0, 0)
    body += bytes([7])
    body += struct.pack("<I", 20260515)
    body += struct.pack("<I", 1)
    body += struct.pack("<I", 20260514)
    body += struct.pack("<I", 2)
    body += struct.pack("<I", 10)
    body += struct.pack("<I", 20)
    body += b"\xaa\xbb"
    return bytes(body)


def test_build_mac_server_info_frame_default_payload():
    frame = build_command_frame(TYPE_MAC_SERVER_INFO, {}, 0)
    raw = frame.to_bytes()

    assert raw == bytes.fromhex(
        "01"
        + "00000000"
        + "01"
        + "4600"
        + "4600"
        + "0f12"
        + "04002d31"
        + "00" * 8
        + "0027060e"
        + "00" * 52
    )
    # gotdx 测试的 payload 定位断言：raw[12]=data[0]=0x04、raw[15]=data[3]=0x31、
    # raw[24]=data[12]=0x00、raw[25]=data[13]=0x27。
    assert len(frame.data) == 68
    assert frame.data[0] == 0x04
    assert frame.data[3] == 0x31
    assert frame.data[12] == 0x00
    assert frame.data[13] == 0x27


def test_parse_mac_server_info_payload_golden():
    body = _server_info_body()
    reply = parse_command_response(TYPE_MAC_SERVER_INFO, _response(body, TYPE_MAC_SERVER_INFO), {})

    assert reply.count == 1
    assert reply.flags_hex == "0102030405060708"
    assert reply.tag == "-1"
    assert reply.today == "2026-05-16"
    assert reply.ts1 == 93000
    assert len(reply.sessions1) == 4
    assert reply.sessions1[0].open_minutes == 570
    assert reply.sessions1[0].open == "9:30"
    assert reply.sessions1[0].close == "11:30"
    assert reply.sessions1[1].close == "15:00"
    assert len(reply.sessions2) == 4
    assert reply.sessions2[0].open_minutes == 540
    assert reply.sessions2[0].open == "9:00"
    assert reply.sessions2[1].close == "23:00"
    assert reply.flag == 7
    assert reply.last_trading_day == "2026-05-15"
    assert reply.ts2 == 1
    assert reply.last_trading_day2 == "2026-05-14"
    assert reply.ts3 == 2
    assert reply.market_param1 == 10
    assert reply.market_param2 == 20
    assert reply.extra_hex == "aabb"
    assert reply.raw_payload == b""


def test_parse_mac_server_info_keeps_raw_payload():
    body = _server_info_body()
    reply = parse_command_response(
        TYPE_MAC_SERVER_INFO, _response(body, TYPE_MAC_SERVER_INFO), {"include_raw": True}
    )
    assert reply.raw_payload == body


def test_parse_mac_server_info_rejects_short_payload():
    with pytest.raises(Exception, match="invalid mac server info payload length"):
        parse_command_response(
            TYPE_MAC_SERVER_INFO, _response(b"\x00" * 86, TYPE_MAC_SERVER_INFO), {}
        )


# -------------------------------------------------------------- kline offset


def test_build_mac_kline_offset_frame_golden():
    frame = build_command_frame(TYPE_MAC_KLINE_OFFSET, {"offset": 3, "count": 128000}, 0)
    raw = frame.to_bytes()

    assert raw == bytes.fromhex(
        "01" + "00000000" + "01" + "0f00" + "0f00" + "4a12" + "03000000" + "00f40100" + "0000000000"
    )
    assert frame.head == 0x01
    assert frame.msg_type == TYPE_MAC_KLINE_OFFSET


def test_build_mac_kline_offset_frame_defaults():
    frame = build_command_frame(TYPE_MAC_KLINE_OFFSET, {}, 0)

    assert len(frame.data) == 13
    assert frame.data[:4] == b"\x00" * 4
    assert frame.data[4:8] == (128000).to_bytes(4, "little")
    assert frame.data[8:13] == b"\x00" * 5


def test_parse_mac_kline_offset_payload_golden():
    # gotdx TestMACKLineOffset 金标准：total 大端 128000、returned 小端 2。
    body = bytes.fromhex("0001f40002000000")
    reply = parse_command_response(
        TYPE_MAC_KLINE_OFFSET, _response(body, TYPE_MAC_KLINE_OFFSET), {}
    )

    assert reply.total == 128000
    assert reply.returned == 2


def test_parse_mac_kline_offset_rejects_short_payload():
    with pytest.raises(Exception, match="invalid mac kline offset payload length"):
        parse_command_response(
            TYPE_MAC_KLINE_OFFSET, _response(b"\x00" * 7, TYPE_MAC_KLINE_OFFSET), {}
        )


# ---------------------------------------------------------------------- file


def test_build_mac_file_list_frame_golden():
    frame = build_command_frame(TYPE_MAC_FILE_LIST, {"filename": "StockInfo.dat", "offset": 16}, 0)
    raw = frame.to_bytes()

    assert frame.head == 0x01
    assert frame.msg_type == TYPE_MAC_FILE_LIST
    assert raw[0] == 0x01
    assert raw[6:8] == (106).to_bytes(2, "little")
    assert len(frame.data) == 104
    assert frame.data[:4] == (16).to_bytes(4, "little")
    assert frame.data[4:17] == b"StockInfo.dat"
    assert frame.data[17:74] == b"\x00" * 57
    assert frame.data[74:104] == b"\x00" * 30


def test_parse_mac_file_list_payload_golden():
    body = bytearray()
    body += struct.pack("<I", 16)
    body += struct.pack("<I", 1024)
    body += bytes([2])
    body += b"abcdef1234567890".ljust(32, b"\x00")
    reply = parse_command_response(
        TYPE_MAC_FILE_LIST, _response(bytes(body), TYPE_MAC_FILE_LIST), {}
    )

    assert reply.offset == 16
    assert reply.size == 1024
    assert reply.flag == 2
    assert reply.hash == "abcdef1234567890"


def test_parse_mac_file_list_negative_flag():
    body = bytearray()
    body += struct.pack("<I", 0)
    body += struct.pack("<I", 0)
    body += bytes([0xFF])
    body += b"\x00" * 32
    reply = parse_command_response(
        TYPE_MAC_FILE_LIST, _response(bytes(body), TYPE_MAC_FILE_LIST), {}
    )

    assert reply.flag == -1


def test_parse_mac_file_list_rejects_short_payload():
    with pytest.raises(Exception, match="invalid mac file list payload length"):
        parse_command_response(TYPE_MAC_FILE_LIST, _response(b"\x00" * 40, TYPE_MAC_FILE_LIST), {})


def test_build_mac_file_download_frame_golden():
    frame = build_command_frame(
        TYPE_MAC_FILE_DOWNLOAD,
        {"filename": "StockInfo.dat", "index": 3, "offset": 64, "size": 128},
        0,
    )
    raw = frame.to_bytes()

    assert frame.head == 0x01
    assert frame.msg_type == TYPE_MAC_FILE_DOWNLOAD
    assert raw[6:8] == (114).to_bytes(2, "little")
    assert len(frame.data) == 112
    assert frame.data[:4] == (3).to_bytes(4, "little")
    assert frame.data[4:8] == (64).to_bytes(4, "little")
    assert frame.data[8:12] == (128).to_bytes(4, "little")
    assert frame.data[12:25] == b"StockInfo.dat"
    assert frame.data[25:82] == b"\x00" * 57
    assert frame.data[82:112] == b"\x00" * 30


def test_build_mac_file_download_frame_defaults():
    frame = build_command_frame(TYPE_MAC_FILE_DOWNLOAD, {"filename": "x"}, 0)

    assert frame.data[:4] == (1).to_bytes(4, "little")
    assert frame.data[4:8] == b"\x00" * 4
    assert frame.data[8:12] == (30000).to_bytes(4, "little")


def test_parse_mac_file_download_payload_golden():
    body = struct.pack("<I", 3) + struct.pack("<I", 5) + b"hello"
    reply = parse_command_response(
        TYPE_MAC_FILE_DOWNLOAD, _response(body, TYPE_MAC_FILE_DOWNLOAD), {}
    )

    assert reply.index == 3
    assert reply.size == 5
    assert reply.data == b"hello"


def test_parse_mac_file_download_rejects_short_payload():
    with pytest.raises(Exception, match="invalid mac file download payload length"):
        parse_command_response(
            TYPE_MAC_FILE_DOWNLOAD, _response(b"\x00" * 7, TYPE_MAC_FILE_DOWNLOAD), {}
        )


# -------------------------------------------------------------- symbol info


def test_build_mac_symbol_info_frame_golden():
    frame = build_command_frame(TYPE_MAC_SYMBOL_INFO, {"code": "600000.SH"}, 0)
    raw = frame.to_bytes()

    assert frame.head == 0x01
    assert frame.msg_type == TYPE_MAC_SYMBOL_INFO
    assert raw[0] == 0x01
    assert raw[6:8] == (42).to_bytes(2, "little")
    assert len(frame.data) == 40
    assert frame.data[:2] == (1).to_bytes(2, "little")
    assert frame.data[2:24] == b"600000".ljust(22, b"\x00")
    assert frame.data[24:28] == (1).to_bytes(4, "little")
    assert frame.data[28:40] == b"\x00" * 12


def _symbol_info_body() -> bytes:
    body = bytearray()
    body += b"\x00" * 8
    body += struct.pack("<H", 1)
    body += b"600000".ljust(22, b"\x00")
    body += b"PingAn Bank".ljust(44, b"\x00")
    body += b"\x00" * 20
    body += struct.pack("<I", 20260418)
    body += struct.pack("<I", 150005)
    body += struct.pack("<I", 321)
    for value in (10.0, 10.1, 10.3, 9.9, 10.2, 0.2):
        body += struct.pack("<f", value)
    body += struct.pack("<I", 220)
    body += struct.pack("<f", 12345.6)
    body += struct.pack("<I", 100)
    body += struct.pack("<I", 120)
    body += struct.pack("<H", 2)
    body += struct.pack("<I", 11)
    body += struct.pack("<f", 22.5)
    body += b"\x00" * 20
    body += struct.pack("<I", 33)
    body += struct.pack("<f", 1.5)
    body += struct.pack("<f", 2.5)
    body += struct.pack("<f", 10.1)
    return bytes(body)


def test_parse_mac_symbol_info_payload_golden():
    body = _symbol_info_body()
    assert len(body) == 194
    reply = parse_command_response(
        TYPE_MAC_SYMBOL_INFO, _response(body, TYPE_MAC_SYMBOL_INFO), {"code": "600000.SH"}
    )

    assert reply.market == 1
    assert reply.code == "600000"
    assert reply.name == "PingAn Bank"
    assert reply.date_time == datetime(2026, 4, 18, 15, 0, 5)
    assert reply.activity == 321
    assert reply.pre_close == pytest.approx(10.0)
    assert reply.open == pytest.approx(10.1)
    assert reply.high == pytest.approx(10.3)
    assert reply.low == pytest.approx(9.9)
    assert reply.close == pytest.approx(10.2)
    assert reply.momentum == pytest.approx(0.2)
    assert reply.vol == 220
    assert reply.amount == pytest.approx(12345.6)
    assert reply.inside_volume == 100
    assert reply.outside_volume == 120
    assert reply.decimal == 2
    assert reply.unknown_a == 11
    assert reply.unknown_b == pytest.approx(22.5)
    assert reply.unknown_c == 33
    assert reply.vr == pytest.approx(1.5)
    assert reply.turnover == pytest.approx(2.5)
    assert reply.avg == pytest.approx(10.1)
    assert reply.raw_payload == b""


def test_parse_mac_symbol_info_keeps_raw_payload():
    body = _symbol_info_body()
    reply = parse_command_response(
        TYPE_MAC_SYMBOL_INFO,
        _response(body, TYPE_MAC_SYMBOL_INFO),
        {"code": "600000.SH", "include_raw": True},
    )
    assert reply.raw_payload == body


def test_parse_mac_symbol_info_rejects_short_payload():
    with pytest.raises(Exception, match="invalid mac symbol info payload length"):
        parse_command_response(
            TYPE_MAC_SYMBOL_INFO, _response(b"\x00" * 193, TYPE_MAC_SYMBOL_INFO), {}
        )


# ---------------------------------------------------------- belong board


def _belong_board_body_nine() -> bytes:
    body = bytearray()
    body += struct.pack("<H", 1)
    body += b"Stock_GLHQ".ljust(12, b"\x00")
    body += b"\x00" * 13
    body += b'[["HY",1,"880001","Coal",10.5,10.0,1,2,3]]'
    return bytes(body)


def _belong_board_body_thirteen() -> bytes:
    body = bytearray()
    body += struct.pack("<H", 1)
    body += b"Stock_GLHQ".ljust(12, b"\x00")
    body += b"\x00" * 13
    body += b'[["HY",1,"880001","Coal",10.5,10.0,2.5,1,"600001","Peer",11.1,10.9,1.2]]'
    return bytes(body)


def test_build_mac_symbol_belong_board_via_01218_route():
    # 0x1218 同码路由：TYPE_MAC_SYMBOL_BELONG_BOARD 走 mac_capital_flow builder，
    # 按 query="Stock_GLHQ" 分流到 belong board（head=0x01）。
    frame = build_command_frame(
        TYPE_MAC_SYMBOL_BELONG_BOARD, {"code": "600000.SH", "query": "Stock_GLHQ"}, 0
    )
    raw = frame.to_bytes()

    assert frame.head == 0x01
    assert frame.msg_type == TYPE_MAC_SYMBOL_BELONG_BOARD
    assert raw[0] == 0x01
    assert raw[6:8] == (49).to_bytes(2, "little")
    assert len(frame.data) == 47
    assert frame.data[:2] == (1).to_bytes(2, "little")
    assert frame.data[2:10] == b"600000\x00\x00"
    assert frame.data[10:26] == b"\x00" * 16
    assert frame.data[26:47] == b"Stock_GLHQ".ljust(21, b"\x00")


def test_parse_mac_symbol_belong_board_nine_columns():
    body = _belong_board_body_nine()
    reply = parse_command_response(
        TYPE_MAC_SYMBOL_BELONG_BOARD, _response(body, TYPE_MAC_SYMBOL_BELONG_BOARD), {}
    )

    assert reply.market == 1
    assert reply.query == "Stock_GLHQ"
    assert len(reply.items) == 1
    item = reply.items[0]
    assert item.board_type == "HY"
    assert item.market_code == 1
    assert item.status_code == 1
    assert item.board_code == "880001"
    assert item.board_name == "Coal"
    assert item.price == pytest.approx(10.5)
    assert item.pre_close == pytest.approx(10.0)
    assert item.schema_columns == 9
    assert item.limit_up_count == pytest.approx(1.0)
    assert item.limit_down_count == pytest.approx(2.0)
    assert item.most_similar == pytest.approx(3.0)
    assert item.metric1 == pytest.approx(1.0)
    assert item.metric2 == pytest.approx(2.0)
    assert item.metric3 == pytest.approx(3.0)
    assert item.speed_pct == 0.0
    assert item.symbol == ""


def test_parse_mac_symbol_belong_board_expanded_schema():
    body = _belong_board_body_thirteen()
    reply = parse_command_response(
        TYPE_MAC_SYMBOL_BELONG_BOARD, _response(body, TYPE_MAC_SYMBOL_BELONG_BOARD), {}
    )

    assert len(reply.items) == 1
    item = reply.items[0]
    assert item.schema_columns == 13
    assert item.speed_pct == pytest.approx(2.5)
    assert item.symbol_market == 1
    assert item.symbol == "600001"
    assert item.symbol_name == "Peer"
    assert item.symbol_close == pytest.approx(11.1)
    assert item.symbol_pre_close == pytest.approx(10.9)
    assert item.symbol_speed_pct == pytest.approx(1.2)
    assert item.metric1 == pytest.approx(2.5)
    assert item.metric2 == pytest.approx(11.1)
    assert item.metric3 == pytest.approx(1.2)
    assert item.limit_up_count == 0.0
    assert item.limit_down_count == 0.0
    assert item.most_similar == 0.0


def test_parse_mac_capital_flow_dispatches_to_belong_board():
    # parse 侧按响应回显的 query 常量（data[2:14]=Stock_GLHQ）分流。
    reply = parse_command_response(
        TYPE_MAC_CAPITAL_FLOW, _response(_belong_board_body_nine(), TYPE_MAC_CAPITAL_FLOW), {}
    )

    assert reply.__class__.__name__ == "MacSymbolBelongBoardList"
    assert reply.market == 1
    assert reply.query == "Stock_GLHQ"
    assert len(reply.items) == 1


def test_parse_mac_symbol_belong_board_skips_short_rows():
    body = bytearray()
    body += struct.pack("<H", 1)
    body += b"Stock_GLHQ".ljust(12, b"\x00")
    body += b"\x00" * 13
    body += b'[["HY",1,"880001",1,2,3],["HY",1,"880001","Coal",10.5,10.0,1,2,3]]'
    reply = parse_command_response(
        TYPE_MAC_SYMBOL_BELONG_BOARD, _response(bytes(body), TYPE_MAC_SYMBOL_BELONG_BOARD), {}
    )

    assert len(reply.items) == 1
    assert reply.items[0].board_code == "880001"


def test_parse_mac_symbol_belong_board_tolerates_other_schemas():
    body = bytearray()
    body += struct.pack("<H", 1)
    body += b"Stock_GLHQ".ljust(12, b"\x00")
    body += b"\x00" * 13
    body += b'[["HY",1,"880001","Coal",10.5,10.0,7.5,8.5,9.5,10.5]]'
    reply = parse_command_response(
        TYPE_MAC_SYMBOL_BELONG_BOARD, _response(bytes(body), TYPE_MAC_SYMBOL_BELONG_BOARD), {}
    )

    assert len(reply.items) == 1
    item = reply.items[0]
    assert item.schema_columns == 10
    assert item.metric1 == pytest.approx(7.5)
    assert item.metric2 == pytest.approx(8.5)
    assert item.metric3 == pytest.approx(9.5)


def test_parse_mac_symbol_belong_board_keeps_raw_payload():
    body = _belong_board_body_nine()
    reply = parse_command_response(
        TYPE_MAC_SYMBOL_BELONG_BOARD,
        _response(body, TYPE_MAC_SYMBOL_BELONG_BOARD),
        {"include_raw": True},
    )
    assert reply.raw_payload == body


def test_parse_mac_symbol_belong_board_rejects_short_payload():
    # 0x1218 dispatch 先落在 mac_capital_flow parser，长度检查在其分流之前。
    with pytest.raises(Exception, match="invalid mac capital flow payload length"):
        parse_command_response(
            TYPE_MAC_SYMBOL_BELONG_BOARD, _response(b"\x00" * 26, TYPE_MAC_SYMBOL_BELONG_BOARD), {}
        )


def test_parse_mac_symbol_belong_board_rejects_bad_json():
    body = bytearray()
    body += struct.pack("<H", 1)
    body += b"Stock_GLHQ".ljust(12, b"\x00")
    body += b"\x00" * 13
    body += b"not json"
    with pytest.raises(Exception, match="invalid mac belong board json rows"):
        parse_command_response(
            TYPE_MAC_SYMBOL_BELONG_BOARD, _response(bytes(body), TYPE_MAC_SYMBOL_BELONG_BOARD), {}
        )
