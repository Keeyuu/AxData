/**
 * API client helpers.
 *
 * `apiFetch` is the shared fetch wrapper; the snapshot helpers below map the
 * read-only snapshot contract from apps/api/snapshot_routes.py (AXI-050) into
 * typed values. The backend is the source of truth: hash/schema/quality are
 * never recomputed here (plan 09 §5), only aggregated per-file row counts and
 * presence checks.
 */

export function apiFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  return fetch(input, init);
}

// ---------------------------------------------------------------------------
// Snapshot types (plan 09 §5, mapped to the actual AXI-050 payload)
// ---------------------------------------------------------------------------

export type SnapshotQualityStatus = "passed" | "warning";

export type SnapshotAssetRef = {
  uri: string;
  sha256: string;
  size_bytes: number;
  row_count: number;
  schema_hash: string;
};

export type SnapshotSourceDatasetRef = {
  dataset_id: string;
  source_runs: string[];
  fields: string[];
  filters: Record<string, unknown>;
  start_date: string | null;
  end_date: string | null;
  observed_schema_hash: string;
};

/** manifest.json as written by axdata_core.create_snapshot (plan 05 §3). */
export type SnapshotManifestV2 = {
  manifest_version: "skynet.dataset/v2";
  snapshot_id: string;
  dataset_id: string;
  dataset_version: string;
  content_hash: string;
  calendar_version: string;
  created_at: string;
  tables: Record<string, SnapshotAssetRef[]>;
  source_datasets: SnapshotSourceDatasetRef[];
  source_runs: string[];
  qlib_provider_uri: string | null;
  quality_uri: string;
  limitations: string[];
};

/**
 * One snapshot as served by GET /v1/snapshots and GET /v1/snapshots/{id}.
 *
 * Plan 09 §5 asked for `row_counts`, `has_qlib` and `quality_status` on the
 * payload; the backend serves the manifest plus `namespace`/`path` instead,
 * so the three derived fields are computed here from backend facts (per-file
 * row counts, `qlib_provider_uri` presence, and limitations carrying quality
 * warnings per plan 05 §7) — see the mapping table in the AXI-110 report.
 */
export type SnapshotSummary = SnapshotManifestV2 & {
  namespace: string;
  path: string;
  row_counts: Record<string, number>;
  has_qlib: boolean;
  quality_status: SnapshotQualityStatus;
};

export type SnapshotApiErrorPayload = {
  success: false;
  error: { code: string; message: string };
  meta?: Record<string, unknown>;
};

export type SnapshotEnvelope<T> = {
  success: true;
  data: T;
  meta?: Record<string, unknown>;
};

// ---------------------------------------------------------------------------
// Pure mapping helpers (unit-testable without a server)
// ---------------------------------------------------------------------------

export function snapshotRowCounts(tables: Record<string, SnapshotAssetRef[]>): Record<string, number> {
  return Object.fromEntries(
    Object.entries(tables).map(([name, refs]) => [
      name,
      (refs ?? []).reduce((sum, ref) => sum + Number(ref.row_count || 0), 0),
    ])
  );
}

/**
 * Derive the list/detail quality status from manifest `limitations`.
 *
 * The backend has no `quality_status` field; per plan 05 §7 quality warnings
 * must be surfaced in manifest `limitations`, so a non-empty limitations list
 * is rendered as "warning" and an empty one as "passed". quality.json itself
 * is not served through the Web API.
 */
export function snapshotQualityStatus(limitations: string[]): SnapshotQualityStatus {
  return Array.isArray(limitations) && limitations.length > 0 ? "warning" : "passed";
}

export function snapshotHasQlib(qlibProviderUri: string | null | undefined): boolean {
  return Boolean(qlibProviderUri && String(qlibProviderUri).trim());
}

/** Total run ids recorded on the manifest and on each source dataset entry. */
export function snapshotSourceRunCount(snapshot: SnapshotManifestV2): number {
  const manifestRuns = Array.isArray(snapshot.source_runs) ? snapshot.source_runs.length : 0;
  const sourceRuns = (snapshot.source_datasets ?? []).reduce(
    (sum, entry) => sum + (Array.isArray(entry.source_runs) ? entry.source_runs.length : 0),
    0
  );
  return manifestRuns + sourceRuns;
}

