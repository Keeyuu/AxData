"""MAC capital-flow models for the private TDX wire client."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CapitalFlowSnapshot:
    """One stock's server-computed capital-flow snapshot (MAC 0x1218).

    Field names keep the source (TDX) vocabulary verbatim: ``main``/``retail``
    are TDX's own split and ``super``/``large``/``medium``/``small`` are its
    order-size buckets. The classification is a black box on the server side;
    consumers must treat it as one vendor's definition, not a universal one
    (plan axdata-integration/19 §7).
    """

    full_code: str
    market: int
    query_info: str
    ext: str
    today_main_in: float
    today_main_out: float
    today_retail_in: float
    today_retail_out: float
    today_main_net: float
    today_retail_net: float
    five_day_main_buy: float
    five_day_main_sell: float
    five_day_super_net: float
    five_day_large_net: float
    five_day_medium_net: float
    five_day_small_net: float
    five_day_main_net: float
    raw_payload: bytes = b""
