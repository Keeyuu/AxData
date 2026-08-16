"""Unusual-movement feed (0x0563) models for the TDX 7709 wire client.

Field names follow gotdx ``proto/get_unusual.go`` (``UnusualData``) in
snake_case; ``desc``/``value`` are the formatted display strings produced by
gotdx's ``unpackUnusualByType``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UnusualRecord:
    index: int
    market_id: int
    code: str
    time: str
    desc: str
    value: str
    unusual_type: int
    record_hex: str = ""


@dataclass(frozen=True, slots=True)
class UnusualPage:
    market_id: int
    exchange: str
    start: int
    request_count: int
    records: tuple[UnusualRecord, ...]
    raw_payload: bytes = b""

    @property
    def count(self) -> int:
        return len(self.records)
