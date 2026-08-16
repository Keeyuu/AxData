"""K-line models for the private TDX 7709 wire client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class KlineBar:
    time: datetime
    open: float
    close: float
    high: float
    low: float
    open_price_milli: int
    close_price_milli: int
    high_price_milli: int
    low_price_milli: int
    last_close_price_milli: int | None
    volume_raw: int
    amount_raw: int
    volume_wire_value: float
    volume_lots: float
    amount: float
    open_delta_raw: int
    close_delta_raw: int
    high_delta_raw: int
    low_delta_raw: int
    up_count: int | None = None
    down_count: int | None = None
    record_hex: str = ""


@dataclass(frozen=True, slots=True)
class KlineSeries:
    exchange: str
    market_id: int
    code: str
    period_raw: int
    period_param_raw: int
    period_name: str
    start: int
    request_count: int
    adjust_mode_raw: int
    adjust_mode: str
    anchor_date_raw: int
    anchor_date: date | None
    bars: tuple[KlineBar, ...]
    raw_payload: bytes = b""

    @property
    def full_code(self) -> str:
        return f"{self.exchange}{self.code}"

    @property
    def count(self) -> int:
        return len(self.bars)


@dataclass(frozen=True, slots=True)
class Kline0523Bar:
    """0x0523 K 线单条（gotdx ``SecurityBar``）。

    价格为绝对毫单位（区别 0x052D 偏移版的差分编码）；``pre_close`` 来自前一
    条（含被丢弃的响应首条）的收盘。``up_count``/``down_count`` 镜像 gotdx 结构
    字段，但其嗅探分支为死代码，恒为 None。
    """

    time: datetime
    open: float
    close: float
    high: float
    low: float
    pre_close: float
    vol: float
    amount: float
    open_raw: int
    close_raw: int
    high_raw: int
    low_raw: int
    rise_price: float
    rise_rate: float
    up_count: int | None = None
    down_count: int | None = None
    record_hex: str = ""


@dataclass(frozen=True, slots=True)
class Kline0523Series:
    exchange: str
    market_id: int
    code: str
    period_raw: int
    period_param_raw: int
    period_name: str
    start: int
    request_count: int
    wire_count: int
    adjust_mode_raw: int
    bars: tuple[Kline0523Bar, ...]
    raw_payload: bytes = b""

    @property
    def full_code(self) -> str:
        return f"{self.exchange}{self.code}"

    @property
    def count(self) -> int:
        return len(self.bars)
