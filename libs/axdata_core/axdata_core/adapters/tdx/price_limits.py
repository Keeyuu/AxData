"""Compatibility forwarder for TDX price-limit and limit-up status helpers（弃用）。

实现已迁移至 ``axdata_core.market_rules``：

- 核心拥有的纯函数（``st_type_from_name`` / ``ipo_phase_from_name`` /
  ``round_price`` / ``price_close`` / ``price_at_or_above``）直接指向
  ``axdata_core.market_rules``（core 内部直连，不再绕 tdx 包）；
- 仅剩的兼容层辅助（``price_limit_name_flag`` / ``price_limit_ratio_from_rule`` /
  ``price_limit_rule`` / ``rule_price_limits`` / ``special_limit_ratio`` /
  ``positive_number`` / ``limit_ladder_status``）惰性转发到
  ``axdata_source_tdx.price_limits``。

Deprecation: 本转发器计划在下一个 minor 版本移除，新代码请改用
``axdata_core.market_rules``。
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import Any as _Any

_CORE_EXPORTS = frozenset(
    {
        "st_type_from_name",
        "ipo_phase_from_name",
        "round_price",
        "price_close",
        "price_at_or_above",
    }
)

_PROVIDER_EXPORTS = frozenset(
    {
        "price_limit_ratio_from_rule",
        "price_limit_rule",
        "price_limit_name_flag",
        "rule_price_limits",
        "special_limit_ratio",
        "positive_number",
        "limit_ladder_status",
    }
)
__all__ = sorted(_CORE_EXPORTS | _PROVIDER_EXPORTS)

_CORE_MODULE: ModuleType | None = None
_IMPLEMENTATION: ModuleType | None = None


def _market_rules_module() -> ModuleType:
    global _CORE_MODULE
    if _CORE_MODULE is None:
        import axdata_core.market_rules as _CORE_MODULE
    return _CORE_MODULE


def _provider_package_price_limits() -> ModuleType | None:
    try:
        return import_module("axdata_source_tdx.price_limits")
    except ModuleNotFoundError as exc:
        if exc.name in {"axdata_source_tdx", "axdata_source_tdx.price_limits"}:
            return None
        raise


def _provider_module() -> ModuleType:
    global _IMPLEMENTATION
    if _IMPLEMENTATION is None:
        implementation = _provider_package_price_limits()
        _IMPLEMENTATION = (
            implementation if implementation is not None else _fallback_price_limits()
        )
    return _IMPLEMENTATION


def _fallback_price_limits() -> ModuleType:
    from axdata_core.tdx_plugin_required import raise_tdx_plugin_required

    raise_tdx_plugin_required()


def __getattr__(name: str) -> _Any:
    if name in _CORE_EXPORTS:
        value = getattr(_market_rules_module(), name)
    elif name in _PROVIDER_EXPORTS:
        value = getattr(_provider_module(), name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value
