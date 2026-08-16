"""MAC kline-offset (0x124A) command builder and parser.

Wire layout follows gotdx ``proto/mac_kline_offset.go``: the request body is
``<u32 offset><u32 count><reserved[5]>`` with count defaulting to 128000; the
response is ``<u32 total big-endian><u32 returned little-endian>``. The request
frame uses the MAC ex-request head byte 0x01.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.mac_kline_offset import MacKlineOffset

TYPE_MAC_KLINE_OFFSET = command_code("mac_kline_offset")

DEFAULT_MAC_KLINE_COUNT = 128000
_REQUEST_SIZE = 13
_MIN_PAYLOAD = 8

_FRAME_CONSTANTS_MODULE = "axdata_source_tdx._tdx_wire.protocol._frame_constants"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.mac_kline_offset"
_FRAME_CONSTANTS_EXPORTS = {"MAC_EX_PREFIX"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_MODEL_EXPORTS = {"MacKlineOffset"}


def _frame_constants():
    return import_module(_FRAME_CONSTANTS_MODULE)


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _model_module():
    return import_module(_MODEL_MODULE)


def build_mac_kline_offset_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    payload = payload or {}
    offset = _normalize_u32(payload.get("offset", 0), "offset")
    count = payload.get("count", 0)
    if not count:
        count = DEFAULT_MAC_KLINE_COUNT
    count = _normalize_u32(count, "count")
    data = (
        offset.to_bytes(4, "little", signed=False)
        + count.to_bytes(4, "little", signed=False)
        + b"\x00" * (_REQUEST_SIZE - 8)
    )
    return RequestFrame(
        msg_id=msg_id,
        msg_type=TYPE_MAC_KLINE_OFFSET,
        data=data,
        head=_frame_constants().MAC_EX_PREFIX,
    )


def parse_mac_kline_offset_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> MacKlineOffset:
    request_payload = request_payload or {}
    payload = response.data
    if len(payload) < _MIN_PAYLOAD:
        raise _protocol_error()(f"invalid mac kline offset payload length: {len(payload)}")

    # total 大端（gotdx binary.BigEndian）、returned 小端。
    total = int.from_bytes(payload[0:4], "big", signed=False)
    returned = int.from_bytes(payload[4:8], "little", signed=False)
    return _model_module().MacKlineOffset(
        total=total,
        returned=returned,
        raw_payload=payload if request_payload.get("include_raw") else b"",
    )


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
    if name in _FRAME_CONSTANTS_EXPORTS:
        value = getattr(import_module(_FRAME_CONSTANTS_MODULE), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _EXCEPTION_EXPORTS | _MODEL_EXPORTS | _FRAME_CONSTANTS_EXPORTS)
