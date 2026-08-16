"""ICFQS 题材族 fetch 层：题材成分（PIT）与题材事件日历。

数据来自 TDX ICFQS HTTP 网关（tqlex.IcfqsClient），与 TDX 行情 socket 无关；
本模块不创建 wire client。列语义来自 2026-08-16 真机实测（N001.. 列序），
但网关可能调整列：关键列一律"已知列序优先 + 全列按值特征扫描兜底"，
两者都失败时抛带行预览的 ThemeColumnError，绝不静默错列。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from .tqlex import IcfqsClient, icfqs_tables

# topic_list 请求参数：["00601", category + "|" + setcode, page]；真机抓包口径 "1|1"。
_TOPIC_LIST_DEFAULT_CATEGORY = ""
_TOPIC_LIST_DEFAULT_SETCODE = ""
# topic_stocks 请求参数：["00901", code, setcode, 1, size, 0, page]。
_TOPIC_STOCKS_PAGE_SIZE = 100
# events 请求参数：["00401", "", N]。
_THEME_EVENTS_DEFAULT_COUNT = 100
_THEME_EVENTS_MAX_COUNT = 1000
# 翻页安全上限：正常全量题材约几百页以内，超过视为网关异常。
_MAX_LIST_PAGES = 500

_THEME_CODE_RE = re.compile(r"^\d{4,6}$")
_MARKET_SYMBOL_RE = re.compile(r"^([012])_(\d{6})$")
_SYMBOL_RE = re.compile(r"^\d{6}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_MEMBER_CODES_RE = re.compile(r"^[012]_\d{6}(,[012]_\d{6})*$")

_MARKET_SUFFIXES = {"0": "SZ", "1": "SH", "2": "BJ"}
_EXCHANGES = {"0": "SZSE", "1": "SSE", "2": "BSE"}


@dataclass(frozen=True)
class ThemeFetchResult:
    rows: list[dict[str, Any]]
    meta: dict[str, Any]


class ThemeColumnError(ValueError):
    """ICFQS 返回行无法按已知列序或值特征定位关键列（列语义漂移）。"""


def stock_theme_members_request_result(
    params: Mapping[str, Any],
    *,
    client: IcfqsClient | None = None,
    today: date | None = None,
    progress_callback: Callable[..., None] | None = None,
) -> ThemeFetchResult:
    """遍历全部题材并拉取每个题材的成分（PIT 快照）。"""

    from .execution_utils import emit_source_progress

    icfqs = client if client is not None else IcfqsClient()
    as_of = _as_of_date(params, today)
    category = str(params.get("category") or _TOPIC_LIST_DEFAULT_CATEGORY)
    list_setcode = str(params.get("setcode") or _TOPIC_LIST_DEFAULT_SETCODE)

    themes, list_pages = _theme_catalog(icfqs, category, list_setcode)
    emit_source_progress(
        progress_callback,
        40,
        f"题材列表共 {len(themes)} 个（{list_pages} 页）",
    )

    rows: list[dict[str, Any]] = []
    member_pages = 0
    member_skipped = 0
    for index, theme in enumerate(themes):
        theme_rows, pages, skipped = _theme_member_rows(icfqs, theme, as_of_date=as_of)
        member_pages += pages
        member_skipped += skipped
        rows.extend(theme_rows)
        if (index + 1) % 25 == 0 or index + 1 == len(themes):
            emit_source_progress(
                progress_callback,
                50,
                f"已采集题材成分 {index + 1}/{len(themes)}",
                progress_current=index + 1,
                progress_total=len(themes),
                progress_unit="个",
                eta_ms=None,
            )

    meta = {
        "as_of_date": as_of,
        "data_date": as_of,
        "tdx_theme_count": len(themes),
        "tdx_theme_list_pages": list_pages,
        "tdx_theme_member_pages": member_pages,
        "tdx_theme_member_count": len(rows),
        "tdx_theme_member_skipped_rows": member_skipped,
        "tdx_icfqs_host": getattr(icfqs, "default_url", None),
    }
    return ThemeFetchResult(rows=rows, meta=meta)


def stock_theme_events_request_result(
    params: Mapping[str, Any],
    *,
    client: IcfqsClient | None = None,
    today: date | None = None,
) -> ThemeFetchResult:
    """拉取题材事件日历（近 N 条）。"""

    icfqs = client if client is not None else IcfqsClient()
    as_of = _as_of_date(params, today)
    count = _event_count(params)

    raw = icfqs.request_icfqs("events", ["00401", "", count])
    source_rows = _entry_rows(raw, "events")
    rows = [_theme_event_row(row, as_of_date=as_of) for row in source_rows]
    rows = _dedupe_theme_event_rows(rows)

    meta = {
        "as_of_date": as_of,
        "data_date": as_of,
        "tdx_theme_event_count": len(rows),
        "tdx_theme_event_source_count": len(source_rows),
        "tdx_theme_event_limit": count,
        "tdx_icfqs_host": getattr(icfqs, "default_url", None),
    }
    return ThemeFetchResult(rows=rows, meta=meta)


def _dedupe_theme_event_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse source-side duplicates under the table PK (theme_code, event_date, as_of_date).

    The ICFQS feed repeats identical event rows (verified live: 880948 served the
    same text twice); distinct texts on the same theme+date are merged with a
    separator and member lists are unioned.
    """

    by_pk: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        pk = (str(row["theme_code"]), str(row["event_date"]), str(row["as_of_date"]))
        existing = by_pk.get(pk)
        if existing is None:
            by_pk[pk] = dict(row)
            continue
        text = str(row.get("event_text") or "").strip()
        current = str(existing.get("event_text") or "").strip()
        if text and text != current:
            existing["event_text"] = f"{current} ‖ {text}" if current else text
        members = str(row.get("member_codes") or "").strip()
        current_members = str(existing.get("member_codes") or "").strip()
        if members and members != current_members:
            merged = sorted(set(current_members.split(",")) | set(members.split(",")))
            existing["member_codes"] = ",".join(m for m in merged if m)
        if existing.get("change_pct") is None and row.get("change_pct") is not None:
            existing["change_pct"] = row["change_pct"]
    return list(by_pk.values())


