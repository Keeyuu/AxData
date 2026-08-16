"""Wire tests for the MAC board/monitor family (Wave2-B slice C).

Golden vectors mirror gotdx ``proto/mac_protocol_test.go``
(TestMACBoardCount/List, TestMACBoardMembers(+Quotes/Dynamic),
TestMACSymbolQuotes, TestMACMarketMonitor) and
TestMACDynamicFieldMapAlignsLatestTDX. All build tests assert the exact frame
bytes (head=0x01, the 12-byte <BIBHHH header, and the payload layout); parse
tests feed hand-built response bodies and assert every field.
"""

from __future__ import annotations

import struct

import pytest
from axdata_source_tdx._tdx_wire.protocol.commands import (
    build_command_frame,
    parse_command_response,
)
from axdata_source_tdx._tdx_wire.protocol.constants import (
    TYPE_MAC_BOARD_LIST,
    TYPE_MAC_BOARD_MEMBERS,
    TYPE_MAC_MARKET_MONITOR,
    TYPE_MAC_SYMBOL_QUOTES,
)
from axdata_source_tdx._tdx_wire.protocol.frame import ResponseFrame


def _f32(value: float) -> bytes:
    return struct.pack("<f", value)


def _u16(value: int) -> bytes:
    return value.to_bytes(2, "little", signed=False)


def _u32(value: int) -> bytes:
    return value.to_bytes(4, "little", signed=False)


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


# ---------------------------------------------------------------- board list


def test_build_mac_board_list_frame_default_exact_bytes():
    frame = build_command_frame(TYPE_MAC_BOARD_LIST, {}, 0)

    assert frame.to_bytes()[0] == 0x01  # gotdx buildExRequest head
    assert frame.to_bytes()[10:12] == _u16(0x1231)
    body = frame.to_bytes()[12:]
    assert body == bytes.fromhex(
        "9600"  # PageSize u16 = 150
        "0000"  # BoardType u16 = 0
        "00"  # SortType u8 = 0
        "01"  # SortOrder u8 = 1
        "0000"  # Start u16 = 0
        "0100"  # One u16 = 1
        "0000000000000000"  # Reserved[8]
    )


def test_build_mac_board_list_frame_board_type_and_start():
    frame = build_command_frame(TYPE_MAC_BOARD_LIST, {"board_type": 5, "start": 10}, 0)

    body = frame.to_bytes()[12:]
    assert body[2:4] == _u16(5)  # BoardType
    assert body[6:8] == _u16(10)  # Start
    assert body[0:2] == _u16(150)  # PageSize default kept
    assert body[8:10] == _u16(1)  # One default kept


def test_build_mac_board_count_frame_identical_to_list_frame():
    # N/A 等价核心证据：count_only 请求帧与 board_list(start=0) 帧字节完全一致。
    count_frame = build_command_frame(TYPE_MAC_BOARD_LIST, {"board_type": 5, "count_only": True}, 7)
    list_frame = build_command_frame(TYPE_MAC_BOARD_LIST, {"board_type": 5, "start": 0}, 7)

    assert count_frame.to_bytes() == list_frame.to_bytes()


def test_parse_mac_board_list_payload_count_only_golden():
    # gotdx TestMACBoardCountBuildRequestAndParseResponse: payload
    # 2c 01 2f 02 -> count_all=300, total=559；count 语义不要求后续字节。
    page = parse_command_response(
        TYPE_MAC_BOARD_LIST,
        _response(bytes.fromhex("2c012f02"), TYPE_MAC_BOARD_LIST),
        {"board_type": 5, "count_only": True},
    )

    assert page.count_all == 300
    assert page.total == 559
    assert page.count == 0
    assert page.rows == ()


