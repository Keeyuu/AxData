"""Plan 19 §6 — gotdx 公开方法 → 我方能力对照表（初稿）生成器。

机械对比只读规格 C:/Code/gotdx 的公开入口（根目录 ``client*.go``/``icfqs.go``/
``block.go`` 中的 ``func (client *Client) Xxx``、``func (client *ICFQSClient) Xxx``
与包级 ``func Xxx``，排除小写私有）与 skynet-axdata 六类能力面：

- a: ``_tdx_wire/_command_dispatch.py`` 的 ``BUILDER_TARGET_ITEMS`` 命令名
- b: ``_tdx_wire/api/*.py`` 的公开方法
- c: ``icfqs_queries.py`` 的公开 def
- d: 解析器（``block_files.py`` 的 ``parse_*`` + ``icfqs_theme_fetch.py`` 公开函数）
- e: ``axdata_core/adapters/tdx_ext`` 的 ``SUPPORTED_INTERFACES``
- alias: gotdx 高层包装（方法体首个 ``client./qc.`` 调用解引用到真实实现）
- NA: 未匹配（进 TBD 清单）

名字启发式：大小写/下划线归一 + 少量同义词（quotes→quote、kline→bars、
transaction→trades、minute/tickchart→intraday、history→historical 等），
先全串相等（canon），再 token 交集；MAC 族方法只对 ``mac_*`` 命令做候选。
产物是初稿，命中/未命中均需人工复核。

用法（仓库根 cwd）::

    .venv/Scripts/python.exe -m skynet.cli  # 无关
    python scripts/gen_plan19_coverage.py                 # stdout
    python scripts/gen_plan19_coverage.py --out tmp/19-coverage-draft.md
    python scripts/gen_plan19_coverage.py --gotdx-root C:/Code/gotdx
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

VENDOR_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GOTDX_ROOT = Path(r"C:/Code/gotdx")

#: 包级/方法文件：gotdx 根目录 client*.go（排除 *_test.go）+ icfqs.go + block.go。
GOTDX_FILE_GLOB = "client*.go"
GOTDX_EXTRA_FILES = ("icfqs.go", "block.go")

#: 方法体里指向真实实现的调用变量（unified 层用 qc/ex 代表子连接）。
ALIAS_CALL_RE = re.compile(r"\b(?:client|qc)\.([A-Z]\w*)\(")

#: 词级同义词（两侧对称应用，canon 化后比较）。
SYNONYM = {
    "quote": "quote",
    "quotes": "quote",
    "quotation": "quote",
    "kline": "bar",
    "klines": "bar",
    "bars": "bar",
    "bar": "bar",
    "transaction": "trade",
    "transactions": "trade",
    "trades": "trade",
    "minute": "intraday",
    "intraday": "intraday",
    "tickchart": "intraday",
    "tickcharts": "intraday",
    "history": "historical",
    "historical": "historical",
    "member": "member",
    "members": "member",
    "board": "board",
    "boards": "board",
    "security": "code",
    "securities": "code",
    "codes": "code",
    "instrument": "instrument",
    "instruments": "instrument",
    "group": "group",
    "groups": "group",
    "topic": "topic",
    "topics": "topic",
    "limit": "limit",
    "limits": "limit",
    "event": "event",
    "events": "event",
    "market": "market",
    "markets": "market",
    "feature": "feature",
    "features": "feature",
    "announcement": "announcement",
    "announcements": "announcement",
    "f10": "company",
    "connect": "handshake",
    "connectex": "handshake",
    "connectmac": "handshake",
    "stock": "stock",
}

#: 泛化 token（仅用于 token 交集命中判定；canon 全串相等不受影响）。
STOP = {
    "get",
    "data",
    "raw",
    "full",
    "detail",
    "server",
    "info",
    "client",
    "icfqs",
    "ex",
    "stock",
    "query",
    "all",
    "count",
    "current",
    "main",
    "new",
    "hot",
    "top",
    "today",
    "recent",
    "list",
}

#: gotdx 高层前缀（剥离生成候选名，长前缀优先）。
NAME_PREFIXES = (
    "GetSecurity",
    "GetIndex",
    "GetMinute",
    "GetHistory",
    "GetMAC",
    "Get",
    "ExGet",
    "Ex",
    "MAC",
    "ICFQS",
    "Goods",
    "Stock",
    "Main",
    "ConnectEx",
    "Connect",
    "Post",
)

#: 映射类型优先级：api 方法语义最贴近，其次协议命令，再 icfqs/解析器/接口。
TYPE_PRIORITY = {"b": 0, "a": 1, "c": 2, "d": 3, "e": 4}


@dataclass
class GotdxMethod:
    """gotdx 侧一个公开入口。kind: method(*Client/*ICFQSClient) | pkg(包级函数)。"""

    name: str
    kind: str
    file: Path
    line: int
    params: str
    body: str

    @property
    def param_types(self) -> str:
        """签名首行参数类型序列（粗记：去掉参数名、[]、*、包前缀）。"""
        types = []
        for part in self.params.split(","):
            part = part.strip()
            if not part:
                continue
            tokens = part.split()
            if not tokens:
                continue
            typ = tokens[-1]
            typ = typ.removeprefix("*").removeprefix("...")
            typ = typ.replace("[]", "").replace("[", "").replace("]", "")
            typ = typ.rsplit(".", 1)[-1]  # proto./time./context. 前缀剥掉
            types.append(typ)
        return ", ".join(types) if types else "-"

    @property
    def display(self) -> str:
        if self.kind == "pkg":
            return self.name
        return f"{self.kind}.{self.name}"


@dataclass
class Capability:
    """我方能力面一项。keys: level1 候选（canon 后比较）；tokens: level2 交集。"""

    label: str
    type: str
    keys: tuple[str, ...]
    tokens: frozenset[str]


#: 连接/保活类方法：alias 解引用时跳过，不属于能力入口。
CONNECTION_NAMES = {"Connect", "ConnectEx", "ConnectMAC", "Disconnect"}


def snake_split(name: str) -> list[str]:
    """Go camelCase / Python snake_case → 小写 token 序列（剥离数字后缀）。"""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    toks = [re.sub(r"\d+$", "", t.lower()) for t in s2.split("_") if t]
    return [t for t in toks if t]


def _canon_tokens(name: str) -> list[str]:
    """snake 化 + 相邻合并查同义词（KLine→k,line→合并 kline→bar）。"""
    toks = snake_split(name)
    out: list[str] = []
    i = 0
    while i < len(toks):
        for n in range(min(3, len(toks) - i), 0, -1):
            joined = "".join(toks[i : i + n])
            if joined in SYNONYM:
                out.append(SYNONYM[joined])
                i += n
                break
        else:
            out.append(SYNONYM.get(toks[i], toks[i]))
            i += 1
    return out


def canon(name: str) -> str:
    """canon：token 序列（含相邻合并同义）拼接（level1 全串比较用）。"""
    return "".join(_canon_tokens(name))


def tokens(name: str) -> frozenset[str]:
    """token 集合（含相邻合并同义；level2 交集用）。"""
    return frozenset(_canon_tokens(name))


# --------------------------------------------------------------------------
# gotdx 侧
# --------------------------------------------------------------------------


def load_gotdx(root: Path) -> list[GotdxMethod]:
    files = sorted(p for p in root.glob(GOTDX_FILE_GLOB) if not p.name.endswith("_test.go"))
    files += [root / f for f in GOTDX_EXTRA_FILES if (root / f).exists()]

    method_re = re.compile(
        r"^func \((client \*Client|client \*ICFQSClient)\) ([A-Z]\w*)"
        r"(\([^)]*\))(.*?)(?=^func |\Z)",
        re.M | re.S,
    )
    pkg_re = re.compile(
        r"^func ([A-Z]\w*)(\([^)]*\))(.*?)(?=^func |\Z)",
        re.M | re.S,
    )
    methods: list[GotdxMethod] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in method_re.finditer(text):
            kind = "ICFQSClient" if "ICFQS" in m.group(1) else "Client"
            methods.append(
                GotdxMethod(
                    name=m.group(2),
                    kind=kind,
                    file=path,
                    line=text[: m.start()].count("\n") + 1,
                    params=m.group(3)[1:-1],
                    body=m.group(4),
                )
            )
        for m in pkg_re.finditer(text):
            methods.append(
                GotdxMethod(
                    name=m.group(1),
                    kind="pkg",
                    file=path,
                    line=text[: m.start()].count("\n") + 1,
                    params=m.group(2)[1:-1],
                    body=m.group(3),
                )
            )
    return methods


def resolve_alias(m: GotdxMethod, by_name: dict[str, GotdxMethod]) -> tuple[list[str], GotdxMethod]:
    """解引用高层包装：沿方法体首个能力调用（跳过连接类）走到原始方法。

    首个非连接调用与自身无共享 token（保活/工具调用，如 StockKLine930 先
    GetServerHeartbeat）时视为非包装，直接按自身名字匹配。返回 (链, 链尾)。
    """
    chain: list[str] = []
    seen: set[str] = set()
    cur = m
    while cur.kind in ("Client", "ICFQSClient") and cur.name not in seen:
        seen.add(cur.name)
        calls = [c for c in ALIAS_CALL_RE.findall(cur.body) if c not in CONNECTION_NAMES]
        if not calls:
            break
        target = calls[0]
        if not (tokens(cur.name) & tokens(target)):
            break
        chain.append(target)
        nxt = by_name.get(target)
        if nxt is None or nxt.kind == "pkg":
            break
        cur = nxt
    return chain, cur


# --------------------------------------------------------------------------
# 我方能力面
# --------------------------------------------------------------------------


def load_commands(dispatch_path: Path) -> list[Capability]:
    text = dispatch_path.read_text(encoding="utf-8")
    start = text.index("BUILDER_TARGET_ITEMS")
    end = text.index("PARSER_TARGET_ITEMS", start)
    block = text[start:end]
    caps = []
    for line in block.splitlines():
        m = re.match(r'\s+\("(?P<name>[a-z0-9_]+)", \("', line)
        if m:
            name = m.group(1)
            caps.append(Capability(label=f"a:{name}", type="a", keys=(name,), tokens=tokens(name)))
    return caps


def load_api_methods(api_dir: Path) -> list[Capability]:
    caps = []
    for path in sorted(p for p in api_dir.glob("*.py") if p.name not in ("__init__.py", "base.py")):
        cls = None
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^class (\w+)", line)
            if m:
                cls = m.group(1)
                continue
            if cls is None:
                continue
            m = re.match(r"^    (?:async )?def (\w+)\(", line)
            if m and not m.group(1).startswith("_"):
                method = m.group(1)
                caps.append(
                    Capability(
                        label=f"b:{cls}.{method}",
                        type="b",
                        keys=(method, cls),
                        tokens=tokens(method) | tokens(cls),
                    )
                )
    return caps


def load_icfqs(path: Path) -> list[Capability]:
    caps = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^def (\w+)\(", line)
        if m and not m.group(1).startswith("_"):
            name = m.group(1)
            caps.append(Capability(label=f"c:{name}", type="c", keys=(name,), tokens=tokens(name)))
    return caps


def load_parsers(block_path: Path, theme_path: Path) -> list[Capability]:
    caps = []
    for line in block_path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^def (parse_\w+)\(", line)
        if m:
            name = m.group(1)
            caps.append(Capability(label=f"d:{name}", type="d", keys=(name,), tokens=tokens(name)))
    for line in theme_path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^def (\w+)\(", line)
        if m and not m.group(1).startswith("_"):
            name = m.group(1)
            caps.append(Capability(label=f"d:{name}", type="d", keys=(name,), tokens=tokens(name)))
    return caps


def load_tdx_ext_interfaces(interface_sets_path: Path) -> list[Capability]:
    """用 ast 解析 SUPPORTED_INTERFACES 集合（字面量 + *DICT 展开）。"""
    tree = ast.parse(interface_sets_path.read_text(encoding="utf-8"))
    name_values: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if isinstance(tgt, ast.Name):
                name_values[tgt.id] = node.value

    def eval_expr(expr: ast.expr) -> object:
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return expr.value
        if isinstance(expr, ast.Set):
            out: set[str] = set()
            for elt in expr.elts:
                if isinstance(elt, ast.Starred):
                    out |= set(eval_expr(elt.value))  # type: ignore[arg-type]
                else:
                    out.add(eval_expr(elt))  # type: ignore[arg-type]
            return out
        if isinstance(expr, ast.Dict):
            return {eval_expr(k): eval_expr(v) for k, v in zip(expr.keys, expr.values, strict=True)}
        if isinstance(expr, ast.Name):
            if expr.id not in name_values:
                raise ValueError(f"cannot resolve {expr.id} in interface_sets.py")
            return eval_expr(name_values[expr.id])
        raise ValueError(f"unsupported ast node {type(expr).__name__}")

    value = eval_expr(name_values["SUPPORTED_INTERFACES"])
    assert isinstance(value, set)
    return [
        Capability(label=f"e:{name}", type="e", keys=(name,), tokens=tokens(name))
        for name in sorted(value)
    ]


# --------------------------------------------------------------------------
# 匹配
# --------------------------------------------------------------------------


def candidate_names(name: str) -> set[str]:
    """剥离高层前缀 + 去 Raw 后缀，生成 level1 候选名。"""
    cands = {name}
    for prefix in NAME_PREFIXES:
        if name.startswith(prefix) and len(name) > len(prefix):
            cands.add(name[len(prefix) :])
    out: set[str] = set()
    for c in cands:
        out.add(c)
        if c.endswith("Raw") and len(c) > 3:
            out.add(c[:-3])
    return out


def match_method(
    raw: GotdxMethod,
    caps: list[Capability],
) -> list[tuple[Capability, int]]:
    """对原始方法返回 (能力, score) 命中列表，按 (score, 类型优先级, 顺序) 已排好。"""
    name = raw.name
    cand_keys = {canon(c) for c in candidate_names(name)}
    method_tokens = tokens(name)

    def cap_key_canon(cap: Capability) -> set[str]:
        return {canon(k) for k in cap.keys}

    hits: list[tuple[Capability, int]] = []
    for cap in caps:
        is_command = cap.type == "a"
        if is_command:
            if "MAC" in name:
                if not cap.keys[0].startswith("mac_"):
                    continue
            elif cap.keys[0].startswith("mac_"):
                continue
        cap_canons = cap_key_canon(cap)
        exact = cand_keys & cap_canons
        contained = {
            k
            for c in cand_keys
            for k in cap_canons
            if len(c) >= 3
            and len(k) >= 3
            and (c.startswith(k) or c.endswith(k) or k.startswith(c) or k.endswith(c))
        }
        if exact:
            hits.append((cap, 1000 + max(len(s) for s in exact)))
            continue
        if contained:
            hits.append((cap, 100 + max(len(s) for s in contained)))
            continue
        inter = method_tokens & cap.tokens - STOP
        if inter:
            hits.append((cap, len(inter)))
    hits.sort(key=lambda h: (-h[1], TYPE_PRIORITY[h[0].type], caps.index(h[0])))
    return hits


# --------------------------------------------------------------------------
# 渲染
# --------------------------------------------------------------------------


def render(
    methods: list[GotdxMethod],
    caps: list[Capability],
) -> str:
    by_name = {m.name: m for m in methods}
    rows: list[tuple[GotdxMethod, str, str, str]] = []
    type_counts: Counter[str] = Counter()
    tbd: list[tuple[GotdxMethod, str]] = []

    for m in methods:
        chain, raw = resolve_alias(m, by_name)
        hits = match_method(raw, caps) if raw is not None else []
        if m.kind == "pkg" and m.name.startswith("New"):
            type_counts["NA"] += 1
            rows.append((m, "NA", "客户端构造器，无数据能力对应", _source(m)))
            tbd.append((m, "客户端构造器，无数据能力对应"))
            continue
        if chain:
            type_counts["alias"] += 1
            map_type = "alias"
            location = " → ".join([m.name, *chain])
            if hits:
                location += f" → {describe_hits(hits)}"
            else:
                location += " → NA"
        elif hits:
            primary = hits[0][0]
            map_type = primary.type
            type_counts[primary.type] += 1
            location = describe_hits(hits)
        else:
            type_counts["NA"] += 1
            map_type = "NA"
            reason = "未匹配到任何能力面"
            if raw is not None and raw.name != m.name:
                reason = f"alias 链尾 {raw.name} 未匹配到能力面"
            location = reason
            tbd.append((m, reason))
        rows.append((m, map_type, location, _source(m)))

    lines = [
        "# Plan 19 §6 — gotdx 公开方法 → 我方能力对照表（初稿）",
        "",
        "- 生成：脚本 `scripts/gen_plan19_coverage.py`，人工复核前仅作初稿",
        "- gotdx 规格：`C:/Code/gotdx`（只读），仅取根目录 `client*.go`/`icfqs.go`/`block.go`",
        "- 映射类型：a=命令 b=api方法 c=icfqs查询 d=解析器 e=tdx_ext接口 "
        "alias=高层包装(指向实现) NA=无对应",
        "",
        "## 统计",
        "",
        "| 项 | 值 |",
        "| --- | --- |",
        f"| gotdx 公开方法总数 | {len(methods)} |",
        f"| ├─ `*Client` 方法 | {sum(1 for m in methods if m.kind == 'Client')} |",
        f"| ├─ `*ICFQSClient` 方法 | {sum(1 for m in methods if m.kind == 'ICFQSClient')} |",
        f"| └─ 包级公开函数 | {sum(1 for m in methods if m.kind == 'pkg')} |",
        "| 映射类型计数 | "
        + " ".join(f"{t}={type_counts.get(t, 0)}" for t in ("a", "b", "c", "d", "e", "alias", "NA"))
        + " |",
        f"| TBD（NA 未匹配） | {len(tbd)} |",
        "",
        "## 对照表",
        "",
        "| # | gotdx 方法 | 签名(参数类型) | 映射类型 | 我方落点 | 来源 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for i, (m, map_type, location, source) in enumerate(rows, 1):
        lines.append(
            f"| {i} | {m.display} | {m.param_types} | {map_type} | {location} | {source} |"
        )

    lines += [
        "",
        "## TBD 清单（未匹配，截前 30）",
        "",
        "| # | gotdx 方法 | 理由 |",
        "| --- | --- | --- |",
    ]
    for i, (m, reason) in enumerate(tbd[:30], 1):
        lines.append(f"| {i} | {m.display} | {reason} |")
    if len(tbd) > 30:
        lines.append(f"| ... | （其余 {len(tbd) - 30} 条略） | |")
    return "\n".join(lines) + "\n"


def describe_hits(hits: list[tuple[Capability, int]]) -> str:
    """主命中 + 至多 3 个次命中。"""
    parts = [hits[0][0].label]
    for cap, _ in hits[1:4]:
        parts.append(cap.label)
    return "; ".join(parts)


def _source(m: GotdxMethod) -> str:
    return f"{m.file.name}:{m.line}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", metavar="PATH", help="markdown 输出文件（默认 stdout）")
    parser.add_argument(
        "--gotdx-root",
        default=str(DEFAULT_GOTDX_ROOT),
        help=f"gotdx 只读规格根（默认 {DEFAULT_GOTDX_ROOT}）",
    )
    args = parser.parse_args(argv)

    tdx_pkg = VENDOR_ROOT / "packages" / "axdata-source-tdx" / "src" / "axdata_source_tdx"
    core_pkg = VENDOR_ROOT / "libs" / "axdata_core" / "axdata_core"

    methods = load_gotdx(Path(args.gotdx_root))
    if not methods:
        print(f"error: gotdx root 下未找到公开入口: {args.gotdx_root}", file=sys.stderr)
        return 2

    commands = load_commands(tdx_pkg / "_tdx_wire" / "_command_dispatch.py")
    caps: list[Capability] = []
    caps += commands
    caps += load_api_methods(tdx_pkg / "_tdx_wire" / "api")
    caps += load_icfqs(tdx_pkg / "icfqs_queries.py")
    caps += load_parsers(tdx_pkg / "block_files.py", tdx_pkg / "icfqs_theme_fetch.py")
    caps += load_tdx_ext_interfaces(core_pkg / "adapters" / "tdx_ext" / "interface_sets.py")

    text = render(methods, caps)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"written: {out}")
    else:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
