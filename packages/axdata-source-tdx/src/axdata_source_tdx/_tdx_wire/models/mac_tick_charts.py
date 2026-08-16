"""MAC multi-day tick charts (0x123E) models for the private TDX wire client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MacTickChartItem:
    """One intraday tick of a multi-day chart (gotdx MACTickChartItem)."""

    time: str
    price: float
    avg: float
    vol: int
    unknown: int


@dataclass(frozen=True, slots=True)
class MacTickChartDay:
    """One trading day's tick series (gotdx MACTickChartDay).

    ``date`` is "YYYY-MM-DD" ("" when the server did not fill that day slot)
    and ``pre_close`` comes from the response's per-day pre-close array.
    """

    date: str
    pre_close: float
    ticks: tuple[MacTickChartItem, ...]


@dataclass(frozen=True, slots=True)
class MacTickChartsPage:
    """One MAC multi-day tick-charts response (gotdx MACTickChartsReply).

    ``charts`` holds exactly ``count`` day entries; days without ticks are
    padded with empty entries.
    """

    full_code: str
    market: int
    code: str
    count: int
    send_last: int
    page_size: int
    total: int
    charts: tuple[MacTickChartDay, ...]
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
