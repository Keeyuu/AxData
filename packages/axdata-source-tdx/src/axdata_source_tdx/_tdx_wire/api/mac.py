"""MAC channel API."""

from __future__ import annotations

from .base import ApiBase


class MacApi(ApiBase):
    def capital_flow(self, code: str, *, include_raw: bool = False):
        return self._execute("mac_capital_flow", code=code, include_raw=include_raw)
