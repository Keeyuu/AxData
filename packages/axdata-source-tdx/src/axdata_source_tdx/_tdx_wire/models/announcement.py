"""Announcement response models for the TDX 7709 wire client.

Field names follow gotdx ``proto/server.go`` (``AnnouncementReply`` /
``ExchangeAnnouncementReply``) in snake_case.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class AnnouncementNotice:
    """服务商公告（gotdx ``Announcement``，0x000A）。"""

    has_content: bool
    expire_date_raw: int
    expire_date: date | None
    title: str
    author: str
    content: str
    raw_payload: bytes = b""


@dataclass(frozen=True, slots=True)
class ExchangeAnnouncementInfo:
    """交易所公告（gotdx ``ExchangeAnnouncement``，0x0002）。"""

    version: int
    content: str
    raw_payload: bytes = b""
