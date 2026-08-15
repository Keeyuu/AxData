"""Session 级 wheel 构建复用（docs/plan/test-speed/04-axdata-optimization.md §2）。

每个 package_id 在整个 pytest session 内只构建一次 wheel：
- artifact 发布后只读，记录 SHA-256；
- 构建失败不发布（下次请求重试，不会留下半成品被误用）；
- 统计每包 build count / request count，验收断言每包最多构建一次；
- 负例（缺文件时 build 失败）必须复制最小源码树独立构建，不污染成功 artifact。

构建使用 ``--no-build-isolation`` + ``--no-deps``：packaging 分区默认断网可运行，
不触发在线依赖解析。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

REPO_ROOT = Path(__file__).resolve().parents[1]

# package_id -> 仓库内源码根目录（同一 session 内只按此根目录构建一次）
_PACKAGE_SOURCE_ROOTS: dict[str, Path] = {
    "tdx": REPO_ROOT / "packages" / "axdata-source-tdx",
    "tdx_ext": REPO_ROOT / "packages" / "axdata-source-tdx-ext",
    "tencent": REPO_ROOT / "packages" / "axdata-source-tencent",
    "cninfo": REPO_ROOT / "packages" / "axdata-source-cninfo",
}


@dataclass(frozen=True)
class BuiltWheel:
    """一次 session 级构建发布的只读 wheel artifact。"""

    package_id: str
    source_root: Path
    wheel_path: Path
    sha256: str
    metadata: dict[str, object]


class PackagingWheelRegistry:
    """Session 级 wheel 构建复用与统计。"""

    def __init__(self) -> None:
        self._wheel_dir: Path | None = None
        self._artifacts: dict[str, BuiltWheel] = {}
        self._build_counts: dict[str, int] = {}
        self._request_counts: dict[str, int] = {}

    @property
    def wheel_dir(self) -> Path:
        if self._wheel_dir is None:
            self._wheel_dir = Path(tempfile.mkdtemp(prefix="axdata-test-wheels-"))
        return self._wheel_dir

    def get(self, package_id: str) -> BuiltWheel:
        """返回该 package_id 的 session artifact；首次请求时构建并发布。"""
        self._request_counts[package_id] = self._request_counts.get(package_id, 0) + 1
        artifact = self._artifacts.get(package_id)
        if artifact is not None:
            return artifact
        source_root = _PACKAGE_SOURCE_ROOTS[package_id]
        self._build_counts[package_id] = self._build_counts.get(package_id, 0) + 1
        # 每包独立子目录；构建前清空可能残留的半成品，保证目录内 wheel 唯一
        build_dir = self.wheel_dir / package_id
        build_dir.mkdir(parents=True, exist_ok=True)
        for stale in build_dir.glob("*.whl"):
            stale.unlink()
        wheel_path = _build_wheel(source_root, build_dir)
        artifact = BuiltWheel(
            package_id=package_id,
            source_root=source_root,
            wheel_path=wheel_path,
            sha256=hashlib.sha256(wheel_path.read_bytes()).hexdigest(),
            metadata=_wheel_metadata(wheel_path),
        )
        self._artifacts[package_id] = artifact
        return artifact

    def stats(self) -> dict[str, dict[str, int]]:
        return {
            package_id: {
                "builds": self._build_counts.get(package_id, 0),
                "requests": self._request_counts.get(package_id, 0),
            }
            for package_id in sorted(set(self._build_counts) | set(self._request_counts))
        }

    def write_report(self, path: Path) -> None:
        report = json.dumps(self.stats(), ensure_ascii=False, indent=2) + "\n"
        path.write_text(report, encoding="utf-8")


REGISTRY = PackagingWheelRegistry()


def _build_wheel(source_root: Path, wheel_dir: Path) -> Path:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "-w",
            str(wheel_dir),
            str(source_root),
        ],
        check=True,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    wheels = sorted(wheel_dir.glob("*.whl"))
    if not wheels:
        raise AssertionError(f"pip wheel produced no artifact for {source_root}")
    return wheels[0]


def _wheel_metadata(wheel_path: Path) -> dict[str, object]:
    with ZipFile(wheel_path) as wheel:
        names = sorted(wheel.namelist())
        entry_points = ""
        dist_metadata = ""
        manifest: object = None
        dist_info: str | None = None
        for name in names:
            if name.endswith(".dist-info/entry_points.txt"):
                entry_points = wheel.read(name).decode("utf-8")
            elif name.endswith(".dist-info/METADATA"):
                dist_metadata = wheel.read(name).decode("utf-8")
            elif name.endswith("axdata-provider.json"):
                manifest = json.loads(wheel.read(name))
            elif ".dist-info" in name and dist_info is None:
                dist_info = name.split("/")[0]
    return {
        "names": names,
        "entry_points": entry_points,
        "dist_metadata": dist_metadata,
        "manifest": manifest,
        "dist_info": dist_info,
    }
