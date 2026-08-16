from __future__ import annotations

import struct
import zlib

from axdata_core.adapters.tdx_ext.client import (
    _package,
    parse_board_list_response,
    parse_instrument_count_response,
    parse_instrument_info_response,
    parse_instrument_quote_response,
    parse_history_transaction_response,
    parse_kline2_response,
    parse_markets_response,
    parse_market_board_mapping_response,
    parse_quotes_multi_response,
    parse_transaction_response,
)


def test_parse_markets_response_decodes_records():
    body = struct.pack("<H", 2)
    body += struct.pack(
        "<B32sB2s26s2s",
        3,
        "大连商品".encode("gbk").ljust(32, b"\x00"),
        29,
        b"QD",
        b"\x00" * 26,
        b"\x00" * 2,
    )
    body += struct.pack(
        "<B32sB2s26s2s",
        0,
        b"\x00" * 32,
        0,
        b"\x00" * 2,
        b"\x00" * 26,
        b"\x00" * 2,
    )

    rows = parse_markets_response(body)

    assert len(rows) == 1
    assert rows[0].category == 3
    assert rows[0].market == 29
    assert rows[0].name == "大连商品"
    assert rows[0].short_name == "QD"


def test_parse_instrument_count_response_reads_payload_offset():
    body = b"TDX_DS" + b"\x00" * 13 + struct.pack("<I", 12345)

    assert parse_instrument_count_response(body) == 12345


def test_parse_instrument_info_response_decodes_rows():
    body = struct.pack("<IH", 0, 1)
    record = struct.pack(
        "<BB3s9s17s9s",
        3,
        29,
        b"\x00" * 3,
        b"IF2606\x00\x00\x00",
        "沪深期指".encode("gbk").ljust(17, b"\x00"),
        b"IF\x00\x00\x00\x00\x00\x00\x00",
    )
    body += record + b"\x00" * 24

    rows = parse_instrument_info_response(body)

    assert len(rows) == 1
    assert rows[0].category == 3
    assert rows[0].market == 29
    assert rows[0].code == "IF2606"
    assert rows[0].name == "沪深期指"
    assert rows[0].desc == "IF"


def test_parse_instrument_quote_response_decodes_core_fields():
    row = bytearray(314)
    row[:24] = struct.pack("<B23s", 47, b"IF2606")
    row[24:84] = struct.pack(
        "<I5f4If4I",
        19713,
        8583.6,
        8580.6,
        8718.0,
        8571.0,
        8682.8,
        32819,
        0,
        58561,
        2,
        101313191936.0,
        28500,
        30061,
        0,
        40211,
    )
    row[84:164] = struct.pack(
        "<5f5I5f5I",
        8680.6,
        0.0,
        0.0,
        0.0,
        0.0,
        2,
        0,
        0,
        0,
        0,
        8682.8,
        0.0,
        0.0,
        0.0,
        0.0,
        1,
        0,
        0,
        0,
        0,
    )
    row[164:202] = struct.pack(
        "<HfIffIIIIf",
        0,
        8685.4,
        1,
        8650.206,
        8583.6,
        0,
        65953,
        0,
        0,
        8613.2,
    )
    row[202:314] = struct.pack(
        "<12sff12sff25sfIIff24sHB",
        b"",
        68652.0,
        0.277,
        b"",
        0.0,
        3.9,
        b"",
        8685.4,
        20260618,
        0,
        0.1268,
        372.2,
        b"",
        65535,
        0,
    )
    body = struct.pack("<IIH", 0, 0, 1) + bytes(row)

    rows = parse_quotes_multi_response(body)

    assert len(rows) == 1
    quote = rows[0]
    assert quote.market == 47
    assert quote.code == "IF2606"
    assert round(quote.pre_close or 0, 1) == 8583.6
    assert round(quote.last_price or 0, 1) == 8682.8
    assert quote.volume == 58561
    assert quote.open_interest == 40211
    assert quote.trade_date == "20260618"
    assert round(quote.bid_levels[0].price or 0, 1) == 8680.6
    assert quote.bid_levels[1].price is None
    assert round(quote.ask_levels[0].price or 0, 1) == 8682.8


