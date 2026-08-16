"""Server-info (0x0015) model for the TDX 7709 wire client.

Field names follow gotdx ``proto/server.go`` (``InfoReply``) in snake_case;
the three ``unknown*`` triples keep gotdx's string/hex renderings.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ServerInfo:
    delay: int
    info: str
    content: str
    server_sign: str
    time_now: str
    unknown1: tuple[str, str, str]
    unknown2: tuple[str, str, str]
    unknown3: tuple[int, int, int]
    region: int
    maybe_switch: int
    raw_payload: bytes = b""
