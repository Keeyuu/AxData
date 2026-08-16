"""Provider-owned command dispatch target facts."""

BUILDER_TARGET_ITEMS: tuple[tuple[str, tuple[str, str]], ...] = (
    ("exchange_announcement", ("announcements", "build_exchange_announcement_frame")),
    ("heartbeat", ("session", "build_heartbeat_frame")),
    ("announcement", ("announcements", "build_announcement_frame")),
    ("handshake", ("session", "build_handshake_frame")),
    ("capital_changes", ("corporate", "build_capital_changes_frame")),
    ("finance_info", ("finance", "build_finance_info_frame")),
    ("server_info", ("server_info", "build_server_info_frame")),
    ("file_meta", ("resources", "build_file_meta_frame")),
    ("security_list", ("security", "build_security_list_frame")),
    ("security_count", ("security", "build_security_count_frame")),
    ("security_list_old", ("security_old", "build_security_list_old_frame")),
    ("price_limits", ("price_limits", "build_price_limits_frame")),
    ("volume_profile", ("volume_profile", "build_volume_profile_frame")),
    ("intraday_subchart", ("subchart", "build_intraday_subchart_frame")),
    ("index_momentum", ("index", "build_index_momentum_frame")),
    ("index_info", ("index", "build_index_info_frame")),
    ("klines_0523", ("klines", "build_klines_0523_frame")),
    ("klines", ("klines", "build_klines_frame")),
    ("today_intraday", ("intraday", "build_today_intraday_frame")),
    ("legacy_quotes", ("quotes", "build_legacy_quotes_frame")),
    ("top_board", ("top_board", "build_top_board_frame")),
    ("refresh_quotes", ("quotes", "build_refresh_quotes_frame")),
    ("category_quotes", ("quotes", "build_category_quotes_frame")),
    ("explicit_quotes", ("quotes", "build_explicit_quotes_frame")),
    ("unusual", ("unusual", "build_unusual_frame")),
    ("auction_process", ("auction", "build_auction_process_frame")),
    ("file_content", ("resources", "build_file_content_frame")),
    ("historical_intraday", ("intraday", "build_historical_intraday_frame")),
    ("historical_trades_basic", ("trades", "build_historical_trades_basic_frame")),
    ("today_trades", ("trades", "build_today_trades_frame")),
    ("historical_trades", ("trades", "build_historical_trades_frame")),
    ("chart_sampling", ("chart_sampling", "build_chart_sampling_frame")),
    ("recent_historical_intraday", ("intraday", "build_recent_historical_intraday_frame")),
    # MAC 余族；顺序与 _command_codes/_command_metadata 严格一致。
    ("mac_server_info", ("mac_server_info", "build_mac_server_info_frame")),
    ("mac_file_list", ("mac_file", "build_mac_file_list_frame")),
    ("mac_file_download", ("mac_file", "build_mac_file_download_frame")),
    ("mac_capital_flow", ("mac_capital_flow", "build_mac_capital_flow_frame")),
    # 0x1218 同码双名：mac_symbol_belong_board 与 mac_capital_flow 共用同一
    # 路由 builder/parser（按 payload query 常量 / 响应回显分流），dict 码键
    # 去重后两侧等价，覆盖顺序无关。
    ("mac_symbol_belong_board", ("mac_capital_flow", "build_mac_capital_flow_frame")),
    ("mac_symbol_info", ("mac_symbol_info", "build_mac_symbol_info_frame")),
    ("mac_symbol_quotes", ("mac_symbol_quotes", "build_mac_symbol_quotes_frame")),
    ("mac_board_members", ("mac_board_members", "build_mac_board_members_frame")),
    ("mac_quotes", ("mac_quotes", "build_mac_quotes_frame")),
    ("mac_symbol_bars", ("mac_symbol_bars", "build_mac_symbol_bars_frame")),
    ("mac_transactions", ("mac_transactions", "build_mac_transactions_frame")),
    ("mac_board_list", ("mac_board", "build_mac_board_list_frame")),
    ("mac_market_monitor", ("mac_market_monitor", "build_mac_market_monitor_frame")),
    ("mac_auction", ("mac_auction", "build_mac_auction_frame")),
    ("mac_tick_charts", ("mac_tick_charts", "build_mac_tick_charts_frame")),
    ("mac_kline_offset", ("mac_kline_offset", "build_mac_kline_offset_frame")),
)