def _theme_catalog(
    icfqs: IcfqsClient, category: str, setcode: str
) -> tuple[list[dict[str, str]], int]:
    """topic_list 翻页到空页，返回 [{theme_code, theme_name, setcode}]。"""

    themes: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    pages = 0
    skipped_rows = 0
    for page_rows in _entry_pages(icfqs, "topic_list", ["00601", f"{category}|{setcode}"]):
        pages += 1
        page_theme_count = 0
        for row in page_rows:
            theme_code = _cell(
                row,
                entry="topic_list",
                semantic="theme_code",
                known_keys=("N002",),
                validate=_is_theme_code,
                scan=_is_theme_code,
                required=False,
            )
            if theme_code is None:
                # Deep pages serve mixed payloads (two-digit category ids with
                # color fields observed live); skip non-theme rows instead of
                # aborting the whole catalog walk.
                skipped_rows += 1
                continue
            code = str(theme_code)
            theme_setcode = _topic_setcode(row, code)
            if (code, theme_setcode) in seen:
                continue
            seen.add((code, theme_setcode))
            page_theme_count += 1
            themes.append(
                {
                    "theme_code": code,
                    "theme_name": _text_cell(row, known_keys=("N003",), required=False),
                    "setcode": theme_setcode,
                }
            )
        if page_theme_count == 0 and themes:
            # A page with zero parseable theme rows after real pages is the
            # de-facto end of the catalog (the feed does not send empty pages).
            break
    if not themes:
        # An empty catalog means the ICFQS gateway is flapping (observed live:
        # some default-pool hosts return ErrorCode=0 with zero rows while
        # others serve 20). Fail loudly so the scheduler backs off and retries
        # instead of persisting an empty snapshot (which would look like "all
        # themes vanished" downstream).
        raise ValueError(
            "ICFQS topic_list returned an empty catalog (gateway flap); "
            "retry the run instead of persisting an empty snapshot"
        )
    return themes, pages


