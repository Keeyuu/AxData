"""MAC symbol-belong-board (0x1218 Stock_GLHQ) command builder and parser.

This is the second semantic of the 0x1218 command code (shared with capital
flow, gotdx proto/mac_symbol_belong_board.go): the request is
``<u16 market><symbol[8]><reserved[16]><query[21]="Stock_GLHQ">`` with head
byte 0x01 (unlike capital flow's head 0x02). The response carries the market,
the echoed query and a GBK-encoded JSON array of rows; each row is decoded
per its column count (9-column and 13-column schemas are known).

The module is invoked through the 0x1218 route in
``protocol/commands/mac_capital_flow.py`` and registers no dispatch entry of
its own.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._code_utils import split_code
from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.mac_symbol_belong_board import (
        MacSymbolBelongBoardList,
    )

TYPE_MAC_SYMBOL_BELONG_BOARD = command_code("mac_symbol_belong_board")

# gotdx NewMACSymbolBelongBoard 默认 query 常量。
MAC_SYMBOL_BELONG_BOARD_QUERY = "Stock_GLHQ"
_SYMBOL_WIDTH = 8
_RESERVED_WIDTH = 16
_QUERY_WIDTH = 21
_QUERY_ECHO_WIDTH = 12
_MIN_PAYLOAD = 27
_MIN_ROW_COLUMNS = 9
_SCHEMA_NINE = 9
_SCHEMA_THIRTEEN = 13

_BINARY_MODULE = "axdata_source_tdx._tdx_wire._binary"
_FRAME_CONSTANTS_MODULE = "axdata_source_tdx._tdx_wire.protocol._frame_constants"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.mac_symbol_belong_board"
_BINARY_EXPORTS = {"decode_gbk_text"}
_FRAME_CONSTANTS_EXPORTS = {"MAC_EX_PREFIX"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_MODEL_EXPORTS = {"MacBelongBoardItem", "MacSymbolBelongBoardList"}


def _frame_constants():
    return import_module(_FRAME_CONSTANTS_MODULE)


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _binary():
    return import_module(_BINARY_MODULE)


def _model_module():
    return import_module(_MODEL_MODULE)


def build_mac_symbol_belong_board_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    payload = payload or {}
    market_id, _, number = split_code(payload["code"])
    symbol = number.encode("ascii").ljust(_SYMBOL_WIDTH, b"\x00")
    query = str(payload.get("query") or MAC_SYMBOL_BELONG_BOARD_QUERY)
    data = (
        market_id.to_bytes(2, "little", signed=False)
        + symbol
        + b"\x00" * _RESERVED_WIDTH
        + query.encode("ascii").ljust(_QUERY_WIDTH, b"\x00")
    )
    return RequestFrame(
        msg_id=msg_id,
        msg_type=TYPE_MAC_SYMBOL_BELONG_BOARD,
        data=data,
        head=_frame_constants().MAC_EX_PREFIX,
    )


def parse_mac_symbol_belong_board_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> MacSymbolBelongBoardList:
    import json

    request_payload = request_payload or {}
    payload = response.data
    if len(payload) < _MIN_PAYLOAD:
        raise _protocol_error()(f"invalid mac belong board payload length: {len(payload)}")

    binary = _binary()
    market = _little_u16(payload[0:2])
    query = binary.decode_gbk_text(payload[2 : 2 + _QUERY_ECHO_WIDTH])
    try:
        rows = json.loads(binary.decode_gbk_text(payload[_MIN_PAYLOAD:]))
    except (ValueError, UnicodeDecodeError) as exc:
        raise _protocol_error()("invalid mac belong board json rows") from exc
    if not isinstance(rows, list):
        raise _protocol_error()("mac belong board expects a json list")

    item_cls = _model_module().MacBelongBoardItem
    items = []
    for row in rows:
        if not isinstance(row, list) or len(row) < _MIN_ROW_COLUMNS:
            continue
        columns = len(row)
        fields = {
            "board_type": _any_to_string(row[0]),
            "market_code": _any_to_int(row[1]),
            "status_code": _any_to_int(row[1]),
            "board_code": _any_to_string(row[2]),
            "board_name": _any_to_string(row[3]),
            "price": _any_to_float(row[4]),
            "pre_close": _any_to_float(row[5]),
            "schema_columns": columns,
            "limit_up_count": 0.0,
            "limit_down_count": 0.0,
            "most_similar": 0.0,
            "speed_pct": 0.0,
            "symbol_market": 0,
            "symbol": "",
            "symbol_name": "",
            "symbol_close": 0.0,
            "symbol_pre_close": 0.0,
            "symbol_speed_pct": 0.0,
            "metric1": 0.0,
            "metric2": 0.0,
            "metric3": 0.0,
        }
        if columns == _SCHEMA_NINE:
            limit_up_count = _any_to_float(row[6])
            limit_down_count = _any_to_float(row[7])
            most_similar = _any_to_float(row[8])
            fields.update(
                limit_up_count=limit_up_count,
                limit_down_count=limit_down_count,
                most_similar=most_similar,
                metric1=limit_up_count,
                metric2=limit_down_count,
                metric3=most_similar,
            )
        elif columns == _SCHEMA_THIRTEEN:
            speed_pct = _any_to_float(row[6])
            symbol_close = _any_to_float(row[10])
            symbol_speed_pct = _any_to_float(row[12])
            fields.update(
                speed_pct=speed_pct,
                symbol_market=_any_to_int(row[7]),
                symbol=_any_to_string(row[8]),
                symbol_name=_any_to_string(row[9]),
                symbol_close=symbol_close,
                symbol_pre_close=_any_to_float(row[11]),
                symbol_speed_pct=symbol_speed_pct,
                metric1=speed_pct,
                metric2=symbol_close,
                metric3=symbol_speed_pct,
            )
        else:
            fields.update(
                metric1=_any_to_float(row[6]),
                metric2=_any_to_float(row[7]),
                metric3=_any_to_float(row[8]),
            )
        items.append(item_cls(**fields))

    return _model_module().MacSymbolBelongBoardList(
        market=market,
        query=query,
        items=tuple(items),
        raw_payload=payload if request_payload.get("include_raw") else b"",
    )


def _any_to_string(value: Any) -> str:
    """Port of gotdx anyToString (proto/mac_symbol_belong_board.go)."""

    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        # strconv.FormatFloat 'f' -1：整数 float 无小数点，无科学计数。
        if value.is_integer():
            return str(int(value))
        return format(value, "f").rstrip("0").rstrip(".")
    if isinstance(value, int):
        return str(value)
    return str(value)


def _any_to_int(value: Any) -> int:
    """Port of gotdx anyToInt: str/float/int 都收，失败给 0。"""

    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _any_to_float(value: Any) -> float:
    """Port of gotdx anyToFloat64: str/float/int 都收，失败给 0.0。"""

    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _little_u16(data: bytes) -> int:
    return int.from_bytes(data, "little", signed=False)


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