def test_parse_mac_board_list_payload_decodes_row_golden():
    # gotdx TestMACBoardListParseResponse：count_all=2 -> count=1 行。
    buf = bytearray()
    buf += _u16(2)  # count_all
    buf += _u16(559)  # total
    buf += _u16(1)  # market
    buf += b"880001"
    buf += b"\x00" * 16
    buf += b"Coal".ljust(44, b"\x00")
    buf += _f32(10.5)
    buf += _f32(0.8)
    buf += _f32(10.0)
    buf += _u16(0)  # symbol_market
    buf += b"000001"
    buf += b"\x00" * 16
    buf += b"PingAn".ljust(44, b"\x00")
    buf += _f32(12.3)
    buf += _f32(0.1)
    buf += _f32(12.0)

    page = parse_command_response(
        TYPE_MAC_BOARD_LIST, _response(bytes(buf), TYPE_MAC_BOARD_LIST), {}
    )

    assert page.count_all == 2
    assert page.total == 559
    assert page.count == 1
    assert len(page.rows) == 1
    row = page.rows[0]
    assert row.market == 1
    assert row.code == "880001"
    assert row.name == "Coal"
    assert row.price == pytest.approx(10.5)
    assert row.rise_speed == pytest.approx(0.8)
    assert row.pre_close == pytest.approx(10.0)
    assert row.symbol_market == 0
    assert row.symbol_code == "000001"
    assert row.symbol_name == "PingAn"
    assert row.symbol_price == pytest.approx(12.3)
    assert row.symbol_rise_speed == pytest.approx(0.1)
    assert row.symbol_pre_close == pytest.approx(12.0)


def test_parse_mac_board_list_payload_count_all_fallback():
    # count_all=1 时 count=count_all/2=0 -> 回退 count_all。
    buf = _u16(1) + _u16(10) + b"\x00" * 160
    page = parse_command_response(
        TYPE_MAC_BOARD_LIST, _response(bytes(buf), TYPE_MAC_BOARD_LIST), {}
    )

    assert page.count_all == 1
    assert page.count == 1
    assert len(page.rows) == 1


def test_parse_mac_board_list_payload_rejects_short_head():
    with pytest.raises(Exception, match="invalid mac board list payload length"):
        parse_command_response(TYPE_MAC_BOARD_LIST, _response(b"\x00\x00", TYPE_MAC_BOARD_LIST), {})


def test_parse_mac_board_list_payload_rejects_truncated_row():
    buf = _u16(2) + _u16(559) + b"\x00" * 100  # count=1 但行不足 160
    with pytest.raises(Exception, match="truncated mac board list item"):
        parse_command_response(TYPE_MAC_BOARD_LIST, _response(bytes(buf), TYPE_MAC_BOARD_LIST), {})


# ------------------------------------------------------------ board members


def test_build_mac_board_members_frame_plain_form_layout():
    frame = build_command_frame(
        TYPE_MAC_BOARD_MEMBERS,
        {"board_symbol": "880761", "start": 10},
        0,
    )

    assert frame.to_bytes()[0] == 0x01
    assert frame.to_bytes()[10:12] == _u16(0x122C)
    body = frame.to_bytes()[12:]
    assert len(body) == 43
    assert body[0:4] == _u32(20761)  # exchange_mac_board_code("880761")
    assert body[13:15] == _u16(14)  # SortType 默认 14
    assert body[15:19] == _u32(10)  # Start
    assert body[19] == 80  # PageSize 默认 80
    assert body[20] == 0  # Zero
    assert body[21:23] == _u16(1)  # SortOrder u16
    assert body[23:43] == b"\x00" * 20  # Extra[20] 全 0


def test_build_mac_board_members_frame_quotes_form_layout():
    frame = build_command_frame(
        TYPE_MAC_BOARD_MEMBERS,
        {"board_symbol": "880761", "include_quotes": True},
        0,
    )

    body = frame.to_bytes()[12:]
    assert len(body) == 43
    assert body[0:4] == _u32(20761)
    assert body[19] == 80  # PageSize u8
    assert body[20] == 0  # Zero
    assert body[21] == 1  # SortOrder u8
    extra = body[22:43]
    assert len(extra) == 21
    assert extra[1] == 0xFF
    assert extra[5] == 0x3F
    assert extra == bytes.fromhex("00fffc e1cc3f080301000000000000000000000000")


