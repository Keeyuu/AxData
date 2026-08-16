"""TDX file resource models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FileContentChunk:
    path: str
    offset: int
    request_size: int
    chunk_len: int
    content: bytes

    @property
    def is_last(self) -> bool:
        return self.chunk_len < self.request_size


@dataclass(frozen=True, slots=True)
class FileMeta:
    """文件元信息（gotdx proto/get_file.go GetFileMetaReply，共 38 字节）。

    布局：size u32 LE + unknown1 u8 + 32 字节哈希 + unknown2 u8。
    """

    size: int
    unknown1: int
    hash_value: bytes
    unknown2: int
