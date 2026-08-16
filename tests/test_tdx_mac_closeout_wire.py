"""Wave2-B 收口测试：注册计数不变式、file_meta 0x02C5 codec 接线、
0x0452 feature452 parser 分流、0x1218 同码双语义路由。"""

from __future__ import annotations

import struct

from axdata_source_tdx._tdx_wire._command_codec import BUILDERS, PARSERS
from axdata_source_tdx._tdx_wire._command_codes import COMMAND_CODE_ITEMS, command_code
from axdata_source_tdx._tdx_wire._command_dispatch import (
    BUILDER_TARGET_ITEMS,
    PARSER_TARGET_ITEMS,
)
from axdata_source_tdx._tdx_wire._command_metadata import COMMAND_METADATA_ITEMS
from axdata_source_tdx._tdx_wire._command_registry import COMMANDS
from axdata_source_tdx._tdx_wire.models.resource import FileMeta
from axdata_source_tdx._tdx_wire.protocol.commands import (
    build_command_frame,
    parse_command_response,
)
from axdata_source_tdx._tdx_wire.protocol.commands.resources import (
    FileMeta as ResourcesFileMeta,
)
from axdata_source_tdx._tdx_wire.protocol.constants import (
    TYPE_FILE_META,
    TYPE_MAC_CAPITAL_FLOW,
    TYPE_MAC_SYMBOL_BELONG_BOARD,
    TYPE_PRICE_LIMITS,
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


def test_wave2_registration_counts_and_duplicate_code_collapse():
    # 29（Wave1 后）+ 15 个 MAC 命令名 + file_meta = 45 个注册名；
    # 计划 19 收口 wire 真缺口 4 命令（exchange_announcement 0x0002 /
    # announcement 0x000a / klines_0523 0x0523 / historical_trades_basic
    # 0x0fb5）→ 49 名。mac_symbol_belong_board 与 mac_capital_flow 同码
    # 0x1218，双名指向同一路由 builder/parser，码键 dict 去重后 48。
    assert len(COMMAND_CODE_ITEMS) == 49
    assert len(COMMAND_METADATA_ITEMS) == 49
    assert len(BUILDER_TARGET_ITEMS) == 49
    assert len(PARSER_TARGET_ITEMS) == 49
    assert len(COMMANDS) == 49
    assert len(BUILDERS) == 48
    assert len(PARSERS) == 48
    assert command_code("mac_symbol_belong_board") == 0x1218
    assert command_code("mac_capital_flow") == 0x1218
    assert BUILDERS[0x1218].__name__ == "build_mac_capital_flow_frame"
    assert PARSERS[0x1218].__name__ == "parse_mac_capital_flow_payload"


def test_mac_capital_flow_registered_path_unchanged_after_router():
    # 0x1218 路由合入后，既有注册路径（默认 query=Stock_ZJLX）字节不变：
    # head=0x02、47 字节请求体、query 常量 Stock_ZJLX。
    frame = build_command_frame(TYPE_MAC_CAPITAL_FLOW, {"code": "000001.SZ"}, 0)

    raw = frame.to_bytes()
    assert raw[0] == 0x02
    assert frame.msg_type == 0x1218
    assert len(frame.data) == 47
    assert frame.data[26:47].rstrip(b"\x00") == b"Stock_ZJLX"


def test_belong_board_routes_through_shared_1218_builder():
    frame = build_command_frame(
        TYPE_MAC_SYMBOL_BELONG_BOARD, {"code": "600000.SH", "query": "Stock_GLHQ"}, 0
    )

    raw = frame.to_bytes()
    assert raw[0] == 0x01  # gotdx buildExRequest head，区别于 capital flow 的 0x02
    assert frame.msg_type == 0x1218
    assert len(frame.data) == 47
    assert frame.data[26:47].rstrip(b"\x00") == b"Stock_GLHQ"


def test_file_meta_builds_and_parses_through_codec_dispatch():
    frame = build_command_frame(TYPE_FILE_META, {"path": "block_gn.dat"}, 7)

    assert frame.msg_type == TYPE_FILE_META == 0x02C5
    assert frame.msg_id == 7
    assert frame.data == b"block_gn.dat".ljust(40, b"\x00")

    body = (70304).to_bytes(4, "little") + b"\x0f" + bytes(range(32)) + b"\x07"
    meta = parse_command_response(TYPE_FILE_META, _response(body, TYPE_FILE_META))

    assert isinstance(meta, FileMeta)
    assert meta.size == 70304
    assert meta.unknown1 == 0x0F
    assert meta.hash_value == bytes(range(32))
    assert meta.unknown2 == 0x07


def test_file_meta_model_migrated_and_reexported():
    # FileMeta dataclass 迁 models/resource.py；commands.resources 保留再导出。
    assert ResourcesFileMeta is FileMeta


def test_price_limits_parser_routes_feature452_by_request_keys():
    # 0x0452 同码双语义：请求带 count/one（builder 的 feature452 判别键）时，
    # codec 分发落到源口径 SecurityFeature452 解析。
    row = bytes([0x00]) + (1).to_bytes(4, "little") + struct.pack("<ff", 11.5, 9.5)
    body = (1).to_bytes(2, "little") + row

    records = parse_command_response(
        TYPE_PRICE_LIMITS, _response(body, TYPE_PRICE_LIMITS), {"start_index": 0, "count": 1}
    )

    assert len(records) == 1
    assert records[0].__class__.__name__ == "SecurityFeature452"
    assert records[0].market == 0
    assert records[0].code == "1"  # 源口径：u32 直转字符串，不补零
    assert records[0].p1 == 11.5
    assert records[0].p2 == 9.5


def test_price_limits_parser_keeps_strict_path_without_feature_keys():
    row = bytes([0x00]) + (1).to_bytes(4, "little") + struct.pack("<ff", 11.5, 9.5)
    body = (1).to_bytes(2, "little") + row

    records = parse_command_response(
        TYPE_PRICE_LIMITS, _response(body, TYPE_PRICE_LIMITS), {"start_index": 0}
    )

    assert len(records) == 1
    assert records[0].__class__.__name__ == "PriceLimitRecord"
    assert records[0].code == "000001"  # 补零 6 位口径
