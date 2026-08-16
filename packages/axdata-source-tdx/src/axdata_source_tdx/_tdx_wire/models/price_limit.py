"""Security feature (0x0452) models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SecurityFeature452:
    """Source-named 0x0452 record (gotdx ``SecurityFeature452Item``).

    ``code`` keeps the gotdx source format: unpadded decimal of the wire
    ``code_num`` (e.g. ``"1"``), unlike ``PriceLimitRecord.code`` which is
    zero-padded to six digits.
    """

    market: int
    code: str
    p1: float
    p2: float
