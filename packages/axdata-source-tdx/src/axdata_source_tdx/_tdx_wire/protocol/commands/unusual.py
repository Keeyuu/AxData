"""Unusual-movement feed (0x0563) command builder and parser.

Wire layout follows gotdx ``proto/get_unusual.go``: the request body is
``<u16 market><u32 start><u32 count>`` (count defaults to 600); the response
is ``<u16 count>`` followed by 32-byte records whose desc/value strings come
from gotdx's ``unpackUnusualByType`` switch on the event type byte.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire._command_defaults import DEFAULT_UNUSUAL_COUNT
from axdata_source_tdx._tdx_wire._market import market_to_id, normalize_market
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.unusual import UnusualPage

TYPE_UNUSUAL = command_code("unusual")

UNUSUAL_RECORD_SIZE = 32

_BINARY_MODULE = "axdata_source_tdx._tdx_wire._binary"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.unusual"
_BINARY_EXPORTS = {"decode_gbk_text", "little_f32", "little_u16"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_MODEL_EXPORTS = {"UnusualPage", "UnusualRecord"}


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _binary():
    return import_module(_BINARY_MODULE)


def build_unusual_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    market_id = market_to_id(payload.get("market", payload.get("market_id", "sz")))
    start = _normalize_u32(payload.get("start", 0), "start")
    count = payload.get("count", 0)
    count = DEFAULT_UNUSUAL_COUNT if not count else _normalize_u32(count, "count")
    data = (
        market_id.to_bytes(2, "little", signed=False)
        + start.to_bytes(4, "little", signed=False)
        + count.to_bytes(4, "little", signed=False)
    )
    return RequestFrame(msg_id=msg_id, msg_type=TYPE_UNUSUAL, data=data)


def parse_unusual_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> UnusualPage:
    request_payload = request_payload or {}
    exchange = normalize_market(
        request_payload.get("market", request_payload.get("market_id", "sz"))
    )
    market_id = market_to_id(exchange)
    start = _normalize_u32(request_payload.get("start", 0), "start")
    count = _normalize_u32(
        request_payload.get("count", 0) or DEFAULT_UNUSUAL_COUNT,
        "count",
    )
    payload = response.data
    if len(payload) < 2:
        raise _protocol_error()("invalid unusual payload")

    binary = _binary()
    record_count = binary.little_u16(payload[:2])
    expected_length = 2 + record_count * UNUSUAL_RECORD_SIZE
    if len(payload) < expected_length:
        raise _protocol_error()(
            f"truncated unusual payload: expected {expected_length}, got {len(payload)}"
        )

    record_cls = import_module(_MODEL_MODULE).UnusualRecord
    records = []
    for index in range(record_count):
        base = 2 + index * UNUSUAL_RECORD_SIZE
        record = payload[base : base + UNUSUAL_RECORD_SIZE]
        event_type = record[9]
        row_index = binary.little_u16(record[11:13])
        desc, value = _unpack_unusual_by_type(event_type, record[15:28])
        hour = record[29]
        minute_sec = binary.little_u16(record[30:32])
        records.append(
            record_cls(
                index=row_index,
                market_id=binary.little_u16(record[0:2]),
                code=binary.decode_gbk_text(record[2:8]),
                time=f"{hour:02d}:{minute_sec // 100:02d}:{minute_sec % 100:02d}",
                desc=desc,
                value=value,
                unusual_type=event_type,
                record_hex=record.hex(),
            )
        )

    return import_module(_MODEL_MODULE).UnusualPage(
        market_id=market_id,
        exchange=exchange,
        start=start,
        request_count=count,
        records=tuple(records),
        raw_payload=payload if request_payload.get("include_raw") else b"",
    )


def _unpack_unusual_by_type(event_type: int, data: bytes) -> tuple[str, str]:
    """Port of gotdx ``unpackUnusualByType`` (proto/get_unusual.go)."""

    if len(data) < 13:
        return "", ""

    binary = _binary()
    v1 = data[0]
    v2 = float(binary.little_f32(data[1:5]))
    v3 = float(binary.little_f32(data[5:9]))
    v4 = float(binary.little_f32(data[9:13]))

    if event_type == 0x03:
        desc = "主力卖出" if v1 != 0x00 else "主力买入"
        return desc, f"{v2:.2f}/{v3:.2f}"
    if event_type == 0x04:
        return "加速拉升", f"{v2 * 100:.2f}%"
    if event_type == 0x05:
        return "加速下跌", ""
    if event_type == 0x06:
        return "低位反弹", f"{v2 * 100:.2f}%"
    if event_type == 0x07:
        return "高位回落", f"{v2 * 100:.2f}%"
    if event_type == 0x08:
        return "撑杆跳高", f"{v2 * 100:.2f}%"
    if event_type == 0x09:
        return "平台跳水", f"{v2 * 100:.2f}%"
    if event_type == 0x0A:
        desc = "单笔冲跌" if v2 < 0 else "单笔冲涨"
        return desc, f"{v2 * 100:.2f}%"
    if event_type == 0x0B:
        if v3 == 0:
            return "区间放量平", f"{v2:.1f}倍"
        direction = "跌" if v3 < 0 else "涨"
        return f"区间放量{direction}", f"{v2:.1f}倍{v3 * 100:.2f}%"
    if event_type == 0x0C:
        return "区间缩量", ""
    if event_type == 0x10:
        return "大单托盘", f"{v4:.2f}/{v3:.2f}"
    if event_type == 0x11:
        return "大单压盘", f"{v2:.2f}/{v3:.2f}"
    if event_type == 0x12:
        return "大单锁盘", ""
    if event_type == 0x13:
        return "竞价试买", f"{v2:.2f}/{v3:.2f}"
    if event_type == 0x14:
        return _unpack_limit_event(v1, data)
    if event_type == 0x15:
        desc = {0x00: "尾盘??", 0x01: "尾盘对倒", 0x02: "尾盘拉升"}.get(v1, "尾盘打压")
        return desc, f"{v2 * 100:.2f}%/{v3:.2f}"
    if event_type == 0x16:
        desc = "盘中弱势" if v2 < 0 else "盘中强势"
        return desc, f"{v2 * 100:.2f}%"
    if event_type == 0x1D:
        return "急速拉升", f"{v2 * 100:.2f}%"
    if event_type == 0x1E:
        return "急速下跌", f"{v2 * 100:.2f}%"
    return "", ""


def _unpack_limit_event(v1: int, data: bytes) -> tuple[str, str]:
    binary = _binary()
    if len(data) < 10:
        return "", ""
    sub_type = data[1]
    uv2 = float(binary.little_f32(data[2:6]))
    uv3 = float(binary.little_f32(data[6:10]))
    direction = "涨" if v1 == 0x00 else "跌"
    sub_desc = {
        0x01: f"逼近{direction}停",
        0x02: f"封{direction}停板",
        0x04: f"封{direction}大减",
        0x05: f"打开{direction}停",
    }.get(sub_type, "")
    return sub_desc, f"{uv2:.2f}/{uv3:.2f}"


def _normalize_u32(value: Any, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise _protocol_error()(f"{name} must be an integer") from exc
    if parsed < 0 or parsed > 0xFFFFFFFF:
        raise _protocol_error()(f"{name} must be between 0 and 4294967295")
    return parsed


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
    return sorted(set(globals()) | _EXCEPTION_EXPORTS | _MODEL_EXPORTS | _BINARY_EXPORTS)
