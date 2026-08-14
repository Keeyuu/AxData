"""Generic dataset query engine (AXI-020).

Queries any AxData catalog dataset stored as Parquet through DuckDB. Dataset
resolution is driven entirely by the dynamic dataset catalog
(:func:`axdata_core.dataset_catalog.get_dataset_descriptor`), so datasets that
are completely absent from the static core ``SCHEMAS`` are queryable as long
as a Collector/Plugin declared them and the output files exist.

Safety model (shared with :mod:`axdata_core.query`):

- Field names are validated against a whitelist built from the descriptor and
  the actual Parquet schema, and every SQL identifier is quoted;
- filter values, date bounds and the limit are always bound as DuckDB
  parameters — values are never spliced into SQL text;
- file discovery uses ``read_parquet(..., union_by_name = true,
  hive_partitioning = true)`` so multi-file, multi-partition outputs are read
  as one unified view;
- path resolution and path-safety checks are delegated to the catalog
  (:class:`DatasetDescriptor` paths are catalog-verified output directories);
  they are never re-implemented or bypassed here.

``preview_dataset`` in :mod:`axdata_core.data_browser` calls this engine and
keeps only the UI-level 100-row limit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .dataset_catalog import get_dataset_descriptor

_NO_MATCHING_PARTITIONS = object()
_HIVE_STRUCTURAL_KEYS = frozenset({"table", "dataset", "interface"})


class DatasetQueryError(ValueError):
    """Raised when a query_dataset request cannot be executed."""


def query_dataset(
    dataset_id: str,
    *,
    data_root: str | Path,
    fields: Sequence[str] | None = None,
    filters: Mapping[str, Any] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
):
    """Query one catalogued AxData dataset and return a pandas DataFrame.

    Resolution goes through :func:`get_dataset_descriptor`, which fails
    explicitly for unknown datasets, missing files, stale output metadata,
    catalog conflicts and unsafe paths. Only Parquet datasets are supported.

    Args:
        dataset_id: Dataset id known to the AxData catalog.
        data_root: AxData data root (the catalog resolves paths against it).
        fields: Columns to return, in this order. ``None`` returns the
            descriptor columns that actually exist in the files.
        filters: Equality / ``IN`` / ``IS NULL`` predicates, AND-combined.
        start_date: Inclusive lower bound on the dataset's ``date_field``,
            either ``YYYY-MM-DD`` or ``YYYYMMDD``. Only allowed when the
            descriptor defines a ``date_field``.
        end_date: Inclusive upper bound on the dataset's ``date_field``.
        limit: Maximum number of rows. ``None`` means no truncation.

    Raises:
        DatasetQueryError: unknown fields, date bounds without a ``date_field``,
            malformed dates or limit, or a non-Parquet dataset.
        DatasetNotFoundError: unknown dataset id.
        CatalogConflictError: conflicting declarations for the dataset.
        DatasetCatalogError: unsafe catalogued paths.
        FileNotFoundError: no existing Parquet output.
    """
    import duckdb
    import pandas as pd

    descriptor = get_dataset_descriptor(dataset_id, data_root=data_root)
    if descriptor.format != "parquet":
        raise DatasetQueryError(
            f"Dataset {dataset_id!r} is stored as {descriptor.format!r}; "
            "only Parquet datasets are supported."
        )

    start = _normalize_date_bound(start_date, "start_date")
    end = _normalize_date_bound(end_date, "end_date")
    if (start is not None or end is not None) and descriptor.date_field is None:
        raise DatasetQueryError(
            f"Dataset {dataset_id!r} does not define a date_field; "
            "start_date/end_date cannot be used."
        )
    if limit is not None and (not isinstance(limit, int) or limit < 0):
        raise DatasetQueryError("limit must be a non-negative integer.")

    selected = _normalize_fields(fields)
    descriptor_columns = list(descriptor.columns)
    read_paths = _dataset_read_paths(
        descriptor.paths,
        date_field=descriptor.date_field,
        start=start,
        end=end,
    )
    if read_paths is _NO_MATCHING_PARTITIONS:
        known = set(descriptor_columns)
        _validate_fields(selected, known=known, available=None, dataset_id=dataset_id)
        _validate_filter_fields(filters, known=known, available=None, dataset_id=dataset_id)
        columns = selected if selected is not None else list(descriptor_columns)
        return pd.DataFrame(columns=columns)

    with duckdb.connect(database=":memory:") as conn:
        available = _available_source_fields(conn, read_paths)
        known = set(descriptor_columns) | set(available)
        _validate_fields(selected, known=known, available=available, dataset_id=dataset_id)
        _validate_filter_fields(filters, known=known, available=available, dataset_id=dataset_id)
        if selected is None:
            selected = _default_columns(descriptor_columns, available)
        if descriptor.date_field and (start is not None or end is not None):
            if descriptor.date_field not in available:
                raise DatasetQueryError(
                    f"Date filter field {descriptor.date_field!r} is not present "
                    f"in the actual Parquet schema of dataset {dataset_id!r}."
                )
        where_sql, params = _build_where_clause(
            filters,
            date_field=descriptor.date_field,
            start=start,
            end=end,
        )
        limit_sql = " LIMIT ?" if limit is not None else ""
        limit_params = [limit] if limit is not None else []
        select_sql = ", ".join(_quote_identifier(field) for field in selected)
        sql = (
            f"SELECT {select_sql} "
            "FROM read_parquet(?, hive_partitioning = true, union_by_name = true)"
            f"{where_sql}{limit_sql}"
        )
        return conn.execute(sql, [read_paths, *params, *limit_params]).fetchdf()


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _normalize_fields(fields: Sequence[str] | str | None) -> list[str] | None:
    if fields is None:
        return None
    if isinstance(fields, str):
        fields = [fields]
    normalized = [str(field).strip() for field in fields if str(field).strip()]
    return normalized or None


def _normalize_date_bound(value: str | None, label: str) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    compact = text.replace("-", "")
    if not (compact.isdigit() and len(compact) == 8):
        raise DatasetQueryError(f"{label} must be YYYY-MM-DD or YYYYMMDD, got {value!r}.")
    return compact


def _validate_fields(
    selected: Sequence[str] | None,
    *,
    known: set[str],
    available: Sequence[str] | None,
    dataset_id: str,
) -> None:
    if not selected:
        return
    unknown = [field for field in selected if field not in known]
    if unknown:
        raise DatasetQueryError(
            f"Unknown field(s): {', '.join(unknown)}. Known fields: {sorted(known)}."
        )
    if available is not None:
        missing = [field for field in selected if field not in set(available)]
        if missing:
            raise DatasetQueryError(
                f"Field(s) {missing} are declared for dataset {dataset_id!r} "
                "but missing from the actual Parquet schema."
            )


def _validate_filter_fields(
    filters: Mapping[str, Any] | None,
    *,
    known: set[str],
    available: Sequence[str] | None,
    dataset_id: str,
) -> None:
    if not filters:
        return
    for field in filters:
        if field not in known:
            raise DatasetQueryError(
                f"Unknown filter field: {field!r}. Known fields: {sorted(known)}."
            )
        if available is not None and field not in set(available):
            raise DatasetQueryError(
                f"Filter field {field!r} is declared for dataset {dataset_id!r} "
                "but missing from the actual Parquet schema."
            )


def _default_columns(descriptor_columns: Sequence[str], available: Sequence[str]) -> list[str]:
    if descriptor_columns:
        return [column for column in descriptor_columns if column in set(available)]
    return [column for column in available if column not in _HIVE_STRUCTURAL_KEYS]


def _available_source_fields(conn: Any, read_paths: Sequence[str]) -> list[str]:
    rows = conn.execute(
        "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning = true, union_by_name = true)",
        [list(read_paths)],
    ).fetchall()
    return [str(row[0]) for row in rows]


def _dataset_read_paths(
    paths: Sequence[Path],
    *,
    date_field: str | None,
    start: str | None,
    end: str | None,
) -> list[str] | object:
    read_paths: list[str] = []
    for path in paths:
        if path.is_file():
            read_paths.append(str(path))
            continue
        if not path.is_dir():
            continue
        date_globs = _date_partition_globs(path, date_field=date_field, start=start, end=end)
        if date_globs is None:
            read_paths.append(str(path / "**" / "*.parquet"))
        else:
            read_paths.extend(date_globs)
    if read_paths:
        return read_paths
    return _NO_MATCHING_PARTITIONS


def _date_partition_globs(
    directory: Path,
    *,
    date_field: str | None,
    start: str | None,
    end: str | None,
) -> list[str] | None:
    if not date_field or not (start or end):
        return None
    partition_dirs = [path for path in directory.glob(f"{date_field}=*") if path.is_dir()]
    date_files = [
        path for path in directory.glob("*.parquet") if _date_file_value(path) is not None
    ]
    if not partition_dirs and not date_files:
        return None

    globs: list[str] = []
    for path in sorted(partition_dirs):
        value = path.name.split("=", 1)[1].replace("-", "")
        if _date_value_in_bounds(value, start, end):
            globs.append(str(path / "**" / "*.parquet"))
    for path in sorted(date_files):
        value = _date_file_value(path)
        if _date_value_in_bounds(value, start, end):
            globs.append(str(path))
    return globs


def _date_file_value(path: Path) -> str | None:
    value = path.stem.replace("-", "")
    return value if len(value) == 8 and value.isdigit() else None


def _date_value_in_bounds(value: str, start: str | None, end: str | None) -> bool:
    return (start is None or value >= start) and (end is None or value <= end)


def _build_where_clause(
    filters: Mapping[str, Any] | None,
    *,
    date_field: str | None,
    start: str | None,
    end: str | None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if filters:
        for field, value in filters.items():
            quoted = _quote_identifier(str(field))
            if isinstance(value, (list, tuple, set, frozenset)):
                values = [item for item in value if item is not None]
                if not values:
                    clauses.append("1 = 0")
                    continue
                placeholders = ", ".join("?" for _ in values)
                clauses.append(f"{quoted} IN ({placeholders})")
                params.extend(values)
            elif value is None:
                clauses.append(f"{quoted} IS NULL")
            else:
                clauses.append(f"{quoted} = ?")
                params.append(value)

    if date_field and (start or end):
        quoted_date = _quote_identifier(date_field)
        if start:
            clauses.append(f"REPLACE(CAST({quoted_date} AS VARCHAR), '-', '') >= ?")
            params.append(start)
        if end:
            clauses.append(f"REPLACE(CAST({quoted_date} AS VARCHAR), '-', '') <= ?")
            params.append(end)

    if not clauses:
        return "", params
    return " WHERE " + " AND ".join(clauses), params
