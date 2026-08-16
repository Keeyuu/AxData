"""MAC symbol bars (0x122E) models for the private TDX wire client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MacSymbolBar:
    """One K-line bar (gotdx MACSymbolBar).

    ``pre_close``/``last_close`` chain from the previous bar's close (0.0 for
    the first), ``rise_price``/``rise_rate`` are gotdx GetRisePrice/GetRiseRate.
    ``turnover`` stays 0.0: gotdx applies it as client-side post-processing
    (applyMACSymbolBarTurnover) which is not ported.
    """

    datetime: datetime | None
    open: float
    high: float
    low: float
    close: float
    amount: float
    vol: float
    float_shares: float
    turnover: float
    pre_close: float
    last_close: float
    rise_price: float
    rise_rate: float


@dataclass(frozen=True, slots=True)
class MacSymbolBarsPage:
    """One MAC symbol-bars response page (gotdx MACSymbolBarsReply).

    ``count`` is the response header count minus the discarded first bar
    (the request always asks for count+1 bars; see the wire module).
    """

    full_code: str
    market: int
    code: str
    period: int
    unknown: int
    count: int
    start: int
    bars: tuple[MacSymbolBar, ...]
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
