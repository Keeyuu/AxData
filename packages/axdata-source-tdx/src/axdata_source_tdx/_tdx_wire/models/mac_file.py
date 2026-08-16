"""MAC file models for the private TDX wire client (0x1215 / 0x1217)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MacFileListMeta:
    """MAC file metadata (gotdx proto/mac_file.go MACFileListReply)."""

    offset: int
    size: int
    flag: int
    hash: str
    raw_payload: bytes = b""


@dataclass(frozen=True, slots=True)
class MacFileDownloadChunk:
    """One MAC file download chunk (gotdx proto/mac_file.go MACFileDownloadReply)."""

    index: int
    size: int
    data: bytes
    raw_payload: bytes = b""
