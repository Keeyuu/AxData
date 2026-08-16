"""Chart-sampling (0x0FD1) command builder and parser.

Wire layout follows gotdx ``proto/get_chart_sampling.go``: the request body is
``<u16 market><code[6]><reserved[28]>`` with gotdx's default reserved block;
the response echoes market/code, carries ``count`` at offset 34 and
``pre_close`` at 36, then ``count`` little-endian f32 samples from offset 42.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._code_utils import split_code
from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.chart_sampling import ChartSamplingSeries

TYPE_CHART_SAMPLING = command_code("chart_sampling")

CHART_SAMPLING_RESERVED = bytes(
    [
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x01, 0x00, 0x14, 0x00, 0x00, 0x00, 0x00, 0x01,
        0x00, 0x00, 0x00, 0x00,
    ]
)
CHART_SAMPLING_HEADER_SIZE = 42

_BINARY_MODULE = "axdata_source_tdx._tdx_wire._binary"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.chart_sampling"
_BINARY_EXPORTS = {"decode_gbk_text", "little_f32", "little_u16"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_MODEL_EXPORTS = {"ChartSamplingSeries"}


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _binary():
    return import_module(_BINARY_MODULE)


def _series_cls():
    return import_module(_MODEL_MODULE).ChartSamplingSeries


def build_chart_sampling_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    market_id, _, number = split_code(payload["code"])
    reserved = payload.get("reserved_raw", CHART_SAMPLING_RESERVED)
    if not isinstance(reserved, (bytes, bytearray)) or len(reserved) != 28:
        raise _protocol_error()("reserved_raw must be 28 bytes")
    data = (
        market_id.to_bytes(2, "little", signed=False)
        + number.encode("ascii")
        + bytes(reserved)
    )
    return RequestFrame(msg_id=msg_id, msg_type=TYPE_CHART_SAMPLING, data=data)


def parse_chart_sampling_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> ChartSamplingSeries:
    request_payload = request_payload or {}
    requested_code = request_payload.get("code", "sz000001")
    market_id, exchange, number = split_code(requested_code)
    payload = response.data
    if len(payload) < CHART_SAMPLING_HEADER_SIZE:
        raise _protocol_error()(
            f"invalid chart sampling payload length: {len(payload)}"
        )

    binary = _binary()
    count = binary.little_u16(payload[34:36])
    expected_length = CHART_SAMPLING_HEADER_SIZE + count * 4
    if len(payload) < expected_length:
        raise _protocol_error()(
            f"truncated chart sampling payload: expected {expected_length}, got {len(payload)}"
        )

    prices = [
        float(binary.little_f32(payload[offset : offset + 4]))
        for offset in range(CHART_SAMPLING_HEADER_SIZE, expected_length, 4)
    ]

    return _series_cls()(
        market_id=market_id,
        exchange=exchange,
        code=number,
        count=count,
        pre_close=float(binary.little_f32(payload[36:40])),
        prices=tuple(prices),
        raw_payload=payload if request_payload.get("include_raw") else b"",
    )


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