def _theme_member_rows(
    icfqs: IcfqsClient,
    theme: Mapping[str, str],
    *,
    as_of_date: str,
) -> tuple[list[dict[str, Any]], int]:
    """topic_stocks size=100 翻页到空页，返回 (rows, pages)。"""

    theme_code = theme["theme_code"]
    setcode = theme["setcode"]
    rows: list[dict[str, Any]] = []
    pages = 0
    skipped = 0
    base = ["00901", theme_code, setcode, 1, _TOPIC_STOCKS_PAGE_SIZE, 0]
    for page_rows in _entry_pages(icfqs, "topic_stocks", base):
        pages += 1
        for row in page_rows:
            try:
                rows.append(
                    _theme_member_row(
                        row, theme_code=theme_code, setcode=setcode, as_of_date=as_of_date
                    )
                )
            except ThemeColumnError:
                # Mixed payloads reach topic_stocks too (live: a "866" category
                # row surfaced inside a member page); skip unparseable rows
                # instead of aborting the theme walk.
                skipped += 1
    return rows, pages, skipped


def _entry_pages(
    icfqs: IcfqsClient,
    entry: str,
    base_params: list[Any],
) -> Iterator[list[dict[str, Any]]]:
    """按 page 递增翻页，空页即止；超过安全上限抛错。"""

    page = 1
    while page <= _MAX_LIST_PAGES:
        raw = icfqs.request_icfqs(entry, [*base_params, page])
        rows = _entry_rows(raw, entry)
        if not rows:
            return
        yield rows
        page += 1
    raise ThemeColumnError(
        f"icfqs {entry}: 翻页超过 {_MAX_LIST_PAGES} 页仍未出现空页，疑似网关翻页异常"
    )


def _entry_rows(raw: Mapping[str, Any], entry: str) -> list[dict[str, Any]]:
    tables = icfqs_tables(dict(raw))
    for table in tables:
        if table.rows:
            return [dict(row) for row in table.rows]
    return []


def _theme_member_row(
    row: Mapping[str, Any],
    *,
    theme_code: str,
    setcode: str,
    as_of_date: str,
) -> dict[str, Any]:
    instrument_id, symbol, market = _member_instrument(row, theme_code=theme_code, setcode=setcode)
    return {
        "theme_code": theme_code,
        "setcode": setcode,
        "instrument_id": instrument_id,
        "symbol": symbol,
        "exchange": _EXCHANGES[market],
        "instrument_name": _text_cell(row, known_keys=("N005",)),
        "join_reason": _text_cell(row, known_keys=("N008",), required=False, scan=False),
        "join_date": _date_cell(row, known_keys=("N009",), required=False),
        "as_of_date": as_of_date,
    }


def _theme_event_row(row: Mapping[str, Any], *, as_of_date: str) -> dict[str, Any]:
    return {
        "theme_code": _cell(
            row,
            entry="events",
            semantic="theme_code",
            known_keys=("N003",),
            validate=_is_theme_code,
            scan=_is_theme_code,
        ),
        "theme_name": _text_cell(row, known_keys=("N004",), required=False, scan=False),
        "event_date": _date_cell(row, known_keys=("N005",)),
        "event_text": _text_cell(row, known_keys=("N006",)),
        "member_codes": _raw_member_codes(row),
        "change_pct": _change_pct(row),
        "as_of_date": as_of_date,
    }


