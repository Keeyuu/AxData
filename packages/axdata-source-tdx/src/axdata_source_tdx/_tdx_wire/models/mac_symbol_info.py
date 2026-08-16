"""MAC symbol-info models for the private TDX wire client (0x122A)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MacSymbolInfo:
    """MAC symbol summary (gotdx proto/mac_symbol_info.go reply).

    Field names keep the gotdx reply vocabulary verbatim; ``unknown_a``/
    ``unknown_b``/``unknown_c`` are the vendor's unmapped fields.
    """

    market: int
    code: str
    name: str
    date_time: datetime
    activity: int
    pre_close: float
    open: float
    high: float
    low: float
    close: float
    momentum: float
    vol: int
    amount: float
    inside_volume: int
    outside_volume: int
    decimal: int
    unknown_a: int
    unknown_b: float
    unknown_c: int
    vr: float
    turnover: float
    avg: float
    raw_payload: bytes = b""
