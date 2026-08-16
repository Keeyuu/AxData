"""Index snapshot and momentum models for the TDX 7709 wire client.

Field names follow gotdx ``proto/get_index_info.go`` (``GetIndexInfoReply`` /
``IndexInfoOrder``) and ``proto/get_index_momentum.go``
(``GetIndexMomentumReply``) in snake_case.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IndexInfoOrder:
    price: float
    unknown: int
    vol: int


@dataclass(frozen=True, slots=True)
class IndexInfoSnapshot:
    order_count: int
    market_id: int
    exchange: str
    code: str
    active: int
    close: float
    pre_close: float
    diff: float
    open: float
    high: float
    low: float
    server_time: str
    after_hour: int
    vol: int
    cur_vol: int
    amount: float
    open_amount: int
    up_count: int
    down_count: int
    orders: tuple[IndexInfoOrder, ...]
    raw_payload: bytes = b""

    @property
    def full_code(self) -> str:
        return f"{self.exchange}{self.code}"


@dataclass(frozen=True, slots=True)
class IndexMomentumSeries:
    market_id: int
    exchange: str
    code: str
    count: int
    values: tuple[int, ...]
    raw_payload: bytes = b""

    @property
    def full_code(self) -> str:
        return f"{self.exchange}{self.code}"
