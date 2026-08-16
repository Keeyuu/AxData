"""MAC auction (0x123D) wire tests — golden vectors from gotdx
proto/mac_protocol_test.go TestMACAuctionBuildRequestAndParseResponse."""

from __future__ import annotations

import struct

import pytest
from axdata_source_tdx._tdx_wire.protocol.commands import (
    build_command_frame,
    parse_command_response,
)
from axdata_source_tdx._tdx_wire.protocol.constants import TYPE_MAC_AUCTION
from axdata_source_tdx._tdx_wire.protocol.frame import ResponseFrame


def _response(body: bytes) -> ResponseFrame:
    return ResponseFrame(
        control=0,
        msg_id=1,
        msg_type=TYPE_MAC_AUCTION,
        zip_length=len(body),
        length=len(body),
        data=body,
        raw=b"",
    )


def _f32(value: float) -> bytes:
    return struct.pack("<f", value)


def test_build_mac_auction_frame_matches_gotdx_layout():
    frame = build_command_frame(TYPE_MAC_AUCTION, {"code": "600000.SH", "start": 3}, 0)

    raw = frame.to_bytes()
    assert raw[0] == 0x01  # gotdx buildExRequest head
    assert frame.msg_type == TYPE_MAC_AUCTION == 0x123D
    expected = (
        (1).to_bytes(2, "little")
        + b"600000".ljust(22, b"\x00")
        + (3).to_bytes(4, "little")
        + (500).to_bytes(4, "little")
        + b"\x00" * 10
    )
    assert frame.data == expected
    # <BIBHHH 头：长度字段 = 2（msg_type） + 42（请求体）
    assert raw[6:8] == (44).to_bytes(2, "little") == raw[8:10]


def test_build_mac_auction_frame_defaults_count_and_uses_request_count():
    default_frame = build_command_frame(TYPE_MAC_AUCTION, {"code": "sz000001"}, 0)
    assert default_frame.data[28:32] == (500).to_bytes(4, "little")

    explicit = build_command_frame(
        TYPE_MAC_AUCTION, {"code": "sz000001", "start": 10, "count": 120}, 0
    )
    assert explicit.data[24:28] == (10).to_bytes(4, "little")
    assert explicit.data[28:32] == (120).to_bytes(4, "little")


def test_parse_mac_auction_payload_golden_full_fields():
    body = (
        (1).to_bytes(2, "little")
        + b"600000".ljust(22, b"\x00")
        + (2).to_bytes(4, "little")
        + b"\x00" * 8  # count@24:28 与首条记录间的 8 字节空洞
        + (34215).to_bytes(4, "little")
        + _f32(10.5)
        + (100).to_bytes(4, "little")
        + (-50).to_bytes(4, "little", signed=True)
        + (55800).to_bytes(4, "little")
        + _f32(10.8)
        + (120).to_bytes(4, "little")
        + (30).to_bytes(4, "little", signed=True)
    )

    page = parse_command_response(TYPE_MAC_AUCTION, _response(body), {"code": "sh600000"})

    assert page.market == 1
    assert page.code == "600000"
    assert page.count == 2
    assert len(page.items) == 2
    first, second = page.items
    # gotdx 金标准：符号语义（上游 impl 的 abs 分支与其测试矛盾，按测试走）
    assert first.time == "09:30:15"
    assert first.price == pytest.approx(10.5)
    assert first.matched == 100
    assert first.unmatched == -50
    assert first.flag == -1
    assert second.time == "15:30:00"
    assert second.price == pytest.approx(10.8)
    assert second.matched == 120
    assert second.unmatched == 30
    assert second.flag == 1
    assert page.raw_payload == b""


def test_parse_mac_auction_keeps_raw_payload_on_request():
    body = (
        (0).to_bytes(2, "little")
        + b"000001".ljust(22, b"\x00")
        + (0).to_bytes(4, "little")
        + b"\x00" * 8
    )

    page = parse_command_response(
        TYPE_MAC_AUCTION, _response(body), {"code": "sz000001", "include_raw": True}
    )

    assert page.items == ()
    assert page.raw_payload == body


def test_parse_mac_auction_rejects_short_payload_and_truncated_item():
    with pytest.raises(Exception, match="invalid mac auction response length"):
        parse_command_response(TYPE_MAC_AUCTION, _response(b"\x00" * 35), {"code": "sz000001"})

    truncated = (
        (1).to_bytes(2, "little")
        + b"600000".ljust(22, b"\x00")
        + (1).to_bytes(4, "little")
        + b"\x00" * 8
        + (34215).to_bytes(4, "little")
        + _f32(10.5)
        + (100).to_bytes(4, "little")
    )
    with pytest.raises(Exception, match="invalid mac auction item 0"):
        parse_command_response(TYPE_MAC_AUCTION, _response(truncated), {"code": "sh600000"})
