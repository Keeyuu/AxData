"""7709 protocol constants."""

from __future__ import annotations

from importlib import import_module


_COMMAND_CODES_MODULE = "axdata_source_tdx._tdx_wire._command_codes"
_FRAME_CONSTANTS_MODULE = "axdata_source_tdx._tdx_wire.protocol._frame_constants"
_REQUEST_DEFAULTS_MODULE = "axdata_source_tdx._tdx_wire._request_defaults"
_COMMAND_EXPORTS = {
    "TYPE_ANNOUNCEMENT": "announcement",
    "TYPE_AUCTION_PROCESS": "auction_process",
    "TYPE_CAPITAL_CHANGES": "capital_changes",
    "TYPE_CATEGORY_QUOTES": "category_quotes",
    "TYPE_CHART_SAMPLING": "chart_sampling",
    "TYPE_EXCHANGE_ANNOUNCEMENT": "exchange_announcement",
    "TYPE_EXPLICIT_QUOTES": "explicit_quotes",
    "TYPE_FILE_CONTENT": "file_content",
    "TYPE_FILE_META": "file_meta",
    "TYPE_FINANCE_INFO": "finance_info",
    "TYPE_HANDSHAKE": "handshake",
    "TYPE_HEARTBEAT": "heartbeat",
    "TYPE_HISTORICAL_INTRADAY": "historical_intraday",
    "TYPE_HISTORICAL_TRADES": "historical_trades",
    "TYPE_HISTORICAL_TRADES_BASIC": "historical_trades_basic",
    "TYPE_INDEX_INFO": "index_info",
    "TYPE_INDEX_MOMENTUM": "index_momentum",
    "TYPE_INTRADAY_SUBCHART": "intraday_subchart",
    "TYPE_KLINES": "klines",
    "TYPE_KLINES_0523": "klines_0523",
    "TYPE_LEGACY_QUOTES": "legacy_quotes",
    "TYPE_MAC_AUCTION": "mac_auction",
    "TYPE_MAC_BOARD_LIST": "mac_board_list",
    "TYPE_MAC_BOARD_MEMBERS": "mac_board_members",
    "TYPE_MAC_CAPITAL_FLOW": "mac_capital_flow",
    "TYPE_MAC_FILE_DOWNLOAD": "mac_file_download",
    "TYPE_MAC_FILE_LIST": "mac_file_list",
    "TYPE_MAC_KLINE_OFFSET": "mac_kline_offset",
    "TYPE_MAC_MARKET_MONITOR": "mac_market_monitor",
    "TYPE_MAC_QUOTES": "mac_quotes",
    "TYPE_MAC_SERVER_INFO": "mac_server_info",
    "TYPE_MAC_SYMBOL_BARS": "mac_symbol_bars",
    "TYPE_MAC_SYMBOL_BELONG_BOARD": "mac_symbol_belong_board",
    "TYPE_MAC_SYMBOL_INFO": "mac_symbol_info",
    "TYPE_MAC_SYMBOL_QUOTES": "mac_symbol_quotes",
    "TYPE_MAC_TICK_CHARTS": "mac_tick_charts",
    "TYPE_MAC_TRANSACTIONS": "mac_transactions",
    "TYPE_PRICE_LIMITS": "price_limits",
    "TYPE_RECENT_HISTORICAL_INTRADAY": "recent_historical_intraday",
    "TYPE_REFRESH_QUOTES": "refresh_quotes",
    "TYPE_SECURITY_COUNT": "security_count",
    "TYPE_SECURITY_LIST": "security_list",
    "TYPE_SECURITY_LIST_OLD": "security_list_old",
    "TYPE_SERVER_INFO": "server_info",
    "TYPE_TODAY_INTRADAY": "today_intraday",
    "TYPE_TODAY_TRADES": "today_trades",
    "TYPE_TOP_BOARD": "top_board",
    "TYPE_UNUSUAL": "unusual",
    "TYPE_VOLUME_PROFILE": "volume_profile",
}
_FRAME_EXPORTS = {"CONTROL_DEFAULT", "PREFIX", "PREFIX_RESP"}
_REQUEST_DEFAULT_EXPORTS = {"DEFAULT_CODE_PAGE_SIZE", "DEFAULT_QUOTE_BATCH_SIZE"}


def _command_codes_module():
    return import_module(_COMMAND_CODES_MODULE)


def _frame_constants_module():
    return import_module(_FRAME_CONSTANTS_MODULE)


def _request_defaults_module():
    return import_module(_REQUEST_DEFAULTS_MODULE)


def __getattr__(name: str):
    if name in _COMMAND_EXPORTS:
        value = _command_codes_module().command_code(_COMMAND_EXPORTS[name])
    elif name == "command_code":
        value = _command_codes_module().command_code
    elif name == "COMMAND_CODES":
        value = _command_codes_module().COMMAND_CODES
    elif name in _FRAME_EXPORTS:
        value = getattr(_frame_constants_module(), name)
    elif name in _REQUEST_DEFAULT_EXPORTS:
        value = getattr(_request_defaults_module(), name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = sorted(set(_COMMAND_EXPORTS) | _FRAME_EXPORTS | _REQUEST_DEFAULT_EXPORTS | {"COMMAND_CODES", "command_code"})
