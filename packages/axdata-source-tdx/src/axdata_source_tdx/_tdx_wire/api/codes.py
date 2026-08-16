"""Security code table API."""

from __future__ import annotations

from axdata_source_tdx._tdx_wire._request_defaults import DEFAULT_CODE_PAGE_SIZE

from .base import ApiBase


class CodeApi(ApiBase):
    def count(self, market: str):
        return self._execute("security_count", market=market)

    def list(self, market: str, *, start: int = 0, limit: int = 1600):
        return self._execute("security_list", market=market, start=start, limit=limit)

    def list_old(self, market: str, *, start: int = 0, include_raw: bool = False):
        return self._execute(
            "security_list_old",
            market=market,
            start=start,
            include_raw=include_raw,
        )

    def all(self, market: str, *, page_size: int = DEFAULT_CODE_PAGE_SIZE):
        start = 0
        items = []
        while True:
            page = self.list(market, start=start, limit=page_size)
            items.extend(page)
            if len(page) < page_size:
                return items
            start += page_size
