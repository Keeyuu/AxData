"""Connection/session API."""

from __future__ import annotations

from .base import ApiBase


class SessionApi(ApiBase):
    def ping(self) -> str:
        return self._transport.request("ping")

    def handshake(self):
        return self._execute("handshake")

    def heartbeat(self):
        return self._execute("heartbeat")

    def server_info(self):
        return self._execute("server_info")

    def announcement(self):
        """服务商公告（gotdx ``GetAnnouncement``，0x000A）。"""
        return self._execute("announcement")

    def exchange_announcement(self):
        """交易所公告（gotdx ``GetExchangeAnnouncement``，0x0002）。"""
        return self._execute("exchange_announcement")
