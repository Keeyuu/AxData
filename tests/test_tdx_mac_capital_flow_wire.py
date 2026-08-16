from __future__ import annotations

from pathlib import Path

import pytest
from axdata_source_tdx._tdx_wire.protocol.commands import (
    build_command_frame,
    parse_command_response,
)
from axdata_source_tdx._tdx_wire.protocol.constants import (
    TYPE_AUCTION_PROCESS,
    TYPE_MAC_CAPITAL_FLOW,
)
from axdata_source_tdx._tdx_wire.protocol.frame import ResponseFrame

# Live capture 2026-08-16, three MAC hosts byte-identical (plan 19 §5 P1 capture).
# 59 bytes = 12-byte <BIBHHH header (head=0x02, seqID, 0x01, len, len, 0x1218)
# + market u16 + symbol[8] + reserved[16] + query[21] "Stock_ZJLX".
GOLDEN_REQUEST_SZ000001 = (
    "020000000001310031001812"
    "000030303030303100000000000000000000000000000000000053746f636b5f5a4a4c580000000000000000000000"
)
GOLDEN_REQUEST_SH600000 = (
    "020000000001310031001812"
    "010036303030303000000000000000000000000000000000000053746f636b5f5a4a4c580000000000000000000000"
)
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mac" / "capital_flow_000001_20260816.bin"


def _masked(frame_bytes: bytes) -> bytes:
    """Zero out the seqID field (bytes 1..5) - it is request-scoped, not stable."""
    return frame_bytes[:1] + b"\x00" * 4 + frame_bytes[5:]


def _fixture_body() -> bytes:
    raw = FIXTURE.read_bytes()
    assert raw[:4] == b"\xb1\xcb\x74\x00"
    return raw[16:]


def _response(body: bytes, msg_type: int = TYPE_MAC_CAPITAL_FLOW) -> ResponseFrame:
    return ResponseFrame(
        control=0,
        msg_id=1,
        msg_type=msg_type,
        zip_length=len(body),
        length=len(body),
        data=body,
        raw=b"",
    )


def test_build_mac_capital_flow_frame_matches_live_capture():
    frame = build_command_frame(TYPE_MAC_CAPITAL_FLOW, {"code": "000001.SZ"}, 0)

    assert frame.msg_type == TYPE_MAC_CAPITAL_FLOW
    assert frame.to_bytes().hex() == GOLDEN_REQUEST_SZ000001


def test_build_mac_capital_flow_frame_market_shanghai():
    frame = build_command_frame(TYPE_MAC_CAPITAL_FLOW, {"code": "600000.SH"}, 0)

    assert frame.to_bytes().hex() == GOLDEN_REQUEST_SH600000


def test_build_mac_capital_flow_frame_masks_seq_id_only():
    frame = build_command_frame(TYPE_MAC_CAPITAL_FLOW, {"code": "sz000001"}, 13)

    golden_masked = _masked(bytes.fromhex(GOLDEN_REQUEST_SZ000001))
    assert _masked(frame.to_bytes()) == golden_masked


def test_mac_frame_uses_head_02_while_main_station_stays_0c():
    mac_frame = build_command_frame(TYPE_MAC_CAPITAL_FLOW, {"code": "000001.SZ"}, 0)
    main_frame = build_command_frame(TYPE_AUCTION_PROCESS, {"code": "000988.SZ"}, 0)

    assert mac_frame.to_bytes()[0] == 0x02
    assert main_frame.to_bytes()[0] == 0x0C


def test_parse_mac_capital_flow_payload_decodes_live_fixture():
    snapshot = parse_command_response(
        TYPE_MAC_CAPITAL_FLOW,
        _response(_fixture_body()),
        {"code": "sz000001"},
    )

    assert snapshot.full_code == "sz000001"
    assert snapshot.market == 0
    assert snapshot.query_info == "Stock_ZJLX"
    assert snapshot.today_main_in == 320706176.0
    assert snapshot.today_main_out == 373999296.0
    assert snapshot.today_main_net == pytest.approx(-53293120.0)
    # Not strictly -today_main_net: the server-side series are rounded
    # independently (captured live delta is 64 CNY).
    assert snapshot.today_retail_in == 608355072.0
    assert snapshot.today_retail_out == 555062016.0
    assert snapshot.today_retail_net == pytest.approx(53293056.0)
    assert snapshot.five_day_main_buy == 1986570752.0
    assert snapshot.five_day_main_sell == 2257087744.0
    assert snapshot.five_day_super_net == 31367040.0
    assert snapshot.five_day_large_net == -91887392.0
    assert snapshot.five_day_medium_net == 97695472.0
    assert snapshot.five_day_small_net == -37175104.0
    assert snapshot.five_day_main_net == pytest.approx(-270516992.0)
    assert snapshot.raw_payload == b""


def test_parse_mac_capital_flow_keeps_raw_payload_on_request():
    snapshot = parse_command_response(
        TYPE_MAC_CAPITAL_FLOW,
        _response(_fixture_body()),
        {"code": "sz000001", "include_raw": True},
    )

    assert snapshot.raw_payload == _fixture_body()


def test_parse_mac_capital_flow_rejects_short_payload():
    # Match by type name + message, not class identity: another test installs
    # the package into a temp dir and pollutes sys.path, which re-imports this
    # module from the copy and breaks isinstance-style assertions.
    with pytest.raises(Exception, match="invalid mac capital flow payload length"):
        parse_command_response(
            TYPE_MAC_CAPITAL_FLOW,
            _response(b"\x00\x00Stock_ZJLX"),
            {"code": "sz000001"},
        )


def test_parse_mac_capital_flow_rejects_incomplete_rows():
    body = _fixture_body()
    import json as _json

    trimmed = body[:27] + _json.dumps([[1.0, 2.0]]).encode()
    with pytest.raises(Exception, match="expects two json rows"):
        parse_command_response(TYPE_MAC_CAPITAL_FLOW, _response(trimmed), {"code": "sz000001"})


def test_parse_mac_capital_flow_rejects_non_numeric_values():
    body = _fixture_body()
    import json as _json

    tampered = body[:27] + _json.dumps([["x", "y", "z", "w"], [1, 2, 3, 4, 5, 6]]).encode()
    with pytest.raises(Exception, match="non-numeric"):
        parse_command_response(TYPE_MAC_CAPITAL_FLOW, _response(tampered), {"code": "sz000001"})