def _member_instrument(
    row: Mapping[str, Any], *, theme_code: str, setcode: str
) -> tuple[str, str, str]:
    """返回 (instrument_id, symbol, market)。

    已知列序优先：N004 股票代码（支持 "0_300243" 带市场位或裸 6 位）。
    兜底扫描：先找市场位前缀形态（权威），再找裸 6 位代码（排除与请求
    theme_code/setcode 同值的格）。裸代码市场位按 A 股代码前缀推断
    （6→SH，0/2/3→SZ，4/8/92→BJ，其余 9→SH B 股）。
    """

    def _from_parts(market: str, symbol: str) -> tuple[str, str, str]:
        return f"{symbol}.{_MARKET_SUFFIXES[market]}", symbol, market

    known = row.get("N004")
    if _present(known):
        text = str(known)
        matched = _MARKET_SYMBOL_RE.match(text)
        if matched:
            return _from_parts(matched.group(1), matched.group(2))
        if _SYMBOL_RE.match(text):
            return _from_parts(_market_from_symbol(text), text)

    cells = _ordered_cells(row)
    for value in cells:
        matched = _MARKET_SYMBOL_RE.match(str(value))
        if matched:
            return _from_parts(matched.group(1), matched.group(2))
    skip = {theme_code, setcode}
    for value in cells:
        symbol = str(value)
        if _SYMBOL_RE.match(symbol) and symbol not in skip:
            return _from_parts(_market_from_symbol(symbol), symbol)
    raise ThemeColumnError(
        "icfqs topic_stocks: 无法定位股票代码"
        f"（期望 6 位代码或 [012]_xxxxxx；row={_row_preview(row)}）"
    )


def _market_from_symbol(symbol: str) -> str:
    if symbol.startswith("6"):
        return "1"
    if symbol[0] in "023":
        return "0"
    if symbol[0] in "48" or symbol.startswith("92"):
        return "2"
    if symbol[0] == "9":
        return "1"
    raise ThemeColumnError(f"icfqs topic_stocks: 无法从代码 {symbol!r} 推断市场位")


def _topic_setcode(row: Mapping[str, Any], theme_code: str) -> str:
    """setcode：880 前缀强制 "2"（真机实测 880 系成分/K线都只吃 setcode=2，
    且 N005 JSON 的 setcode 对 880 系不可靠——"880915" 标着 "1" 但三个
    setcode 都取不到成分，它本是"行情特征"动态题材）；其余按 N005 JSON，
    缺失时纯数字默认 "1"。"""

    if theme_code.startswith("880"):
        return "2"
    raw = row.get("N005")
    if isinstance(raw, str) and raw.strip().startswith(("[", "{")):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            items = [payload]
        else:
            items = []
        for item in items:
            if isinstance(item, dict):
                setcode = str(item.get("setcode") or "").strip()
                if setcode in _MARKET_SUFFIXES:
                    return setcode
    if theme_code.isdigit():
        return "1"
    raise ThemeColumnError(
        f"icfqs topic_list: 题材 {theme_code!r} 无 setcode "
        f"且不满足默认推断规则（row={_row_preview(row)}）"
    )


def _cell(
    row: Mapping[str, Any],
    *,
    entry: str,
    semantic: str,
    known_keys: tuple[str, ...],
    validate: Callable[[Any], bool],
    scan: Callable[[Any], bool],
    required: bool = True,
) -> Any:
    """已知列序优先，值特征全列扫描兜底；required 时失败抛 ThemeColumnError。

    required=False 时失败返回 None（调用方跳过该行）——用于容忍深层分页里
    混入的非目标数据行（真机观测：topic_list 深页混入两位码分类行）。
    """

    for key in known_keys:
        value = row.get(key)
        if _present(value) and validate(value):
            return value
    for value in _ordered_cells(row):
        if scan(value):
            return value
    if not required:
        return None
    raise ThemeColumnError(
        f"icfqs {entry}: 无法定位 {semantic}（已知列 {known_keys} 不匹配，"
        f"全列扫描未命中；row={_row_preview(row)}）"
    )


def _text_cell(
    row: Mapping[str, Any],
    *,
    known_keys: tuple[str, ...],
    required: bool = True,
    scan: bool = True,
) -> str | None:
    """文本列：已知列序优先；scan=True 时按"非数值样"文本扫描兜底。

    可选文本列（join_reason/theme_name）传 scan=False：已知列缺失就返回
    None，不做位置无关扫描——文本与文本无法按值区分，扫描会静默错列。
    """

    for key in known_keys:
        value = row.get(key)
        if _present(value) and _is_text(value):
            return str(value)
    if scan:
        for value in _ordered_cells(row):
            text = str(value)
            if (
                _is_text(value)
                and not _MARKET_SYMBOL_RE.match(text)
                and not _MEMBER_CODES_RE.match(text)
            ):
                return text
    if required:
        raise ThemeColumnError(
            f"icfqs: 无法定位文本列（已知列 {known_keys} 不匹配；row={_row_preview(row)}）"
        )
    return None


