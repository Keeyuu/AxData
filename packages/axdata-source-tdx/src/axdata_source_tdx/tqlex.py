"""TDX 7615 TQLEX HTTP helpers.

This module is intentionally small and source-facing. Product interfaces map
the parsed tables to AxData fields in the request adapter.

Two TQLEX service families share the 7615 protocol:

- F10 pages (``TdxTqlexClient``) on static.tdx.com.cn.
- ICFQS topic / LHB data services (``IcfqsClient``), routed by entry family:
  ``default`` entries hit the zttz host pool, ``hot`` entries hit
  hot.icfqs.com. The two ICFQS gateways are independent, never failover.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_TQLEX_URL = "http://static.tdx.com.cn:7615/TQLEX"


@dataclass(frozen=True)
class TqlexTable:
    """One table parsed from a 7615 JSON response."""

    key: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]


class TdxTqlexClient:
    """Minimal request-level client for TDX 7615 data pages."""

    def __init__(self, *, base_url: str | None = None, timeout: float | None = None) -> None:
        self.base_url = (base_url or os.getenv("AXDATA_TDX_TQLEX_URL") or DEFAULT_TQLEX_URL).rstrip(
            "?"
        )
        self.timeout = (
            timeout if timeout is not None else _env_float("AXDATA_TDX_TQLEX_TIMEOUT", 10.0)
        )

    def request(self, entry: str, body: Any) -> dict[str, Any]:
        """POST one request and return decoded JSON."""

        entry_text = str(entry or "").strip()
        if not entry_text:
            raise ValueError("entry is required")
        separator = "&" if "?" in self.base_url else "?"
        url = f"{self.base_url}{separator}{urlencode({'Entry': entry_text})}"
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "User-Agent": "Mozilla/5.0 AxData/0.1",
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            raw = response.read()
        text = raw.decode("utf-8-sig")
        decoded = json.loads(text)
        if not isinstance(decoded, dict):
            raise ValueError("TQLEX response must be a JSON object")
        return decoded


def parse_tqlex_tables(payload: dict[str, Any]) -> tuple[TqlexTable, ...]:
    """Parse TQLEX ResultSets into row dictionaries.

    Duplicate source column names are preserved by suffixing later occurrences
    with ``__{index}``, while the first occurrence keeps the original name.
    """

    error_code = payload.get("ErrorCode", 0)
    if error_code not in (0, "0", None):
        raise ValueError(f"TQLEX response ErrorCode={error_code}")

    result_sets = payload.get("ResultSets") or []
    if not isinstance(result_sets, list):
        raise ValueError("TQLEX ResultSets must be a list")

    tables: list[TqlexTable] = []
    for table_index, result_set in enumerate(result_sets):
        if not isinstance(result_set, dict):
            continue
        columns = _result_set_columns(result_set)
        unique_columns = _unique_columns(columns)
        content = result_set.get("Content") or []
        rows: list[dict[str, Any]] = []
        if isinstance(content, list):
            for raw_row in content:
                if isinstance(raw_row, dict):
                    rows.append(dict(raw_row))
                    continue
                if not isinstance(raw_row, list):
                    continue
                row = {
                    unique_columns[index]: raw_row[index] if index < len(raw_row) else None
                    for index in range(len(unique_columns))
                }
                rows.append(row)
        key = str(result_set.get("ResultSetKey") or f"table{table_index}")
        tables.append(TqlexTable(key=key, columns=tuple(unique_columns), rows=tuple(rows)))
    return tuple(tables)


def _result_set_columns(result_set: dict[str, Any]) -> list[str]:
    col_name = result_set.get("ColName")
    if isinstance(col_name, list):
        return [str(name) for name in col_name]
    col_des = result_set.get("ColDes")
    if isinstance(col_des, list):
        names: list[str] = []
        for item in col_des:
            if isinstance(item, dict):
                names.append(str(item.get("Name") or item.get("name") or ""))
            else:
                names.append(str(item))
        return names
    return []


def _unique_columns(columns: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    unique: list[str] = []
    for index, column in enumerate(columns):
        name = column or f"column_{index}"
        count = seen.get(name, 0)
        seen[name] = count + 1
        unique.append(name if count == 0 else f"{name}__{index}")
    return unique


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# ICFQS (通达信题材/龙虎榜数据服务) — 与 F10 同族 7615 协议但地址/入口不同，
# 双网关按入口族路由（不互为故障切换）。地址池来自 gotdx hosts.go icfqsHostList，
# 入口清单与 Params 模板来自 gotdx icfqs.go（ICFQSTopicListRaw 等 Raw 方法）。
ICFQS_DEFAULT_HOSTS = (
    "119.3.157.89:7615",
    "139.9.211.159:7615",
    "121.37.193.4:7615",
    "124.71.56.161:7615",
    "123.60.69.160:7615",
    "123.60.149.213:7615",
    "118.25.106.154:7615",
    "129.204.254.13:7615",
    "159.75.115.35:7615",
    "82.157.190.225:7615",
    "121.36.192.253:7615",
    "124.71.105.217:7615",
)

ICFQS_HOT_HOST = "hot.icfqs.com:7615"


@dataclass(frozen=True)
class IcfqsEntry:
    """One ICFQS endpoint: TQLEX Entry name and gateway family."""

    entry: str
    gateway: str  # "default" (zttz pool) or "hot" (cfg host)


ICFQS_ENTRIES: dict[str, IcfqsEntry] = {
    # 题材族 (default 池；对应 gotdx ICFQS*Raw)
    "topic_list": IcfqsEntry("CWServ.ph_tdxdatacenter_zttz_zy", "default"),
    "search_topics": IcfqsEntry("CWServ.ph_tdxdatacenter_zttz_zy", "default"),
    "new_topics": IcfqsEntry("DataAggregation.zttz_xzgn2", "default"),
    "hot_topics": IcfqsEntry("CWServ.ph_tdxdatacenter_zttz_zy", "default"),
    "events": IcfqsEntry("DataAggregation.zttz_jhqz", "default"),
    "top_topics": IcfqsEntry("CWServ.ph_tdxdatacenter_zttz_zy", "default"),
    "topic_detail": IcfqsEntry("CWServ.ph_tdxdatacenter_zttz_xqy", "default"),
    "topic_kline": IcfqsEntry("CWServ.ph_tdxdatacenter_zttz_xqy_v2_qsid", "default"),
    "topic_stocks": IcfqsEntry("CWServ.ph_tdxdatacenter_zttz_xggp", "default"),
    "topic_quotes": IcfqsEntry("HQServ.hq_nlp", "default"),
    "topic_rotation": IcfqsEntry("HQServ.hq_nlp_copilot", "default"),
    "quotes_batch": IcfqsEntry("HQServ.PBCombHQ", "default"),
    # cfg 族 (hot 网关：龙虎榜/每日复盘)
    "lhb_detail": IcfqsEntry("CWServ.cfg_fx_yzlhb", "hot"),
    "yyb_detail": IcfqsEntry("CWServ.cfg_fx_yzlhb", "hot"),
    "yz_detail": IcfqsEntry("CWServ.cfg_fx_yzlhb", "hot"),
    "mrfp": IcfqsEntry("CWServ.cfg_tk_mrfp", "hot"),
    "mrfp_latest_date": IcfqsEntry("CWServ.cfg_tk_mrfp", "hot"),
}


@dataclass(frozen=True)
class IcfqsTable:
    """One table parsed from an ICFQS response."""

    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]


class IcfqsClient:
    """Request-level client for TDX ICFQS (topic / LHB) data services.

    ICFQS shares the 7615 TQLEX protocol with F10 but routes by entry family:
    ``default`` entries hit the zttz host pool, ``hot`` entries hit
    hot.icfqs.com. The two gateways are independent, never failover.
    """

    def __init__(
        self,
        *,
        default_url: str | None = None,
        hot_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        env_override = default_url or os.getenv("AXDATA_TDX_ICFQS_URL")
        self.default_url = _icfqs_gateway_url(
            default_url, "AXDATA_TDX_ICFQS_URL", ICFQS_DEFAULT_HOSTS[0]
        )
        # Round-robin the default pool: live probing showed hosts in the same
        # pool behave differently (one returns ErrorCode=0 with zero rows while
        # its neighbours serve full pages), so spread requests across the pool
        # instead of pinning the first host. An explicit default_url/env pins a
        # single host and keeps behaviour observable for tests.
        self._default_pool = (
            [self.default_url]
            if env_override
            else [f"http://{host}" for host in ICFQS_DEFAULT_HOSTS]
        )
        self._default_cursor = 0
        self.hot_url = _icfqs_gateway_url(hot_url, "AXDATA_TDX_ICFQS_HOT_URL", ICFQS_HOT_HOST)
        self.timeout = (
            timeout if timeout is not None else _env_float("AXDATA_TDX_TQLEX_TIMEOUT", 10.0)
        )

    def _next_default_url(self) -> str:
        pool = self._default_pool
        url = pool[self._default_cursor % len(pool)]
        self._default_cursor += 1
        return url

    def request_icfqs(self, entry: str, params: list[Any]) -> dict[str, Any]:
        """POST one ICFQS request, routed to the entry's gateway family."""

        name = str(entry or "").strip()
        definition = ICFQS_ENTRIES.get(name)
        if definition is None:
            raise ValueError(f"unknown icfqs entry: {name!r}")
        base_url = self.default_url if definition.gateway == "default" else self.hot_url
        payload = json.dumps(
            {"Params": params, "oauth_zzfw": "1"}, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        last_error: Exception | None = None
        attempts = len(self._default_pool) if definition.gateway == "default" else 1
        for _ in range(attempts):
            if definition.gateway == "default":
                base_url = self._next_default_url()
            request = Request(
                f"{base_url}/TQLEX?{urlencode({'Entry': definition.entry})}",
                data=payload,
                headers={
                    "Content-Type": "text/plain;charset=UTF-8",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "User-Agent": "Mozilla/5.0 AxData/0.1",
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                decoded = _parse_icfqs_json(raw)
                if not isinstance(decoded, dict):
                    raise ValueError("ICFQS response must be a JSON object")
                return decoded
            except Exception as exc:  # noqa: BLE001 - rotate to the next pool host
                last_error = exc
                continue
        raise last_error if last_error else ValueError("ICFQS request failed")


def icfqs_tables(raw: dict[str, Any]) -> list[IcfqsTable]:
    """Convert ICFQS ResultSets into row dicts keyed by ColName / ColDes.Name.

    Equivalent to gotdx ICFQSFormatTables + icfqsColumns: column names come
    from ``ColName`` when present, falling back to ``ColDes[].Name``; Content
    rows are aligned to the columns with missing trailing values padded as
    ``None``.
    """

    result_sets = raw.get("ResultSets") or []
    if not isinstance(result_sets, list):
        raise ValueError("ICFQS ResultSets must be a list")
    tables: list[IcfqsTable] = []
    for result_set in result_sets:
        if not isinstance(result_set, dict):
            continue
        columns = _icfqs_columns(result_set)
        content = result_set.get("Content")
        rows: list[dict[str, Any]] = []
        if isinstance(content, list):
            for raw_row in content:
                values = raw_row if isinstance(raw_row, list) else []
                row = {
                    column: values[index] if index < len(values) else None
                    for index, column in enumerate(columns)
                }
                rows.append(row)
        tables.append(IcfqsTable(columns=tuple(columns), rows=tuple(rows)))
    return tables


def _icfqs_columns(result_set: dict[str, Any]) -> list[str]:
    col_name = result_set.get("ColName")
    if isinstance(col_name, list):
        return [str(name) for name in col_name]
    col_des = result_set.get("ColDes")
    if isinstance(col_des, list):
        names: list[str] = []
        for item in col_des:
            if isinstance(item, dict):
                names.append(str(item.get("Name") or item.get("name") or ""))
            else:
                names.append(str(item))
        return names
    return []


def _parse_icfqs_json(raw: bytes) -> Any:
    """Extract the first balanced JSON object from a possibly prefixed payload.

    Mirrors gotdx parseICFQSTQLResponse: scan from the first ``{`` while
    tracking brace depth, skipping quoted strings and escape characters.
    """

    start = raw.find(b"{")
    if start < 0:
        raise ValueError(f"cannot parse icfqs response: {_icfqs_preview(raw)}")
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(raw)):
        char = raw[index]
        if escape:
            escape = False
            continue
        if char == 0x5C:  # backslash
            escape = True
            continue
        if char == 0x22:  # double quote
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == 0x7B:  # {
            depth += 1
        elif char == 0x7D:  # }
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start : index + 1])
                except json.JSONDecodeError as exc:
                    raise ValueError(f"cannot parse icfqs response: {_icfqs_preview(raw)}") from exc
    raise ValueError(f"cannot parse icfqs response: {_icfqs_preview(raw)}")


def _icfqs_preview(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    return text if len(text) <= 200 else text[:200]


def _icfqs_gateway_url(override: str | None, env_name: str, fallback: str) -> str:
    raw = (override or os.getenv(env_name) or "").strip()
    if not raw:
        raw = fallback
    if "://" not in raw:
        raw = f"http://{raw}"
    return raw.rstrip("/")
