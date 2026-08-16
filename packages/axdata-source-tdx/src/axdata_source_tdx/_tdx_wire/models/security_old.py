"""Old security code-table models (0x0450) for the TDX 7709 wire client.

Field names follow gotdx ``proto/get_security_list_old.go`` (``Security`` item
fields) in snake_case; ``Turnover``-style derived fields are intentionally not
invented here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SecurityCodeOld:
    code: str
    vol: int
    name: str
    unknown1: float
    legacy_unknown1: int
    decimal_point: int
    pre_close: float
    unknown2: int
    unknown3: int
    record_hex: str = ""

    @property
    def vol_unit(self) -> int:
        return self.vol


@dataclass(frozen=True, slots=True)
class SecurityListOldPage:
    exchange: str
    market_id: int
    start: int
    codes: tuple[SecurityCodeOld, ...]
    raw_payload: bytes = b""

    @property
    def count(self) -> int:
        return len(self.codes)
