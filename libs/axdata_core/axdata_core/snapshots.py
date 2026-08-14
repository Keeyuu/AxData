"""Immutable research snapshot core (AXI-040).

Bundles multiple mutable AxData datasets into one frozen, content-addressed,
relocatable bundle at ``<data_root>/snapshots/<namespace>/<snapshot_id>/``.
The core only writes safely, hashes, publishes atomically, lists and reads;
table semantics, field generation and label logic belong to the plugin layer
(plan docs/plan/axdata-integration/05-snapshot-contract.md §1, §5).

Publish flow
------------
Every write goes to a temporary directory ``tmp-*`` inside the namespace
directory. Tables, per-file hashes, ``quality.json``, the content hash and
``manifest.json`` are all produced there first; the snapshot id is only
decided after the content hash is known, and only then is the directory
atomically renamed to its final content-addressed name (plan §2, §4).

``_SUCCESS`` is written *inside* the temporary directory before the rename,
not after it. The atomic rename then makes the complete snapshot — including
``_SUCCESS`` — visible in a single step, so the final name can never exist in
an incomplete state. A crash before the rename leaves only a ``tmp-*``
directory, which is never returned (no ``_SUCCESS`` and no ``snp_*`` prefix)
and never blocks a retry; a crash can never leave a ``snp_*`` directory
without ``_SUCCESS``. This is the implementation choice behind the plan's
"no ``_SUCCESS`` means never returned" visibility rule.

Hashing (plan §4)
-----------------
- every Parquet file is hashed with a streaming SHA-256 (never loaded into
  memory);
- ``schema_hash`` is the SHA-256 of the canonical JSON of the Arrow schema
  read from the file footer (schema metadata stripped), so it reflects exactly
  what a reader sees;
- ``content_hash`` covers only ``manifest_version``, ``tables`` (relative uris
  plus per-file sha256/size/row count/schema hash), ``source_datasets``,
  ``calendar_version`` and ``limitations``. ``created_at``, the absolute data
  root, machine names, temporary paths and the namespace never enter the hash,
  and asset uris are relative to the snapshot root, so identical content
  hashes identically on any machine;
- ``quality.json`` and ``extra_artifacts`` are deliberately excluded from the
  hash: quality is a caller-owned record and auxiliary artifacts are not part
  of the bundle identity (plan §7 only requires warnings to be surfaced in
  ``limitations``). ``extra_artifacts`` are still copied into the snapshot
  root and move with it.

``dataset_version`` is derived from ``calendar_version``: the create API has
no separate dataset-version argument (plan §5), and the dataset version of a
frozen research bundle is the calendar it was frozen at. The plugin layer can
extend the signature if a distinct versioning scheme is needed.

Safety model
------------
``namespace``, ``snapshot_id`` and ``logical_name`` are single path
components: empty values, URI schemes, UNC prefixes, ``.``/``..`` and path
separators are rejected. Before publishing, and on every explicit lookup, the
resolved target path must stay inside the resolved ``snapshots`` root, so
symlinked / junctioned directories cannot smuggle writes or reads outside the
root. Listing skips such entries instead of failing; explicit lookups fail.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd
    import pyarrow as pa

_MANIFEST_VERSION = "skynet.dataset/v2"
_SNAPSHOT_ID_PREFIX = "snp_"
_SUCCESS_FILE_NAME = "_SUCCESS"
_MANIFEST_FILE_NAME = "manifest.json"
_QUALITY_FILE_NAME = "quality.json"
_HASH_CHUNK_SIZE = 1 << 20
_URI_SCHEME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")
_RESERVED_ROOT_NAMES = frozenset(
    {"tables", _MANIFEST_FILE_NAME, _QUALITY_FILE_NAME, _SUCCESS_FILE_NAME}
)


class SnapshotError(ValueError):
    """Raised when a snapshot cannot be created, listed or resolved."""


class SnapshotNotFoundError(KeyError, SnapshotError):
    """Raised when a snapshot_id has no completed snapshot anywhere."""


class SnapshotConflictError(SnapshotError):
    """Raised when the target snapshot id already exists with different content."""


@dataclass(frozen=True, slots=True)
class SnapshotTableInput:
    """One logical table to freeze into a snapshot.

    Args:
        logical_name: Table name; becomes ``tables/<logical_name>/`` inside the
            snapshot. Must be a plain path component (no separators, ``..``,
            URI scheme).
        frame: Data to write. A pandas DataFrame or pyarrow Table is written
            as a single ``part-0.parquet`` (or hive-partitioned directories
            when ``partition_by`` is set); a pyarrow Dataset is streamed into
            ``part-*.parquet`` files without loading it into memory.
        partition_by: Column names for hive-style partition directories. When
            non-empty the table is written as
            ``tables/<logical_name>/<column>=<value>/part-*.parquet``.
    """

    logical_name: str
    frame: pd.DataFrame | pa.Table | pa.dataset.Dataset
    partition_by: tuple[str, ...] = ()


def create_snapshot(
    *,
    namespace: str,
    dataset_id: str,
    tables: Sequence[SnapshotTableInput],
    source_datasets: Sequence[Mapping[str, Any]],
    calendar_version: str,
    data_root: str | Path,
    quality: Mapping[str, Any],
    limitations: Sequence[str] = (),
    extra_artifacts: Sequence[Path] = (),
    qlib_provider_uri: str | None = None,
) -> dict[str, Any]:
    """Freeze a bundle of tables into one immutable, content-addressed snapshot.

    Writes into a ``tmp-*`` directory inside ``<data_root>/snapshots/
    <namespace>/``, computes hashes and the manifest there, then atomically
    renames the directory to its final name ``snp_<content_hash[:24]>`` (with
    ``_SUCCESS`` already inside, see the module docstring).

    ``qlib_provider_uri`` is the path of an exported Qlib provider directory
    **relative to the snapshot root** (plan 05 §2 / 06 §5), recorded verbatim
    in the manifest so a consumer can default to it; ``None`` records "no
    bundled qlib provider". It is deliberately excluded from the content hash
    (plan 05 §4). The caller owns the semantic — this core only records the
    value and refuses values that could escape the snapshot root.

    Idempotency: when a completed snapshot with the same id already exists and
    its manifest content hash matches, the existing snapshot is returned
    without rewriting anything. An existing id with different content raises
    :class:`SnapshotConflictError`; an existing incomplete or corrupted
    directory raises :class:`SnapshotError`.

    Returns a dict with ``namespace``, absolute ``path`` and the full manifest
    (the same shape as :func:`get_snapshot`).
    """
    root = _resolve_data_root(data_root)
    namespace = _validate_component(namespace, "namespace")
    dataset_id = _require_text(dataset_id, "dataset_id")
    calendar_version = _require_text(calendar_version, "calendar_version")
    _require_table_inputs(tables)
    source_entries = _normalize_source_datasets(source_datasets)
    limitations = [str(item) for item in limitations]
    quality = _require_mapping(quality, "quality")
    artifacts = _normalize_extra_artifacts(extra_artifacts)
    qlib_uri = _normalize_qlib_provider_uri(qlib_provider_uri)

    snapshots_root = root / "snapshots"
    namespace_dir = snapshots_root / namespace
    _check_inside_root(namespace_dir, snapshots_root)
    namespace_dir.mkdir(parents=True, exist_ok=True)

    tmp_dir = namespace_dir / f"tmp-{uuid.uuid4().hex[:12]}"
    tmp_dir.mkdir()
    published = False
    try:
        table_refs = _write_tables(tmp_dir, tables)
        _write_json(tmp_dir / _QUALITY_FILE_NAME, quality, sort_keys=False)
        for name, source in artifacts:
            _copy_artifact(source, tmp_dir / name)
        content_hash = _compute_content_hash(
            table_refs, source_entries, calendar_version, limitations
        )
        snapshot_id = _SNAPSHOT_ID_PREFIX + content_hash[:24]
        manifest = {
            "manifest_version": _MANIFEST_VERSION,
            "snapshot_id": snapshot_id,
            "dataset_id": dataset_id,
            "dataset_version": calendar_version,
            "content_hash": content_hash,
            "calendar_version": calendar_version,
            "created_at": _utc_now(),
            "tables": table_refs,
            "source_datasets": source_entries,
            "source_runs": [],
            "qlib_provider_uri": qlib_uri,
            "quality_uri": _QUALITY_FILE_NAME,
            "limitations": limitations,
        }
        _write_json(tmp_dir / _MANIFEST_FILE_NAME, manifest, sort_keys=True)
        (tmp_dir / _SUCCESS_FILE_NAME).write_text("", encoding="utf-8")

        final_dir = namespace_dir / snapshot_id
        _check_inside_root(final_dir, snapshots_root)
        if final_dir.exists():
            existing = _read_completed_manifest(final_dir)
            if existing.get("content_hash") == content_hash:
                return _snapshot_info(final_dir, namespace, existing)
            raise SnapshotConflictError(
                f"Snapshot {snapshot_id!r} already exists with different "
                "content; refusing to overwrite."
            )
        try:
            tmp_dir.rename(final_dir)
        except OSError as exc:
            raise SnapshotError(f"Failed to publish snapshot {snapshot_id!r}: {exc}") from exc
        published = True
        return _snapshot_info(final_dir, namespace)
    finally:
        if not published and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)


def list_snapshots(
    *,
    namespace: str | None = None,
    data_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """List completed snapshots, newest first.

    Only directories that look like snapshots (``snp_*``) and carry a
    ``_SUCCESS`` file with a parseable manifest are returned. Incomplete,
    corrupted or symlinked-out entries are skipped. ``namespace`` restricts
    the listing to one namespace.
    """
    root = _resolve_data_root(data_root)
    snapshots_root = root / "snapshots"
    if not snapshots_root.is_dir():
        return []
    if namespace is not None:
        namespace = _validate_component(namespace, "namespace")
        namespace_dirs = [snapshots_root / namespace]
    else:
        namespace_dirs = sorted(path for path in snapshots_root.iterdir() if path.is_dir())
    infos: list[dict[str, Any]] = []
    for namespace_dir in namespace_dirs:
        if not namespace_dir.is_dir():
            continue
        namespace_name = namespace_dir.name
        for snapshot_dir in sorted(namespace_dir.iterdir()):
            if not snapshot_dir.name.startswith(_SNAPSHOT_ID_PREFIX):
                continue
            if not snapshot_dir.is_dir():
                continue
            if not (snapshot_dir / _SUCCESS_FILE_NAME).is_file():
                continue
            if not _inside_root(snapshot_dir, snapshots_root):
                continue
            try:
                manifest = _read_completed_manifest(snapshot_dir)
            except SnapshotError:
                continue
            infos.append(_snapshot_info(snapshot_dir, namespace_name, manifest))
    return sorted(
        infos,
        key=lambda info: (
            info["namespace"],
            info.get("created_at", ""),
            info["snapshot_id"],
        ),
        reverse=True,
    )


def get_snapshot(
    snapshot_id: str,
    *,
    data_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return the manifest of one completed snapshot, located by id.

    The snapshot is located across all namespaces (the returned dict carries
    the ``namespace`` and absolute ``path``). Unfinished directories (no
    ``_SUCCESS``) and corrupted manifests raise :class:`SnapshotError`; an
    unknown id raises :class:`SnapshotNotFoundError`.
    """
    snapshot_id = _validate_component(snapshot_id, "snapshot_id")
    root = _resolve_data_root(data_root)
    snapshots_root = root / "snapshots"
    if not snapshots_root.is_dir():
        raise SnapshotNotFoundError(f"No snapshots exist under {root}.")
    namespace, snapshot_dir = _locate_snapshot(snapshot_id, snapshots_root)
    return _snapshot_info(snapshot_dir, namespace)


