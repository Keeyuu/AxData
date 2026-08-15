"""axdata_core.market_rules 公共设施测试。

覆盖：规则表四板块 × 日期分界 × ST × N/C 全网格、未命中一律抛错（绝不默认 10%）、
S*ST/SST 解析、compare 舍入/容差边界、sessions 两方向，以及涨跌停价路径与连板天梯
路径对同一 (code, name, date) 的判定一致性回归（防止回退到各自解析简称的旧实现）。

监管依据：规则表条目来自证监会/交易所公开规则（见 RULE_TABLE.source_note）；
测试中被钉的比例在更新处均附监管依据注释。
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from axdata_core.market_rules import (
    HALF_TICK,
    RULE_TABLE,
    Board,
    MarketRuleError,
    board_from_tdx_code,
    ipo_phase_from_name,
    limit_rule,
    price_at_or_above,
    price_close,
    price_limits,
    round_price,
    session_context,
    st_type_from_name,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "axdata-source-tdx" / "src"))

from axdata_source_tdx.derived_rows import (  # noqa: E402
    limit_ladder_needs_name_lookup,
    normalize_daily_price_limit_from_pre_close,
    normalize_limit_ladder_row,
)

# ── 规则表：四板块 × 日期分界 × ST × N/C 全网格 ──────────────────────────────

_RuleExpectation = tuple[float | None, str] | None


@pytest.mark.parametrize(
    ("rule_date", "st_type", "ipo_phase", "expected"),
    [
        # 主板：1996-12-16 恢复涨跌停板（证监会 1996-12-13 通知），此前无规则
        ("1996-12-15", None, None, None),
        ("1996-12-16", None, None, (10.0, "main_10pct")),
        ("2026-06-17", None, None, (10.0, "main_10pct")),
        # 主板 ST：ST 制度 1998 年起，ST/*ST ±5%
        ("1996-12-16", "ST", None, (5.0, "st_5pct")),
        ("1996-12-16", "*ST", None, (5.0, "st_5pct")),
        ("2026-06-17", "ST", None, (5.0, "st_5pct")),
        # 主板新股：N 首日不设限；C 仅注册制（2023-04-10 首批上市）后存在
        ("2026-06-17", None, "N", (None, "ipo_first_day")),
        ("2023-04-10", None, "C", (None, "ipo_first_5_days")),
        ("2026-06-17", None, "C", (None, "ipo_first_5_days")),
        ("2023-04-09", None, "C", None),
        ("2020-01-02", None, "C", None),
    ],
)
def test_limit_rule_main_grid(rule_date, st_type, ipo_phase, expected):
    _assert_rule_expectation(Board.MAIN, rule_date, st_type, ipo_phase, expected)


@pytest.mark.parametrize(
    ("rule_date", "st_type", "ipo_phase", "expected"),
    [
        # 创业板：2009-10-30 开板前无规则
        ("2009-10-29", None, None, None),
        # 开板至 2020-08-23：±10%，ST ±5%
        ("2009-10-30", None, None, (10.0, "chinext_10pct")),
        ("2020-08-23", None, None, (10.0, "chinext_10pct")),
        ("2020-08-23", "ST", None, (5.0, "st_5pct")),
        # 2020-08-24 注册制改革起：±20%，ST 也是 20%（无特殊比例）
        ("2020-08-24", None, None, (20.0, "chinext_20pct")),
        ("2020-08-24", "ST", None, (20.0, "chinext_20pct")),
        ("2026-06-17", "*ST", None, (20.0, "chinext_20pct")),
        # 新股：改革前 N 首日不设限；改革后 N/C 均不设限；改革前 C 不存在
        ("2020-08-23", None, "N", (None, "ipo_first_day")),
        ("2020-08-24", None, "N", (None, "ipo_first_day")),
        ("2020-08-24", None, "C", (None, "ipo_first_5_days")),
        ("2020-08-23", None, "C", None),
    ],
)
def test_limit_rule_gem_grid(rule_date, st_type, ipo_phase, expected):
    _assert_rule_expectation(Board.GEM, rule_date, st_type, ipo_phase, expected)


@pytest.mark.parametrize(
    ("rule_date", "st_type", "ipo_phase", "expected"),
    [
        ("2019-07-21", None, None, None),
        ("2019-07-22", None, None, (20.0, "star_20pct")),
        ("2019-07-22", "ST", None, (20.0, "star_20pct")),
        ("2026-06-17", "*ST", None, (20.0, "star_20pct")),
        ("2019-07-22", None, "N", (None, "ipo_first_day")),
        ("2019-07-22", None, "C", (None, "ipo_first_5_days")),
    ],
)
def test_limit_rule_star_grid(rule_date, st_type, ipo_phase, expected):
    _assert_rule_expectation(Board.STAR, rule_date, st_type, ipo_phase, expected)


@pytest.mark.parametrize(
    ("rule_date", "st_type", "ipo_phase", "expected"),
    [
        ("2021-11-14", None, None, None),
        ("2021-11-15", None, None, (30.0, "bse_30pct")),
        ("2021-11-15", "ST", None, (30.0, "bse_30pct")),
        ("2026-06-17", "*ST", None, (30.0, "bse_30pct")),
        ("2021-11-15", None, "N", (None, "ipo_first_day")),
        ("2021-11-15", None, "C", (None, "ipo_first_5_days")),
    ],
)
def test_limit_rule_bse_grid(rule_date, st_type, ipo_phase, expected):
    _assert_rule_expectation(Board.BSE, rule_date, st_type, ipo_phase, expected)


def _assert_rule_expectation(
    board: Board,
    rule_date: str,
    st_type: str | None,
    ipo_phase: str | None,
    expected: _RuleExpectation,
) -> None:
    if expected is None:
        with pytest.raises(MarketRuleError):
            limit_rule(board=board, date=rule_date, st_type=st_type, ipo_phase=ipo_phase)
        return
    rule = limit_rule(board=board, date=rule_date, st_type=st_type, ipo_phase=ipo_phase)
    assert (rule.ratio, rule.rule_id) == expected


def test_limit_rule_never_defaults_ratio_for_unmatched_inputs():
    # 红线：未命中任何区间一律抛 MarketRuleError，绝不默认 10%
    with pytest.raises(MarketRuleError):
        limit_rule(board=Board.MAIN, date="1990-01-01")
    with pytest.raises(MarketRuleError):
        limit_rule(board=Board.MAIN, date="1996-12-15", st_type="ST")
    # 非法状态取值
    with pytest.raises(MarketRuleError):
        limit_rule(board=Board.MAIN, date="2026-06-17", st_type="PT")
    with pytest.raises(MarketRuleError):
        limit_rule(board=Board.MAIN, date="2026-06-17", ipo_phase="X")
    # st_type 与 ipo_phase 互斥（证券简称前缀互斥）
    with pytest.raises(MarketRuleError):
        limit_rule(board=Board.MAIN, date="2026-06-17", st_type="ST", ipo_phase="N")
    with pytest.raises(MarketRuleError):
        limit_rule(board="main", date="2026-06-17")
    with pytest.raises(MarketRuleError):
        limit_rule(board=Board.MAIN, date="2026061")  # 无效日期


def test_limit_rule_accepts_date_objects_and_compact_strings():
    rule = limit_rule(board=Board.GEM, date=date(2020, 8, 24))
    assert rule.ratio == 20.0
    assert limit_rule(board=Board.GEM, date="20200824").ratio == 20.0
    assert limit_rule(board=Board.GEM, date="2020-08-24").ratio == 20.0


def test_rule_table_entries_carry_regulatory_source_notes():
    assert RULE_TABLE
    assert all(entry.source_note for entry in RULE_TABLE)
    assert all(entry.rule_id for entry in RULE_TABLE)
    assert all(entry.board in Board for entry in RULE_TABLE)


def test_price_limits_computes_round_trip():
    rule = limit_rule(board=Board.MAIN, date="2026-06-17")
    assert price_limits(8.0, rule) == (8.8, 7.2)
    assert price_limits(10.14, rule) == (11.15, 9.13)
    no_limit = limit_rule(board=Board.MAIN, date="2026-06-17", ipo_phase="N")
    assert price_limits(8.0, no_limit) == (None, None)
    assert price_limits(None, rule) == (None, None)


def test_board_from_tdx_code_full_mapping():
    assert board_from_tdx_code("bj430001") is Board.BSE
    assert board_from_tdx_code("sh688001") is Board.STAR
    assert board_from_tdx_code("sz300001") is Board.GEM
    assert board_from_tdx_code("sz301001") is Board.GEM
    assert board_from_tdx_code("sh600000") is Board.MAIN
    assert board_from_tdx_code("sh603000") is Board.MAIN
    assert board_from_tdx_code("sz000001") is Board.MAIN
    assert board_from_tdx_code("sz002001") is Board.MAIN
    assert board_from_tdx_code("sz003001") is Board.MAIN
    with pytest.raises(MarketRuleError):
        board_from_tdx_code("sz200001")  # 深 B 股：无法判定
    with pytest.raises(MarketRuleError):
        board_from_tdx_code("sh900001")  # 沪 B 股：无法判定
    with pytest.raises(MarketRuleError):
        board_from_tdx_code("600000")  # 长度不为 8
    with pytest.raises(MarketRuleError):
        board_from_tdx_code("")


# ── 证券简称状态解析 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ST国华", "ST"),
        ("st 国华", "ST"),
        ("SST 测试", "ST"),
        ("S*ST 示例", "*ST"),
        ("*ST 示例", "*ST"),
        ("S*ST", "*ST"),
        ("平安银行", None),
        ("N新股", None),
        ("", None),
        (None, None),
    ],
)
def test_st_type_from_name_absorbs_legacy_prefixes(name, expected):
    assert st_type_from_name(name) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("N新股", "N"),
        ("n新股", "N"),
        ("C测试", "C"),
        ("c 测试", "C"),
        ("平安银行", None),
        ("ST国华", None),
        ("", None),
        (None, None),
    ],
)
def test_ipo_phase_from_name_prefix_match(name, expected):
    assert ipo_phase_from_name(name) == expected


def test_st_and_ipo_flags_are_mutually_exclusive():
    # 顺序问题不存在：N/C 与 ST 前缀互斥，同一简称只会命中其中一个
    for name in ("ST国华", "*ST示例", "N新股", "C测试", "平安银行"):
        st = st_type_from_name(name)
        ipo = ipo_phase_from_name(name)
        assert not (st is not None and ipo is not None)


# ── compare：舍入与容差边界 ──────────────────────────────────────────────────


def test_round_price_semantics():
    assert round_price(8.876) == 8.88
    assert round_price(8.874) == 8.87
    assert round_price(8.876, digits=1) == 8.9
    assert round_price(None) is None
    assert round_price("") is None


def test_compare_boundaries_use_half_tick():
    # HALF_TICK = 半个最小报价单位(0.005) + 浮点容差(1e-9)，替代旧魔法数 0.0051
    assert HALF_TICK == 0.005 + 1e-9
    assert price_close(8.8, 8.8) is True
    assert price_close(8.8, 8.8 + 0.005) is True  # 半个报价单位以内 → 相等
    assert price_close(8.8, 8.81) is False  # 差一个最小报价单位 → 不相等
    # 旧魔法数 0.0051 会把差 0.0051 的两个价格误判为相等，新容差不会
    assert price_close(8.8, 8.8 + 0.0051) is False
    assert price_close(None, 8.8) is False
    assert price_at_or_above(8.81, 8.8) is True
    assert price_at_or_above(8.8, 8.81) is False
    assert price_at_or_above(None, 8.8) is False


# ── sessions：交易日上下文两方向 ─────────────────────────────────────────────


def test_session_context_open_day():
    rows = [
        {
            "cal_date": "20260622",
            "is_open": True,
            "pretrade_date": "20260619",
            "next_trade_date": "20260623",
        },
    ]
    ctx = session_context(rows, date(2026, 6, 22))
    assert ctx.is_open is True
    assert ctx.pretrade_date == "20260619"
    assert ctx.next_trade_date == "20260623"
    assert ctx.target_for_preview == "20260622"  # 开市 → 今天
    assert ctx.target_for_review == "20260622"  # 开市 → 今天


def test_session_context_closed_day_directions():
    rows = [
        {
            "cal_date": "20260620",
            "is_open": 0,
            "pretrade_date": "20260619",
            "next_trade_date": "20260622",
        },
    ]
    ctx = session_context(rows, "20260620")
    assert ctx.is_open is False
    assert ctx.target_for_preview == "20260622"  # 休市 → 下一交易日
    assert ctx.target_for_review == "20260619"  # 休市 → 前一交易日（pretrade）


def test_session_context_accepts_int_and_string_open_flags():
    rows = [
        {"cal_date": "20260622", "is_open": "1", "pretrade_date": "20260619"},
    ]
    assert session_context(rows, "20260622").is_open is True


def test_session_context_missing_today_raises():
    rows = [
        {"cal_date": "20260622", "is_open": True, "pretrade_date": "20260619"},
    ]
    with pytest.raises(ValueError):
        session_context(rows, date(2026, 6, 23))


# ── 矛盾回归：涨跌停价路径与连板天梯路径判定一致 ──────────────────────────────


def test_price_limit_row_and_ladder_paths_agree_on_sst_name():
    # 旧实现矛盾：price_limit_name_flag 判不出 S*ST（name_flag=None，走普通比例），
    # 连板天梯路径却按 st_type_from_name 把 S*ST 当 ST 排除——同一名称两路径结论不同。
    # 迁移后两路径统一用 market_rules.names.st_type_from_name，S*ST 一律视为 *ST。
    ladder = normalize_limit_ladder_row(
        {
            "tdx_code": "sz300001",
            "last_price": 11.5,
            "pre_close": 10.0,
            "high": 11.9,
            "amount": 100.0,
            "locked_amount": 0,
            "bid1_price": 11.9,
        },
        stats=SimpleNamespace(stats_date="20260617"),
        name="S*ST 示例",
        boards=None,
        include_touched=True,
    )
    assert ladder is None  # 连板天梯路径把 S*ST 视为 ST 并排除

    # 涨跌停价路径对同一名称给出同一 st_type，并按 ST 规则取比例：
    # 主板 ST=5%（ST 制度 1998 年起）；创业板注册制后 ST=20%（2020-08-24 起，无特殊比例）
    for code, expected_ratio in (("sh600001", 5.0), ("sz300001", 20.0)):
        row = normalize_daily_price_limit_from_pre_close(
            code,
            target_trade_date="20260617",
            pre_close_trade_date="20260616",
            pre_close=10.0,
            pre_close_source="tdx_daily_kline",
            name="S*ST 示例",
        )
        assert row["name_flag"] == st_type_from_name("S*ST 示例") == "*ST"
        assert row["limit_ratio_pct"] == expected_ratio


def test_gem_limit_ratio_flips_at_registration_reform_boundary():
    # 2020-08-24 创业板注册制改革：±10% → ±20%（深交所创业板改革并试点注册制）
    before = normalize_daily_price_limit_from_pre_close(
        "sz300001",
        target_trade_date="2020-08-23",
        pre_close_trade_date="2020-08-21",
        pre_close=10.0,
        pre_close_source="tdx_daily_kline",
        name="测试A",
    )
    after = normalize_daily_price_limit_from_pre_close(
        "sz300001",
        target_trade_date="2020-08-24",
        pre_close_trade_date="2020-08-21",
        pre_close=10.0,
        pre_close_source="tdx_daily_kline",
        name="测试A",
    )
    assert before["limit_ratio_pct"] == 10.0
    assert before["limit_rule"] == "chinext_10pct"
    assert after["limit_ratio_pct"] == 20.0
    assert after["limit_rule"] == "chinext_20pct"
    assert before["limit_up_price"] == 11.0
    assert after["limit_up_price"] == 12.0


def test_ladder_needs_name_lookup_uses_market_rules():
    # 连板天梯候选过滤与涨跌停价行共用 market_rules：创业板按 20% 计算涨停价
    snapshot = {
        "tdx_code": "sz300001",
        "last_price": 12.0,
        "pre_close": 10.0,
        "high": 12.0,
        "change_pct": 20.0,
        "high_change_pct": 20.0,
    }
    assert limit_ladder_needs_name_lookup(snapshot, boards=None, include_touched=True) is True
