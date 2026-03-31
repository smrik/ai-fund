import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useOutletContext, useParams } from "react-router-dom";

import { createTickerExport, getAudit, getRunStatus, listTickerExports } from "@/lib/api";
import { downloadCompletedExport, getCompletedExportId } from "@/lib/exportJobs";
import { formatDateLabel, formatText } from "@/lib/format";
import { PageHero } from "@/components/PageHero";
import type { SavedExport, TickerExportSourceMode, TickerWorkspace } from "@/lib/types";

type TickerLayoutContext = {
  workspace?: TickerWorkspace;
  openLatestSnapshot?: () => void;
  runDeepAnalysis?: () => void;
  openLatestSnapshotPending?: boolean;
  runDeepAnalysisPending?: boolean;
};

const auditViews = ["Summary", "Exports", "DCF", "Filings", "Comps", "Flags"] as const;
type AuditView = (typeof auditViews)[number];

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function asRows(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((row): row is Record<string, unknown> => typeof row === "object" && row !== null && !Array.isArray(row));
}

function asText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function titleize(value: string): string {
  return value
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatBool(value: unknown): string {
  return value ? "Yes" : "No";
}

function renderLoadingPanel(label: string) {
  return (
    <section className="panel">
      <h2>{label}</h2>
      <div className="skeleton-line skeleton" style={{ width: "90%" }} />
      <div className="skeleton-line skeleton" style={{ width: "76%" }} />
      <div className="skeleton-line skeleton" />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0.5rem", marginTop: "0.5rem" }}>
        <div className="skeleton skeleton-card" />
        <div className="skeleton skeleton-card" />
        <div className="skeleton skeleton-card" />
      </div>
    </section>
  );
}

function renderValueTable(
  rows: Record<string, unknown>[],
  columns: Array<{ key: string; label: string }>,
) {
  if (!rows.length) {
    return <p className="table-note">No rows available.</p>;
  }
  return (
    <div className="table-shell">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${index}-${columns[0]?.key ?? "row"}`}>
              {columns.map((column) => (
                <td key={column.key}>{formatText(asText(row[column.key]) ?? String(row[column.key] ?? "—"))}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function renderFlagGroup(title: string, flags: string[]) {
  return (
    <article className="panel">
      <h2>{title}</h2>
      <ul className="clean-list">
        {flags.length ? flags.map((flag) => <li key={`${title}-${flag}`}>{flag}</li>) : [<li key={`${title}-empty`}>No flags for this section.</li>]}
      </ul>
    </article>
  );
}

function SummaryPanel({
  dcfIntegrityRows,
  statementPresenceRows,
  compareRows,
  firstMetricKey,
  firstMetricSummary,
  dcfFlags,
  filingsFlags,
  compsFlags,
}: {
  dcfIntegrityRows: Array<{ label: string; value: string }>;
  statementPresenceRows: Array<{ statement: string; available: string }>;
  compareRows: Array<{ metric: string; target: string; peer_value: string }>;
  firstMetricKey: string | undefined;
  firstMetricSummary: Record<string, unknown> | null;
  dcfFlags: string[];
  filingsFlags: string[];
  compsFlags: string[];
}) {
  return (
    <section className="page-stack">
      <section className="grid-cards">
        <article className="panel">
          <h2>DCF Integrity</h2>
          <ul className="clean-list">
            {dcfIntegrityRows.map((row) => (
              <li key={row.label}>
                {row.label}: {row.value}
              </li>
            ))}
          </ul>
        </article>
        <article className="panel">
          <h2>Filings Coverage</h2>
          <ul className="clean-list">
            {statementPresenceRows.length
              ? statementPresenceRows.map((row) => (
                  <li key={row.statement}>
                    {row.statement}: {row.available}
                  </li>
                ))
              : [<li key="audit-no-coverage">No statement coverage summary available.</li>]}
          </ul>
        </article>
        <article className="panel">
          <h2>Historical Multiples Audit</h2>
          <p>{compareRows.length ? `${compareRows.length} target-versus-peer comparison rows loaded.` : "No comparable set is currently loaded."}</p>
          <p>Metric: {formatText(asText(firstMetricKey))}</p>
          <p>Current: {formatText(asText(firstMetricSummary?.current) ?? String(firstMetricSummary?.current ?? "—"))}</p>
          <p>Median: {formatText(asText(firstMetricSummary?.median) ?? String(firstMetricSummary?.median ?? "—"))}</p>
        </article>
      </section>

      <section className="grid-cards">
        {renderFlagGroup("DCF Flags", dcfFlags)}
        {renderFlagGroup("Filings Flags", filingsFlags)}
        {renderFlagGroup("Comps Flags", compsFlags)}
      </section>
    </section>
  );
}

function DcfPanel({
  dcfScenarioRows,
  driverRows,
  healthFlags,
  forecastRows,
  terminalBridgeRows,
  evBridgeRows,
  sensitivityPreviewRows,
}: {
  dcfScenarioRows: Record<string, unknown>[];
  driverRows: Record<string, unknown>[];
  healthFlags: Record<string, unknown>;
  forecastRows: Record<string, unknown>[];
  terminalBridgeRows: Array<{ metric: string; value: string }>;
  evBridgeRows: Array<{ metric: string; value: string }>;
  sensitivityPreviewRows: Array<{ grid: string; row: string; values: string }>;
}) {
  return (
    <section className="page-stack">
      <section className="grid-cards">
        <article className="panel">
          <h2>Terminal Bridge</h2>
          {renderValueTable(
            terminalBridgeRows.map((row) => ({ metric: row.metric, value: row.value })),
            [
              { key: "metric", label: "Metric" },
              { key: "value", label: "Value" },
            ],
          )}
        </article>
        <article className="panel">
          <h2>EV Bridge</h2>
          {renderValueTable(
            evBridgeRows.map((row) => ({ metric: row.metric, value: row.value })),
            [
              { key: "metric", label: "Metric" },
              { key: "value", label: "Value" },
            ],
          )}
        </article>
      </section>

      <section className="panel">
        <h2>DCF Scenario Summary</h2>
        {renderValueTable(dcfScenarioRows, [
          { key: "scenario", label: "Scenario" },
          { key: "intrinsic_value", label: "Intrinsic Value" },
          { key: "upside_pct", label: "Upside" },
        ])}
      </section>

      <section className="grid-cards">
        <article className="panel">
          <h2>DCF Drivers</h2>
          {renderValueTable(driverRows, [
            { key: "label", label: "Driver" },
            { key: "value", label: "Value" },
            { key: "source", label: "Source" },
          ])}
        </article>
        <article className="panel">
          <h2>Health Flags</h2>
          <ul className="clean-list">
            {Object.keys(healthFlags).length
              ? Object.entries(healthFlags).map(([label, value]) => <li key={label}>{titleize(label)}: {formatBool(value)}</li>)
              : [<li key="audit-no-health">No DCF health flags available.</li>]}
          </ul>
        </article>
      </section>

      <section className="panel">
        <h2>Forecast Bridge</h2>
        {renderValueTable(forecastRows, [
          { key: "year", label: "Year" },
          { key: "revenue_mm", label: "Revenue (MM)" },
          { key: "growth_pct", label: "Growth" },
          { key: "fcff_mm", label: "FCFF (MM)" },
        ])}
      </section>

      <section className="panel">
        <h2>Sensitivity Preview</h2>
        {renderValueTable(sensitivityPreviewRows, [
          { key: "grid", label: "Grid" },
          { key: "row", label: "Row" },
          { key: "values", label: "Visible Cells" },
        ])}
      </section>
    </section>
  );
}

function FilingsPanel({
  retrievalRows,
  filingsList,
  retrievalProfiles,
  sectionCoverageRows,
  statementPresenceByFilingRows,
  evidenceRows,
}: {
  retrievalRows: Record<string, unknown>[];
  filingsList: Record<string, unknown>[];
  retrievalProfiles: Array<Record<string, unknown>>;
  sectionCoverageRows: Array<{ section: string; count: string }>;
  statementPresenceByFilingRows: Array<{ filing: string; statements: string }>;
  evidenceRows: Array<{ profile: string; filing: string; section: string; score: string }>;
}) {
  return (
    <section className="page-stack">
      <section className="panel">
        <h2>Filing Retrieval Details</h2>
        {renderValueTable(retrievalRows, [
          { key: "filing_type", label: "Filing Type" },
          { key: "filing_date", label: "Date" },
          { key: "source", label: "Source" },
          { key: "status", label: "Status" },
        ])}
      </section>

      <section className="panel">
        <h2>Evidence Preview</h2>
        {renderValueTable(
          evidenceRows.map((row) => ({ profile: row.profile, filing: row.filing, section: row.section, score: row.score })),
          [
            { key: "profile", label: "Profile" },
            { key: "filing", label: "Filing" },
            { key: "section", label: "Section" },
            { key: "score", label: "Score" },
          ],
        )}
      </section>

      <section className="panel">
        <h2>Filings Inventory</h2>
        {renderValueTable(filingsList.slice(0, 8), [
          { key: "form_type", label: "Form" },
          { key: "filing_date", label: "Date" },
          { key: "doc_name", label: "Document" },
          { key: "clean_available", label: "Clean Text" },
        ])}
      </section>

      <section className="panel">
        <h2>Agent Retrieval Profiles</h2>
        {renderValueTable(retrievalProfiles, [
          { key: "profile", label: "Profile" },
          { key: "fallback_mode", label: "Fallback Mode" },
          { key: "selected_chunk_count", label: "Selected Chunks" },
          { key: "skipped_sections", label: "Skipped Sections" },
        ])}
      </section>

      <section className="grid-cards">
        <article className="panel">
          <h2>Section Coverage</h2>
          {renderValueTable(sectionCoverageRows, [
            { key: "section", label: "Section" },
            { key: "count", label: "Mentions" },
          ])}
        </article>
        <article className="panel">
          <h2>Statement Presence By Filing</h2>
          {renderValueTable(statementPresenceByFilingRows, [
            { key: "filing", label: "Filing" },
            { key: "statements", label: "Statements" },
          ])}
        </article>
      </section>
    </section>
  );
}

function CompsPanel({
  compareRows,
  peerRows,
  notes,
  sourceLineage,
  peerCounts,
  primaryMetric,
  similarityMethod,
  weightingFormula,
}: {
  compareRows: Array<{ metric: string; target: string; peer_value: string }>;
  peerRows: Record<string, unknown>[];
  notes: string | null;
  sourceLineage: Record<string, unknown>;
  peerCounts: Record<string, unknown> | null;
  primaryMetric: string | null;
  similarityMethod: string | null;
  weightingFormula: string | null;
}) {
  return (
    <section className="page-stack">
      <section className="grid-cards">
        <article className="panel">
          <h2>Comp Methodology</h2>
          <ul className="clean-list">
            <li>Primary Metric: {formatText(primaryMetric)}</li>
            <li>Similarity Method: {formatText(similarityMethod)}</li>
            <li>Weighting Formula: {formatText(weightingFormula)}</li>
            <li>Peer Set: {String(peerCounts?.clean ?? peerRows.length ?? 0)} clean / {String(peerCounts?.raw ?? peerRows.length ?? 0)} raw</li>
          </ul>
        </article>
        <article className="panel">
          <h2>Comps Notes</h2>
          <p>{formatText(notes) ?? "No comps notes available."}</p>
          <p className="table-note">Source lineage: {formatText(asText(sourceLineage?.source_file))} · {formatText(asText(sourceLineage?.as_of_date))}</p>
        </article>
      </section>

      <section className="panel">
        <h2>Target Vs Peer Diagnostics</h2>
        {renderValueTable(compareRows, [
          { key: "metric", label: "Metric" },
          { key: "target", label: "Target" },
          { key: "peer_value", label: "Peer Value" },
        ])}
      </section>

      <section className="panel">
        <h2>Comparable Company Details</h2>
        {renderValueTable(peerRows.slice(0, 8), [
          { key: "ticker", label: "Ticker" },
          { key: "similarity_score", label: "Similarity" },
          { key: "model_weight", label: "Weight" },
          { key: "tev_ebitda_ltm", label: "TEV / EBITDA LTM" },
          { key: "pe_ltm", label: "P / E LTM" },
        ])}
      </section>
    </section>
  );
}

function FlagsPanel({ dcfFlags, filingsFlags, compsFlags }: { dcfFlags: string[]; filingsFlags: string[]; compsFlags: string[] }) {
  return (
    <section className="grid-cards">
      {renderFlagGroup("DCF Flags", dcfFlags)}
      {renderFlagGroup("Filings Flags", filingsFlags)}
      {renderFlagGroup("Comps Flags", compsFlags)}
    </section>
  );
}

function exportFormatLabel(value: string): string {
  return value === "xlsx" ? "Excel Workbook" : "HTML Memo";
}

function exportSourceLabel(value: string): string {
  if (value === "loaded_backend_state") {
    return "Loaded Backend State";
  }
  if (value === "saved_watchlist") {
    return "Saved Watchlist";
  }
  return "Latest Snapshot";
}

function ExportsPanel({
  sourceMode,
  onSelectSourceMode,
  onExport,
  exportPending,
  runStatus,
  exports,
  exportsPending,
}: {
  sourceMode: TickerExportSourceMode;
  onSelectSourceMode: (value: TickerExportSourceMode) => void;
  onExport: (format: "html" | "xlsx") => void;
  exportPending: boolean;
  runStatus: Record<string, unknown> | null | undefined;
  exports: SavedExport[];
  exportsPending: boolean;
}) {
  return (
    <section className="page-stack">
      <section className="grid-cards">
        <article className="panel">
          <h2>Export Source</h2>
          <p className="table-note">Use the archived snapshot for reproducibility, or the backend-loaded workspace for current route state.</p>
          <div className="section-nav">
            <button
              type="button"
              className={`section-chip${sourceMode === "latest_snapshot" ? " active" : ""}`}
              onClick={() => onSelectSourceMode("latest_snapshot")}
            >
              Latest Snapshot
            </button>
            <button
              type="button"
              className={`section-chip${sourceMode === "loaded_backend_state" ? " active" : ""}`}
              onClick={() => onSelectSourceMode("loaded_backend_state")}
            >
              Loaded Backend State
            </button>
          </div>
        </article>
        <article className="panel">
          <h2>Export Actions</h2>
          <p className="table-note">Excel stages the review workbook. HTML produces the memo bundle with context and sidecar assets.</p>
          <div className="action-row">
            <button type="button" className="primary-button" onClick={() => onExport("xlsx")} disabled={exportPending}>
              {exportPending ? "Queueing..." : "Export Excel Workbook"}
            </button>
            <button type="button" className="ghost-button" onClick={() => onExport("html")} disabled={exportPending}>
              {exportPending ? "Queueing..." : "Export HTML Memo"}
            </button>
          </div>
        </article>
      </section>

      {runStatus ? (
        <div className="run-status">
          <strong>{formatText(asText(runStatus.status))}</strong>
          <span>{formatText(asText(runStatus.message)) ?? "The export job is running in the background."}</span>
        </div>
      ) : null}

      <section className="panel">
        <h2>Recent Exports</h2>
        {exportsPending ? <p className="table-note">Loading export history...</p> : null}
        {!exportsPending && !exports.length ? <p className="table-note">No exports created yet.</p> : null}
        {exports.length ? (
          <div className="stacked-cards">
            {exports.map((savedExport) => (
              <article key={savedExport.export_id} className="mini-card">
                <strong>{formatText(savedExport.title) ?? savedExport.export_id}</strong>
                <p>
                  {exportFormatLabel(savedExport.export_format)} · {exportSourceLabel(savedExport.source_mode)}
                </p>
                <p>
                  Created {formatDateLabel(savedExport.created_at)} · Status {formatText(savedExport.status)}
                </p>
                <div className="action-row">
                  <button type="button" className="ghost-button" onClick={() => downloadCompletedExport(savedExport.export_id)}>
                    Download
                  </button>
                  {(savedExport.artifacts ?? [])
                    .filter((artifact) => !artifact.is_primary)
                    .slice(0, 2)
                    .map((artifact) => (
                      <button
                        key={`${savedExport.export_id}-${artifact.artifact_key}`}
                        type="button"
                        className="ghost-button"
                        onClick={() => downloadCompletedExport(savedExport.export_id, artifact.artifact_key)}
                      >
                        {formatText(artifact.title) ?? artifact.artifact_key}
                      </button>
                    ))}
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </section>
    </section>
  );
}

export function AuditPage() {
  const { ticker = "" } = useParams();
  const queryClient = useQueryClient();
  const {
    workspace,
    openLatestSnapshot,
    runDeepAnalysis,
    openLatestSnapshotPending,
    runDeepAnalysisPending,
  } = useOutletContext<TickerLayoutContext>();
  const [selectedView, setSelectedView] = useState<AuditView>("Summary");
  const [selectedSourceMode, setSelectedSourceMode] = useState<TickerExportSourceMode>("latest_snapshot");
  const [exportRunId, setExportRunId] = useState<string | null>(null);
  const [downloadedExportId, setDownloadedExportId] = useState<string | null>(null);
  const auditQuery = useQuery({
    queryKey: ["ticker-audit", ticker],
    queryFn: () => getAudit(ticker),
    enabled: Boolean(ticker),
  });
  const exportHistoryQuery = useQuery({
    queryKey: ["ticker-exports", ticker],
    queryFn: () => listTickerExports(ticker),
    enabled: Boolean(ticker),
  });
  const createExportMutation = useMutation({
    mutationFn: (format: "html" | "xlsx") =>
      createTickerExport(ticker, {
        format,
        source_mode: selectedSourceMode,
      }),
    onSuccess: (payload) => setExportRunId(payload.run_id),
  });
  const exportRunStatusQuery = useQuery({
    queryKey: ["ticker-export-run", exportRunId],
    queryFn: () => getRunStatus(exportRunId ?? ""),
    enabled: Boolean(exportRunId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" ? false : 1000;
    },
  });

  const audit = (auditQuery.data ?? {}) as Record<string, unknown>;
  const dcfAudit = asRecord(audit.dcf_audit);
  const filings = asRecord(audit.filings_browser);
  const comps = asRecord(audit.comps);

  const dcfFlags = asRows(dcfAudit?.audit_flags).map((row, index) => asText(row.message) ?? asText(row.flag) ?? `DCF flag ${index + 1}`);
  const filingsFlags = asRows(filings?.audit_flags).map((row, index) => asText(row.message) ?? asText(row.flag) ?? `Filings flag ${index + 1}`);
  const compsFlags = Array.isArray(comps?.audit_flags) ? comps.audit_flags.map((flag) => formatText(asText(flag))) : [];

  const targetVsPeers = asRecord(comps?.target_vs_peers);
  const compareRows = Object.keys({
    ...(asRecord(targetVsPeers?.target) ?? {}),
    ...(asRecord(targetVsPeers?.peer_medians) ?? {}),
  }).map((key) => ({
    metric: titleize(key),
    target: String((asRecord(targetVsPeers?.target) ?? {})[key] ?? "—"),
    peer_value: String((asRecord(targetVsPeers?.peer_medians) ?? {})[key] ?? "—"),
  }));

  const filingsList = asRows(filings?.filings);
  const agentUsage = asRecord(filings?.agent_usage) ?? {};
  const retrievalRows =
    asRows(filings?.retrieval_rows).length
      ? asRows(filings?.retrieval_rows)
      : Object.entries(agentUsage).flatMap(([profile, chunks]) =>
          asRows(chunks).slice(0, 3).map((chunk) => ({
            filing_type: asText(chunk.form_type) ?? profile,
            filing_date: asText(chunk.filing_date),
            source: titleize(profile),
            status: `score ${typeof chunk.score === "number" ? chunk.score.toFixed(2) : "—"}`,
          })),
        );
  const evidenceRows = Object.entries(agentUsage).flatMap(([profile, chunks]) =>
    asRows(chunks).slice(0, 4).map((chunk) => ({
      profile: titleize(profile),
      filing: asText(chunk.form_type) ?? asText(chunk.accession_no) ?? "—",
      section: titleize(asText(chunk.section_key) ?? "unknown"),
      score: typeof chunk.score === "number" ? chunk.score.toFixed(2) : "—",
    })),
  );

  const coverageSummary = asRecord(filings?.coverage_summary);
  const statementPresence = asRecord(coverageSummary?.statement_presence) ?? {};
  const statementPresenceRows = Object.entries(statementPresence).map(([statement, present]) => ({
    statement: statement.replace(/_/g, " "),
    available: formatBool(present),
  }));
  const retrievalProfiles = Object.entries(asRecord(filings?.retrieval_profiles) ?? {}).map(([profile, value]) => {
    const summary = asRecord(value) ?? {};
    return {
      profile,
      fallback_mode: formatBool(summary.fallback_mode),
      selected_chunk_count: String(summary.selected_chunk_count ?? "0"),
      skipped_sections: Array.isArray(summary.skipped_sections) ? summary.skipped_sections.join(", ") || "—" : "—",
    };
  });
  const dcfScenarioRows = asRows(dcfAudit?.scenario_summary);
  const dcfIntegrity = asRecord(dcfAudit?.model_integrity) ?? {};
  const dcfIntegrityRows = [
    { label: "TV % of EV", value: String(dcfIntegrity.tv_pct_of_ev ?? "—") },
    { label: "TV High Flag", value: formatBool(dcfIntegrity.tv_high_flag) },
    { label: "Revenue Data Quality", value: asText(dcfIntegrity.revenue_data_quality_flag) ?? "—" },
    { label: "NWC Driver Quality", value: formatBool(dcfIntegrity.nwc_driver_quality_flag) },
    { label: "ROIC Consistency", value: formatBool(dcfIntegrity.roic_consistency_flag) },
  ];
  const terminalBridge = asRecord(dcfAudit?.terminal_bridge) ?? {};
  const terminalBridgeRows = [
    { metric: "Method Used", value: String(terminalBridge.method_used ?? "—") },
    { metric: "Terminal Growth %", value: String(terminalBridge.terminal_growth_pct ?? "—") },
    { metric: "TV % of EV", value: String(terminalBridge.tv_pct_of_ev ?? "—") },
  ];
  const evBridge = asRecord(dcfAudit?.ev_bridge) ?? {};
  const evBridgeRows = [
    { metric: "Enterprise Value", value: String(evBridge.enterprise_value_total_mm ?? "—") },
    { metric: "Equity Value", value: String(evBridge.equity_value_mm ?? "—") },
    { metric: "IV / Share", value: String(evBridge.intrinsic_value_per_share ?? "—") },
  ];
  const multiplesMetrics = asRecord(asRecord(comps?.historical_multiples_summary)?.metrics) ?? {};
  const [firstMetricKey] = Object.keys(multiplesMetrics);
  const firstMetric = asRecord(firstMetricKey ? multiplesMetrics[firstMetricKey] : null);
  const firstMetricSummary = asRecord(firstMetric?.summary);
  const forecastRows = asRows(dcfAudit?.forecast_bridge);
  const driverRows = asRows(dcfAudit?.driver_rows);
  const healthFlags = asRecord(dcfAudit?.health_flags) ?? {};
  const sectionCoverageRows = Object.entries(asRecord(coverageSummary?.by_section_key) ?? {}).map(([section, count]) => ({
    section: titleize(section),
    count: String(count ?? "0"),
  }));
  const statementPresenceByFiling = asRecord(filings?.statement_presence_by_filing) ?? {};
  const statementPresenceByFilingRows = Object.entries(statementPresenceByFiling).slice(0, 6).map(([filingKey, summary]) => ({
    filing: filingKey,
    statements: Object.entries(asRecord(summary) ?? {})
      .filter(([, present]) => Boolean(present))
      .map(([statement]) => titleize(statement))
      .join(", ") || "—",
  }));
  const peerRows = asRows(comps?.peers);
  const peerCounts = asRecord(comps?.peer_counts);
  const sourceLineage = asRecord(comps?.source_lineage) ?? {};
  const sensitivity = asRecord(dcfAudit?.sensitivity) ?? {};
  const sensitivityPreviewRows = [
    ...asRows(sensitivity.wacc_x_terminal_growth).slice(0, 2).map((row) => ({
      grid: "WACC × Terminal Growth",
      row: String(row.wacc ?? "—"),
      values: Object.entries(asRecord(row.values) ?? {}).map(([key, value]) => `${key}: ${String(value)}`).join(" · ") || "—",
    })),
    ...asRows(sensitivity.wacc_x_exit_multiple).slice(0, 2).map((row) => ({
      grid: "WACC × Exit Multiple",
      row: String(row.wacc ?? "—"),
      values: Object.entries(asRecord(row.values) ?? {}).map(([key, value]) => `${key}: ${String(value)}`).join(" · ") || "—",
    })),
  ];
  const recentExports = exportHistoryQuery.data?.exports ?? [];
  const completedExportId = useMemo(
    () => getCompletedExportId(exportRunStatusQuery.data?.result),
    [exportRunStatusQuery.data?.result],
  );

  useEffect(() => {
    if (exportRunStatusQuery.data?.status === "completed") {
      queryClient.invalidateQueries({ queryKey: ["ticker-exports", ticker] }).catch(() => undefined);
    }
  }, [exportRunStatusQuery.data?.status, queryClient, ticker]);

  useEffect(() => {
    if (!completedExportId || downloadedExportId === completedExportId) {
      return;
    }
    setDownloadedExportId(completedExportId);
    downloadCompletedExport(completedExportId);
  }, [completedExportId, downloadedExportId]);

  let activePanel: JSX.Element;
  if (auditQuery.isPending && !auditQuery.data) {
    activePanel = renderLoadingPanel("Loading audit");
  } else if (selectedView === "Exports") {
    activePanel = (
      <ExportsPanel
        sourceMode={selectedSourceMode}
        onSelectSourceMode={setSelectedSourceMode}
        onExport={(format) => createExportMutation.mutate(format)}
        exportPending={createExportMutation.isPending}
        runStatus={exportRunStatusQuery.data as Record<string, unknown> | undefined}
        exports={recentExports}
        exportsPending={exportHistoryQuery.isPending}
      />
    );
  } else if (selectedView === "DCF") {
    activePanel = (
      <DcfPanel
        dcfScenarioRows={dcfScenarioRows}
        driverRows={driverRows}
        healthFlags={healthFlags}
        forecastRows={forecastRows}
        terminalBridgeRows={terminalBridgeRows}
        evBridgeRows={evBridgeRows}
        sensitivityPreviewRows={sensitivityPreviewRows}
      />
    );
  } else if (selectedView === "Filings") {
    activePanel = (
      <FilingsPanel
        retrievalRows={retrievalRows}
        filingsList={filingsList}
        retrievalProfiles={retrievalProfiles}
        sectionCoverageRows={sectionCoverageRows}
        statementPresenceByFilingRows={statementPresenceByFilingRows}
        evidenceRows={evidenceRows}
      />
    );
  } else if (selectedView === "Comps") {
    activePanel = (
      <CompsPanel
        compareRows={compareRows}
        peerRows={peerRows}
        notes={asText(comps?.notes)}
        sourceLineage={sourceLineage}
        peerCounts={peerCounts}
        primaryMetric={asText(comps?.primary_metric)}
        similarityMethod={asText(comps?.similarity_method)}
        weightingFormula={asText(comps?.weighting_formula)}
      />
    );
  } else if (selectedView === "Flags") {
    activePanel = <FlagsPanel dcfFlags={dcfFlags} filingsFlags={filingsFlags} compsFlags={compsFlags} />;
  } else {
    activePanel = (
      <SummaryPanel
        dcfIntegrityRows={dcfIntegrityRows}
        statementPresenceRows={statementPresenceRows}
        compareRows={compareRows}
        firstMetricKey={firstMetricKey}
        firstMetricSummary={firstMetricSummary}
        dcfFlags={dcfFlags}
        filingsFlags={filingsFlags}
        compsFlags={compsFlags}
      />
    );
  }

  const totalFlags = dcfFlags.length + filingsFlags.length + compsFlags.length;

    const heroChips = [
      { label: "Scenarios", value: dcfScenarioRows.length },
      { label: "Filings Rows", value: retrievalRows.length },
      { label: "Peer Set", value: String(peerCounts?.clean ?? peerRows.length ?? 0) },
      { label: "Total Flags", value: totalFlags },
      { label: "Exports", value: recentExports.length },
    ];

  return (
    <section className="page-stack">
      <header className="valuation-route-nav">
        <div className="section-nav section-nav--page">
          {auditViews.map((view) => (
            <button
              key={view}
              type="button"
              className={`section-chip${selectedView === view ? " active" : ""}`}
              onClick={() => setSelectedView(view)}
            >
              {view}
            </button>
          ))}
        </div>
      </header>

      <PageHero
        kicker="Audit"
        title={workspace?.company_name ?? ticker.toUpperCase()}
        subtitle="Pipeline health, filings evidence, exports, and operational checks."
        chips={heroChips}
        actions={
          <div className="action-row page-hero-actions">
            <button
              type="button"
              className="primary-button"
              onClick={openLatestSnapshot}
              disabled={openLatestSnapshotPending || !workspace?.snapshot_available}
            >
              {openLatestSnapshotPending ? "Opening..." : "Open Latest Snapshot"}
            </button>
            <button
              type="button"
              className="ghost-button"
              onClick={runDeepAnalysis}
              disabled={runDeepAnalysisPending}
            >
              {runDeepAnalysisPending ? "Running..." : "Run Deep Analysis"}
            </button>
          </div>
        }
      />

      {activePanel}
    </section>
  );
}