def test_build_mac_board_members_frame_dynamic_form_layout():
    bitmap = bytearray(20)
    bitmap[0] = 0x31  # bits 0/4/5: pre_close/close/vol
    frame = build_command_frame(
        TYPE_MAC_BOARD_MEMBERS,
        {
            "board_symbol": "880761",
            "field_bitmap": bitmap,
            "filter": 0x24,
            "page_size": 10,
        },
        0,
    )

    body = frame.to_bytes()[12:]
    assert len(body) == 43
    assert body[0:4] == _u32(20761)
    assert body[13:15] == _u16(14)  # SortType
    assert body[15:19] == _u32(0)  # Start
    assert body[19:21] == _u16(10)  # PageSize 以 u16 发送
    assert body[21] == 1  # SortOrder u8
    assert body[22] == 0  # Zero u8
    sent_bitmap = body[23:43]
    assert sent_bitmap[0] == 0x31  # 用户位保留
    assert sent_bitmap[17] == 0x24  # filter 写入发送副本
    assert sent_bitmap[19] == 0x01  # bit19 置位
    assert bitmap[17] == 0x00  # 请求入参未被改写
    assert bitmap[19] == 0x00


def test_parse_mac_board_members_payload_plain_form_golden():
    # gotdx TestMACBoardMembersBuildRequestAndParseResponse。
    buf = bytearray(b"\x00" * 16)
    buf += b"BK01"
    buf += _u32(123)
    buf += _u16(1)
    buf += _u16(1)  # market
    buf += b"600000"
    buf += b"\x00" * 16
    buf += b"BANK".ljust(16, b"\x00")
    buf += b"\x00" * 28

    page = parse_command_response(
        TYPE_MAC_BOARD_MEMBERS,
        _response(bytes(buf), TYPE_MAC_BOARD_MEMBERS),
        {"board_symbol": "880761"},
    )

    assert page.name == "BK01"
    assert page.total == 123
    assert page.count == 1
    assert len(page.stocks) == 1
    assert page.stocks[0].market == 1
    assert page.stocks[0].symbol == "600000"
    assert page.stocks[0].name == "BANK"


