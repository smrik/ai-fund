import type {
  AgenticHandoffRunPayload,
  AssumptionsPayload,
  AssumptionsPreviewPayload,
  ArchivedSnapshotPayload,
  AuditPayload,
  EvidencePacketsPayload,
  ExportListPayload,
  PMDecisionQueueListPayload,
  PMDecisionQueuePreviewPayload,
  RunPayload,
  SavedExport,
  TickerExportRequest,
  TickerExportSourceMode,
  MarketPayload,
  OverviewPayload,
  RecommendationsPayload,
  RecommendationsPreviewPayload,
  ResearchPayload,
  TickerWorkspace,
  ValuationCompsPayload,
  ValuationDcfPayload,
  ValuationSummaryPayload,
  ValuationPolicyPayload,
  ValuationPolicyPreviewPayload,
  WatchlistPayload,
  WatchlistExportRequest,
  WatchlistExportSourceMode,
  WaccPayload,
  WaccPreviewPayload,
} from "@/lib/types";
import {
  normalizeOverviewPayload,
  normalizeTickerWorkspace,
  normalizeValuationSummaryPayload,
} from "@/lib/canonical";

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

async function requestJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    const message = await response.text().catch(() => response.statusText);
    throw new Error(message || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

export function getWatchlist(): Promise<WatchlistPayload> {
  return requestJSON<WatchlistPayload>("/watchlist");
}

export function refreshWatchlist(tickers?: string[], shortlistSize = 10): Promise<RunPayload> {
  return requestJSON<RunPayload>("/watchlist/refresh", {
    method: "POST",
    body: JSON.stringify({ tickers, shortlist_size: shortlistSize }),
  });
}

export function getRunStatus(runId: string): Promise<RunPayload> {
  return requestJSON<RunPayload>(`/runs/${encodeURIComponent(runId)}`);
}

export function getTickerWorkspace(ticker: string): Promise<TickerWorkspace> {
  return requestJSON<TickerWorkspace>(`/tickers/${encodeURIComponent(ticker)}/workspace`).then(normalizeTickerWorkspace);
}

export function getOverview(ticker: string): Promise<OverviewPayload> {
  return requestJSON<OverviewPayload>(`/tickers/${encodeURIComponent(ticker)}/overview`).then(normalizeOverviewPayload);
}

export function getValuationSummary(ticker: string): Promise<ValuationSummaryPayload> {
  return requestJSON<ValuationSummaryPayload>(`/tickers/${encodeURIComponent(ticker)}/valuation/summary`).then(
    normalizeValuationSummaryPayload,
  );
}

export function getValuationDcf(ticker: string): Promise<ValuationDcfPayload> {
  return requestJSON<ValuationDcfPayload>(`/tickers/${encodeURIComponent(ticker)}/valuation/dcf`);
}

export function getValuationComps(ticker: string): Promise<ValuationCompsPayload> {
  return requestJSON<ValuationCompsPayload>(`/tickers/${encodeURIComponent(ticker)}/valuation/comps`);
}

export function getValuationAssumptions(ticker: string): Promise<AssumptionsPayload> {
  return requestJSON<AssumptionsPayload>(`/tickers/${encodeURIComponent(ticker)}/valuation/assumptions`);
}

export function getValuationPolicy(): Promise<ValuationPolicyPayload> {
  return requestJSON<ValuationPolicyPayload>("/valuation/policy");
}

export function previewValuationPolicy(payload: unknown): Promise<ValuationPolicyPreviewPayload> {
  return requestJSON<ValuationPolicyPreviewPayload>("/valuation/policy/preview", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function saveValuationPolicy(payload: unknown): Promise<ValuationPolicyPayload> {
  return requestJSON<ValuationPolicyPayload>("/valuation/policy", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function parseDamodaranPolicyDrafts(): Promise<Record<string, unknown>> {
  return requestJSON<Record<string, unknown>>("/valuation/policy/damodaran/parse", { method: "POST" });
}

export function previewValuationAssumptions(ticker: string, payload: unknown): Promise<AssumptionsPreviewPayload> {
  return requestJSON<AssumptionsPreviewPayload>(`/tickers/${encodeURIComponent(ticker)}/valuation/assumptions/preview`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function applyValuationAssumptions(ticker: string, payload: unknown): Promise<RunPayload> {
  return requestJSON<RunPayload>(`/tickers/${encodeURIComponent(ticker)}/valuation/assumptions/apply`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getWacc(ticker: string): Promise<WaccPayload> {
  return requestJSON<WaccPayload>(`/tickers/${encodeURIComponent(ticker)}/valuation/wacc`);
}

export function previewWacc(ticker: string, payload: unknown): Promise<WaccPreviewPayload> {
  return requestJSON<WaccPreviewPayload>(`/tickers/${encodeURIComponent(ticker)}/valuation/wacc/preview`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function applyWacc(ticker: string, payload: unknown): Promise<RunPayload> {
  return requestJSON<RunPayload>(`/tickers/${encodeURIComponent(ticker)}/valuation/wacc/apply`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getRecommendations(ticker: string): Promise<RecommendationsPayload> {
  return requestJSON<RecommendationsPayload>(`/tickers/${encodeURIComponent(ticker)}/valuation/recommendations`);
}

export function previewRecommendations(ticker: string, payload: unknown): Promise<RecommendationsPreviewPayload> {
  return requestJSON<RecommendationsPreviewPayload>(`/tickers/${encodeURIComponent(ticker)}/valuation/recommendations/preview`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function applyRecommendations(ticker: string, payload: unknown): Promise<RunPayload> {
  return requestJSON<RunPayload>(`/tickers/${encodeURIComponent(ticker)}/valuation/recommendations/apply`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function runAgenticHandoffProfile(ticker: string, profileName: string): Promise<AgenticHandoffRunPayload> {
  return requestJSON<AgenticHandoffRunPayload>(`/tickers/${encodeURIComponent(ticker)}/agentic-handoff/${encodeURIComponent(profileName)}/run`, {
    method: "POST",
  });
}

export function getEvidencePackets(ticker: string): Promise<EvidencePacketsPayload> {
  return requestJSON<EvidencePacketsPayload>(`/tickers/${encodeURIComponent(ticker)}/evidence-packets`);
}

export function getPmDecisionQueue(
  ticker: string,
  filters?: {
    status?: string;
    item_type?: string;
    qualitative_importance?: string;
    valuation_impact_bucket?: string;
  },
): Promise<PMDecisionQueueListPayload> {
  const query = new URLSearchParams();
  if (filters?.status) {
    query.set("status", filters.status);
  }
  if (filters?.item_type) {
    query.set("item_type", filters.item_type);
  }
  if (filters?.qualitative_importance) {
    query.set("qualitative_importance", filters.qualitative_importance);
  }
  if (filters?.valuation_impact_bucket) {
    query.set("valuation_impact_bucket", filters.valuation_impact_bucket);
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return requestJSON<PMDecisionQueueListPayload>(`/tickers/${encodeURIComponent(ticker)}/pm-decision-queue${suffix}`);
}

export function previewPmDecisionQueueItem(ticker: string, itemId: number): Promise<PMDecisionQueuePreviewPayload> {
  return requestJSON<PMDecisionQueuePreviewPayload>(`/tickers/${encodeURIComponent(ticker)}/pm-decision-queue/${itemId}/preview`, {
    method: "POST",
  });
}

export function editPmDecisionQueueItem(ticker: string, itemId: number, proposalPack: unknown): Promise<Record<string, unknown>> {
  return requestJSON<Record<string, unknown>>(`/tickers/${encodeURIComponent(ticker)}/pm-decision-queue/${itemId}/edit`, {
    method: "POST",
    body: JSON.stringify({ proposal_pack: proposalPack }),
  });
}

export function approvePmDecisionQueueItem(ticker: string, itemId: number): Promise<Record<string, unknown>> {
  return requestJSON<Record<string, unknown>>(`/tickers/${encodeURIComponent(ticker)}/pm-decision-queue/${itemId}/approve`, {
    method: "POST",
  });
}

export function rejectPmDecisionQueueItem(ticker: string, itemId: number, reason?: string): Promise<Record<string, unknown>> {
  return requestJSON<Record<string, unknown>>(`/tickers/${encodeURIComponent(ticker)}/pm-decision-queue/${itemId}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function deferPmDecisionQueueItem(ticker: string, itemId: number, reason?: string): Promise<Record<string, unknown>> {
  return requestJSON<Record<string, unknown>>(`/tickers/${encodeURIComponent(ticker)}/pm-decision-queue/${itemId}/defer`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function getMarket(ticker: string): Promise<MarketPayload> {
  return requestJSON<MarketPayload>(`/tickers/${encodeURIComponent(ticker)}/market`);
}

export function getResearch(ticker: string): Promise<ResearchPayload> {
  return requestJSON<ResearchPayload>(`/tickers/${encodeURIComponent(ticker)}/research`);
}

export function getAudit(ticker: string): Promise<AuditPayload> {
  return requestJSON<AuditPayload>(`/tickers/${encodeURIComponent(ticker)}/audit`);
}

export function listTickerExports(ticker: string): Promise<ExportListPayload> {
  return requestJSON<ExportListPayload>(`/tickers/${encodeURIComponent(ticker)}/exports`);
}

export function createTickerExport(
  ticker: string,
  payload: TickerExportRequest,
): Promise<RunPayload> {
  return requestJSON<RunPayload>(`/tickers/${encodeURIComponent(ticker)}/exports`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listWatchlistExports(): Promise<ExportListPayload> {
  return requestJSON<ExportListPayload>("/watchlist/exports");
}

export function createWatchlistExport(
  payload: WatchlistExportRequest,
): Promise<RunPayload> {
  return requestJSON<RunPayload>("/watchlist/exports", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getExportDetail(exportId: string): Promise<SavedExport> {
  return requestJSON<SavedExport>(`/exports/${encodeURIComponent(exportId)}`);
}

export function getExportDownloadUrl(exportId: string, artifactKey?: string): string {
  if (artifactKey) {
    return apiUrl(`/exports/${encodeURIComponent(exportId)}/artifacts/${encodeURIComponent(artifactKey)}`);
  }
  return apiUrl(`/exports/${encodeURIComponent(exportId)}/download`);
}

export function triggerFileDownload(url: string): void {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "";
  anchor.rel = "noopener";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
}

export function runDeepAnalysis(ticker: string): Promise<RunPayload> {
  return requestJSON<RunPayload>(`/tickers/${encodeURIComponent(ticker)}/analysis/run`, {
    method: "POST",
    body: JSON.stringify({ use_cache: true, force_refresh_agents: [] }),
  });
}

export function openLatestSnapshot(ticker: string): Promise<ArchivedSnapshotPayload> {
  return requestJSON<ArchivedSnapshotPayload>(`/tickers/${encodeURIComponent(ticker)}/snapshot/open-latest`, {
    method: "POST",
  });
}

export function defaultTickerExportRequest(
  format: "html" | "xlsx",
  sourceMode: TickerExportSourceMode,
): TickerExportRequest {
  return { format, source_mode: sourceMode };
}

export function defaultWatchlistExportRequest(
  format: "html" | "xlsx",
  sourceMode: WatchlistExportSourceMode = "saved_watchlist",
  shortlistSize = 10,
): WatchlistExportRequest {
  return { format, source_mode: sourceMode, shortlist_size: shortlistSize };
}
