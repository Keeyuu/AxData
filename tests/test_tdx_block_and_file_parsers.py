from __future__ import annotations

from importlib import import_module

import pytest
from axdata_source_tdx._tdx_wire.protocol.commands.resources import (
    FILE_META_NAME_FIELD_SIZE,
    FILE_META_REPLY_SIZE,
    TYPE_FILE_META,
    build_file_meta_frame,
    parse_csv_rows,
    parse_file_meta_payload,
    parse_pipe_table_rows,
)
from axdata_source_tdx.block_files import (
    BLOCK_COUNT_OFFSET,
    BLOCK_HEADER_SIZE,
    BLOCK_NAME_FIELD_SIZE,
    BLOCK_STOCK_AREA_SIZE,
    parse_block_flat,
    parse_block_groups,
)


def _block_entry(name: str, codes: list[str], block_type: int) -> bytes:
    header = name.encode("gbk").ljust(BLOCK_NAME_FIELD_SIZE, b"\x00")
    header += len(codes).to_bytes(2, "little")
    header += block_type.to_bytes(2, "little")
    area = b"".join(code.encode("ascii").ljust(7, b"\x00") for code in codes)
    return header + area.ljust(BLOCK_STOCK_AREA_SIZE, b"\x00")


def _block_file(*blocks: bytes) -> bytes:
    return b"\x00" * BLOCK_COUNT_OFFSET + len(blocks).to_bytes(2, "little") + b"".join(blocks)


def test_parse_block_groups_decodes_names_and_codes():
    data = _block_file(
        _block_entry("钢铁", ["000001", "600019"], 0x0102),
        _block_entry("农商", ["002776"], 2),
    )

    groups = parse_block_groups(data)

    assert [(g.block_name, g.block_type, g.stock_count) for g in groups] == [
        ("钢铁", 0x0102, 2),
        ("农商", 2, 1),
    ]
    assert groups[0].codes == ("000001", "600019")
    assert groups[1].codes == ("002776",)


def test_parse_block_flat_expands_one_row_per_code():
    data = _block_file(
        _block_entry("钢铁", ["000001", "600019"], 0x0102),
        _block_entry("农商", ["002776"], 2),
    )

    flat = parse_block_flat(data)

    # code_index 每个板块内重新从 0 计数（gotdx 语义）
    assert [(f.block_name, f.block_type, f.code_index, f.code) for f in flat] == [
        ("钢铁", 0x0102, 0, "000001"),
        ("钢铁", 0x0102, 1, "600019"),
        ("农商", 2, 0, "002776"),
    ]


def test_parse_block_ignores_padding_beyond_stock_count():
    entry = _block_entry("钢铁", ["000001"], 1)
    # 成员区填充段塞入额外“成员”，stock_count=1 时必须被忽略
    junk_slot = b"9999999".ljust(7, b"\x00")
    entry = entry[: BLOCK_HEADER_SIZE + 7] + junk_slot + entry[BLOCK_HEADER_SIZE + 14 :]
    data = _block_file(entry)

    groups = parse_block_groups(data)

    assert len(groups) == 1
    assert groups[0].codes == ("000001",)
    assert groups[0].stock_count == 1


def test_parse_block_empty_total_returns_empty():
    assert parse_block_groups(_block_file()) == []
    assert parse_block_flat(_block_file()) == []


def test_parse_block_rejects_short_data():
    with pytest.raises(ValueError, match="invalid block data length"):
        parse_block_groups(b"\x00" * 385)
    with pytest.raises(ValueError, match="invalid block data length"):
        parse_block_flat(b"\x00" * 385)


def test_parse_block_rejects_truncated_header():
    data = b"\x00" * BLOCK_COUNT_OFFSET + (1).to_bytes(2, "little")

    with pytest.raises(ValueError, match="invalid block header 0"):
        parse_block_groups(data)


def test_parse_block_rejects_truncated_codes():
    header = "钢铁".encode("gbk").ljust(9, b"\x00")
    header += (5).to_bytes(2, "little") + (1).to_bytes(2, "little")
    data = b"\x00" * BLOCK_COUNT_OFFSET + (1).to_bytes(2, "little") + header + b"600000\x00"

    with pytest.raises(ValueError, match="invalid block code 0:1"):
        parse_block_groups(data)


def test_parse_block_matches_gotdx_block_test_vector():
    # gotdx block_test.go buildBlockData() 的原始字节，golden 交叉校验
    data = bytearray(BLOCK_COUNT_OFFSET + 2 + BLOCK_STOCK_AREA_SIZE)
    data[BLOCK_COUNT_OFFSET] = 1
    data[386:395] = b"TEST"
    data[395] = 2
    data[397] = 3
    data[399:406] = b"600000"
    data[406:413] = b"000001"

    items = parse_block_flat(bytes(data))
    groups = parse_block_groups(bytes(data))

    assert [(i.block_name, i.block_type, i.code_index, i.code) for i in items] == [
        ("TEST", 3, 0, "600000"),
        ("TEST", 3, 1, "000001"),
    ]
    assert [(g.block_name, g.block_type, g.stock_count, g.codes) for g in groups] == [
        ("TEST", 3, 2, ("600000", "000001"))
    ]


def test_parse_csv_rows_decodes_gbk_and_skips_blank_lines():
    content = "code,name\n000001,平安银行\n\n600019,宝钢\n".encode("gbk")

    assert parse_csv_rows(content) == [
        ["code", "name"],
        ["000001", "平安银行"],
        ["600019", "宝钢"],
    ]


def test_parse_csv_rows_keeps_quoted_commas():
    assert parse_csv_rows(b'a,b\n"c,d",e\n') == [["a", "b"], ["c,d", "e"]]


def test_parse_pipe_table_rows_strips_and_splits():
    # gotdx 语义：仅整行 TrimSpace，字段内部空格保留
    content = "  600000 |浦发银行| 1  \n\n".encode("gbk")

    assert parse_pipe_table_rows(content) == [["600000 ", "浦发银行", " 1"]]


def test_build_file_meta_frame_pads_40_byte_name():
    frame = build_file_meta_frame({"path": "block_gn.dat"}, 3)

    assert frame.msg_id == 3
    assert frame.msg_type == TYPE_FILE_META == 0x02C5
    assert len(frame.data) == FILE_META_NAME_FIELD_SIZE
    assert frame.data == b"block_gn.dat".ljust(FILE_META_NAME_FIELD_SIZE, b"\x00")


def test_build_file_meta_frame_rejects_long_or_non_ascii_path():
    protocol_error = import_module("axdata_source_tdx._tdx_wire.exceptions").ProtocolError
    with pytest.raises(protocol_error, match="40 ASCII"):
        build_file_meta_frame({"path": "z" * 41}, 1)
    with pytest.raises(protocol_error, match="ASCII"):
        build_file_meta_frame({"path": "板块.dat"}, 1)


def test_parse_file_meta_payload_decodes_gotdx_layout():
    payload = (70304).to_bytes(4, "little") + b"\x0f" + bytes(range(32)) + b"\x07"

    meta = parse_file_meta_payload(payload)

    assert len(payload) == FILE_META_REPLY_SIZE == 38
    assert meta.size == 70304
    assert meta.unknown1 == 0x0F
    assert meta.hash_value == bytes(range(32))
    assert meta.unknown2 == 0x07


def test_parse_file_meta_payload_rejects_short_payload():
    protocol_error = import_module("axdata_source_tdx._tdx_wire.exceptions").ProtocolError
    with pytest.raises(protocol_error, match="invalid file meta payload"):
        parse_file_meta_payload(b"\x00" * 37)
