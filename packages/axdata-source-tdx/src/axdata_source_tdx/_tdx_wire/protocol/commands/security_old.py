"""Old security code-table (0x0450) command builder and parser.

Wire layout follows gotdx ``proto/get_security_list_old.go``: the request body
is ``<u16 market><u16 start>``; the response is ``<u16 count>`` followed by
29-byte legacy records (code/vol/name/unknown1/pad2/decimal/preclose/unknown2/
unknown3).
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire._market import market_to_id, normalize_market
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.security_old import SecurityListOldPage

TYPE_SECURITY_LIST_OLD = command_code("security_list_old")

SECURITY_OLD_RECORD_SIZE = 29

_BINARY_MODULE = "axdata_source_tdx._tdx_wire._binary"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.security_old"
_BINARY_EXPORTS = {"decode_gbk_text", "little_f32", "little_u16"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_MODEL_EXPORTS = {"SecurityCodeOld", "SecurityListOldPage"}


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _binary():
    return import_module(_BINARY_MODULE)


def _page_cls():
    return import_module(_MODEL_MODULE).SecurityListOldPage


def build_security_list_old_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    market_id = market_to_id(payload.get("market", payload.get("market_id", "sz")))
    start = _normalize_u16(payload.get("start", 0), "start")
    data = (
        market_id.to_bytes(2, "little", signed=False)
        + start.to_bytes(2, "little", signed=False)
    )
    return RequestFrame(msg_id=msg_id, msg_type=TYPE_SECURITY_LIST_OLD, data=data)


def parse_security_list_old_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> SecurityListOldPage:
    request_payload = request_payload or {}
    exchange = normalize_market(
        request_payload.get("market", request_payload.get("market_id", "sz"))
    )
    market_id = market_to_id(exchange)
    start = _normalize_u16(request_payload.get("start", 0), "start")
    payload = response.data
    if len(payload) < 2:
        raise _protocol_error()("invalid security list old payload")

    binary = _binary()
    count = binary.little_u16(payload[:2])
    expected_length = 2 + count * SECURITY_OLD_RECORD_SIZE
    if len(payload) < expected_length:
        raise _protocol_error()(
            f"truncated security list old payload: expected {expected_length}, got {len(payload)}"
        )

    record_cls = import_module(_MODEL_MODULE).SecurityCodeOld
    codes = []
    offset = 2
    for _ in range(count):
        record = payload[offset : offset + SECURITY_OLD_RECORD_SIZE]
        offset += SECURITY_OLD_RECORD_SIZE
        legacy_unknown1 = binary.little_u16(record[16:18])
        decimal_point = record[20]
        if decimal_point >= 0x80:
            decimal_point -= 0x100
        codes.append(
            record_cls(
                code=binary.decode_gbk_text(record[:6]),
                vol=binary.little_u16(record[6:8]),
                name=binary.decode_gbk_text(record[8:16]),
                unknown1=float(legacy_unknown1),
                legacy_unknown1=legacy_unknown1,
                decimal_point=decimal_point,
                pre_close=float(binary.little_f32(record[21:25])),
                unknown2=binary.little_u16(record[25:27]),
                unknown3=binary.little_u16(record[27:29]),
                record_hex=record.hex(),
            )
        )

    return _page_cls()(
        exchange=exchange,
        market_id=market_id,
        start=start,
        codes=tuple(codes),
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
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _EXCEPTION_EXPORTS | _MODEL_EXPORTS | _BINARY_EXPORTS)
