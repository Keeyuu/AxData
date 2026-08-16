"""MAC transactions (0x122F) models for the private TDX wire client."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MacTransactionItem:
    """One intraday trade record (gotdx MACTransactionItem)."""

    time: str
    price: float
    vol: int
    trade_count: int
    buy_or_sell: int


@dataclass(frozen=True, slots=True)
class MacTransactionsPage:
    """One MAC transactions response page (gotdx MACTransactionsReply)."""

    full_code: str
    market: int
    code: str
    query_date: int
    count: int
    start: int
    total: int
    items: tuple[MacTransactionItem, ...]
    raw_payload: bytes = b""
