"""MAC board-members (0x122C) command builder and parser — three forms.

Wire layout follows gotdx ``proto/mac_board_members.go`` (plain members,
``MACBoardMembers``; fixed quotes, ``MACBoardMembersQuotes``) and
``proto/mac_board_members_dynamic.go`` (``MACBoardMembersQuotesDynamic``).
All three share a 43-byte request body and the same 26-byte response head
(name gbk[16:20], total u32@20, count u16@24); they differ in the SortOrder
width and the tail (Extra[20] / Extra[21] / FieldBitmap[20] + filter) and in
the per-row layout.

One registration item routes on the request payload keys:

- ``field_bitmap`` key present (bytes/bytearray len 20, ``None`` ->
  ``DEFAULT_MAC_FIELD_BITMAP``) -> dynamic form (plus ``filter`` int, default
  0, written into the *sent* bitmap copy at byte 17 with bit 19 forced);
- otherwise ``include_quotes`` truthy -> fixed-quotes form;
- otherwise -> plain-members form.

The parser routes on the same keys of ``request_payload``.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from axdata_source_tdx._tdx_wire._command_codes import command_code
from axdata_source_tdx._tdx_wire.protocol.commands.mac_common import (
    DEFAULT_MAC_BOARD_MEMBERS_QUOTES_EXTRA,
    DEFAULT_MAC_FIELD_BITMAP,
    active_mac_dynamic_fields,
    decode_mac_dynamic_value,
    exchange_mac_board_code,
    mac_lot_size_board_symbol,
)
from axdata_source_tdx._tdx_wire.protocol.frame import RequestFrame, ResponseFrame

if TYPE_CHECKING:
    from axdata_source_tdx._tdx_wire.models.mac_board_members import (
        MacBoardMembersDynamicPage,
        MacBoardMembersPage,
        MacBoardMembersQuotesPage,
    )

TYPE_MAC_BOARD_MEMBERS = command_code("mac_board_members")

MAC_BOARD_MEMBERS_DEFAULT_SORT_TYPE = 14
MAC_BOARD_MEMBERS_DEFAULT_PAGE_SIZE = 80
_BOARD_CODE_WIDTH = 4
_RESERVED1_WIDTH = 9
_MEMBER_ROW_SIZE = 68
_QUOTES_ROW_SIZE = 196
_DYNAMIC_HEAD_SIZE = 26
_MEMBER_NAME_START = 16
_MEMBER_NAME_WIDTH = 4

_BINARY_MODULE = "axdata_source_tdx._tdx_wire._binary"
_EXCEPTIONS_MODULE = "axdata_source_tdx._tdx_wire.exceptions"
_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.mac_board_members"
_FRAME_CONSTANTS_MODULE = "axdata_source_tdx._tdx_wire.protocol._frame_constants"
_BINARY_EXPORTS = {"decode_gbk_text", "little_f32", "little_u16", "little_u32"}
_EXCEPTION_EXPORTS = {"ProtocolError"}
_MODEL_EXPORTS = {
    "MacBoardMemberItem",
    "MacBoardMemberQuoteDynamicItem",
    "MacBoardMemberQuoteItem",
    "MacBoardMembersDynamicPage",
    "MacBoardMembersPage",
    "MacBoardMembersQuotesPage",
}
_FRAME_CONSTANTS_EXPORTS = {"MAC_EX_PREFIX"}


def _frame_constants():
    return import_module(_FRAME_CONSTANTS_MODULE)


def _protocol_error():
    return import_module(_EXCEPTIONS_MODULE).ProtocolError


def _binary():
    return import_module(_BINARY_MODULE)


def _dynamic_route(payload: dict[str, Any]) -> bool:
    return "field_bitmap" in payload


def _quotes_route(payload: dict[str, Any]) -> bool:
    return bool(payload.get("include_quotes"))


def build_mac_board_members_frame(payload: dict[str, Any], msg_id: int) -> RequestFrame:
    """Build the 0x122C request frame (head=0x01, 43 bytes) for the routed form."""
    board_code = _resolve_board_code(payload)
    sort_type = _normalize_u16(payload.get("sort_type", 0), "sort_type")
    if sort_type == 0:
        sort_type = MAC_BOARD_MEMBERS_DEFAULT_SORT_TYPE
    start = _normalize_u32(payload.get("start", 0), "start")
    sort_order = _normalize_u8(payload.get("sort_order", 1), "sort_order")
    if sort_order == 0:
        sort_order = 1

    head = (
        board_code.to_bytes(_BOARD_CODE_WIDTH, "little", signed=False)
        + b"\x00" * _RESERVED1_WIDTH
        + sort_type.to_bytes(2, "little", signed=False)
        + start.to_bytes(4, "little", signed=False)
    )

    if _dynamic_route(payload):
        # gotdx MACBoardMembersQuotesDynamic: PageSize 以 u16 发送（高位 0）。
        page_size = _normalize_u16(payload.get("page_size", 0), "page_size")
        if page_size == 0:
            page_size = MAC_BOARD_MEMBERS_DEFAULT_PAGE_SIZE
        filter_value = _normalize_u8(payload.get("filter", 0), "filter")
        sent_bitmap = bytearray(_normalize_bitmap(payload.get("field_bitmap")))
        sent_bitmap[17] = filter_value
        sent_bitmap[19] |= 1
        data = (
            head
            + page_size.to_bytes(2, "little", signed=False)
            + sort_order.to_bytes(1, "little", signed=False)
            + b"\x00"  # Zero u8
            + bytes(sent_bitmap)
        )
    else:
        page_size = _normalize_u8(payload.get("page_size", 0), "page_size")
        if page_size == 0:
            page_size = MAC_BOARD_MEMBERS_DEFAULT_PAGE_SIZE
        if _quotes_route(payload):
            data = (
                head
                + page_size.to_bytes(1, "little", signed=False)
                + b"\x00"  # Zero u8
                + sort_order.to_bytes(1, "little", signed=False)
                + bytes(DEFAULT_MAC_BOARD_MEMBERS_QUOTES_EXTRA)
            )
        else:
            data = (
                head
                + page_size.to_bytes(1, "little", signed=False)
                + b"\x00"  # Zero u8
                + sort_order.to_bytes(2, "little", signed=False)
                + b"\x00" * 20  # Extra[20] 默认全 0
            )
    return RequestFrame(
        msg_id=msg_id,
        msg_type=TYPE_MAC_BOARD_MEMBERS,
        data=data,
        head=_frame_constants().MAC_EX_PREFIX,
    )


def parse_mac_board_members_payload(
    response: ResponseFrame,
    request_payload: dict[str, Any] | None = None,
) -> MacBoardMembersPage | MacBoardMembersQuotesPage | MacBoardMembersDynamicPage:
    request_payload = request_payload or {}
    payload = response.data
    if len(payload) < _DYNAMIC_HEAD_SIZE:
        raise _protocol_error()(f"invalid mac board members payload length: {len(payload)}")

    binary = _binary()
    name_end = _MEMBER_NAME_START + _MEMBER_NAME_WIDTH
    board_name = binary.decode_gbk_text(payload[_MEMBER_NAME_START:name_end])
    total = binary.little_u32(payload[20:24])
    count = binary.little_u16(payload[24:26])

    if _dynamic_route(request_payload):
        return _parse_dynamic(request_payload, payload, board_name, total, count)
    if _quotes_route(request_payload):
        return _parse_quotes(request_payload, payload, board_name, total, count)
    return _parse_members(request_payload, payload, board_name, total, count)


def _parse_members(
    request_payload: dict[str, Any],
    payload: bytes,
    board_name: str,
    total: int,
    count: int,
) -> MacBoardMembersPage:
    binary = _binary()
    model_module = import_module(_MODEL_MODULE)
    item_cls = model_module.MacBoardMemberItem
    stocks = []
    offset = _DYNAMIC_HEAD_SIZE
    for _ in range(count):
        if offset + _MEMBER_ROW_SIZE > len(payload):
            raise _protocol_error()(f"truncated mac board member item at offset {offset}")
        record = payload[offset : offset + _MEMBER_ROW_SIZE]
        stocks.append(
            item_cls(
                name=binary.decode_gbk_text(record[24:40]),
                market=binary.little_u16(record[0:2]),
                symbol=binary.decode_gbk_text(record[2:8]),
            )
        )
        offset += _MEMBER_ROW_SIZE
    return model_module.MacBoardMembersPage(
        name=board_name,
        total=total,
        count=count,
        stocks=tuple(stocks),
        raw_payload=payload if request_payload.get("include_raw") else b"",
    )


def _parse_quotes(
    request_payload: dict[str, Any],
    payload: bytes,
    board_name: str,
    total: int,
    count: int,
) -> MacBoardMembersQuotesPage:
    binary = _binary()
    model_module = import_module(_MODEL_MODULE)
    item_cls = model_module.MacBoardMemberQuoteItem
    stocks = []
    offset = _DYNAMIC_HEAD_SIZE
    for _ in range(count):
        if offset + _QUOTES_ROW_SIZE > len(payload):
            raise _protocol_error()(f"truncated mac board member quote item at offset {offset}")
        record = payload[offset : offset + _QUOTES_ROW_SIZE]
        metrics = record[68:196]
        pre_close = _float_at(metrics, 0)
        open_price = _float_at(metrics, 1)
        high = _float_at(metrics, 2)
        low = _float_at(metrics, 3)
        close = _float_at(metrics, 4)
        vol = _uint_at(metrics, 5)
        volume_ratio = _float_at(metrics, 6)
        amount = _float_at(metrics, 7)
        total_shares = _float_at(metrics, 8)
        float_shares = _float_at(metrics, 9)
        eps = _float_at(metrics, 10)
        net_assets = _float_at(metrics, 11)
        action_price = _float_at(metrics, 12)
        total_market_cap_ab = _float_at(metrics, 13)
        pe_dynamic = _float_at(metrics, 14)
        lot_size_info = _uint_at(metrics, 15)
        unknown23 = _float_at(metrics, 16)
        dividend_yield = _float_at(metrics, 17)
        speed_pct = _float_at(metrics, 27)
        last_volume = _uint_at(metrics, 18)
        turnover = _float_at(metrics, 19)
        some_bitmap = _uint_at(metrics, 20)
        decimal_point = _uint_at(metrics, 21)
        buy_price_limit = _float_at(metrics, 22)
        sell_price_limit = _float_at(metrics, 23)
        unknown34 = _uint_at(metrics, 24)
        lot_size = _uint_at(metrics, 25)
        pre_ipov = _float_at(metrics, 26)
        kcb_flag = _uint_at(metrics, 28)
        pe_ttm = _float_at(metrics, 29)
        pe_static = _float_at(metrics, 30)
        unknown_close_price = _float_at(metrics, 31)

        stocks.append(
            item_cls(
                name=binary.decode_gbk_text(record[24:48]),
                market=binary.little_u16(record[0:2]),
                symbol=binary.decode_gbk_text(record[2:8]),
                pre_close=pre_close,
                open=open_price,
                high=high,
                low=low,
                close=close,
                unknown6=float(vol),
                vol=vol,
                volume_ratio=volume_ratio,
                amount=amount,
                total_shares=total_shares,
                float_shares=float_shares,
                eps=eps,
                roe=net_assets,
                net_assets=net_assets,
                action_price=action_price,
                unknown13=action_price,
                unknown_action_price=action_price,
                market_cap=total_market_cap_ab,
                total_market_cap_ab=total_market_cap_ab,
                pe_dynamic=pe_dynamic,
                zero16=float(lot_size_info),
                lot_size_info=lot_size_info,
                unknown23=unknown23,
                zero17=unknown23,
                dividend_yield=dividend_yield,
                rise_speed=speed_pct,
                current_vol=last_volume & 0xFFFF,
                last_volume=last_volume,
                turnover=turnover,
                turnover_rate=turnover,
                unknown21=float(some_bitmap),
                some_bitmap=some_bitmap,
                unknown22=float(decimal_point),
                decimal_point=decimal_point,
                limit_up=buy_price_limit,
                buy_price_limit=buy_price_limit,
                limit_down=sell_price_limit,
                sell_price_limit=sell_price_limit,
                zero25=float(unknown34),
                unknown34=unknown34,
                unknown26=float(lot_size),
                lot_size=lot_size,
                lot_size_board_symbol=mac_lot_size_board_symbol(lot_size),
                unknown27=pre_ipov,
                pre_ipov=pre_ipov,
                rise_speed2=speed_pct,
                speed_pct=speed_pct,
                zero29=float(kcb_flag),
                flag_kcb=kcb_flag,
                kcb_flag=kcb_flag,
                pe_static=pe_static,
                pe_ttm=pe_ttm,
                unknown31=unknown_close_price,
                unknown_close_price=unknown_close_price,
            )
        )
        offset += _QUOTES_ROW_SIZE
    return model_module.MacBoardMembersQuotesPage(
        name=board_name,
        total=total,
        count=count,
        stocks=tuple(stocks),
        raw_payload=payload if request_payload.get("include_raw") else b"",
    )


def _parse_dynamic(
    request_payload: dict[str, Any],
    payload: bytes,
    board_name: str,
    total: int,
    count: int,
) -> MacBoardMembersDynamicPage:
    binary = _binary()
    model_module = import_module(_MODEL_MODULE)
    item_cls = model_module.MacBoardMemberQuoteDynamicItem
    field_bitmap = bytes(payload[:20])
    active_fields = active_mac_dynamic_fields(field_bitmap)
    row_size = 68 + len(active_fields) * 4
    stocks = []
    offset = _DYNAMIC_HEAD_SIZE
    for _ in range(count):
        if offset + row_size > len(payload):
            raise _protocol_error()(f"truncated mac board member dynamic item at offset {offset}")
        row = payload[offset : offset + row_size]
        values: dict[str, Any] = {}
        field_pos = 68
        for field_def in active_fields:
            raw = row[field_pos : field_pos + 4]
            value = decode_mac_dynamic_value(field_def.format, raw)
            values[field_def.name] = value
            for alias in field_def.aliases:
                values[alias] = value
            field_pos += 4
        stocks.append(
            item_cls(
                name=binary.decode_gbk_text(row[24:68]),
                market=binary.little_u16(row[0:2]),
                symbol=binary.decode_gbk_text(row[2:24]),
                values=values,
            )
        )
        offset += row_size
    return model_module.MacBoardMembersDynamicPage(
        field_bitmap=field_bitmap,
        active_fields=tuple(active_fields),
        total=total,
        count=count,
        stocks=tuple(stocks),
        raw_payload=payload if request_payload.get("include_raw") else b"",
    )


def _resolve_board_code(payload: dict[str, Any]) -> int:
    board_symbol = payload.get("board_symbol")
    if board_symbol not in (None, ""):
        try:
            return exchange_mac_board_code(str(board_symbol))
        except ValueError as exc:
            raise _protocol_error()(f"invalid board_symbol: {board_symbol!r}") from exc
    if "board_code" in payload:
        try:
            code = int(payload["board_code"])
        except (TypeError, ValueError) as exc:
            raise _protocol_error()("board_code must be an integer") from exc
        if code < 0 or code > 0xFFFFFFFF:
            raise _protocol_error()("board_code must be between 0 and 4294967295")
        return code
    raise _protocol_error()("mac board members requires board_symbol or board_code")


def _normalize_bitmap(value: Any) -> bytes:
    if value is None:
        return bytes(DEFAULT_MAC_FIELD_BITMAP)
    if not isinstance(value, (bytes, bytearray)) or len(value) != 20:
        raise _protocol_error()("field_bitmap must be 20 bytes")
    return bytes(value)


def _float_at(metrics: bytes, index: int) -> float:
    return float(import_module(_BINARY_MODULE).little_f32(metrics[index * 4 : index * 4 + 4]))


def _uint_at(metrics: bytes, index: int) -> int:
    return import_module(_BINARY_MODULE).little_u32(metrics[index * 4 : index * 4 + 4])


def _normalize_u8(value: Any, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise _protocol_error()(f"{name} must be an integer") from exc
    if parsed < 0 or parsed > 0xFF:
        raise _protocol_error()(f"{name} must be between 0 and 255")
    return parsed


def _normalize_u16(value: Any, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise _protocol_error()(f"{name} must be an integer") from exc
    if parsed < 0 or parsed > 0xFFFF:
        raise _protocol_error()(f"{name} must be between 0 and 65535")
    return parsed


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
