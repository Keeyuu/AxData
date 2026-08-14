"""Tests for the SDK snapshot methods in local and API modes (AXI-050).

``AxDataClient.snapshots`` / ``snapshot`` / ``snapshot_manifest`` are exercised
in both backends. API mode uses a FastAPI TestClient as the requests session;
local mode talks directly to ``axdata_core``. The tests prove the two backends
return identical fields, hide unfinished snapshots (no ``_SUCCESS``), filter by
namespace identically, return the manifest exactly as written on disk, and
translate failures into the same :class:`axdata.AxDataError` categories.
"""

from __future__ import annotations

import json

import axdata as ax
import pytest
from axdata_core import create_snapshot, list_snapshots
from fastapi.testclient import TestClient

from apps.api.main import app
from tests.test_snapshots import (
    NAMESPACE,
    _snapshot_kwargs,
)

DATA_ROOT = "data"


class NoHttpSession:
    def get(self, *args, **kwargs):
        raise AssertionError("local SDK backend must not issue HTTP GET requests")

    def post(self, *args, **kwargs):
        raise AssertionError("local SDK backend must not issue HTTP POST requests")


@pytest.fixture
def api_session(tmp_path, monkeypatch):
    monkeypatch.setenv("AXDATA_DATA_DIR", str(tmp_path / DATA_ROOT))
    return TestClient(app)


def _data_root(tmp_path):
    return tmp_path / DATA_ROOT


def _local_client(root):
    return ax.AxDataClient(data_root=root, session=NoHttpSession())


def _api_client(api_session):
    return ax.AxDataClient(api_base="http://testserver", session=api_session)


def _two_snapshots(root):
    first = create_snapshot(**_snapshot_kwargs(root))
    second = create_snapshot(**_snapshot_kwargs(root, calendar_version="2026-02-28"))
    return first, second


def test_sdk_snapshots_local_matches_core_listing(tmp_path) -> None:
    root = _data_root(tmp_path)
    _two_snapshots(root)

    sdk = _local_client(root).snapshots()
    core = list_snapshots(data_root=root)

    assert sdk == core
    assert len(sdk) == 2


def test_sdk_snapshots_api_matches_local_field_by_field(tmp_path, api_session) -> None:
    root = _data_root(tmp_path)
    first, second = _two_snapshots(root)
    local = _local_client(root)
    api = _api_client(api_session)

    local_listing = local.snapshots()
    api_listing = api.snapshots()

    assert api_listing == local_listing
    assert {entry["snapshot_id"] for entry in api_listing} == {
        first["snapshot_id"],
        second["snapshot_id"],
    }
    assert api_listing[0]["namespace"] == NAMESPACE
    assert api_listing[0]["manifest_version"] == "skynet.dataset/v2"


def test_sdk_snapshot_detail_matches_creation_both_modes(tmp_path, api_session) -> None:
    root = _data_root(tmp_path)
    info = create_snapshot(**_snapshot_kwargs(root))
    local = _local_client(root)
    api = _api_client(api_session)

    local_detail = local.snapshot(info["snapshot_id"])
    api_detail = api.snapshot(info["snapshot_id"])

    assert local_detail == info
    assert api_detail == local_detail


def test_sdk_snapshots_namespace_filter_both_modes(tmp_path, api_session) -> None:
    root = _data_root(tmp_path)
    first = create_snapshot(**_snapshot_kwargs(root))
    other = create_snapshot(**_snapshot_kwargs(root, namespace="research"))
    local = _local_client(root)
    api = _api_client(api_session)

    local_skynet = local.snapshots(namespace=NAMESPACE)
    api_skynet = api.snapshots(namespace=NAMESPACE)
    assert local_skynet == api_skynet
    assert [entry["snapshot_id"] for entry in api_skynet] == [first["snapshot_id"]]

    local_other = local.snapshots(namespace="research")
    api_other = api.snapshots(namespace="research")
    assert api_other == local_other
    assert [entry["snapshot_id"] for entry in api_other] == [other["snapshot_id"]]

    assert api.snapshots(namespace="no.such") == []
    assert local.snapshots(namespace="no.such") == []


def test_sdk_snapshot_unknown_id_same_error_both_modes(tmp_path, api_session) -> None:
    root = _data_root(tmp_path)
    _two_snapshots(root)
    local = _local_client(root)
    api = _api_client(api_session)

    for client in (local, api):
        with pytest.raises(ax.AxDataError) as exc_info:
            client.snapshot("snp_nosuch_0001")
        assert exc_info.value.status_code == 404
        assert exc_info.value.code == "SNAPSHOT_NOT_FOUND"

        with pytest.raises(ax.AxDataError) as exc_info:
            client.snapshot_manifest("snp_nosuch_0001")
        assert exc_info.value.status_code == 404
        assert exc_info.value.code == "SNAPSHOT_NOT_FOUND"


def test_sdk_snapshot_requires_id(tmp_path) -> None:
    local = _local_client(_data_root(tmp_path))
    with pytest.raises(ValueError, match="snapshot_id is required"):
        local.snapshot("")
    with pytest.raises(ValueError, match="snapshot_id is required"):
        local.snapshot_manifest(None)


def test_sdk_snapshot_incomplete_is_hidden_both_modes(tmp_path, api_session) -> None:
    root = _data_root(tmp_path)
    info = create_snapshot(**_snapshot_kwargs(root))
    namespace_dir = root / "snapshots" / NAMESPACE
    incomplete = namespace_dir / "snp_incomplete_0001"
    incomplete.mkdir()
    (incomplete / "manifest.json").write_text(json.dumps({"content_hash": "x"}), encoding="utf-8")
    local = _local_client(root)
    api = _api_client(api_session)

    assert [entry["snapshot_id"] for entry in api.snapshots()] == [info["snapshot_id"]]
    assert [entry["snapshot_id"] for entry in local.snapshots()] == [info["snapshot_id"]]

    for client in (local, api):
        with pytest.raises(ax.AxDataError) as exc_info:
            client.snapshot("snp_incomplete_0001")
        assert exc_info.value.status_code == 404
        assert exc_info.value.code == "SNAPSHOT_NOT_FOUND"


def test_sdk_snapshot_manifest_matches_disk_both_modes(tmp_path, api_session) -> None:
    root = _data_root(tmp_path)
    info = create_snapshot(**_snapshot_kwargs(root))
    disk_manifest = json.loads(
        (root / "snapshots" / NAMESPACE / info["snapshot_id"] / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    local = _local_client(root)
    api = _api_client(api_session)

    assert local.snapshot_manifest(info["snapshot_id"]) == disk_manifest
    assert api.snapshot_manifest(info["snapshot_id"]) == disk_manifest
    assert api.snapshot_manifest(info["snapshot_id"]) == local.snapshot_manifest(
        info["snapshot_id"]
    )
