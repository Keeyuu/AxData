"""Provider-owned 7709 command code facts."""

from __future__ import annotations

COMMAND_CODE_ITEMS: tuple[tuple[str, int], ...] = (
    ("exchange_announcement", 0x0002),
    ("heartbeat", 0x0004),
    ("announcement", 0x000A),
    ("handshake", 0x000D),
    ("capital_changes", 0x000F),
    ("finance_info", 0x0010),
    ("server_info", 0x0015),
    ("file_meta", 0x02C5),
    ("security_list", 0x044D),
    ("security_count", 0x044E),
    ("security_list_old", 0x0450),
    ("price_limits", 0x0452),
    ("volume_profile", 0x051A),
    ("intraday_subchart", 0x051B),
    ("index_momentum", 0x051C),
    ("index_info", 0x051D),
    ("klines_0523", 0x0523),
    ("klines", 0x052D),
    ("today_intraday", 0x0537),
    ("legacy_quotes", 0x053E),
    ("top_board", 0x053F),
    ("refresh_quotes", 0x0547),
    ("category_quotes", 0x054B),
    ("explicit_quotes", 0x054C),
    ("unusual", 0x0563),
    ("auction_process", 0x056A),
    ("file_content", 0x06B9),
    ("historical_intraday", 0x0FB4),
    ("historical_trades_basic", 0x0FB5),
    ("today_trades", 0x0FC5),
    ("historical_trades", 0x0FC6),
    ("chart_sampling", 0x0FD1),
    ("recent_historical_intraday", 0x0FEB),
    # MAC 族（gotdx proto/proto.go KMSG_MAC*；除 capital_flow 外 head=0x01）。
    # mac_symbol_belong_board 与 mac_capital_flow 同码 0x1218（gotdx 同值不同
    # query 常量与 head），dispatch 两侧指向同一路由 builder/parser。
    ("mac_server_info", 0x120F),
    ("mac_file_list", 0x1215),
    ("mac_file_download", 0x1217),
    ("mac_capital_flow", 0x1218),
    ("mac_symbol_belong_board", 0x1218),
    ("mac_symbol_info", 0x122A),
    ("mac_symbol_quotes", 0x122B),
    ("mac_board_members", 0x122C),
    ("mac_quotes", 0x122D),
    ("mac_symbol_bars", 0x122E),
    ("mac_transactions", 0x122F),
    ("mac_board_list", 0x1231),
    ("mac_market_monitor", 0x1237),
    ("mac_auction", 0x123D),
    ("mac_tick_charts", 0x123E),
    ("mac_kline_offset", 0x124A),
)

_TYPE_EXPORTS = {
    "TYPE_HEARTBEAT": "heartbeat",
    "TYPE_HANDSHAKE": "handshake",
}


def command_code(name: str) -> int:
    for command_name, code in COMMAND_CODE_ITEMS:
        if command_name == name:
            return code
    raise KeyError(name)


def command_name(code: int) -> str:
    for command_name, command_code_value in COMMAND_CODE_ITEMS:
        if command_code_value == code:
            return command_name
    raise KeyError(code)


def _command_codes() -> dict[str, int]:
    cached = globals().get("COMMAND_CODES")
    if cached is not None:
        return cached
    command_codes = dict(COMMAND_CODE_ITEMS)
    globals()["COMMAND_CODES"] = command_codes
    return command_codes


def __getattr__(name: str):
    if name == "COMMAND_CODES":
        return _command_codes()
    if name in _TYPE_EXPORTS:
        value = command_code(_TYPE_EXPORTS[name])
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "COMMAND_CODE_ITEMS",
    "COMMAND_CODES",
    "TYPE_HEARTBEAT",
    "TYPE_HANDSHAKE",
    "command_code",
    "command_name",
]
