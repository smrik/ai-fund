import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useOutletContext, useParams } from "react-router-dom";

import { getMarket } from "@/lib/api";
import { formatCurrency, formatDateLabel, formatPercent, formatText } from "@/lib/format";
import type { MarketPayload } from "@/lib/types";
import { PageHero } from "@/components/PageHero";
import type { TickerWorkspace } from "@/lib/types";

type TickerLayoutContext = {
  workspace?: TickerWorkspace;
  openLatestSnapshot?: () => void;
  runDeepAnalysis?: () => void;
  openLatestSnapshotPending?: boolean;
  runDeepAnalysisPending?: boolean;
};

const marketViews = ["Summary", "News & Revisions", "Macro", "Sentiment", "Factor Exposure"] as const;
type MarketView = (typeof marketViews)[number];

type OrderedChartPoint = {
  label: string;
  xValue: number;
  yValue: number;
};

const factorDefinitions: Array<{ key: string; label: string; description: string }> = [
  {
    key: "market_beta",
    label: "Market Beta",
    description: "How strongly the stock tends to move with the broad market. Above 1 means more market-sensitive, below 1 means more defensive.",
  },
  {
    key: "r_squared",
    label: "R²",
    description: "How much of the stock's return pattern the factor model explains. Higher values mean the factor fit is more informative.",
  },
  {
    key: "annualized_alpha",
    label: "Alpha (ann.)",
    description: "The return left over after accounting for the factor model. Positive alpha suggests idiosyncratic upside beyond factor exposures.",
  },
  {
    key: "value_beta",
    label: "Value (HML)",
    description: "Sensitivity to the value factor. Positive values suggest the stock behaves more like cheaper, asset-heavy names.",
  },
  {
    key: "momentum_beta",
    label: "Momentum",
    description: "Sensitivity to recent price leadership. Negative values imply the stock has tended to lag momentum cohorts.",
  },
  {
    key: "profitability_beta",
    label: "Quality (RMW)",
    description: "Sensitivity to high-quality, high-profitability companies. Positive values indicate some exposure to quality leadership.",
  },
];

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

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function titleize(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatSignedDecimal(value: unknown, digits = 2): string {
  const amount = asNumber(value);
  if (amount == null) {
    return "—";
  }
  return `${amount >= 0 ? "+" : ""}${amount.toFixed(digits)}`;
}

function formatSignedPercentFraction(value: unknown): string {
  const amount = asNumber(value);
  if (amount == null) {
    return "—";
  }
  const basisPoints = amount * 100;
  return `${basisPoints >= 0 ? "+" : ""}${formatPercent(basisPoints)}`;
}

function formatPercentFraction(value: unknown): string {
  const amount = asNumber(value);
  if (amount == null) {
    return "—";
  }
  return formatPercent(amount * 100);
}

function withAlpha(color: string, alpha: number): string {
  const normalized = color.replace("#", "");
  if (normalized.length !== 6) {
    return color;
  }

  const red = Number.parseInt(normalized.slice(0, 2), 16);
  const green = Number.parseInt(normalized.slice(2, 4), 16);
  const blue = Number.parseInt(normalized.slice(4, 6), 16);
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function buildTickIndexes(length: number, maxTicks: number): number[] {
  if (length <= 1) {
    return [0];
  }

  const tickCount = Math.min(length, Math.max(2, maxTicks));
  const indexes = new Set<number>([0, length - 1]);
  for (let tickIndex = 1; tickIndex < tickCount - 1; tickIndex += 1) {
    indexes.add(Math.round((tickIndex / (tickCount - 1)) * (length - 1)));
  }
  return Array.from(indexes).sort((left, right) => left - right);
}

function renderLoadingPanel(label: string) {
  return (
    <section className="panel">
      <h2>{label}</h2>
      <div className="skeleton-line skeleton" style={{ width: "92%" }} />
      <div className="skeleton-line skeleton" style={{ width: "78%" }} />
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
  columns: Array<{ key: string; label: string; kind?: "text" | "currency" | "percent" | "number" }>,
) {
  if (!rows.length) {
    return <p className="table-note">No rows available.</p>;
  }

  const formatValue = (value: unknown, kind: "text" | "currency" | "percent" | "number" = "text") => {
    if (kind === "currency") {
      return formatCurrency(asNumber(value));
    }
    if (kind === "percent") {
      return formatPercentFraction(value);
    }
    if (kind === "number") {
      const amount = asNumber(value);
      return amount == null ? "—" : amount.toFixed(2);
    }
    return formatText(asText(value) ?? String(value ?? ""));
  };

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
                <td key={column.key}>{formatValue(row[column.key], column.kind ?? "text")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function renderOrderedSeriesChart(
  points: OrderedChartPoint[],
  options: {
    testId: string;
    axisLabel: string;
    legendLabel: string;
    color: string;
    valueFormatter?: (value: number) => string;
    footerLabel?: string;
  },
) {
  if (!points.length) {
    return <p className="table-note">No chart series available.</p>;
  }

  const sortedPoints = [...points].sort((left, right) => left.xValue - right.xValue);
  const rawMin = Math.min(...sortedPoints.map((point) => point.yValue));
  const rawMax = Math.max(...sortedPoints.map((point) => point.yValue));
  const rangePadding = rawMin === rawMax ? Math.max(Math.abs(rawMin) * 0.12, 0.1) : (rawMax - rawMin) * 0.18;
  const minValue = rawMin - rangePadding;
  const maxValue = rawMax + rangePadding;
  const width = 640;
  const height = 300;
  const margin = { top: 18, right: 68, bottom: 52, left: 26 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const xTickIndexes = buildTickIndexes(sortedPoints.length, 6);

  const xMin = sortedPoints[0]?.xValue ?? 0;
  const xMax = sortedPoints[sortedPoints.length - 1]?.xValue ?? 1;
  const toX = (value: number) => {
    if (xMin === xMax) {
      return margin.left + plotWidth / 2;
    }
    return margin.left + ((value - xMin) / (xMax - xMin)) * plotWidth;
  };
  const toY = (value: number) => {
    const ratio = (value - minValue) / Math.max(maxValue - minValue, 1);
    return margin.top + plotHeight - ratio * plotHeight;
  };

  const linePoints = sortedPoints.map((point) => `${toX(point.xValue)},${toY(point.yValue)}`).join(" ");
  const areaPoints = [
    `${toX(sortedPoints[0]?.xValue ?? 0)},${height - margin.bottom}`,
    ...sortedPoints.map((point) => `${toX(point.xValue)},${toY(point.yValue)}`),
    `${toX(sortedPoints[sortedPoints.length - 1]?.xValue ?? 0)},${height - margin.bottom}`,
  ].join(" ");
  const gridLines = Array.from({ length: 4 }, (_, index) => {
    const ratio = index / 3;
    const value = maxValue - ratio * (maxValue - minValue);
    return {
      key: `grid-${index}`,
      y: margin.top + ratio * plotHeight,
      label: options.valueFormatter ? options.valueFormatter(value) : value.toFixed(2),
    };
  });

  return (
    <div className="time-series-card time-series-chart" data-testid={options.testId}>
      <div className="time-series-legend">
        <span className="time-series-legend-item">
          <span className="time-series-legend-swatch" style={{ backgroundColor: options.color }} />
          {options.legendLabel}
        </span>
      </div>
      <svg className="time-series-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${options.axisLabel} chart`}>
        {gridLines.map((line) => (
          <g key={line.key}>
            <line className="time-series-grid-line" x1={margin.left} x2={width - margin.right} y1={line.y} y2={line.y} />
            <text className="time-series-grid-label" x={width - margin.right + 4} y={line.y - 4} textAnchor="start">
              {line.label}
            </text>
          </g>
        ))}
        <line className="time-series-axis-line" x1={margin.left} x2={width - margin.right} y1={height - margin.bottom} y2={height - margin.bottom} />
        <polygon className="time-series-area" fill={withAlpha(options.color, 0.12)} points={areaPoints} />
        <polyline
          className="time-series-line"
          fill="none"
          stroke={options.color}
          strokeWidth="2.8"
          strokeLinejoin="round"
          strokeLinecap="round"
          points={linePoints}
        />
        {sortedPoints.map((point) => (
          <circle key={point.label} className="chart-point" cx={toX(point.xValue)} cy={toY(point.yValue)} r="3.4" fill={options.color} />
        ))}
        {xTickIndexes.map((index) => (
          <text key={`${sortedPoints[index]?.label ?? index}-${index}`} className="time-series-axis-label" x={toX(sortedPoints[index]?.xValue ?? 0)} y={height - 14} textAnchor="middle">
            {sortedPoints[index]?.label}
          </text>
        ))}
        <text className="time-series-axis-label chart-axis-label" x={width / 2} y={height - 26} textAnchor="middle">
          {options.axisLabel}
        </text>
      </svg>
      <div className="chart-foot">
        <span>{options.footerLabel ?? `${options.axisLabel} increases left to right`}</span>
        <span>{sortedPoints.length} observations</span>
      </div>
    </div>
  );
}

function MetricDefinitionBadge({ description }: { description: string }) {
  return (
    <span className="metric-help" title={description} aria-label={description}>
      ?
    </span>
  );
}

function buildSentimentReasoning(sentiment: Record<string, unknown> | null): string {
  const direction = titleize(asText(sentiment?.direction) ?? asText(sentiment?.label) ?? asText(sentiment?.stance));
  const score = formatSignedDecimal(sentiment?.score);
  const bullishThemes = asTextArray(sentiment?.key_bullish_themes);
  const bearishThemes = asTextArray(sentiment?.key_bearish_themes);
  const riskNarratives = asTextArray(sentiment?.risk_narratives);
  const bullishLead = bullishThemes.length ? bullishThemes.slice(0, 2).join(" and ") : "limited positive catalysts";
  const bearishLead = bearishThemes.length ? bearishThemes.slice(0, 2).join(" and ") : "few clearly defined bearish drags";
  const riskLead = riskNarratives[0] ?? "No dominant break-risk was returned for this ticker.";
  return `${direction} with a ${score} score. Bulls are leaning on ${bullishLead}, while the main drag comes from ${bearishLead}. The key break-risk called out in the source narrative is: ${riskLead}`;
}

function SummaryPanel({
  analyst,
  historicalBrief,
  quarterlyHeadlines,
  auditFlags,
}: {
  analyst: Record<string, unknown> | null;
  historicalBrief: Record<string, unknown> | null;
  quarterlyHeadlines: Record<string, unknown>[];
  auditFlags: string[];
}) {
  const timeline = asRows(historicalBrief?.event_timeline);

  return (
    <section className="page-stack">
      <section className="grid-cards">
        <article className="panel">
          <h2>Recommendation</h2>
          <p>{formatText(asText(analyst?.recommendation))}</p>
          <p>Target Mean: {formatCurrency(asNumber(analyst?.target_mean))}</p>
          <p>Analysts: {formatText(asText(analyst?.num_analysts != null ? String(analyst?.num_analysts) : null))}</p>
          <p>Current Price: {formatCurrency(asNumber(analyst?.current_price))}</p>
        </article>
        <article className="panel">
          <h2>Historical Brief</h2>
          <p>{asText(historicalBrief?.summary) ?? "No historical brief available yet."}</p>
          <p className="table-note">
            {formatDateLabel(asText(historicalBrief?.period_start))} → {formatDateLabel(asText(historicalBrief?.period_end))}
          </p>
        </article>
        <article className="panel">
          <h2>Quarterly Materiality</h2>
          <ul className="clean-list">
            {quarterlyHeadlines.length
              ? quarterlyHeadlines.slice(0, 5).map((row, index) => (
                  <li key={`${asText(row.title) ?? "headline"}-${index}`}>{formatText(asText(row.title) ?? asText(row.headline))}</li>
                ))
              : [<li key="market-empty">No recent quarterly headlines returned for this ticker.</li>]}
          </ul>
        </article>
      </section>

      <section className="panel">
        <h2>Historical Timeline</h2>
        {timeline.length
          ? renderValueTable(timeline, [
              { key: "date_label", label: "Date" },
              { key: "source", label: "Source" },
              { key: "category", label: "Category" },
              { key: "summary", label: "Summary" },
            ])
          : <p className="table-note">No historical timeline is available yet.</p>}
      </section>

      {auditFlags.length ? (
        <section className="panel">
          <h2>Flags</h2>
          <ul className="clean-list">
            {auditFlags.map((flag) => (
              <li key={flag}>{flag}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </section>
  );
}

function NewsAndRevisionsPanel({
  revisions,
  headlines,
}: {
  revisions: Record<string, unknown> | null;
  headlines: Record<string, unknown>[];
}) {
  const momentum = titleize(asText(revisions?.revision_momentum));

  return (
    <section className="page-stack">
      <section className="grid-cards">
        <article className="panel"><h2>EPS Rev (30d)</h2><p>{formatPercentFraction(revisions?.eps_revision_30d_pct)}</p></article>
        <article className="panel"><h2>Rev Rev (30d)</h2><p>{formatPercentFraction(revisions?.revenue_revision_30d_pct)}</p></article>
        <article className="panel"><h2>EPS Rev (90d)</h2><p>{formatPercentFraction(revisions?.eps_revision_90d_pct)}</p></article>
        <article className="panel"><h2>Est. Dispersion</h2><p>{formatPercentFraction(revisions?.estimate_dispersion)}</p></article>
      </section>

      <section className="panel">
        <h2>Revision Momentum</h2>
        <p>{momentum}</p>
        <p className="table-note">As of {formatDateLabel(asText(revisions?.as_of_date))} · Analysts {formatText(asText(revisions?.num_analysts != null ? String(revisions?.num_analysts) : null))}</p>
      </section>

      <section className="panel">
        <h2>News & Revisions</h2>
        {renderValueTable(headlines, [
          { key: "date", label: "Date" },
          { key: "source", label: "Source" },
          { key: "title", label: "Headline" },
          { key: "topic_bucket", label: "Topic" },
          { key: "materiality_score", label: "Materiality", kind: "number" },
        ])}
      </section>
    </section>
  );
}

function MacroPanel({ macro }: { macro: Record<string, unknown> | null }) {
  const regime = asRecord(macro?.regime);
  const scenarioWeights = asRecord(macro?.scenario_weights);
  const snapshot = asRecord(macro?.snapshot);
  const series = asRecord(snapshot?.series) ?? {};
  const yieldCurve = asRecord(macro?.yield_curve);
  const maturities = Array.isArray(yieldCurve?.maturities) ? (yieldCurve?.maturities as unknown[]) : [];

  const yieldPoints = maturities
    .map((entry, index) => {
      const parts = Array.isArray(entry) ? entry : [];
      const xValue = asNumber(parts[1]);
      const yValue = asNumber(parts[2]);
      if (xValue == null || yValue == null) {
        return null;
      }
      return {
        label: String(parts[0] ?? `Point ${index + 1}`),
        xValue,
        yValue,
      };
    })
    .filter((entry): entry is OrderedChartPoint => entry != null);

  const twoYear = yieldPoints.find((point) => point.label === "2Y")?.yValue ?? null;
  const tenYear = yieldPoints.find((point) => point.label === "10Y")?.yValue ?? null;
  const thirtyYear = yieldPoints.find((point) => point.label === "30Y")?.yValue ?? null;
  const curveInsight = twoYear != null && tenYear != null
    ? `${tenYear >= twoYear ? "The curve is positively sloped beyond 2Y" : "The curve is still inverted at the 2Y to 10Y segment"} with a ${Math.abs(tenYear - twoYear).toFixed(2)}pt spread.`
    : "Yield-curve shape commentary is unavailable.";
  const longEndInsight = thirtyYear != null && tenYear != null
    ? `Long-end yield sits ${Math.abs(thirtyYear - tenYear).toFixed(2)}pt ${thirtyYear >= tenYear ? "above" : "below"} the 10Y point.`
    : null;

  return (
    <section className="page-stack">
      <section className="grid-cards">
        <article className="panel">
          <h2>Market Regime</h2>
          <p>{formatText(asText(regime?.label))}</p>
          <ul className="clean-list">
            {Object.entries(asRecord(regime?.probabilities) ?? {}).map(([label, probability]) => (
              <li key={label}>{label}: {formatPercentFraction(probability)}</li>
            ))}
          </ul>
        </article>
        <article className="panel"><h2>VIX</h2><p>{asNumber(asRecord(series.VIXCLS)?.latest_value)?.toFixed(1) ?? "—"}</p></article>
        <article className="panel"><h2>HY Spread</h2><p>{formatPercentFraction(asRecord(series.BAMLH0A0HYM2)?.latest_value)}</p></article>
        <article className="panel"><h2>2s10s Slope</h2><p>{formatPercentFraction(asRecord(series.T10Y2Y)?.latest_value)}</p></article>
        <article className="panel"><h2>Fed Funds</h2><p>{formatPercentFraction(asRecord(series.FEDFUNDS)?.latest_value)}</p></article>
      </section>

      <section className="grid-cards grid-cards--tight">
        <article className="panel"><h2>Bear Weight</h2><p>{formatPercentFraction(scenarioWeights?.bear)}</p></article>
        <article className="panel"><h2>Base Weight</h2><p>{formatPercentFraction(scenarioWeights?.base)}</p></article>
        <article className="panel"><h2>Bull Weight</h2><p>{formatPercentFraction(scenarioWeights?.bull)}</p></article>
      </section>

      <section className="panel">
        <div className="panel-heading-inline">
          <h2>Yield Curve</h2>
          <span className="panel-caption">Rendered as an ordered curve, not a table dump.</span>
        </div>
        {yieldPoints.length
          ? renderOrderedSeriesChart(yieldPoints, {
              testId: "market-yield-curve",
              axisLabel: "Maturity",
              legendLabel: "Treasury Yield",
              color: "#38bdf8",
              valueFormatter: (value) => `${value.toFixed(2)}%`,
              footerLabel: "Yield curve ordered by maturity, left to right",
            })
          : <p className="table-note">Yield curve unavailable.</p>}
        <div className="curve-insight">
          <p>{curveInsight}</p>
          {longEndInsight ? <p>{longEndInsight}</p> : null}
        </div>
      </section>
    </section>
  );
}

function SentimentPanel({ sentiment }: { sentiment: Record<string, unknown> | null }) {
  const bullishThemes = asTextArray(sentiment?.key_bullish_themes);
  const bearishThemes = asTextArray(sentiment?.key_bearish_themes);
  const riskNarratives = asTextArray(sentiment?.risk_narratives);

  return (
    <section className="page-stack">
      <section className="grid-cards grid-cards--tight">
        <article className="panel panel-compact">
          <h2>Direction</h2>
          <p>{formatText(asText(sentiment?.direction) ?? asText(sentiment?.label))}</p>
        </article>
        <article className="panel panel-compact">
          <h2>Score</h2>
          <p>{formatSignedDecimal(sentiment?.score)}</p>
        </article>
        <article className="panel panel-compact">
          <h2>Summary</h2>
          <p>{formatText(asText(sentiment?.raw_summary) ?? asText(sentiment?.summary))}</p>
        </article>
      </section>

      <section className="panel">
        <h2>What Drives The Score</h2>
        <p>{buildSentimentReasoning(sentiment)}</p>
      </section>

      <section className="grid-cards">
        <article className="panel">
          <h2>Bullish Themes</h2>
          <ul className="clean-list">
            {bullishThemes.length ? bullishThemes.map((item) => <li key={item}>{item}</li>) : [<li key="no-bullish">No bullish themes available.</li>]}
          </ul>
        </article>
        <article className="panel">
          <h2>Bearish Themes</h2>
          <ul className="clean-list">
            {bearishThemes.length ? bearishThemes.map((item) => <li key={item}>{item}</li>) : [<li key="no-bearish">No bearish themes available.</li>]}
          </ul>
        </article>
      </section>

      <section className="panel">
        <h2>Risk Narratives</h2>
        <ul className="clean-list">
          {riskNarratives.length ? riskNarratives.map((item) => <li key={item}>{item}</li>) : [<li key="no-risk">No risk narratives available.</li>]}
        </ul>
      </section>
    </section>
  );
}

function FactorExposurePanel({ factorExposure }: { factorExposure: Record<string, unknown> | null }) {
  const attribution = asRecord(factorExposure?.factor_attribution) ?? {};
  const attributionRows = Object.entries(attribution).map(([factor, weight]) => ({
    label: titleize(factor),
    value: Math.abs(asNumber(weight) ?? 0) * 100,
  }));
  const maxValue = Math.max(...attributionRows.map((row) => row.value), 1);

  return (
    <section className="page-stack">
      <section className="panel">
        <h2>Summary</h2>
        <p>{formatText(asText(factorExposure?.summary_text))}</p>
      </section>

      <section className="grid-cards">
        {factorDefinitions.map((definition) => (
          <article key={definition.key} className="panel panel-compact">
            <div className="panel-heading-inline">
              <h2>{definition.label}</h2>
              <MetricDefinitionBadge description={definition.description} />
            </div>
            <p>
              {definition.key === "annualized_alpha"
                ? formatSignedPercentFraction(factorExposure?.[definition.key])
                : definition.key === "r_squared"
                  ? formatPercentFraction(factorExposure?.[definition.key])
                  : formatSignedDecimal(factorExposure?.[definition.key])}
            </p>
          </article>
        ))}
      </section>

      <section className="panel">
        <h2>How to Read These Factor Stats</h2>
        <div className="definition-grid">
          {factorDefinitions.map((definition) => (
            <article key={`${definition.key}-definition`} className="definition-card">
              <strong>{definition.label}</strong>
              <p>{definition.description}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2>Factor Attribution</h2>
        {attributionRows.length ? (
          <div className="chart-stack category-bar-chart">
            {attributionRows.map((row) => (
              <div key={row.label} className="chart-row">
                <span className="chart-label">{row.label}</span>
                <div className="chart-bar-shell">
                  <div className="chart-bar" style={{ width: `${Math.max((row.value / maxValue) * 100, 4)}%` }} />
                </div>
                <strong>{row.value.toFixed(1)}%</strong>
              </div>
            ))}
          </div>
        ) : (
          <p className="table-note">Factor attribution unavailable.</p>
        )}
      </section>
    </section>
  );
}

export function MarketPage() {
  const { ticker = "" } = useParams();
  const {
    workspace,
    openLatestSnapshot,
    runDeepAnalysis,
    openLatestSnapshotPending,
    runDeepAnalysisPending,
  } = useOutletContext<TickerLayoutContext>();
  const [selectedView, setSelectedView] = useState<MarketView>("Summary");
  const marketQuery = useQuery({
    queryKey: ["ticker-market", ticker],
    queryFn: () => getMarket(ticker),
    enabled: Boolean(ticker),
  });

  const market = (marketQuery.data ?? { ticker }) as MarketPayload;
  const historicalBrief = asRecord(market.historical_brief);
  const analyst = asRecord(market.analyst_snapshot);
  const revisions = asRecord(market.revisions);
  const sentiment = asRecord(market.sentiment_summary);
  const macro = asRecord(market.macro);
  const factorExposure = asRecord(market.factor_exposure);
  const quarterlyHeadlines = asRows(market.quarterly_headlines);
  const headlines = asRows(market.headlines);
  const auditFlags = (market.audit_flags ?? []).filter(Boolean);
  const timelineCount = asRows(historicalBrief?.event_timeline).length;

  let activePanel: JSX.Element;
  if (marketQuery.isPending && !marketQuery.data) {
    activePanel = renderLoadingPanel("Loading market");
  } else if (selectedView === "News & Revisions") {
    activePanel = <NewsAndRevisionsPanel revisions={revisions} headlines={headlines.length ? headlines : quarterlyHeadlines} />;
  } else if (selectedView === "Macro") {
    activePanel = <MacroPanel macro={macro} />;
  } else if (selectedView === "Sentiment") {
    activePanel = <SentimentPanel sentiment={sentiment} />;
  } else if (selectedView === "Factor Exposure") {
    activePanel = <FactorExposurePanel factorExposure={factorExposure} />;
  } else {
    activePanel = (
      <SummaryPanel
        analyst={analyst}
        historicalBrief={historicalBrief}
        quarterlyHeadlines={quarterlyHeadlines}
        auditFlags={auditFlags}
      />
    );
  }

    const heroChips = [
      { label: "Historical Events", value: timelineCount },
      { label: "History Flags", value: auditFlags.length },
      {
        label: "Sentiment",
        value: formatText(asText(sentiment?.direction) ?? asText(sentiment?.label) ?? asText(sentiment?.stance)) ?? "—",
      },
      {
        label: "Sentiment Score",
        value: formatSignedDecimal(sentiment?.score),
      },
      { label: "Headlines", value: headlines.length || quarterlyHeadlines.length },
    ];

    return (
      <section className="page-stack">
        <PageHero
          kicker="Market"
          title={workspace?.company_name ?? ticker.toUpperCase()}
          subtitle="Macro, revisions, sentiment, and factor framing."
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

        <div className="section-nav section-nav--page">
          {marketViews.map((view) => (
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

        {activePanel}
      </section>
    );
}
