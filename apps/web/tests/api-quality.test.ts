/**
 * Web API client tests for GET /v1/snapshots/{id}/quality (plan 09 §7).
 *
 * Runs with the Node native test runner (`node --test tests/`); Node 24
 * strips TypeScript types natively, so this file imports the real api.ts
 * sources — no build step, no test framework dependency. fetch is mocked
 * per test via node:test's `t.mock.method`, so the API contract (URL,
 * Accept header, envelope parsing, SnapshotApiError mapping) is pinned
 * without a backend.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  SnapshotApiError,
  getSnapshotQuality,
  qualityCheckRows,
  qualityLabels,
  qualityQlibStatus,
  qualityQlibWarnings,
  qualitySources,
  qualityTableRows,
  snapshotRowCounts,
  type SnapshotAssetRef,
  type SnapshotQuality
} from "../src/api.ts";

function envelope(data: unknown, status = 200): Response {
  return new Response(JSON.stringify({ success: true, data }), {
    status,
    headers: { "content-type": "application/json" }
  });
}

function errorEnvelope(code: string, message: string, status: number): Response {
  return new Response(
    JSON.stringify({ success: false, error: { code, message }, data: null }),
    { status, headers: { "content-type": "application/json" } }
  );
}

/** A payload shaped like skynet-axdata runner._quality_payload. */
const QUALITY_SAMPLE: SnapshotQuality = {
  ok: true,
  checks: [
    { check_id: "date-coverage", level: "pass", message: "input dates covered by calendar" },
    { check_id: "path-bars", level: "warning", message: "membership paths without bars: 3" }
  ],
  failures: [],
  warnings: [
    { check_id: "path-bars", level: "warning", message: "membership paths without bars: 3" }
  ],
  tables: {
    market: {
      row_count: 120,
      missing_ratio: 0,
      date_min: "2026-01-01",
      date_max: "2026-01-04",
      entity_count: 30
    },
    labels: { row_count: 90, missing_ratio: 0.0125 }
  },
  labels: { total: 90, resolved: 88, pending: 2, untradable: 0 },
  membership_to_labels_coverage: "labels cover every membership path by construction",
  calendar_version: "2026-01",
  sources: {
    "alpha/bars": { source_runs: ["run-1", "run-2"], row_count: 120 },
    "alpha/labels": { source_runs: ["run-3"], row_count: 90 }
  },
  qlib: {
    provider_uri: "qlib",
    content_hash: "0123456789abcdef",
    start_date: "2026-01-01",
    end_date: "2026-01-04",
    calendar_end: "2026-01-04",
    instrument_count: 30,
    fields: ["open", "high", "low", "close", "volume", "amount"],
    price_basis: "close",
    adjustment: "none",
    warnings: []
  }
};

// ---------------------------------------------------------------------------
// getSnapshotQuality: transport and error mapping
// ---------------------------------------------------------------------------

test("getSnapshotQuality: requests {apiBase}/v1/snapshots/{id}/quality with Accept header", async (t) => {
  const fetchMock = t.mock.method(globalThis, "fetch", async () => envelope(QUALITY_SAMPLE));
  const quality = await getSnapshotQuality("http://localhost:8000", "snap-1");

  assert.equal(fetchMock.mock.callCount(), 1);
  const [input, init] = fetchMock.mock.calls[0].arguments as [RequestInfo | URL, RequestInit | undefined];
  assert.equal(String(input), "http://localhost:8000/v1/snapshots/snap-1/quality");
  assert.equal((init?.headers as Record<string, string>)?.Accept, "application/json");
  assert.equal(quality.ok, true);
  assert.equal(quality.calendar_version, "2026-01");
});

test("getSnapshotQuality: URL-encodes the snapshot id", async (t) => {
  const fetchMock = t.mock.method(globalThis, "fetch", async () => envelope({}));
  await getSnapshotQuality("http://localhost:8000", "a/b c");
  const [input] = fetchMock.mock.calls[0].arguments as [RequestInfo | URL];
  assert.equal(String(input), "http://localhost:8000/v1/snapshots/a%2Fb%20c/quality");
});

test("getSnapshotQuality: 404 error envelope maps to SnapshotApiError", async (t) => {
  t.mock.method(globalThis, "fetch", async () =>
    errorEnvelope("SNAPSHOT_NOT_FOUND", "snapshot not found", 404)
  );
  await assert.rejects(
    getSnapshotQuality("http://localhost:8000", "missing"),
    (err: unknown) => {
      assert.ok(err instanceof SnapshotApiError);
      assert.equal(err.code, "SNAPSHOT_NOT_FOUND");
      assert.equal(err.message, "snapshot not found");
      assert.equal(err.status, 404);
      return true;
    }
  );
});

test("getSnapshotQuality: non-JSON error body falls back to HTTP code/message", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response("not found", { status: 404 }));
  await assert.rejects(
    getSnapshotQuality("http://localhost:8000", "missing"),
    (err: unknown) => {
      assert.ok(err instanceof SnapshotApiError);
      assert.equal(err.code, "HTTP_404");
      assert.equal(err.status, 404);
      return true;
    }
  );
});

test("getSnapshotQuality: malformed 2xx JSON maps to SnapshotApiError, not a raw SyntaxError", async (t) => {
  t.mock.method(globalThis, "fetch", async () =>
    new Response("<html>gateway error</html>", { status: 200 })
  );
  await assert.rejects(
    getSnapshotQuality("http://localhost:8000", "snap-1"),
    (err: unknown) => {
      assert.ok(err instanceof SnapshotApiError);
      assert.equal(err.code, "SNAPSHOT_INVALID_RESPONSE");
      assert.equal(err.status, 200);
      return true;
    }
  );
});

