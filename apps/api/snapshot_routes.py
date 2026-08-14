"""Snapshot catalog routes (AXI-050).

Serves the read-only snapshot contract from
docs/plan/axdata-integration/05-snapshot-contract.md §6:

    GET /v1/snapshots?namespace=<namespace>
    GET /v1/snapshots/{snapshot_id}
    GET /v1/snapshots/{snapshot_id}/manifest

Snapshots are created by the Collector, not through this API (plan §6), so
there are no write routes here.

Status codes:

- 404: unknown snapshot id, or an existing directory that is not a completed
  snapshot (no ``_SUCCESS``, corrupted manifest, or path escaping the snapshot
  root) — such entries are never visible, exactly like unknown ids;
- 400: malformed namespace / snapshot_id path components;
- 503: axdata_core unavailable.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from .config import data_root
from .serialization import error_payload, response_payload, to_jsonable

router = APIRouter()


@router.get("/v1/snapshots")
def list_snapshots_route(
    namespace: str | None = Query(
        default=None,
        description="Restrict the listing to one namespace.",
    ),
) -> JSONResponse:
    try:
        from axdata_core import list_snapshots
    except ImportError:
        return _snapshot_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "CORE_UNAVAILABLE",
            "axdata_core is not available. Install the core package before listing snapshots.",
        )
    try:
        snapshots = list_snapshots(namespace=namespace, data_root=data_root())
    except ValueError as exc:
        return _snapshot_error(
            status.HTTP_400_BAD_REQUEST,
            "SNAPSHOT_INVALID_REQUEST",
            str(exc),
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=to_jsonable(
            response_payload(
                snapshots,
                count=len(snapshots),
                namespace=namespace,
            )
        ),
    )


@router.get("/v1/snapshots/{snapshot_id}")
def get_snapshot_route(snapshot_id: str) -> JSONResponse:
    try:
        from axdata_core import get_snapshot
    except ImportError:
        return _snapshot_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "CORE_UNAVAILABLE",
            "axdata_core is not available. Install the core package before reading snapshots.",
            snapshot_id=snapshot_id,
        )
    try:
        info = get_snapshot(snapshot_id, data_root=data_root())
    except ValueError as exc:
        return _snapshot_error(
            _snapshot_lookup_status(exc),
            _snapshot_lookup_code(exc),
            str(exc),
            snapshot_id=snapshot_id,
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=to_jsonable(response_payload(info)),
    )


@router.get("/v1/snapshots/{snapshot_id}/manifest")
def get_snapshot_manifest_route(snapshot_id: str) -> JSONResponse:
    try:
        from axdata_core import resolve_snapshot_manifest
    except ImportError:
        return _snapshot_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "CORE_UNAVAILABLE",
            "axdata_core is not available. Install the core package before reading snapshots.",
            snapshot_id=snapshot_id,
        )
    try:
        manifest_path = resolve_snapshot_manifest(snapshot_id, data_root=data_root())
    except ValueError as exc:
        return _snapshot_error(
            _snapshot_lookup_status(exc),
            _snapshot_lookup_code(exc),
            str(exc),
            snapshot_id=snapshot_id,
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _snapshot_error(
            status.HTTP_404_NOT_FOUND,
            "SNAPSHOT_NOT_FOUND",
            f"Cannot read snapshot manifest {manifest_path}: {exc}",
            snapshot_id=snapshot_id,
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=to_jsonable(response_payload(manifest, snapshot_id=snapshot_id)),
    )


def _snapshot_hidden(exc: ValueError) -> bool:
    """True when the error means "this snapshot must not be visible" (plan §2)."""
    message = str(exc)
    return "incomplete" in message or "corrupted" in message or "escapes" in message


def _snapshot_lookup_status(exc: ValueError) -> int:
    if isinstance(exc, LookupError) or _snapshot_hidden(exc):
        return status.HTTP_404_NOT_FOUND
    return status.HTTP_400_BAD_REQUEST


def _snapshot_lookup_code(exc: ValueError) -> str:
    if isinstance(exc, LookupError) or _snapshot_hidden(exc):
        return "SNAPSHOT_NOT_FOUND"
    return "SNAPSHOT_INVALID_REQUEST"


def _snapshot_error(
    http_status: int,
    code: str,
    message: str,
    **details: Any,
) -> JSONResponse:
    payload = error_payload(code, message, **details)
    return JSONResponse(status_code=http_status, content=to_jsonable(payload))
