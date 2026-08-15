"""Tests for the snapshot catalog API routes (AXI-050).

Covers the read-only snapshot contract from docs/plan/axdata-integration/
05-snapshot-contract.md §6:

    GET /v1/snapshots?namespace=<namespace>
    GET /v1/snapshots/{snapshot_id}
    GET /v1/snapshots/{snapshot_id}/manifest

Snapshots are created through ``axdata_core.create_snapshot`` (the API has no
write route). Incomplete directories (no ``_SUCCESS``) are never returned,
unknown ids respond 404 ``SNAPSHOT_NOT_FOUND``, and the manifest route
returns exactly the manifest.json written on disk.
"""

from __future__ import annotations

import json

import pytest
from axdata_core import create_snapshot
from fastapi.testclient import TestClient

from apps.api.main import app
from tests.test_snapshots import (
    NAMESPACE,
    _make_qlib_style_dir,
    _snapshot_kwargs,
)

DATA_ROOT = "data"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AXDATA_DATA_DIR", str(tmp_path / DATA_ROOT))
    return TestClient(app)


def _data_root(tmp_path):
    return tmp_path / DATA_ROOT


def _create_two_snapshots(data_root):
    """Two content-distinct snapshots plus one in another namespace."""
    first = create_snapshot(**_snapshot_kwargs(data_root))
    second = create_snapshot(**_snapshot_kwargs(data_root, calendar_version="2026-02-28"))
    other = create_snapshot(**_snapshot_kwargs(data_root, namespace="research"))
    return first, second, other


def test_snapshot_list_returns_created_snapshots(client, tmp_path) -> None:
    first, second, other = _create_two_snapshots(_data_root(tmp_path))

    response = client.get("/v1/snapshots")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    listed = payload["data"]
    assert len(listed) == 3
    assert payload["meta"]["count"] == 3
    by_key = {(entry["namespace"], entry["snapshot_id"]): entry for entry in listed}
    expected = {
        (first["namespace"], first["snapshot_id"]): first,
        (second["namespace"], second["snapshot_id"]): second,
        (other["namespace"], other["snapshot_id"]): other,
    }
    assert by_key == expected


def test_snapshot_list_namespace_filter(client, tmp_path) -> None:
    first, second, other = _create_two_snapshots(_data_root(tmp_path))

    skynet = client.get(f"/v1/snapshots?namespace={NAMESPACE}")
    assert skynet.status_code == 200
    assert {entry["snapshot_id"] for entry in skynet.json()["data"]} == {
        first["snapshot_id"],
        second["snapshot_id"],
    }

    research = client.get("/v1/snapshots?namespace=research")
    assert research.status_code == 200
    assert [entry["snapshot_id"] for entry in research.json()["data"]] == [other["snapshot_id"]]

    missing = client.get("/v1/snapshots?namespace=no.such")
    assert missing.status_code == 200
    assert missing.json()["data"] == []
    assert missing.json()["meta"]["count"] == 0


def test_snapshot_list_hides_incomplete_directories(client, tmp_path) -> None:
    info = create_snapshot(**_snapshot_kwargs(_data_root(tmp_path)))
    namespace_dir = _data_root(tmp_path) / "snapshots" / NAMESPACE
    incomplete = namespace_dir / "snp_incomplete_0001"
    incomplete.mkdir()
    (incomplete / "manifest.json").write_text(json.dumps({"content_hash": "x"}), encoding="utf-8")

    response = client.get("/v1/snapshots")

    assert response.status_code == 200
    assert [entry["snapshot_id"] for entry in response.json()["data"]] == [info["snapshot_id"]]


def test_snapshot_get_returns_full_info(client, tmp_path) -> None:
    info = create_snapshot(**_snapshot_kwargs(_data_root(tmp_path)))

    response = client.get(f"/v1/snapshots/{info['snapshot_id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"] == info


def test_snapshot_get_unknown_id_returns_404(client, tmp_path) -> None:
    create_snapshot(**_snapshot_kwargs(_data_root(tmp_path)))

    response = client.get("/v1/snapshots/snp_nosuch_0001")

    assert response.status_code == 404
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "SNAPSHOT_NOT_FOUND"
    assert "snp_nosuch_0001" in payload["error"]["message"]


def test_snapshot_get_incomplete_directory_returns_404(client, tmp_path) -> None:
    namespace_dir = _data_root(tmp_path) / "snapshots" / NAMESPACE
    incomplete = namespace_dir / "snp_incomplete_0001"
    incomplete.mkdir(parents=True)
    (incomplete / "manifest.json").write_text(json.dumps({"content_hash": "x"}), encoding="utf-8")

    response = client.get("/v1/snapshots/snp_incomplete_0001")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SNAPSHOT_NOT_FOUND"


def test_snapshot_list_invalid_namespace_returns_400(client, tmp_path) -> None:
    create_snapshot(**_snapshot_kwargs(_data_root(tmp_path)))

    response = client.get("/v1/snapshots?namespace=../x")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SNAPSHOT_INVALID_REQUEST"


def test_snapshot_manifest_route_matches_disk(client, tmp_path) -> None:
    info = create_snapshot(**_snapshot_kwargs(_data_root(tmp_path)))
    disk_manifest = json.loads(
        (
            tmp_path / DATA_ROOT / "snapshots" / NAMESPACE / info["snapshot_id"] / "manifest.json"
        ).read_text(encoding="utf-8")
    )

    response = client.get(f"/v1/snapshots/{info['snapshot_id']}/manifest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"] == disk_manifest
    assert payload["data"]["manifest_version"] == "skynet.dataset/v2"


