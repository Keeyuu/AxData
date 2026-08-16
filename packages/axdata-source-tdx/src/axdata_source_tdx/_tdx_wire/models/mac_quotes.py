"""MAC quotes (0x122D) models for the private TDX wire client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MacQuoteChartItem:
    """One intraday sampling point of a MAC quotes response."""

    time: str
    price: float
    avg: float
    vol: int
    momentum: float


@dataclass(frozen=True, slots=True)
class MacQuotesSnapshot:
    """One stock's MAC quote snapshot plus intraday sampling (gotdx MACQuotesReply)."""

    full_code: str
    market: int
    code: str
    date: int
    unknown: int
    price: float
    count: int
    chart: tuple[MacQuoteChartItem, ...]
    name: str
    decimal: int
    category: int
    vol_unit: float
    datetime: datetime | None
    pre_close: float
    open: float
    high: float
    low: float
    close: float
    momentum: float
    vol: int
    amount: float
    turnover: float
    avg: float
    industry: int
    industry_code: str
    raw_payload: bytes = b""
