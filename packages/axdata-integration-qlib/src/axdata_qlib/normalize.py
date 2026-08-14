"""Reversible mapping between AxData instrument ids and Qlib symbols (CN).

Qlib 0.9.7 stores one feature directory per instrument (``features/<inst>/``)
and reads the instrument list from ``instruments/all.txt``; it applies no
normalization itself, so the export format is entirely our contract.

The CN convention (matching Qlib's dump_bin layout) is::

    000001.SZ <-> SZ000001
    600000.SH <-> SH600000

The mapping is strict and reversible: both directions round-trip exactly,
and unknown formats are rejected instead of being guessed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from .errors import QlibExportError

_SUPPORTED_REGIONS = ("cn",)
#: Two-letter exchange suffix as it appears in the AxData source id.
_EXCHANGE_SUFFIXES = ("SZ", "SH", "BJ")
_CODE_PATTERN = re.compile(r"^([0-9]{6})\.(SZ|SH|BJ)$")
_SYMBOL_PATTERN = re.compile(r"^(SZ|SH|BJ)([0-9]{6})$")


def to_qlib_symbol(source_id: str, *, region: str = "cn") -> str:
    """Normalize an AxData instrument id to a Qlib symbol.

    Idempotent for ids already in Qlib form (``SZ000001``). ``region`` is
    reserved for future markets; only ``"cn"`` is supported today.
    """
    _check_region(region)
    text = str(source_id).strip().upper()
    if _SYMBOL_PATTERN.match(text):
        return text
    match = _CODE_PATTERN.match(text)
    if match is None:
        raise QlibExportError(
            f"Cannot normalize instrument id {source_id!r}: expected "
            f"'NNNNNN.SZ' / 'NNNNNN.SH' / 'NNNNNN.BJ' or Qlib form "
            f"'SZNNNNNN' / 'SHNNNNNN' / 'BJNNNNNN'."
        )
    return f"{match.group(2)}{match.group(1)}"


def from_qlib_symbol(qlib_symbol: str, *, region: str = "cn") -> str:
    """Restore the AxData instrument id from a Qlib symbol."""
    _check_region(region)
    text = str(qlib_symbol).strip().upper()
    match = _SYMBOL_PATTERN.match(text)
    if match is None:
        raise QlibExportError(
            f"Cannot restore instrument id from Qlib symbol {qlib_symbol!r}: "
            f"expected 'SZNNNNNN' / 'SHNNNNNN' / 'BJNNNNNN'."
        )
    return f"{match.group(2)}.{match.group(1)}"


def build_instrument_map(source_ids: Iterable[str]) -> Mapping[str, Mapping[str, str]]:
    """Build the serializable bidirectional instrument map.

    Returns ``{"source_to_qlib": {...}, "qlib_to_source": {...}}`` with
    keys sorted for a stable hash across identical inputs.
    """
    source_ids = sorted(
        {str(identifier).strip() for identifier in source_ids if str(identifier).strip()}
    )
    to_qlib = {identifier: to_qlib_symbol(identifier) for identifier in source_ids}
    qlib_to_source = {symbol: identifier for identifier, symbol in to_qlib.items()}
    if len(qlib_to_source) != len(to_qlib):
        raise QlibExportError("Instrument mapping is not injective; duplicate Qlib symbols found.")
    return {
        "source_to_qlib": to_qlib,
        "qlib_to_source": qlib_to_source,
    }


def _check_region(region: str) -> None:
    if region not in _SUPPORTED_REGIONS:
        raise NotImplementedError(
            f"Qlib symbol normalization is only defined for regions "
            f"{', '.join(_SUPPORTED_REGIONS)}, got {region!r}."
        )