def test_snapshot_manifest_unknown_id_returns_404(client, tmp_path) -> None:
    response = client.get("/v1/snapshots/snp_nosuch_0001/manifest")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SNAPSHOT_NOT_FOUND"


def test_snapshot_manifest_incomplete_returns_404(client, tmp_path) -> None:
    namespace_dir = _data_root(tmp_path) / "snapshots" / NAMESPACE
    incomplete = namespace_dir / "snp_incomplete_0001"
    incomplete.mkdir(parents=True)
    (incomplete / "manifest.json").write_text(json.dumps({"content_hash": "x"}), encoding="utf-8")

    response = client.get("/v1/snapshots/snp_incomplete_0001/manifest")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SNAPSHOT_NOT_FOUND"


# ---------------------------------------------------------------------------
# GET /v1/snapshots/{snapshot_id}/quality
# ---------------------------------------------------------------------------


def test_snapshot_quality_route_matches_disk(client, tmp_path) -> None:
    info = create_snapshot(**_snapshot_kwargs(_data_root(tmp_path)))
    disk_quality = json.loads(
        (
            tmp_path / DATA_ROOT / "snapshots" / NAMESPACE / info["snapshot_id"] / "quality.json"
        ).read_text(encoding="utf-8")
    )

    response = client.get(f"/v1/snapshots/{info['snapshot_id']}/quality")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"] == disk_quality


def test_snapshot_quality_unknown_and_incomplete_return_404(client, tmp_path) -> None:
    namespace_dir = _data_root(tmp_path) / "snapshots" / NAMESPACE
    incomplete = namespace_dir / "snp_incomplete_0001"
    incomplete.mkdir(parents=True)
    (incomplete / "manifest.json").write_text(json.dumps({"content_hash": "x"}), encoding="utf-8")

    for snapshot_id in ("snp_nosuch_0001", "snp_incomplete_0001"):
        response = client.get(f"/v1/snapshots/{snapshot_id}/quality")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "SNAPSHOT_NOT_FOUND"


# ---------------------------------------------------------------------------
# GET /v1/snapshots/{snapshot_id}/artifact/{artifact_path}
# ---------------------------------------------------------------------------


def test_snapshot_artifact_route_serves_registered_files(client, tmp_path) -> None:
    info = create_snapshot(**_snapshot_kwargs(_data_root(tmp_path)))
    snapshot_dir = tmp_path / DATA_ROOT / "snapshots" / NAMESPACE / info["snapshot_id"]

    for uri in ("tables/market/part-0.parquet", "quality.json", "manifest.json", "_SUCCESS"):
        response = client.get(f"/v1/snapshots/{info['snapshot_id']}/artifact/{uri}")
        assert response.status_code == 200, uri
        assert response.content == (snapshot_dir / uri).read_bytes()


def test_snapshot_artifact_route_serves_directory_artifact_files(client, tmp_path) -> None:
    qlib_dir = _make_qlib_style_dir(tmp_path / "export")
    info = create_snapshot(
        **_snapshot_kwargs(
            _data_root(tmp_path), extra_artifacts=[qlib_dir], qlib_provider_uri="qlib"
        )
    )
    snapshot_dir = tmp_path / DATA_ROOT / "snapshots" / NAMESPACE / info["snapshot_id"]

    response = client.get(
        f"/v1/snapshots/{info['snapshot_id']}/artifact/qlib/features/600000/open.day.bin"
    )

    assert response.status_code == 200
    assert response.content == b"\x00\x01qlib-bin"
    assert response.content == (
        snapshot_dir / "qlib" / "features" / "600000" / "open.day.bin"
    ).read_bytes()


def test_snapshot_artifact_route_rejects_traversal(client, tmp_path) -> None:
    info = create_snapshot(**_snapshot_kwargs(_data_root(tmp_path)))

    # Literal dot segments are stripped by HTTP clients before the request is
    # sent, so every "." is percent-encoded — the route must still reject the
    # decoded path (and would equally reject a raw socket-level attempt).
    for bad in (
        "%2e%2e/secret",
        "tables/%2e%2e/%2e%2e/manifest.json",
        "%2e%2e%5csecret",
        "a/%2e/b",
        "/abs",
        "a//b",
    ):
        response = client.get(f"/v1/snapshots/{info['snapshot_id']}/artifact/{bad}")
        assert response.status_code == 400, bad
        assert response.json()["error"]["code"] == "SNAPSHOT_INVALID_REQUEST"


def test_snapshot_artifact_route_missing_and_incomplete_return_404(client, tmp_path) -> None:
    info = create_snapshot(**_snapshot_kwargs(_data_root(tmp_path)))
    namespace_dir = _data_root(tmp_path) / "snapshots" / NAMESPACE
    incomplete = namespace_dir / "snp_incomplete_0001"
    incomplete.mkdir(parents=True)
    (incomplete / "manifest.json").write_text(json.dumps({"content_hash": "x"}), encoding="utf-8")

    # missing files and whole directories are 404, never a listing
    for uri in ("missing.bin", "tables", "tables/market"):
        response = client.get(f"/v1/snapshots/{info['snapshot_id']}/artifact/{uri}")
        assert response.status_code == 404, uri
        assert response.json()["error"]["code"] == "SNAPSHOT_NOT_FOUND"

    response = client.get("/v1/snapshots/snp_incomplete_0001/artifact/manifest.json")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SNAPSHOT_NOT_FOUND"
