"""File resource command builders and parsers."""

from __future__ import annotations

import csv
import io
from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire._command_defaults import FILE_PATH_FIELD_SIZE
from axdata_source_tdx._tdx_wire._request_defaults import DEFAULT_FILE_CHUNK_SIZE
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.resource import FileContentChunk, FileMeta

TYPE_FILE_CONTENT = command_code("file_content")
# gotdx proto/proto.go KMSG_BLOCKINFOMETA（板块/静态文件元信息），Wave2 注册。
TYPE_FILE_META = command_code("file_meta")
FILE_META_NAME_FIELD_SIZE = 40
FILE_META_REPLY_SIZE = 38
_BINARY_MODULE = "axdata_source_tdx._tdx_wire._binary"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.resource"
_BINARY_EXPORTS = {"decode_gbk_text", "little_u32"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_MODEL_EXPORTS = {"FileContentChunk", "FileMeta"}


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _file_content_chunk_cls():
    return import_module(_MODEL_MODULE).FileContentChunk


def _file_meta_cls():
    return import_module(_MODEL_MODULE).FileMeta


def build_file_content_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    path = _file_path(payload.get("path"))
    offset = _u32_param(payload.get("offset", 0), "offset")
    size = _u32_param(payload.get("size", DEFAULT_FILE_CHUNK_SIZE), "size")
    if size <= 0:
        raise _protocol_error()("file content size must be > 0")

    path_raw = path.encode("ascii")
    if len(path_raw) > FILE_PATH_FIELD_SIZE:
        raise _protocol_error()("file content path exceeds 300 ASCII bytes")
    data = (
        offset.to_bytes(4, "little", signed=False)
        + size.to_bytes(4, "little", signed=False)
        + path_raw.ljust(FILE_PATH_FIELD_SIZE, b"\x00")
    )
    return RequestFrame(msg_id=msg_id, msg_type=TYPE_FILE_CONTENT, data=data)


def parse_file_content_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> FileContentChunk:
    request_payload = request_payload or {}
    payload = response.data
    if len(payload) < 4:
        raise _protocol_error()("invalid file content payload")
    chunk_len = import_module(_BINARY_MODULE).little_u32(payload[:4])
    if len(payload) < 4 + chunk_len:
        raise _protocol_error()(
            f"invalid file content payload length: expected {4 + chunk_len}, got {len(payload)}"
        )

    return _file_content_chunk_cls()(
        path=_file_path(request_payload.get("path", "")),
        offset=_u32_param(request_payload.get("offset", 0), "offset"),
        request_size=_u32_param(request_payload.get("size", DEFAULT_FILE_CHUNK_SIZE), "size"),
        chunk_len=chunk_len,
        content=payload[4 : 4 + chunk_len],
    )


def build_file_meta_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    """构建文件元信息请求帧（gotdx proto/get_file.go GetFileMetaRequest）。

    请求体为 40 字节定长文件名字段；0x02C5 已注册进统一 dispatch。
    """
    path = _file_path(payload.get("path"))
    path_raw = path.encode("ascii")
    if len(path_raw) > FILE_META_NAME_FIELD_SIZE:
        raise _protocol_error()("file meta path exceeds 40 ASCII bytes")
    data = path_raw.ljust(FILE_META_NAME_FIELD_SIZE, b"\x00")
    return RequestFrame(msg_id=msg_id, msg_type=TYPE_FILE_META, data=data)


def parse_file_meta_payload(
    response: ResponseFrame | bytes,
    request_payload: dict[str, Any] | None = None,
) -> FileMeta:
    """解析文件元信息应答（gotdx GetFileMetaReply，38 字节定长）。

    布局：size u32 LE + unknown1 u8 + 32 字节哈希 + unknown2 u8。
    dispatch 走 ResponseFrame；直接传 bytes（Wave1 用法）保持兼容。
    """
    data = response.data if isinstance(response, ResponseFrame) else response
    if len(data) < FILE_META_REPLY_SIZE:
        raise _protocol_error()(
            f"invalid file meta payload length: expected {FILE_META_REPLY_SIZE}, got {len(data)}"
        )
    return _file_meta_cls()(
        size=import_module(_BINARY_MODULE).little_u32(data[:4]),
        unknown1=data[4],
        hash_value=bytes(data[5:37]),
        unknown2=data[37],
    )


def parse_csv_rows(content: bytes) -> list[list[str]]:
    """整文件 CSV 行解析（gotdx GetCSVFile/parseCSVContent）。

    GBK 解码后按 CSV 规则拆分，逐行字段数不校验、空行跳过。
    """
    text = _decode_gbk_text(content)
    return [row for row in csv.reader(io.StringIO(text)) if row]


def parse_pipe_table_rows(content: bytes) -> list[list[str]]:
    """整文件竖线分隔表格行解析（gotdx GetTableFile/parsePipeTableContent）。

    GBK 解码后按行拆分，去首尾空白、跳过空行，字段以 ``|`` 分隔。
    """
    rows: list[list[str]] = []
    for line in _decode_gbk_text(content).split("\n"):
        line = line.strip()
        if not line:
            continue
        rows.append(line.split("|"))
    return rows


def _decode_gbk_text(data: bytes) -> str:
    return import_module(_BINARY_MODULE).decode_gbk_text(data)


def _file_path(value: Any) -> str:
    path = str(value or "").strip().replace("\\", "/")
    if not path:
        raise _protocol_error()("file content path is required")
    try:
        path.encode("ascii")
    except UnicodeEncodeError as exc:
        raise _protocol_error()("file content path must be ASCII") from exc
    return path


def _u32_param(value: Any, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise _protocol_error()(f"file content {name} must be an integer") from exc
    if number < 0 or number > 0xFFFFFFFF:
        raise _protocol_error()(f"file content {name} out of uint32 range")
    return number


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
