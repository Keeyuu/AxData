"""Chart-sampling (0x0FD1) models for the TDX 7709 wire client.

Field names follow gotdx ``proto/get_chart_sampling.go``
(``GetChartSamplingReply``) in snake_case.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChartSamplingSeries:
    market_id: int
    exchange: str
    code: str
    count: int
    pre_close: float
    prices: tuple[float, ...]
    raw_payload: bytes = b""

    @property
    def full_code(self) -> str:
        return f"{self.exchange}{self.code}"
