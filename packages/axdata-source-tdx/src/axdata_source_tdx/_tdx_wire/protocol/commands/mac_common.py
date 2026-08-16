"""Shared MAC-channel helpers (gotdx proto/mac_util.go & field tables).

Everything here is a faithful transcription of gotdx source facts used by
several MAC command modules:

- ``exchange_mac_board_code`` — ``proto/mac_util.go`` ExchangeMACBoardCode.
- ``MAC_INDUSTRY_BOARD_SYMBOL_MAP`` / ``mac_industry_board_symbol`` /
  ``mac_lot_size_board_symbol`` — ``proto/field_alignment_helpers.go``.
- ``MAC_DYNAMIC_FIELD_DEFS`` / ``active_mac_dynamic_fields`` /
  ``decode_mac_dynamic_value`` / bitmap defaults —
  ``proto/mac_board_members_dynamic.go``.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_MODEL_MODULE = "axdata_source_tdx._tdx_wire.models.mac_symbol_quotes"
_MODEL_EXPORTS = {"MacDynamicFieldDef"}

# gotdx proto/field_alignment_helpers.go macIndustryBoardSymbolMap（131 项原样）。
MAC_INDUSTRY_BOARD_SYMBOL_MAP: dict[str, str] = {
    "1001": "881002",
    "1102": "881008",
    "1103": "881011",
    "1201": "881016",
    "1202": "881019",
    "1203": "881026",
    "1204": "881034",
    "1205": "881044",
    "1206": "881051",
    "1207": "881055",
    "1208": "881104",
    "1301": "881062",
    "1302": "881065",
    "1303": "881069",
    "1401": "881071",
    "1402": "881075",
    "1403": "881078",
    "1404": "881082",
    "1405": "881087",
    "1501": "881091",
    "1502": "881094",
    "1503": "881097",
    "2001": "881106",
    "2002": "881111",
    "2003": "881115",
    "2004": "881116",
    "2005": "881119",
    "2006": "881123",
    "2007": "881127",
    "2102": "881130",
    "2103": "881136",
    "2104": "881139",
    "2105": "881140",
    "2106": "881144",
    "2201": "881151",
    "2202": "881157",
    "2203": "881162",
    "2301": "881167",
    "2302": "881171",
    "2303": "881177",
    "2304": "881180",
    "2401": "881184",
    "2402": "881187",
    "2403": "881190",
    "2404": "881194",
    "2406": "881198",
    "2501": "881200",
    "2503": "881204",
    "2504": "881205",
    "2505": "881206",
    "2506": "881207",
    "2601": "881212",
    "2602": "881215",
    "2603": "881218",
    "2604": "881224",
    "2605": "881227",
    "2701": "881231",
    "2702": "881234",
    "2703": "881241",
    "2704": "881247",
    "2705": "881252",
    "2706": "881256",
    "2707": "881257",
    "3001": "881261",
    "3002": "881262",
    "3003": "881268",
    "3004": "881275",
    "3005": "881282",
    "3006": "881285",
    "3101": "881287",
    "3102": "881288",
    "3103": "881289",
    "3104": "881290",
    "3105": "881291",
    "3201": "881293",
    "3202": "881294",
    "3203": "881303",
    "3204": "881310",
    "3205": "881313",
    "4001": "881319",
    "4002": "881326",
    "4003": "881329",
    "4004": "881333",
    "4005": "881336",
    "4101": "881338",
    "4102": "881344",
    "4103": "881347",
    "4201": "881352",
    "4202": "881355",
    "4203": "881359",
    "4204": "881364",
    "4301": "881369",
    "4302": "881370",
    "4303": "881373",
    "4304": "881376",
    "4306": "881380",
    "4307": "881384",
    "5001": "881386",
    "5002": "881389",
    "5101": "881394",
    "5102": "881395",
    "5103": "881396",
    "5201": "881406",
    "5202": "881407",
    "5203": "881410",
    "5204": "881415",
    "5205": "881416",
    "5301": "881418",
    "5302": "881422",
    "6001": "881427",
    "6002": "881428",
    "6003": "881429",
    "6005": "881432",
    "6006": "881436",
    "6101": "881442",
    "6102": "881446",
    "6103": "881449",
    "6104": "881452",
    "6201": "881459",
    "6202": "881467",
    "6203": "881468",
    "6301": "881470",
    "6302": "881471",
    "6303": "881476",
    "9901": "881478",
}

# gotdx proto/mac_board_members_dynamic.go macBoardMembersQuotesDynamicFieldMap.
# (bit, name, format, description, aliases)；缺号位图（0x5a/0x79/0x7c）为源表空洞。
MAC_DYNAMIC_FIELD_DEFS: dict[int, tuple[str, str, str, tuple[str, ...]]] = {
    0x00: ("pre_close", "float32", "昨收", ()),
    0x01: ("open", "float32", "开盘价", ()),
    0x02: ("high", "float32", "最高价", ()),
    0x03: ("low", "float32", "最低价", ()),
    0x04: ("close", "float32", "收盘价", ()),
    0x05: ("vol", "uint32", "成交量", ()),
    0x06: ("vol_ratio", "float32", "量比", ()),
    0x07: ("amount", "float32", "总金额(元)", ()),
    0x08: ("inside_volume", "uint32", "内盘", ()),
    0x09: ("outside_volume", "uint32", "外盘", ()),
    0x0A: ("total_shares", "float32", "总股数(单位万)", ()),
    0x0B: ("float_shares", "float32", "流通股(单位万)", ("total_shares_hk",)),
    0x0C: ("eps", "float32", "每股收益", ()),
    0x0D: ("net_assets", "float32", "净资产", ()),
    0x0E: ("security_type_price", "float32", "证券类型价", ("action_price",)),
    0x0F: ("total_market_cap_ab", "float32", "AB股总市值", ()),
    0x10: ("pe_dynamic", "float32", "市盈率(动)", ()),
    0x11: ("bid_price", "float32", "买一价", ("bid",)),
    0x12: ("ask_price", "float32", "卖一价", ("ask",)),
    0x13: ("server_update_date", "uint32", "服务器更新日期 YYYYMMDD", ()),
    0x14: ("server_update_time", "uint32", "服务器更新时间 HHMMSS", ()),
    0x15: ("lot_size_info", "uint32", "未确定", ()),
    0x16: ("board_strength", "int32", "板块强度(涨跌家数差)", ("unknown_22",)),
    0x17: ("dividend_yield", "float32", "每股股息(元)", ()),
    0x18: ("bid_volume", "uint32", "买量", ()),
    0x19: ("ask_volume", "uint32", "卖量", ()),
    0x1A: ("last_volume", "uint32", "现量", ()),
    0x1B: ("turnover", "float32", "换手", ()),
    0x1C: ("industry", "uint32", "行业分类代码", ("block5",)),
    0x1D: ("industry_change_up", "float32", "行业涨跌幅", ("block_ext_info",)),
    0x1E: ("stock_tag_flags", "uint32", "股票标签位图", ("some_bitmap",)),
    0x1F: ("decimal_point", "uint32", "数据精度", ()),
    0x20: ("buy_price_limit", "float32", "涨停价", ()),
    0x21: ("sell_price_limit", "float32", "跌停价", ()),
    0x22: ("price_decimal_info", "uint32", "价格精度标志", ("unknown_34",)),
    0x23: ("lot_size", "uint32", "所属地区板块(A股)/每手股数(港股)", ()),
    0x24: ("pre_iopv", "float32", "昨IOPV", ("pre_ipov", "float_shares")),
    0x25: ("speed_pct", "float32", "涨速", ()),
    0x26: ("avg_price", "float32", "均价", ()),
    0x27: ("iopv", "float32", "IOPV", ("ipov", "float_shares2")),
    0x28: ("pe_ttm_vol_related", "float32", "前参考价(美股适用)", ()),
    0x29: ("ex_price_placeholder", "float32", "前金额参考", ("close_placeholder",)),
    0x2A: ("operating_revenue", "float32", "营业收入(万)", ("unknown_42",)),
    0x2B: ("flag_kcb", "uint32", "科创板标志", ("kcb_flag",)),
    0x2C: ("flag_bj", "uint32", "北交所标志", ("bj_flag",)),
    0x2D: ("circulating_capital_z", "float32", "流通股本Z（单位：万股）", ("unknown_45",)),
    0x2E: ("after_hours_volume", "int32", "盘后量", ("gem_star_info", "unknown_46")),
    0x2F: ("unknown_47", "float32", "未知字段 47", ()),
    0x30: ("pe_ttm", "float32", "市盈率TTM", ()),
    0x31: ("pe_static", "float32", "市盈率静", ()),
    0x32: ("unknown_50", "uint32", "未知字段 50", ()),
    0x33: ("unknown_51", "uint32", "未知字段 51", ()),
    0x34: ("unknown_52", "uint32", "未知字段 52", ()),
    0x35: ("unknown_53", "float32", "未知字段 53", ()),
    0x36: ("unknown_54", "float32", "未知字段 54", ()),
    0x37: ("index_metric", "float32", "指数指标", ("unknown_55",)),
    0x38: ("main_net_amount", "float32", "今日主力净流入", ("unknown_close_price",)),
    0x39: ("bid_ask_ratio", "float32", "委比", ("unknown_57",)),
    0x3A: ("non_index_flag", "uint32", "非指数标志", ("unknown_58",)),
    0x3B: ("change_20d_pct", "float32", "20日涨幅%", ()),
    0x3C: ("ytd_pct", "float32", "年初至今%", ()),
    0x3D: ("unknown_61", "float32", "未知字段 61", ()),
    0x3E: ("stock_class_code", "uint32", "证券子分类码", ("unknown_62",)),
    0x3F: ("percent_base", "uint32", "百分比基底", ("unknown_63",)),
    0x40: ("mtd_pct", "float32", "月初至今%", ()),
    0x41: ("change_1y_pct", "float32", "一年涨幅%", ()),
    0x42: ("prev_change_pct", "float32", "昨涨幅%", ()),
    0x43: ("change_3d_pct", "float32", "3日涨幅%", ()),
    0x44: ("change_60d_pct", "float32", "60日涨幅%", ()),
    0x45: ("change_5d_pct", "float32", "5日涨幅%", ()),
    0x46: ("change_10d_pct", "float32", "10日涨幅%", ()),
    0x47: ("prev2_change_pct", "float32", "前日涨幅%", ("unknown_71",)),
    0x48: ("bid2_price", "float32", "买二价", ("low_copy",)),
    0x49: ("ask2_price", "float32", "卖二价", ("low_copy2",)),
    0x4A: ("ah_code", "uint32", "对应A/H股code,不足位数前面补0", ()),
    0x4B: ("unknown_code", "uint32", "少部分有数据,6位数字", ()),
    0x4C: ("unknown_76", "float32", "未知字段 76", ()),
    0x4D: ("unknown_77", "float32", "未知字段 77", ()),
    0x4E: ("unknown_78", "float32", "未知字段 78", ()),
    0x4F: ("unknown_79", "float32", "未知字段 79", ()),
    0x50: ("unknown_80", "float32", "未知字段 80", ()),
    0x51: ("unknown_81", "float32", "未知字段 81", ()),
    0x52: ("unknown_82", "float32", "未知字段 82", ()),
    0x53: ("unknown_83", "float32", "未知字段 83", ()),
    0x54: ("unknown_84", "float32", "未知字段 84", ()),
    0x55: ("unknown_85", "float32", "未知字段 85", ()),
    0x56: ("unknown_86", "float32", "未知字段 86", ()),
    0x57: ("open_amount", "float32", "开盘金额(元)", ()),
    0x58: ("annual_limit_up_days", "int32", "年涨停天数", ()),
    0x59: ("activity", "uint32", "活跃度", ()),
    0x5B: ("dividend_yield_rate", "float32", "股息率%", ("dividend_yield_pct",)),
    0x5C: ("consecutive_up_days", "int32", "连涨天", ()),
    0x5D: ("limit_up_count", "uint32", "涨停数(板块) / 买二量(个股)", ("bid2_volume",)),
    0x5E: ("limit_down_count", "uint32", "跌停数(板块) / 卖二量(个股)", ("ask2_volume",)),
    0x5F: ("industry_sub", "uint32", "行业二级分类", ()),
    0x66: ("auction_buy_limit", "float32", "连续竞价买入上限", ()),
    0x67: ("auction_sell_limit", "float32", "连续竞价卖出下限", ()),
    0x68: ("vol_speed_pct", "float32", "量涨速%", ()),
    0x69: ("short_turnover_pct", "float32", "短换手%", ()),
    0x6A: ("amount_2m", "float32", "2分钟金额(元)", ()),
    0x6B: ("main_net_amount_copy", "float32", "今日主力净流入(副本)", ()),
    0x6C: ("main_net_ratio", "float32", "主力净比%", ()),
    0x6D: ("retail_net_amount", "float32", "散户单增比", ()),
    0x6E: ("main_net_5m_amount", "float32", "5分钟主力净额", ()),
    0x6F: ("main_net_3d_amount", "float32", "近三日主力净额", ()),
    0x70: ("main_net_5d_amount", "float32", "近五日主力净额", ()),
    0x71: ("main_net_10d_amount", "float32", "近十日主买金额(待确定)", ()),
    0x72: ("main_buy_net_amount", "float32", "今日主买净额", ()),
    0x73: ("ddx", "float32", "DDX", ()),
    0x74: ("ddy", "float32", "DDY", ()),
    0x75: ("ddz", "float32", "DDZ", ()),
    0x76: ("ddf", "float32", "DDF", ()),
    0x77: ("stock_flag_a", "float32", "个股标志位A", ()),
    0x78: ("stock_flag_b", "float32", "个股标志位B(副本)", ()),
    0x7A: ("auction_vol_ratio", "float32", "竞价昨比", ()),
    0x7B: ("prev_amount", "float32", "昨成交额(元)", ()),
    0x7D: ("recent_indicator", "float32", "近日指标提示", ()),
    0x80: ("bid3_price", "float32", "买三价", ()),
    0x81: ("bid4_price", "float32", "买四价", ()),
    0x82: ("bid5_price", "float32", "买五价", ()),
    0x83: ("ask3_price", "float32", "卖三价", ()),
    0x84: ("ask4_price", "float32", "卖四价", ()),
    0x85: ("ask5_price", "float32", "卖五价", ("avg_price_copy",)),
    0x86: ("bid3_volume", "uint32", "买三量", ()),
    0x87: ("bid4_volume", "uint32", "买四量", ()),
    0x88: ("up_count", "uint32", "上涨家数(板块) / 买五量(个股)", ("bid5_volume",)),
    0x89: ("ask3_volume", "uint32", "卖三量", ()),
    0x8A: ("ask4_volume", "uint32", "卖四量", ()),
    0x8B: ("down_count", "uint32", "下跌家数(板块) / 卖五量(个股)", ("ask5_volume",)),
    0x8C: ("bid_ask_diff", "int32", "委差", ()),
    0x8D: ("change_up_type", "int32", "封板状态", ()),
    0x8E: ("safety_score", "float32", "安全分", ("constant_neg_one",)),
    0x8F: ("highlight_count", "float32", "亮点数", ("stock_rating",)),
    0x90: ("change_at_1000", "float32", "日内涨幅% 10:00", ()),
    0x91: ("change_at_1030", "float32", "日内涨幅% 10:30", ()),
    0x92: ("change_at_1100", "float32", "日内涨幅% 11:00", ()),
    0x93: ("change_at_1130", "float32", "日内涨幅% 11:30", ()),
    0x94: ("change_at_1330", "float32", "日内涨幅% 13:30", ()),
    0x95: ("change_at_1400", "float32", "日内涨幅% 14:00", ()),
    0x96: ("change_at_1430", "float32", "日内涨幅% 14:30", ()),
}

# gotdx defaultMACBoardMembersQuotesFieldBitmap()。
DEFAULT_MAC_FIELD_BITMAP = bytes(
    [
        0xFF, 0xFC, 0xE1, 0xCC, 0x3F, 0x08, 0x03, 0x01, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ]
)

# gotdx NewMACBoardMembersQuotes 的默认 Extra[21]（选择器字节）。
DEFAULT_MAC_BOARD_MEMBERS_QUOTES_EXTRA = bytes(
    [
        0x00, 0xFF, 0xFC, 0xE1, 0xCC, 0x3F, 0x08, 0x03, 0x01, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00,
    ]
)


def exchange_mac_board_code(board_symbol: str) -> int:
    """Port of gotdx ``ExchangeMACBoardCode`` (proto/mac_util.go)."""

    symbol = str(board_symbol).strip()
    try:
        if symbol.startswith("US"):
            return 30000 + int(symbol[2:])
        if symbol.startswith("HK"):
            return 20000 + int(symbol[2:])
        if symbol.startswith("000"):
            return 31000 + int(symbol)
        if symbol.startswith("399"):
            return int(symbol) - 399000 + 30000
        if symbol.startswith("899"):
            return int(symbol) - 899000 + 32000
        if symbol.startswith("88"):
            return int(symbol) - 880000 + 20000
        return int(symbol)
    except ValueError as exc:
        raise ValueError(f"invalid board symbol {board_symbol!r}") from exc


def mac_industry_board_symbol(industry: int) -> str:
    """Port of gotdx ``macIndustryBoardSymbol`` (field_alignment_helpers.go)."""

    if industry == 0:
        return ""
    return MAC_INDUSTRY_BOARD_SYMBOL_MAP.get(f"{industry % 10000:04d}", "")


def mac_lot_size_board_symbol(lot_size: int) -> str:
    """Port of gotdx ``macLotSizeBoardSymbol`` (field_alignment_helpers.go)."""

    if lot_size == 0:
        return ""
    return str(880200 + lot_size)


def active_mac_dynamic_fields(bitmap: bytes):
    """Port of gotdx ``activeMACDynamicFields``: bitmap bits -> field defs."""

    field_def_cls = import_module(_MODEL_MODULE).MacDynamicFieldDef
    fields = []
    for bit in range(len(bitmap) * 8):
        if not bitmap[bit // 8] & (1 << (bit % 8)):
            continue
        name, format_name, description, aliases = MAC_DYNAMIC_FIELD_DEFS.get(
            bit, (f"unknown_field_{bit}", "uint32", "未映射字段", ())
        )
        fields.append(
            field_def_cls(
                bit=bit,
                name=name,
                format=format_name,
                description=description,
                aliases=aliases,
            )
        )
    return fields


def decode_mac_dynamic_value(format_name: str, raw: bytes) -> Any:
    """Port of gotdx ``decodeMACDynamicValue``: 4 raw bytes -> typed value."""

    if format_name == "uint32":
        return int.from_bytes(raw, "little", signed=False)
    if format_name == "int32":
        return int.from_bytes(raw, "little", signed=True)
    import struct

    return float(struct.unpack("<f", raw)[0])


def __getattr__(name: str) -> Any:
    if name in _MODEL_EXPORTS:
        value = getattr(import_module(_MODEL_MODULE), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _MODEL_EXPORTS)
