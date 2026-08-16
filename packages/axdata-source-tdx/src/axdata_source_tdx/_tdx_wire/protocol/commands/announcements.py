"""Announcement command builders and parsers (0x0002 / 0x000A).

Wire layout follows gotdx ``proto/server.go``:

- ``ExchangeAnnouncement``（交易所公告，``KMSG_EXCHANGEANNOUNCE`` = 0x0002）：
  请求无 body（同心跳）；响应 ``<u8 version><GBK content>``。
- ``Announcement``（服务商公告，``KMSG_ANNOUNCEMENT`` = 0x000A）：请求为 54 个
  ``0x00`` 字节（gotdx ``BuildRequest`` 写 ``make([]byte, 54)``）；响应
  ``<u8 has_content>``，首字节非 0x01 表示无公告（gotdx 直接返回空 reply 不报
  错），为 0x01 时后续为 ``<u32 expire_date(yyyymmdd)><u16 title_len><u16
  author_len><u16 content_len><title><author><content>``，三段文本均 GBK。
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.announcement import (
        AnnouncementNotice,
        ExchangeAnnouncementInfo,
    )

TYPE_ANNOUNCEMENT = command_code("announcement")
TYPE_EXCHANGE_ANNOUNCEMENT = command_code("exchange_announcement")

ANNOUNCEMENT_BODY_SIZE = 54

_BINARY_MODULE = "axdata_source_tdx._tdx_wire._binary"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.announcement"
_BINARY_EXPORTS = {"decode_gbk_text", "little_u16", "little_u32"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_MODEL_EXPORTS = {"AnnouncementNotice", "ExchangeAnnouncementInfo"}


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _binary():
    return import_module(_BINARY_MODULE)


def build_announcement_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    """Build the 0x000A provider-announcement request frame (54 zero bytes)."""
    return RequestFrame(
        msg_id=msg_id,
        msg_type=TYPE_ANNOUNCEMENT,
        data=b"\x00" * ANNOUNCEMENT_BODY_SIZE,
    )


def build_exchange_announcement_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    """Build the 0x0002 exchange-announcement request frame (no body)."""
    return RequestFrame(msg_id=msg_id, msg_type=TYPE_EXCHANGE_ANNOUNCEMENT)


def parse_announcement_payload(response: ResponseFrame) -> AnnouncementNotice:
    payload = response.data
    if len(payload) == 0:
        raise _protocol_error()(f"invalid announcement response length: {len(payload)}")
    if payload[0] != 0x01:
        # gotdx：首字节非 0x01 时直接返回零值 reply（HasContent=false）。
        return import_module(_MODEL_MODULE).AnnouncementNotice(
            has_content=False,
            expire_date_raw=0,
            expire_date=None,
            title="",
            author="",
            content="",
            raw_payload=payload,
        )
    if len(payload) < 11:
        raise _protocol_error()(f"invalid announcement payload length: {len(payload)}")

    binary = _binary()
    expire_date_raw = binary.little_u32(payload[1:5])
    title_len = binary.little_u16(payload[5:7])
    author_len = binary.little_u16(payload[7:9])
    content_len = binary.little_u16(payload[9:11])
    end = 11 + title_len + author_len + content_len
    if end > len(payload):
        raise _protocol_error()(f"invalid announcement text length: {len(payload)}")

    pos = 11
    title = binary.decode_gbk_text(payload[pos : pos + title_len])
    pos += title_len
    author = binary.decode_gbk_text(payload[pos : pos + author_len])
    pos += author_len
    content = binary.decode_gbk_text(payload[pos : pos + content_len])

    return import_module(_MODEL_MODULE).AnnouncementNotice(
        has_content=True,
        expire_date_raw=expire_date_raw,
        expire_date=binary.date_from_yyyymmdd(expire_date_raw),
        title=title,
        author=author,
        content=content,
        raw_payload=payload,
    )


def parse_exchange_announcement_payload(response: ResponseFrame) -> ExchangeAnnouncementInfo:
    payload = response.data
    if len(payload) == 0:
        raise _protocol_error()(
            f"invalid exchange announcement response length: {len(payload)}"
        )
    return import_module(_MODEL_MODULE).ExchangeAnnouncementInfo(
        version=payload[0],
        content=_binary().decode_gbk_text(payload[1:]),
        raw_payload=payload,
    )


def __getattr__(name: str) -> Any:
    if name in _EXCEPTION_EXPORTS:
        value = getattr(import_module(_EXCEPTIONS_MODULE), name)
        globals()[name] = value
        return value
    if name in _MODEL_EXPORTS:
        value = getattr(import_module(_MODEL_MODULE), name)
        globals()[name] = value
        return value
    if name in _BINARY_EXPORTS:
        value = getattr(import_module(_BINARY_MODULE), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(
        set(globals()) | _EXCEPTION_EXPORTS | _MODEL_EXPORTS | _BINARY_EXPORTS
    )
