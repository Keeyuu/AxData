"""MAC transactions (0x122F) command builder and parser.

Wire layout follows gotdx ``proto/mac_transactions.go``. The request body is
a packed struct (44 bytes): ``<u16 market><code[22]><u32 query_date><u32
start><u16 count><reserved[10]>`` with default count=1000. The ``query_date``
payload key is an explicit field of the base request structure, so the
"with date" variant is N/A-equivalent: same command code, same frame
geometry, only the query_date bytes differ.

The response header skips byte 28 (a reserved byte) before ``count`` at
offset 29; each of the ``count`` 18-byte items holds a seconds-of-day
timestamp formatted as zero-padded "HH:MM:SS".
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._code_utils import split_code
from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.mac_transactions import MacTransactionsPage

TYPE_MAC_TRANSACTIONS = command_code("mac_transactions")

_SYMBOL_WIDTH = 22
_HEADER_LENGTH = 39
_ITEM_LENGTH = 18
_DEFAULT_COUNT = 1000

_BINARY_MODULE = "axdata_source_tdx._tdx_wire._binary"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_FRAME_CONSTANTS_MODULE = "axdata_source_tdx._tdx_wire.protocol._frame_constants"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.mac_transactions"
_BINARY_EXPORTS = {"decode_gbk_text", "little_f32", "little_u16", "little_u32"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_FRAME_CONSTANTS_EXPORTS = {"MAC_EX_PREFIX"}
_MODEL_EXPORTS = {"MacTransactionItem", "MacTransactionsPage"}


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _binary():
    return import_module(_BINARY_MODULE)


def _frame_constants():
    return import_module(_FRAME_CONSTANTS_MODULE)


def _item_cls():
    return import_module(_MODEL_MODULE).MacTransactionItem


def _page_cls():
    return import_module(_MODEL_MODULE).MacTransactionsPage


def build_mac_transactions_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    market_id, _, number = split_code(payload["code"])
    symbol = number.encode("ascii").ljust(_SYMBOL_WIDTH, b"\x00")
    query_date = int(payload.get("query_date") or 0) & 0xFFFFFFFF
    start = int(payload.get("start", 0)) & 0xFFFFFFFF
    count = int(payload.get("count", _DEFAULT_COUNT)) or _DEFAULT_COUNT
    data = (
        market_id.to_bytes(2, "little", signed=False)
        + symbol
        + query_date.to_bytes(4, "little", signed=False)
        + start.to_bytes(4, "little", signed=False)
        + (count & 0xFFFF).to_bytes(2, "little", signed=False)
        + b"\x00" * 10
    )
    return RequestFrame(
        msg_id=msg_id,
        msg_type=TYPE_MAC_TRANSACTIONS,
        data=data,
        head=_frame_constants().MAC_EX_PREFIX,
    )


def parse_mac_transactions_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> MacTransactionsPage:
    request_payload = request_payload or {}
    payload = response.data
    if len(payload) < _HEADER_LENGTH:
        raise _protocol_error()(f"invalid mac transactions payload length: {len(payload)}")

    binary = _binary()
    market = binary.little_u16(payload[0:2])
    code = binary.decode_gbk_text(payload[2:24])
    query_date = binary.little_u32(payload[24:28])
    count = binary.little_u16(payload[29:31])
    start = binary.little_u32(payload[31:35])
    total = binary.little_u32(payload[35:39])

    pos = _HEADER_LENGTH
    item_cls = _item_cls()
    items = []
    for index in range(count):
        if pos + _ITEM_LENGTH > len(payload):
            raise _protocol_error()(f"truncated mac transactions item {index}")
        seconds = binary.little_u32(payload[pos : pos + 4])
        items.append(
            item_cls(
                time=f"{seconds // 3600 % 24:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}",
                price=float(binary.little_f32(payload[pos + 4 : pos + 8])),
                vol=binary.little_u32(payload[pos + 8 : pos + 12]),
                trade_count=binary.little_u32(payload[pos + 12 : pos + 16]),
                buy_or_sell=binary.little_u16(payload[pos + 16 : pos + 18]),
            )
        )
        pos += _ITEM_LENGTH

    return _page_cls()(
        full_code=request_payload.get("code", ""),
        market=market,
        code=code,
        query_date=query_date,
        count=count,
        start=start,
        total=total,
        items=tuple(items),
        raw_payload=payload if request_payload.get("include_raw") else b"",
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
