"""涨跌停规则核心：与证券名称语义解耦，只认 board / date / st_type / ipo_phase。

本模块不解析证券简称（见 ``names``），所有规则事实以 ``RULE_TABLE`` 为准；
``limit_rule`` 未命中任何区间一律抛 ``MarketRuleError``（**绝不默认 10%**）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _Date
from datetime import datetime
from enum import Enum
from typing import Any

from .compare import round_price

#: 证券简称可解析出的 ST 状态取值
_ST_TYPES = frozenset({"ST", "*ST"})
#: 证券简称可解析出的上市阶段取值
_IPO_PHASES = frozenset({"N", "C"})


class MarketRuleError(ValueError):
    """涨跌停规则无法判定（未命中区间 / 非法入参 / 数据异常）。"""


class Board(Enum):
    """交易板块。"""

    MAIN = "main"  # 沪深主板
    GEM = "gem"  # 创业板（深交所）
    STAR = "star"  # 科创板（上交所）
    BSE = "bse"  # 北交所


#: 各板块开板/开市日（此前无涨跌停规则，判定为 unknown）
_BOARD_OPEN_DATES: dict[Board, _Date] = {
    Board.MAIN: _Date(1996, 12, 16),  # 1996-12-13 证监会通知，1996-12-16 恢复涨跌停板
    Board.GEM: _Date(2009, 10, 30),  # 创业板开板
    Board.STAR: _Date(2019, 7, 22),  # 科创板开板
    Board.BSE: _Date(2021, 11, 15),  # 北交所开市
}

#: 各板块 "C"（上市后前 5 日）标识的最早存在日期；此前出现 C 标志即数据异常
_C_FLAG_FIRST_DATES: dict[Board, _Date] = {
    Board.MAIN: _Date(2023, 4, 10),  # 主板注册制首批上市
    Board.GEM: _Date(2020, 8, 24),  # 创业板注册制改革
    Board.STAR: _Date(2019, 7, 22),
    Board.BSE: _Date(2021, 11, 15),
}


@dataclass(frozen=True, slots=True)
class LimitRule:
    """单日涨跌停规则。

    ratio=None 表示该日不设涨跌停（如新股上市首日/前 5 日）。
    """

    ratio: float | None
    rule_id: str
    source_note: str


@dataclass(frozen=True, slots=True)
class RuleEntry:
    """规则表条目：区间 [start, end]（闭区间，end=None 表示至今）。

    st_types / ipo_phases 为 None 表示"仅当对应状态未设置时匹配"；
    为 frozenset 表示"对应状态须属于该集合"。
    """

    board: Board
    start: _Date
    end: _Date | None
    ratio: float | None
    rule_id: str
    source_note: str
    st_types: frozenset[str] | None = None
    ipo_phases: frozenset[str] | None = None


def _entry(
    board: Board,
    start: str,
    *,
    end: str | None = None,
    ratio: float | None,
    rule_id: str,
    source_note: str,
    st_types: frozenset[str] | None = None,
    ipo_phases: frozenset[str] | None = None,
) -> RuleEntry:
    return RuleEntry(
        board=board,
        start=_Date.fromisoformat(start),
        end=_Date.fromisoformat(end) if end is not None else None,
        ratio=ratio,
        rule_id=rule_id,
        source_note=source_note,
        st_types=st_types,
        ipo_phases=ipo_phases,
    )


#: 生效日期规则表（frozen tuple）。规则事实与监管出处逐条固定，改动需同步更新
#: 测试与上游计划文档。
RULE_TABLE: tuple[RuleEntry, ...] = (
    # ── 沪深主板（1996-12-16 起恢复涨跌停板制度，±10%）──
    _entry(
        Board.MAIN,
        "1996-12-16",
        ratio=10.0,
        rule_id="main_10pct",
        source_note=(
            "证监会 1996-12-13 通知：1996-12-16 起恢复沪深主板涨跌停板制度（±10%）"
        ),
    ),
    _entry(
        Board.MAIN,
        "1996-12-16",
        ratio=5.0,
        rule_id="st_5pct",
        source_note="ST 制度 1998 年起实施，沪深主板 ST 股票涨跌幅限制为 ±5%",
        st_types=frozenset({"ST", "*ST"}),
    ),
    _entry(
        Board.MAIN,
        "1996-12-16",
        ratio=None,
        rule_id="ipo_first_day",
        source_note=(
            "主板新股上市首日不设涨跌幅限制；已知局限：2014-01 至 2023-04-09 主板首日"
            "实际实行 ±44%/-36% 特殊限制（沪深交易所新股首日价格笼子），本模型统一以 "
            "None（不设限）近似"
        ),
        ipo_phases=frozenset({"N"}),
    ),
    _entry(
        Board.MAIN,
        "2023-04-10",
        ratio=None,
        rule_id="ipo_first_5_days",
        source_note=(
            "主板注册制改革：2023-04-10 首批注册制主板股票上市，上市后前 5 个交易日"
            "不设涨跌幅限制"
        ),
        ipo_phases=frozenset({"C"}),
    ),
    # ── 创业板（2009-10-30 开板 ±10%；2020-08-24 注册制改革 ±20%）──
    _entry(
        Board.GEM,
        "2009-10-30",
        end="2020-08-23",
        ratio=10.0,
        rule_id="chinext_10pct",
        source_note=(
            "创业板 2009-10-30 开板至 2020-08-23（注册制改革前）实行 ±10% 涨跌幅限制"
        ),
    ),
    _entry(
        Board.GEM,
        "2009-10-30",
        end="2020-08-23",
        ratio=5.0,
        rule_id="st_5pct",
        source_note="创业板注册制改革前 ST 股票涨跌幅限制为 ±5%",
        st_types=frozenset({"ST", "*ST"}),
    ),
    _entry(
        Board.GEM,
        "2009-10-30",
        end="2020-08-23",
        ratio=None,
        rule_id="ipo_first_day",
        source_note="创业板注册制改革前新股上市首日不设涨跌幅限制（历史口径）",
        ipo_phases=frozenset({"N"}),
    ),
    _entry(
        Board.GEM,
        "2020-08-24",
        ratio=20.0,
        rule_id="chinext_20pct",
        source_note=(
            "创业板注册制改革：2020-08-24 起涨跌幅限制放宽至 ±20%"
            "（深交所创业板改革并试点注册制）"
        ),
    ),
    _entry(
        Board.GEM,
        "2020-08-24",
        ratio=20.0,
        rule_id="chinext_20pct",
        source_note="创业板注册制改革后 ST 股票同样适用 ±20%，无特殊比例",
        st_types=frozenset({"ST", "*ST"}),
    ),
    _entry(
        Board.GEM,
        "2020-08-24",
        ratio=None,
        rule_id="ipo_first_day",
        source_note="创业板注册制改革后新股上市首日不设涨跌幅限制",
        ipo_phases=frozenset({"N"}),
    ),
    _entry(
        Board.GEM,
        "2020-08-24",
        ratio=None,
        rule_id="ipo_first_5_days",
        source_note="创业板注册制改革后新股上市后前 5 个交易日不设涨跌幅限制",
        ipo_phases=frozenset({"C"}),
    ),
    # ── 科创板（2019-07-22 开板，±20%，ST 无特殊比例）──
    _entry(
        Board.STAR,
        "2019-07-22",
        ratio=20.0,
        rule_id="star_20pct",
        source_note="科创板 2019-07-22 开板起涨跌幅限制为 ±20%",
    ),
    _entry(
        Board.STAR,
        "2019-07-22",
        ratio=20.0,
        rule_id="star_20pct",
        source_note="科创板 ST 股票同样适用 ±20%，无特殊比例",
        st_types=frozenset({"ST", "*ST"}),
    ),
    _entry(
        Board.STAR,
        "2019-07-22",
        ratio=None,
        rule_id="ipo_first_day",
        source_note="科创板新股上市首日不设涨跌幅限制",
        ipo_phases=frozenset({"N"}),
    ),
    _entry(
        Board.STAR,
        "2019-07-22",
        ratio=None,
        rule_id="ipo_first_5_days",
        source_note="科创板新股上市后前 5 个交易日不设涨跌幅限制",
        ipo_phases=frozenset({"C"}),
    ),
    # ── 北交所（2021-11-15 开市，±30%，ST 无特殊比例）──
    _entry(
        Board.BSE,
        "2021-11-15",
        ratio=30.0,
        rule_id="bse_30pct",
        source_note="北交所 2021-11-15 开市起涨跌幅限制为 ±30%",
    ),
    _entry(
        Board.BSE,
        "2021-11-15",
        ratio=30.0,
        rule_id="bse_30pct",
        source_note="北交所 ST 股票同样适用 ±30%，无特殊比例",
        st_types=frozenset({"ST", "*ST"}),
    ),
    _entry(
        Board.BSE,
        "2021-11-15",
        ratio=None,
        rule_id="ipo_first_day",
        source_note="北交所新股上市首日不设涨跌幅限制",
        ipo_phases=frozenset({"N"}),
    ),
    _entry(
        Board.BSE,
        "2021-11-15",
        ratio=None,
        rule_id="ipo_first_5_days",
        source_note="北交所新股上市后前 5 个交易日不设涨跌幅限制",
        ipo_phases=frozenset({"C"}),
    ),
)


def _parse_date(value: Any) -> _Date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, _Date):
        return value
    text = str(value or "").strip()
    compact = text[:10].replace("-", "")
    if len(compact) != 8 or not compact.isdigit():
        raise MarketRuleError(f"无效日期: {value!r}（须为 date/ISO 字符串）")
    try:
        return _Date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))
    except ValueError as exc:
        raise MarketRuleError(f"无效日期: {value!r}") from exc


def _validate_status(
    value: Any,
    allowed: frozenset[str],
    field_name: str,
) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text not in allowed:
        raise MarketRuleError(
            f"非法{field_name}: {value!r}（允许值: {', '.join(sorted(allowed))}）"
        )
    return text


def limit_rule(
    *,
    board: Board,
    date: Any,
    st_type: str | None = None,
    ipo_phase: str | None = None,
) -> LimitRule:
    """查表返回指定板块/日期/状态的涨跌停规则；未命中任何区间一律抛错。

    date 接受 datetime.date / datetime 或字符串（``YYYY-MM-DD`` / ``YYYYMMDD``）。
    st_type 仅允许 ``ST`` / ``*ST``，ipo_phase 仅允许 ``N`` / ``C``，且二者互斥
    （证券简称前缀互斥，同时给出视为非法输入）。
    """
    if not isinstance(board, Board):
        raise MarketRuleError(f"非法 board: {board!r}")
    rule_date = _parse_date(date)
    st_type = _validate_status(st_type, _ST_TYPES, "st_type")
    ipo_phase = _validate_status(ipo_phase, _IPO_PHASES, "ipo_phase")
    if st_type is not None and ipo_phase is not None:
        raise MarketRuleError("st_type 与 ipo_phase 互斥（证券简称前缀互斥），不能同时指定")

    open_date = _BOARD_OPEN_DATES[board]
    if rule_date < open_date:
        raise MarketRuleError(
            f"{board.value} 于 {open_date.isoformat()} 才开板/开市，"
            f"{rule_date.isoformat()} 无涨跌停规则（unknown）"
        )

    if ipo_phase == "C" and rule_date < _C_FLAG_FIRST_DATES[board]:
        raise MarketRuleError(
            f"{board.value} 在 {rule_date.isoformat()} 不存在 C 标志（注册制上市后"
            "前 5 日标识），出现即数据异常"
        )

    for entry in RULE_TABLE:
        if entry.board is not board:
            continue
        if not (entry.start <= rule_date and (entry.end is None or rule_date <= entry.end)):
            continue
        if entry.st_types is None:
            if st_type is not None:
                continue
        elif st_type not in entry.st_types:
            continue
        if entry.ipo_phases is None:
            if ipo_phase is not None:
                continue
        elif ipo_phase not in entry.ipo_phases:
            continue
        return LimitRule(ratio=entry.ratio, rule_id=entry.rule_id, source_note=entry.source_note)

    raise MarketRuleError(
        f"未命中任何涨跌停规则区间: board={board.value} date={rule_date.isoformat()} "
        f"st_type={st_type} ipo_phase={ipo_phase}"
    )


def price_limits(pre_close: Any, rule: LimitRule) -> tuple[float | None, float | None]:
    """按规则计算涨跌停价格；rule.ratio 为 None 或缺少前收价时返回 (None, None)。"""
    if rule.ratio is None or pre_close in (None, ""):
        return None, None
    close = float(pre_close)
    return (
        round_price(close * (1.0 + rule.ratio / 100.0)),
        round_price(close * (1.0 - rule.ratio / 100.0)),
    )


def board_from_tdx_code(tdx_code: Any) -> Board:
    """从 TDX 代码判定板块：bj→BSE、sh688→STAR、sz300/301→GEM、
    sh6xx / sz000/001/002/003→MAIN。

    这是对 TDX 代码结构的知识（source 侧知识），置于规则表旁便于消费；无法判定
    一律抛 ``MarketRuleError``，绝不默认主板。
    """
    text = str(tdx_code or "").strip().lower()
    if len(text) != 8:
        raise MarketRuleError(f"无法从 TDX 代码判定板块: {tdx_code!r}（长度须为 8）")
    market = text[:2]
    symbol = text[2:]
    if market == "bj":
        return Board.BSE
    if market == "sh":
        if symbol.startswith("688"):
            return Board.STAR
        if symbol.startswith("6"):
            return Board.MAIN
    if market == "sz":
        if symbol.startswith(("300", "301")):
            return Board.GEM
        if symbol.startswith(("000", "001", "002", "003")):
            return Board.MAIN
    raise MarketRuleError(f"无法从 TDX 代码判定板块: {tdx_code!r}")
