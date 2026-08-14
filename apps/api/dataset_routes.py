"""Dynamic dataset query routes (AXI-030).

Serves the generic dataset query contract from
docs/plan/axdata-integration/04-axdata-core-contracts.md §6:

    POST /v1/data/datasets/{dataset_id}/query

The catalog listing and inspection GET routes live in ``data_routes.py`` and
keep serving the Web Data Browser summary payloads.

Status codes:

- 404: dataset or its output files do not exist;
- 400: unknown fields/filters, invalid dates/limits, catalog conflicts;
- 413: explicit limit above the server AXDATA_API_MAX_QUERY_ROWS cap;
- 503: DuckDB / axdata_core unavailable.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from .config import data_root
from .models import DatasetQueryRequest
from .serialization import error_payload, response_payload, to_jsonable

router = APIRouter()

DEFAULT_API_MAX_QUERY_ROWS = 100000
API_MAX_QUERY_ROWS_ENV = "AXDATA_API_MAX_QUERY_ROWS"


def api_max_query_rows() -> int:
    """Server-side query cap, from ``AXDATA_API_MAX_QUERY_ROWS`` (default 100000)."""

    try:
        value = int(os.getenv(API_MAX_QUERY_ROWS_ENV, str(DEFAULT_API_MAX_QUERY_ROWS)))
    except (TypeError, ValueError):
        return DEFAULT_API_MAX_QUERY_ROWS
    return value if value > 0 else DEFAULT_API_MAX_QUERY_ROWS


@router.post("/v1/data/datasets/{dataset_id}/query")
def query_local_dataset(dataset_id: str, request: DatasetQueryRequest) -> JSONResponse:
    try:
        from axdata_core import (
            DatasetCatalogError,
            DatasetNotFoundError,
            DatasetQueryError,
            query_dataset,
        )
    except ImportError:
        return _dataset_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "CORE_UNAVAILABLE",
            "axdata_core is not available. Install the core package before querying datasets.",
            dataset_id=dataset_id,
        )

    cap = api_max_query_rows()
    requested_limit = request.limit
    if requested_limit is not None and requested_limit > cap:
        return _dataset_error(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "QUERY_LIMIT_EXCEEDED",
            (
                f"Requested limit {requested_limit} exceeds the API maximum of {cap} rows. "
                "Use snapshot exports for large-scale research instead of the JSON API."
            ),
            dataset_id=dataset_id,
            requested_limit=requested_limit,
            max_limit=cap,
        )

    # Probe one row past the cap so truncated=true is exact, not ambiguous.
    probe_limit = requested_limit if requested_limit is not None else cap + 1
    try:
        df = query_dataset(
            dataset_id,
            data_root=data_root(),
            fields=request.fields,
            filters=request.filters or None,
            start_date=request.start_date,
            end_date=request.end_date,
            limit=probe_limit,
        )
    except (DatasetNotFoundError, FileNotFoundError) as exc:
        return _dataset_error(
            status.HTTP_404_NOT_FOUND,
            "DATASET_NOT_FOUND",
            str(exc),
            dataset_id=dataset_id,
        )
    except (DatasetQueryError, DatasetCatalogError, ValueError) as exc:
        return _dataset_error(
            status.HTTP_400_BAD_REQUEST,
            "DATASET_QUERY_ERROR",
            str(exc),
            dataset_id=dataset_id,
        )
    except ImportError:
        return _dataset_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "CORE_UNAVAILABLE",
            "DuckDB is not available. Install the core package before querying datasets.",
            dataset_id=dataset_id,
        )

    truncated = False
    if requested_limit is None and len(df) > cap:
        truncated = True
        df = df.iloc[:cap]
    records = df.to_dict(orient="records")
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=to_jsonable(
            response_payload(
                records,
                dataset=dataset_id,
                count=len(records),
                limit=requested_limit if requested_limit is not None else cap,
                truncated=truncated,
                columns=list(df.columns),
            )
        ),
    )


def _dataset_error(
    http_status: int,
    code: str,
    message: str,
    **details: Any,
) -> JSONResponse:
    payload = error_payload(code, message, **details)
    return JSONResponse(status_code=http_status, content=to_jsonable(payload))