def resolve_snapshot_manifest(
    snapshot_id: str,
    *,
    data_root: str | Path | None = None,
) -> Path:
    """Resolve the absolute ``manifest.json`` path of one completed snapshot.

    Locates the snapshot like :func:`get_snapshot` and verifies it is
    completed (``_SUCCESS`` present, manifest readable) before returning.
    """
    snapshot_id = _validate_component(snapshot_id, "snapshot_id")
    root = _resolve_data_root(data_root)
    snapshots_root = root / "snapshots"
    if not snapshots_root.is_dir():
        raise SnapshotNotFoundError(f"No snapshots exist under {root}.")
    _, snapshot_dir = _locate_snapshot(snapshot_id, snapshots_root)
    _read_completed_manifest(snapshot_dir)
    return snapshot_dir / _MANIFEST_FILE_NAME


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _require_table_inputs(tables: Sequence[SnapshotTableInput]) -> None:
    if not isinstance(tables, Sequence) or isinstance(tables, (str, bytes, bytearray)):
        raise SnapshotError("tables must be a sequence of SnapshotTableInput.")
    if not tables:
        raise SnapshotError("At least one table is required to create a snapshot.")
    for table in tables:
        if not isinstance(table, SnapshotTableInput):
            raise SnapshotError("tables must contain only SnapshotTableInput entries.")


