"""MAC server-info (0x120F) command builder and parser.

Wire layout follows gotdx ``proto/mac_server_info.go``: the request is a
68-byte fixed payload (gotdx ``defaultMACServerInfoPayload``) and the response
carries the server trading calendar, two session tables and market params.
The request frame uses the MAC ex-request head byte 0x01.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.mac_server_info import MacServerInfo

TYPE_MAC_SERVER_INFO = command_code("mac_server_info")

_MIN_PAYLOAD = 87
_SESSION_WIDTH = 16
# gotdx defaultMACServerInfoPayload：前 4 字节 04 00 2d 31、[12:16] 00 27 06 0e，其余 0。
DEFAULT_MAC_SERVER_INFO_PAYLOAD = (
    bytes([0x04, 0x00, 0x2D, 0x31]) + b"\x00" * 8 + bytes([0x00, 0x27, 0x06, 0x0E]) + b"\x00" * 52
)

_FRAME_CONSTANTS_MODULE = "axdata_source_tdx._tdx_wire.protocol._frame_constants"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.mac_server_info"
_FRAME_CONSTANTS_EXPORTS = {"MAC_EX_PREFIX"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_MODEL_EXPORTS = {"MacServerInfo", "MacTradingSession"}


def _frame_constants():
    return import_module(_FRAME_CONSTANTS_MODULE)


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _model_module():
    return import_module(_MODEL_MODULE)


def build_mac_server_info_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    return RequestFrame(
        msg_id=msg_id,
        msg_type=TYPE_MAC_SERVER_INFO,
        data=DEFAULT_MAC_SERVER_INFO_PAYLOAD,
        head=_frame_constants().MAC_EX_PREFIX,
    )


def parse_mac_server_info_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> MacServerInfo:
    request_payload = request_payload or {}
    payload = response.data
    if len(payload) < _MIN_PAYLOAD:
        raise _protocol_error()(f"invalid mac server info payload length: {len(payload)}")

    session_cls = _model_module().MacTradingSession
    count = _little_u16(payload[0:2])
    flags_hex = payload[2:10].hex()
    tag = payload[10:13].rstrip(b"\x00").decode("ascii", errors="replace")
    today = _format_mac_server_date(_little_u32(payload[22:26]))
    ts1 = _little_u32(payload[26:30])
    sessions1 = _sessions(payload[30:46], session_cls)
    sessions2 = _sessions(payload[46:62], session_cls)
    flag = payload[62]
    last_trading_day = _format_mac_server_date(_little_u32(payload[63:67]))
    ts2 = _little_u32(payload[67:71])
    last_trading_day2 = _format_mac_server_date(_little_u32(payload[71:75]))
    ts3 = _little_u32(payload[75:79])
    market_param1 = _little_u32(payload[79:83])
    market_param2 = _little_u32(payload[83:87])
    extra_hex = payload[_MIN_PAYLOAD:].hex()

    return _model_module().MacServerInfo(
        count=count,
        flags_hex=flags_hex,
        tag=tag,
        today=today,
        ts1=ts1,
        sessions1=sessions1,
        sessions2=sessions2,
        flag=flag,
        last_trading_day=last_trading_day,
        ts2=ts2,
        last_trading_day2=last_trading_day2,
        ts3=ts3,
        market_param1=market_param1,
        market_param2=market_param2,
        extra_hex=extra_hex,
        raw_payload=payload if request_payload.get("include_raw") else b"",
    )


def _sessions(data: bytes, session_cls) -> tuple:
    sessions = []
    for offset in range(0, len(data), 4):
        open_minutes = _little_u16(data[offset : offset + 2])
        close_minutes = _little_u16(data[offset + 2 : offset + 4])
        sessions.append(
            session_cls(
                open_minutes=open_minutes,
                close_minutes=close_minutes,
                open=_format_mac_session_time(open_minutes),
                close=_format_mac_session_time(close_minutes),
            )
        )
    return tuple(sessions)


def _little_u16(data: bytes) -> int:
    return int.from_bytes(data, "little", signed=False)


def _little_u32(data: bytes) -> int:
    return int.from_bytes(data, "little", signed=False)


def _format_mac_session_time(minutes: int) -> str:
    # gotdx formatMACSessionTime：小时不补零（"9:30"），分钟两位。
    return f"{minutes // 60}:{minutes % 60:02d}"


def _format_mac_server_date(raw: int) -> str:
    # gotdx formatMACServerDate：YYYYMMDD -> "YYYY-MM-DD"。
    return f"{raw // 10000:04d}-{(raw % 10000) // 100:02d}-{raw % 100:02d}"


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
