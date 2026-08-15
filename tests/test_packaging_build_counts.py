"""Packaging fixture 验收（04-axdata-optimization.md §2 规则 7）。

每个 package_id 在整个 pytest session 内只构建一次 wheel；跨文件消费同一
artifact（例如 tencent wheel 被 test_axp / test_cli / test_api / test_tencent
_provider_package 共同消费）。全量证据由 conftest 在 session 结束时落盘
``axdata_packaging_build_counts.json``。
"""

from __future__ import annotations

import pytest

from tests.packaging_fixtures import REGISTRY


@pytest.mark.packaging
def test_each_package_wheel_built_at_most_once() -> None:
    stats = REGISTRY.stats()

    assert stats, "没有任何 packaging 测试消费 BuiltWheel fixture"
    repeated = [package_id for package_id, entry in stats.items() if entry["builds"] > 1]
    assert not repeated, f"同一 session 内重复构建 wheel: {repeated}"
    assert stats["tencent"]["builds"] == 1
    # tencent wheel 在 test_axp/test_cli/test_api 中多次请求（每次安装独立 target），
    # 但只构建一次 —— 证明复用生效。
    assert stats["tencent"]["requests"] >= 2, stats["tencent"]
