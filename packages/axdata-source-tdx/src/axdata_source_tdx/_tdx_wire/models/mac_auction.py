"""MAC auction models (gotdx proto/mac_auction.go MACAuctionItem/Reply)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MacAuctionItem:
    """单条竞价数据；unmatched 保留符号，flag 表方向（见命令模块 docstring）。"""

    time: str
    price: float
    matched: int
    unmatched: int
    flag: int


@dataclass(frozen=True, slots=True)
class MacAuctionPage:
    market: int
    code: str
    count: int
    items: tuple[MacAuctionItem, ...]
    raw_payload: bytes = b""
