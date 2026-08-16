"""Stable provider-owned 7709 frame constants."""

PREFIX = 0x0C
PREFIX_RESP = b"\xB1\xCB\x74\x00"
CONTROL_DEFAULT = 0x01
# MAC (通达信 App 通道) requests use the same <BIBHHH layout with head=0x02
# instead of the main-station zip flag 0x0c; responses share the same prefix.
MAC_PREFIX = 0x02
