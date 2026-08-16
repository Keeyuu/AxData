"""MAC extended board list & count (0x1231) command builder and parser.

Wire layout follows gotdx ``proto/mac_board.go``. board_count and board_list
share ``KMSG_EXBOARDLIST`` and an identical 18-byte request body; the count
semantic only reads the 4-byte response head (``count_all``/``total``). The
builder routes on the request ``count_only`` payload key but emits exactly the
same frame either way; the parser routes on the same key and skips row parsing
when ``count_only`` is set (gotdx ``MACBoardCount.ParseResponse``).
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.mac_board import MacBoardListPage

TYPE_MAC_BOARD_LIST = command_code("mac_board_list")

MAC_BOARD_DEFAULT_PAGE_SIZE = 150
MAC_BOARD_ITEM_SIZE = 160

_BINARY_MODULE = "axdata_source_tdx._tdx_wire._binary"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.mac_board"
_FRAME_CONSTANTS_MODULE = "axdata_source_tdx._tdx_wire.protocol._frame_constants"
_BINARY_EXPORTS = {"decode_gbk_text", "little_f32", "little_u16"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_MODEL_EXPORTS = {"MacBoardListItem", "MacBoardListPage"}
_FRAME_CONSTANTS_EXPORTS = {"MAC_EX_PREFIX"}


def _frame_constants():
    return import_module(_FRAME_CONSTANTS_MODULE)


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _binary():
    return import_module(_BINARY_MODULE)


def build_mac_board_list_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    """Build the 0x1231 board-list/count request frame (head=0x01, 18 bytes)."""
    page_size = _normalize_u16(payload.get("page_size", 0), "page_size")
    if page_size == 0:
        page_size = MAC_BOARD_DEFAULT_PAGE_SIZE
    board_type = _normalize_u16(payload.get("board_type", 0), "board_type")
    sort_order = _normalize_u8(payload.get("sort_order", 1), "sort_order")
    if sort_order == 0:
        sort_order = 1
    start = _normalize_u16(payload.get("start", 0), "start")
    data = (
        page_size.to_bytes(2, "little", signed=False)
        + board_type.to_bytes(2, "little", signed=False)
        + b"\x00"  # SortType u8, gotdx default 0
        + sort_order.to_bytes(1, "little", signed=False)
        + start.to_bytes(2, "little", signed=False)
        + b"\x01\x00"  # One u16, gotdx default 1
        + b"\x00" * 8  # Reserved[8]
    )
    return RequestFrame(
        msg_id=msg_id,
        msg_type=TYPE_MAC_BOARD_LIST,
        data=data,
        head=_frame_constants().MAC_EX_PREFIX,
    )


def parse_mac_board_list_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> MacBoardListPage:
    request_payload = request_payload or {}
    count_only = bool(request_payload.get("count_only"))
    payload = response.data
    if len(payload) < 4:
        raise _protocol_error()(f"invalid mac board list payload length: {len(payload)}")

    binary = _binary()
    count_all = binary.little_u16(payload[:2])
    total = binary.little_u16(payload[2:4])

    model_module = import_module(_MODEL_MODULE)
    raw_payload = payload if request_payload.get("include_raw") else b""
    if count_only:
        # gotdx MACBoardCount：只消费 4 字节头，不要求后续字节。
        return model_module.MacBoardListPage(
            count_all=count_all,
            total=total,
            count=0,
            rows=(),
            raw_payload=raw_payload,
        )

    count = count_all // 2
    if count == 0 and count_all > 0:
        count = count_all

    item_cls = model_module.MacBoardListItem
    rows = []
    offset = 4
    for _ in range(count):
        if offset + MAC_BOARD_ITEM_SIZE > len(payload):
            raise _protocol_error()(f"truncated mac board list item at offset {offset}")
        record = payload[offset : offset + MAC_BOARD_ITEM_SIZE]
        rows.append(
            item_cls(
                market=binary.little_u16(record[0:2]),
                code=binary.decode_gbk_text(record[2:8]),
                name=binary.decode_gbk_text(record[24:68]),
                price=float(binary.little_f32(record[68:72])),
                rise_speed=float(binary.little_f32(record[72:76])),
                pre_close=float(binary.little_f32(record[76:80])),
                symbol_market=binary.little_u16(record[80:82]),
                symbol_code=binary.decode_gbk_text(record[82:88]),
                symbol_name=binary.decode_gbk_text(record[104:148]),
                symbol_price=float(binary.little_f32(record[148:152])),
                symbol_rise_speed=float(binary.little_f32(record[152:156])),
                symbol_pre_close=float(binary.little_f32(record[156:160])),
            )
        )
        offset += MAC_BOARD_ITEM_SIZE

    return model_module.MacBoardListPage(
        count_all=count_all,
        total=total,
        count=count,
        rows=tuple(rows),
        raw_payload=raw_payload,
    )


def _normalize_u8(value: Any, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise _protocol_error()(f"{name} must be an integer") from exc
    if parsed < 0 or parsed > 0xFF:
        raise _protocol_error()(f"{name} must be between 0 and 255")
    return parsed


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
