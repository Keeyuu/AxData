"""Trade-detail models for the private TDX 7709 wire client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time


@dataclass(frozen=True, slots=True)
class TradeDetailRecord:
    trade_time: time
    trade_datetime: datetime | None
    trade_date: date | None
    index: int
    absolute_index: int
    time_minutes: int
    price: float
    price_acc_raw: int
    price_delta_raw: int
    volume: int
    order_count: int
    status_raw: int
    side: str
    tail_raw: int
    record_hex: str = ""


@dataclass(frozen=True, slots=True)
class TradeDetailSeries:
    exchange: str
    market_id: int
    code: str
    start: int
    request_count: int
    records: tuple[TradeDetailRecord, ...]
    trade_date: date | None = None
    price_base_raw_f32: float | None = None
    raw_payload: bytes = b""

    @property
    def full_code(self) -> str:
        return f"{self.exchange}{self.code}"

    @property
    def count(self) -> int:
        return len(self.records)


@dataclass(frozen=True, slots=True)
class BasicTradeRecord:
    """0x0FB5 基础历史逐笔成交单条记录（gotdx ``HistoryTransactionData``）。

    与 ``TradeDetailRecord``（0x0FC5/0x0FC6）的差异：无第 5 个 varint 字段，
    ``buyorsell_raw`` 对应 gotdx ``BuyOrSell``，``unknown_raw`` 对应 gotdx
    ``Unknown``。
    """

    trade_time: time
    trade_datetime: datetime | None
    trade_date: date | None
    index: int
    absolute_index: int
    time_minutes: int
    price: float
    price_acc_raw: int
    price_delta_raw: int
    volume: int
    buyorsell_raw: int
    side: str
    unknown_raw: int
    record_hex: str = ""


@dataclass(frozen=True, slots=True)
class BasicTradeSeries:
    exchange: str
    market_id: int
    code: str
    start: int
    request_count: int
    records: tuple[BasicTradeRecord, ...]
    trade_date: date | None = None
    skipped_head_raw: bytes = b""
    price_base_unit: float = 100.0
    raw_payload: bytes = b""

    @property
    def full_code(self) -> str:
        return f"{self.exchange}{self.code}"

    @property
    def count(self) -> int:
        return len(self.records)
