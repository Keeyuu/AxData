"""MAC file commands (0x1215 list / 0x1217 download) builder and parser.

Wire layout follows gotdx ``proto/mac_file.go``: the list request is
``<u32 offset><filename[70]><reserved[30]>`` and the download request is
``<u32 index><u32 offset><u32 size><filename[70]><reserved[30]>`` with
gotdx defaults (index=1, size=30000). Both use the MAC ex-request head byte
0x01.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.mac_file import (
        MacFileDownloadChunk,
        MacFileListMeta,
    )

TYPE_MAC_FILE_LIST = command_code("mac_file_list")
TYPE_MAC_FILE_DOWNLOAD = command_code("mac_file_download")

DEFAULT_MAC_DOWNLOAD_INDEX = 1
DEFAULT_MAC_DOWNLOAD_SIZE = 30000
_FILENAME_WIDTH = 70
_LIST_RESERVED_WIDTH = 30
_DOWNLOAD_RESERVED_WIDTH = 30
_LIST_MIN_PAYLOAD = 41
_DOWNLOAD_MIN_PAYLOAD = 8
_HASH_WIDTH = 32

_FRAME_CONSTANTS_MODULE = "axdata_source_tdx._tdx_wire.protocol._frame_constants"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.mac_file"
_FRAME_CONSTANTS_EXPORTS = {"MAC_EX_PREFIX"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_MODEL_EXPORTS = {"MacFileDownloadChunk", "MacFileListMeta"}


def _frame_constants():
    return import_module(_FRAME_CONSTANTS_MODULE)


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _model_module():
    return import_module(_MODEL_MODULE)


def build_mac_file_list_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    payload = payload or {}
    offset = _normalize_u32(payload.get("offset", 0), "offset")
    data = (
        offset.to_bytes(4, "little", signed=False)
        + _filename_bytes(payload.get("filename", ""))
        + b"\x00" * _LIST_RESERVED_WIDTH
    )
    return RequestFrame(
        msg_id=msg_id,
        msg_type=TYPE_MAC_FILE_LIST,
        data=data,
        head=_frame_constants().MAC_EX_PREFIX,
    )


def parse_mac_file_list_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> MacFileListMeta:
    request_payload = request_payload or {}
    payload = response.data
    if len(payload) < _LIST_MIN_PAYLOAD:
        raise _protocol_error()(f"invalid mac file list payload length: {len(payload)}")

    flag = int.from_bytes(payload[8:9], "little", signed=True)  # int8
    hash_text = payload[9 : 9 + _HASH_WIDTH].rstrip(b"\x00").decode("ascii", errors="replace")
    return _model_module().MacFileListMeta(
        offset=_little_u32(payload[0:4]),
        size=_little_u32(payload[4:8]),
        flag=flag,
        hash=hash_text,
        raw_payload=payload if request_payload.get("include_raw") else b"",
    )


def build_mac_file_download_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    payload = payload or {}
    index = payload.get("index", 0)
    if not index:
        index = DEFAULT_MAC_DOWNLOAD_INDEX
    index = _normalize_u32(index, "index")
    offset = _normalize_u32(payload.get("offset", 0), "offset")
    size = payload.get("size", 0)
    if not size:
        size = DEFAULT_MAC_DOWNLOAD_SIZE
    size = _normalize_u32(size, "size")
    data = (
        index.to_bytes(4, "little", signed=False)
        + offset.to_bytes(4, "little", signed=False)
        + size.to_bytes(4, "little", signed=False)
        + _filename_bytes(payload.get("filename", ""))
        + b"\x00" * _DOWNLOAD_RESERVED_WIDTH
    )
    return RequestFrame(
        msg_id=msg_id,
        msg_type=TYPE_MAC_FILE_DOWNLOAD,
        data=data,
        head=_frame_constants().MAC_EX_PREFIX,
    )


def parse_mac_file_download_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> MacFileDownloadChunk:
    request_payload = request_payload or {}
    payload = response.data
    if len(payload) < _DOWNLOAD_MIN_PAYLOAD:
        raise _protocol_error()(f"invalid mac file download payload length: {len(payload)}")

    return _model_module().MacFileDownloadChunk(
        index=_little_u32(payload[0:4]),
        size=_little_u32(payload[4:8]),
        data=payload[8:],
        raw_payload=payload if request_payload.get("include_raw") else b"",
    )


def _filename_bytes(value: Any) -> bytes:
    """gotdx makeMACCode70：定长拷贝，超长截断、不足右补 \\0。"""

    text = str(value).encode("ascii", errors="ignore")
    if len(text) > _FILENAME_WIDTH:
        text = text[:_FILENAME_WIDTH]
    return text.ljust(_FILENAME_WIDTH, b"\x00")


def _little_u32(data: bytes) -> int:
    return int.from_bytes(data, "little", signed=False)


def _normalize_u32(value: Any, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise _protocol_error()(f"{name} must be an integer") from exc
    if parsed < 0 or parsed > 0xFFFFFFFF:
        raise _protocol_error()(f"{name} must be between 0 and 4294967295")
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
    if name in _FRAME_CONSTANTS_EXPORTS:
        value = getattr(import_module(_FRAME_CONSTANTS_MODULE), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _EXCEPTION_EXPORTS | _MODEL_EXPORTS | _FRAME_CONSTANTS_EXPORTS)
