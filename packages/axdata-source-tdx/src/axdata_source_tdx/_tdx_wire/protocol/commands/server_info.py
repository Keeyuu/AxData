"""Server-info (0x0015) command builder and parser.

Wire layout follows gotdx ``proto/server.go`` (``Info`` / ``InfoReply``): the
request carries an empty body; the reply is a fixed-offset block of at least
427 bytes (delay, GBK info/content/server-sign, region/switch u16 fields and
a packed date+time pair).
"""

from __future__ import annotations

from datetime import datetime
from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.server_info import ServerInfo

TYPE_SERVER_INFO = command_code("server_info")

SERVER_INFO_MIN_SIZE = 427

_BINARY_MODULE = "axdata_source_tdx._tdx_wire._binary"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.server_info"
_BINARY_EXPORTS = {"decode_gbk_text", "little_u16", "little_u32"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_MODEL_EXPORTS = {"ServerInfo"}


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _binary():
    return import_module(_BINARY_MODULE)


def build_server_info_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    return RequestFrame(msg_id=msg_id, msg_type=TYPE_SERVER_INFO, data=b"")


def parse_server_info_payload(response: ResponseFrame) -> ServerInfo:
    payload = response.data
    if len(payload) < SERVER_INFO_MIN_SIZE:
        raise _protocol_error()(
            f"invalid server info payload length: {len(payload)}"
        )

    binary = _binary()
    delay = binary.little_u32(payload[0:4])
    unknown1_a = binary.little_u16(payload[4:6])
    unknown1_b = binary.little_u16(payload[14:16])
    unknown2_a = binary.little_u16(payload[360:362])
    unknown2_b = binary.little_u16(payload[362:364])
    unknown3_b = binary.little_u16(payload[391:393])
    region = binary.little_u16(payload[389:391])
    maybe_switch = binary.little_u16(payload[395:397])
    date_now = binary.little_u32(payload[397:401])
    time_now = binary.little_u32(payload[401:405])

    time_now_text = ""
    if date_now != 0:
        try:
            parsed = datetime.strptime(f"{date_now:08d}{time_now:06d}", "%Y%m%d%H%M%S")
            time_now_text = parsed.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise _protocol_error()(
                f"invalid server info time: {date_now!r}/{time_now!r}"
            ) from exc

    return import_module(_MODEL_MODULE).ServerInfo(
        delay=delay,
        info=binary.decode_gbk_text(payload[16:71]),
        content=binary.decode_gbk_text(payload[81:336]),
        server_sign=binary.decode_gbk_text(payload[336:356]),
        time_now=time_now_text,
        unknown1=(
            f"{unknown1_a}",
            f"{unknown1_b}",
            payload[6:14].hex(),
        ),
        unknown2=(
            f"{unknown2_a}",
            f"{unknown2_b}",
            payload[364:370].hex(),
        ),
        unknown3=(region, unknown3_b, maybe_switch),
        region=region,
        maybe_switch=maybe_switch,
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
    return sorted(set(globals()) | _EXCEPTION_EXPORTS | _MODEL_EXPORTS | _BINARY_EXPORTS)
