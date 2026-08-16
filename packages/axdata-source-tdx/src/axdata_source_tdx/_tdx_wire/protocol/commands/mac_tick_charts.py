"""MAC multi-day tick charts (0x123E) command builder and parser.

Wire layout follows gotdx ``proto/mac_tick_charts.go``. The request body is a
packed struct (38 bytes): ``<u16 market><code[22]><u32 query_date><u16 days>
<u16 one=1><reserved[6]>`` with default days=5. The ``query_date`` payload
key is an explicit field of the base request structure (same N/A-equivalent
treatment as mac_transactions).

The response carries five date/pre-close day slots, then ``total`` 14-byte
ticks. Ticks are split into days with gotdx's algorithm: while the next
tick's minute is <= the current tick's minute, start a new day; the day
index bounds the dates/pre-closes arrays (missing day slots get date=""
and pre_close=0.0); trailing days are padded with empty entries. The
optional 120-byte summary is parsed when present (gotdx returns early when
it is missing).
"""

from __future__ import annotations

from datetime import datetime
from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._code_utils import split_code
from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.mac_tick_charts import MacTickChartsPage

TYPE_MAC_TICK_CHARTS = command_code("mac_tick_charts")

_SYMBOL_WIDTH = 22
_HEADER_LENGTH = 71
_TICK_LENGTH = 14
_SUMMARY_LENGTH = 120
_DAY_SLOTS = 5

