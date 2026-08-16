"""Index info (0x051D) and index momentum (0x051C) command builders/parsers.

Wire layouts follow gotdx ``proto/get_index_info.go`` and
``proto/get_index_momentum.go``: index-info requests are
``<u16 market><code[6]><u32 zero>`` and replies mix fixed fields with
``getprice`` varints plus trailing cumulative order rows; momentum requests
are ``<u16 market><code[6]>`` and replies are ``<u16 count>`` plus one varint
delta per point accumulated into running values.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._code_utils import split_code
from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.index import IndexInfoSnapshot, IndexMomentumSeries

TYPE_INDEX_INFO = command_code("index_info")
TYPE_INDEX_MOMENTUM = command_code("index_momentum")

_BINARY_MODULE = "axdata_source_tdx._tdx_wire._binary"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.index"
_BINARY_EXPORTS = {"consume_tdx_signed_varint", "decode_gbk_text", "little_f32", "little_u32"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_MODEL_EXPORTS = {"IndexInfoOrder", "IndexInfoSnapshot", "IndexMomentumSeries"}


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _binary():
    return import_module(_BINARY_MODULE)


def build_index_info_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    market_id, _, number = split_code(payload["code"])
    data = (
        market_id.to_bytes(2, "little", signed=False)
        + number.encode("ascii")
        + (0).to_bytes(4, "little", signed=False)
    )
    return RequestFrame(msg_id=msg_id, msg_type=TYPE_INDEX_INFO, data=data)


def build_index_momentum_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    market_id, _, number = split_code(payload["code"])
    data = market_id.to_bytes(2, "little", signed=False) + number.encode("ascii")
    return RequestFrame(msg_id=msg_id, msg_type=TYPE_INDEX_MOMENTUM, data=data)


def parse_index_info_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> IndexInfoSnapshot:
    request_payload = request_payload or {}
    requested_code = request_payload.get("code", "sh000001")
    market_id, exchange, number = split_code(requested_code)
    payload = response.data
    if len(payload) < 15:
        raise _protocol_error()("invalid index info payload")

    binary = _binary()
    order_count = binary.little_u32(payload[0:4])
    market = payload[4]
    code = binary.decode_gbk_text(payload[5:11])
    active = binary.little_u16(payload[11:13])

    offset = 13
    close_raw, offset = _varint(payload, offset)
    pre_close_diff, offset = _varint(payload, offset)
    open_diff, offset = _varint(payload, offset)
    high_diff, offset = _varint(payload, offset)
    low_diff, offset = _varint(payload, offset)
    server_time_raw, offset = _varint(payload, offset)
    after_hour, offset = _varint(payload, offset)
    vol, offset = _varint(payload, offset)
    cur_vol, offset = _varint(payload, offset)
    if offset + 4 > len(payload):
        raise _protocol_error()("truncated index info amount")
    amount = float(binary.little_f32(payload[offset : offset + 4]))
    offset += 4

    for _ in range(2):
        _, offset = _varint(payload, offset)
    open_amount, offset = _varint(payload, offset)
    for _ in range(4):
        _, offset = _varint(payload, offset)
    up_count, offset = _varint(payload, offset)
    down_count, offset = _varint(payload, offset)
    for _ in range(9):
        _, offset = _varint(payload, offset)

    order_cls = import_module(_MODEL_MODULE).IndexInfoOrder
    orders = []
    last_price = 0
    for _ in range(order_count):
        price_raw, offset = _varint(payload, offset)
        unknown, offset = _varint(payload, offset)
        order_vol, offset = _varint(payload, offset)
        last_price += price_raw
        orders.append(
            order_cls(
                price=last_price / 100.0,
                unknown=unknown,
                vol=order_vol,
            )
        )

    return import_module(_MODEL_MODULE).IndexInfoSnapshot(
        order_count=order_count,
        market_id=market,
        exchange=exchange,
        code=code or number,
        active=active,
        close=close_raw / 100.0,
        pre_close=(close_raw + pre_close_diff) / 100.0,
        diff=-pre_close_diff / 100.0,
        open=(close_raw + open_diff) / 100.0,
        high=(close_raw + high_diff) / 100.0,
        low=(close_raw + low_diff) / 100.0,
        server_time=format_server_time(server_time_raw),
        after_hour=after_hour,
        vol=vol,
        cur_vol=cur_vol,
        amount=amount,
        open_amount=open_amount,
        up_count=up_count,
        down_count=down_count,
        orders=tuple(orders),
        raw_payload=payload if request_payload.get("include_raw") else b"",
    )


def parse_index_momentum_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> IndexMomentumSeries:
    request_payload = request_payload or {}
    requested_code = request_payload.get("code", "sh000001")
    market_id, exchange, number = split_code(requested_code)
    payload = response.data
    if len(payload) < 2:
        raise _protocol_error()("invalid index momentum payload")

    binary = _binary()
    count = binary.little_u16(payload[:2])
    offset = 2
    values = []
    start_momentum = 0
    for _ in range(count):
        momentum, offset = _varint(payload, offset)
        start_momentum += momentum
        values.append(start_momentum)

    return import_module(_MODEL_MODULE).IndexMomentumSeries(
        market_id=market_id,
        exchange=exchange,
        code=number,
        count=count,
        values=tuple(values),
        raw_payload=payload if request_payload.get("include_raw") else b"",
    )


def format_server_time(raw: int) -> str:
    """Port of gotdx ``formatServerTime`` (proto/proto.go)."""

    if raw == 0 or raw == 100:
        return "00:00:00.000"

    minutes_field = (raw // 10000) % 100
    if minutes_field < 60:
        hours = raw // 1000000
        minutes = minutes_field
        seconds_millis = (raw % 10000) * 60 / 10000.0
    else:
        total = (raw % 1000000) * 60 / 1000000.0
        hours = raw // 1000000
        minutes = int(total / 60)
        seconds_millis = total - minutes * 60
    seconds = int(seconds_millis)
    millis = int((seconds_millis - seconds) * 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _varint(payload: bytes, offset: int) -> tuple[int, int]:
    return _binary().consume_tdx_signed_varint(payload, offset)


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
