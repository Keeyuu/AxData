"""Tests for the immutable research snapshot core (AXI-040).

Covers the acceptance checklist of docs/plan/axdata-integration/
05-snapshot-contract.md §9: idempotent creation without rewriting, content-hash
sensitivity to values / schema / source filters, hash stability across
created_at and data root, invisible incomplete snapshots, conflict rejection,
path traversal and symlink/junction escape rejection, manifest relocation to
another root, and hive-partitioned table writes.

Snapshot fixtures follow the plan §2 layout: a tiny deterministic ``market``
table is frozen under ``<data_root>/snapshots/skynet/<snapshot_id>/``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import pytest
from axdata_core import (
    SnapshotTableInput,
    create_snapshot,
    get_snapshot,
    list_snapshots,
    resolve_snapshot_artifact,
    resolve_snapshot_manifest,
)
from axdata_core.snapshots import (
    SnapshotConflictError,
    SnapshotError,
    SnapshotNotFoundError,
)

MARKET_ROWS = [
    {"date": "2026-01-02", "instrument_id": "600000", "return": 0.01},
    {"date": "2026-01-02", "instrument_id": "600001", "return": -0.02},
    {"date": "2026-01-03", "instrument_id": "600000", "return": 0.005},
    {"date": "2027-01-02", "instrument_id": "600000", "return": 0.03},
]

SOURCE_DATASETS = [
    {
        "dataset_id": "demo.market",
        "source_runs": ("run_demo_20260131_abcdef12",),
        "filters": {"region": "CN"},
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "observed_schema_hash": "a" * 64,
    }
]

NAMESPACE = "skynet"
DATASET_ID = "demo.market.bundle"
CALENDAR_VERSION = "2026-01-31"
QUALITY = {"status": "ok", "checks": ["required_columns", "primary_key"]}
LIMITATIONS = ("no history before 2026-01-01",)


def _market_frame(rows=None) -> pd.DataFrame:
    return pd.DataFrame(rows if rows is not None else MARKET_ROWS)


def _snapshot_kwargs(data_root, *, tables=None, source_datasets=None, **overrides):
    kwargs = dict(
        namespace=NAMESPACE,
        dataset_id=DATASET_ID,
        tables=tables if tables is not None else [SnapshotTableInput("market", _market_frame())],
        source_datasets=source_datasets if source_datasets is not None else SOURCE_DATASETS,
        calendar_version=CALENDAR_VERSION,
        data_root=data_root,
        quality=QUALITY,
        limitations=LIMITATIONS,
    )
    kwargs.update(overrides)
    return kwargs


def _manifest(snapshot_dir) -> dict:
    return json.loads((Path(snapshot_dir) / "manifest.json").read_text(encoding="utf-8"))


def _make_directory_link(link: Path, target: Path) -> bool:
    """Create a directory symlink (junction on Windows); False if forbidden."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        pass
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    return False


# ---------------------------------------------------------------------------
# §9: idempotency and content addressing
# ---------------------------------------------------------------------------


def test_create_snapshot_is_idempotent_without_rewrite(tmp_path):
    kwargs = _snapshot_kwargs(tmp_path)
    first = create_snapshot(**kwargs)
    second = create_snapshot(**kwargs)
    assert second == first
    assert first["snapshot_id"].startswith("snp_")
    assert Path(first["path"]).name == first["snapshot_id"]

    snapshot_dir = Path(first["path"])
    files_before = {str(p.relative_to(snapshot_dir)) for p in snapshot_dir.rglob("*")}
    mtimes_before = {
        str(p.relative_to(snapshot_dir)): p.stat().st_mtime_ns
        for p in snapshot_dir.rglob("*")
        if p.is_file()
    }
    create_snapshot(**kwargs)  # third call must not touch the published dir
    mtimes_after = {
        str(p.relative_to(snapshot_dir)): p.stat().st_mtime_ns
        for p in snapshot_dir.rglob("*")
        if p.is_file()
    }
    assert {str(p.relative_to(snapshot_dir)) for p in snapshot_dir.rglob("*")} == files_before
    assert mtimes_after == mtimes_before

    namespace_dir = tmp_path / "snapshots" / NAMESPACE
    assert [d.name for d in namespace_dir.iterdir()] == [first["snapshot_id"]]


