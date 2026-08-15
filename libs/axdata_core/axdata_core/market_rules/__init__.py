"""axdata_core.market_rules — 涨跌停规则、证券简称状态与交易日上下文的公共纯函数设施。

本包只含纯函数与冻结数据结构，不依赖 clock、IO 或全局状态，便于在采集侧、适配层与
测试中直接消费。职责划分：

- ``names``：证券简称状态解析（ST 状态与上市阶段）；
- ``rules``：涨跌停规则核心（``Board`` / ``LimitRule`` / ``RULE_TABLE`` / ``limit_rule``），
  与证券名称语义解耦，只认 board / date / st_type / ipo_phase；
- ``compare``：价格舍入与比较（半个最小报价单位 + 浮点容差）；
- ``sessions``：交易日上下文单源解析（``SessionContext`` / ``session_context``）。

两条红线：

(a) **skynet_axdata.mapping 禁止 import 本包**（Skynet 纯度约定，见 Skynet 计划文档
    ``docs/plan/axdata-integration/07`` §4）。Skynet 只能通过已持久化的数据列消费本包
    产出的规则结果（如 ``limit_ratio_pct`` / ``limit_rule`` / ``limit_up_price`` 等），
    不得在数据映射/清洗阶段直接调用本包接口。
(b) **升级为独立 distribution 的触发条件 = 出现 AxData 生态外的消费方**。本包当前随
    ``axdata_core`` 分发；一旦出现 Skynet/AxData 生态之外的第三方消费方，须先将本包
    拆分为独立 distribution 并完成版本管理，再放开外部引用。
"""

from __future__ import annotations

from .compare import HALF_TICK, price_at_or_above, price_close, round_price
from .names import ipo_phase_from_name, st_type_from_name
from .rules import (
    RULE_TABLE,
    Board,
    LimitRule,
    MarketRuleError,
    board_from_tdx_code,
    limit_rule,
    price_limits,
)
from .sessions import SessionContext, session_context

__all__ = [
    "Board",
    "HALF_TICK",
    "LimitRule",
    "MarketRuleError",
    "RULE_TABLE",
    "SessionContext",
    "board_from_tdx_code",
    "ipo_phase_from_name",
    "limit_rule",
    "price_at_or_above",
    "price_close",
    "price_limits",
    "round_price",
    "session_context",
    "st_type_from_name",
]
