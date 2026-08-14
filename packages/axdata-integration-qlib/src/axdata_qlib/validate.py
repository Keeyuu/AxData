"""Layout validation and content hashing for exported qlib directories.

The content hash is a stable SHA-256 over every file of the export except
``qlib_export.json`` itself (which embeds the hash and a generation
timestamp). Identical inputs therefore produce identical hashes, and any
source change changes the hash.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .errors import QlibExportError
from .writer import QLIB_EXPORT_FILENAME

_BIN_HEADER_FLOATS = 1  # first float32 is the calendar start index


def compute_content_hash(provider_dir: str | Path) -> str:
    """Stable SHA-256 of the export's content files (hex)."""
    root = Path(provider_dir)
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == QLIB_EXPORT_FILENAME:
            continue
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\x00")
        with path.open("rb") as fp:
            while True:
                block = fp.read(1 << 20)
                if not block:
                    break
                digest.update(block)
        digest.update(b"\x00")
    return digest.hexdigest()


def verify_layout(provider_dir: str | Path) -> list[str]:
    """Verify the qlib provider layout; return the exported instrument symbols.

    Raises:
        QlibExportError: on any structural defect (missing calendar,
            malformed instrument rows, missing or mis-sized feature files,
            feature dirs without an instrument row).
    """
    root = Path(provider_dir)

    calendar_path = root / "calendars" / "day.txt"
    if not calendar_path.is_file():
        raise QlibExportError(f"Missing {calendar_path.relative_to(root)}.")
    calendar = [
        line.strip()
        for line in calendar_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not calendar:
        raise QlibExportError("Export calendar is empty.")

    instruments_path = root / "instruments" / "all.txt"
    if not instruments_path.is_file():
        raise QlibExportError(f"Missing {instruments_path.relative_to(root)}.")
    symbols: list[str] = []
    for lineno, line in enumerate(
        instruments_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            raise QlibExportError(
                f"Malformed instrument row at {instruments_path.relative_to(root)}:{lineno} "
                f"(expected '<symbol>\\t<start>\\t<end>'): {line!r}."
            )
        symbols.append(parts[0])

    fields = _exported_fields(root)
    for symbol in symbols:
        inst_dir = root / "features" / symbol.lower()
        if not inst_dir.is_dir():
            raise QlibExportError(
                f"Instrument {symbol!r} has an all.txt row but no "
                f"features/{symbol.lower()}/ directory."
            )
        for field in fields:
            bin_path = inst_dir / f"{field}.day.bin"
            if not bin_path.is_file():
                raise QlibExportError(f"Missing feature file {bin_path.relative_to(root)}.")
            size = bin_path.stat().st_size
            if size < 4 * (_BIN_HEADER_FLOATS + 1) or size % 4 != 0:
                raise QlibExportError(
                    f"Feature file {bin_path.relative_to(root)} has invalid "
                    f"size {size} (expected 4-byte float32 array with header)."
                )
    for inst_dir in sorted((root / "features").glob("*")):
        if inst_dir.is_dir() and inst_dir.name not in {symbol.lower() for symbol in symbols}:
            raise QlibExportError(
                f"Feature directory {inst_dir.name!r} has no row in instruments/all.txt."
            )
    return symbols


def _exported_fields(root: Path) -> list[str]:
    features_dir = root / "features"
    if not features_dir.is_dir() or not any(features_dir.iterdir()):
        raise QlibExportError("Export has no features/ directory.")
    inst_dir = next(iter(sorted(d for d in features_dir.iterdir() if d.is_dir())))
    fields = sorted(path.name[: -len(".day.bin")] for path in inst_dir.glob("*.day.bin"))
    if not fields:
        raise QlibExportError(f"No feature files under {inst_dir.relative_to(root)}.")
    return fields
