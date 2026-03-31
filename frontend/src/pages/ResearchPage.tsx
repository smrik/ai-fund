import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useOutletContext, useParams } from "react-router-dom";

import { createTickerExport, getResearch, getRunStatus } from "@/lib/api";
import { downloadCompletedExport, getCompletedExportId } from "@/lib/exportJobs";
import { formatCurrency, formatDateLabel, formatText } from "@/lib/format";
import { PageHero } from "@/components/PageHero";
import type { TickerWorkspace } from "@/lib/types";

type TickerLayoutContext = {
  workspace?: TickerWorkspace;
  openLatestSnapshot?: () => void;
  runDeepAnalysis?: () => void;
  openLatestSnapshotPending?: boolean;
  runDeepAnalysisPending?: boolean;
};

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

function asTextArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((entry) => asText(entry) ?? "").filter(Boolean);
}

function summarizeBlockText(value: unknown): string | null {
  const text = asText(value);
  if (!text) {
    return null;
  }
  return text.replace(/\s+/g, " ").trim();
}

function formatPublishablePreview(value: string | null): string | null {
  if (!value?.trim()) {
    return null;
  }

  const withoutFrontmatter = value.replace(/^---[\s\S]*?---\s*/u, "").trim();
  const sectionMatches = Array.from(withoutFrontmatter.matchAll(/^##\s+(.+)$/gmu)).map((match) => match[1].trim());
  const body = withoutFrontmatter
    .replace(/^#.*$/gmu, "")
    .replace(/^##.*$/gmu, "")
    .replace(/\n{2,}/g, "\n")
    .trim();

  if (body) {
    return body.replace(/\s+/g, " ").trim();
  }

  if (sectionMatches.length) {
    return `Draft memo available (${sectionMatches.length} sections: ${sectionMatches.join(", ")}).`;
  }

  return withoutFrontmatter.replace(/^#+\s+/gmu, "").replace(/\s+/g, " ").trim();
}

export function ResearchPage() {
  const { ticker = "" } = useParams();
  const queryClient = useQueryClient();
  const {
    workspace,
    openLatestSnapshot,
    runDeepAnalysis,
    openLatestSnapshotPending,
    runDeepAnalysisPending,
  } = useOutletContext<TickerLayoutContext>();
  const [exportRunId, setExportRunId] = useState<string | null>(null);
  const [downloadedExportId, setDownloadedExportId] = useState<string | null>(null);
  const researchQuery = useQuery({
    queryKey: ["ticker-research", ticker],
    queryFn: () => getResearch(ticker),
    enabled: Boolean(ticker),
  });
  const exportMutation = useMutation({
    mutationFn: () => createTickerExport(ticker, { format: "html", source_mode: "loaded_backend_state" }),
    onSuccess: (payload) => setExportRunId(payload.run_id),
  });
  const exportRunStatusQuery = useQuery({
    queryKey: ["research-export-run", exportRunId],
    queryFn: () => getRunStatus(exportRunId ?? ""),
    enabled: Boolean(exportRunId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" ? false : 1000;
    },
  });
  const research = (researchQuery.data ?? {}) as Record<string, unknown>;
  const tracker = asRecord(research.tracker);
  const notebook = asRecord(research.notebook);
  const trackerState =
    asRecord(research.current_tracker_state) ??
    asRecord(tracker?.current_tracker_state) ??
    asRecord(tracker?.stance) ??
    asRecord(tracker?.tracker_state);
  const publishablePreview = formatPublishablePreview(asText(research.publishable_memo_preview));
  const questions = asRows(tracker?.open_questions ?? asRecord(tracker?.next_queue)?.open_questions).map(
    (row, index) => asText(row.question) ?? asText(row.title) ?? `Open question ${index + 1}`,
  );
  const whatChangedLines =
    Array.isArray(asRecord(tracker?.what_changed)?.summary_lines)
      ? (asRecord(tracker?.what_changed)?.summary_lines as unknown[]).map((value, index) => asText(value) ?? `Change ${index + 1}`).filter(Boolean)
      : [];
  const pillars = asRows(tracker?.pillar_board);
  const nextQueue = asRecord(tracker?.next_queue);
  const catalystRows = asRows(nextQueue?.upcoming_catalysts ?? asRecord(tracker?.catalyst_board)?.urgent_open);
  const continuity = asRecord(tracker?.continuity);
  const latestDecision = asRecord(continuity?.latest_decision);
  const latestReview = asRecord(continuity?.latest_review);
  const latestCheckpoint = asRecord(continuity?.latest_checkpoint);
  const checkpointValuation = asRecord(latestCheckpoint?.valuation);
  const snapshotRefs = asRecord(continuity?.snapshot_refs);
  const blockGroups = asRecord(notebook?.blocks_by_type) ?? {};
  const notebookHighlights = Object.values(blockGroups)
    .flatMap((group) => asRows(group))
    .slice(0, 4);
  const notebookCountsRecord = asRecord(notebook?.counts) ?? {};
  const derivedNotebookCounts = Object.entries(blockGroups).reduce<Record<string, number>>((acc, [key, value]) => {
    acc[key] = asRows(value).length;
    return acc;
  }, {});
  const noteBlockCount =
    (typeof notebookCountsRecord.all === "number" ? (notebookCountsRecord.all as number) : null) ??
    Object.values(derivedNotebookCounts).reduce((sum, count) => sum + count, 0) ??
    asRows(research.note_blocks).length;
  const notebookCounts = Object.entries(
    Object.keys(notebookCountsRecord).length > 1 ? notebookCountsRecord : derivedNotebookCounts,
  )
    .filter(([key, value]) => key !== "all" && typeof value === "number" && value > 0)
    .map(([key, value]) => ({ label: key, value }));
  const missingEvidenceFlags = asTextArray(nextQueue?.missing_evidence_flags);
  const nextCatalyst = asRecord(trackerState?.next_catalyst);
  const upsidePct = typeof trackerState?.upside_pct === "number" ? (trackerState.upside_pct as number) * 100 : null;
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

    const heroChips = [
      {
        label: "PM Action",
        value: formatText(asText(trackerState?.pm_action) ?? asText(tracker?.pm_action)) ?? "—",
      },
      {
        label: "Conviction",
        value: formatText(asText(trackerState?.pm_conviction) ?? asText(tracker?.pm_conviction)) ?? "—",
      },
      { label: "Open Questions", value: questions.length },
      { label: "Note Blocks", value: noteBlockCount },
      { label: "Status", value: formatText(asText(trackerState?.overall_status)) ?? "—" },
    ];

    return (
      <section className="page-stack">
        <PageHero
          kicker="Research"
          title={workspace?.company_name ?? ticker.toUpperCase()}
          subtitle="Working research board, note blocks, and continuity."
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
                onClick={() => exportMutation.mutate()}
                disabled={exportMutation.isPending}
              >
                {exportMutation.isPending ? "Queueing..." : "Export HTML Memo"}
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

      {exportRunStatusQuery.data ? (
        <div className="run-status">
          <strong>{formatText(asText(exportRunStatusQuery.data.status))}</strong>
          <span>{formatText(asText(exportRunStatusQuery.data.message)) ?? "Research memo export is running in the background."}</span>
        </div>
      ) : null}

      <section className="grid-cards">
        <article className="panel">
          <h2>Tracker Summary</h2>
          <p>{asText(trackerState?.summary_note) ?? "No tracker summary recorded yet."}</p>
        </article>
        <article className="panel">
          <h2>Review Date</h2>
          <p>{formatDateLabel(asText(trackerState?.last_reviewed_at) ?? asText(tracker?.last_reviewed_at))}</p>
        </article>
        <article className="panel">
          <h2>Publishable Memo</h2>
          <p>{publishablePreview ?? "No publishable memo preview saved yet."}</p>
        </article>
      </section>

      <section className="grid-cards">
        <article className="panel">
          <h2>Stance Snapshot</h2>
          <p>Base IV: {formatCurrency(typeof trackerState?.base_iv === "number" ? (trackerState.base_iv as number) : null)}</p>
          <p>Current Price: {formatCurrency(typeof trackerState?.current_price === "number" ? (trackerState.current_price as number) : null)}</p>
          <p>Upside: {upsidePct == null ? "—" : `${upsidePct >= 0 ? "+" : ""}${upsidePct.toFixed(1)}%`}</p>
          <p>Archived Stance: {formatText(asText(trackerState?.latest_archived_action))} / {formatText(asText(trackerState?.latest_archived_conviction))}</p>
        </article>
        <article className="panel">
          <h2>Next Catalyst</h2>
          <p>{formatText(asText(nextCatalyst?.title))}</p>
          <p>{formatDateLabel(asText(nextCatalyst?.expected_date))}</p>
        </article>
        <article className="panel">
          <h2>Continuity Window</h2>
          <p>Latest Snapshot: {formatDateLabel(asText(snapshotRefs?.latest_snapshot_created_at))}</p>
          <p>Prior Snapshot: {formatDateLabel(asText(snapshotRefs?.prior_snapshot_created_at))}</p>
        </article>
      </section>

      <section className="panel">
        <h2>Open Questions</h2>
        <ul className="clean-list">
          {questions.length
            ? questions.map((question) => <li key={question}>{question}</li>)
            : [<li key="research-empty">No open questions are currently tracked.</li>]}
        </ul>
      </section>

      <section className="grid-cards">
        <article className="panel">
          <h2>What Changed</h2>
          <ul className="clean-list">
            {whatChangedLines.length
              ? whatChangedLines.map((line) => <li key={line}>{line}</li>)
              : [<li key="research-no-change">No material thesis delta versus the prior archived snapshot.</li>]}
          </ul>
        </article>
        <article className="panel">
          <h2>Upcoming Catalysts</h2>
          <ul className="clean-list">
            {catalystRows.length
              ? catalystRows.map((row, index) => (
                  <li key={`${asText(row.title) ?? "catalyst"}-${index}`}>
                    <strong>{formatText(asText(row.title) ?? asText(row.catalyst_key))}</strong>
                    {asText(row.latest_evidence_cue) ? ` · ${formatText(asText(row.latest_evidence_cue))}` : ""}
                  </li>
                ))
              : [<li key="research-no-catalyst">No upcoming catalysts are currently queued.</li>]}
          </ul>
          <p className="table-note">Review status: {formatText(asText(nextQueue?.review_status))}</p>
        </article>
      </section>

      <section className="grid-cards">
        <article className="panel">
          <h2>Thesis Pillars</h2>
          <div className="stacked-cards">
            {pillars.length
              ? pillars.map((pillar, index) => (
                  <div key={`${asText(pillar.title) ?? "pillar"}-${index}`} className="mini-card">
                    <strong>{formatText(asText(pillar.title))}</strong>
                    <p>{formatText(asText(pillar.description))}</p>
                    <span>{formatText(asText(pillar.latest_evidence_cue))}</span>
                  </div>
                ))
              : [<p key="research-no-pillars" className="table-note">No thesis pillars are currently archived.</p>]}
          </div>
        </article>
        <article className="panel">
          <h2>Notebook Highlights</h2>
          <div className="stacked-cards">
            {notebookHighlights.length
              ? notebookHighlights.map((block, index) => (
                  <div key={`${asText(block.title) ?? "block"}-${index}`} className="mini-card">
                    <strong>{formatText(asText(block.title) ?? asText(block.block_type))}</strong>
                    <p>{formatText(summarizeBlockText(block.markdown_block) ?? summarizeBlockText(block.body_markdown))}</p>
                  </div>
                ))
              : [<p key="research-no-notebook" className="table-note">No notebook highlights recorded yet.</p>]}
          </div>
        </article>
      </section>

      <section className="grid-cards">
        <article className="panel">
          <h2>Note Block Mix</h2>
          <ul className="clean-list">
            {notebookCounts.length
              ? notebookCounts.map((entry) => (
                  <li key={entry.label}>
                    {entry.label}: {entry.value}
                  </li>
                ))
              : [<li key="research-no-counts">No note-block counts are currently available.</li>]}
          </ul>
        </article>
        <article className="panel">
          <h2>Continuity</h2>
          <p>Latest Decision: {formatText(asText(latestDecision?.decision_note) ?? asText(latestDecision?.decision_label))}</p>
          <p>Latest Review: {formatText(asText(latestReview?.summary) ?? asText(latestReview?.review_outcome))}</p>
          <p>Checkpoint Base IV: {formatCurrency((checkpointValuation?.base_iv as number | null | undefined) ?? (latestCheckpoint?.base_iv as number | null | undefined) ?? null)}</p>
        </article>
      </section>

      {missingEvidenceFlags.length ? (
        <section className="panel">
          <h2>Missing Evidence Flags</h2>
          <ul className="clean-list">
            {missingEvidenceFlags.map((flag) => (
              <li key={flag}>{flag}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </section>
  );
}
