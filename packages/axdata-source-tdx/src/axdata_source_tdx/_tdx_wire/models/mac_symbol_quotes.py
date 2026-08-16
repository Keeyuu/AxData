"""MAC dynamic-field quote models for the private TDX wire client.

``MacDynamicFieldDef`` mirrors gotdx ``MACDynamicFieldDef``
(proto/mac_board_members_dynamic.go) and is shared by every bitmap-driven MAC
command (board members dynamic, symbol quotes). ``MacSymbolQuoteItem`` /
``MacSymbolQuotesPage`` mirror gotdx ``MACSymbolQuoteItem`` /
``MACSymbolQuotesReply`` (proto/mac_symbol_quotes.go).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class MacDynamicFieldDef:
    bit: int
    name: str
    format: str
    description: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MacSymbolQuoteItem:
    name: str
    market: int
    symbol: str
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MacSymbolQuotesPage:
    field_bitmap: bytes
    active_fields: tuple[MacDynamicFieldDef, ...]
    total: int
    count: int
    stocks: tuple[MacSymbolQuoteItem, ...] = ()
    raw_payload: bytes = b""
