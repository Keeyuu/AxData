"""MAC symbol-info (0x122A) command builder and parser.

Wire layout follows gotdx ``proto/mac_symbol_info.go``: the request body is
``<u16 market><code[22]><u32 one><reserved[12]>`` with one defaulting to 1;
the response is a fixed 194-byte symbol summary (GBK text, little-endian
u32/u16, IEEE-754 f32). The request frame uses the MAC ex-request head byte
0x01.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._code_utils import split_code
from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.mac_symbol_info import MacSymbolInfo

TYPE_MAC_SYMBOL_INFO = command_code("mac_symbol_info")

DEFAULT_MAC_SYMBOL_INFO_ONE = 1
_CODE_WIDTH = 22
_RESERVED_WIDTH = 12
_MIN_PAYLOAD = 194

_BINARY_MODULE = "axdata_source_tdx._tdx_wire._binary"
_FRAME_CONSTANTS_MODULE = "axdata_source_tdx._tdx_wire.protocol._frame_constants"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.mac_symbol_info"
_BINARY_EXPORTS = {"decode_gbk_text", "little_f32"}
_FRAME_CONSTANTS_EXPORTS = {"MAC_EX_PREFIX"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_MODEL_EXPORTS = {"MacSymbolInfo"}


def _frame_constants():
    return import_module(_FRAME_CONSTANTS_MODULE)


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _binary():
    return import_module(_BINARY_MODULE)


def _model_module():
    return import_module(_MODEL_MODULE)


def _datetime_cls():
    return import_module("datetime").datetime


def build_mac_symbol_info_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    payload = payload or {}
    market_id, _, number = split_code(payload["code"])
    code = number.encode("ascii").ljust(_CODE_WIDTH, b"\x00")
    one = payload.get("one", 0)
    if not one:
        one = DEFAULT_MAC_SYMBOL_INFO_ONE
    one = _normalize_u32(one, "one")
    data = (
        market_id.to_bytes(2, "little", signed=False)
        + code
        + one.to_bytes(4, "little", signed=False)
        + b"\x00" * _RESERVED_WIDTH
    )
    return RequestFrame(
        msg_id=msg_id,
        msg_type=TYPE_MAC_SYMBOL_INFO,
        data=data,
        head=_frame_constants().MAC_EX_PREFIX,
    )


def parse_mac_symbol_info_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> MacSymbolInfo:
    request_payload = request_payload or {}
    payload = response.data
    if len(payload) < _MIN_PAYLOAD:
        raise _protocol_error()(f"invalid mac symbol info payload length: {len(payload)}")

    binary = _binary()
    date_time = _format_mac_quote_datetime(
        _little_u32(payload[96:100]), _little_u32(payload[100:104])
    )
    return _model_module().MacSymbolInfo(
        market=_little_u16(payload[8:10]),
        code=binary.decode_gbk_text(payload[10:32]),
        name=binary.decode_gbk_text(payload[32:76]),
        date_time=date_time,
        activity=_little_u32(payload[104:108]),
        pre_close=float(binary.little_f32(payload[108:112])),
        open=float(binary.little_f32(payload[112:116])),
        high=float(binary.little_f32(payload[116:120])),
        low=float(binary.little_f32(payload[120:124])),
        close=float(binary.little_f32(payload[124:128])),
        momentum=float(binary.little_f32(payload[128:132])),
        vol=_little_u32(payload[132:136]),
        amount=float(binary.little_f32(payload[136:140])),
        inside_volume=_little_u32(payload[140:144]),
        outside_volume=_little_u32(payload[144:148]),
        decimal=_little_u16(payload[148:150]),
        unknown_a=_little_u32(payload[150:154]),
        unknown_b=float(binary.little_f32(payload[154:158])),
        unknown_c=_little_u32(payload[178:182]),
        vr=float(binary.little_f32(payload[182:186])),
        turnover=float(binary.little_f32(payload[186:190])),
        avg=float(binary.little_f32(payload[190:194])),
        raw_payload=payload if request_payload.get("include_raw") else b"",
    )


def _little_u16(data: bytes) -> int:
    return int.from_bytes(data, "little", signed=False)


def _little_u32(data: bytes) -> int:
    return int.from_bytes(data, "little", signed=False)


def _format_mac_quote_datetime(date_raw: int, time_raw: int):
    # gotdx formatMACQuoteDateTime：YYYYMMDD + HHMMSS -> naive datetime。
    year = date_raw // 10000
    month = (date_raw % 10000) // 100
    day = date_raw % 100
    hour = time_raw // 10000
    minute = (time_raw % 10000) // 100
    second = time_raw % 100
    return _datetime_cls()(year, month, day, hour, minute, second)


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
    if name in _BINARY_EXPORTS:
        value = getattr(import_module(_BINARY_MODULE), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(
        set(globals())
        | _EXCEPTION_EXPORTS
        | _MODEL_EXPORTS
        | _FRAME_CONSTANTS_EXPORTS
        | _BINARY_EXPORTS
    )
