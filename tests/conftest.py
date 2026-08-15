from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.packaging_fixtures import REGISTRY, BuiltWheel


@pytest.fixture(autouse=True)
def _isolate_api_token_store(tmp_path, monkeypatch):
    monkeypatch.delenv("AXDATA_API_TOKEN", raising=False)
    monkeypatch.setenv("AXDATA_API_TOKEN_FILE", str(tmp_path / "metadata" / "api_tokens.json"))


@pytest.fixture(scope="session")
def built_wheel() -> Callable[[str], BuiltWheel]:
    """按 package_id 返回 session 级 BuiltWheel；每包整个 session 只构建一次。"""

    return REGISTRY.get


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    # 验收证据：每包 build count 落盘到 session basetemp
    factory = getattr(session.config, "_tmp_path_factory", None)
    if factory is not None:
        REGISTRY.write_report(Path(factory.getbasetemp()) / "axdata_packaging_build_counts.json")
