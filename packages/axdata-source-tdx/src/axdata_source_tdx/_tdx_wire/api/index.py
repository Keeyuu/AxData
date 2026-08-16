"""Index snapshot and momentum API."""

from __future__ import annotations

from .base import ApiBase


class IndexApi(ApiBase):
    def info(self, code: str, *, include_raw: bool = False):
        return self._execute("index_info", code=code, include_raw=include_raw)

    def momentum(self, code: str, *, include_raw: bool = False):
        return self._execute("index_momentum", code=code, include_raw=include_raw)
