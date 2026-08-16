"""MAC quotes (0x122D) command builder and parser.

Wire layout follows gotdx ``proto/mac_quotes.go``. The request body is a
packed struct (38 bytes): ``<u16 market><code[22]><u16 zero1><u16 zero2>
<u16 one=1><u16 zero3..zero6>``. The ``query_date`` payload key (int
YYYYMMDD, default 0) is the N/A-equivalent "with date" variant of the same
command: when non-zero it is split across ``zero1``/``zero2``
(``query_date & 0xffff`` and ``query_date >> 16``), so the with-date frame
differs from the base frame only in those 4 bytes.

The response is the intraday chart followed by a 120-byte summary block.
gotdx only guards ``pos+109`` before reading 120 bytes; we tighten the guard
to the actual 120-byte read (documented divergence).
"""

from __future__ import annotations

from datetime import datetime
from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._code_utils import split_code
from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.mac_quotes import MacQuotesSnapshot

TYPE_MAC_QUOTES = command_code("mac_quotes")

_SYMBOL_WIDTH = 22
_HEADER_LENGTH = 35
_CHART_ITEM_LENGTH = 18
_SUMMARY_LENGTH = 120

_BINARY_MODULE = "axdata_source_tdx._tdx_wire._binary"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_FRAME_CONSTANTS_MODULE = "axdata_source_tdx._tdx_wire.protocol._frame_constants"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.mac_quotes"
_COMMON_MODULE = "axdata_source_tdx._tdx_wire.protocol.commands.mac_common"
_BINARY_EXPORTS = {"decode_gbk_text", "little_f32", "little_u16", "little_u32"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_FRAME_CONSTANTS_EXPORTS = {"MAC_EX_PREFIX"}
_MODEL_EXPORTS = {"MacQuoteChartItem", "MacQuotesSnapshot"}


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _binary():
    return import_module(_BINARY_MODULE)


def _frame_constants():
    return import_module(_FRAME_CONSTANTS_MODULE)


def _mac_common():
    return import_module(_COMMON_MODULE)


def _chart_item_cls():
    return import_module(_MODEL_MODULE).MacQuoteChartItem


def _snapshot_cls():
    return import_module(_MODEL_MODULE).MacQuotesSnapshot


def build_mac_quotes_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    market_id, _, number = split_code(payload["code"])
    symbol = number.encode("ascii").ljust(_SYMBOL_WIDTH, b"\x00")
    query_date = int(payload.get("query_date") or 0)
    zero1 = query_date & 0xFFFF
    zero2 = (query_date >> 16) & 0xFFFF
    data = (
        market_id.to_bytes(2, "little", signed=False)
        + symbol
        + zero1.to_bytes(2, "little", signed=False)
        + zero2.to_bytes(2, "little", signed=False)
        + (1).to_bytes(2, "little", signed=False)
        + b"\x00" * 8
    )
    return RequestFrame(
        msg_id=msg_id,
        msg_type=TYPE_MAC_QUOTES,
        data=data,
        head=_frame_constants().MAC_EX_PREFIX,
    )


def parse_mac_quotes_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> MacQuotesSnapshot:
    request_payload = request_payload or {}
    payload = response.data
    if len(payload) < _HEADER_LENGTH:
        raise _protocol_error()(f"invalid mac quotes payload length: {len(payload)}")

    binary = _binary()
    market = binary.little_u16(payload[0:2])
    code = binary.decode_gbk_text(payload[2:24])
    date = binary.little_u32(payload[24:28])
    unknown = payload[28]
    price = float(binary.little_f32(payload[29:33]))
    count = binary.little_u16(payload[33:35])

    pos = _HEADER_LENGTH
    chart_item = _chart_item_cls()
    items = []
    for index in range(count):
        if pos + _CHART_ITEM_LENGTH > len(payload):
            raise _protocol_error()(f"truncated mac quote chart item {index}")
        minutes = binary.little_u16(payload[pos : pos + 2])
        items.append(
            chart_item(
                time=f"{minutes // 60 % 24:02d}:{minutes % 60:02d}:00",
                price=float(binary.little_f32(payload[pos + 2 : pos + 6])),
                avg=float(binary.little_f32(payload[pos + 6 : pos + 10])),
                vol=binary.little_u32(payload[pos + 10 : pos + 14]),
                momentum=float(binary.little_f32(payload[pos + 14 : pos + 18])),
            )
        )
        pos += _CHART_ITEM_LENGTH

    if pos + _SUMMARY_LENGTH > len(payload):
        raise _protocol_error()(
            f"invalid mac quotes summary length: {len(payload) - pos}"
        )

    summary = _parse_mac_summary(binary, payload, pos)
    return _snapshot_cls()(
        full_code=request_payload.get("code", ""),
        market=market,
        code=code,
        date=date,
        unknown=unknown,
        price=price,
        count=count,
        chart=tuple(items),
        raw_payload=payload if request_payload.get("include_raw") else b"",
        **summary,
    )


def _parse_mac_summary(binary, payload: bytes, pos: int) -> dict[str, Any]:
    """Parse the 120-byte summary block shared by quotes/bars/tick-charts.

    Layout (gotdx): name gbk[0:44], decimal u8@44, category u16@45,
    vol_unit f32@47, 5-byte hole, date u32@56, time u32@60, pre_close/open/
    high/low/close/momentum f32@64..88, vol u32@88, amount f32@92, 12-byte
    hole, turnover f32@108, avg f32@112, industry u32@116.
    """

    summary = {
        "name": binary.decode_gbk_text(payload[pos : pos + 44]),
        "decimal": payload[pos + 44],
        "category": binary.little_u16(payload[pos + 45 : pos + 47]),
        "vol_unit": float(binary.little_f32(payload[pos + 47 : pos + 51])),
        "datetime": _format_mac_quote_datetime(
            binary.little_u32(payload[pos + 56 : pos + 60]),
            binary.little_u32(payload[pos + 60 : pos + 64]),
        ),
        "pre_close": float(binary.little_f32(payload[pos + 64 : pos + 68])),
        "open": float(binary.little_f32(payload[pos + 68 : pos + 72])),
        "high": float(binary.little_f32(payload[pos + 72 : pos + 76])),
        "low": float(binary.little_f32(payload[pos + 76 : pos + 80])),
        "close": float(binary.little_f32(payload[pos + 80 : pos + 84])),
        "momentum": float(binary.little_f32(payload[pos + 84 : pos + 88])),
        "vol": binary.little_u32(payload[pos + 88 : pos + 92]),
        "amount": float(binary.little_f32(payload[pos + 92 : pos + 96])),
        "turnover": float(binary.little_f32(payload[pos + 108 : pos + 112])),
        "avg": float(binary.little_f32(payload[pos + 112 : pos + 116])),
    }
    industry = binary.little_u32(payload[pos + 116 : pos + 120])
    summary["industry"] = industry
    summary["industry_code"] = _mac_common().mac_industry_board_symbol(industry)
    return summary


def _format_mac_quote_datetime(date_raw: int, time_raw: int) -> datetime | None:
    """Port of gotdx ``formatMACQuoteDateTime`` (naive, no tz).

    A zero date yields None: gotdx feeds year 0 through Go's time package
    (normalized to an odd epoch-like value); Python has no year 0, so the
    empty date is represented as None (documented divergence).
    """

    if date_raw == 0:
        return None
    try:
        return datetime(
            date_raw // 10000,
            (date_raw % 10000) // 100,
            date_raw % 100,
            time_raw // 10000,
            (time_raw % 10000) // 100,
            time_raw % 100,
        )
    except ValueError as exc:
        raise _protocol_error()(f"invalid mac quote datetime: date={date_raw}") from exc


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