def test_parse_mac_board_members_payload_quotes_form_golden():
    # gotdx TestMACBoardMembersQuotesBuildRequestAndParseResponse：52 字段逐槽。
    buf = bytearray(b"\x00" * 16)
    buf += b"BKQ1"
    buf += _u32(88)
    buf += _u16(1)
    buf += _u16(1)  # market
    buf += b"600000"
    buf += b"\x00" * 16
    buf += b"BANK".ljust(24, b"\x00")
    buf += b"\x00" * 20
    metrics = bytearray()
    metrics += _f32(1)  # 0 pre_close
    metrics += _f32(2)  # 1 open
    metrics += _f32(3)  # 2 high
    metrics += _f32(4)  # 3 low
    metrics += _f32(5)  # 4 close
    metrics += _u32(600)  # 5 vol
    metrics += _f32(7)  # 6 vol_ratio
    metrics += _f32(8)  # 7 amount
    metrics += _f32(9)  # 8 total_shares
    metrics += _f32(10)  # 9 float_shares
    metrics += _f32(11)  # 10 eps
    metrics += _f32(12)  # 11 net_assets
    metrics += _f32(13)  # 12 action_price
    metrics += _f32(14)  # 13 market_cap_ab
    metrics += _f32(15)  # 14 pe_dynamic
    metrics += _u32(1600)  # 15 lot_size_info
    metrics += _f32(17)  # 16 unknown23
    metrics += _f32(18)  # 17 dividend_yield
    metrics += _u32(321)  # 18 last_volume
    metrics += _f32(20)  # 19 turnover
    metrics += _u32(21)  # 20 some_bitmap
    metrics += _u32(22)  # 21 decimal_point
    metrics += _f32(23)  # 22 buy_price_limit
    metrics += _f32(24)  # 23 sell_price_limit
    metrics += _u32(25)  # 24 unknown34
    metrics += _u32(26)  # 25 lot_size
    metrics += _f32(27)  # 26 pre_ipov
    metrics += _f32(28)  # 27 speed_pct
    metrics += _u32(29)  # 28 kcb_flag
    metrics += _f32(30)  # 29 pe_ttm
    metrics += _f32(31)  # 30 pe_static
    metrics += _f32(32)  # 31 unknown_close_price
    buf += metrics

    page = parse_command_response(
        TYPE_MAC_BOARD_MEMBERS,
        _response(bytes(buf), TYPE_MAC_BOARD_MEMBERS),
        {"board_symbol": "880761", "include_quotes": True},
    )

    assert page.name == "BKQ1"
    assert page.total == 88
    assert page.count == 1
    item = page.stocks[0]
    assert item.symbol == "600000"
    assert item.name == "BANK"
    assert item.market == 1
    assert item.pre_close == pytest.approx(1)
    assert item.open == pytest.approx(2)
    assert item.high == pytest.approx(3)
    assert item.low == pytest.approx(4)
    assert item.close == pytest.approx(5)
    assert item.unknown6 == pytest.approx(600)
    assert item.vol == 600
    assert item.volume_ratio == pytest.approx(7)
    assert item.amount == pytest.approx(8)
    assert item.total_shares == pytest.approx(9)
    assert item.float_shares == pytest.approx(10)
    assert item.eps == pytest.approx(11)
    assert item.roe == pytest.approx(12)  # = net_assets
    assert item.net_assets == pytest.approx(12)
    assert item.action_price == pytest.approx(13)
    assert item.unknown13 == pytest.approx(13)  # = action_price
    assert item.unknown_action_price == pytest.approx(13)  # = action_price
    assert item.market_cap == pytest.approx(14)  # = total_market_cap_ab
    assert item.total_market_cap_ab == pytest.approx(14)
    assert item.pe_dynamic == pytest.approx(15)
    assert item.zero16 == pytest.approx(1600)  # = float(lot_size_info)
    assert item.lot_size_info == 1600
    assert item.unknown23 == pytest.approx(17)
    assert item.zero17 == pytest.approx(17)  # = unknown23
    assert item.dividend_yield == pytest.approx(18)
    assert item.rise_speed == pytest.approx(28)  # = speed_pct
    assert item.current_vol == 321  # uint16(last_volume)
    assert item.last_volume == 321
    assert item.turnover == pytest.approx(20)
    assert item.turnover_rate == pytest.approx(20)  # = turnover
    assert item.unknown21 == pytest.approx(21)  # = float(some_bitmap)
    assert item.some_bitmap == 21
    assert item.unknown22 == pytest.approx(22)  # = float(decimal_point)
    assert item.decimal_point == 22
    assert item.limit_up == pytest.approx(23)  # = buy_price_limit
    assert item.buy_price_limit == pytest.approx(23)
    assert item.limit_down == pytest.approx(24)  # = sell_price_limit
    assert item.sell_price_limit == pytest.approx(24)
    assert item.zero25 == pytest.approx(25)  # = float(unknown34)
    assert item.unknown34 == 25
    assert item.unknown26 == pytest.approx(26)  # = float(lot_size)
    assert item.lot_size == 26
    assert item.lot_size_board_symbol == "880226"  # 880200 + 26
    assert item.unknown27 == pytest.approx(27)  # = pre_ipov
    assert item.pre_ipov == pytest.approx(27)
    assert item.rise_speed2 == pytest.approx(28)  # = speed_pct
    assert item.speed_pct == pytest.approx(28)
    assert item.zero29 == pytest.approx(29)  # = float(kcb_flag)
    assert item.flag_kcb == 29
    assert item.kcb_flag == 29
    assert item.pe_static == pytest.approx(31)
    assert item.pe_ttm == pytest.approx(30)
    assert item.unknown31 == pytest.approx(32)  # = unknown_close_price
    assert item.unknown_close_price == pytest.approx(32)


