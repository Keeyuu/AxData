"""Top-board ranking (0x053F) command builder and parser.

Wire layout follows gotdx ``proto/get_top_board.go``: the request body is
``<u8 category><u8 mode><reserved[7]><u8 size>`` with gotdx defaults
(mode=5, size=20, reserved=``00 00 00 00 01 00 00``); the response is one
``u8 size`` byte followed by nine board lists of ``size`` 15-byte rows
(``<u8 market><code[6]><f32 price><f32 value>``) in gotdx's fixed order.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire._market import ID_TO_MARKET
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.board import TopBoardPage

TYPE_TOP_BOARD = command_code("top_board")

TOP_BOARD_RESERVED = bytes([0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00])
TOP_BOARD_DEFAULT_MODE = 5
TOP_BOARD_DEFAULT_SIZE = 20
TOP_BOARD_ITEM_SIZE = 15
TOP_BOARD_BOARD_NAMES = (
    "increase",
    "decrease",
    "amplitude",
    "rise_speed",
    "fall_speed",
    "vol_ratio",
    "pos_commission_ratio",
    "neg_commission_ratio",
    "turnover",
)

_BINARY_MODULE = "axdata_source_tdx._tdx_wire._binary"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.board"
_BINARY_EXPORTS = {"decode_gbk_text", "little_f32"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_MODEL_EXPORTS = {"TopBoardItem", "TopBoardPage"}


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _binary():
    return import_module(_BINARY_MODULE)


def build_top_board_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    category = _normalize_u8(payload.get("category", 0), "category")
    mode = _normalize_u8(payload.get("mode", TOP_BOARD_DEFAULT_MODE), "mode")
    size = _normalize_u8(payload.get("size", TOP_BOARD_DEFAULT_SIZE), "size")
    reserved = payload.get("reserved_raw", TOP_BOARD_RESERVED)
    if not isinstance(reserved, (bytes, bytearray)) or len(reserved) != 7:
        raise _protocol_error()("reserved_raw must be 7 bytes")
    data = (
        category.to_bytes(1, "little", signed=False)
        + mode.to_bytes(1, "little", signed=False)
        + bytes(reserved)
        + size.to_bytes(1, "little", signed=False)
    )
    return RequestFrame(msg_id=msg_id, msg_type=TYPE_TOP_BOARD, data=data)


def parse_top_board_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> TopBoardPage:
    request_payload = request_payload or {}
    payload = response.data
    if len(payload) < 1:
        raise _protocol_error()("invalid top board payload")

    binary = _binary()
    item_cls = import_module(_MODEL_MODULE).TopBoardItem
    size = payload[0]
    expected_length = 1 + len(TOP_BOARD_BOARD_NAMES) * size * TOP_BOARD_ITEM_SIZE
    if len(payload) < expected_length:
        raise _protocol_error()(
            f"truncated top board payload: expected {expected_length}, got {len(payload)}"
        )

    offset = 1
    boards: dict[str, list] = {name: [] for name in TOP_BOARD_BOARD_NAMES}
    for name in TOP_BOARD_BOARD_NAMES:
        for _ in range(size):
            record = payload[offset : offset + TOP_BOARD_ITEM_SIZE]
            offset += TOP_BOARD_ITEM_SIZE
            market_id = record[0]
            boards[name].append(
                item_cls(
                    market_id=market_id,
                    exchange=ID_TO_MARKET.get(market_id, ""),
                    code=binary.decode_gbk_text(record[1:7]),
                    price=float(binary.little_f32(record[7:11])),
                    value=float(binary.little_f32(record[11:15])),
                )
            )

    return import_module(_MODEL_MODULE).TopBoardPage(
        size=size,
        **{name: tuple(items) for name, items in boards.items()},
        raw_payload=payload if request_payload.get("include_raw") else b"",
    )


def _normalize_u8(value: Any, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise _protocol_error()(f"{name} must be an integer") from exc
    if parsed < 0 or parsed > 0xFF:
        raise _protocol_error()(f"{name} must be between 0 and 255")
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
