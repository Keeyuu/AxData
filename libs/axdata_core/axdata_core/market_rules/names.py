"""证券简称状态解析：ST 状态与上市阶段。

本模块是**唯一的**证券简称状态解析入口，采集侧消费点（涨跌停价行、连板天梯、
候选过滤）统一从这里取 ``st_type`` / ``ipo_phase``，保证同一
(code, name, date) 在各路径下的判定一致。
"""

from __future__ import annotations

from typing import Any, Literal


def st_type_from_name(name: Any) -> Literal["*ST", "ST"] | None:
    """解析 ST 状态：*ST/S*ST → "*ST"，ST/SST → "ST"，否则 None。

    大小写不敏感并 strip；吸收 S*ST/SST（股改前遗留简称）。N/C 与 ST 前缀互斥，
    因此本函数与 ``ipo_phase_from_name`` 之间不存在判定顺序问题。
    """
    text = str(name or "").strip().upper()
    if not text:
        return None
    if text.startswith("*ST") or text.startswith("S*ST"):
        return "*ST"
    if text.startswith("ST") or text.startswith("SST"):
        return "ST"
    return None


def ipo_phase_from_name(name: Any) -> Literal["N", "C"] | None:
    """解析上市阶段：N=上市首日，C=上市后前 5 日，否则 None。

    前缀匹配：以 N/C 开头即命中；大小写不敏感并 strip。
    """
    text = str(name or "").strip().upper()
    if not text:
        return None
    if text.startswith("N"):
        return "N"
    if text.startswith("C"):
        return "C"
    return None
