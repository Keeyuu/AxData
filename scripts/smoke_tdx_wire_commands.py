"""Real-host smoke matrix over every registered _tdx_wire 7709 command (plan 19 §5.2 P2).

Iterates all 45 commands registered in ``_tdx_wire._command_dispatch``
(33 main-station + 12 MAC), builds one minimal payload per command (params
inferred from each builder's required fields, symbols sz000001 / sh600000 /
index sh000001), and sends each frame over a real socket:

- main-station commands -> the quote host pool resolved by
  ``axdata_source_tdx.host_config.configured_tdx_hosts_from_options``
- MAC commands -> the MAC host group from
  ``axdata_source_tdx.host_config.configured_tdx_mac_hosts``

Read-only by construction: every command below is a query; nothing writes
AxData data, state, or files beyond the JSON + matrix outputs of this script.

Statuses are recorded honestly per (command, host): ``ok`` (parsed, non-empty),
``empty`` (parsed, zero records -- a known capability boundary on some server
versions, plan 19 §7.5), ``error`` (build/parse/transport failure), ``timeout``.
Failing commands are recorded, never patched here.

Usage (repo root cwd, parent venv python):
    python scripts/smoke_tdx_wire_commands.py [--hosts N] [--only substr,...]
        [--timeout 6] [--pause-ms 200] [--out-dir PATH] [--quiet]

Outputs (under --out-dir, default <skynet-root>/tmp/wire-smoke):
    wire_smoke_<YYYYmmdd_HHMMSS>.json  full per-(command, host) records
    matrix.md                          command x host support matrix (rewritten)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT.parent.parent / "tmp" / "wire-smoke"
DEFAULT_HOSTS = 2
DEFAULT_TIMEOUT = 6.0
DEFAULT_PAUSE_MS = 200.0

#: 主站/MAC 命令分界：dispatch 顺序里 ``mac_`` 前缀即 MAC host 组。
MAC_PREFIX = "mac_"


def _resolve_trade_date() -> str:
    """Most recent Mon-Fri date (approximate last trade date; holidays return empty)."""

    day = date.today()
    day = date.today()
    while day.weekday() >= 5:
        day = date.fromordinal(day.toordinal() - 1)
    return day.strftime("%Y%m%d")


#: 45 个注册命令的最小 payload（顺序 = _command_dispatch.BUILDER_TARGET_ITEMS）。
#: 参数只填各 build_*_frame 的必填项/小页容量；其余走 builder 默认。
#: mac_symbol_belong_board 与 mac_capital_flow 同码 0x1218，按 query 常量分流
#: （Stock_GLHQ vs 默认 Stock_ZJLX），故 belong_board 必须显式带 query。
def _command_payloads(trade_date: str) -> dict[str, dict[str, Any]]:
    securities = [("sz", "000001"), ("sh", "600000")]
    return {
        "heartbeat": {},
        "handshake": {},
        "capital_changes": {"code": "sz000001"},
        "finance_info": {"code": "sz000001"},
        "server_info": {},
        "file_meta": {"path": "tdxfin/gpcw.txt"},
        "security_list": {"market": "sz", "start": 0, "limit": 20},
        "security_count": {"market": "sz"},
        "security_list_old": {"market": "sz", "start": 0},
        "price_limits": {"start_index": 0},
        "volume_profile": {"code": "sz000001"},
        "intraday_subchart": {"code": "sz000001"},
        "index_momentum": {"code": "sh000001"},
        "index_info": {"code": "sh000001"},
        "klines": {"code": "sz000001", "period": "day", "start": 0, "count": 10},
        "today_intraday": {"code": "sz000001"},
        "legacy_quotes": {"securities": securities},
        "top_board": {},
        "refresh_quotes": {"cursors": [("sz", "000001", 0)]},
        "category_quotes": {"category": 6, "count": 20},
        "explicit_quotes": {"securities": securities},
        "unusual": {"market": "sz", "count": 20},
        "auction_process": {"code": "sz000001", "count": 50},
        "file_content": {"path": "tdxfin/gpcw.txt", "offset": 0, "size": 256},
        "historical_intraday": {"code": "sz000001", "trade_date": trade_date},
        "today_trades": {"code": "sz000001", "count": 30},
        "historical_trades": {"code": "sz000001", "trade_date": trade_date, "count": 30},
        "historical_trades_basic": {"code": "sz000001", "trade_date": trade_date, "count": 30},
        "announcement": {},
        "exchange_announcement": {},
        "klines_0523": {"code": "sz000001", "period": "day", "start": 0, "count": 10},
        "chart_sampling": {"code": "sz000001"},
        "recent_historical_intraday": {"code": "sz000001", "trade_date": trade_date},
        "mac_server_info": {},
        "mac_file_list": {"filename": "StockInfo.dat", "offset": 16},
        "mac_file_download": {"filename": "StockInfo.dat", "index": 1, "offset": 0, "size": 512},
        "mac_capital_flow": {"code": "sz000001"},
        "mac_symbol_belong_board": {"code": "sz000001", "query": "Stock_GLHQ"},
        "mac_symbol_info": {"code": "sz000001"},
        "mac_symbol_quotes": {"securities": ["sz000001", "sh600000"]},
        "mac_board_members": {"board_symbol": "880001", "page_size": 20},
        "mac_quotes": {"code": "sz000001"},
        "mac_symbol_bars": {"code": "sz000001", "period": 4, "count": 10},
        "mac_transactions": {"code": "sz000001", "count": 30},
        "mac_board_list": {"board_type": 0, "page_size": 20},
        "mac_market_monitor": {"market": "sz", "count": 20},
        "mac_auction": {"code": "sz000001", "count": 50},
        "mac_tick_charts": {"code": "sz000001", "days": 5},
        "mac_kline_offset": {"offset": 0, "count": 256},
    }


def _command_specs() -> list[tuple[str, int, dict[str, Any]]]:
    from axdata_source_tdx._tdx_wire._command_codes import COMMAND_CODE_ITEMS

    payloads = _command_payloads(_resolve_trade_date())
    missing = [name for name, _ in COMMAND_CODE_ITEMS if name not in payloads]
    if missing:
        raise SystemExit(f"payload table missing commands: {missing}")
    return [(name, code, payloads[name]) for name, code in COMMAND_CODE_ITEMS]


def _host_groups(host_count: int) -> dict[str, list[str]]:
    from axdata_source_tdx.host_config import (
        configured_tdx_hosts_from_options,
        configured_tdx_mac_hosts,
    )

    main_pool = list(configured_tdx_hosts_from_options({}))
    mac_pool = list(configured_tdx_mac_hosts())
    return {
        "main": main_pool[:host_count],
        "mac": mac_pool[:host_count],
        "main_pool_size": main_pool,
        "mac_pool_size": mac_pool,
    }


def _summarize(result: Any, depth: int = 0) -> dict[str, Any]:
    """Small honest summary: record counts per collection field, no full dumps."""

    try:
        if result is None:
            return {"kind": "none"}
        if isinstance(result, bool):
            return {"value": result}
        if isinstance(result, (int, float)):
            return {"value": result}
        if isinstance(result, str):
            return {"value": result[:60], "chars": len(result)}
        if isinstance(result, (bytes, bytearray)):
            return {"bytes": len(result)}
        if is_dataclass(result):
            summary: dict[str, Any] = {}
            for field in fields(result):
                if field.name == "raw_payload":
                    continue
                value = getattr(result, field.name)
                if (
                    isinstance(value, (list, tuple, bytes, bytearray))
                    or is_dataclass(value)
                    and depth < 1
                ):
                    summary[field.name] = _summarize(value, depth + 1)
                elif isinstance(value, (int, float, str, bool)) or value is None:
                    text = str(value)
                    summary[field.name] = value if len(text) <= 40 else text[:40]
            return summary
        if hasattr(result, "__len__"):
            return {"count": len(result)}
        return {"kind": type(result).__name__}
    except Exception as exc:  # pragma: no cover - summary must never fail the smoke
        return {"summary_error": f"{type(exc).__name__}: {exc}"}


def _record_count(result: Any) -> int:
    """Records seen: collection length; dataclass uses collection fields only
    (scalar-only snapshots count 1, ``total==0`` tables count 0 -> empty)."""

    try:
        if result is None:
            return 0
        if isinstance(result, bool):
            return 1
        if isinstance(result, (int, float)):
            return 1
        if isinstance(result, str):
            return 1 if result else 0
        if isinstance(result, (bytes, bytearray)):
            return len(result)
        if is_dataclass(result):
            counts: list[int] = []
            total_value: int | None = None
            for field in fields(result):
                if field.name == "raw_payload":
                    continue
                value = getattr(result, field.name)
                if isinstance(value, (list, tuple, bytes, bytearray)):
                    counts.append(len(value))
                elif field.name == "total" and isinstance(value, int):
                    total_value = value
            if counts:
                return max(counts)
            if total_value == 0:
                return 0
            return 1
        if hasattr(result, "__len__"):
            return len(result)
        return 1
    except Exception:
        return 1


def _is_timeout(exc: BaseException) -> bool:
    name = type(exc).__name__
    return "timeout" in name.lower() or "timed out" in str(exc).lower()


def _smoke_command_on_host(
    client: Any,
    name: str,
    code: int,
    payload: dict[str, Any],
    host: str,
) -> dict[str, Any]:
    from axdata_source_tdx._tdx_wire.exceptions import ResponseTimeoutError

    started = time.perf_counter()
    try:
        result = client.transport.execute(code, dict(payload))
    except ResponseTimeoutError as exc:
        return _record(name, code, "timeout", host, started, error=str(exc), payload=payload)
    except Exception as exc:
        status = "timeout" if _is_timeout(exc) else "error"
        detail = f"{type(exc).__name__}: {exc}"
        return _record(name, code, status, host, started, error=detail, payload=payload)
    count = _record_count(result)
    status = "ok" if count > 0 else "empty"
    return _record(
        name, code, status, host, started, count=count, summary=_summarize(result), payload=payload
    )


def _record(
    name: str,
    code: int,
    status: str,
    host: str,
    started: float,
    *,
    count: int | None = None,
    summary: dict[str, Any] | None = None,
    error: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "command": name,
        "code": f"0x{code:04X}",
        "status": status,
        "host": host,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
        "record_count": count,
        "summary": summary,
        "error": error,
        "payload": payload,
    }


def _run(
    specs: list[tuple[str, int, dict[str, Any]]],
    groups: dict[str, list[str]],
    timeout: float,
    pause_ms: float,
    quiet: bool,
) -> list[dict[str, Any]]:
    from axdata_source_tdx._tdx_wire.client import TdxClient

    results: list[dict[str, Any]] = []
    main_hosts, mac_hosts = groups["main"], groups["mac"]
    for name, code, payload in specs:
        group = "mac" if name.startswith(MAC_PREFIX) else "main"
        hosts = mac_hosts if group == "mac" else main_hosts
        for host in hosts:
            client = TdxClient.from_hosts(
                hosts=[host], timeout=timeout, pool_size=1, heartbeat_interval=None
            )
            try:
                client.connect()
                row = _smoke_command_on_host(client, name, code, payload, host)
            finally:
                client.close()
            results.append(row)
            if not quiet:
                mark = {
                    "ok": "ok  ",
                    "empty": "empty",
                    "error": "error",
                    "timeout": "timeout",
                }[row["status"]]
                detail = row.get("record_count")
                tail = f"records={detail}" if detail is not None else (row.get("error") or "")[:70]
                head = f"[{mark}] {row['code']} {name:<28} {host:<22}"
                print(f"{head} {row['elapsed_ms']:>8.0f}ms {tail}", flush=True)
            time.sleep(pause_ms / 1000.0)
    return results


def _write_outputs(
    results: list[dict[str, Any]],
    groups: dict[str, list[str]],
    args: argparse.Namespace,
    trade_date: str,
    out_dir: Path,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    json_path = out_dir / f"wire_smoke_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    matrix_path = out_dir / "matrix.md"

    main_hosts, mac_hosts = groups["main"], groups["mac"]
    counters = {status: 0 for status in ("ok", "empty", "error", "timeout")}
    for row in results:
        counters[row["status"]] += 1

    payload_doc = {
        "generated_at": generated_at,
        "args": {key: value for key, value in vars(args).items()},
        "trade_date_used": trade_date,
        "main_host_pool": groups["main_pool_size"],
        "mac_host_pool": groups["mac_pool_size"],
        "main_hosts_used": main_hosts,
        "mac_hosts_used": mac_hosts,
        "counts": counters,
        "results": results,
    }
    json_path.write_text(
        json.dumps(payload_doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    matrix_path.write_text(
        _render_matrix(results, groups, counters, generated_at, args, trade_date),
        encoding="utf-8",
    )
    return json_path, matrix_path


def _cell(row: dict[str, Any] | None) -> str:
    if row is None:
        return "-"
    status = row["status"]
    if status == "ok":
        return f"ok({row.get('record_count')})"
    if status == "error":
        text = (row.get("error") or "").replace("|", "/")
        return f"error: {text[:44]}"
    return status


def _render_matrix(
    results: list[dict[str, Any]],
    groups: dict[str, list[str]],
    counters: dict[str, int],
    generated_at: str,
    args: argparse.Namespace,
    trade_date: str,
) -> str:
    main_hosts, mac_hosts = groups["main"], groups["mac"]
    by_key = {(row["command"], row["host"]): row for row in results}
    commands = []
    for row in results:
        if row["command"] not in commands:
            commands.append(row["command"])

    lines = [
        "# _tdx_wire 命令 × host 真机支持矩阵（plan 19 §5.2 P2 smoke）",
        "",
        f"> 生成：{generated_at}；timeout={args.timeout}s；pause={args.pause_ms}ms；"
        f"示例 trade_date={trade_date}（近端工作日，节假日可能空）",
        "> host 来源：`axdata_source_tdx.host_config`（主站=quote 池，MAC=MAC 组）；"
        "只读查询，不写任何数据。",
        "> 状态：`ok(n)`=解析成功且 n 条记录；`empty`=解析成功但 0 条；`error`=构造/解析/传输失败；"
        "`timeout`=超时。空响应与错误如实区分（§7.5 已知能力边界）。",
        "",
        "## 汇总",
        "",
        f"- 命令×host 单元 {len(results)} 个：ok={counters['ok']}，empty={counters['empty']}，"
        f"error={counters['error']}，timeout={counters['timeout']}",
        f"- 主站池 {len(groups['main_pool_size'])} 台取前 {len(main_hosts)} 台：",
        f"  {', '.join(main_hosts)}",
        f"- MAC 池 {len(groups['mac_pool_size'])} 台取前 {len(mac_hosts)} 台：",
        f"  {', '.join(mac_hosts)}",
        "",
        "## 主站命令（33）",
        "",
        "| 命令 | " + " | ".join(main_hosts) + " |",
        "|---" * (len(main_hosts) + 1) + "|",
    ]
    for command in commands:
        if command.startswith(MAC_PREFIX):
            continue
        cells = [_cell(by_key.get((command, host))) for host in main_hosts]
        lines.append(f"| `{command}` | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## MAC 命令（12）",
        "",
        "| 命令 | " + " | ".join(mac_hosts) + " |",
        "|---" * (len(mac_hosts) + 1) + "|",
    ]
    for command in commands:
        if not command.startswith(MAC_PREFIX):
            continue
        cells = [_cell(by_key.get((command, host))) for host in mac_hosts]
        lines.append(f"| `{command}` | " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hosts", type=int, default=DEFAULT_HOSTS, help="hosts per group")
    parser.add_argument("--only", default="", help="comma-separated name substrings filter")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="timeout s")
    parser.add_argument("--pause-ms", type=float, default=DEFAULT_PAUSE_MS, help="pause ms")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="output directory")
    parser.add_argument("--quiet", action="store_true", help="suppress per-command console lines")
    args = parser.parse_args(argv)
    if args.hosts < 1:
        parser.error("--hosts must be >= 1")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    specs = _command_specs()
    if args.only:
        wanted = [item.strip() for item in args.only.split(",") if item.strip()]
        specs = [spec for spec in specs if any(item in spec[0] for item in wanted)]
        if not specs:
            print(f"no command matches --only {args.only!r}", file=sys.stderr)
            return 2
    groups = _host_groups(args.hosts)
    trade_date = _resolve_trade_date()
    print(
        f"smoke {len(specs)} commands; main={groups['main']} mac={groups['mac']} "
        f"timeout={args.timeout}s pause={args.pause_ms}ms trade_date={trade_date}",
        flush=True,
    )
    results = _run(specs, groups, args.timeout, args.pause_ms, args.quiet)
    json_path, matrix_path = _write_outputs(results, groups, args, trade_date, args.out_dir)
    counters = {status: 0 for status in ("ok", "empty", "error", "timeout")}
    for row in results:
        counters[row["status"]] += 1
    print(
        f"done: {len(results)} cells ok={counters['ok']} empty={counters['empty']} "
        f"error={counters['error']} timeout={counters['timeout']}",
        flush=True,
    )
    print(f"json:   {json_path}", flush=True)
    print(f"matrix: {matrix_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
