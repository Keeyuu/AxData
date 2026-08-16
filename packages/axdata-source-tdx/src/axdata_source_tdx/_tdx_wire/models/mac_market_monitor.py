"""MAC market-monitor (0x1237) models for the private TDX wire client.

Field names follow gotdx ``proto/mac_market_monitor.go``
(``MACMarketMonitorItem``) in snake_case; ``desc``/``value`` are the formatted
display strings produced by the shared unusual ``unpackUnusualByType`` port.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MacMarketMonitorItem:
    index: int
    market: int
    code: str
    name: str
    time: str
    desc: str
    value: str
    unusual_type: int
    v1: int
    v2: float
    v3: float
    v4: float


@dataclass(frozen=True, slots=True)
class MacMarketMonitorPage:
    count: int
    items: tuple[MacMarketMonitorItem, ...] = ()
    raw_payload: bytes = b""