def test_parse_mac_board_members_payload_dynamic_form_golden():
    # gotdx TestMACBoardMembersQuotesDynamicBuildRequestAndParseResponse。
    bitmap = bytearray(20)
    bitmap[0] = 0x31  # bits 0/4/5: pre_close/close/vol
    buf = bytearray(bitmap)
    buf += _u32(88)
    buf += _u16(1)
    buf += _u16(1)  # market
    buf += b"600000".ljust(22, b"\x00")
    buf += b"BANK".ljust(44, b"\x00")
    buf += _f32(10.1)  # pre_close
    buf += _f32(10.5)  # close
    buf += _u32(1234)  # vol

    page = parse_command_response(
        TYPE_MAC_BOARD_MEMBERS,
        _response(bytes(buf), TYPE_MAC_BOARD_MEMBERS),
        {"board_symbol": "880761", "field_bitmap": bitmap},
    )

    assert page.total == 88
    assert page.count == 1
    assert [field.name for field in page.active_fields] == ["pre_close", "close", "vol"]
    item = page.stocks[0]
    assert item.symbol == "600000"
    assert item.name == "BANK"
    assert item.market == 1
    assert item.values["pre_close"] == pytest.approx(10.1)
    assert item.values["close"] == pytest.approx(10.5)
    assert item.values["vol"] == 1234