def test_content_hash_changes_with_value_schema_and_source(tmp_path):
    base = create_snapshot(**_snapshot_kwargs(tmp_path))

    changed_value = dict(MARKET_ROWS[0])
    changed_value["return"] = 0.99
    rows_snapshot = create_snapshot(
        **_snapshot_kwargs(
            tmp_path,
            tables=[SnapshotTableInput("market", _market_frame([changed_value]))],
        )
    )
    assert rows_snapshot["content_hash"] != base["content_hash"]
    assert rows_snapshot["snapshot_id"] != base["snapshot_id"]

    schema_changed = _market_frame()
    schema_changed["new_column"] = 1
    schema_snapshot = create_snapshot(
        **_snapshot_kwargs(tmp_path, tables=[SnapshotTableInput("market", schema_changed)])
    )
    assert schema_snapshot["content_hash"] != base["content_hash"]

    source_snapshot = create_snapshot(
        **_snapshot_kwargs(
            tmp_path,
            source_datasets=[{**SOURCE_DATASETS[0], "filters": {"region": "US"}}],
        )
    )
    assert source_snapshot["content_hash"] != base["content_hash"]
    assert source_snapshot["snapshot_id"] != base["snapshot_id"]


def test_content_hash_stable_across_created_at_and_data_root(tmp_path, monkeypatch):
    fixed_times = iter(["2026-01-01T00:00:00+00:00", "2026-02-02T02:02:02+00:00"])
    monkeypatch.setattr("axdata_core.snapshots._utc_now", lambda: next(fixed_times))
    first = create_snapshot(**_snapshot_kwargs(tmp_path / "root_a"))
    second = create_snapshot(**_snapshot_kwargs(tmp_path / "root_b"))
    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["content_hash"] == second["content_hash"]
    assert first["created_at"] != second["created_at"]
    assert Path(first["path"]) != Path(second["path"])


# ---------------------------------------------------------------------------
# §9: visibility, conflicts
# ---------------------------------------------------------------------------


def test_incomplete_and_corrupt_snapshots_are_invisible(tmp_path):
    info = create_snapshot(**_snapshot_kwargs(tmp_path))
    namespace_dir = tmp_path / "snapshots" / NAMESPACE

    incomplete = namespace_dir / "snp_incomplete_0001"
    incomplete.mkdir()
    (incomplete / "manifest.json").write_text(json.dumps({"content_hash": "x"}), encoding="utf-8")
    corrupt = namespace_dir / "snp_corrupt_0001"
    corrupt.mkdir()
    (corrupt / "_SUCCESS").write_text("", encoding="utf-8")
    (corrupt / "manifest.json").write_text("{not json", encoding="utf-8")

    listed = list_snapshots(data_root=tmp_path)
    assert [entry["snapshot_id"] for entry in listed] == [info["snapshot_id"]]
    assert listed[0]["namespace"] == NAMESPACE

    with pytest.raises(SnapshotError, match="incomplete"):
        get_snapshot("snp_incomplete_0001", data_root=tmp_path)
    with pytest.raises(SnapshotError, match="corrupted"):
        get_snapshot("snp_corrupt_0001", data_root=tmp_path)
    with pytest.raises(SnapshotNotFoundError):
        get_snapshot("snp_nosuch_0001", data_root=tmp_path)
    with pytest.raises(SnapshotError, match="incomplete"):
        resolve_snapshot_manifest("snp_incomplete_0001", data_root=tmp_path)


def test_existing_snapshot_id_with_different_content_rejected(tmp_path):
    kwargs = _snapshot_kwargs(tmp_path)
    info = create_snapshot(**kwargs)
    snapshot_dir = Path(info["path"])
    manifest_path = snapshot_dir / "manifest.json"
    foreign = _manifest(snapshot_dir)
    foreign["content_hash"] = "f" * 64  # same id, foreign content
    manifest_path.write_text(json.dumps(foreign), encoding="utf-8")
    with pytest.raises(SnapshotConflictError, match="refusing to overwrite"):
        create_snapshot(**kwargs)


def test_list_snapshots_namespace_filter(tmp_path):
    first = create_snapshot(**_snapshot_kwargs(tmp_path))
    second = create_snapshot(**_snapshot_kwargs(tmp_path, namespace="research"))
    assert first["snapshot_id"] == second["snapshot_id"]  # namespace is not hashed

    all_infos = list_snapshots(data_root=tmp_path)
    assert {entry["namespace"] for entry in all_infos} == {NAMESPACE, "research"}
    skynet_only = list_snapshots(namespace=NAMESPACE, data_root=tmp_path)
    assert [entry["snapshot_id"] for entry in skynet_only] == [first["snapshot_id"]]
    assert list_snapshots(namespace="missing", data_root=tmp_path) == []


