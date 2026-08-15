"""Market-date context for TDX snapshot-derived indicators."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from threading import RLock
from typing import Any, Callable
from zoneinfo import ZoneInfo

from axdata_core.market_rules import session_context


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
AUCTION_READY_TIME = time(9, 25)
_CALENDAR_ROWS_BY_DATE: dict[date, tuple[Mapping[str, Any], ...]] = {}
_CALENDAR_CACHE_LOCK = RLock()


@dataclass(frozen=True, slots=True)
class MarketDateContext:
    target_trade_date: str | None
    previous_trade_date: str | None
    server_datetime: datetime | None
    phase: str
    ready: bool
    source: str


def resolve_market_date_context(
    client: Any,
    *,
    fallback_trade_date: Any = None,
    request_interface: Callable[..., Any] | None = None,
) -> MarketDateContext:
    handshake = client_handshake_info(client)
    server_datetime = getattr(handshake, "server_datetime", None)
    if server_datetime is not None and server_datetime.tzinfo is None:
        server_datetime = server_datetime.replace(tzinfo=SHANGHAI_TZ)

    market_dates = sorted(
        {
            value
            for value in (
                getattr(handshake, "server_date_1", None),
                getattr(handshake, "server_date_2", None),
            )
            if isinstance(value, date)
        }
    )
    handshake_trade_date = market_dates[-1] if market_dates else None
    calendar_context = _calendar_market_date_context(
        server_datetime,
        request_interface=request_interface,
    )
    if calendar_context is not None:
        if (
            calendar_context.ready
            and handshake_trade_date is not None
            and handshake_trade_date.strftime("%Y%m%d") != calendar_context.target_trade_date
        ):
            return MarketDateContext(
                target_trade_date=calendar_context.target_trade_date,
                previous_trade_date=calendar_context.previous_trade_date,
                server_datetime=server_datetime,
                phase="market_date_unconfirmed",
                ready=False,
                source="exchange_calendar+tdx_handshake",
            )
        return calendar_context

    fallback_text = _date_text(handshake_trade_date) or _date_text(fallback_trade_date)
    fallback_ready = True
    fallback_phase = "fallback"
    if server_datetime is not None and handshake_trade_date is not None:
        local_datetime = server_datetime.astimezone(SHANGHAI_TZ)
        if (
            local_datetime.date() == handshake_trade_date
            and local_datetime.time() < AUCTION_READY_TIME
        ):
            fallback_ready = False
            fallback_phase = "pre_auction_fallback"
    return MarketDateContext(
        target_trade_date=fallback_text,
        previous_trade_date=None,
        server_datetime=server_datetime,
        phase=fallback_phase,
        ready=fallback_ready,
        source="tdx_handshake" if handshake_trade_date is not None else "stats_fallback",
    )


def client_handshake_info(client: Any) -> Any | None:
    transport = getattr(client, "transport", None)
    candidates = list(getattr(transport, "_transports", ()) or ())
    if transport is not None and not candidates:
        candidates = [transport]
    for candidate in candidates:
        handshake = getattr(candidate, "last_handshake", None)
        if handshake is not None:
            return handshake

    session = getattr(client, "session", None)
    request_handshake = getattr(session, "handshake", None)
    if callable(request_handshake):
        try:
            return request_handshake()
        except Exception:
            return None
    return None


def _calendar_market_date_context(
    server_datetime: datetime | None,
    *,
    request_interface: Callable[..., Any] | None,
) -> MarketDateContext | None:
    if server_datetime is None:
        return None
    if request_interface is None:
        try:
            from axdata_core.source_request import request_interface as current_request_interface
        except ImportError:
            return None
    else:
        current_request_interface = request_interface

    today = server_datetime.astimezone(SHANGHAI_TZ).date()
    start_date = (today - timedelta(days=14)).strftime("%Y%m%d")
    end_date = (today + timedelta(days=1)).strftime("%Y%m%d")
    rows = _calendar_rows(
        today,
        start_date=start_date,
        end_date=end_date,
        request_interface=current_request_interface,
        use_cache=request_interface is None,
    )
    if rows is None:
        return None

    by_date = {
        str(row.get("cal_date") or ""): row
        for row in rows
        if isinstance(row, Mapping) and row.get("cal_date") not in (None, "")
    }
    today_text = today.strftime("%Y%m%d")
    today_row = by_date.get(today_text)
    if today_row is None:
        return None

    ctx = session_context(rows, today)
    if ctx.is_open:
        ready = server_datetime.astimezone(SHANGHAI_TZ).time() >= AUCTION_READY_TIME
        return MarketDateContext(
            target_trade_date=ctx.target_for_review,
            previous_trade_date=ctx.pretrade_date,
            server_datetime=server_datetime,
            phase="trading" if ready else "pre_auction",
            ready=ready,
            source="exchange_calendar+tdx_handshake",
        )

    target_trade_date = ctx.target_for_review
    target_row = by_date.get(target_trade_date or "")
    previous_trade_date = (
        _optional_text(target_row.get("pretrade_date"))
        if isinstance(target_row, Mapping)
        else None
    )
    return MarketDateContext(
        target_trade_date=target_trade_date,
        previous_trade_date=previous_trade_date,
        server_datetime=server_datetime,
        phase="closed",
        ready=True,
        source="exchange_calendar+tdx_handshake",
    )


def _date_text(value: Any) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y%m%d")
    return _optional_text(value)


def _calendar_rows(
    today: date,
    *,
    start_date: str,
    end_date: str,
    request_interface: Callable[..., Any],
    use_cache: bool,
) -> tuple[Mapping[str, Any], ...] | None:
    if not use_cache:
        return _request_calendar_rows(
            start_date=start_date,
            end_date=end_date,
            request_interface=request_interface,
        )

    with _CALENDAR_CACHE_LOCK:
        cached = _CALENDAR_ROWS_BY_DATE.get(today)
        if cached is not None:
            return cached
        rows = _request_calendar_rows(
            start_date=start_date,
            end_date=end_date,
            request_interface=request_interface,
        )
        if rows is None:
            return None
        today_text = today.strftime("%Y%m%d")
        has_today = any(str(row.get("cal_date") or "") == today_text for row in rows)
        if has_today:
            _CALENDAR_ROWS_BY_DATE[today] = rows
            while len(_CALENDAR_ROWS_BY_DATE) > 8:
                del _CALENDAR_ROWS_BY_DATE[min(_CALENDAR_ROWS_BY_DATE)]
        return rows


def _request_calendar_rows(
    *,
    start_date: str,
    end_date: str,
    request_interface: Callable[..., Any],
) -> tuple[Mapping[str, Any], ...] | None:
    try:
        result = request_interface(
            "stock_trade_calendar_exchange",
            params={"start_date": start_date, "end_date": end_date},
            fields=["cal_date", "is_open", "pretrade_date"],
            persist=False,
        )
        return tuple(row for row in result.records if isinstance(row, Mapping))
    except Exception:
        return None


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