/**
 * Date span covered by the snapshot, aggregated from source dataset
 * start/end dates (min start - max end); falls back to the calendar version.
 */
export function snapshotDateRange(snapshot: SnapshotManifestV2): string {
  const dates: string[] = [];
  for (const entry of snapshot.source_datasets ?? []) {
    if (entry.start_date) dates.push(String(entry.start_date));
    if (entry.end_date) dates.push(String(entry.end_date));
  }
  if (dates.length > 0) {
    const sorted = [...dates].sort();
    const start = sorted[0];
    const end = sorted[sorted.length - 1];
    return start === end ? start : `${start} - ${end}`;
  }
  return snapshot.calendar_version || "";
}

export function snapshotUri(snapshotId: string): string {
  return `axdata://snapshot/${snapshotId}`;
}

export function mapSnapshotSummary(raw: SnapshotManifestV2 & { namespace?: string; path?: string }): SnapshotSummary {
  const tables = raw.tables ?? {};
  return {
    ...raw,
    namespace: raw.namespace ?? "",
    path: raw.path ?? "",
    row_counts: snapshotRowCounts(tables),
    has_qlib: snapshotHasQlib(raw.qlib_provider_uri),
    quality_status: snapshotQualityStatus(raw.limitations),
  };
}

// ---------------------------------------------------------------------------
// API calls (AXI-050 routes)
// ---------------------------------------------------------------------------

export class SnapshotApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "SnapshotApiError";
    this.code = code;
    this.status = status;
  }
}

async function parseErrorPayload(response: Response): Promise<SnapshotApiError> {
  let code = `HTTP_${response.status}`;
  let message = `HTTP ${response.status}`;
  try {
    const payload = (await response.json()) as SnapshotApiErrorPayload & { detail?: string };
    if (payload?.error?.code && payload?.error?.message) {
      code = payload.error.code;
      message = payload.error.message;
    } else if (typeof payload?.detail === "string") {
      message = payload.detail;
    }
  } catch {
    // Non-JSON error body; keep the HTTP fallback.
  }
  return new SnapshotApiError(code, message, response.status);
}

async function readEnvelope<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw await parseErrorPayload(response);
  }
  const payload = (await response.json()) as {
    success?: boolean;
    data?: unknown;
    error?: { code?: string; message?: string };
  };
  if (payload?.success === false || payload?.data === undefined) {
    throw new SnapshotApiError(
      payload?.error?.code ?? "SNAPSHOT_INVALID_RESPONSE",
      payload?.error?.message ?? "快照 API 返回了无法识别的响应",
      response.status
    );
  }
  return payload.data as T;
}

export type ListSnapshotsOptions = {
  signal?: AbortSignal;
  namespace?: string;
};

export async function listSnapshots(apiBase: string, options: ListSnapshotsOptions = {}): Promise<SnapshotSummary[]> {
  const params = new URLSearchParams();
  if (options.namespace) {
    params.set("namespace", options.namespace);
  }
  const query = params.toString();
  const response = await apiFetch(`${apiBase}/v1/snapshots${query ? `?${query}` : ""}`, {
    signal: options.signal,
    headers: { Accept: "application/json" },
  });
  const raw = await readEnvelope<Array<Partial<SnapshotManifestV2> & { namespace?: string; path?: string }>>(response);
  return (Array.isArray(raw) ? raw : []).map((entry) =>
    mapSnapshotSummary(entry as SnapshotManifestV2)
  );
}

export async function getSnapshot(apiBase: string, snapshotId: string, signal?: AbortSignal): Promise<SnapshotSummary> {
  const response = await apiFetch(
    `${apiBase}/v1/snapshots/${encodeURIComponent(snapshotId)}`,
    { signal, headers: { Accept: "application/json" } }
  );
  const raw = await readEnvelope<Partial<SnapshotManifestV2>>(response);
  return mapSnapshotSummary(raw as SnapshotManifestV2);
}

export async function getSnapshotManifest(apiBase: string, snapshotId: string, signal?: AbortSignal): Promise<SnapshotManifestV2> {
  const response = await apiFetch(
    `${apiBase}/v1/snapshots/${encodeURIComponent(snapshotId)}/manifest`,
    { signal, headers: { Accept: "application/json" } }
  );
  return readEnvelope<SnapshotManifestV2>(response);
}