def _write_tables(
    snapshot_root: Path,
    tables: Sequence[SnapshotTableInput],
) -> dict[str, list[dict[str, Any]]]:
    import pandas as pd
    import pyarrow as pa

    refs: dict[str, list[dict[str, Any]]] = {}
    for table_input in tables:
        logical_name = _validate_component(table_input.logical_name, "logical_name")
        if logical_name in refs:
            raise SnapshotError(f"Duplicate table logical name: {logical_name!r}")
        table_dir = snapshot_root / "tables" / logical_name
        table_dir.mkdir(parents=True)
        frame = table_input.frame
        if isinstance(frame, pd.DataFrame):
            data = pa.Table.from_pandas(frame, preserve_index=False)
        elif isinstance(frame, pa.Table) or isinstance(frame, pa.dataset.Dataset):
            data = frame
        else:
            raise SnapshotError(
                f"Table {logical_name!r}: frame must be a pandas DataFrame, "
                "pyarrow Table or pyarrow Dataset."
            )
        try:
            _write_arrow_table(table_dir, data, tuple(table_input.partition_by))
        except SnapshotError:
            raise
        except Exception as exc:
            raise SnapshotError(f"Failed to write table {logical_name!r}: {exc}") from exc
        files = sorted(path for path in table_dir.rglob("*.parquet"))
        if not files:
            raise SnapshotError(f"Table {logical_name!r}: no parquet files were written.")
        refs[logical_name] = [_asset_ref(path, snapshot_root) for path in files]
    return refs


