"""MAC capital-flow (0x1218) command builder and parser.

Byte layout captured live against three MAC hosts on 2026-08-16 (all three
byte-identical); see plan axdata-integration/19 and the fixture under
``tests/fixtures/mac/``. The request frame is the same ``<BIBHHH`` layout as
the main station with ``head=0x02``; the response prefix matches
``PREFIX_RESP`` so the shared response decoder is reused unchanged.

This module is also the dispatch home for the second 0x1218 semantic,
``mac_symbol_belong_board`` (gotdx query constant ``Stock_GLHQ``, ``head=0x01``):
the builder routes on the request ``query`` payload key and the parser on the
query constant echoed at ``data[2:14]``; both delegate to
``protocol/commands/mac_symbol_belong_board.py``.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._code_utils import split_code
from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.mac_capital_flow import CapitalFlowSnapshot

TYPE_MAC_CAPITAL_FLOW = command_code("mac_capital_flow")

MAC_CAPITAL_FLOW_QUERY = b"Stock_ZJLX"
# gotdx proto/mac_symbol_belong_board.go：0x1218 同码的第二语义（query=Stock_GLHQ，
# head=0x01）。请求/响应分流都以此常量为判别式（响应在 data[2:14] 回显）。
MAC_SYMBOL_BELONG_BOARD_QUERY = "Stock_GLHQ"
_BELONG_BOARD_MODULE = "axdata_source_tdx._tdx_wire.protocol.commands.mac_symbol_belong_board"
_SYMBOL_WIDTH = 8
_RESERVED_WIDTH = 16
_QUERY_WIDTH = 21
_MIN_PAYLOAD = 27
_TODAY_VALUES = 4
_FIVE_DAY_VALUES = 6

_FRAME_CONSTANTS_MODULE = "axdata_source_tdx._tdx_wire.protocol._frame_constants"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.mac_capital_flow"
_FRAME_CONSTANTS_EXPORTS = {"MAC_PREFIX"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_MODEL_EXPORTS = {"CapitalFlowSnapshot"}


def _frame_constants():
    return import_module(_FRAME_CONSTANTS_MODULE)


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _snapshot_cls():
    return import_module(_MODEL_MODULE).CapitalFlowSnapshot


def build_mac_capital_flow_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    query = str(payload.get("query") or MAC_CAPITAL_FLOW_QUERY.decode("ascii"))
    if query == MAC_SYMBOL_BELONG_BOARD_QUERY:
        # 0x1218 同码双语义：股票所属板块（head=0x01、Stock_GLHQ）。
        return import_module(_BELONG_BOARD_MODULE).build_mac_symbol_belong_board_frame(
            payload, msg_id
        )
    market_id, _, number = split_code(payload["code"])
    symbol = number.encode("ascii").ljust(_SYMBOL_WIDTH, b"\x00")
    query = MAC_CAPITAL_FLOW_QUERY.ljust(_QUERY_WIDTH, b"\x00")
    data = (
        market_id.to_bytes(2, "little", signed=False)
        + symbol
        + b"\x00" * _RESERVED_WIDTH
        + query
    )
    return RequestFrame(
        msg_id=msg_id,
        msg_type=TYPE_MAC_CAPITAL_FLOW,
        data=data,
        head=_frame_constants().MAC_PREFIX,
    )


def parse_mac_capital_flow_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> CapitalFlowSnapshot:
    import json

    request_payload = request_payload or {}
    full_code = request_payload.get("code", "")
    payload = response.data
    if len(payload) < _MIN_PAYLOAD:
        raise _protocol_error()(f"invalid mac capital flow payload length: {len(payload)}")

    market = int.from_bytes(payload[0:2], "little", signed=False)
    query_info = payload[2:14].rstrip(b"\x00").decode("ascii", errors="replace")
    if query_info == MAC_SYMBOL_BELONG_BOARD_QUERY:
        # 0x1218 同码双语义：按响应回显的 query 常量分流到所属板块解析。
        return import_module(_BELONG_BOARD_MODULE).parse_mac_symbol_belong_board_payload(
            response, request_payload
        )
    ext = payload[19:27].hex()
    try:
        rows = json.loads(payload[_MIN_PAYLOAD:])
    except (ValueError, UnicodeDecodeError) as exc:
        raise _protocol_error()("invalid mac capital flow json rows") from exc
    if not isinstance(rows, list) or len(rows) < 2:
        raise _protocol_error()("mac capital flow expects two json rows")

    today = _floats(rows[0], _TODAY_VALUES, "today")
    five_day = _floats(rows[1], _FIVE_DAY_VALUES, "five-day")

    today_main_in, today_main_out, today_retail_in, today_retail_out = today
    (
        five_day_main_buy,
        five_day_main_sell,
        five_day_super_net,
        five_day_large_net,
        five_day_medium_net,
        five_day_small_net,
    ) = five_day

    return _snapshot_cls()(
        full_code=full_code,
        market=market,
        query_info=query_info,
        ext=ext,
        today_main_in=today_main_in,
        today_main_out=today_main_out,
        today_retail_in=today_retail_in,
        today_retail_out=today_retail_out,
        today_main_net=today_main_in - today_main_out,
        today_retail_net=today_retail_in - today_retail_out,
        five_day_main_buy=five_day_main_buy,
        five_day_main_sell=five_day_main_sell,
        five_day_super_net=five_day_super_net,
        five_day_large_net=five_day_large_net,
        five_day_medium_net=five_day_medium_net,
        five_day_small_net=five_day_small_net,
        five_day_main_net=five_day_main_buy - five_day_main_sell,
        raw_payload=payload if request_payload.get("include_raw") else b"",
    )


def _floats(row: Any, expected: int, label: str) -> list[float]:
    if not isinstance(row, list) or len(row) < expected:
        raise _protocol_error()(f"mac capital flow {label} row needs {expected} values")
    try:
        return [float(value) for value in row[:expected]]
    except (TypeError, ValueError) as exc:
        raise _protocol_error()(f"mac capital flow {label} row has non-numeric value") from exc


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
    return sorted(
        set(globals()) | _EXCEPTION_EXPORTS | _MODEL_EXPORTS | _FRAME_CONSTANTS_EXPORTS
    )
