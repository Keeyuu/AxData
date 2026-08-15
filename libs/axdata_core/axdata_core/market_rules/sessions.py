"""交易日上下文单源解析。

输入为交易所日历接口行（``cal_date`` / ``is_open`` / ``pretrade_date`` /
``next_trade_date``），输出命名方向字段，供盘前（preview）与盘后（review）
两个方向复用，避免各调用点自行解读日历行：

- ``target_for_preview``：休市 → 下一交易日，开市 → 今天；
- ``target_for_review``：休市 → 前一交易日（pretrade），开市 → 今天。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class SessionContext:
    """某一天的交易日上下文（所有日期为 ``%Y%m%d`` 文本，缺失为 None）。"""

    is_open: bool
    pretrade_date: str | None
    next_trade_date: str | None
    target_for_preview: str | None
    target_for_review: str | None


def session_context(calendar_rows: Sequence[Mapping[str, Any]], today: Any) -> SessionContext:
    """从交易日历行解析 today 的交易日上下文。

    ``calendar_rows`` 为交易所日历接口行（Mapping，含 ``cal_date`` 等字段）；
    ``today`` 为 date/datetime 或 ``YYYY-MM-DD``/``YYYYMMDD`` 文本。
    缺少 today 行时抛 ``ValueError``（调用方需自行决定 fallback 策略）。
    """
    today_text = _date_text(today)
    by_date = {
        str(row.get("cal_date") or ""): row
        for row in calendar_rows
        if isinstance(row, Mapping) and row.get("cal_date") not in (None, "")
    }
    today_row = by_date.get(today_text)
    if today_row is None:
        raise ValueError(f"交易日历缺少 {today_text} 行，无法解析交易日上下文")

    is_open = _is_open(today_row.get("is_open"))
    pretrade_date = _optional_text(today_row.get("pretrade_date"))
    next_trade_date = _optional_text(today_row.get("next_trade_date"))
    return SessionContext(
        is_open=is_open,
        pretrade_date=pretrade_date,
        next_trade_date=next_trade_date,
        target_for_preview=today_text if is_open else next_trade_date,
        target_for_review=today_text if is_open else pretrade_date,
    )


def _date_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    return _optional_text(value) or ""


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _is_open(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "open"}
