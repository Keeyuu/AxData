import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Archive,
  CheckCircle2,
  Copy,
  Database,
  FileJson,
  GitBranch,
  Link2,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Table2
} from "lucide-react";

import {
  SnapshotApiError,
  getSnapshot,
  listSnapshots,
  snapshotDateRange,
  snapshotSourceRunCount,
  snapshotUri,
  type SnapshotSourceDatasetRef,
  type SnapshotSummary
} from "../api";
import { DataTable, Metric } from "../components/common";
import type { TableRow } from "../types";

const CORE_TABLE_NAMES = ["market", "track", "membership", "instrument", "labels"];

export function SnapshotsPage({
  apiBase,
  onOpenDataBrowser
}: {
  apiBase: string;
  onOpenDataBrowser?: () => void;
}) {
  const [snapshots, setSnapshots] = useState<SnapshotSummary[]>([]);
  const [activeSnapshotId, setActiveSnapshotId] = useState(initialSnapshotIdFromUrl());
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<SnapshotApiError | null>(null);

  const activeSnapshot = useMemo(
    () => snapshots.find((item) => item.snapshot_id === activeSnapshotId) ?? null,
    [activeSnapshotId, snapshots]
  );

  const loadSnapshots = useCallback(async (signal?: AbortSignal) => {
    setIsLoading(true);
    setError(null);
    try {
      const rows = await listSnapshots(apiBase, { signal });
      setSnapshots(rows);
      setActiveSnapshotId((current) =>
        current && rows.some((item) => item.snapshot_id === current) ? current : (rows[0]?.snapshot_id ?? "")
      );
    } catch (loadError) {
      if (!signal?.aborted) {
        setSnapshots([]);
        setActiveSnapshotId("");
        setError(loadError instanceof Error ? loadError.message : "快照读取失败");
      }
    } finally {
      if (!signal?.aborted) {
        setIsLoading(false);
      }
    }
  }, [apiBase]);

  useEffect(() => {
    const controller = new AbortController();
    loadSnapshots(controller.signal);
    return () => controller.abort();
  }, [loadSnapshots]);

  useEffect(() => {
    if (!activeSnapshotId) {
      setDetailError(null);
      return;
    }
    const controller = new AbortController();
    setDetailError(null);
    getSnapshot(apiBase, activeSnapshotId, controller.signal)
      .then((fresh) => {
        if (!controller.signal.aborted) {
          setSnapshots((current) =>
            current.some((item) => item.snapshot_id === fresh.snapshot_id)
              ? current.map((item) => (item.snapshot_id === fresh.snapshot_id ? fresh : item))
              : [fresh, ...current]
          );
        }
      })
      .catch((detailFailure: unknown) => {
        if (!controller.signal.aborted) {
          setDetailError(detailFailure instanceof SnapshotApiError ? detailFailure : null);
        }
      });
    return () => controller.abort();
  }, [activeSnapshotId, apiBase]);

  function selectSnapshot(snapshotId: string) {
    setActiveSnapshotId(snapshotId);
    syncSnapshotRoute(snapshotId);
  }

  const showEmptyState = !isLoading && !error && snapshots.length === 0;
  const totalRows = snapshots.reduce(
    (sum, item) => sum + Object.values(item.row_counts).reduce((tableSum, count) => tableSum + count, 0),
    0
  );

  return (
    <>
      <section className="doc-hero single">
        <div className="doc-heading">
          <div className="endpoint-line">
            <span className="section-eyebrow">研究快照</span>
            <span className="ready-badge">
              <Archive size={15} />
              只读，由采集任务生成
            </span>
          </div>
          <div className="title-row">
            <span className="title-icon">
              <Archive size={26} />
            </span>
            <h1>快照</h1>
          </div>
          <p>冻结的研究数据 bundle（manifest v2），可复制 axdata://snapshot/&lt;id&gt; 在 Skynet 中加载。</p>
          <div className="metrics-row">
            <Metric icon={Archive} label="快照" value={String(snapshots.length)} />
            <Metric icon={Table2} label="总行数" value={totalRows ? totalRows.toLocaleString("zh-CN") : "0"} />
            <Metric
              icon={CheckCircle2}
              label="含 Qlib"
              value={String(snapshots.filter((item) => item.has_qlib).length)}
            />
            <Metric
              icon={AlertCircle}
              label="含提醒"
              value={String(snapshots.filter((item) => item.quality_status === "warning").length)}
            />
          </div>
        </div>
      </section>

      <section className={`data-browser-layout${showEmptyState ? " empty" : ""}`}>
        {showEmptyState ? (
          <div className="data-browser-empty-state">
            <div>
              <span className="empty-state-icon">
                <Archive size={24} />
              </span>
              <h2>还没有研究快照</h2>
              <p>安装并启用 skynet-axdata 插件后，在「采集」页面运行 skynet.research.snapshot 任务。</p>
              <p>快照生成后，这里会显示快照列表、五表行数、质量状态和 axdata:// 复制入口。</p>
            </div>
            <div className="empty-state-actions">
              <button className="ghost-action" disabled={isLoading} onClick={() => loadSnapshots()} type="button">
                {isLoading ? <Loader2 size={16} /> : <RefreshCw size={16} />}
                刷新
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="dataset-list-panel">
              <div className="section-title compact-title">
                <Archive size={19} />
                <h2>快照目录</h2>
                <button className="ghost-action compact" disabled={isLoading} onClick={() => loadSnapshots()} type="button">
                  {isLoading ? <Loader2 size={15} /> : <RefreshCw size={15} />}
                  刷新
                </button>
              </div>
              {error ? (
                <div className="data-browser-message error">
                  <AlertCircle size={17} />
                  <span>{error}</span>
                  <button className="ghost-action compact" onClick={() => loadSnapshots()} type="button">
                    重试
                  </button>
                </div>
              ) : null}
              {isLoading ? (
                <div className="data-browser-message">
                  <Loader2 size={17} />
                  <span>正在读取快照目录</span>
                </div>
              ) : snapshots.length > 0 ? (
                <div className="dataset-list">
                  {snapshots.map((snapshot) => (
                    <button
                      className={snapshot.snapshot_id === activeSnapshotId ? "dataset-list-item active" : "dataset-list-item"}
                      key={snapshot.snapshot_id}
                      onClick={() => selectSnapshot(snapshot.snapshot_id)}
                      type="button"
                    >
                      <strong>{snapshot.snapshot_id.slice(0, 20)}</strong>
                      <small>{snapshot.namespace} / {snapshot.dataset_id}</small>
                      <span>{snapshotDateRange(snapshot)}</span>
                      <em className={qualityClass(snapshot.quality_status)}>{qualityLabel(snapshot.quality_status)}</em>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>

            <div className="dataset-detail-panel">
              {activeSnapshot ? (
                <SnapshotDetail
                  detailError={detailError}
                  onOpenDataBrowser={onOpenDataBrowser}
                  snapshot={activeSnapshot}
                />
              ) : detailError ? (
                <MissingSnapshotDetail error={detailError} />
              ) : (
                <div className="dataset-detail-empty">
                  <span>选择一个快照查看详情。</span>
                </div>
              )}
            </div>
          </>
        )}
      </section>
    </>
  );
}

function SnapshotDetail({
  detailError,
  onOpenDataBrowser,
  snapshot
}: {
  detailError: SnapshotApiError | null;
  onOpenDataBrowser?: () => void;
  snapshot: SnapshotSummary;
}) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");

  async function copySnapshotUri() {
    const uri = snapshotUri(snapshot.snapshot_id);
    let ok = false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(uri);
        ok = true;
      }
    } catch {
      ok = false;
    }
    if (!ok) {
      ok = fallbackCopyText(uri);
    }
    setCopyState(ok ? "copied" : "failed");
    window.setTimeout(() => setCopyState("idle"), 2000);
  }

  const hasQlib = snapshot.has_qlib;
  const isWarning = snapshot.quality_status === "warning";

  return (
    <>
      {detailError ? (
        <div className="data-browser-message error">
          <AlertCircle size={17} />
          <span>详情刷新失败：{detailError.message}</span>
        </div>
      ) : null}

      <section className="doc-section dataset-detail-section">
        <div className="section-title">
          <Archive size={20} />
          <h2>{snapshot.snapshot_id}</h2>
          <code className="dataset-title-id">{snapshot.namespace}/{snapshot.dataset_id}</code>
          <span className={qualityBadgeClass(snapshot.quality_status)}>{qualityLabel(snapshot.quality_status)}</span>
          <span className={hasQlib ? "ready-badge" : "ready-badge example"}>
            {hasQlib ? <ShieldCheck size={15} /> : null}
            {hasQlib ? "含 Qlib" : "无 Qlib"}
          </span>
        </div>

        <div className="snapshot-uri-row">
          <Link2 size={16} />
          <code>{snapshotUri(snapshot.snapshot_id)}</code>
          <button className="ghost-action compact" onClick={copySnapshotUri} type="button">
            <Copy size={15} />
            {copyState === "copied" ? "已复制" : copyState === "failed" ? "复制失败" : "复制 URI"}
          </button>
          <span className="snapshot-uri-note">不含 token，可直接用于 Skynet 加载</span>
        </div>

        {isWarning ? (
          <div className="quality-note-list">
            <p className="quality-note">
              {snapshot.limitations.length} 条 limitations 或质量提醒，快照可发布但请先阅读下方 quality 区块。
            </p>
          </div>
        ) : null}

        <DataTable
          columns={["项目", "当前值", "说明"]}
          rows={snapshotFacts(snapshot)}
        />
      </section>

      <section className="doc-section">
        <div className="section-title">
          <Table2 size={20} />
          <h2>五张表</h2>
          <span className="snapshot-uri-note">文件、行数、schema hash 由 API 提供，不在前端重算</span>
        </div>
        <SnapshotTables snapshot={snapshot} />
      </section>

      <section className="doc-section">
        <div className="section-title">
          <GitBranch size={20} />
          <h2>来源追溯</h2>
        </div>
        {snapshot.source_datasets.length > 0 ? (
          <DataTable
            columns={["来源数据集", "source runs", "字段", "筛选", "日期范围", "observed schema hash"]}
            rows={snapshot.source_datasets.map((entry) => sourceDatasetRow(entry))}
          />
        ) : (
          <div className="data-browser-empty">
            <strong>没有记录来源数据集</strong>
            <span>manifest 未声明 source_datasets。</span>
          </div>
        )}
        {snapshot.source_runs.length > 0 ? (
          <div className="path-list">
            {snapshot.source_runs.map((runId) => (
              <code key={runId}>{runId}</code>
            ))}
          </div>
        ) : null}
        {onOpenDataBrowser ? (
          <button className="ghost-action" onClick={onOpenDataBrowser} type="button">
            <Database size={16} />
            在数据中心查看来源数据集
          </button>
        ) : null}
      </section>

      <section className="doc-section">
        <div className="section-title">
          <FileJson size={20} />
          <h2>质量与限制</h2>
        </div>
        {snapshot.limitations.length > 0 ? (
          <div className="quality-note-list">
            {snapshot.limitations.map((item) => (
              <p className="quality-note" key={item}>{item}</p>
            ))}
          </div>
        ) : (
          <div className="data-browser-empty">
            <strong>没有 limitations</strong>
            <span>manifest 未声明限制项。</span>
          </div>
        )}
        <div className="path-list">
          <code>quality 文件：{snapshot.quality_uri || "quality.json"}</code>
          <code className="missing">quality.json 内容不通过 Web API 提供；其 warning 已按契约进入 limitations</code>
        </div>
      </section>

      <section className="doc-section">
        <div className="section-title">
          <ShieldCheck size={20} />
          <h2>Qlib 导出</h2>
        </div>
        {hasQlib ? (
          <div className="path-list">
            <code>相对路径：{snapshot.qlib_provider_uri}</code>
            <code>验证状态：包含在快照 bundle 中，由插件导出（validation 结果见 quality 文件）</code>
          </div>
        ) : (
          <div className="data-browser-empty">
            <strong>未包含 Qlib provider</strong>
            <span>该快照创建时未导出 Qlib 目录（include_qlib=false）。</span>
          </div>
        )}
      </section>
    </>
  );
}

function SnapshotTables({ snapshot }: { snapshot: SnapshotSummary }) {
  const tableEntries = Object.entries(snapshot.tables ?? {});
  if (tableEntries.length === 0) {
    return (
      <div className="data-browser-empty">
        <strong>没有表文件</strong>
        <span>manifest 未记录任何表。</span>
      </div>
    );
  }
  return (
    <div className="snapshot-tables">
      {tableEntries.map(([name, refs]) => (
        <div className={`snapshot-table-card${CORE_TABLE_NAMES.includes(name) ? " core" : ""}`} key={name}>
          <div className="snapshot-table-card-head">
            <strong>{name}</strong>
            {CORE_TABLE_NAMES.includes(name) ? <span className="ready-badge">core</span> : null}
            <span>{refs.length} 个文件 · {formatNumber(snapshot.row_counts[name] ?? 0)} 行</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>文件</th>
                  <th>行数</th>
                  <th>大小</th>
                  <th>sha256（前 12）</th>
                  <th>schema hash（前 12）</th>
                </tr>
              </thead>
              <tbody>
                {refs.map((ref) => (
                  <tr key={ref.uri}>
                    <td><code>{ref.uri}</code></td>
                    <td>{formatNumber(ref.row_count)}</td>
                    <td>{formatBytes(ref.size_bytes)}</td>
                    <td><code title={ref.sha256}>{ref.sha256.slice(0, 12)}</code></td>
                    <td><code title={ref.schema_hash}>{ref.schema_hash.slice(0, 12)}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="data-browser-message">
            <AlertCircle size={15} />
            <span>表内预览在 Web 中不可用（bundle 表没有 dataset 查询路由，且不得全量加载进浏览器）；请复制 axdata://snapshot/{snapshot.snapshot_id} 用 Skynet 加载。</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function MissingSnapshotDetail({ error }: { error: SnapshotApiError }) {
  return (
    <div className="data-browser-empty-state detail">
      <div>
        <span className="empty-state-icon">
          <AlertCircle size={24} />
        </span>
        <h2>快照不存在或不可见</h2>
        <p>该快照可能已被移除，或目录未完成（没有 _SUCCESS / manifest 损坏）——后端对这类目录一律按不存在处理。</p>
        <p className="form-error">{error.code}: {error.message}</p>
      </div>
    </div>
  );
}

function snapshotFacts(snapshot: SnapshotSummary): TableRow[] {
  return [
    ["manifest 版本", snapshot.manifest_version, "skynet.dataset/v2"],
    ["数据集", `${snapshot.namespace} / ${snapshot.dataset_id}`, "快照目录 namespace 与数据集 ID"],
    ["数据集版本", snapshot.dataset_version || "", "冻结时的 calendar_version"],
    ["日历版本", snapshot.calendar_version || "", "快照冻结的交易日历版本"],
    ["日期范围", snapshotDateRange(snapshot), "来源数据集 start/end 的最小/最大；无来源时取日历版本"],
    ["内容 hash", snapshot.content_hash || "", "完整 SHA-256，前 12 位见列表"],
    ["创建时间", snapshot.created_at || "", "UTC ISO"],
    ["本地路径", snapshot.path || "", "bundle 目录（不在 hash 内）"],
    ["_SUCCESS", "存在", "API 只返回已完成（含 _SUCCESS）的快照"],
    ["quality 状态", qualityLabel(snapshot.quality_status), "由 manifest limitations 推导（后端无独立字段）"],
    ["source runs", String(snapshotSourceRunCount(snapshot)), "manifest source_runs + 各来源数据集 source_runs"],
    ["limitations", String(snapshot.limitations.length), "限制与质量提醒，见质量区块"]
  ];
}

function sourceDatasetRow(entry: SnapshotSourceDatasetRef): TableRow {
  const filters = entry.filters && Object.keys(entry.filters).length > 0
    ? Object.entries(entry.filters).map(([key, value]) => `${key}=${String(value)}`).join(", ")
    : "";
  const range = entry.start_date && entry.end_date
    ? `${entry.start_date} - ${entry.end_date}`
    : (entry.start_date || entry.end_date || "");
  return [
    entry.dataset_id,
    (entry.source_runs ?? []).join(", ") || "",
    (entry.fields ?? []).join(", ") || "",
    filters,
    range,
    entry.observed_schema_hash?.slice(0, 12) || ""
  ];
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function qualityLabel(status: string) {
  if (status === "warning") {
    return "提醒";
  }
  if (status === "passed") {
    return "通过";
  }
  return "未知";
}

function qualityClass(status: string) {
  if (status === "passed") {
    return "ok";
  }
  if (status === "warning") {
    return "warn";
  }
  return "";
}

function qualityBadgeClass(status: string) {
  return `provider-status-badge ${qualityClass(status) || "installed"}`;
}

function formatNumber(value: number | null | undefined) {
  return value === null || value === undefined ? "" : value.toLocaleString("zh-CN");
}

function formatBytes(value: number) {
  if (!Number.isFinite(value)) {
    return "";
  }
  if (value >= 1024 * 1024) {
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }
  if (value >= 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${value} B`;
}

function fallbackCopyText(text: string) {
  try {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(textarea);
    return ok;
  } catch {
    return false;
  }
}

function initialSnapshotIdFromUrl() {
  if (typeof window === "undefined") {
    return "";
  }
  const params = new URLSearchParams(window.location.search);
  return params.get("snapshot") ?? "";
}

function syncSnapshotRoute(snapshotId: string) {
  if (typeof window === "undefined") {
    return;
  }
  const url = new URL(window.location.href);
  url.searchParams.set("section", "snapshots");
  if (snapshotId) {
    url.searchParams.set("snapshot", snapshotId);
  } else {
    url.searchParams.delete("snapshot");
  }
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}
