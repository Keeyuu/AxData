"""Top-board ranking (0x053F) models for the TDX 7709 wire client.

Field names follow gotdx ``proto/get_top_board.go`` (``GetTopBoardReply`` /
``TopBoardItem``) in snake_case; the nine board lists keep gotdx's order.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TopBoardItem:
    market_id: int
    exchange: str
    code: str
    price: float
    value: float

    @property
    def full_code(self) -> str:
        return f"{self.exchange}{self.code}"


@dataclass(frozen=True, slots=True)
class TopBoardPage:
    size: int
    increase: tuple[TopBoardItem, ...]
    decrease: tuple[TopBoardItem, ...]
    amplitude: tuple[TopBoardItem, ...]
    rise_speed: tuple[TopBoardItem, ...]
    fall_speed: tuple[TopBoardItem, ...]
    vol_ratio: tuple[TopBoardItem, ...]
    pos_commission_ratio: tuple[TopBoardItem, ...]
    neg_commission_ratio: tuple[TopBoardItem, ...]
    turnover: tuple[TopBoardItem, ...]
    raw_payload: bytes = b""

    @property
    def boards(self) -> dict[str, tuple[TopBoardItem, ...]]:
        return {
            "increase": self.increase,
            "decrease": self.decrease,
            "amplitude": self.amplitude,
            "rise_speed": self.rise_speed,
            "fall_speed": self.fall_speed,
            "vol_ratio": self.vol_ratio,
            "pos_commission_ratio": self.pos_commission_ratio,
            "neg_commission_ratio": self.neg_commission_ratio,
            "turnover": self.turnover,
        }
