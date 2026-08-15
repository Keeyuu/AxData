"""TDX price-limit and limit-up status rules（弃用兼容层）。

实现已迁移至 ``axdata_core.market_rules``，本文件仅保留兼容面：

- 从 ``market_rules`` 直接 re-export 的纯函数：``st_type_from_name`` /
  ``ipo_phase_from_name`` / ``round_price`` / ``price_close`` / ``price_at_or_above``；
- 组合便捷函数与快照上下文辅助：``price_limit_name_flag``（ST 状态 + 上市阶段组合）/
  ``rule_price_limits`` / ``special_limit_ratio`` / ``limit_ladder_status`` /
  ``positive_number``；
- ``price_limit_ratio_from_rule`` / ``price_limit_rule``：保持原签名的兼容薄封装，
  内部按 ``date.today()`` 调 ``market_rules.limit_rule``（真实消费方已迁移到传日版本）。

Deprecation: 本模块计划在下一个 minor 版本移除，新代码一律使用
``axdata_core.market_rules``。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from axdata_core.market_rules import (
    LimitRule,
    board_from_tdx_code,
    ipo_phase_from_name,
    limit_rule,
    price_at_or_above,
    price_close,
    round_price,
    st_type_from_name,
)

from .normalize_utils import round_optional_float


def price_limit_name_flag(name: str | None) -> str | None:
    """证券简称组合标记：先 ST 状态（*ST/ST，含 S*ST/SST），再上市阶段（N/C）。"""
    st_type = st_type_from_name(name)
    if st_type is not None:
        return st_type
    return ipo_phase_from_name(name)


def price_limit_ratio_from_rule(tdx_code: str, name_flag: str | None) -> float | None:
    """弃用：无日期参数的兼容薄封装，按今天日期解析规则（见模块 docstring）。"""
    return _rule_for_compat(tdx_code, name_flag).ratio


def price_limit_rule(tdx_code: str, name_flag: str | None) -> str:
    """弃用：无日期参数的兼容薄封装，返回 ``LimitRule.rule_id``。"""
    return _rule_for_compat(tdx_code, name_flag).rule_id


def _rule_for_compat(tdx_code: str, name_flag: str | None) -> LimitRule:
    st_type = name_flag if name_flag in {"ST", "*ST"} else None
    ipo_phase = name_flag if name_flag in {"N", "C"} else None
    return limit_rule(
        board=board_from_tdx_code(tdx_code),
        date=date.today(),
        st_type=st_type,
        ipo_phase=ipo_phase,
    )


def rule_price_limits(pre_close: Any, limit_ratio: float) -> tuple[float | None, float | None]:
    if pre_close in (None, ""):
        return None, None
    close = float(pre_close)
    return (
        round_price(close * (1.0 + limit_ratio / 100.0)),
        round_price(close * (1.0 - limit_ratio / 100.0)),
    )


def special_limit_ratio(pre_close: Any, limit_up_price: Any, limit_down_price: Any) -> float | None:
    if pre_close in (None, "", 0) or limit_up_price in (None, ""):
        return None
    return round_optional_float((float(limit_up_price) / float(pre_close) - 1.0) * 100.0)


def positive_number(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def limit_ladder_status(snapshot: Mapping[str, Any], limit_up_price: Any) -> str:
    if limit_up_price is None:
        return "none"
    if price_close(snapshot.get("last_price"), limit_up_price) and (
        price_close(snapshot.get("bid1_price"), limit_up_price)
        or (snapshot.get("locked_amount") not in (None, "") and float(snapshot.get("locked_amount") or 0) > 0)
    ):
        return "sealed"
    if price_at_or_above(snapshot.get("high"), limit_up_price) or price_at_or_above(
        snapshot.get("last_price"), limit_up_price
    ):
        return "touched"
    return "none"