test("getSnapshotQuality: error envelope with success=false maps to SnapshotApiError", async (t) => {
  t.mock.method(globalThis, "fetch", async () =>
    new Response(JSON.stringify({ success: false, error: { code: "E", message: "boom" } }), {
      status: 200,
      headers: { "content-type": "application/json" }
    })
  );
  await assert.rejects(
    getSnapshotQuality("http://localhost:8000", "snap-1"),
    (err: unknown) => {
      assert.ok(err instanceof SnapshotApiError);
      assert.equal(err.code, "E");
      assert.equal(err.message, "boom");
      return true;
    }
  );
});

// ---------------------------------------------------------------------------
// Pure display mappings (quality.json -> UI rows)
// ---------------------------------------------------------------------------

test("qualityCheckRows: normalizes check list, drops malformed entries", () => {
  const rows = qualityCheckRows({
    checks: [
      { check_id: "a", level: "pass", message: "ok" },
      null,
      42,
      { level: "warning" },
      { check_id: "b", level: "failure", message: "bad" }
    ]
  } as unknown as SnapshotQuality);
  assert.deepEqual(rows, [
    { check_id: "a", level: "pass", message: "ok" },
    { check_id: "", level: "warning", message: "" },
    { check_id: "b", level: "failure", message: "bad" }
  ]);
});

test("qualityCheckRows: missing/non-array checks yields empty list", () => {
  assert.deepEqual(qualityCheckRows(null), []);
  assert.deepEqual(qualityCheckRows({}), []);
  assert.deepEqual(qualityCheckRows({ checks: "nope" } as unknown as SnapshotQuality), []);
});

test("qualityTableRows: maps row_count/missing_ratio/date range/entity count defensively", () => {
  const rows = qualityTableRows({
    tables: {
      market: { row_count: 120, missing_ratio: 0, date_min: "2026-01-01", date_max: "2026-01-04", entity_count: 30 },
      labels: { row_count: 90 },
      weird: "not-an-object"
    }
  } as unknown as SnapshotQuality);
  assert.deepEqual(rows, [
    { name: "market", row_count: 120, missing_ratio: 0, date_min: "2026-01-01", date_max: "2026-01-04", entity_count: 30 },
    { name: "labels", row_count: 90, missing_ratio: null, date_min: null, date_max: null, entity_count: null },
    { name: "weird", row_count: null, missing_ratio: null, date_min: null, date_max: null, entity_count: null }
  ]);
});

test("qualityTableRows: missing tables section yields empty list", () => {
  assert.deepEqual(qualityTableRows({ tables: QUALITY_SAMPLE.tables }), [
    { name: "market", row_count: 120, missing_ratio: 0, date_min: "2026-01-01", date_max: "2026-01-04", entity_count: 30 },
    { name: "labels", row_count: 90, missing_ratio: 0.0125, date_min: null, date_max: null, entity_count: null }
  ]);
  assert.deepEqual(qualityTableRows(null), []);
});

test("qualityLabels: passthrough with empty fallback", () => {
  assert.deepEqual(qualityLabels(QUALITY_SAMPLE), { total: 90, resolved: 88, pending: 2, untradable: 0 });
  assert.deepEqual(qualityLabels({}), {});
  assert.deepEqual(qualityLabels(null), {});
});

test("qualityQlibStatus: derives display status from qlib warnings", () => {
  assert.equal(qualityQlibStatus(QUALITY_SAMPLE), "passed");
  assert.equal(qualityQlibStatus({ qlib: { warnings: ["tail bars missing"] } } as unknown as SnapshotQuality), "warning");
  assert.equal(qualityQlibStatus({ qlib: null } as unknown as SnapshotQuality), "absent");
  assert.equal(qualityQlibStatus({}), "absent");
  assert.equal(qualityQlibStatus(null), "absent");
});

test("qualityQlibWarnings: returns string warnings only", () => {
  assert.deepEqual(qualityQlibWarnings(QUALITY_SAMPLE), []);
  const quality = { qlib: { warnings: ["a", 42, null, "b"] } } as unknown as SnapshotQuality;
  assert.deepEqual(qualityQlibWarnings(quality), ["a", "b"]);
  assert.deepEqual(qualityQlibWarnings({}), []);
});

test("qualitySources: maps source rows and sorts by dataset id", () => {
  const rows = qualitySources(QUALITY_SAMPLE);
  assert.deepEqual(rows, [
    { dataset_id: "alpha/bars", row_count: 120, run_count: 2 },
    { dataset_id: "alpha/labels", row_count: 90, run_count: 1 }
  ]);
  assert.deepEqual(qualitySources(null), []);
  assert.deepEqual(qualitySources({ sources: { d: { source_runs: "x", row_count: null } } } as unknown as SnapshotQuality), [
    { dataset_id: "d", row_count: null, run_count: 0 }
  ]);
});

test("snapshotRowCounts: aggregates per-file row counts per table (list contract)", () => {
  const counts = snapshotRowCounts({
    market: [
      { uri: "a.parquet", sha256: "x", size_bytes: 1, row_count: 100, schema_hash: "y" },
      { uri: "b.parquet", sha256: "x", size_bytes: 1, row_count: 20, schema_hash: "y" }
    ],
    labels: [],
    missing: undefined
  } as Record<string, SnapshotAssetRef[]>);
  assert.deepEqual(counts, { market: 120, labels: 0, missing: 0 });
});
