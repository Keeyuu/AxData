"""MAC symbol bars (0x122E) command builder and parser.

Wire layout follows gotdx ``proto/mac_symbol_bars.go``. The request body is a
packed struct (46 bytes): ``<u16 market><code[22]><u16 period><u16 times>
<u32 start><u16 count><u16 adjust><i8 flag1><i8 flag2><i8 flag3>
<i8 flag4><u16 zero><reserved[4]>`` with gotdx defaults (times/flag1/flag2/
flag4 = 1, flag3 = 0). ``count`` is incremented by one at build time
(gotdx applyRequest does this unconditionally), so a payload ``count=1``
produces a frame count of 2.

The response carries ``count`` 36-byte bars; the first bar is the pre-close
seed and is discarded, so the page ``count`` is the header count minus one.
``pre_close``/``last_close`` chain from the previous bar's close (0.0 for
the first) and ``rise_price``/``rise_rate`` follow gotdx GetRisePrice/
GetRiseRate. ``turnover`` stays 0.0: gotdx's applyMACSymbolBarTurnover is a
client-layer post-processing step that is not ported. The optional 120-byte
summary is parsed when present (gotdx returns early when it is missing).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._code_utils import split_code
from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.mac_symbol_bars import MacSymbolBarsPage

TYPE_MAC_SYMBOL_BARS = command_code("mac_symbol_bars")

_SYMBOL_WIDTH = 22
_HEADER_LENGTH = 33
_BAR_LENGTH = 36
_SUMMARY_LENGTH = 120

_BINARY_MODULE = "axdata_source_tdx._tdx_wire._binary"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_FRAME_CONSTANTS_MODULE = "axdata_source_tdx._tdx_wire.protocol._frame_constants"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.mac_symbol_bars"
_COMMON_MODULE = "axdata_source_tdx._tdx_wire.protocol.commands.mac_common"
_BINARY_EXPORTS = {"decode_gbk_text", "little_f32", "little_u16", "little_u32"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_FRAME_CONSTANTS_EXPORTS = {"MAC_EX_PREFIX"}
_MODEL_EXPORTS = {"MacSymbolBar", "MacSymbolBarsPage"}


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _binary():
    return import_module(_BINARY_MODULE)


def _frame_constants():
    return import_module(_FRAME_CONSTANTS_MODULE)


def _mac_common():
    return import_module(_COMMON_MODULE)


def _bar_cls():
    return import_module(_MODEL_MODULE).MacSymbolBar


def _page_cls():
    return import_module(_MODEL_MODULE).MacSymbolBarsPage


def build_mac_symbol_bars_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    market_id, _, number = split_code(payload["code"])
    symbol = number.encode("ascii").ljust(_SYMBOL_WIDTH, b"\x00")
    period = int(payload.get("period", 4))
    times = int(payload.get("times", 1)) or 1
    start = int(payload.get("start", 0))
    count = int(payload.get("count", 800))
    adjust = int(payload.get("adjust", 0))
    flag1 = int(payload.get("flag1", 1)) or 1
    flag2 = int(payload.get("flag2", 1)) or 1
    flag4 = int(payload.get("flag4", 1)) or 1
    data = (
        market_id.to_bytes(2, "little", signed=False)
        + symbol
        + period.to_bytes(2, "little", signed=False)
        + times.to_bytes(2, "little", signed=False)
        + (start & 0xFFFFFFFF).to_bytes(4, "little", signed=False)
        + ((count + 1) & 0xFFFF).to_bytes(2, "little", signed=False)
        + adjust.to_bytes(2, "little", signed=False)
        + bytes([flag1 & 0xFF, flag2 & 0xFF, 0, flag4 & 0xFF])
        + (0).to_bytes(2, "little", signed=False)
        + b"\x00" * 4
    )
    return RequestFrame(
        msg_id=msg_id,
        msg_type=TYPE_MAC_SYMBOL_BARS,
        data=data,
        head=_frame_constants().MAC_EX_PREFIX,
    )


def parse_mac_symbol_bars_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> MacSymbolBarsPage:
    request_payload = request_payload or {}
    payload = response.data
    if len(payload) < _HEADER_LENGTH:
        raise _protocol_error()(f"invalid mac symbol bars payload length: {len(payload)}")

    binary = _binary()
    market = binary.little_u16(payload[0:2])
    code = binary.decode_gbk_text(payload[2:14])
    period = payload[24]
    unknown = binary.little_u16(payload[25:27])
    response_count = binary.little_u16(payload[27:29])
    start = binary.little_u32(payload[29:33])

    format_tdx_time = period < 4 or period == 7 or period == 8
    pos = _HEADER_LENGTH
    bar_cls = _bar_cls()
    pre_close = 0.0
    bars = []
    for index in range(response_count):
        if pos + _BAR_LENGTH > len(payload):
            raise _protocol_error()(f"truncated mac symbol bar item {index}")
        close = float(binary.little_f32(payload[pos + 20 : pos + 24]))
        open_price = float(binary.little_f32(payload[pos + 8 : pos + 12]))
        bars.append(
            bar_cls(
                datetime=_combine_mac_datetime(
                    binary.little_u32(payload[pos : pos + 4]),
                    binary.little_u32(payload[pos + 4 : pos + 8]),
                    format_tdx_time,
                ),
                open=open_price,
                high=float(binary.little_f32(payload[pos + 12 : pos + 16])),
                low=float(binary.little_f32(payload[pos + 16 : pos + 20])),
                close=close,
                amount=float(binary.little_f32(payload[pos + 24 : pos + 28])),
                vol=float(binary.little_f32(payload[pos + 28 : pos + 32])),
                float_shares=float(binary.little_f32(payload[pos + 32 : pos + 36])),
                turnover=0.0,
                pre_close=pre_close,
                last_close=pre_close,
                rise_price=_rise_price(close, open_price, pre_close),
                rise_rate=_rise_rate(close, open_price, pre_close),
            )
        )
        pre_close = close
        pos += _BAR_LENGTH

    result = [bar for bar in bars[1:]] if response_count > 0 else []
    page_count = response_count - 1 if response_count > 0 else 0

    summary = _empty_mac_summary()
    if pos + _SUMMARY_LENGTH <= len(payload):
        summary.update(_parse_mac_summary(binary, payload, pos))
    return _page_cls()(
        full_code=request_payload.get("code", ""),
        market=market,
        code=code,
        period=period,
        unknown=unknown,
        count=page_count,
        start=start,
        bars=tuple(result),
        raw_payload=payload if request_payload.get("include_raw") else b"",
        **summary,
    )


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


def _combine_mac_datetime(
    ymd: int, seconds: int, format_tdx_time: bool
) -> datetime | None:
    """Port of gotdx ``combineMACDateTime`` (naive; zero ymd -> None).

    Intraday/1-minute bars are timestamped with the following morning
    (TDX stores night session hours 0..5 on the previous day), so when the
    period needs TDX-style time formatting and the hour is <= 5, roll one
    day forward.
    """

    if ymd == 0:
        return None
    try:
        ts = datetime(
            ymd // 10000,
            (ymd % 10000) // 100,
            ymd % 100,
            seconds // 3600,
            (seconds % 3600) // 60,
        )
    except ValueError as exc:
        raise _protocol_error()(f"invalid mac symbol bar datetime: ymd={ymd}") from exc
    if format_tdx_time and ts.hour <= 5:
        return ts + timedelta(days=1)
    return ts


def _rise_price(close: float, open_price: float, pre_close: float) -> float:
    if pre_close == 0:
        return close - open_price
    return close - pre_close


def _rise_rate(close: float, open_price: float, pre_close: float) -> float:
    if pre_close == 0:
        if open_price == 0:
            return 0.0
        return (close - open_price) / open_price * 100.0
    return (close - pre_close) / pre_close * 100.0


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
