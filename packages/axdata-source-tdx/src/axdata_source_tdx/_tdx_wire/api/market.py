"""Market-wide ranking and unusual-movement API."""

from __future__ import annotations

from axdata_source_tdx._tdx_wire._command_defaults import DEFAULT_UNUSUAL_COUNT

from .base import ApiBase


class MarketApi(ApiBase):
    def top_board(
        self,
        *,
        category: int = 0,
        mode: int = 5,
        size: int = 20,
        include_raw: bool = False,
    ):
        return self._execute(
            "top_board",
            category=category,
            mode=mode,
            size=size,
            include_raw=include_raw,
        )

    def unusual(
        self,
        market,
        *,
        start: int = 0,
        count: int = DEFAULT_UNUSUAL_COUNT,
        include_raw: bool = False,
    ):
        return self._execute(
            "unusual",
            market=market,
            start=start,
            count=count,
            include_raw=include_raw,
        )
