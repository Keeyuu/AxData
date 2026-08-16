"""Volume-profile (0x051A) command builder and parser.

Wire layout follows gotdx ``proto/get_volume_profile.go``: the request body
is ``<u16 market><code[6]>``; the reply is a quote-style snapshot header
(fixed prefix + ``getprice`` varints + f32 amount + three bid/ask level
groups + u16 unknown) followed by ``count`` cumulative profile rows
(``<price delta><vol><buy><sell>``) whose price deltas may arrive as wrapped
32-bit two's complement varints (gotdx ``decodeVolumeProfilePriceDelta``).
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._code_utils import split_code
from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.volume_profile import VolumeProfileSnapshot

TYPE_VOLUME_PROFILE = command_code("volume_profile")

_BINARY_MODULE = "axdata_source_tdx._tdx_wire._binary"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.volume_profile"
_BINARY_EXPORTS = {"consume_tdx_signed_varint", "decode_gbk_text", "little_f32", "little_u16"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_MODEL_EXPORTS = {"VolumeProfileItem", "VolumeProfileLevel", "VolumeProfileSnapshot"}


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _binary():
    return import_module(_BINARY_MODULE)


def build_volume_profile_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    market_id, _, number = split_code(payload["code"])
    data = market_id.to_bytes(2, "little", signed=False) + number.encode("ascii")
    return RequestFrame(msg_id=msg_id, msg_type=TYPE_VOLUME_PROFILE, data=data)


def parse_volume_profile_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> VolumeProfileSnapshot:
    request_payload = request_payload or {}
    requested_code = request_payload.get("code", "sz000001")
    _, exchange, number = split_code(requested_code)
    payload = response.data
    if len(payload) < 11:
        raise _protocol_error()("invalid volume profile payload")

    binary = _binary()
    count = binary.little_u16(payload[:2])
    market = payload[2]
    code = binary.decode_gbk_text(payload[3:9])
    active = binary.little_u16(payload[9:11])

    offset = 11
    base_price, offset = _varint(payload, offset)
    pre_close_diff, offset = _varint(payload, offset)
    open_diff, offset = _varint(payload, offset)
    high_diff, offset = _varint(payload, offset)
    low_diff, offset = _varint(payload, offset)
    server_time_raw, offset = _varint(payload, offset)
    neg_price_raw, offset = _varint(payload, offset)
    vol, offset = _varint(payload, offset)
    cur_vol, offset = _varint(payload, offset)
    if offset + 4 > len(payload):
        raise _protocol_error()("truncated volume profile amount")
    amount = float(binary.little_f32(payload[offset : offset + 4]))
    offset += 4
    in_vol, offset = _varint(payload, offset)
    out_vol, offset = _varint(payload, offset)
    s_amount, offset = _varint(payload, offset)
    open_amount, offset = _varint(payload, offset)

    level_cls = import_module(_MODEL_MODULE).VolumeProfileLevel
    bid_levels = []
    ask_levels = []
    for _ in range(3):
        bid_diff, offset = _varint(payload, offset)
        ask_diff, offset = _varint(payload, offset)
        bid_vol, offset = _varint(payload, offset)
        ask_vol, offset = _varint(payload, offset)
        bid_levels.append(level_cls(price=(base_price + bid_diff) / 100.0, vol=bid_vol))
        ask_levels.append(level_cls(price=(base_price + ask_diff) / 100.0, vol=ask_vol))

    if offset + 2 > len(payload):
        raise _protocol_error()("truncated volume profile unknown tail")
    unknown = binary.little_u16(payload[offset : offset + 2])
    offset += 2

    profile_cls = import_module(_MODEL_MODULE).VolumeProfileItem
    vol_profiles = []
    profile_price = 0
    for _ in range(count):
        price_delta, offset = _varint(payload, offset)
        profile_vol, offset = _varint(payload, offset)
        buy, offset = _varint(payload, offset)
        sell, offset = _varint(payload, offset)
        profile_price += _decode_price_delta(price_delta)
        vol_profiles.append(
            profile_cls(
                price=profile_price / 100.0,
                vol=profile_vol,
                buy=buy,
                sell=sell,
            )
        )

    return import_module(_MODEL_MODULE).VolumeProfileSnapshot(
        count=count,
        market_id=market,
        exchange=exchange,
        code=code or number,
        active=active,
        close=base_price / 100.0,
        open=(base_price + open_diff) / 100.0,
        high=(base_price + high_diff) / 100.0,
        low=(base_price + low_diff) / 100.0,
        pre_close=(base_price + pre_close_diff) / 100.0,
        server_time=_format_server_time(server_time_raw),
        neg_price=neg_price_raw / 100.0,
        vol=vol,
        cur_vol=cur_vol,
        amount=amount,
        in_vol=in_vol,
        out_vol=out_vol,
        s_amount=s_amount,
        open_amount=open_amount,
        bid_levels=tuple(bid_levels),
        ask_levels=tuple(ask_levels),
        unknown=unknown,
        vol_profiles=tuple(vol_profiles),
        raw_payload=payload if request_payload.get("include_raw") else b"",
    )


def _decode_price_delta(value: int) -> int:
    """Port of gotdx ``decodeVolumeProfilePriceDelta``."""

    if value >= 1 << 31:
        return value - (1 << 32)
    return value


def _format_server_time(raw: int) -> str:
    from axdata_source_tdx._tdx_wire.protocol.commands.index import format_server_time

    return format_server_time(raw)


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
