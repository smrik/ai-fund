import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { startTransition, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { WatchlistTable } from "@/components/WatchlistTable";
import { createWatchlistExport, getRunStatus, getWatchlist, listWatchlistExports, refreshWatchlist, runDeepAnalysis } from "@/lib/api";
import { downloadCompletedExport, getCompletedExportId } from "@/lib/exportJobs";
import { formatCurrency, formatDateLabel, formatPercent, formatText } from "@/lib/format";

function parseTickerInput(rawValue: string): string[] {
  return rawValue
    .split(/[\n,]+/)
    .map((value) => value.trim().toUpperCase())
    .filter(Boolean);
}

export function WatchlistPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [tickerInput, setTickerInput] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const [exportRunId, setExportRunId] = useState<string | null>(null);
  const [downloadedExportId, setDownloadedExportId] = useState<string | null>(null);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const watchlistQuery = useQuery({
    queryKey: ["watchlist"],
    queryFn: getWatchlist,
  });
  const exportHistoryQuery = useQuery({
    queryKey: ["watchlist-exports"],
    queryFn: listWatchlistExports,
  });
  const refreshMutation = useMutation({
    mutationFn: ({ tickers, shortlistSize }: { tickers?: string[]; shortlistSize?: number }) =>
      refreshWatchlist(tickers, shortlistSize),
    onSuccess: (payload) => {
      setRunId(payload.run_id);
    },
  });
  const deepAnalysisMutation = useMutation({
    mutationFn: (ticker: string) => runDeepAnalysis(ticker),
    onSuccess: (payload) => {
      setRunId(payload.run_id);
    },
  });
  const exportMutation = useMutation({
    mutationFn: (format: "html" | "xlsx") =>
      createWatchlistExport({ format, source_mode: "saved_watchlist", shortlist_size: payload?.shortlist_size ?? 10 }),
    onSuccess: (payload) => {
      setExportRunId(payload.run_id);
    },
  });
  const runStatusQuery = useQuery({
    queryKey: ["watchlist-run", runId],
    queryFn: () => getRunStatus(runId ?? ""),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" ? false : 1000;
    },
  });
  const exportRunStatusQuery = useQuery({
    queryKey: ["watchlist-export-run", exportRunId],
    queryFn: () => getRunStatus(exportRunId ?? ""),
    enabled: Boolean(exportRunId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" ? false : 1000;
    },
  });

  const payload = watchlistQuery.data;
  const rows = payload?.rows ?? [];
  const focusTicker = payload?.default_focus_ticker ?? rows[0]?.ticker;
  const parsedTickers = parseTickerInput(tickerInput);
  const runStatus = runStatusQuery.data;
  const selectedRow = useMemo(() => {
    const resolvedTicker = selectedTicker ?? focusTicker ?? null;
    return rows.find((row) => row.ticker === resolvedTicker) ?? rows[0] ?? null;
  }, [focusTicker, rows, selectedTicker]);

  useEffect(() => {
    if (runStatus?.status === "completed") {
      queryClient.invalidateQueries({ queryKey: ["watchlist"] }).catch(() => undefined);
    }
  }, [queryClient, runStatus?.status]);

  const completedExportId = useMemo(
    () => getCompletedExportId(exportRunStatusQuery.data?.result),
    [exportRunStatusQuery.data?.result],
  );

  useEffect(() => {
    if (exportRunStatusQuery.data?.status === "completed") {
      queryClient.invalidateQueries({ queryKey: ["watchlist-exports"] }).catch(() => undefined);
    }
  }, [exportRunStatusQuery.data?.status, queryClient]);

  useEffect(() => {
    if (!completedExportId || downloadedExportId === completedExportId) {
      return;
    }
    setDownloadedExportId(completedExportId);
    downloadCompletedExport(completedExportId);
  }, [completedExportId, downloadedExportId]);

  useEffect(() => {
    if (!rows.length) {
      return;
    }
    if (!selectedTicker || !rows.some((row) => row.ticker === selectedTicker)) {
      setSelectedTicker(focusTicker ?? rows[0]?.ticker ?? null);
    }
  }, [focusTicker, rows, selectedTicker]);

  return (
    <section className="watchlist-page">
      <header className="page-hero compact">
        <div className="page-hero-copy">
          <div className="page-kicker">Watchlist</div>
          <h1>Universe Tracker</h1>
          <p>Saved deterministic universe snapshot, ranked best-first, with latest PM stance metadata.</p>
        </div>
        <div className="hero-meta">
          <div className="hero-chip">
            <span>Last Updated</span>
            <strong>{formatDateLabel(payload?.last_updated)}</strong>
          </div>
          <div className="hero-chip">
            <span>Saved Rows</span>
            <strong>{payload?.saved_row_count ?? rows.length}</strong>
          </div>
          <div className="hero-chip">
            <span>Universe Rows</span>
            <strong>{payload?.universe_row_count ?? rows.length}</strong>
          </div>
          <div className="hero-chip">
            <span>Shortlist</span>
            <strong>{payload?.shortlist_size ?? payload?.shortlist?.length ?? 0}</strong>
          </div>
        </div>
      </header>

      {watchlistQuery.isLoading ? <div className="panel">Loading watchlist...</div> : null}
      {watchlistQuery.isError ? <div className="panel error">Failed to load watchlist.</div> : null}
      {payload ? (
        <section className="watchlist-layout">
          <WatchlistTable rows={rows} selectedTicker={selectedRow?.ticker ?? null} onSelectTicker={setSelectedTicker} />
          <aside className="panel focus-pane">
            <div className="panel-toolbar">
              <div>
                <h2>{selectedRow?.ticker ?? "Focus Ticker"}</h2>
                <p>{formatText(selectedRow?.company_name)}</p>
              </div>
              <div className={`status-pill ${selectedRow?.latest_action?.toLowerCase() === "buy" ? "status-pill--buy" : selectedRow?.latest_action?.toLowerCase() === "sell" ? "status-pill--sell" : "status-pill--watch"}`}>{formatText(selectedRow?.latest_action)}</div>
            </div>
            <div className="grid-cards focus-metrics">
              <div className="mini-card">
                <strong>Current Price</strong>
                <p>{formatCurrency(selectedRow?.price ?? null)}</p>
              </div>
              <div className="mini-card">
                <strong>Base IV</strong>
                <p>{formatCurrency(selectedRow?.iv_base ?? null)}</p>
              </div>
              <div className="mini-card">
                <strong>Weighted IV</strong>
                <p>{formatCurrency(selectedRow?.expected_iv ?? null)}</p>
              </div>
              <div className="mini-card">
                <strong>Analyst Target</strong>
                <p>{formatCurrency(selectedRow?.analyst_target ?? null)}</p>
              </div>
              <div className="mini-card">
                <strong>Upside</strong>
                <p className={(selectedRow?.expected_upside_pct ?? selectedRow?.upside_base_pct ?? null) != null ? ((selectedRow?.expected_upside_pct ?? selectedRow?.upside_base_pct ?? 0) >= 0 ? "val-positive" : "val-negative") : ""}>{formatPercent(selectedRow?.expected_upside_pct ?? selectedRow?.upside_base_pct ?? null)}</p>
              </div>
              <div className="mini-card">
                <strong>Last Memo Date</strong>
                <p>{formatDateLabel(selectedRow?.latest_snapshot_date)}</p>
              </div>
              <div className="mini-card">
                <strong>Conviction</strong>
                <p>{formatText(selectedRow?.latest_conviction)}</p>
              </div>
              <div className="mini-card">
                <strong>Bear / Bull</strong>
                <p>
                  {formatCurrency(selectedRow?.iv_bear ?? null)} / {formatCurrency(selectedRow?.iv_bull ?? null)}
                </p>
              </div>
              <div className="mini-card">
                <strong>Model Status</strong>
                <p>{formatText(selectedRow?.model_applicability_status) ?? "—"}</p>
              </div>
            </div>
            <div className="action-row">
              <button
                type="button"
                className="primary-button"
                onClick={() => selectedRow && navigate(`/ticker/${selectedRow.ticker}/overview`)}
                disabled={!selectedRow}
              >
                {selectedRow ? `Open ${selectedRow.ticker}` : "Open Ticker"}
              </button>
              <button
                type="button"
                className="ghost-button"
                onClick={() => selectedRow && deepAnalysisMutation.mutate(selectedRow.ticker)}
                disabled={!selectedRow || deepAnalysisMutation.isPending}
              >
                {deepAnalysisMutation.isPending ? "Queueing..." : "Run Deep Analysis"}
              </button>
            </div>
          </aside>
        </section>
      ) : null}

      <section className="panel subtle">
        <h2>Actions</h2>
        <div className="action-grid">
          <div>
            <strong>Refresh saved batch</strong>
            <p>Triggers deterministic batch valuation against the saved universe or an ad hoc ticker list.</p>
          </div>
          <div>
            <strong>Run deep analysis</strong>
            <p>Manual only. Stay on the watchlist until you intentionally open a ticker workspace.</p>
          </div>
          <div>
            <strong>Export saved watchlist</strong>
            <p>Generate an Excel workbook or HTML summary from the saved deterministic snapshot.</p>
          </div>
        </div>
        <div className="action-controls">
          <textarea
            className="watchlist-textarea"
            placeholder="Optional ad hoc tickers: IBM, MSFT, NVDA"
            value={tickerInput}
            onChange={(event) => startTransition(() => setTickerInput(event.target.value))}
          />
          <div className="action-row">
            <button
              type="button"
              className="primary-button"
              onClick={() => refreshMutation.mutate({ tickers: parsedTickers.length ? parsedTickers : undefined })}
              disabled={refreshMutation.isPending}
            >
              {refreshMutation.isPending ? "Queueing..." : "Refresh Deterministic Batch"}
            </button>
            {selectedRow ? (
              <button
                type="button"
                className="ghost-button"
                onClick={() => navigate(`/ticker/${selectedRow.ticker}/valuation`)}
              >
                Open Valuation Workbench
              </button>
            ) : null}
          </div>
          <div className="action-row">
            <button
              type="button"
              className="ghost-button"
              onClick={() => exportMutation.mutate("xlsx")}
              disabled={exportMutation.isPending}
            >
              {exportMutation.isPending ? "Queueing..." : "Export Watchlist Excel"}
            </button>
            <button
              type="button"
              className="ghost-button"
              onClick={() => exportMutation.mutate("html")}
              disabled={exportMutation.isPending}
            >
              {exportMutation.isPending ? "Queueing..." : "Export Watchlist HTML"}
            </button>
          </div>
          {runStatus ? (
            <div className="run-status">
              <strong>{formatText(runStatus.status)}</strong>
              <span>{runStatus.message ?? "Running against the saved universe."}</span>
              <span>
                Progress {(Math.max(0, Math.min(1, runStatus.progress ?? 0)) * 100).toFixed(0)}%
              </span>
            </div>
          ) : null}
          {exportRunStatusQuery.data ? (
            <div className="run-status">
              <strong>{formatText(exportRunStatusQuery.data.status)}</strong>
              <span>{formatText(exportRunStatusQuery.data.message) ?? "Batch export is running in the background."}</span>
            </div>
          ) : null}
          <div className="stacked-cards">
            {(exportHistoryQuery.data?.exports ?? []).slice(0, 4).map((savedExport) => (
              <div key={savedExport.export_id} className="mini-card">
                <strong>{formatText(savedExport.title) ?? savedExport.export_id}</strong>
                <p>{formatText(savedExport.export_format.toUpperCase())} · {formatDateLabel(savedExport.created_at)}</p>
                <button type="button" className="ghost-button" onClick={() => downloadCompletedExport(savedExport.export_id)}>
                  Download
                </button>
              </div>
            ))}
          </div>
        </div>
      </section>
    </section>
  );
}
