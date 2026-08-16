"""MAC auction (0x123D) command builder and parser.

Wire layout follows gotdx ``proto/mac_auction.go``: the request body is the
tight-packed struct ``<u16 market><code[22]><u32 start><u32 count><reserved[10]>``
(42 bytes, count defaults to 500); the response is ``<u16 market><code[22]>
<u32 count>`` plus an 8-byte gap, then 16-byte records of ``<u32 seconds>
<f32 price><u32 matched><i32 unmatched>``.

Upstream note (@c6958ea): gotdx's implementation absolutizes ``unmatched``
before deriving ``flag``, which makes the flag branch dead code and contradicts
``mac_protocol_test.go`` (``TestMACAuctionBuildRequestAndParseResponse`` asserts
``Unmatched == -50, Flag == -1`` for a negative wire value). The port follows
the test's explicit golden semantics: ``unmatched`` keeps its sign and ``flag``
carries the direction (-1 negative, 1 otherwise).
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._code_utils import split_code
from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.mac_auction import MacAuctionPage

TYPE_MAC_AUCTION = command_code("mac_auction")

MAC_AUCTION_DEFAULT_COUNT = 500
_SYMBOL_WIDTH = 22
_RESERVED_WIDTH = 10
_MIN_PAYLOAD = 36
_ITEM_SIZE = 16

_FRAME_CONSTANTS_MODULE = "axdata_source_tdx._tdx_wire.protocol._frame_constants"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.mac_auction"
_BINARY_MODULE = "axdata_source_tdx._tdx_wire._binary"
_FRAME_CONSTANTS_EXPORTS = {"MAC_EX_PREFIX"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_MODEL_EXPORTS = {"MacAuctionItem", "MacAuctionPage"}
_BINARY_EXPORTS = {"decode_gbk_text", "little_f32", "little_u16", "little_u32"}


def _frame_constants():
    return import_module(_FRAME_CONSTANTS_MODULE)


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _binary():
    return import_module(_BINARY_MODULE)


def build_mac_auction_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    market_id, _, number = split_code(payload["code"])
    symbol = number.encode("ascii").ljust(_SYMBOL_WIDTH, b"\x00")
    start = _normalize_u32(payload.get("start", 0), "start")
    count = _normalize_u32(payload.get("count", 0) or MAC_AUCTION_DEFAULT_COUNT, "count")
    data = (
        market_id.to_bytes(2, "little", signed=False)
        + symbol
        + start.to_bytes(4, "little", signed=False)
        + count.to_bytes(4, "little", signed=False)
        + b"\x00" * _RESERVED_WIDTH
    )
    return RequestFrame(
        msg_id=msg_id,
        msg_type=TYPE_MAC_AUCTION,
        data=data,
        head=_frame_constants().MAC_EX_PREFIX,
    )


def parse_mac_auction_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> MacAuctionPage:
    request_payload = request_payload or {}
    payload = response.data
    if len(payload) < _MIN_PAYLOAD:
        raise _protocol_error()(f"invalid mac auction response length: {len(payload)}")

    binary = _binary()
    model = import_module(_MODEL_MODULE)
    market = binary.little_u16(payload[0:2])
    code = binary.decode_gbk_text(payload[2:24])
    count = binary.little_u32(payload[24:28])

    offset = _MIN_PAYLOAD
    items = []
    for index in range(count):
        if offset + _ITEM_SIZE > len(payload):
            raise _protocol_error()(f"invalid mac auction item {index}")
        record = payload[offset : offset + _ITEM_SIZE]
        offset += _ITEM_SIZE
        seconds = binary.little_u32(record[0:4])
        unmatched = int.from_bytes(record[12:16], "little", signed=True)
        time_text = (
            f"{(seconds // 3600) % 24:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
        )
        items.append(
            model.MacAuctionItem(
                time=time_text,
                price=float(binary.little_f32(record[4:8])),
                matched=binary.little_u32(record[8:12]),
                unmatched=unmatched,
                flag=-1 if unmatched < 0 else 1,
            )
        )

    return model.MacAuctionPage(
        market=market,
        code=code,
        count=count,
        items=tuple(items),
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