def _write_arrow_table(
    table_dir: Path,
    data: Any,
    partition_by: tuple[str, ...],
) -> None:
    import pyarrow.dataset as ds
    import pyarrow.parquet as pq

    if partition_by:
        ds.write_dataset(
            data,
            table_dir,
            format="parquet",
            partitioning=list(partition_by),
            partitioning_flavor="hive",
            basename_template="part-{i}.parquet",
            existing_data_behavior="overwrite_or_ignore",
        )
    elif isinstance(data, ds.Dataset):
        ds.write_dataset(
            data,
            table_dir,
            format="parquet",
            partitioning_flavor="hive",
            basename_template="part-{i}.parquet",
            existing_data_behavior="overwrite_or_ignore",
        )
    else:
        pq.write_table(data, table_dir / "part-0.parquet")


def _asset_ref(file_path: Path, snapshot_root: Path) -> dict[str, Any]:
    import pyarrow.parquet as pq

    parquet_file = pq.ParquetFile(file_path)
    try:
        schema = parquet_file.schema_arrow
        row_count = parquet_file.metadata.num_rows
    finally:
        parquet_file.close()
    return {
        "uri": "/".join(file_path.relative_to(snapshot_root).parts),
        "sha256": _sha256_file(file_path),
        "size_bytes": file_path.stat().st_size,
        "row_count": row_count,
        "schema_hash": _schema_hash(schema),
    }


