"""Batched full-market daily collection driver (AxData-side ops, plan 16).

Collects, via the documented ``axdata plugin collector-run`` CLI:
- stocks:  all SH/SZ/BSE stocks, daily bars, adjust=qfq, full history to
  listing day
- indices: every index from the TDX catalog (official + tdx board/theme
  880/881 series), daily bars, full history to index origin

Landing tables (snapshot write mode, one parquet per batch, disjoint codes):
- core/table=daily         stock daily bars (qfq)
- core/table=index_daily   index daily bars
- core/table=index_catalog index directory (single run, complete)

Usage (repo root cwd, parent venv python):
    python scripts/collect_full_market_daily.py stocks  [--batch-size 400]
                                       [--server-count 8] [--pool 4] [--limit N] [--dry-run]
    python scripts/collect_full_market_daily.py indices [--batch-size 200]
                                                         [--parallel 3] [--limit N] [--dry-run]
    python scripts/collect_full_market_daily.py missing [--kind stocks|indices] [--rounds 2]
    python scripts/collect_full_market_daily.py catalog
    python scripts/collect_full_market_daily.py verify
    python scripts/collect_full_market_daily.py catalog
    python scripts/collect_full_market_daily.py verify

Resume: completed batches are recorded in logs/collect_full_market_state.json
and skipped on re-run. A batch either lands whole or not at all (collector-run
accumulates then writes one file), so re-running a failed batch is safe.
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
#: migrated out of the submodule working tree (plan 16 / oracle condition 3)
DATA_ROOT = Path(os.environ.get("AXDATA_DATA_DIR") or (REPO_ROOT / "data"))
STATE_PATH = REPO_ROOT / "logs" / "collect_full_market_state.json"


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"stocks": [], "indices": []}


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


def _run_batch(
    kind: str,
    batch_id: int,
    codes: list[str],
    extra_args: list[str],
    max_retries: int = 2,
) -> dict:
    collector = (
        "tdx.stock_kline_daily_tdx.snapshot"
        if kind.startswith("stocks")
        else "tdx.index_kline_tdx.snapshot"
    )
    argv = _axdata_cli() + [
        "plugin",
        "collector-run",
        collector,
        "--params",
        json.dumps(
            {"code": ",".join(codes), "adjust": "qfq"}
            if kind.startswith("stocks")
            else {"code": ",".join(codes), "period": "day", "full_history": True}
        ),
        "--json",
        *extra_args,
    ]
    t0 = time.time()
    result: dict | None = None
    for _attempt in range(max_retries + 1):
        # each attempt is a fresh process -> fresh TDX host selection; some
        # public hosts carry no BSE/BJ quotes and return 0 rows, so an empty
        # write is treated as a failure and retried on other hosts.
        if _attempt > 0 and _batch_already_landed(kind, codes):
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


def _landed_codes(kind: str) -> set[str]:
    import pandas as pd

    # base-kind mapping: "stocks_missing"/"indices_missing" must read the
    # same table as their parent kind
    table = "daily" if kind.startswith("stocks") else "index_daily"
    table_dir = DATA_ROOT / "core" / f"table={table}" / "parquet"
    files = sorted(table_dir.glob("*.parquet"))
    if not files:
        return set()
    frames = [pd.read_parquet(f, columns=["tdx_code"]) for f in files]
    return set(pd.concat(frames, ignore_index=True)["tdx_code"].unique())


def _batch_already_landed(kind: str, codes: list[str]) -> bool:
    # batch writes are atomic single files over disjoint code sets, so any
    # landed code implies the whole batch landed
    return bool(_landed_codes(kind).intersection(codes))


def _missing_rounds(kind: str, rounds: int) -> int:
    for round_no in range(1, rounds + 1):
        expected = _stock_codes() if kind == "stocks" else _index_codes()
        missing = [c for c in expected if c not in _landed_codes(kind)]
        print(f"missing sweep {kind} round {round_no}: {len(missing)} codes absent")
        if not missing:
            return 0
        if kind == "indices":
            extra = []
        else:
            extra = ["--source-server-count", "4", "--connections-per-server", "2"]
        code = _collect(
            f"{kind}_missing",
            batch_size=50,
            parallel=2,
            limit=None,
            dry_run=False,
            extra_args=extra,
            codes_override=missing,
        )
        if code != 0 and round_no == rounds:
            still = [c for c in expected if c not in _landed_codes(kind)]
            print(f"still missing after {rounds} rounds: {len(still)} {still[:20]}")
            return 1
    return 0


def _collect(
    kind: str,
    *,
    batch_size: int,
    parallel: int,
    limit: int | None,
    dry_run: bool,
    extra_args: list[str],
    codes_override: list[str] | None = None,
) -> int:
    codes = codes_override if codes_override is not None else (
        _stock_codes() if kind.startswith("stocks") else _index_codes()
    )
    if limit:
        codes = codes[:limit]
    batches = _chunks(codes, batch_size)
    print(
        f"{kind}: {len(codes)} codes -> {len(batches)} batches "
        f"(size={batch_size}, parallel={parallel})"
    )

    def batch_key(chunk: list[str]) -> str:
        import hashlib

        return hashlib.sha256(",".join(chunk).encode()).hexdigest()[:16]

    state = _load_state()
    done = set(state.get(kind, []))
    landed = _landed_codes(kind)
    # reconcile against landed data first: a batch whose codes are already on
    # disk is complete even if the state file missed it (killed between the
    # write and the state save, or a batch-size change)
    pending = [
        (i, chunk)
        for i, chunk in enumerate(batches)
        if batch_key(chunk) not in done and not landed.intersection(chunk)
    ]
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
            pool.submit(_run_batch, kind, i, chunk, extra_args): i for i, chunk in pending
        }
        for future in as_completed(futures):
            result = future.result()
            if result["ok"]:
                done.add(batch_key(batches[result["batch"]]))
                state[kind] = sorted(done)
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
        f"{kind}: {len(pending) - failures}/{len(pending)} batches ok, "
        f"{failures} failed (re-run to resume)"
    )
    return 1 if failures else 0


def _catalog() -> int:
    argv = _axdata_cli() + [
        "plugin",
        "collector-run",
        "tdx.index_codes_tdx.snapshot",
        "--params",
        json.dumps({"include_tdx_block_index": True}),
    ]
    proc = subprocess.run(argv, cwd=str(REPO_ROOT))
    return proc.returncode


def _verify() -> int:
    import pandas as pd

    problems: list[str] = []
    landed: dict[str, set[str]] = {"daily": set(), "index_daily": set()}
    for table in ("daily", "index_daily"):
        code_col, date_col = "instrument_id", "trade_time"
        table_dir = DATA_ROOT / "core" / f"table={table}" / "parquet"
        files = sorted(table_dir.glob("*.parquet"))
        if not files:
            problems.append(f"{table}: no files")
            continue
        frames = (pd.read_parquet(f, columns=[code_col, date_col, "tdx_code"]) for f in files)
        df = pd.concat(list(frames), ignore_index=True)
        dup = df.duplicated(subset=[code_col, date_col]).sum()
        per = df.groupby(code_col)[date_col].agg(["count", "min", "max"])
        print(f"{table}: files={len(files)} rows={len(df)} codes={per.shape[0]} "
              f"date={df[date_col].min()}..{df[date_col].max()} dup_pk={dup}")
        if dup:
            problems.append(f"{table}: {dup} duplicate PK rows across files")
        landed[table] = set(df["tdx_code"].unique())
    for kind, expected_fn, table in (
        ("stocks", _stock_codes, "daily"),
        ("indices", _index_codes, "index_daily"),
    ):
        expected = expected_fn()
        missing = [c for c in expected if c not in landed[table]]
        print(f"coverage: {kind} {len(expected) - len(missing)}/{len(expected)} "
              f"missing={len(missing)}")
        if missing[:10]:
            print(f"  first missing: {missing[:10]}")
        if missing:
            problems.append(f"{kind} missing {len(missing)} codes")
    for p in problems:
        print(f"PROBLEM: {p}", file=sys.stderr)
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name in ("stocks", "indices"):
        p = sub.add_parser(name)
        p.add_argument("--batch-size", type=int, default=400 if name == "stocks" else 200)
        p.add_argument("--parallel", type=int, default=1 if name == "stocks" else 3)
        p.add_argument("--server-count", type=int, default=8)
        p.add_argument("--pool", type=int, default=4)
        p.add_argument("--limit", type=int, default=None, help="only first N codes (smoke)")
        p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("missing", help="sweep codes absent from landed data")
    p.add_argument("--kind", choices=("stocks", "indices"), default="stocks")
    p.add_argument("--rounds", type=int, default=2)

    sub.add_parser("catalog")
    sub.add_parser("verify")

    args = parser.parse_args(argv)
    if args.cmd == "catalog":
        return _catalog()
    if args.cmd == "verify":
        return _verify()
    if args.cmd == "missing":
        return _missing_rounds(args.kind, args.rounds)
    extra = [] if args.cmd == "indices" else [
        "--source-server-count", str(args.server_count),
        "--connections-per-server", str(args.pool),
    ]
    return _collect(
        args.cmd,
        batch_size=args.batch_size,
        parallel=args.parallel,
        limit=args.limit,
        dry_run=args.dry_run,
        extra_args=extra,
    )


if __name__ == "__main__":
    raise SystemExit(main())
