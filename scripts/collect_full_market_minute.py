"""Batched full-market minute collection driver (AxData-side ops, plan 18).

Collects, via the documented ``axdata plugin collector-run`` CLI:
- stocks:  all SH/SZ/BSE stocks, 1m/5m bars, adjust=none. The stock minute
  interface (``stock_kline_minute_tdx``) has no count parameter; the stock
  kind auto-pages up to the TDX server retention cap: 1m ~= 95 trading days
  (~22800 rows/code), 5m ~= 495 trading days (~23760 rows/code). This depth
  limit is TDX retention policy, not a script option -- the driver documents
  it honestly and never fabricates older bars.
- indices: every index from the TDX catalog (official + tdx board/theme
  880/881 series), 1m/5m bars, full_history paging. Reuses the existing
  ``tdx.index_kline_tdx.snapshot`` collector with a driver-side ``--output-dir``
  override to route rows into the separate ``index_minute`` table; the engine
  keeps one-interface-one-table, so no new index spec is added. PK semantics
  (instrument_id, trade_time, period) for the routed table are guaranteed by
  this driver's verify step, not by the collector spec.

15m and longer periods are NEVER collected: they are synthesized locally from
5m bars (5m x 3 -> 15m OHLC). This script only ingests native 1m/5m.

Landing tables (snapshot write mode, one parquet per batch, disjoint codes):
- core/table=minute        stock 1m/5m bars (all periods mixed per batch file)
- core/table=index_minute  index 1m/5m bars (driver --output-dir routed)

Usage (repo root cwd, parent venv python):
    python scripts/collect_full_market_minute.py stocks  --period 1m|5m
                                      [--batch-size 50] [--parallel 2]
                                      [--server-count 4] [--pool 2]
                                      [--limit N] [--dry-run]
    python scripts/collect_full_market_minute.py indices --period 1m|5m
                                      [same options]
    python scripts/collect_full_market_minute.py missing --kind stocks|indices
                                      --period 1m|5m [--rounds 2]
    python scripts/collect_full_market_minute.py verify
    python scripts/collect_full_market_minute.py synthesize-check

Resume: completed batches are recorded in
logs/collect_full_market_minute_state.json per (kind, period) and skipped on
re-run. A batch either lands whole or not at all (collector-run accumulates
then writes one file), so re-running a failed batch is safe. Landed data is
the only skip authority; state entries never override the landed check.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
#: data root honors AXDATA_DATA_DIR so the collection can follow a data root
#: migrated out of the submodule working tree (same convention as the daily driver)
DATA_ROOT = Path(os.environ.get("AXDATA_DATA_DIR") or (REPO_ROOT / "data"))
STATE_PATH = REPO_ROOT / "logs" / "collect_full_market_minute_state.json"
#: table -> (dir signature, {period: landed tdx_code set}); see _landed_codes
_LANDED_CACHE: dict[str, tuple[tuple[int, int], dict[str, set[str]]]] = {}

PERIODS = ("1m", "5m")
DEFAULT_BATCH_SIZE = 50
DEFAULT_PARALLEL = 2
DEFAULT_SERVER_COUNT = 4
DEFAULT_POOL = 2
#: max rows a single batch can write (~50 codes x 22800 1m bars); keep well
#: under the 1.2M rows/process budget so the collector process stays lean.
#: 5m has fewer bars per code so the same batch size is fine.
MAX_BATCH_ROWS = 1_200_000

#: TDX 服务器保留深度下限（交易日数，distinct date 近似），1m~95/5m~495 是
#: 服务器保留策略，verify 只做"不得低于诚实声明"的下限校验。
DEPTH_MIN_TRADING_DAYS = {"1m": 90, "5m": 485}
#: 单 code 单日 bar 数硬上限（240 = 4 小时 x 60，48 = 240/5）。
SESSION_BAR_CAPS = {"1m": 240, "5m": 48}
#: 已知无分钟行情的零行情豁免清单（长期停牌/退市整理/北交所极少数），
#: verify 覆盖率不计入缺失；采集时仍会请求，只是允许永远不落地。
ZERO_QUOTE_EXEMPTIONS = frozenset(
    {
        "bj920059",
        "bj920093",
        "bj920107",
        "sh601123",
        "sh688826",
        "sh688835",
        "sh688836",
        "sz301655",
        "sz301688",
        "sz301697",
    }
)
#: 全市场标的数下限（sanity floor）：若实时代码列表小于该数，说明代码枚举
#: 链路异常，verify 直接报 hard fail，避免用残缺列表掩盖覆盖率。
EXPECTED_UNIVERSE_FLOOR = {"stocks": 5542, "indices": 1678}


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {f"{kind}_{period}": [] for kind in ("stocks", "indices") for period in PERIODS}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE_PATH)


def _axdata_cli() -> list[str]:
    import shutil

    exe = shutil.which("axdata")
    if exe:
        return [exe]
    candidate = Path(sys.executable).parent / "axdata.exe"
    if candidate.exists():
        return [str(candidate)]
    raise SystemExit("axdata CLI not found on PATH or next to the interpreter")


def _client():
    from axdata import AxDataClient

    return AxDataClient()


def _stock_codes() -> list[str]:
    df = _client().call("stock_codes_tdx", scope="all")
    return sorted(str(code) for code in df["tdx_code"].tolist())


def _index_codes() -> list[str]:
    df = _client().call("index_codes_tdx", include_tdx_block_index=True)
    return sorted(str(code) for code in df["tdx_code"].tolist())


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _table_for_kind(kind: str) -> str:
    return "minute" if kind.startswith("stocks") else "index_minute"


def _run_batch(
    kind: str,
    period: str,
    batch_id: int,
    codes: list[str],
    extra_args: list[str],
    max_retries: int = 2,
) -> dict:
    collector = (
        "tdx.stock_kline_minute_tdx.snapshot"
        if kind.startswith("stocks")
        else "tdx.index_kline_tdx.snapshot"
    )
    params = (
        {"code": ",".join(codes), "period": period, "adjust": "none"}
        if kind.startswith("stocks")
        else {"code": ",".join(codes), "period": period, "full_history": True}
    )
    argv = _axdata_cli() + [
        "plugin",
        "collector-run",
        collector,
        "--params",
        json.dumps(params),
        "--json",
        *extra_args,
    ]
    if kind.startswith("indices"):
        # deliberate driver-side routing: index minute rows land in the
        # separate index_minute table (see module docstring for why)
        argv += ["--output-dir", str(DATA_ROOT / "core" / "table=index_minute" / "parquet")]
    t0 = time.time()
    result: dict | None = None
    for _attempt in range(max_retries + 1):
        # each attempt is a fresh process -> fresh TDX host selection; some
        # public hosts carry no BSE/BJ quotes and return 0 rows, so an empty
        # write is treated as a failure and retried on other hosts.
        if _attempt > 0 and _batch_already_landed(kind, period, codes):
            # a previous attempt wrote the batch but we failed to parse its
            # output (or were killed before saving state): re-running would
            # write a second overlapping file, so accept it as landed.
            result = {
                "batch": batch_id,
                "codes": len(codes),
                "rows": "already-landed",
                "ok": True,
                "seconds": round(time.time() - t0, 1),
                "stderr_tail": "",
            }
            break
        proc = subprocess.run(argv, cwd=str(REPO_ROOT), capture_output=True, text=True)
        rows = None
        if proc.returncode == 0:
            try:
                payload = json.loads(proc.stdout)
                meta = payload.get("download_result", {}).get("write_metadata", {})
                rows = int(meta.get("rows_written", -1))
            except (json.JSONDecodeError, TypeError, ValueError):
                rows = None
        result = {
            "batch": batch_id,
            "codes": len(codes),
            "rows": rows,
            "ok": proc.returncode == 0 and rows is not None and rows > 0,
            "seconds": round(time.time() - t0, 1),
            "stderr_tail": proc.stderr.strip()[-400:] if proc.returncode else "",
        }
        if result["ok"]:
            break
    assert result is not None
    return result


def _landed_codes(table: str, period: str) -> set[str]:
    """Landed tdx_code set for (table, period), read per file and unioned.

    The minute table mixes 1m/5m (and later synthesized 15m+) rows in the same
    batch files, so per-file reads filter the ``period`` column instead of
    trusting filenames. Each batch file holds at most DEFAULT_BATCH_SIZE codes;
    per-file filtering keeps memory flat -- a full-table concat over ~340M rows
    would blow the process, so this never builds a combined frame.
    """

    import pandas as pd

    table_dir = DATA_ROOT / "core" / f"table={table}" / "parquet"
    files = sorted(table_dir.glob("*.parquet"))
    signature = (len(files), max((f.stat().st_mtime_ns for f in files), default=0))
    cached = _LANDED_CACHE.get(table)
    if cached is not None and cached[0] == signature:
        return cached[1].get(period, set())
    landed: dict[str, set[str]] = {}
    for f in files:
        try:
            df = pd.read_parquet(f, columns=["period", "tdx_code"])
        except Exception:  # noqa: BLE001 - zero-column debris from aborted runs
            print(f"  warn: skipping unreadable/no-column file {f.name}", file=sys.stderr)
            continue
        if df.empty:
            continue
        if "period" not in df.columns or "tdx_code" not in df.columns:
            print(
                f"  warn: skipping file without period/tdx_code columns {f.name}", file=sys.stderr
            )
            continue
        for present in df["period"].dropna().unique():
            landed.setdefault(str(present), set()).update(
                df.loc[df["period"] == present, "tdx_code"].tolist()
            )
    _LANDED_CACHE[table] = (signature, landed)
    return landed.get(period, set())


def _batch_already_landed(kind: str, period: str, codes: list[str]) -> bool:
    # batch writes are atomic single files over disjoint code sets, so any
    # landed code implies the whole batch landed
    return bool(_landed_codes(_table_for_kind(kind), period).intersection(codes))


def _missing_rounds(kind: str, period: str, rounds: int) -> int:
    exemptions = ZERO_QUOTE_EXEMPTIONS if kind.startswith("stocks") else frozenset()
    for round_no in range(1, rounds + 1):
        expected = _stock_codes() if kind == "stocks" else _index_codes()
        landed = _landed_codes(_table_for_kind(kind), period)
        missing = [c for c in expected if c not in landed and c not in exemptions]
        print(
            f"missing sweep {kind} {period} round {round_no}: "
            f"{len(missing)} codes absent (exempt {len(exemptions)})"
        )
        if not missing:
            return 0
        code = _collect(
            f"{kind}_missing",
            period,
            batch_size=DEFAULT_BATCH_SIZE,
            parallel=DEFAULT_PARALLEL,
            limit=None,
            dry_run=False,
            extra_args=_concurrency_args(),
            codes_override=missing,
        )
        if code != 0 and round_no == rounds:
            still = [
                c
                for c in expected
                if c not in _landed_codes(_table_for_kind(kind), period) and c not in exemptions
            ]
            print(f"still missing after {rounds} rounds: {len(still)} {still[:20]}")
            return 1
    return 0


def _concurrency_args() -> list[str]:
    return [
        "--source-server-count",
        str(DEFAULT_SERVER_COUNT),
        "--connections-per-server",
        str(DEFAULT_POOL),
    ]


def _collect(
    kind: str,
    period: str,
    *,
    batch_size: int,
    parallel: int,
    limit: int | None,
    dry_run: bool,
    extra_args: list[str],
    codes_override: list[str] | None = None,
) -> int:
    codes = (
        codes_override
        if codes_override is not None
        else (_stock_codes() if kind.startswith("stocks") else _index_codes())
    )
    if limit:
        codes = codes[:limit]
    batches = _chunks(codes, batch_size)
    print(
        f"{kind} {period}: {len(codes)} codes -> {len(batches)} batches "
        f"(size={batch_size}, parallel={parallel}, max_rows/batch~={MAX_BATCH_ROWS})"
    )

    def batch_key(chunk: list[str]) -> str:
        import hashlib

        return hashlib.sha256(",".join(chunk).encode()).hexdigest()[:16]

    state = _load_state()
    done = set(state.get(f"{kind}_{period}", []))
    landed = _landed_codes(_table_for_kind(kind), period)
    # landed data is the ONLY truth: state entries must never override it
    pending = [(i, chunk) for i, chunk in enumerate(batches) if not landed.intersection(chunk)]
    if not pending:
        print("nothing to do (all batches complete)")
        return 0
    if dry_run:
        for i, chunk in pending[:3]:
            print(f"  batch {i}: {len(chunk)} codes, e.g. {chunk[:3]}")
        print(f"  ... {len(pending)} batches pending")
        return 0

    failures = 0
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {
            pool.submit(_run_batch, kind, period, i, chunk, extra_args): i for i, chunk in pending
        }
        for future in as_completed(futures):
            result = future.result()
            if result["ok"]:
                done.add(batch_key(batches[result["batch"]]))
                state[f"{kind}_{period}"] = sorted(done)
                _save_state(state)
                print(
                    f"  batch {result['batch']}: ok codes={result['codes']} "
                    f"rows={result['rows']} {result['seconds']}s"
                )
            else:
                failures += 1
                print(
                    f"  batch {result['batch']}: FAILED {result['seconds']}s "
                    f"{result['stderr_tail'][:200]}",
                    file=sys.stderr,
                )
    print(
        f"{kind} {period}: {len(pending) - failures}/{len(pending)} batches ok, "
        f"{failures} failed (re-run to resume)"
    )
    return 1 if failures else 0


def _verify() -> int:
    import duckdb

    con = duckdb.connect()
    problems: list[str] = []
    for table in ("minute", "index_minute"):
        table_dir = DATA_ROOT / "core" / f"table={table}" / "parquet"
        files = sorted(table_dir.glob("*.parquet"))
        if not files:
            problems.append(f"{table}: no files")
            continue
        glob = str(table_dir / "*.parquet")
        # ② duplicate PK across the whole table (period is part of the PK)
        dup_pk = con.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT instrument_id, trade_time, period, COUNT(*) c"
            "  FROM read_parquet(?) GROUP BY 1, 2, 3 HAVING c > 1"
            ")",
            [glob],
        ).fetchone()[0]
        print(f"{table}: files={len(files)} dup_pk={dup_pk}")
        if dup_pk:
            problems.append(
                f"{table}: {dup_pk} duplicate PK (instrument_id, trade_time, period) rows"
            )
        kind = "stocks" if table == "minute" else "indices"
        expected = _expected_universe(kind, problems)
        for period in PERIODS:
            _verify_period(con, table, kind, period, glob, expected, problems)
    for p in problems:
        print(f"PROBLEM: {p}", file=sys.stderr)
    return 1 if problems else 0


def _expected_universe(kind: str, problems: list[str]) -> set[str]:
    """Live code universe with a sanity floor so a broken enumeration never
    masks coverage. Returns the code set or empty on enumeration failure."""

    try:
        expected = set(_stock_codes() if kind == "stocks" else _index_codes())
    except Exception as exc:  # noqa: BLE001 - network enumeration failure
        problems.append(f"{kind}: cannot enumerate expected universe ({exc})")
        return set()
    floor = EXPECTED_UNIVERSE_FLOOR[kind]
    if len(expected) < floor:
        problems.append(f"{kind}: expected universe {len(expected)} < floor {floor}")
    return expected


def _verify_period(
    con,
    table: str,
    kind: str,
    period: str,
    glob: str,
    expected: set[str],
    problems: list[str],
) -> None:
    # ① coverage: missing = expected - landed - known zero-quote exemptions
    landed = _landed_codes(table, period)
    exemptions = ZERO_QUOTE_EXEMPTIONS if kind == "stocks" else frozenset()
    missing = sorted(c for c in expected if c not in landed and c not in exemptions)
    print(
        f"coverage {table} {period}: {len(expected) - len(missing)}/{len(expected)} "
        f"missing={len(missing)} exempt={len(exemptions)}"
    )
    if missing:
        print(f"  first missing ({period}): {missing[:50]}")
        problems.append(f"{table} {period}: {len(missing)} codes missing")

    # ③ depth: distinct trading-date count must not fall below the honest
    # server-retention floor (1m~95/5m~495 trading days)
    depth = con.execute(
        "SELECT COUNT(DISTINCT CAST(trade_time AS DATE)) FROM read_parquet(?) WHERE period = ?",
        [glob, period],
    ).fetchone()[0]
    floor = DEPTH_MIN_TRADING_DAYS[period]
    print(f"depth {table} {period}: {depth} distinct dates (floor {floor})")
    if depth < floor:
        problems.append(f"{table} {period}: depth {depth} < {floor} trading days")

    # ④ session completeness: a single code/date must not exceed the bar cap
    overflow = con.execute(
        "SELECT instrument_id, CAST(trade_time AS DATE), COUNT(*) c"
        " FROM read_parquet(?) WHERE period = ?"
        " GROUP BY 1, 2 HAVING COUNT(*) > ? ORDER BY c DESC",
        [glob, period, SESSION_BAR_CAPS[period]],
    ).fetchall()
    print(f"session {table} {period}: {len(overflow)} code-day over cap {SESSION_BAR_CAPS[period]}")
    for row in overflow[:20]:
        print(f"  overflow: {row}")
    if overflow:
        problems.append(f"{table} {period}: {len(overflow)} code-day rows over bar cap")

    # ⑤ scale sanity: row-count report (informational, not a hard fail)
    total, codes, first, last = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT instrument_id), MIN(trade_time), MAX(trade_time)"
        " FROM read_parquet(?) WHERE period = ?",
        [glob, period],
    ).fetchone()
    print(f"scale {table} {period}: rows={total} codes={codes} time={first}..{last}")


def _synthesize_check() -> int:
    """Re-runnable check of the 5m -> 15m synthesis rule.

    Takes the native 5m tail (180 bars) and native 15m tail (60 bars) of three
    reference instruments, aggregates the 5m bars into 15m buckets
    (open=first / high=max / low=min / close=last, bucket = floor to 15 min),
    and asserts value-by-value equality against the native 15m OHLC. This is
    the logic already validated manually; the check pins it for regression.
    """

    import numpy as np

    client = _client()
    failures = 0
    for code in ("000001.SZ", "600000.SH", "sh000001"):
        is_index = code.startswith(("sh", "sz"))
        interface = "index_kline_tdx" if is_index else "stock_kline_minute_tdx"
        try:
            five_kwargs = (
                {"code": code, "period": "5m", "full_history": True}
                if is_index
                else {"code": code, "period": "5m", "adjust": "none"}
            )
            native15_kwargs = (
                {"code": code, "period": "15m", "full_history": True}
                if is_index
                else {"code": code, "period": "15m", "adjust": "none"}
            )
            df5 = client.call(interface, **five_kwargs).tail(180)
            df15 = client.call(interface, **native15_kwargs).tail(60)
        except Exception as exc:  # noqa: BLE001 - network request failure
            print(f"synthesize-check {code}: FAILED to fetch ({exc})", file=sys.stderr)
            failures += 1
            continue
        agg = _aggregate_5m_to_15m(df5)
        native = _native_15m_buckets(df15)
        common = agg.index.intersection(native.index)
        if len(common) < 55:
            print(
                f"synthesize-check {code}: FAILED overlap only {len(common)}/60 buckets",
                file=sys.stderr,
            )
            failures += 1
            continue
        for column in ("open", "high", "low", "close"):
            left = agg.loc[common, column].to_numpy(dtype=float)
            right = native.loc[common, column].to_numpy(dtype=float)
            if not np.allclose(left, right, rtol=1e-6, atol=1e-6):
                mismatch = int(np.count_nonzero(~np.isclose(left, right, rtol=1e-6, atol=1e-6)))
                print(
                    f"synthesize-check {code}: FAILED {column} "
                    f"{mismatch}/{len(common)} buckets differ",
                    file=sys.stderr,
                )
                failures += 1
    if failures == 0:
        print("synthesize-check: 5m x3 -> 15m OHLC matches native 15m for all targets")
        return 0
    print(f"synthesize-check: {failures} target(s) failed", file=sys.stderr)
    return 1


def _aggregate_5m_to_15m(df5):
    import pandas as pd

    work = df5.copy()
    bucket = pd.to_datetime(work["trade_time"]).dt.floor("15min")
    grouped = work.groupby(bucket).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    )
    return grouped


def _native_15m_buckets(df15):
    import pandas as pd

    work = df15.copy()
    bucket = pd.to_datetime(work["trade_time"]).dt.floor("15min")
    indexed = work.set_index(bucket)
    return indexed[["open", "high", "low", "close"]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name in ("stocks", "indices"):
        p = sub.add_parser(name)
        p.add_argument("--period", choices=PERIODS, required=True)
        p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
        p.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL)
        p.add_argument("--server-count", type=int, default=DEFAULT_SERVER_COUNT)
        p.add_argument("--pool", type=int, default=DEFAULT_POOL)
        p.add_argument("--limit", type=int, default=None, help="only first N codes (smoke)")
        p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("missing", help="sweep codes absent from landed data")
    p.add_argument("--kind", choices=("stocks", "indices"), default="stocks")
    p.add_argument("--period", choices=PERIODS, required=True)
    p.add_argument("--rounds", type=int, default=2)

    sub.add_parser("verify", help="duckdb-based completeness/duplication/depth/session checks")
    sub.add_parser("synthesize-check", help="assert 5m x3 aggregates to native 15m OHLC")

    args = parser.parse_args(argv)
    if args.cmd == "verify":
        return _verify()
    if args.cmd == "synthesize-check":
        return _synthesize_check()
    if args.cmd == "missing":
        return _missing_rounds(args.kind, args.period, args.rounds)
    extra = [
        "--source-server-count",
        str(args.server_count),
        "--connections-per-server",
        str(args.pool),
    ]
    return _collect(
        args.cmd,
        args.period,
        batch_size=args.batch_size,
        parallel=args.parallel,
        limit=args.limit,
        dry_run=args.dry_run,
        extra_args=extra,
    )


if __name__ == "__main__":
    raise SystemExit(main())
