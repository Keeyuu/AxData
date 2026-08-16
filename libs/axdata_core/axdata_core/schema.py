"""Canonical AxData interface schemas."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Field:
    """Field metadata used by storage, query, docs, and quality checks."""

    name: str
    dtype: str
    nullable: bool = True
    description: str = ""
    description_zh: str = ""
    unit: str | None = None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableSchema:
    """Table-level schema metadata."""

    name: str
    fields: tuple[Field, ...]
    primary_key: tuple[str, ...]
    date_field: str | None = None
    datetime_field: str | None = None
    description: str = ""
    display_name_zh: str = ""
    interface_group: str = ""
    status: str = "ready"
    provider_field_mappings: Mapping[str, str] = field(default_factory=dict)

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)

    @property
    def required_fields(self) -> tuple[str, ...]:
        required = {field.name for field in self.fields if not field.nullable}
        required.update(self.primary_key)
        return tuple(name for name in self.field_names if name in required)

    def has_field(self, name: str) -> bool:
        return name in self.field_names


STOCK_BASIC_FIELDS: tuple[Field, ...] = (
    Field(
        "instrument_id",
        "string",
        nullable=False,
        description="AxData stock identifier, e.g. 000001.SZ.",
        description_zh="AxData 统一证券代码，例如 000001.SZ、600000.SH、430047.BJ。",
    ),
    Field(
        "symbol",
        "string",
        nullable=False,
        description="Exchange-local stock code without suffix.",
        description_zh="证券代码，不带交易所后缀，例如 000001。",
    ),
    Field(
        "exchange",
        "string",
        nullable=False,
        description="Exchange code: SSE, SZSE, or BSE.",
        description_zh="交易所代码，建议值为 SSE、SZSE、BSE。",
    ),
    Field(
        "asset_type",
        "string",
        nullable=False,
        description="Asset type, fixed to stock for stock basic interfaces.",
        description_zh="资产类型，本接口固定为 stock。",
    ),
    Field(
        "name",
        "string",
        nullable=False,
        description="Security short name.",
        description_zh="证券简称。",
    ),
    Field(
        "security_full_name",
        "string",
        description="Security full name when available.",
        description_zh="证券全称；没有时为空。",
    ),
    Field(
        "market_code",
        "string",
        description="Market board code when available.",
        description_zh="市场板块代码；没有时为空。",
    ),
    Field(
        "market",
        "string",
        description="Market board name.",
        description_zh="市场板块名称，例如主板、创业板、科创板、北交所。",
    ),
    Field(
        "industry_code",
        "string",
        description="Industry code when available.",
        description_zh="行业代码；没有时为空。",
    ),
    Field(
        "industry",
        "string",
        description="Industry name when available.",
        description_zh="行业名称；没有时为空。",
    ),
    Field(
        "region_code",
        "string",
        description="Region code when available.",
        description_zh="地区代码；没有时为空。",
    ),
    Field(
        "region",
        "string",
        description="Company region when available.",
        description_zh="地区名称；没有时为空。",
    ),
    Field(
        "company_code",
        "string",
        description="Company code when available.",
        description_zh="公司代码；没有时为空。",
    ),
    Field(
        "company_short_name",
        "string",
        description="Company short name when available.",
        description_zh="公司简称；没有时为空。",
    ),
    Field(
        "company_full_name",
        "string",
        description="Company full legal name when available.",
        description_zh="公司法定全称；没有时为空。",
    ),
    Field(
        "company_short_name_en",
        "string",
        description="Company English short name when available.",
        description_zh="公司英文简称；没有时为空。",
    ),
    Field(
        "company_full_name_en",
        "string",
        description="Company English full name when available.",
        description_zh="公司英文全称；没有时为空。",
    ),
    Field(
        "listing_status",
        "string",
        nullable=False,
        description="AxData listing status: listed, delisted, suspended, or unknown.",
        description_zh="AxData 上市状态，建议值 listed、delisted、suspended、unknown。",
    ),
    Field(
        "list_date",
        "string",
        description="Listing date in YYYYMMDD format.",
        description_zh="上市日期，格式为 YYYYMMDD。",
    ),
    Field(
        "delist_date",
        "string",
        description="Delisting date in YYYYMMDD format.",
        description_zh="退市日期，格式为 YYYYMMDD；未退市为空。",
    ),
    Field(
        "total_share",
        "float64",
        description="Total shares, unit: 100 million shares.",
        description_zh="总股本，单位：亿股；没有时为空。",
    ),
    Field(
        "float_share",
        "float64",
        description="Tradable shares, unit: 100 million shares.",
        description_zh="流通股本，单位：亿股；没有时为空。",
    ),
    Field(
        "is_profit",
        "string",
        description="Profitability marker when available.",
        description_zh="是否尚未盈利；没有时为空。",
    ),
    Field(
        "is_vie",
        "string",
        description="VIE/control-structure marker when available.",
        description_zh="是否具有协议控制架构；没有时为空。",
    ),
    Field(
        "has_weighted_voting_rights",
        "string",
        description="Weighted voting rights marker when available.",
        description_zh="是否具有表决权差异安排；没有时为空。",
    ),
    Field(
        "sponsor",
        "string",
        description="Sponsoring broker or listing sponsor when available.",
        description_zh="保荐机构或主办券商；没有时为空。",
    ),
    Field(
        "share_report_date",
        "string",
        description="Share capital report date in YYYYMMDD format when available.",
        description_zh="股本数据报告日期，格式为 YYYYMMDD；没有时为空。",
    ),
)


def _kline_fields(*, index: bool = False) -> tuple[Field, ...]:
    """Shared TDX kline columns.

    ``trade_time`` is the bar CLOSE time in ISO-8601 with +08:00 (TDX labels
    bars by close time); ``period`` is part of the primary key so multiple
    periods coexist in one table. ``>=15m`` periods are synthesized locally
    from 5m and never stored (plan axdata-integration/18).
    """

    fields: tuple[Field, ...] = (
        Field(
            "instrument_id",
            "string",
            nullable=False,
            aliases=("ts_code",),
            description="AxData instrument identifier, e.g. 000001.SZ.",
            description_zh="AxData 统一证券代码，例如 000001.SZ。",
        ),
        Field(
            "symbol",
            "string",
            description="Plain symbol without exchange suffix, e.g. 000001.",
            description_zh="不带交易所后缀的代码，例如 000001。",
        ),
        Field(
            "tdx_code",
            "string",
            description="TDX source code, e.g. sz000001.",
            description_zh="通达信源代码，例如 sz000001。",
        ),
        Field(
            "exchange",
            "string",
            description="Exchange code: SSE / SZSE / BSE.",
            description_zh="交易所代码：SSE / SZSE / BSE。",
        ),
        Field(
            "trade_time",
            "string",
            nullable=False,
            aliases=("trade_date",),
            description="Bar close time, ISO-8601 with +08:00 offset (close-time labeled).",
            description_zh="bar 收盘时刻，ISO-8601 含 +08:00 时区（收盘时刻标记）。",
        ),
        Field(
            "period",
            "string",
            nullable=False,
            description="Bar period: day / 1m / 5m (15m+ synthesized locally from 5m).",
            description_zh="周期：day / 1m / 5m（15m 及以上由 5m 本地合成，不落库）。",
        ),
        Field("open", "double", description="Open price.", description_zh="开盘价。"),
        Field("high", "double", description="High price.", description_zh="最高价。"),
        Field("low", "double", description="Low price.", description_zh="最低价。"),
        Field("close", "double", description="Close price.", description_zh="收盘价。"),
        Field(
            "volume",
            "double",
            aliases=("vol",),
            description="Bar volume in source (TDX) units.",
            description_zh="成交量（TDX 源口径）。",
        ),
        Field(
            "amount",
            "double",
            description="Bar turnover amount in source (TDX) units.",
            description_zh="成交额（TDX 源口径）。",
        ),
    )
    if index:
        fields += (
            Field(
                "up_count",
                "int64",
                description="Rising member count on index bars.",
                description_zh="上涨家数（指数 bar）。",
            ),
            Field(
                "down_count",
                "int64",
                description="Falling member count on index bars.",
                description_zh="下跌家数（指数 bar）。",
            ),
        )
    return fields


INDEX_CATALOG_FIELDS: tuple[Field, ...] = (
    Field(
        "instrument_id",
        "string",
        nullable=False,
        description="AxData index identifier, e.g. 000001.SH.",
        description_zh="AxData 指数代码，例如 000001.SH。",
    ),
    Field(
        "symbol",
        "string",
        description="Plain index symbol without exchange suffix.",
        description_zh="不带交易所后缀的指数代码。",
    ),
    Field(
        "tdx_code",
        "string",
        description="TDX source code, e.g. sh000001.",
        description_zh="通达信源代码，例如 sh000001。",
    ),
    Field(
        "exchange",
        "string",
        description="Exchange code: SSE / SZSE / BSE.",
        description_zh="交易所代码：SSE / SZSE / BSE。",
    ),
    Field(
        "name",
        "string",
        description="Index display name.",
        description_zh="指数名称。",
    ),
    Field(
        "index_type",
        "string",
        description="Index category tag: official_index / tdx_block_index (sector & theme).",
        description_zh="指数分类标签：official_index（官方）/ tdx_block_index（通达信板块·题材）。",
    ),
    Field(
        "previous_close",
        "double",
        description="Previous close captured with the daily directory snapshot.",
        description_zh="随每日目录快照留痕的昨收。",
    ),
)


CAPITAL_FLOW_FIELDS: tuple[Field, ...] = (
    Field(
        "instrument_id",
        "string",
        nullable=False,
        aliases=("ts_code",),
        description="AxData instrument identifier, e.g. 000001.SZ.",
        description_zh="AxData 统一证券代码，例如 000001.SZ。",
    ),
    Field(
        "trade_date",
        "string",
        nullable=False,
        description="Snapshot trade date in YYYYMMDD format.",
        description_zh="快照交易日，格式为 YYYYMMDD。",
    ),
    Field(
        "today_main_in",
        "double",
        description="TDX main-force inflow today (source vocabulary kept verbatim).",
        description_zh="今日主力流入（通达信源口径，命名保持源词汇）。",
    ),
    Field(
        "today_main_out",
        "double",
        description="TDX main-force outflow today.",
        description_zh="今日主力流出（通达信源口径）。",
    ),
    Field(
        "today_retail_in",
        "double",
        description="TDX retail inflow today.",
        description_zh="今日散户流入（通达信源口径）。",
    ),
    Field(
        "today_retail_out",
        "double",
        description="TDX retail outflow today.",
        description_zh="今日散户流出（通达信源口径）。",
    ),
    Field(
        "today_main_net",
        "double",
        description="TDX main-force net today (in - out).",
        description_zh="今日主力净额（入-出）。",
    ),
    Field(
        "today_retail_net",
        "double",
        description="TDX retail net today (in - out).",
        description_zh="今日散户净额（入-出）。",
    ),
    Field(
        "five_day_main_buy",
        "double",
        description="TDX 5-day main-force buy.",
        description_zh="五日主力买入（通达信源口径）。",
    ),
    Field(
        "five_day_main_sell",
        "double",
        description="TDX 5-day main-force sell.",
        description_zh="五日主力卖出（通达信源口径）。",
    ),
    Field(
        "five_day_super_net",
        "double",
        description="TDX 5-day super-large order net.",
        description_zh="五日超大单净额（通达信源口径）。",
    ),
    Field(
        "five_day_large_net",
        "double",
        description="TDX 5-day large order net.",
        description_zh="五日大单净额（通达信源口径）。",
    ),
    Field(
        "five_day_medium_net",
        "double",
        description="TDX 5-day medium order net.",
        description_zh="五日中单净额（通达信源口径）。",
    ),
    Field(
        "five_day_small_net",
        "double",
        description="TDX 5-day small order net.",
        description_zh="五日小单净额（通达信源口径）。",
    ),
    Field(
        "five_day_main_net",
        "double",
        description="TDX 5-day main-force net (buy - sell).",
        description_zh="五日主力净额（买-卖）。",
    ),
)

THEME_MEMBERS_FIELDS: tuple[Field, ...] = (
    Field(
        "theme_code",
        "string",
        nullable=False,
        description="ICFQS theme code; 880-series use setcode 2, numeric themes use 1.",
        description_zh="题材代码；880 系 setcode=2，数字新题材 setcode=1。",
    ),
    Field(
        "setcode",
        "string",
        nullable=False,
        description="Theme code space; PK includes it because 880 and numeric codes may collide.",
        description_zh="题材代码空间；880 系与数字系可能重码，故入主键。",
    ),
    Field(
        "instrument_id",
        "string",
        nullable=False,
        description="AxData instrument identifier of the member stock.",
        description_zh="成分股 AxData 统一证券代码。",
    ),
    Field(
        "as_of_date",
        "string",
        nullable=False,
        description="PIT snapshot trade date in YYYYMMDD (trade calendar day, not wall clock).",
        description_zh="PIT 留痕交易日（交易日历日，非自然日），格式 YYYYMMDD。",
    ),
    Field(
        "instrument_name",
        "string",
        description="Member stock display name at snapshot time.",
        description_zh="快照时成分股名称。",
    ),
    Field(
        "symbol",
        "string",
        description="Plain symbol without exchange suffix, e.g. 000001.",
        description_zh="不带交易所后缀的代码，例如 000001。",
    ),
    Field(
        "exchange",
        "string",
        description="Exchange code: SSE / SZSE / BSE.",
        description_zh="交易所代码：SSE / SZSE / BSE。",
    ),
    Field(
        "join_reason",
        "string",
        description="ICFQS join-reason text.",
        description_zh="ICFQS 入选理由文本。",
    ),
    Field(
        "join_date",
        "string",
        description="ICFQS join date (YYYY-MM-DD as served).",
        description_zh="ICFQS 入选日期（源格式 YYYY-MM-DD）。",
    ),
)

THEME_EVENTS_FIELDS: tuple[Field, ...] = (
    Field(
        "theme_code",
        "string",
        nullable=False,
        description="ICFQS theme code.",
        description_zh="题材代码。",
    ),
    Field(
        "event_date",
        "string",
        nullable=False,
        description="Theme event date in YYYYMMDD format.",
        description_zh="题材事件日期，格式 YYYYMMDD。",
    ),
    Field(
        "as_of_date",
        "string",
        nullable=False,
        description="PIT snapshot trade date in YYYYMMDD.",
        description_zh="PIT 留痕交易日，格式 YYYYMMDD。",
    ),
    Field("theme_name", "string", description="Theme display name.", description_zh="题材名称。"),
    Field(
        "event_text",
        "string",
        description="Theme event description text.",
        description_zh="题材事件描述文本。",
    ),
    Field(
        "member_codes",
        "string",
        description="Raw member list as served (e.g. '0_300243,1_688598').",
        description_zh="成分代码原样串（如 '0_300243,1_688598'）。",
    ),
    Field(
        "change_pct",
        "double",
        description="Theme change percent served with the event row.",
        description_zh="随事件行返回的题材涨跌幅。",
    ),
)


SCHEMAS: dict[str, TableSchema] = {
    "stock_basic_exchange": TableSchema(
        name="stock_basic_exchange",
        primary_key=("instrument_id",),
        date_field="list_date",
        description="Stock list in official exchange interface口径.",
        display_name_zh="股票列表（交易所）",
        interface_group="本地数据/股票/基础资料",
        fields=STOCK_BASIC_FIELDS,
    ),
    "trade_cal": TableSchema(
        name="trade_cal",
        primary_key=("exchange", "cal_date"),
        date_field="cal_date",
        description="Trading calendar by exchange.",
        display_name_zh="交易日历",
        interface_group="本地数据/股票/基础资料",
        fields=(
            Field(
                "exchange",
                "string",
                nullable=False,
                description="Exchange code.",
                description_zh="交易所代码。",
            ),
            Field(
                "cal_date",
                "string",
                nullable=False,
                description="Calendar date in YYYYMMDD format.",
                description_zh="自然日期，格式为 YYYYMMDD。",
            ),
            Field(
                "is_open",
                "int64",
                nullable=False,
                description="1 for trading day, 0 otherwise.",
                description_zh="是否交易日，1 表示交易日，0 表示非交易日。",
            ),
            Field(
                "pretrade_date",
                "string",
                description="Previous trading date in YYYYMMDD format.",
                description_zh="上一个交易日，格式为 YYYYMMDD。",
            ),
        ),
    ),
    "daily": TableSchema(
        name="daily",
        primary_key=("instrument_id", "trade_time", "period"),
        date_field="trade_time",
        description="Daily OHLCV market data (TDX reload, qfq, close-time labeled).",
        display_name_zh="个股日线行情",
        interface_group="本地数据/股票/行情数据",
        fields=_kline_fields(),
    ),
    "adj_factor": TableSchema(
        name="adj_factor",
        primary_key=("ts_code", "trade_date"),
        date_field="trade_date",
        description="Daily adjustment factors.",
        display_name_zh="复权因子",
        interface_group="本地数据/股票/复权与股本",
        fields=(
            Field(
                "ts_code",
                "string",
                nullable=False,
                description="AxData stock identifier.",
                description_zh="AxData 统一证券代码，例如 000001.SZ。",
                aliases=("instrument_id",),
            ),
            Field(
                "trade_date",
                "string",
                nullable=False,
                description="Trading date in YYYYMMDD format.",
                description_zh="交易日期，格式为 YYYYMMDD。",
            ),
            Field(
                "adj_factor",
                "float64",
                nullable=False,
                description="Adjustment factor.",
                description_zh="复权因子。",
            ),
        ),
    ),
    "minute": TableSchema(
        name="minute",
        primary_key=("instrument_id", "trade_time", "period"),
        date_field="trade_time",
        description="Stock minute bars, native periods 1m/5m only (plan 18).",
        display_name_zh="个股分钟行情（1m/5m）",
        interface_group="本地数据/股票/行情数据",
        fields=_kline_fields(),
    ),
    "index_daily": TableSchema(
        name="index_daily",
        primary_key=("instrument_id", "trade_time", "period"),
        date_field="trade_time",
        description="Index daily bars incl. TDX 880/881 sector/theme indices.",
        display_name_zh="指数日线行情",
        interface_group="本地数据/指数/行情数据",
        fields=_kline_fields(index=True),
    ),
    "index_minute": TableSchema(
        name="index_minute",
        primary_key=("instrument_id", "trade_time", "period"),
        date_field="trade_time",
        description="Index minute bars, native periods 1m/5m only (plan 18).",
        display_name_zh="指数分钟行情（1m/5m）",
        interface_group="本地数据/指数/行情数据",
        fields=_kline_fields(index=True),
    ),
    "index_catalog": TableSchema(
        name="index_catalog",
        primary_key=("instrument_id",),
        date_field=None,
        description="Index directory incl. TDX 880/881 sector/theme indices (daily PIT snapshot).",
        display_name_zh="指数目录（含板块/题材）",
        interface_group="本地数据/指数/基础资料",
        fields=INDEX_CATALOG_FIELDS,
    ),
    "capital_flow": TableSchema(
        name="capital_flow",
        primary_key=("instrument_id", "trade_date"),
        date_field="trade_date",
        description="TDX MAC capital-flow daily snapshot (today + 5-day buckets, plan 19).",
        display_name_zh="个股资金流（每日留痕）",
        interface_group="本地数据/股票/资金流",
        fields=CAPITAL_FLOW_FIELDS,
    ),
    "theme_members": TableSchema(
        name="theme_members",
        primary_key=("theme_code", "setcode", "instrument_id", "as_of_date"),
        date_field="as_of_date",
        description="ICFQS theme constituents PIT snapshot with join reason and date (plan 19).",
        display_name_zh="题材成分（PIT 留痕）",
        interface_group="本地数据/题材/成分",
        fields=THEME_MEMBERS_FIELDS,
    ),
    "theme_events": TableSchema(
        name="theme_events",
        primary_key=("theme_code", "event_date", "as_of_date"),
        date_field="as_of_date",
        description="ICFQS theme event calendar snapshot (plan 19).",
        display_name_zh="题材事件日历（留痕）",
        interface_group="本地数据/题材/事件",
        fields=THEME_EVENTS_FIELDS,
    ),
}

TABLE_ALIASES: dict[str, str] = {
    "stock_basic": "stock_basic_exchange",
    "stock-basic": "stock_basic_exchange",
    "stock-basic-exchange": "stock_basic_exchange",
    "stock_basic_exchange": "stock_basic_exchange",
}


def normalize_table_name(table: str) -> str:
    normalized = table.strip().lower()
    return TABLE_ALIASES.get(normalized, normalized)


def list_tables(*, include_aliases: bool = False) -> tuple[str, ...]:
    tables = tuple(SCHEMAS)
    if include_aliases:
        return tuple(dict.fromkeys((*tables, *TABLE_ALIASES)))
    return tables


def get_schema(table: str) -> TableSchema:
    table_name = normalize_table_name(table)
    try:
        return SCHEMAS[table_name]
    except KeyError as exc:
        known = ", ".join(list_tables())
        raise KeyError(f"Unknown AxData table {table!r}. Known tables: {known}.") from exc


def require_fields(table: str, fields: Iterable[str]) -> None:
    schema = get_schema(table)
    missing = [field for field in fields if not schema.has_field(field)]
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"Unknown field(s) for {table!r}: {missing_text}.")