def _copy_artifact(source: Path, target: Path) -> None:
    try:
        shutil.copy2(source, target)
    except OSError as exc:
        raise SnapshotError(f"Failed to copy extra artifact {source}: {exc}") from exc


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_HASH_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _schema_hash(schema: Any) -> str:
    """SHA-256 of the schema's canonical JSON (05 §4, Skynet reader contract).

    Canonical form: the ordered field list with name / type string / nullable
    and per-field metadata; file-level key-value metadata (e.g. pandas' blob)
    is not part of any field, so it never enters the digest. Must stay
    byte-identical to ``skynet.adapters.manifest._schema_hash`` — the reader
    recomputes it from the published file and rejects mismatches.
    """
    fields = [
        {
            "name": field.name,
            "type": str(field.type),
            "nullable": field.nullable,
            "metadata": (
                {
                    key.decode("utf-8", "replace"): value.decode("utf-8", "replace")
                    for key, value in field.metadata.items()
                }
                if field.metadata
                else {}
            ),
        }
        for field in schema
    ]
    return _sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _compute_content_hash(
    table_refs: Mapping[str, list[dict[str, Any]]],
    source_datasets: Sequence[Mapping[str, Any]],
    calendar_version: str,
    limitations: Sequence[str],
) -> str:
    """Root content hash over the manifest payload (05 §4).

    Assets are keyed ``relative_uri`` in the hash payload (the manifest wire
    format keeps ``uri``) and the canonical JSON follows the repo convention
    (``sort_keys``, compact separators, ``ensure_ascii=False``) — both sides
    of the contract are pinned by docs/plan/axdata-integration/05 §4 and
    recomputed by the Skynet v2 reader on load.
    """
    payload = {
        "manifest_version": _MANIFEST_VERSION,
        "tables": {
            logical_name: [
                {
                    "relative_uri": asset["uri"],
                    "sha256": asset["sha256"],
                    "size_bytes": asset["size_bytes"],
                    "row_count": asset["row_count"],
                    "schema_hash": asset["schema_hash"],
                }
                for asset in assets
            ]
            for logical_name, assets in table_refs.items()
        },
        "source_datasets": [dict(entry) for entry in source_datasets],
        "calendar_version": calendar_version,
        "limitations": list(limitations),
    }
    try:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except TypeError as exc:
        raise SnapshotError(f"Snapshot metadata is not JSON-serializable: {exc}") from exc
    return _sha256(canonical)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _read_completed_manifest(snapshot_dir: Path) -> dict[str, Any]:
    if not (snapshot_dir / _SUCCESS_FILE_NAME).is_file():
        raise SnapshotError(f"Snapshot is incomplete (missing _SUCCESS): {snapshot_dir}")
    manifest_path = snapshot_dir / _MANIFEST_FILE_NAME
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SnapshotError(f"Cannot read snapshot manifest {manifest_path}: {exc}") from exc
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"Snapshot manifest is corrupted {manifest_path}: {exc}") from exc
    if not isinstance(manifest, Mapping):
        raise SnapshotError(f"Snapshot manifest is corrupted (not an object): {manifest_path}")
    return dict(manifest)


