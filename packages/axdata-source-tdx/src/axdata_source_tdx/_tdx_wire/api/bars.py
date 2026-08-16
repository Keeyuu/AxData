"""K-line/bar API."""

from __future__ import annotations

from .base import ApiBase


class BarApi(ApiBase):
    def get(
        self,
        code: str,
        *,
        period: str = "day",
        start: int = 0,
        count: int = 800,
        adjust: str | None = None,
        anchor_date=None,
        kind: str = "stock",
        include_raw: bool = False,
    ):
        return self._execute(
            "klines",
            code=code,
            period=period,
            start=start,
            count=count,
            adjust=adjust,
            anchor_date=anchor_date,
            kind=kind,
            include_raw=include_raw,
        )

    def get_0523(
        self,
        code: str,
        *,
        period: str = "day",
        start: int = 0,
        count: int = 800,
        adjust: str | None = None,
        include_raw: bool = False,
    ):
        """0x0523 K 线（gotdx ``GetKLine``/``NewGetSecurityBars``，绝对价格版）。"""
        return self._execute(
            "klines_0523",
            code=code,
            period=period,
            start=start,
            count=count,
            adjust=adjust,
            include_raw=include_raw,
        )