def test_parse_mac_board_members_payload_dynamic_signed_and_alias():
    # gotdx TestMACBoardMembersQuotesDynamicSupportsSignedAndAliasFields。
    bitmap = bytearray(20)
    for bit in (0x24, 0x58, 0x8D, 0x8E):
        bitmap[bit // 8] |= 1 << (bit % 8)
    buf = bytearray(bitmap)
    buf += _u32(1)
    buf += _u16(1)
    buf += _u16(1)  # market
    buf += b"000001".ljust(22, b"\x00")
    buf += b"PINGAN".ljust(44, b"\x00")
    buf += _f32(12.3)  # pre_iopv
    buf += struct.pack("<i", -7)  # annual_limit_up_days
    buf += struct.pack("<i", 3)  # change_up_type
    buf += _f32(88.5)  # safety_score

    page = parse_command_response(
        TYPE_MAC_BOARD_MEMBERS,
        _response(bytes(buf), TYPE_MAC_BOARD_MEMBERS),
        {"board_symbol": "880761", "field_bitmap": bitmap},
    )

    assert page.active_fields[0].name == "pre_iopv"
    assert "pre_ipov" in page.active_fields[0].aliases
    item = page.stocks[0]
    assert item.values["pre_iopv"] == pytest.approx(12.3)
    assert item.values["pre_ipov"] == pytest.approx(12.3)  # alias
    assert item.values["float_shares"] == pytest.approx(12.3)  # alias
    assert item.values["annual_limit_up_days"] == -7  # int32 负值
    assert item.values["change_up_type"] == 3
    assert item.values["safety_score"] == pytest.approx(88.5)


def test_mac_dynamic_field_map_aligns_latest_tdx():
    # gotdx TestMACDynamicFieldMapAlignsLatestTDX：12 个指定位全表校验。
    from axdata_source_tdx._tdx_wire.protocol.commands.mac_common import (
        active_mac_dynamic_fields,
    )

    bits = [0x16, 0x37, 0x3E, 0x48, 0x6C, 0x73, 0x7B, 0x85, 0x8C, 0x8D, 0x8F, 0x90]
    bitmap = bytearray(20)
    for bit in bits:
        bitmap[bit // 8] |= 1 << (bit % 8)

    want = {
        0x16: ("board_strength", "int32", "unknown_22"),
        0x37: ("index_metric", "float32", "unknown_55"),
        0x3E: ("stock_class_code", "uint32", "unknown_62"),
        0x48: ("bid2_price", "float32", "low_copy"),
        0x6C: ("main_net_ratio", "float32", None),
        0x73: ("ddx", "float32", None),
        0x7B: ("prev_amount", "float32", None),
        0x85: ("ask5_price", "float32", "avg_price_copy"),
        0x8C: ("bid_ask_diff", "int32", None),
        0x8D: ("change_up_type", "int32", None),
        0x8F: ("highlight_count", "float32", "stock_rating"),
        0x90: ("change_at_1000", "float32", None),
    }

    fields = active_mac_dynamic_fields(bytes(bitmap))
    assert len(fields) == len(bits)
    for field in fields:
        name, format_name, alias = want[field.bit]
        assert field.name == name
        assert field.format == format_name
        if alias is not None:
            assert alias in field.aliases


def test_build_mac_board_members_frame_rejects_invalid_board_symbol():
    with pytest.raises(Exception, match="invalid board_symbol"):
        build_command_frame(TYPE_MAC_BOARD_MEMBERS, {"board_symbol": "not-a-symbol"}, 0)


def test_parse_mac_board_members_payload_rejects_truncated_row():
    buf = b"\x00" * 16 + b"BK01" + _u32(123) + _u16(1) + b"\x00" * 20
    with pytest.raises(Exception, match="truncated mac board member item"):
        parse_command_response(
            TYPE_MAC_BOARD_MEMBERS,
            _response(bytes(buf), TYPE_MAC_BOARD_MEMBERS),
            {"board_symbol": "880761"},
        )


# ------------------------------------------------------------- symbol quotes


def test_build_mac_symbol_quotes_frame_layout():
    # gotdx TestMACSymbolQuotesBuildRequestAndParseResponse。
    bitmap = bytearray(20)
    for bit in (0x00, 0x04, 0x05, 0x4A):
        bitmap[bit // 8] |= 1 << (bit % 8)

    frame = build_command_frame(
        TYPE_MAC_SYMBOL_QUOTES,
        {"securities": ["000001.SZ", "600000.SH"], "field_bitmap": bitmap},
        0,
    )

    assert frame.to_bytes()[0] == 0x01
    assert frame.to_bytes()[10:12] == _u16(0x122B)
    body = frame.to_bytes()[12:]
    assert body[0:20] == bytes(bitmap)
    assert body[20:22] == _u16(2)
    assert body[22:24] == _u16(0)  # 第一标的市场 sz
    assert body[24:46] == b"000001".ljust(22, b"\x00")
    assert body[46:48] == _u16(1)  # 第二标的市场 sh
    assert body[48:70] == b"600000".ljust(22, b"\x00")
    assert len(body) == 70


def test_build_mac_symbol_quotes_frame_default_bitmap():
    from axdata_source_tdx._tdx_wire.protocol.commands.mac_common import (
        DEFAULT_MAC_FIELD_BITMAP,
    )

    frame = build_command_frame(TYPE_MAC_SYMBOL_QUOTES, {"securities": ["000001.SZ"]}, 0)

    body = frame.to_bytes()[12:]
    assert body[0:20] == DEFAULT_MAC_FIELD_BITMAP


def test_parse_mac_symbol_quotes_payload_golden():
    bitmap = bytearray(20)
    for bit in (0x00, 0x04, 0x05, 0x4A):
        bitmap[bit // 8] |= 1 << (bit % 8)
    buf = bytearray(bitmap)
    buf += _u32(2)
    buf += _u16(2)
    for market, symbol, name, pre_close, close, vol, ah_code in (
        (0, "000001", "PingAn Bank", 10.1, 10.5, 123456, 700),
        (1, "600000", "PuFa Bank", 11.1, 11.8, 654321, 6881),
    ):
        buf += _u16(market)
        buf += symbol.encode().ljust(22, b"\x00")
        buf += name.encode().ljust(44, b"\x00")
        buf += _f32(pre_close)
        buf += _f32(close)
        buf += _u32(vol)
        buf += _u32(ah_code)

    page = parse_command_response(
        TYPE_MAC_SYMBOL_QUOTES,
        _response(bytes(buf), TYPE_MAC_SYMBOL_QUOTES),
        {"securities": ["000001.SZ", "600000.SH"], "field_bitmap": bitmap},
    )

    assert page.total == 2
    assert page.count == 2
    assert [field.name for field in page.active_fields] == [
        "pre_close",
        "close",
        "vol",
        "ah_code",
    ]
    assert page.active_fields[3].name == "ah_code"
    first, second = page.stocks
    assert first.symbol == "000001"
    assert first.name == "PingAn Bank"
    assert first.values["pre_close"] == pytest.approx(10.1)
    assert first.values["vol"] == 123456
    assert second.symbol == "600000"
    assert second.values["close"] == pytest.approx(11.8)
    assert second.values["ah_code"] == 6881


def test_parse_mac_symbol_quotes_payload_rejects_short():
    with pytest.raises(Exception, match="invalid mac symbol quotes payload length"):
        parse_command_response(
            TYPE_MAC_SYMBOL_QUOTES, _response(b"\x00" * 10, TYPE_MAC_SYMBOL_QUOTES), {}
        )


# ----------------------------------------------------------- market monitor


def test_build_mac_market_monitor_frame_layout():
    # gotdx TestMACMarketMonitorBuildRequestAndParseResponse。
    frame = build_command_frame(TYPE_MAC_MARKET_MONITOR, {"market": "sh", "start": 5}, 0)

    assert frame.to_bytes()[0] == 0x01
    assert frame.to_bytes()[10:12] == _u16(0x1237)
    body = frame.to_bytes()[12:]
    assert len(body) == 22
    assert body[0:2] == _u16(1)  # Market sh
    assert body[2:4] == _u16(5)  # Start
    assert body[4:6] == _u16(0)  # Reserved1
    assert body[6:8] == _u16(600)  # Count 默认 600
    assert body[8:10] == _u16(0)  # Reserved2
    assert body[10:12] == _u16(1)  # Mode 默认 1
    limits = [int.from_bytes(body[12 + i * 2 : 14 + i * 2], "little") for i in range(5)]
    assert limits == [200, 30, 40, 50, 200]


def test_build_mac_market_monitor_frame_accepts_market_id():
    frame = build_command_frame(TYPE_MAC_MARKET_MONITOR, {"market": 0, "count": 100}, 0)

    body = frame.to_bytes()[12:]
    assert body[0:2] == _u16(0)
    assert body[6:8] == _u16(100)


def test_parse_mac_market_monitor_payload_golden():
    # gotdx TestMACMarketMonitorBuildRequestAndParseResponse。
    item = bytearray(32)
    item[0:2] = _u16(1)  # market
    item[2:8] = b"600000"
    item[9] = 0x0B  # unusual_type
    item[11:13] = _u16(321)  # index
    item[15] = 1  # v1
    item[16:20] = _f32(2.5)  # v2
    item[20:24] = _f32(0.032)  # v3
    item[24:28] = _f32(7.7)  # v4
    item[29] = 14  # hour
    item[30:32] = _u16(3015)  # mmss
    buf = _u16(1) + bytes(item) + b"PingAn,"

    page = parse_command_response(
        TYPE_MAC_MARKET_MONITOR,
        _response(buf, TYPE_MAC_MARKET_MONITOR),
        {"market": "sh", "start": 5},
    )

    assert page.count == 1
    got = page.items[0]
    assert got.index == 321
    assert got.market == 1
    assert got.code == "600000"
    assert got.name == "PingAn"
    assert got.time == "14:30:15"
    assert got.desc == "区间放量涨"
    assert got.value == "2.5倍3.20%"
    assert got.unusual_type == 0x0B
    assert got.v1 == 1
    assert got.v2 == pytest.approx(2.5)
    assert got.v3 == pytest.approx(0.032)
    assert got.v4 == pytest.approx(7.7)


def test_parse_mac_market_monitor_payload_keeps_raw_on_request():
    item = bytearray(32)
    item[2:8] = b"000001"
    buf = _u16(1) + bytes(item) + b"PingAn,"
    page = parse_command_response(
        TYPE_MAC_MARKET_MONITOR,
        _response(buf, TYPE_MAC_MARKET_MONITOR),
        {"market": "sz", "include_raw": True},
    )

    assert page.raw_payload == buf


def test_parse_mac_market_monitor_payload_rejects_short():
    with pytest.raises(Exception, match="invalid mac market monitor payload length"):
        parse_command_response(
            TYPE_MAC_MARKET_MONITOR,
            _response(b"\x00", TYPE_MAC_MARKET_MONITOR),
            {"market": "sz"},
        )


def test_parse_mac_market_monitor_payload_rejects_truncated_row():
    buf = _u16(2) + b"\x00" * 10
    with pytest.raises(Exception, match="truncated mac market monitor item"):
        parse_command_response(
            TYPE_MAC_MARKET_MONITOR,
            _response(buf, TYPE_MAC_MARKET_MONITOR),
            {"market": "sz"},
        )