def _snapshot_info(
    snapshot_dir: Path,
    namespace: str,
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if manifest is None:
        manifest = _read_completed_manifest(snapshot_dir)
    return {"namespace": namespace, "path": str(snapshot_dir), **dict(manifest)}


def _locate_snapshot(snapshot_id: str, snapshots_root: Path) -> tuple[str, Path]:
    found: list[tuple[str, Path]] = []
    for namespace_dir in sorted(snapshots_root.iterdir()):
        if not namespace_dir.is_dir():
            continue
        candidate = namespace_dir / snapshot_id
        if not candidate.exists():
            continue
        _check_inside_root(candidate, snapshots_root)
        found.append((namespace_dir.name, candidate))
    if not found:
        raise SnapshotNotFoundError(
            f"Snapshot {snapshot_id!r} was not found under {snapshots_root}. "
            "Only completed snapshots (with _SUCCESS) are visible."
        )
    if len(found) > 1:
        namespaces = ", ".join(name for name, _ in found)
        raise SnapshotError(f"Snapshot {snapshot_id!r} exists in multiple namespaces: {namespaces}")
    return found[0]


# ---------------------------------------------------------------------------
# Validation and path safety
# ---------------------------------------------------------------------------


def _resolve_data_root(data_root: str | Path | None) -> Path:
    return Path(data_root or os.getenv("AXDATA_DATA_DIR", "data")).expanduser().resolve()


def _validate_component(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SnapshotError(f"Snapshot {label} must be a non-empty string.")
    text = value.strip()
    if _URI_SCHEME_PATTERN.match(text):
        raise SnapshotError(f"Refusing {label} with URI scheme: {text!r}")
    normalized = text.replace("\\", "/")
    if normalized.startswith("//"):
        raise SnapshotError(f"Refusing non-local {label}: {text!r}")
    if "/" in normalized:
        raise SnapshotError(f"Refusing {label} with path separators: {text!r}")
    if text in (".", ".."):
        raise SnapshotError(f"Refusing {label} with '.'/'..' component: {text!r}")
    return text


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SnapshotError(f"Snapshot {label} must be a non-empty string.")
    return value.strip()


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SnapshotError(f"{label} must be a mapping.")
    return dict(value)


def _normalize_source_datasets(
    source_datasets: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(source_datasets, Sequence) or isinstance(
        source_datasets, (str, bytes, bytearray)
    ):
        raise SnapshotError("source_datasets must be a sequence of mappings.")
    return [_require_mapping(entry, "source_datasets entry") for entry in source_datasets]


def _normalize_extra_artifacts(
    extra_artifacts: Sequence[Path],
) -> list[tuple[str, Path]]:
    if not isinstance(extra_artifacts, Sequence) or isinstance(
        extra_artifacts, (str, bytes, bytearray)
    ):
        raise SnapshotError("extra_artifacts must be a sequence of paths.")
    entries: list[tuple[str, Path]] = []
    for artifact in extra_artifacts:
        path = Path(artifact)
        if not path.is_file():
            raise SnapshotError(f"Extra artifact is not an existing file: {path}")
        name = path.name
        if not name or name in _RESERVED_ROOT_NAMES:
            raise SnapshotError(f"Extra artifact name is reserved: {name!r}")
        if any(existing == name for existing, _ in entries):
            raise SnapshotError(f"Duplicate extra artifact name: {name!r}")
        entries.append((name, path))
    return entries


def _normalize_qlib_provider_uri(value: str | None) -> str | None:
    """A snapshot-root-relative provider path, or ``None``.

    Absolute values, URI schemes and ``..`` escapes are refused: the value is
    recorded verbatim in the manifest and consumers resolve it against the
    snapshot root, so it must never be able to point outside it.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SnapshotError("qlib_provider_uri must be None or a non-empty relative path.")
    text = value.strip()
    if _URI_SCHEME_PATTERN.match(text):
        raise SnapshotError(f"Refusing qlib_provider_uri with URI scheme: {text!r}")
    path = Path(text)
    # ``Path.is_absolute()`` is False for ``/abs`` on Windows (no drive), so
    # a leading separator is checked explicitly — a snapshot-relative uri may
    # never start at a filesystem root.
    if path.is_absolute() or text.startswith(("/", "\\")) or ".." in path.parts:
        raise SnapshotError(
            f"Refusing qlib_provider_uri outside the snapshot root: {text!r}"
        )
    return text


def _inside_root(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    resolved_root = root.resolve()
    return resolved == resolved_root or resolved_root in resolved.parents


def _check_inside_root(path: Path, root: Path) -> None:
    if not _inside_root(path, root):
        raise SnapshotError(f"Snapshot path escapes the snapshot root: {path}")


def _write_json(path: Path, value: Any, *, sort_keys: bool) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=sort_keys)
    path.write_text(text + "\n", encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
