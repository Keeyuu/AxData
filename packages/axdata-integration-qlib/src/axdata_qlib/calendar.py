"""Trading calendar resolution for the Qlib export.

Qlib's backtest reads ``calendar[end + 1]`` to step past the research end
(ADR-0001), so the exported ``calendars/day.txt`` must contain at least one
trading day strictly after the research end date. The calendar dataset may
cover a wider range; only the study window plus one margin day is exported.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from .errors import QlibExportError


def normalize_date(value: str) -> str:
    """Accept ``YYYY-MM-DD`` or ``YYYYMMDD`` and return ``YYYY-MM-DD``."""
    text = str(value).strip()
    compact = text.replace("-", "")
    if not (len(compact) == 8 and compact.isdigit()):
        raise QlibExportError(f"Date must be YYYY-MM-DD or YYYYMMDD, got {value!r}.")
    parsed = pd.Timestamp(compact)
    return f"{parsed:%Y-%m-%d}"


def resolve_export_calendar(
    calendar_dates: Iterable[object],
    start_date: str,
    end_date: str,
) -> tuple[list[str], str]:
    """Resolve the exported trading calendar and its margin day.

    Args:
        calendar_dates: All trading days from the calendar dataset (any
            date-like type pandas can parse).
        start_date / end_date: Research window bounds (inclusive).

    Returns:
        ``(export_calendar, margin_date)`` where ``export_calendar`` spans
        the trading days in ``[start_date, margin_date]`` (inclusive) and
        ``margin_date`` is the first trading day strictly after ``end_date``.

    Raises:
        QlibExportError: when no trading day exists after ``end_date`` — the
            export is refused rather than silently truncated.
    """
    start = normalize_date(start_date)
    end = normalize_date(end_date)
    dates = sorted(
        {f"{pd.Timestamp(value):%Y-%m-%d}" for value in calendar_dates if str(value).strip()}
    )
    if not dates:
        raise QlibExportError("Calendar dataset contains no trading days.")
    margin = next((day for day in dates if day > end), None)
    if margin is None:
        raise QlibExportError(
            f"Calendar dataset has no trading day after research end {end}; "
            "the exported qlib calendar must extend past the research window "
            "(at least one margin trading day, ADR-0001)."
        )
    export_calendar = [day for day in dates if start <= day <= margin]
    if not export_calendar:
        raise QlibExportError(
            f"No trading day in [{start}, {margin}] matched the calendar dataset."
        )
    return export_calendar, margin
