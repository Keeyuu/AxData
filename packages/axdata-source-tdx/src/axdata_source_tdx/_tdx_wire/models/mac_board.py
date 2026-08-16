"""MAC extended board list/count (0x1231) models for the private TDX wire client.

Field names follow gotdx ``proto/mac_board.go`` (``MACBoardListItem`` /
``MACBoardListReply``) in snake_case. ``count`` is the gotdx row-count
derivation from ``count_all`` (``count_all/2``, falling back to ``count_all``
when the halving yields zero); the count semantic reads only the 4-byte head
and leaves ``rows`` empty.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MacBoardListItem:
    market: int
    code: str
    name: str
    price: float
    rise_speed: float
    pre_close: float
    symbol_market: int
    symbol_code: str
    symbol_name: str
    symbol_price: float
    symbol_rise_speed: float
    symbol_pre_close: float


@dataclass(frozen=True, slots=True)
class MacBoardListPage:
    count_all: int
    total: int
    count: int
    rows: tuple[MacBoardListItem, ...] = ()
    raw_payload: bytes = b""
