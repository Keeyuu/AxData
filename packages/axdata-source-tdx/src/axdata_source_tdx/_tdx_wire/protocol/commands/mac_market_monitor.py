"""MAC market monitor (0x1237) command builder and parser.

Wire layout follows gotdx ``proto/mac_market_monitor.go``: the request is
``<u16 market><u16 start><u16 reserved1><u16 count><u16 reserved2><u16 mode>
<limits[5] u16>`` with gotdx defaults (count=600, mode=1, limits
``[200,30,40,50,200]``); the response is ``<u16 count>`` followed by 32-byte
records whose desc/value strings come from the shared unusual
``unpackUnusualByType`` port, with the trailing GBK names split on commas.
"""

from __future__ import annotations

from dataclasses import replace
from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire._market import market_to_id
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.mac_market_monitor import MacMarketMonitorPage

TYPE_MAC_MARKET_MONITOR = command_code("mac_market_monitor")

MAC_MARKET_MONITOR_DEFAULT_COUNT = 600
MAC_MARKET_MONITOR_DEFAULT_MODE = 1
MAC_MARKET_MONITOR_DEFAULT_LIMITS = (200, 30, 40, 50, 200)
MAC_MARKET_MONITOR_ITEM_SIZE = 32

_BINARY_MODULE = "axdata_source_tdx._tdx_wire._binary"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.mac_market_monitor"
_UNUSUAL_MODULE = "axdata_source_tdx._tdx_wire.protocol.commands.unusual"
_FRAME_CONSTANTS_MODULE = "axdata_source_tdx._tdx_wire.protocol._frame_constants"
_BINARY_EXPORTS = {"decode_gbk_text", "little_f32", "little_u16"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_MODEL_EXPORTS = {"MacMarketMonitorItem", "MacMarketMonitorPage"}
_FRAME_CONSTANTS_EXPORTS = {"MAC_EX_PREFIX"}


def _frame_constants():
    return import_module(_FRAME_CONSTANTS_MODULE)


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _binary():
    return import_module(_BINARY_MODULE)


def _unpack_unusual_by_type(event_type: int, data: bytes) -> tuple[str, str]:
    # 惰性复用 commands.unusual 的 port，不复制实现。
    return import_module(_UNUSUAL_MODULE)._unpack_unusual_by_type(event_type, data)


def build_mac_market_monitor_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    """Build the 0x1237 request frame (head=0x01, 22 bytes)."""
    market_id = market_to_id(payload.get("market", payload.get("market_id", "sz")))
    start = _normalize_u16(payload.get("start", 0), "start")
    count = _normalize_u16(payload.get("count", 0), "count")
    if count == 0:
        count = MAC_MARKET_MONITOR_DEFAULT_COUNT
    mode = _normalize_u16(payload.get("mode", 0), "mode")
    if mode == 0:
        mode = MAC_MARKET_MONITOR_DEFAULT_MODE
    limits = payload.get("limits")
    if limits is None:
        limits = MAC_MARKET_MONITOR_DEFAULT_LIMITS
    if not isinstance(limits, (list, tuple)) or len(limits) != 5:
        raise _protocol_error()("limits must be a sequence of 5 integers")
    limits_bytes = b"".join(
        _normalize_u16(value, "limits").to_bytes(2, "little", signed=False) for value in limits
    )
    data = (
        market_id.to_bytes(2, "little", signed=False)
        + start.to_bytes(2, "little", signed=False)
        + b"\x00\x00"  # Reserved1 u16
        + count.to_bytes(2, "little", signed=False)
        + b"\x00\x00"  # Reserved2 u16
        + mode.to_bytes(2, "little", signed=False)
        + limits_bytes
    )
    return RequestFrame(
        msg_id=msg_id,
        msg_type=TYPE_MAC_MARKET_MONITOR,
        data=data,
        head=_frame_constants().MAC_EX_PREFIX,
    )


def parse_mac_market_monitor_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> MacMarketMonitorPage:
    request_payload = request_payload or {}
    payload = response.data
    if len(payload) < 2:
        raise _protocol_error()(f"invalid mac market monitor payload length: {len(payload)}")

    binary = _binary()
    model_module = import_module(_MODEL_MODULE)
    item_cls = model_module.MacMarketMonitorItem
    count = binary.little_u16(payload[:2])

    items = []
    for index in range(count):
        base = 2 + index * MAC_MARKET_MONITOR_ITEM_SIZE
        if base + MAC_MARKET_MONITOR_ITEM_SIZE > len(payload):
            raise _protocol_error()(f"truncated mac market monitor item at offset {base}")
        record = payload[base : base + MAC_MARKET_MONITOR_ITEM_SIZE]
        v_payload = record[15:28]
        v1 = v_payload[0]
        v2 = float(binary.little_f32(v_payload[1:5]))
        v3 = float(binary.little_f32(v_payload[5:9]))
        v4 = float(binary.little_f32(v_payload[9:13]))
        desc, value = _unpack_unusual_by_type(record[9], v_payload)
        hour = record[29]
        minute_sec = binary.little_u16(record[30:32])
        items.append(
            item_cls(
                index=binary.little_u16(record[11:13]),
                market=binary.little_u16(record[0:2]),
                code=binary.decode_gbk_text(record[2:8]),
                name="",
                time=f"{hour:02d}:{minute_sec // 100:02d}:{minute_sec % 100:02d}",
                desc=desc,
                value=value,
                unusual_type=record[9],
                v1=v1,
                v2=v2,
                v3=v3,
                v4=v4,
            )
        )

    binary_length = 2 + count * MAC_MARKET_MONITOR_ITEM_SIZE
    if binary_length < len(payload):
        names_text = binary.decode_gbk_text(payload[binary_length:]).strip(" ,")
        if names_text:
            parts = names_text.split(",")
            for position, part in enumerate(parts):
                if position < len(items):
                    items[position] = replace(items[position], name=part)

    return model_module.MacMarketMonitorPage(
        count=count,
        items=tuple(items),
        raw_payload=payload if request_payload.get("include_raw") else b"",
    )


def _normalize_u16(value: Any, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise _protocol_error()(f"{name} must be an integer") from exc
    if parsed < 0 or parsed > 0xFFFF:
        raise _protocol_error()(f"{name} must be between 0 and 65535")
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
    if name in _FRAME_CONSTANTS_EXPORTS:
        value = getattr(import_module(_FRAME_CONSTANTS_MODULE), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(
        set(globals())
        | _EXCEPTION_EXPORTS
        | _MODEL_EXPORTS
        | _BINARY_EXPORTS
        | _FRAME_CONSTANTS_EXPORTS
    )