# ---------------------------------------------------------------------------
# §9: path safety
# ---------------------------------------------------------------------------


def test_path_traversal_and_schemes_rejected(tmp_path):
    for bad_namespace in (
        "..",
        "../x",
        "a/../b",
        "x\\..\\y",
        "s3://bucket",
        "file:///etc",
        "",
        "  ",
        "//server/share",
    ):
        with pytest.raises(SnapshotError):
            create_snapshot(**_snapshot_kwargs(tmp_path, namespace=bad_namespace))
    for bad_id in ("..", "../x", "snp_../x", "a/b", "", "s3://bucket"):
        with pytest.raises(SnapshotError):
            get_snapshot(bad_id, data_root=tmp_path)
        with pytest.raises(SnapshotError):
            resolve_snapshot_manifest(bad_id, data_root=tmp_path)


def test_namespace_symlink_escape_rejected_on_publish(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    namespace_dir = tmp_path / "snapshots" / NAMESPACE
    (tmp_path / "snapshots").mkdir()
    if not _make_directory_link(namespace_dir, outside):
        pytest.skip("symlink/junction creation is not permitted on this host")
    with pytest.raises(SnapshotError, match="escapes"):
        create_snapshot(**_snapshot_kwargs(tmp_path))


def test_snapshot_id_symlink_escape_rejected_on_publish(tmp_path):
    info = create_snapshot(**_snapshot_kwargs(tmp_path))
    snapshot_dir = Path(info["path"])
    outside = tmp_path / "outside"
    outside.mkdir()
    snapshot_dir.rename(snapshot_dir.parent / (info["snapshot_id"] + "_moved"))
    if not _make_directory_link(snapshot_dir, outside):
        pytest.skip("symlink/junction creation is not permitted on this host")
    with pytest.raises(SnapshotError, match="escapes"):
        create_snapshot(**_snapshot_kwargs(tmp_path))


def test_read_side_symlink_escape_rejected(tmp_path):
    info = create_snapshot(**_snapshot_kwargs(tmp_path))
    snapshot_dir = Path(info["path"])
    outside = tmp_path / "outside_snap"
    outside.mkdir()
    (outside / "_SUCCESS").write_text("", encoding="utf-8")
    (outside / "manifest.json").write_text(json.dumps({"content_hash": "x"}), encoding="utf-8")
    snapshot_dir.rename(snapshot_dir.parent / (info["snapshot_id"] + "_real"))
    if not _make_directory_link(snapshot_dir, outside):
        pytest.skip("symlink/junction creation is not permitted on this host")
    with pytest.raises(SnapshotError, match="escapes"):
        get_snapshot(info["snapshot_id"], data_root=tmp_path)
    with pytest.raises(SnapshotError, match="escapes"):
        resolve_snapshot_manifest(info["snapshot_id"], data_root=tmp_path)


# ---------------------------------------------------------------------------
# §9: relocation, partitioning, input kinds
# ---------------------------------------------------------------------------


def test_manifest_relocatable_to_another_root(tmp_path):
    root_a = tmp_path / "root_a"
    root_b = tmp_path / "root_b"
    info = create_snapshot(**_snapshot_kwargs(root_a))
    manifest = _manifest(info["path"])

    source_dir = Path(info["path"])
    target_dir = root_b / "snapshots" / NAMESPACE / info["snapshot_id"]
    target_dir.parent.mkdir(parents=True)
    shutil.move(str(source_dir), str(target_dir))

    moved = get_snapshot(info["snapshot_id"], data_root=root_b)
    assert moved["namespace"] == NAMESPACE
    assert moved["snapshot_id"] == info["snapshot_id"]
    assert moved["content_hash"] == info["content_hash"]
    manifest_path = resolve_snapshot_manifest(info["snapshot_id"], data_root=root_b)
    assert manifest_path == target_dir / "manifest.json"
    for refs in manifest["tables"].values():
        for ref in refs:
            assert (target_dir / ref["uri"]).is_file(), ref["uri"]
    with pytest.raises(SnapshotNotFoundError):
        get_snapshot(info["snapshot_id"], data_root=root_a)


def test_partitioned_table_written_as_hive_dirs_and_readable(tmp_path):
    frame = _market_frame()
    frame["year"] = frame["date"].str[:4]
    info = create_snapshot(
        **_snapshot_kwargs(
            tmp_path,
            tables=[SnapshotTableInput("market", frame, partition_by=("year",))],
        )
    )
    table_dir = Path(info["path"]) / "tables" / "market"
    assert sorted(p.name for p in table_dir.iterdir() if p.is_dir()) == [
        "year=2026",
        "year=2027",
    ]
    for partition_dir in table_dir.glob("year=*"):
        files = list(partition_dir.glob("part-*.parquet"))
        assert files, partition_dir
    manifest = _manifest(info["path"])
    refs = manifest["tables"]["market"]
    assert all("year=" in ref["uri"] for ref in refs)
    assert sum(ref["row_count"] for ref in refs) == len(frame)

    restored = ds.dataset(table_dir, partitioning="hive").to_table().to_pandas()
    restored["year"] = restored["year"].astype(str)  # hive partition values are type-inferred
    restored = restored[frame.columns.tolist()]
    expected = frame.sort_values(list(frame.columns)).reset_index(drop=True)
    got = restored.sort_values(list(frame.columns)).reset_index(drop=True)
    pd.testing.assert_frame_equal(got, expected, check_dtype=False)


def test_dataset_input_streamed_to_multiple_files(tmp_path):
    source_dir = tmp_path / "source_ds"
    source_dir.mkdir()
    pq.write_table(pa.Table.from_pandas(_market_frame()), source_dir / "a.parquet")
    pq.write_table(pa.Table.from_pandas(_market_frame()), source_dir / "b.parquet")
    info = create_snapshot(
        **_snapshot_kwargs(tmp_path, tables=[SnapshotTableInput("market", ds.dataset(source_dir))])
    )
    refs = _manifest(info["path"])["tables"]["market"]
    assert all(ref["uri"].startswith("tables/market/part-") for ref in refs)
    assert sum(ref["row_count"] for ref in refs) == 2 * len(MARKET_ROWS)


# ---------------------------------------------------------------------------
# Manifest contract and auxiliary files
# ---------------------------------------------------------------------------


def test_manifest_v2_fields(tmp_path):
    info = create_snapshot(**_snapshot_kwargs(tmp_path))
    manifest = _manifest(info["path"])
    assert manifest["manifest_version"] == "skynet.dataset/v2"
    assert manifest["snapshot_id"] == info["snapshot_id"]
    assert manifest["snapshot_id"].startswith("snp_")
    assert manifest["content_hash"] == info["content_hash"]
    assert len(manifest["content_hash"]) == 64
    assert all(c in "0123456789abcdef" for c in manifest["content_hash"])
    assert manifest["dataset_id"] == DATASET_ID
    assert manifest["dataset_version"] == CALENDAR_VERSION
    assert manifest["calendar_version"] == CALENDAR_VERSION
    assert manifest["created_at"] == info["created_at"]
    # aggregated from SOURCE_DATASETS[].source_runs (no explicit value given)
    assert manifest["source_runs"] == ["run_demo_20260131_abcdef12"]
    assert manifest["qlib_provider_uri"] is None
    assert manifest["quality_uri"] == "quality.json"
    assert manifest["limitations"] == list(LIMITATIONS)
    assert list(manifest["tables"]) == ["market"]
    assert manifest["source_datasets"] == json.loads(json.dumps(SOURCE_DATASETS))

    (ref,) = manifest["tables"]["market"]
    assert ref["uri"] == "tables/market/part-0.parquet"
    assert ref["row_count"] == len(MARKET_ROWS)
    assert ref["size_bytes"] > 0
    assert len(ref["sha256"]) == 64
    assert len(ref["schema_hash"]) == 64
    assert (Path(info["path"]) / ref["uri"]).is_file()


def test_qlib_provider_uri_recorded_and_validated(tmp_path):
    def _create(root: Path, **overrides) -> dict:
        return _manifest(create_snapshot(**_snapshot_kwargs(root, **overrides))["path"])

    # Default: recorded as None.
    plain = _create(tmp_path / "plain")
    assert plain["qlib_provider_uri"] is None

    # A relative path is recorded verbatim in the manifest, and the hash
    # payload is untouched by it (05 §4: qlib_provider_uri is not hashed), so
    # the two snapshots share one content hash across data roots.
    with_qlib = _create(tmp_path / "with_qlib", qlib_provider_uri="qlib")
    assert with_qlib["qlib_provider_uri"] == "qlib"
    assert with_qlib["content_hash"] == plain["content_hash"]

    for index, bad in enumerate(("", "  ", "https://host/qlib", "/abs/qlib", "a/../qlib")):
        with pytest.raises(SnapshotError):
            create_snapshot(
                **_snapshot_kwargs(tmp_path / f"bad_{index}", qlib_provider_uri=bad)
            )


def test_quality_and_extra_artifacts_written(tmp_path):
    artifact = tmp_path / "notes.txt"
    artifact.write_text("research note", encoding="utf-8")
    quality = {
        "status": "ok",
        "checks": ["required_columns", "primary_key"],
        "row_count": 4,
        "warnings": ["no PIT guarantee"],
    }
    info = create_snapshot(
        **_snapshot_kwargs(
            tmp_path,
            quality=quality,
            extra_artifacts=[artifact],
            limitations=("warning surfaced",),
        )
    )
    snapshot_dir = Path(info["path"])
    assert json.loads((snapshot_dir / "quality.json").read_text(encoding="utf-8")) == quality
    assert (snapshot_dir / "notes.txt").read_text(encoding="utf-8") == "research note"
    manifest = _manifest(snapshot_dir)
    assert manifest["quality_uri"] == "quality.json"
    assert manifest["limitations"] == ["warning surfaced"]

    with pytest.raises(SnapshotError, match="reserved"):
        reserved = tmp_path / "manifest.json"
        reserved.write_text("{}", encoding="utf-8")
        create_snapshot(**_snapshot_kwargs(tmp_path, extra_artifacts=[artifact, reserved]))
    missing = tmp_path / "missing.txt"
    with pytest.raises(SnapshotError, match="not an existing file"):
        create_snapshot(**_snapshot_kwargs(tmp_path, extra_artifacts=[missing]))


# ---------------------------------------------------------------------------
# Directory extra artifacts (runner call shape, 05 §2 / 06 §5)
# ---------------------------------------------------------------------------


def _make_qlib_style_dir(parent: Path) -> Path:
    """A Qlib-provider-shaped directory tree: calendars/instruments/features."""
    qlib = parent / "qlib"
    (qlib / "calendars").mkdir(parents=True)
    (qlib / "instruments").mkdir()
    (qlib / "features" / "600000").mkdir(parents=True)
    (qlib / "calendars" / "day.txt").write_text("2026-01-02\n2026-01-03\n", encoding="utf-8")
    (qlib / "instruments" / "all.txt").write_text("600000\t600001\n", encoding="utf-8")
    (qlib / "features" / "600000" / "open.day.bin").write_bytes(b"\x00\x01qlib-bin")
    return qlib


def test_directory_extra_artifact_published_intact(tmp_path):
    """The runner's real call shape: a nested qlib directory via extra_artifacts."""
    qlib_dir = _make_qlib_style_dir(tmp_path / "export")
    kwargs = _snapshot_kwargs(
        tmp_path, extra_artifacts=[qlib_dir], qlib_provider_uri="qlib"
    )
    info = create_snapshot(**kwargs)

    snapshot_dir = Path(info["path"])
    published = snapshot_dir / "qlib"
    assert (published / "calendars" / "day.txt").read_text(encoding="utf-8") == (
        "2026-01-02\n2026-01-03\n"
    )
    assert (published / "instruments" / "all.txt").read_text(encoding="utf-8") == (
        "600000\t600001\n"
    )
    assert (
        (published / "features" / "600000" / "open.day.bin").read_bytes() == b"\x00\x01qlib-bin"
    )
    assert _manifest(snapshot_dir)["qlib_provider_uri"] == "qlib"

    # Idempotency is unchanged: the same inputs return the existing snapshot.
    assert create_snapshot(**kwargs) == info


def test_directory_extra_artifact_never_enters_content_hash(tmp_path):
    """File artifacts never entered the hash; directory artifacts must not either."""
    qlib_dir = _make_qlib_style_dir(tmp_path / "export")
    with_artifact = create_snapshot(
        **_snapshot_kwargs(tmp_path / "root_a", extra_artifacts=[qlib_dir])
    )
    without_artifact = create_snapshot(**_snapshot_kwargs(tmp_path / "root_b"))
    assert with_artifact["snapshot_id"] == without_artifact["snapshot_id"]
    assert with_artifact["content_hash"] == without_artifact["content_hash"]


def test_directory_artifact_reserved_and_duplicate_names_rejected(tmp_path):
    reserved = tmp_path / "tables"
    reserved.mkdir()
    (reserved / "f.txt").write_text("x", encoding="utf-8")
    with pytest.raises(SnapshotError, match="reserved"):
        create_snapshot(**_snapshot_kwargs(tmp_path / "r1", extra_artifacts=[reserved]))

    first = _make_qlib_style_dir(tmp_path / "a")
    second = _make_qlib_style_dir(tmp_path / "b")
    with pytest.raises(SnapshotError, match="Duplicate"):
        create_snapshot(
            **_snapshot_kwargs(tmp_path / "r2", extra_artifacts=[first, second])
        )


def test_extra_artifact_symlinks_rejected(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    nested_root = _make_qlib_style_dir(tmp_path / "nested")
    nested_link = nested_root / "calendars" / "escape.txt"
    top_link = tmp_path / "linked_qlib"
    try:
        nested_link.symlink_to(outside)
        top_link.symlink_to(nested_root, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is not permitted on this host")
    with pytest.raises(SnapshotError, match="symbolic link"):
        create_snapshot(**_snapshot_kwargs(tmp_path / "r1", extra_artifacts=[nested_root]))
    with pytest.raises(SnapshotError, match="symbolic link"):
        create_snapshot(**_snapshot_kwargs(tmp_path / "r2", extra_artifacts=[top_link]))


# ---------------------------------------------------------------------------
# Top-level source_runs aggregation (05 §3)
# ---------------------------------------------------------------------------


def test_source_runs_aggregated_from_datasets_deduped(tmp_path):
    sources = [
        {"dataset_id": "demo.a", "source_runs": ["run_1", "run_2"]},
        {"dataset_id": "demo.b", "source_runs": ["run_2", "run_3"]},
        {"dataset_id": "demo.c"},  # no runs key at all
    ]
    info = create_snapshot(**_snapshot_kwargs(tmp_path, source_datasets=sources))
    assert info["source_runs"] == ["run_1", "run_2", "run_3"]
    assert _manifest(info["path"])["source_runs"] == ["run_1", "run_2", "run_3"]


def test_source_runs_explicit_value_wins_verbatim(tmp_path):
    sources = [{"dataset_id": "demo.a", "source_runs": ["run_1"]}]
    explicit = create_snapshot(
        **_snapshot_kwargs(
            tmp_path, source_datasets=sources, source_runs=["run_x", "run_x"]
        )
    )
    # explicit values are the caller's lineage and are kept verbatim
    assert explicit["source_runs"] == ["run_x", "run_x"]

    # an explicit empty value is "not provided": aggregation fills it in
    empty = create_snapshot(
        **_snapshot_kwargs(tmp_path / "empty", source_datasets=sources, source_runs=[])
    )
    assert empty["source_runs"] == ["run_1"]

    with pytest.raises(SnapshotError):
        create_snapshot(**_snapshot_kwargs(tmp_path / "bad", source_runs=["ok", ""]))


# ---------------------------------------------------------------------------
# Artifact resolution (shared read path of the API route and the SDK)
# ---------------------------------------------------------------------------


def test_resolve_snapshot_artifact_accepts_files_rejects_bad_paths(tmp_path):
    info = create_snapshot(**_snapshot_kwargs(tmp_path))
    snapshot_id = info["snapshot_id"]
    parquet = resolve_snapshot_artifact(
        snapshot_id, "tables/market/part-0.parquet", data_root=tmp_path
    )
    assert parquet.read_bytes() == (
        Path(info["path"]) / "tables" / "market" / "part-0.parquet"
    ).read_bytes()
    for artifact in ("quality.json", "_SUCCESS", "manifest.json"):
        assert resolve_snapshot_artifact(snapshot_id, artifact, data_root=tmp_path).is_file()

    for bad in ("../x", "a/../../b", "/abs", "C:/abs", "a//b", "a/./b", "", "  ", "file:///x"):
        with pytest.raises(SnapshotError):
            resolve_snapshot_artifact(snapshot_id, bad, data_root=tmp_path)
    with pytest.raises(SnapshotNotFoundError):
        resolve_snapshot_artifact(snapshot_id, "missing.bin", data_root=tmp_path)
    with pytest.raises(SnapshotNotFoundError):  # directories are not downloadable files
        resolve_snapshot_artifact(snapshot_id, "tables", data_root=tmp_path)
    with pytest.raises(SnapshotNotFoundError):
        resolve_snapshot_artifact("snp_nosuch_0001", "quality.json", data_root=tmp_path)
