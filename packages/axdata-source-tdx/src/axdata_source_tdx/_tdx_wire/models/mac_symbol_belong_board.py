"""MAC symbol-belong-board models for the private TDX wire client (0x1218)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MacBelongBoardItem:
    """One belong-board row (gotdx proto/mac_symbol_belong_board.go item).

    Schema-sensitive fields: the 9-column schema fills the limit-up metrics,
    the 13-column schema fills the peer-symbol fields; ``metric1..3`` always
    mirror whichever schema was seen (gotdx semantics).
    """

    board_type: str
    market_code: int
    status_code: int
    board_code: str
    board_name: str
    price: float
    pre_close: float
    schema_columns: int
    limit_up_count: float
    limit_down_count: float
    most_similar: float
    speed_pct: float
    symbol_market: int
    symbol: str
    symbol_name: str
    symbol_close: float
    symbol_pre_close: float
    symbol_speed_pct: float
    metric1: float
    metric2: float
    metric3: float


@dataclass(frozen=True, slots=True)
class MacSymbolBelongBoardList:
    """A symbol's belong-board list (gotdx proto/mac_symbol_belong_board.go reply)."""

    market: int
    query: str
    items: tuple[MacBelongBoardItem, ...]
    raw_payload: bytes = b""