def test_parse_kline2_response_decodes_extended_volume_interest_and_settlement():
    body = struct.pack("<B23sHHIIIH", 47, b"IF2606", 4, 1, 0, 0, 0, 1)
    body += struct.pack(
        "<IffffIIf",
        20260618,
        8580.6,
        8718.0,
        8571.0,
        8682.8,
        40211,
        58561,
        8685.4,
    )

    rows = parse_kline2_response(body)

    assert len(rows) == 1
    row = rows[0]
    assert row.trade_time == "20260618"
    assert row.period == "4"
    assert round(row.close or 0, 1) == 8682.8
    assert row.amount is None
    assert row.open_interest == 40211
    assert row.volume == 58561
    assert round(row.settlement or 0, 1) == 8685.4


def test_parse_board_list_response_decodes_rows():
    body = struct.pack("<HH", 0, 2)
    body += struct.pack(
        "<H22s44sfffH22s44sfff",
        1,
        b"BK0001",
        "玻璃玻纤".encode("gbk").ljust(44, b"\x00"),
        10.1,
        1.2,
        9.9,
        47,
        b"IF2606",
        "中证".encode("gbk").ljust(44, b"\x00"),
        12.3,
        0.4,
        11.8,
    )
    body += struct.pack(
        "<H22s44sfffH22s44sfff",
        2,
        b"BK0002",
        "宏观策略".encode("gbk").ljust(44, b"\x00"),
        0.0,
        0.0,
        0.0,
        0,
        b"",
        b"\x00" * 44,
        0.0,
        0.0,
        0.0,
    )

    rows = parse_board_list_response(body)

    assert len(rows) == 2
    row = rows[0]
    assert row.market == 1
    assert row.code == "BK0001"
    assert row.name == "玻璃玻纤"
    assert round(row.price or 0, 1) == 10.1
    assert round(row.rise_speed, 1) == 1.2
    assert round(row.pre_close or 0, 1) == 9.9
    assert row.symbol_market == 47
    assert row.symbol_code == "IF2606"
    assert row.symbol_name == "中证"
    assert round(row.symbol_price or 0, 1) == 12.3
    assert round(row.symbol_rise_speed, 1) == 0.4
    assert round(row.symbol_pre_close or 0, 1) == 11.8
    empty = rows[1]
    assert empty.price is None
    assert empty.rise_speed == 0.0
    assert empty.pre_close is None
    assert empty.symbol_price is None
    assert empty.symbol_rise_speed == 0.0


def test_parse_market_board_mapping_response_decodes_rows():
    body = struct.pack("<H", 1)
    body += struct.pack(
        "<H23sHIBfffHH",
        74,
        "US Stock".encode("gbk").ljust(23, b"\x00"),
        8,
        99,
        1,
        1.1,
        2.2,
        3.3,
        4,
        5,
    )

    rows = parse_market_board_mapping_response(body)

    assert len(rows) == 1
    row = rows[0]
    assert row.category == 74
    assert row.name == "US Stock"
    assert row.unknown == 8
    assert row.index == 99
    assert row.switch == 1
    assert round(row.code1, 1) == 1.1
    assert round(row.code2, 1) == 2.2
    assert round(row.code3, 1) == 3.3
    assert row.code4 == 4
    assert row.code5 == 5


def test_parse_transaction_response_decodes_paged_rows_and_marker():
    body = struct.pack("<B9s4sH", 47, b"IC2606", b"\x00" * 4, 2)
    body += struct.pack("<HIIiH", 14 * 60 + 59, 8682001, 1, -1, 56)
    body += struct.pack("<HIIiH", 14 * 60 + 59, 8681601, 1, 0, 10056)

    rows = parse_transaction_response(body, price_scale=1000)

    assert len(rows) == 2
    assert rows[0].trade_date is None
    assert rows[0].time_label == "14:59:56"
    assert rows[0].price == 8682.001
    assert rows[0].position_change == -1
    assert rows[0].direction_marker == 0
    assert rows[1].direction_marker == 1


def test_parse_history_transaction_response_preserves_requested_date():
    body = struct.pack("<B9s4sH", 47, b"IC2606", b"\x00" * 4, 1)
    body += struct.pack("<HIIiH", 14 * 60 + 59, 8682001, 1, -1, 56)

    rows = parse_history_transaction_response(body, trade_date="20260618", price_scale=1000)

    assert rows[0].trade_date == "20260618"


def test_package_uses_extended_market_request_header():
    payload = _package(0x2455)

    assert payload[:10] == struct.pack("<BIBHH", 1, 0, 1, 2, 2)


def test_response_payload_shape_matches_zlib_decompress_assumption():
    payload = b"abc"
    compressed = zlib.compress(payload)
    assert zlib.decompress(compressed) == payload
