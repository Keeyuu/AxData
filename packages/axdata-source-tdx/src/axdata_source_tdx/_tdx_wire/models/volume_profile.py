"""Volume-profile (0x051A) models for the TDX 7709 wire client.

Field names follow gotdx ``proto/get_volume_profile.go``
(``GetVolumeProfileReply`` / ``VolumeProfileItem`` / ``Level``) in snake_case.
``turnover`` is excluded: gotdx backfills it from higher-level interfaces, so
it is not part of the wire payload.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VolumeProfileLevel:
    price: float
    vol: int


@dataclass(frozen=True, slots=True)
class VolumeProfileItem:
    price: float
    vol: int
    buy: int
    sell: int


@dataclass(frozen=True, slots=True)
class VolumeProfileSnapshot:
    count: int
    market_id: int
    exchange: str
    code: str
    active: int
    close: float
    open: float
    high: float
    low: float
    pre_close: float
    server_time: str
    neg_price: float
    vol: int
    cur_vol: int
    amount: float
    in_vol: int
    out_vol: int
    s_amount: int
    open_amount: int
    bid_levels: tuple[VolumeProfileLevel, ...]
    ask_levels: tuple[VolumeProfileLevel, ...]
    unknown: int
    vol_profiles: tuple[VolumeProfileItem, ...]
    raw_payload: bytes = b""

    @property
    def full_code(self) -> str:
        return f"{self.exchange}{self.code}"
