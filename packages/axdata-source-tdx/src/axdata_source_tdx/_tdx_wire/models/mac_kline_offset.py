"""MAC kline-offset models for the private TDX wire client (0x124A)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MacKlineOffset:
    """MAC K-line offset info (gotdx proto/mac_kline_offset.go reply)."""

    total: int
    returned: int
    raw_payload: bytes = b""
