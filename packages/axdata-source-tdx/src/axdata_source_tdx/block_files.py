"""TDX 板块归属文件（block_zs.dat / block_gn.dat 等）二进制解析。

布局逐字段照抄 gotdx（c6958ea）block.go 的 ParseBlockFlat/ParseBlockGroups：

- 384 字节保留头；
- 头部之后 2 字节板块总数（u16 LE）；
- 每个板块固定占 2813 字节：9 字节 GBK 板块名 + 2 字节成员数（u16 LE）
  + 2 字节板块类型（u16 LE）+ 2800 字节成员区（每个成员 7 字节代码，
  仅前 stock_count 个有效，成员区固定步进 2800 字节）。

公开独立函数：不接 wire 命令注册，不进采集注册面（计划 19 §4.5，P3）。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from axdata_source_tdx._tdx_wire.protocol.unit import decode_gbk_text, little_u16

BLOCK_RESERVED_HEADER_SIZE = 384
BLOCK_COUNT_OFFSET = 384
BLOCK_NAME_FIELD_SIZE = 9
BLOCK_HEADER_SIZE = 13
BLOCK_CODE_FIELD_SIZE = 7
BLOCK_STOCK_AREA_SIZE = 2800


@dataclass(frozen=True, slots=True)
class BlockFlatItem:
    """板块→成员扁平行（gotdx BlockFlatItem）。"""

    block_name: str
    block_type: int
    code_index: int
    code: str


@dataclass(frozen=True, slots=True)
class BlockGroup:
    """板块层级分组（gotdx BlockGroup）。"""

    block_name: str
    block_type: int
    stock_count: int
    codes: tuple[str, ...]


def parse_block_flat(data: bytes) -> list[BlockFlatItem]:
    """解析为扁平行：每个 (板块, 成员) 一行。"""
    return [
        BlockFlatItem(
            block_name=block_name,
            block_type=block_type,
            code_index=code_index,
            code=code,
        )
        for block_name, block_type, _stock_count, codes in _iter_blocks(data)
        for code_index, code in enumerate(codes)
    ]


def parse_block_groups(data: bytes) -> list[BlockGroup]:
    """解析为层级分组：每个板块一行，成员聚合进 codes。"""
    return [
        BlockGroup(
            block_name=block_name,
            block_type=block_type,
            stock_count=stock_count,
            codes=tuple(codes),
        )
        for block_name, block_type, stock_count, codes in _iter_blocks(data)
    ]


def _iter_blocks(data: bytes) -> Iterator[tuple[str, int, int, list[str]]]:
    if len(data) < BLOCK_COUNT_OFFSET + 2:
        raise ValueError(f"invalid block data length: {len(data)}")

    pos = BLOCK_COUNT_OFFSET
    total = little_u16(data[pos : pos + 2])
    pos += 2

    for i in range(total):
        if pos + BLOCK_HEADER_SIZE > len(data):
            raise ValueError(f"invalid block header {i}")
        block_name = decode_gbk_text(data[pos : pos + BLOCK_NAME_FIELD_SIZE])
        pos += BLOCK_NAME_FIELD_SIZE
        stock_count = little_u16(data[pos : pos + 2])
        block_type = little_u16(data[pos + 2 : pos + 4])
        pos += 4

        stock_begin = pos
        codes: list[str] = []
        for code_index in range(stock_count):
            if pos + BLOCK_CODE_FIELD_SIZE > len(data):
                raise ValueError(f"invalid block code {i}:{code_index}")
            codes.append(decode_gbk_text(data[pos : pos + BLOCK_CODE_FIELD_SIZE]))
            pos += BLOCK_CODE_FIELD_SIZE
        yield block_name, block_type, stock_count, codes
        pos = stock_begin + BLOCK_STOCK_AREA_SIZE
