import { useQuery } from "@tanstack/react-query";
import { useOutletContext, useParams } from "react-router-dom";

import { getOverview } from "@/lib/api";
import { formatCurrency, formatDateLabel, formatPercent, formatText } from "@/lib/format";
import { PageHero } from "@/components/PageHero";
import type { TickerWorkspace } from "@/lib/types";

type TickerLayoutContext = {
  workspace?: TickerWorkspace;
  openLatestSnapshot?: () => void;
  runDeepAnalysis?: () => void;
  openLatestSnapshotPending?: boolean;
  runDeepAnalysisPending?: boolean;
};

export function OverviewPage() {
  const { ticker = "" } = useParams();
  const {
    workspace,
    openLatestSnapshot,
    runDeepAnalysis,
    openLatestSnapshotPending,
    runDeepAnalysisPending,
  } = useOutletContext<TickerLayoutContext>();
  const overviewQuery = useQuery({
    queryKey: ["ticker-overview", ticker],
    queryFn: () => getOverview(ticker),
    enabled: Boolean(ticker),
  });

  const overview = overviewQuery.data;

  const chips = [
    { label: "Action", value: formatText(workspace?.action) ?? "—" },
    { label: "Conviction", value: formatText(workspace?.conviction)?.toUpperCase?.() ?? "—" },
    { label: "Current Price", value: formatCurrency(workspace?.current_price) },
    { label: "Base IV", value: formatCurrency(workspace?.base_iv) },
    {
      label: "Bear / Bull IV",
      value: `${formatCurrency(workspace?.bear_iv)} / ${formatCurrency(workspace?.bull_iv)}`,
    },
    {
      label: "Upside",
      value: (
        <strong className={workspace?.upside_pct_base != null ? (workspace.upside_pct_base >= 0 ? "val-positive" : "val-negative") : ""}>
          {formatPercent(workspace?.upside_pct_base != null ? workspace.upside_pct_base * 100 : null)}
        </strong>
      ),
    },
    { label: "Latest Snapshot", value: formatDateLabel(workspace?.latest_snapshot_date) },
  ];

  return (
    <section className="page-stack">
      <PageHero
        kicker="Overview"
        title={workspace?.company_name ?? formatText(overview?.company_name)}
        subtitle={overview?.one_liner ?? "Compact overview for loaded ticker."}
        chips={chips}
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

      <section className="grid-cards">
        <article className="panel">
          <h2>Variant Thesis</h2>
          <p>{overview?.variant_thesis_prompt ?? "No variant thesis available."}</p>
        </article>
        <article className="panel">
          <h2>Valuation Pulse</h2>
          <p>{overview?.valuation_pulse ?? "No valuation pulse available."}</p>
        </article>
        <article className="panel">
          <h2>Market Pulse</h2>
          <p>{overview?.market_pulse ?? "No market pulse available."}</p>
        </article>
        <article className="panel">
          <h2>Next Catalyst</h2>
          <p>{overview?.next_catalyst ?? "No upcoming catalysts identified."}</p>
        </article>
      </section>

      <section className="panel">
        <h2>What Changed</h2>
        <ul className="clean-list">
          {(overview?.thesis_changes?.length ? overview.thesis_changes : ["No change summary yet."]).map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>
    </section>
  );
}
