"""MAC server-info models for the private TDX wire client (0x120F)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MacTradingSession:
    """One trading session segment (open/close minutes since midnight)."""

    open_minutes: int
    close_minutes: int
    open: str
    close: str


@dataclass(frozen=True, slots=True)
class MacServerInfo:
    """MAC server trading-calendar info (gotdx proto/mac_server_info.go reply).

    ``sessions1``/``sessions2`` are the two session tables (each up to four
    segments); ``extra_hex`` covers any bytes beyond the fixed 87-byte layout.
    """

    count: int
    flags_hex: str
    tag: str
    today: str
    ts1: int
    sessions1: tuple[MacTradingSession, ...]
    sessions2: tuple[MacTradingSession, ...]
    flag: int
    last_trading_day: str
    ts2: int
    last_trading_day2: str
    ts3: int
    market_param1: int
    market_param2: int
    extra_hex: str
    raw_payload: bytes = b""