PARSER_TARGET_ITEMS: tuple[tuple[str, tuple[str, str, bool]], ...] = (
    ("exchange_announcement", ("announcements", "parse_exchange_announcement_payload", False)),
    ("heartbeat", ("session", "parse_heartbeat_payload", False)),
    ("announcement", ("announcements", "parse_announcement_payload", False)),
    ("handshake", ("session", "parse_handshake_payload", False)),
    ("capital_changes", ("corporate", "parse_capital_changes_payload", True)),
    ("finance_info", ("finance", "parse_finance_info_payload", True)),
    ("server_info", ("server_info", "parse_server_info_payload", False)),
    ("file_meta", ("resources", "parse_file_meta_payload", True)),
    ("security_list", ("security", "parse_security_list_payload", True)),
    ("security_count", ("security", "parse_security_count_payload", False)),
    ("security_list_old", ("security_old", "parse_security_list_old_payload", True)),
    ("price_limits", ("price_limits", "parse_price_limits_payload", True)),
    ("volume_profile", ("volume_profile", "parse_volume_profile_payload", True)),
    ("intraday_subchart", ("subchart", "parse_intraday_subchart_payload", True)),
    ("index_momentum", ("index", "parse_index_momentum_payload", True)),
    ("index_info", ("index", "parse_index_info_payload", True)),
    ("klines_0523", ("klines", "parse_klines_0523_payload", True)),
    ("klines", ("klines", "parse_klines_payload", True)),
    ("today_intraday", ("intraday", "parse_today_intraday_payload", True)),
    ("legacy_quotes", ("quotes", "parse_legacy_quotes_payload", True)),
    ("top_board", ("top_board", "parse_top_board_payload", True)),
    ("refresh_quotes", ("quotes", "parse_refresh_quotes_payload", True)),
    ("category_quotes", ("quotes", "parse_category_quotes_payload", True)),
    ("explicit_quotes", ("quotes", "parse_explicit_quotes_payload", True)),
    ("unusual", ("unusual", "parse_unusual_payload", True)),
    ("auction_process", ("auction", "parse_auction_process_payload", True)),
    ("file_content", ("resources", "parse_file_content_payload", True)),
    ("historical_intraday", ("intraday", "parse_historical_intraday_payload", True)),
    ("historical_trades_basic", ("trades", "parse_historical_trades_basic_payload", True)),
    ("today_trades", ("trades", "parse_today_trades_payload", True)),
    ("historical_trades", ("trades", "parse_historical_trades_payload", True)),
    ("chart_sampling", ("chart_sampling", "parse_chart_sampling_payload", True)),
    ("recent_historical_intraday", ("intraday", "parse_recent_historical_intraday_payload", True)),
    # MAC 余族；顺序与 _command_codes/_command_metadata 严格一致。
    ("mac_server_info", ("mac_server_info", "parse_mac_server_info_payload", True)),
    ("mac_file_list", ("mac_file", "parse_mac_file_list_payload", True)),
    ("mac_file_download", ("mac_file", "parse_mac_file_download_payload", True)),
    ("mac_capital_flow", ("mac_capital_flow", "parse_mac_capital_flow_payload", True)),
    # 0x1218 同码双名，见 BUILDER_TARGET_ITEMS 注释。
    ("mac_symbol_belong_board", ("mac_capital_flow", "parse_mac_capital_flow_payload", True)),
    ("mac_symbol_info", ("mac_symbol_info", "parse_mac_symbol_info_payload", True)),
    ("mac_symbol_quotes", ("mac_symbol_quotes", "parse_mac_symbol_quotes_payload", True)),
    ("mac_board_members", ("mac_board_members", "parse_mac_board_members_payload", True)),
    ("mac_quotes", ("mac_quotes", "parse_mac_quotes_payload", True)),
    ("mac_symbol_bars", ("mac_symbol_bars", "parse_mac_symbol_bars_payload", True)),
    ("mac_transactions", ("mac_transactions", "parse_mac_transactions_payload", True)),
    ("mac_board_list", ("mac_board", "parse_mac_board_list_payload", True)),
    ("mac_market_monitor", ("mac_market_monitor", "parse_mac_market_monitor_payload", True)),
    ("mac_auction", ("mac_auction", "parse_mac_auction_payload", True)),
    ("mac_tick_charts", ("mac_tick_charts", "parse_mac_tick_charts_payload", True)),
    ("mac_kline_offset", ("mac_kline_offset", "parse_mac_kline_offset_payload", True)),
)


def builder_target(name: str) -> tuple[str, str]:
    for command_name, target in BUILDER_TARGET_ITEMS:
        if command_name == name:
            return target
    raise KeyError(name)


def parser_target(name: str) -> tuple[str, str, bool]:
    for command_name, target in PARSER_TARGET_ITEMS:
        if command_name == name:
            return target
    raise KeyError(name)


def _builder_targets() -> dict[str, tuple[str, str]]:
    cached = globals().get("BUILDER_TARGETS")
    if cached is not None:
        return cached
    builder_targets = dict(BUILDER_TARGET_ITEMS)
    globals()["BUILDER_TARGETS"] = builder_targets
    return builder_targets


def _parser_targets() -> dict[str, tuple[str, str, bool]]:
    cached = globals().get("PARSER_TARGETS")
    if cached is not None:
        return cached
    parser_targets = dict(PARSER_TARGET_ITEMS)
    globals()["PARSER_TARGETS"] = parser_targets
    return parser_targets


def __getattr__(name: str):
    if name == "BUILDER_TARGETS":
        return _builder_targets()
    if name == "PARSER_TARGETS":
        return _parser_targets()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "BUILDER_TARGET_ITEMS",
    "BUILDER_TARGETS",
    "PARSER_TARGET_ITEMS",
    "PARSER_TARGETS",
    "builder_target",
    "parser_target",
]