_BINARY_MODULE = "axdata_source_tdx._tdx_wire._binary"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_FRAME_CONSTANTS_MODULE = "axdata_source_tdx._tdx_wire.protocol._frame_constants"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.mac_tick_charts"
_COMMON_MODULE = "axdata_source_tdx._tdx_wire.protocol.commands.mac_common"
_BINARY_EXPORTS = {"decode_gbk_text", "little_f32", "little_u16", "little_u32"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_FRAME_CONSTANTS_EXPORTS = {"MAC_EX_PREFIX"}
_MODEL_EXPORTS = {"MacTickChartDay", "MacTickChartItem", "MacTickChartsPage"}


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _binary():
    return import_module(_BINARY_MODULE)


def _frame_constants():
    return import_module(_FRAME_CONSTANTS_MODULE)


def _mac_common():
    return import_module(_COMMON_MODULE)


def _day_cls():
    return import_module(_MODEL_MODULE).MacTickChartDay


def _item_cls():
    return import_module(_MODEL_MODULE).MacTickChartItem


def _page_cls():
    return import_module(_MODEL_MODULE).MacTickChartsPage


def build_mac_tick_charts_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    market_id, _, number = split_code(payload["code"])
    symbol = number.encode("ascii").ljust(_SYMBOL_WIDTH, b"\x00")
    query_date = int(payload.get("query_date") or 0) & 0xFFFFFFFF
    days = int(payload.get("days", 5)) or 5
    data = (
        market_id.to_bytes(2, "little", signed=False)
        + symbol
        + query_date.to_bytes(4, "little", signed=False)
        + (days & 0xFFFF).to_bytes(2, "little", signed=False)
        + (1).to_bytes(2, "little", signed=False)
        + b"\x00" * 6
    )
    return RequestFrame(
        msg_id=msg_id,
        msg_type=TYPE_MAC_TICK_CHARTS,
        data=data,
        head=_frame_constants().MAC_EX_PREFIX,
    )


def parse_mac_tick_charts_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> MacTickChartsPage:
    request_payload = request_payload or {}
    payload = response.data
    if len(payload) < _HEADER_LENGTH:
        raise _protocol_error()(f"invalid mac tick charts payload length: {len(payload)}")

    binary = _binary()
    market = binary.little_u16(payload[0:2])
    code = binary.decode_gbk_text(payload[2:24])

    dates = [
        binary.little_u32(payload[24 + index * 4 : 28 + index * 4])
        for index in range(_DAY_SLOTS)
    ]
    pre_closes = [
        float(binary.little_f32(payload[44 + index * 4 : 48 + index * 4]))
        for index in range(_DAY_SLOTS)
    ]

    count = binary.little_u16(payload[64:66])
    send_last = payload[66]
    page_size = binary.little_u16(payload[67:69])
    total = binary.little_u16(payload[69:71])

    pos = _HEADER_LENGTH
    item_cls = _item_cls()
    ticks = []
    for index in range(total):
        if pos + _TICK_LENGTH > len(payload):
            raise _protocol_error()(f"truncated mac tick charts item {index}")
        minutes = binary.little_u16(payload[pos : pos + 2])
        ticks.append(
            (
                minutes,
                item_cls(
                    time=f"{minutes // 60 % 24:02d}:{minutes % 60:02d}:00",
                    price=float(binary.little_f32(payload[pos + 2 : pos + 6])),
                    avg=float(binary.little_f32(payload[pos + 6 : pos + 10])),
                    vol=binary.little_u16(payload[pos + 10 : pos + 12]),
                    unknown=binary.little_u16(payload[pos + 12 : pos + 14]),
                ),
            )
        )
        pos += _TICK_LENGTH

    charts = _split_tick_days(ticks, dates, pre_closes, count)

    summary = _empty_mac_summary()
    if pos + _SUMMARY_LENGTH <= len(payload):
        summary.update(_parse_mac_summary(binary, payload, pos))
    return _page_cls()(
        full_code=request_payload.get("code", ""),
        market=market,
        code=code,
        count=count,
        send_last=send_last,
        page_size=page_size,
        total=total,
        charts=tuple(charts),
        raw_payload=payload if request_payload.get("include_raw") else b"",
        **summary,
    )


def _split_tick_days(ticks, dates: list[int], pre_closes: list[float], count: int) -> list:
    """Port of gotdx's MACTickCharts day-splitting loop.

    Ticks accumulate into the current day; when more days remain and the
    next tick's minute is <= the current one, the current day is closed and
    a new day starts. Trailing day slots are padded with empty days.
    """

    day_cls = _day_cls()
    if count == 0:
        return []

    def new_day(day_index: int, day_ticks) -> list:
        if day_index < len(dates) and dates[day_index] != 0:
            return day_cls(
                date=_format_mac_date(dates[day_index]),
                pre_close=pre_closes[day_index],
                ticks=tuple(day_ticks),
            )
        return day_cls(date="", pre_close=0.0, ticks=tuple(day_ticks))

    charts = []
    current_day = 0
    day_ticks = []
    for index, (minute, item) in enumerate(ticks):
        day_ticks.append(item)
        if current_day >= count - 1:
            continue
        if index + 1 < len(ticks) and ticks[index + 1][0] <= minute:
            charts.append(new_day(current_day, day_ticks))
            current_day += 1
            day_ticks = []
    charts.append(new_day(current_day, day_ticks))
    while len(charts) < count:
        charts.append(new_day(len(charts), []))
    return charts


def _format_mac_date(raw: int) -> str:
    """Port of gotdx ``formatMACDate`` ("2006-01-02")."""

    return f"{raw // 10000:04d}-{raw % 10000 // 100:02d}-{raw % 100:02d}"


def _parse_mac_summary(binary, payload: bytes, pos: int) -> dict[str, Any]:
    """Parse the 120-byte summary block (same layout as mac_quotes)."""

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


def _empty_mac_summary() -> dict[str, Any]:
    return {
        "name": "",
        "decimal": 0,
        "category": 0,
        "vol_unit": 0.0,
        "datetime": None,
        "pre_close": 0.0,
        "open": 0.0,
        "high": 0.0,
        "low": 0.0,
        "close": 0.0,
        "momentum": 0.0,
        "vol": 0,
        "amount": 0.0,
        "turnover": 0.0,
        "avg": 0.0,
        "industry": 0,
        "industry_code": "",
    }


def _format_mac_quote_datetime(date_raw: int, time_raw: int) -> datetime | None:
    """Port of gotdx ``formatMACQuoteDateTime`` (naive; zero date -> None)."""

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
