"""Dynamic dataset catalog for AxData.

Resolves :class:`DatasetDescriptor` objects for datasets discovered from, in
priority order:

1. Collector/Plugin output declarations (``CollectorSpec.output``);
2. The latest successful Collector run metadata (the collector scheduler store
   and the run log JSON files written next to outputs by the collector and
   downloader engines);
3. Existing Parquet files on disk;
4. The static core ``SCHEMAS`` (compatibility layer).

Dataset identity and structure (dataset id, layer, paths, columns, primary
key, date field, partition layout, write mode) are parsed only here.
``data_browser`` consumes descriptors and enriches summaries with run quality
and parquet statistics.

Conflict rules:

- Declared primary key / date field win over discovered values, but when the
  actual Parquet files are missing a declared column, resolution fails with
  :class:`CatalogConflictError` instead of guessing.
- When two successful runs of the same dataset declare incompatible
  structure, resolution fails with :class:`CatalogConflictError` instead of
  silently picking the latest run.
- A Collector declaration without any existing output files registers the
  dataset (intent only) but does not override the structure of actual data
  views; it is used as the last-resort fallback for declared-only datasets.

Path safety: catalogued paths must be local filesystem paths. Relative paths
are resolved against the data root and must stay inside it; ``..`` components,
URI schemes (``s3://``, ``file://``, ...) and UNC-style paths are rejected.
Absolute paths recorded in run metadata are accepted as explicitly owned
output directories (the collector/downloader engines may write outside the
data root), but they are still subject to the ``..`` and scheme checks.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .collector_registry import build_collector_registry
from .collector_scheduler import (
    CollectorSchedulerStore,
    collector_scheduler_store_path,
)
from .schema import get_schema, list_tables

KNOWN_DATA_LAYERS = ("raw", "staging", "core", "factor", "snapshot", "snapshots")
DATASET_FORMAT_DIRS = ("parquet", "csv", "duckdb", "jsonl")
_MAX_CATALOG_RUNS = 500
_MAX_SCAN_FILES = 200
_MAX_SCAN_DIRS = 2000
_MAX_LOG_FILES_PER_DIR = 200
_DATASET_DIR_PREFIXES = ("dataset=", "table=", "interface=")
_DECLARATION_SOURCES = ("collector_registry", "collector_run", "collector_log")
_URI_SCHEME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")


class DatasetCatalogError(ValueError):
    """Raised when dataset resolution cannot continue."""


class DatasetNotFoundError(KeyError, DatasetCatalogError):
    """Raised when a dataset_id has no catalog entry."""


class CatalogConflictError(DatasetCatalogError):
    """Raised when declarations for one dataset conflict."""


@dataclass(frozen=True, slots=True)
class DatasetDescriptor:
    """Immutable resolved description of one catalogued dataset."""

    dataset_id: str
    layer: str
    format: str
    paths: tuple[Path, ...]
    columns: tuple[str, ...]
    primary_key: tuple[str, ...] = ()
    date_field: str | None = None
    partition_by: tuple[str, ...] = ()
    write_mode: str | None = None
    source_runs: tuple[str, ...] = ()
    updated_at: str | None = None
    declaration: Mapping[str, Any] = field(default_factory=dict)


def list_dataset_descriptors(
    *,
    data_root: str | Path | None = None,
) -> list[DatasetDescriptor]:
    """Return every dataset known to the AxData catalog, sorted by id.

    The listing is a cheap metadata view: it does not read Parquet schemas for
    datasets already described by declarations or run metadata, and it does not
    verify declared columns against actual files. Use
    :func:`get_dataset_descriptor` for authoritative single-dataset
    resolution.
    """

    root = _resolve_data_root(data_root)
    descriptors = _build_descriptors(root)
    return [descriptors[dataset_id] for dataset_id in sorted(descriptors)]


def get_dataset_descriptor(
    dataset_id: str,
    *,
    data_root: str | Path | None = None,
) -> DatasetDescriptor:
    """Resolve one dataset authoritatively.

    Raises:

    - :class:`DatasetNotFoundError` when the dataset_id is unknown;
    - :class:`CatalogConflictError` when successful runs declare incompatible
      structure or when a declared primary key / date field column is missing
      from the actual Parquet files;
    - :class:`DatasetCatalogError` when a catalogued path is unsafe;
    - :class:`FileNotFoundError` when the dataset has no existing Parquet
      output.
    """

    root = _resolve_data_root(data_root)
    descriptors = _build_descriptors(root)
    descriptor = descriptors.get(str(dataset_id))
    if descriptor is None:
        known = ", ".join(sorted(descriptors)) or "<empty>"
        raise DatasetNotFoundError(
            f"Dataset {dataset_id!r} was not found in the AxData catalog. Known datasets: {known}."
        )
    _verify_descriptor_data(descriptor)
    return descriptor


def _resolve_data_root(data_root: str | Path | None) -> Path:
    return Path(data_root or os.getenv("AXDATA_DATA_DIR", "data")).expanduser().resolve()


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


def _safe_catalog_path(path_text: str, root: Path) -> Path:
    if not isinstance(path_text, str) or not str(path_text).strip():
        raise DatasetCatalogError("Dataset output path is empty.")
    text = str(path_text).strip()
    if _URI_SCHEME_PATTERN.match(text):
        raise DatasetCatalogError(f"Refusing unsupported dataset path scheme: {text!r}")
    normalized = text.replace("\\", "/")
    if normalized.startswith("//"):
        raise DatasetCatalogError(f"Refusing non-local dataset path: {text!r}")
    if any(part == ".." for part in normalized.split("/")):
        raise DatasetCatalogError(f"Refusing dataset path escaping the data directory: {text!r}")
    root_resolved = root.resolve()
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = root_resolved / path
    return path.resolve()


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(item) for item in value]
    return [str(value)]


def _string_tuple(value: Any) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_string_list(value)))


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _path_sort_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _dataset_id(interface_name: str, layer: str | None) -> str:
    clean = interface_name.strip() or "dataset"
    if layer and layer not in {"snapshot", "core"}:
        return f"{layer}.{clean}"
    return clean


def _layer_from_payload(
    primary: Mapping[str, Any],
    secondary: Mapping[str, Any],
    output_paths: Mapping[str, Any],
) -> str | None:
    for payload in (primary, secondary):
        output = payload.get("output")
        if isinstance(output, Mapping):
            layer = _string_or_none(output.get("layer") or output.get("output_layer"))
            if layer:
                return layer
        for key in ("layer", "output_layer"):
            layer = _string_or_none(payload.get(key))
            if layer:
                return layer
    joined = " ".join(str(path).replace("\\", "/") for path in output_paths.values())
    for layer in KNOWN_DATA_LAYERS:
        if f"/{layer}/" in joined or f"\\{layer}\\" in joined or f"{layer}/table=" in joined:
            return layer
    return "snapshot"


def _declared_formats(
    declaration: Mapping[str, Any],
    output: Mapping[str, Any],
) -> list[str]:
    values = _string_list(
        declaration.get("formats")
        or declaration.get("supported_formats")
        or output.get("supported_formats")
        or output.get("formats")
        or ["parquet"]
    )
    ordered: list[str] = []
    for value in values:
        clean = value.strip().lower()
        if clean and clean not in ordered:
            ordered.append(clean)
    return ordered or ["parquet"]


def _collector_output_declarations(
    collector: Any,
    output: Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw_datasets = output.get("datasets") or output.get("outputs")
    declarations: list[dict[str, Any]] = []
    if isinstance(raw_datasets, Sequence) and not isinstance(raw_datasets, (str, bytes, bytearray)):
        for item in raw_datasets:
            if isinstance(item, Mapping):
                declarations.append(dict(item))
    if declarations:
        return declarations

    dataset_id = getattr(collector, "dataset_id", None)
    if not dataset_id:
        return []
    return [
        {
            "dataset_id": dataset_id,
            "display_name_zh": getattr(collector, "display_name_zh", None),
            "description": getattr(collector, "description", ""),
            "layer": output.get("layer") or output.get("output_layer"),
            "table": output.get("table") or output.get("logical_table") or dataset_id,
            "fields": output.get("fields"),
            "primary_key": output.get("primary_key"),
            "date_field": output.get("date_field"),
            "partition_by": output.get("partition_by"),
            "write_mode": output.get("write_mode"),
            "storage": output.get("storage"),
            "formats": output.get("supported_formats") or output.get("formats"),
        }
    ]


def _output_dataset_declaration(
    payload: Mapping[str, Any],
    *,
    interface_name: str,
    layer: str | None,
) -> dict[str, Any]:
    output = payload.get("output")
    if not isinstance(output, Mapping):
        output = {}
    raw_datasets = output.get("datasets") or output.get("outputs")
    if isinstance(raw_datasets, Sequence) and not isinstance(raw_datasets, (str, bytes, bytearray)):
        target_names = {
            _normalize_dataset_name(interface_name),
            _normalize_dataset_name(str(payload.get("dataset_id") or "")),
            _normalize_dataset_name(str(payload.get("table") or "")),
        }
        target_names.discard("")
        for item in raw_datasets:
            if not isinstance(item, Mapping):
                continue
            declaration = dict(item)
            names = {
                _normalize_dataset_name(str(declaration.get("dataset_id") or "")),
                _normalize_dataset_name(str(declaration.get("table") or "")),
                _normalize_dataset_name(str(declaration.get("logical_table") or "")),
            }
            names.discard("")
            if target_names & names:
                return declaration
        for item in raw_datasets:
            if isinstance(item, Mapping):
                return dict(item)
    dataset_id = payload.get("dataset_id")
    if dataset_id:
        return {
            "dataset_id": dataset_id,
            "table": payload.get("table") or output.get("table") or dataset_id,
            "layer": layer or output.get("layer") or output.get("output_layer"),
            "fields": output.get("fields"),
            "primary_key": output.get("primary_key"),
            "date_field": output.get("date_field"),
            "partition_by": output.get("partition_by"),
            "write_mode": output.get("write_mode"),
            "storage": output.get("storage"),
            "formats": output.get("supported_formats") or output.get("formats"),
        }
    return {}


def _declared_output_paths(
    root: Path,
    declaration: Mapping[str, Any],
    output: Mapping[str, Any],
) -> dict[str, str]:
    path_parts = _string_list(
        declaration.get("default_output_path_parts")
        or declaration.get("path_parts")
        or output.get("default_output_path_parts")
    )
    if not path_parts:
        layer = str(
            declaration.get("layer")
            or output.get("layer")
            or output.get("output_layer")
            or "snapshot"
        )
        table = str(
            declaration.get("table")
            or declaration.get("logical_table")
            or declaration.get("dataset_id")
            or ""
        )
        default_dir_name = str(
            declaration.get("default_dir_name")
            or output.get("default_dir_name")
            or declaration.get("dataset_id")
            or table
        )
        path_parts = [
            layer,
            (
                f"table={table}"
                if layer == "core" and table and "." not in table
                else default_dir_name
            ),
        ]
    base = root.joinpath(*path_parts)
    formats = _declared_formats(declaration, output)
    return {format_name: str(base / format_name) for format_name in formats}


def _write_metadata_from_payload(
    primary: Mapping[str, Any],
    quality: Mapping[str, Any],
) -> dict[str, Any]:
    nested = primary.get("write_metadata")
    source = dict(nested) if isinstance(nested, Mapping) else primary
    primary_key = _string_list(
        source.get("primary_key") if "primary_key" in source else quality.get("write_primary_key")
    )
    partition_by = _string_list(source.get("partition_by") or quality.get("partition_by"))
    date_field = _string_or_none(
        source.get("date_field") or quality.get("write_date_field") or quality.get("date_field")
    )
    return {
        "write_mode": _string_or_none(source.get("write_mode") or quality.get("write_mode")),
        "partition_by": partition_by,
        "primary_key": primary_key,
        "date_field": date_field,
        "replace_range_start": _string_or_none(
            source.get("replace_range_start") or quality.get("replace_range_start")
        ),
        "replace_range_end": _string_or_none(
            source.get("replace_range_end") or quality.get("replace_range_end")
        ),
        "rows_before": _int_or_none(
            source.get("rows_before") if "rows_before" in source else quality.get("rows_before")
        ),
        "rows_written": _int_or_none(
            source.get("rows_written") if "rows_written" in source else quality.get("rows_written")
        ),
        "rows_after": _int_or_none(
            source.get("rows_after") if "rows_after" in source else quality.get("rows_after")
        ),
        "duplicate_rows_dropped": _int_or_none(
            source.get("duplicate_rows_dropped")
            if "duplicate_rows_dropped" in source
            else quality.get("duplicate_rows_dropped")
        ),
        "partitions_touched": _string_list(
            source.get("partitions_touched") or quality.get("partitions_touched")
        ),
    }


def _source_from_payload(provider: Any, source_meta: Mapping[str, Any]) -> str | None:
    source = _string_or_none(source_meta.get("source") or source_meta.get("source_code"))
    if source:
        return source
    provider_text = _string_or_none(provider)
    if provider_text and "." in provider_text:
        return provider_text.rsplit(".", 1)[-1]
    return provider_text


def _normalize_dataset_name(value: str) -> str:
    return re.sub(r"\s+", "", value.strip().lower())


def _quality_columns(quality: Mapping[str, Any]) -> list[str]:
    columns = quality.get("schema_columns") if isinstance(quality, Mapping) else None
    if isinstance(columns, str):
        return [field.strip() for field in columns.split(",") if field.strip()]
    if isinstance(columns, Iterable):
        return [str(field) for field in columns if str(field).strip()]
    return []


# ---------------------------------------------------------------------------
# Source 1: Collector/Plugin output declarations
# ---------------------------------------------------------------------------


def _registry_declared_views(root: Path) -> list[dict[str, Any]]:
    try:
        registry = build_collector_registry(data_root=root)
    except Exception:
        return []
    views: list[dict[str, Any]] = []
    for registration in registry.list_collectors():
        collector = registration.collector
        output = dict(collector.output or {})
        for declaration in _collector_output_declarations(collector, output):
            dataset_id = str(
                declaration.get("dataset_id") or collector.dataset_id or collector.collector_id
            )
            layer = _string_or_none(
                declaration.get("layer") or output.get("layer") or output.get("output_layer")
            )
            declared_paths = _declared_output_paths(root, declaration, output)
            safe_paths: dict[str, Path] = {}
            for format_name, path_text in declared_paths.items():
                safe_paths[format_name] = _safe_catalog_path(path_text, root)
            existing_paths = {
                format_name: path for format_name, path in safe_paths.items() if path.exists()
            }
            if existing_paths:
                format_name = (
                    "parquet" if "parquet" in existing_paths else next(iter(existing_paths))
                )
                paths = (existing_paths[format_name],)
            else:
                format_name = (
                    "parquet"
                    if "parquet" in safe_paths
                    else (next(iter(safe_paths)) if safe_paths else "parquet")
                )
                paths = ()
            primary_key = _string_tuple(declaration.get("primary_key") or output.get("primary_key"))
            date_field = _string_or_none(declaration.get("date_field") or output.get("date_field"))
            partition_by = _string_tuple(
                declaration.get("partition_by") or output.get("partition_by")
            )
            write_mode = _string_or_none(declaration.get("write_mode") or output.get("write_mode"))
            signature_values = (layer, primary_key, date_field, partition_by, write_mode)
            views.append(
                {
                    "dataset_id": dataset_id,
                    "priority": 1,
                    "layer": layer,
                    "format": format_name,
                    "paths": paths,
                    "columns": _string_tuple(
                        declaration.get("columns") or declaration.get("default_query_fields")
                    ),
                    "primary_key": primary_key,
                    "date_field": date_field,
                    "partition_by": partition_by,
                    "write_mode": write_mode,
                    "updated_at": None,
                    "source_runs": (),
                    "declaration": {
                        **declaration,
                        "declared_only": True,
                        "_source": "collector_registry",
                        "collector_plugin_id": registration.collector_plugin_id,
                        "collector_name": collector.collector_id,
                    },
                    "signature": signature_values if any(signature_values) else None,
                }
            )
    return views


# ---------------------------------------------------------------------------
# Source 2: successful run metadata (scheduler store + run logs)
# ---------------------------------------------------------------------------


def _run_metadata_views(root: Path) -> list[dict[str, Any]]:
    views: list[dict[str, Any]] = []
    run_views: list[dict[str, Any]] = []
    store_path = collector_scheduler_store_path(data_root=root)
    if store_path.exists():
        try:
            runs = CollectorSchedulerStore(data_root=root).list_runs(limit=_MAX_CATALOG_RUNS)
        except Exception:
            runs = ()
        for run in runs:
            if getattr(run, "status", None) != "success":
                continue
            view = _view_from_run(root, run)
            if view is not None:
                run_views.append(view)
    views.extend(run_views)
    seen_dirs: set[Path] = set()
    for log_dir in _candidate_log_dirs(root, run_views):
        views.extend(_iter_log_dir(log_dir, seen_dirs, root))
    return views


def _candidate_log_dirs(
    root: Path,
    run_views: Sequence[Mapping[str, Any]],
) -> Iterable[Path]:
    candidates = [root / layer for layer in KNOWN_DATA_LAYERS if (root / layer).exists()]
    for candidate in candidates:
        yield from candidate.glob("*/logs")
        yield from candidate.glob("*/*/logs")
        yield from candidate.glob("*/*/*/logs")
    for view in run_views:
        for path in view.get("paths", ()):
            if not isinstance(path, Path):
                continue
            adjacent: list[Path] = []
            if path.is_file():
                adjacent.append(path.parent.parent / "logs")
            elif path.is_dir():
                adjacent.append(path / "logs")
                adjacent.append(path.parent / "logs")
            yield from adjacent


def _iter_log_dir(
    log_dir: Path,
    seen: set[Path],
    root: Path,
) -> Iterable[dict[str, Any]]:
    try:
        resolved = log_dir.resolve()
    except OSError:
        return
    if resolved in seen or not resolved.exists():
        return
    seen.add(resolved)
    log_paths = sorted(
        resolved.glob("*.json"),
        key=_path_sort_mtime,
        reverse=True,
    )[:_MAX_LOG_FILES_PER_DIR]
    for log_path in log_paths:
        try:
            payload = json.loads(log_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        status = str(payload.get("status") or "").strip().lower()
        if status and status != "success":
            continue
        view = _view_from_log(root, payload)
        if view is not None:
            yield view


def _view_from_run(root: Path, run: Any) -> dict[str, Any] | None:
    result = dict(getattr(run, "result", {}) or {})
    download_result = result.get("download_result")
    payload = dict(download_result) if isinstance(download_result, Mapping) else dict(result)
    output_paths = {
        str(key): str(value) for key, value in dict(getattr(run, "output_paths", {}) or {}).items()
    }
    if not output_paths and isinstance(download_result, Mapping):
        raw_output_paths = download_result.get("output_paths")
        if isinstance(raw_output_paths, Mapping):
            output_paths = {str(key): str(value) for key, value in raw_output_paths.items()}
    if not output_paths:
        return None
    interface_name = str(
        result.get("target_interface")
        or payload.get("interface_name")
        or getattr(run, "collector_name", "")
        or ""
    )
    quality = dict(getattr(run, "quality", {}) or {})
    if not quality and isinstance(download_result, Mapping):
        download_quality = download_result.get("quality")
        if isinstance(download_quality, Mapping):
            quality = dict(download_quality)
    declaration_payload = dict(payload)
    if "output" not in declaration_payload and isinstance(result.get("output"), Mapping):
        declaration_payload["output"] = result["output"]
    layer = _layer_from_payload(declaration_payload, result, output_paths)
    write_metadata = _write_metadata_from_payload(payload, quality)
    run_metadata = _build_run_metadata(
        run_id=str(run.run_id),
        status=str(getattr(run, "status", None) or ""),
        finished_at=getattr(run, "finished_at", None),
        interface_name=interface_name,
        payload=payload,
        quality=quality,
        write_metadata=write_metadata,
        extra={
            "collector_name": getattr(run, "collector_name", None),
            "task_id": getattr(run, "task_id", None),
            "provider_id": getattr(run, "provider_id", None),
            "downloader_profile": getattr(run, "downloader_profile", None),
            "params": getattr(run, "params", {}),
            "collector_plugin_id": payload.get("collector_plugin_id"),
            "updated_at": getattr(run, "updated_at", None),
        },
    )
    return _view_from_payload(
        payload=declaration_payload,
        interface_name=interface_name,
        layer=layer,
        output_paths=output_paths,
        quality=quality,
        run_id=str(run.run_id),
        updated_at=getattr(run, "finished_at", None) or getattr(run, "updated_at", None),
        source_kind="collector_run",
        run_metadata=run_metadata,
        root=root,
    )


def _view_from_log(root: Path, payload: Mapping[str, Any]) -> dict[str, Any] | None:
    output_paths = payload.get("output_paths")
    if not isinstance(output_paths, Mapping) or not output_paths:
        return None
    output_paths = {str(key): str(value) for key, value in output_paths.items()}
    interface_name = str(payload.get("interface_name") or payload.get("target_interface") or "")
    if not interface_name:
        return None
    quality = dict(payload.get("quality")) if isinstance(payload.get("quality"), Mapping) else {}
    layer = _layer_from_payload(payload, {}, output_paths)
    write_metadata = _write_metadata_from_payload(payload, quality)
    run_metadata = _build_run_metadata(
        run_id=str(payload.get("job_id") or ""),
        status=str(payload.get("status") or ""),
        finished_at=payload.get("finished_at"),
        interface_name=interface_name,
        payload=payload,
        quality=quality,
        write_metadata=write_metadata,
        extra={
            "collector_name": payload.get("collector_id") or payload.get("collector_name"),
            "task_id": payload.get("task_id"),
            "provider_id": payload.get("provider_id"),
            "collector_plugin_id": payload.get("collector_plugin_id"),
            "downloader_profile": payload.get("downloader_profile"),
            "params": payload.get("params"),
            "updated_at": payload.get("updated_at"),
        },
    )
    return _view_from_payload(
        payload=payload,
        interface_name=interface_name,
        layer=layer,
        output_paths=output_paths,
        quality=quality,
        run_id=str(payload.get("job_id") or ""),
        updated_at=_string_or_none(payload.get("finished_at") or payload.get("updated_at")),
        source_kind="collector_log",
        run_metadata=run_metadata,
        root=root,
    )


def _build_run_metadata(
    *,
    run_id: str,
    status: str | None,
    finished_at: str | None,
    interface_name: str,
    payload: Mapping[str, Any],
    quality: Mapping[str, Any],
    write_metadata: Mapping[str, Any],
    extra: Mapping[str, Any],
) -> dict[str, Any]:
    source_meta = payload.get("source_meta")
    source_meta_mapping = dict(source_meta) if isinstance(source_meta, Mapping) else {}
    provider_id = _string_or_none(extra.get("provider_id"))
    return {
        "run_id": run_id or None,
        "status": _string_or_none(status),
        "finished_at": _string_or_none(finished_at),
        "updated_at": _string_or_none(extra.get("updated_at")),
        "collector_name": _string_or_none(extra.get("collector_name")),
        "task_id": _string_or_none(extra.get("task_id")),
        "collector_plugin_id": _string_or_none(extra.get("collector_plugin_id")),
        "provider_id": provider_id,
        "downloader_profile": _string_or_none(extra.get("downloader_profile")),
        "params": (dict(extra.get("params")) if isinstance(extra.get("params"), Mapping) else {}),
        "interface_name": _string_or_none(interface_name),
        "row_count": _int_or_none(payload.get("row_count") or quality.get("row_count_value")),
        "snapshot_date": _string_or_none(payload.get("snapshot_date")),
        "log_path": _string_or_none(payload.get("log_path")),
        "source": _source_from_payload(provider_id, source_meta_mapping),
        "source_meta": source_meta_mapping,
        "quality": dict(quality),
        "write_metadata": dict(write_metadata),
    }


def _view_from_payload(
    *,
    payload: Mapping[str, Any],
    interface_name: str,
    layer: str | None,
    output_paths: Mapping[str, Any],
    quality: Mapping[str, Any],
    run_id: str,
    updated_at: str | None,
    source_kind: str,
    run_metadata: Mapping[str, Any],
    root: Path,
) -> dict[str, Any] | None:
    declared = _output_dataset_declaration(payload, interface_name=interface_name, layer=layer)
    write_metadata = _write_metadata_from_payload(payload, quality)
    dataset_id = str(declared.get("dataset_id") or _dataset_id(interface_name, layer))
    format_name, paths = _paths_for_format(output_paths, root)
    if format_name is None:
        return None
    primary_key = _string_tuple(declared.get("primary_key")) or write_metadata["primary_key"]
    date_field = _string_or_none(declared.get("date_field")) or write_metadata["date_field"]
    partition_by = _string_tuple(declared.get("partition_by")) or write_metadata["partition_by"]
    write_mode = _string_or_none(declared.get("write_mode")) or write_metadata["write_mode"]
    resolved_layer = _string_or_none(declared.get("layer")) or layer
    columns = _string_tuple(declared.get("columns") or declared.get("default_query_fields"))
    if not columns:
        fields = declared.get("fields")
        if isinstance(fields, Sequence) and not isinstance(fields, (str, bytes, bytearray)):
            names = [
                str(item["name"])
                for item in fields
                if isinstance(item, Mapping) and item.get("name")
            ]
            columns = tuple(names)
    if not columns:
        columns = tuple(_quality_columns(quality))
    signature_values = (resolved_layer, primary_key, date_field, partition_by, write_mode)
    return {
        "dataset_id": dataset_id,
        "priority": 2,
        "layer": resolved_layer,
        "format": format_name,
        "paths": paths,
        "columns": columns,
        "primary_key": primary_key,
        "date_field": date_field,
        "partition_by": partition_by,
        "write_mode": write_mode,
        "updated_at": updated_at,
        "source_runs": (run_id,) if run_id else (),
        "declaration": {
            **declared,
            "_source": source_kind,
            "_run_metadata": dict(run_metadata),
        },
        "signature": signature_values if any(signature_values) else None,
    }


def _paths_for_format(
    output_paths: Mapping[str, Any],
    root: Path,
) -> tuple[str | None, tuple[Path, ...]]:
    safe: dict[str, Path] = {}
    for format_name, path_text in output_paths.items():
        if not isinstance(format_name, str) or not isinstance(path_text, str):
            continue
        safe[format_name] = _safe_catalog_path(path_text, root)
    for format_name in ("parquet", "csv", "duckdb", "jsonl"):
        if format_name in safe:
            return format_name, (safe[format_name],)
    if safe:
        format_name = next(iter(safe))
        return format_name, (safe[format_name],)
    return None, ()


# ---------------------------------------------------------------------------
# Source 3: existing Parquet files
# ---------------------------------------------------------------------------


def _parquet_scan_views(root: Path) -> list[dict[str, Any]]:
    views: list[dict[str, Any]] = []
    for layer in KNOWN_DATA_LAYERS:
        layer_dir = root / layer
        if not layer_dir.is_dir():
            continue
        try:
            entries = sorted(
                path
                for path in layer_dir.iterdir()
                if path.is_dir() and not path.name.startswith(".") and path.name != "logs"
            )
        except OSError:
            continue
        for entry in entries:
            view = _scan_dataset_dir_view(root, entry, layer)
            if view is not None:
                views.append(view)
    return views


def _scan_dataset_dir_view(
    root: Path,
    dataset_dir: Path,
    layer: str,
) -> dict[str, Any] | None:
    dataset_id = _dataset_id_from_dir_name(dataset_dir.name, layer)
    format_dir = dataset_dir / "parquet"
    if format_dir.is_dir() and _dir_may_have_parquet(format_dir):
        format_name, path, columns = "parquet", format_dir, _scan_parquet_columns(format_dir)
    elif _dir_may_have_parquet(dataset_dir):
        format_name, path, columns = "parquet", dataset_dir, _scan_parquet_columns(dataset_dir)
    else:
        format_name = None
        for candidate in ("csv", "duckdb", "jsonl"):
            candidate_dir = dataset_dir / candidate
            if candidate_dir.is_dir():
                format_name, path, columns = candidate, candidate_dir, ()
                break
        if format_name is None:
            return None
    return {
        "dataset_id": dataset_id,
        "priority": 3,
        "layer": layer,
        "format": format_name,
        "paths": (path,),
        "columns": columns,
        "primary_key": (),
        "date_field": None,
        "partition_by": (),
        "write_mode": None,
        "updated_at": None,
        "source_runs": (),
        "declaration": {"_source": "parquet_scan", "storage_layout": "parquet_directory"},
        "signature": None,
    }


def _dataset_id_from_dir_name(name: str, layer: str) -> str:
    for prefix in _DATASET_DIR_PREFIXES:
        if name.startswith(prefix) and len(name) > len(prefix):
            return name[len(prefix) :]
    return name


def _dir_may_have_parquet(directory: Path) -> bool:
    files, limited, _dirs_seen = _bounded_parquet_files(
        directory,
        file_limit=1,
        dir_limit=_MAX_SCAN_DIRS,
    )
    return bool(files) or limited


def _bounded_parquet_files(
    directory: Path,
    *,
    file_limit: int,
    dir_limit: int,
) -> tuple[list[Path], bool, int]:
    if file_limit <= 0:
        return [], True, 0
    files: list[Path] = []
    dirs_seen = 0
    try:
        walk = os.walk(directory)
    except OSError:
        return [], False, 0
    for dirpath, dirnames, filenames in walk:
        dirs_seen += 1
        if dirs_seen > dir_limit:
            return files, True, dirs_seen
        dirnames.sort()
        for filename in sorted(filenames):
            if not filename.lower().endswith(".parquet"):
                continue
            files.append((Path(dirpath) / filename).resolve())
            if len(files) >= file_limit:
                return files, True, dirs_seen
    return files, False, dirs_seen


def _scan_parquet_columns(path: Path) -> tuple[str, ...]:
    if path.is_file() and path.suffix.lower() == ".parquet":
        files = [path.resolve()]
    elif path.is_dir():
        files, _limited, _dirs_seen = _bounded_parquet_files(
            path,
            file_limit=_MAX_SCAN_FILES,
            dir_limit=_MAX_SCAN_DIRS,
        )
    else:
        return ()
    columns: list[str] = []
    for file_path in files:
        for name in _file_parquet_columns(file_path):
            if name not in columns:
                columns.append(name)
        for key in _hive_partition_keys(file_path):
            if key not in columns:
                columns.append(key)
    return tuple(columns)


def _file_parquet_columns(path: Path) -> list[str]:
    import pyarrow.parquet as pq

    try:
        return [str(name) for name in pq.ParquetFile(path).schema_arrow.names]
    except Exception:
        return []


def _hive_partition_keys(path: Path) -> list[str]:
    keys: list[str] = []
    for part in path.parts[:-1]:
        if "=" not in part:
            continue
        key = part.split("=", 1)[0]
        if key and key not in ("table", "dataset", "interface") and key not in keys:
            keys.append(key)
    return keys


# ---------------------------------------------------------------------------
# Source 4: core SCHEMAS compatibility layer
# ---------------------------------------------------------------------------


def _core_schema_views(root: Path) -> list[dict[str, Any]]:
    views: list[dict[str, Any]] = []
    for table in list_tables():
        schema = get_schema(table)
        views.append(
            {
                "dataset_id": table,
                "priority": 4,
                "layer": "core",
                "format": "parquet",
                "paths": _core_table_existing_paths(table, root),
                "columns": tuple(schema.field_names),
                "primary_key": tuple(schema.primary_key),
                "date_field": schema.date_field,
                "partition_by": (),
                "write_mode": None,
                "updated_at": None,
                "source_runs": (),
                "declaration": {
                    "schema": table,
                    "table": table,
                    "logical_table": table,
                    "source": "core_schemas",
                    "_source": "core_schemas",
                },
                "signature": None,
            }
        )
    return views


def _core_table_existing_paths(table: str, root: Path) -> tuple[Path, ...]:
    from .storage import core_table_partition_path, core_table_path

    file_path = core_table_path(table, root)
    partition_path = core_table_partition_path(table, root)
    if file_path.exists():
        return (file_path,)
    if partition_path.exists():
        return (partition_path,)
    return ()


# ---------------------------------------------------------------------------
# Merge and resolution
# ---------------------------------------------------------------------------


def _all_views(root: Path) -> list[dict[str, Any]]:
    views: list[dict[str, Any]] = []
    views.extend(_registry_declared_views(root))
    views.extend(_run_metadata_views(root))
    views.extend(_parquet_scan_views(root))
    views.extend(_core_schema_views(root))
    return views


def _build_descriptors(root: Path) -> dict[str, DatasetDescriptor]:
    views_by_id: dict[str, list[dict[str, Any]]] = {}
    for view in _all_views(root):
        views_by_id.setdefault(view["dataset_id"], []).append(view)
    return {
        dataset_id: _merge_views(dataset_id, views) for dataset_id, views in views_by_id.items()
    }


def _merge_views(dataset_id: str, views: Sequence[Mapping[str, Any]]) -> DatasetDescriptor:
    ordered = sorted(views, key=lambda view: view["priority"])
    _check_run_declaration_conflicts(dataset_id, views)
    # A declaration with no existing output files is intent only: it registers
    # the dataset but must not override the structure of actual data views.
    active = [view for view in ordered if not (view["priority"] == 1 and not view["paths"])]
    intent_only = [view for view in ordered if view["priority"] == 1 and not view["paths"]]
    timestamps = [view["updated_at"] for view in ordered if view.get("updated_at")]
    return DatasetDescriptor(
        dataset_id=dataset_id,
        layer=_first_value(active, "layer") or _first_value(intent_only, "layer") or "snapshot",
        format=_first_value(active, "format") or _first_value(intent_only, "format") or "parquet",
        paths=_first_nonempty(active, "paths") or _first_nonempty(intent_only, "paths"),
        columns=_first_nonempty(active, "columns") or _first_nonempty(intent_only, "columns"),
        primary_key=_first_nonempty(active, "primary_key")
        or _first_nonempty(intent_only, "primary_key"),
        date_field=_first_value(active, "date_field") or _first_value(intent_only, "date_field"),
        partition_by=_first_nonempty(active, "partition_by")
        or _first_nonempty(intent_only, "partition_by"),
        write_mode=_first_value(active, "write_mode") or _first_value(intent_only, "write_mode"),
        source_runs=tuple(
            dict.fromkeys(run_id for view in ordered for run_id in view["source_runs"])
        ),
        updated_at=max(timestamps) if timestamps else None,
        declaration=_merge_declaration(active, intent_only, ordered),
    )


def _merge_declaration(
    active: Sequence[Mapping[str, Any]],
    intent_only: Sequence[Mapping[str, Any]],
    ordered: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    declaration = dict(_best_declaration(active, intent_only))
    # Attach the latest successful run's normalized metadata so consumers can
    # enrich the descriptor even when a declaration view wins on structure.
    latest_run_view: Mapping[str, Any] | None = None
    for view in ordered:
        if view["priority"] != 2:
            continue
        if latest_run_view is None or (view.get("updated_at") or "") >= (
            latest_run_view.get("updated_at") or ""
        ):
            latest_run_view = view
    if latest_run_view is not None:
        run_metadata = latest_run_view["declaration"].get("_run_metadata")
        if isinstance(run_metadata, Mapping) and run_metadata:
            declaration["_run_metadata"] = dict(run_metadata)
    return declaration


def _best_declaration(
    active: Sequence[Mapping[str, Any]],
    intent_only: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    for view in (*active, *intent_only):
        if view["declaration"]:
            return view["declaration"]
    return {}


def _check_run_declaration_conflicts(
    dataset_id: str,
    views: Sequence[Mapping[str, Any]],
) -> None:
    signed = [view for view in views if view["priority"] == 2 and view["signature"] is not None]
    if len(signed) < 2:
        return
    first = signed[0]
    for view in signed[1:]:
        if view["signature"] != first["signature"]:
            raise CatalogConflictError(
                f"Conflicting Collector declarations for dataset {dataset_id!r}: "
                f"{_run_label(first)} declares layer/primary_key/date_field/"
                f"partition_by/write_mode {first['signature']}, while "
                f"{_run_label(view)} declares {view['signature']}. "
                "Refusing to silently pick the latest successful run."
            )


def _run_label(view: Mapping[str, Any]) -> str:
    source_runs = view.get("source_runs") or ()
    if source_runs:
        return f"successful run {source_runs[0]!r}"
    return "run metadata"


def _first_value(views: Sequence[Mapping[str, Any]], key: str) -> Any:
    for view in views:
        value = view.get(key)
        if value is not None:
            return value
    return None


def _first_nonempty(views: Sequence[Mapping[str, Any]], key: str) -> Any:
    for view in views:
        value = view.get(key)
        if value:
            return value
    return ()


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _verify_descriptor_data(descriptor: DatasetDescriptor) -> None:
    if not _existing_parquet_paths(descriptor.paths):
        missing = ", ".join(str(path) for path in descriptor.paths) or "<no declared output paths>"
        raise FileNotFoundError(
            f"Dataset {descriptor.dataset_id!r} has no existing Parquet output. "
            f"Missing path(s): {missing}. Run a Collector/Downloader first."
        )
    declaration = descriptor.declaration or {}
    if declaration.get("_source") not in _DECLARATION_SOURCES:
        return
    declared_columns = [
        column for column in (*descriptor.primary_key, descriptor.date_field) if column
    ]
    if not declared_columns:
        return
    actual_columns = _actual_parquet_columns(descriptor.paths)
    missing = [column for column in declared_columns if column not in actual_columns]
    if missing:
        raise CatalogConflictError(
            f"Dataset {descriptor.dataset_id!r} declares primary key/date field "
            f"column(s) {missing} that are missing from the actual Parquet schema "
            f"{sorted(actual_columns)}."
        )


def _existing_parquet_paths(paths: Sequence[Path]) -> list[Path]:
    existing: list[Path] = []
    for path in paths:
        if path.is_file() and path.suffix.lower() == ".parquet":
            existing.append(path)
        elif path.is_dir() and path.exists():
            existing.append(path)
    return existing


def _actual_parquet_columns(paths: Sequence[Path]) -> set[str]:
    columns: set[str] = set()
    for path in paths:
        if path.is_file() and path.suffix.lower() == ".parquet":
            columns.update(_file_parquet_columns(path))
            columns.update(_hive_partition_keys(path))
        elif path.is_dir():
            files, _limited, _dirs_seen = _bounded_parquet_files(
                path,
                file_limit=_MAX_SCAN_FILES,
                dir_limit=_MAX_SCAN_DIRS,
            )
            for file_path in files:
                columns.update(_file_parquet_columns(file_path))
                columns.update(_hive_partition_keys(file_path))
    return columns
