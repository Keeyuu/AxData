"""Stable provider-owned 7709 frame constants."""

PREFIX = 0x0C
PREFIX_RESP = b"\xB1\xCB\x74\x00"
CONTROL_DEFAULT = 0x01
# MAC (通达信 App 通道) requests use the same <BIBHHH layout with a different
# head byte instead of the main-station zip flag 0x0c; responses share the same
# prefix. gotdx ex_request.go: every MAC command sends head=0x01
# (buildExRequest) except capital flow which sends head=0x02
# (buildGenericRequest, proto.go comment "资金流向(head=2)").
MAC_EX_PREFIX = 0x01
MAC_PREFIX = 0x02