def _date_cell(
    row: Mapping[str, Any],
    *,
    known_keys: tuple[str, ...],
    required: bool = True,
) -> str | None:
    """日期列 → YYYYMMDD；已知列序优先，日期特征扫描兜底。"""

    for key in known_keys:
        value = row.get(key)
        if _present(value):
            normalized = _normalize_date(value)
            if normalized is not None:
                return normalized
    for value in _ordered_cells(row):
        normalized = _normalize_date(value)
        if normalized is not None:
            return normalized
    if required:
        raise ThemeColumnError(
            f"icfqs: 无法定位日期列（已知列 {known_keys} 不匹配；row={_row_preview(row)}）"
        )
    return None


def _raw_member_codes(row: Mapping[str, Any]) -> str | None:
    for key in ("N007",):
        value = row.get(key)
        if _present(value) and _MEMBER_CODES_RE.match(str(value)):
            return str(value)
    for value in _ordered_cells(row):
        if _MEMBER_CODES_RE.match(str(value)):
            return str(value)
    return None


def _change_pct(row: Mapping[str, Any]) -> float | None:
    # 已知列 N008 直接按数值解析；扫描兜底要求带小数点/百分号/负号，
    # 排除序号这类纯小整数，避免错列。
    for key in ("N008",):
        parsed = _parse_float(row.get(key))
        if parsed is not None:
            return parsed
    for value in _ordered_cells(row):
        text = str(value)
        if any(marker in text for marker in (".", "%", "-")):
            parsed = _parse_float(text)
            if parsed is not None:
                return parsed
    return None


def _event_count(params: Mapping[str, Any]) -> int:
    from .request_params import int_param

    return int_param(
        params,
        "count",
        _THEME_EVENTS_DEFAULT_COUNT,
        minimum=1,
        maximum=_THEME_EVENTS_MAX_COUNT,
    )


def _as_of_date(params: Mapping[str, Any], today: date | None) -> str:
    """as_of_date：params 覆盖（补采），默认当日。"""

    raw = params.get("as_of_date")
    if raw not in (None, ""):
        normalized = _normalize_date(raw)
        if normalized is None:
            raise ValueError(f"as_of_date 必须是 YYYYMMDD 或 YYYY-MM-DD：{raw!r}")
        return normalized
    return (today or date.today()).strftime("%Y%m%d")


def _normalize_date(value: Any) -> str | None:
    if not _present(value):
        return None
    digits = "".join(ch for ch in str(value).strip() if ch.isdigit())
    if len(digits) != 8:
        return None
    year, month, day = int(digits[:4]), int(digits[4:6]), int(digits[6:8])
    if not (1990 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
        return None
    return digits


def _parse_float(value: Any) -> float | None:
    if not _present(value):
        return None
    text = str(value).strip().removesuffix("%")
    try:
        return float(text)
    except ValueError:
        return None


def _is_theme_code(value: Any) -> bool:
    return bool(_THEME_CODE_RE.match(str(value)))


def _is_text(value: Any) -> bool:
    text = str(value).strip()
    if not text:
        return False
    if _DATE_RE.match(text) or _SYMBOL_RE.match(text) or _MARKET_SYMBOL_RE.match(text):
        return False
    if _MEMBER_CODES_RE.match(text):
        return False
    return any(ch.isalpha() or "\u4e00" <= ch <= "\u9fff" for ch in text)


def _present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _ordered_cells(row: Mapping[str, Any]) -> list[Any]:
    """按列名自然序（N001 < N002 < ... < N010）输出全部非空值。"""

    return [
        row[key]
        for key in sorted(row, key=lambda name: (len(name), name))
        if _present(row[key])
    ]


def _row_preview(row: Mapping[str, Any]) -> str:
    text = json.dumps(dict(row), ensure_ascii=False)
    return text if len(text) <= 200 else text[:200] + "…"
