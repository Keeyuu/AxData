"""价格舍入与比较的纯函数工具。

``HALF_TICK`` = 半个最小报价单位（0.01 元的一半）外加浮点容差，替代历史魔法数
0.0051：0.0051 多出的 0.0001 并非浮点误差量级，会把恰好差一个最小报价单位的两个
价格误判为相等。
"""

from __future__ import annotations

from typing import Any

HALF_TICK: float = 0.005 + 1e-9


def round_price(value: Any, digits: int = 2) -> float | None:
    """按最小报价单位舍入；None/空串返回 None（沿用既有语义）。"""
    if value in (None, ""):
        return None
    return round(float(value) + 1e-9, digits)


def price_close(left: Any, right: Any, *, tolerance: float = HALF_TICK) -> bool:
    """两价格在容差内视为相等；任一为 None/空串返回 False。"""
    if left in (None, "") or right in (None, ""):
        return False
    try:
        return abs(float(left) - float(right)) <= tolerance
    except (TypeError, ValueError):
        return False


def price_at_or_above(left: Any, right: Any, *, tolerance: float = HALF_TICK) -> bool:
    """left 不低于 right（含容差）；任一为 None/空串返回 False。"""
    if left in (None, "") or right in (None, ""):
        return False
    try:
        return float(left) + tolerance >= float(right)
    except (TypeError, ValueError):
        return False
