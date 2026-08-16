"""MAC board-members (0x122C) models for the private TDX wire client.

Field names follow gotdx ``proto/mac_board_members.go``
(``MACBoardMemberItem`` / ``MACBoardMemberQuoteItem``) and
``proto/mac_board_members_dynamic.go`` (``MACBoardMemberQuoteDynamicItem``),
converted to snake_case; alias re-assignments from gotdx's
``MACBoardMembersQuotes.ParseResponse`` are preserved field-for-field (for
example ``unknown6`` = float(``vol``), ``roe`` = ``net_assets``,
``market_cap`` = ``total_market_cap_ab``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from axdata_source_tdx._tdx_wire.models.mac_symbol_quotes import MacDynamicFieldDef


@dataclass(frozen=True, slots=True)
class MacBoardMemberItem:
    name: str
    market: int
    symbol: str


@dataclass(frozen=True, slots=True)
class MacBoardMembersPage:
    name: str
    total: int
    count: int
    stocks: tuple[MacBoardMemberItem, ...] = ()
    raw_payload: bytes = b""


@dataclass(frozen=True, slots=True)
class MacBoardMemberQuoteItem:
    name: str
    market: int
    symbol: str
    pre_close: float
    open: float
    high: float
    low: float
    close: float
    unknown6: float
    vol: int
    volume_ratio: float
    amount: float
    total_shares: float
    float_shares: float
    eps: float
    roe: float
    net_assets: float
    action_price: float
    unknown13: float
    unknown_action_price: float
    market_cap: float
    total_market_cap_ab: float
    pe_dynamic: float
    zero16: float
    lot_size_info: int
    unknown23: float
    zero17: float
    dividend_yield: float
    rise_speed: float
    current_vol: int
    last_volume: int
    turnover: float
    turnover_rate: float
    unknown21: float
    some_bitmap: int
    unknown22: float
    decimal_point: int
    limit_up: float
    buy_price_limit: float
    limit_down: float
    sell_price_limit: float
    zero25: float
    unknown34: int
    unknown26: float
    lot_size: int
    lot_size_board_symbol: str
    unknown27: float
    pre_ipov: float
    rise_speed2: float
    speed_pct: float
    zero29: float
    flag_kcb: int
    kcb_flag: int
    pe_static: float
    pe_ttm: float
    unknown31: float
    unknown_close_price: float


@dataclass(frozen=True, slots=True)
class MacBoardMembersQuotesPage:
    name: str
    total: int
    count: int
    stocks: tuple[MacBoardMemberQuoteItem, ...] = ()
    raw_payload: bytes = b""


@dataclass(frozen=True, slots=True)
class MacBoardMemberQuoteDynamicItem:
    name: str
    market: int
    symbol: str
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MacBoardMembersDynamicPage:
    field_bitmap: bytes
    active_fields: tuple[MacDynamicFieldDef, ...]
    total: int
    count: int
    stocks: tuple[MacBoardMemberQuoteDynamicItem, ...] = ()
    raw_payload: bytes = b""
