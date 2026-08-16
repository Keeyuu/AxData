"""MAC batch symbol quotes (0x122B) command builder and parser.

Wire layout follows gotdx ``proto/mac_symbol_quotes.go``: the request is the
20-byte field bitmap, a u16 stock count, then per stock a u16 market and a
22-byte zero-padded code; the response repeats the 20-byte bitmap, u32 total,
u16 count, then rows of 68 bytes + 4 bytes per active bitmap field decoded
through the shared dynamic field table.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._code_utils import split_code
from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire.protocol.commands.mac_common import (
    DEFAULT_MAC_FIELD_BITMAP,
    active_mac_dynamic_fields,
    decode_mac_dynamic_value,
)
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.mac_symbol_quotes import MacSymbolQuotesPage

TYPE_MAC_SYMBOL_QUOTES = command_code("mac_symbol_quotes")

_SYMBOL_WIDTH = 22
_FIELD_BITMAP_WIDTH = 20
_HEAD_SIZE = 26
_BINARY_MODULE = "axdata_source_tdx._tdx_wire._binary"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.mac_symbol_quotes"
_FRAME_CONSTANTS_MODULE = "axdata_source_tdx._tdx_wire.protocol._frame_constants"
_BINARY_EXPORTS = {"decode_gbk_text", "little_f32", "little_u16", "little_u32"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_MODEL_EXPORTS = {"MacSymbolQuoteItem", "MacSymbolQuotesPage"}
_FRAME_CONSTANTS_EXPORTS = {"MAC_EX_PREFIX"}


def _frame_constants():
    return import_module(_FRAME_CONSTANTS_MODULE)


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _binary():
    return import_module(_BINARY_MODULE)


def build_mac_symbol_quotes_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    """Build the 0x122B request frame (head=0x01)."""
    bitmap = _normalize_bitmap(payload.get("field_bitmap"))
    securities = payload.get("securities") or []
    stock_bytes = bytearray()
    for code in securities:
        market_id, _, number = split_code(str(code))
        stock_bytes += market_id.to_bytes(2, "little", signed=False)
        stock_bytes += number.encode("ascii").ljust(_SYMBOL_WIDTH, b"\x00")
    data = bitmap + len(securities).to_bytes(2, "little", signed=False) + bytes(stock_bytes)
    return RequestFrame(
        msg_id=msg_id,
        msg_type=TYPE_MAC_SYMBOL_QUOTES,
        data=data,
        head=_frame_constants().MAC_EX_PREFIX,
    )


def parse_mac_symbol_quotes_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> MacSymbolQuotesPage:
    request_payload = request_payload or {}
    payload = response.data
    if len(payload) < _HEAD_SIZE:
        raise _protocol_error()(f"invalid mac symbol quotes payload length: {len(payload)}")

    binary = _binary()
    model_module = import_module(_MODEL_MODULE)
    field_bitmap = bytes(payload[:20])
    total = binary.little_u32(payload[20:24])
    count = binary.little_u16(payload[24:26])
    active_fields = active_mac_dynamic_fields(field_bitmap)
    row_size = 68 + len(active_fields) * 4

    item_cls = model_module.MacSymbolQuoteItem
    stocks = []
    offset = _HEAD_SIZE
    for _ in range(count):
        if offset + row_size > len(payload):
            raise _protocol_error()(f"truncated mac symbol quote item at offset {offset}")
        row = payload[offset : offset + row_size]
        values: dict[str, Any] = {}
        field_pos = 68
        for field_def in active_fields:
            raw = row[field_pos : field_pos + 4]
            value = decode_mac_dynamic_value(field_def.format, raw)
            values[field_def.name] = value
            for alias in field_def.aliases:
                values[alias] = value
            field_pos += 4
        stocks.append(
            item_cls(
                name=binary.decode_gbk_text(row[24:68]),
                market=binary.little_u16(row[0:2]),
                symbol=binary.decode_gbk_text(row[2:24]),
                values=values,
            )
        )
        offset += row_size

    return model_module.MacSymbolQuotesPage(
        field_bitmap=field_bitmap,
        active_fields=tuple(active_fields),
        total=total,
        count=count,
        stocks=tuple(stocks),
        raw_payload=payload if request_payload.get("include_raw") else b"",
    )


def _normalize_bitmap(value: Any) -> bytes:
    if value is None:
        return bytes(DEFAULT_MAC_FIELD_BITMAP)
    if not isinstance(value, (bytes, bytearray)) or len(value) != _FIELD_BITMAP_WIDTH:
        raise _protocol_error()("field_bitmap must be 20 bytes")
    return bytes(value)


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
