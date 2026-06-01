import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useOutletContext, useParams, useSearchParams } from "react-router-dom";

import { PageHero } from "@/components/PageHero";
import {
  approvePmDecisionQueueItem,
  applyRecommendations,
  applyValuationAssumptions,
  applyWacc,
  createTickerExport,
  deferPmDecisionQueueItem,
  editPmDecisionQueueItem,
  getEvidencePackets,
  getPmDecisionQueue,
  getRecommendations,
  getRunStatus,
  getValuationAssumptions,
  getValuationComps,
  getValuationDcf,
  getValuationPolicy,
  getValuationSummary,
  getWacc,
  previewPmDecisionQueueItem,
  rejectPmDecisionQueueItem,
  runAgenticHandoffProfile,
  previewRecommendations,
  previewValuationAssumptions,
  previewWacc,
  saveValuationPolicy,
} from "@/lib/api";
import { downloadCompletedExport, getCompletedExportId } from "@/lib/exportJobs";
import { formatCurrency, formatDateLabel, formatPercent, formatText } from "@/lib/format";
import type {
  AgenticHandoffRunError,
  AgenticHandoffRunPayload,
  EvidencePacketRunMetadata,
  EvidencePacketSummary,
  EvidenceSourceQuality,
  PMDecisionQueueActionPayload,
  PMDecisionQueueListPayload,
  PMDecisionQueueItem,
  PMDecisionQueuePreviewPayload,
  RecommendationsPayload,
  RecommendationsPreviewPayload,
  TickerWorkspace,
  ValuationPolicyPayload,
  WaccPreviewPayload,
} from "@/lib/types";

const valuationTabs = ["Summary", "DCF", "Comparables", "Multiples", "Assumptions", "WACC", "Recommendations", "PM Queue"] as const;
type ValuationTab = (typeof valuationTabs)[number];

type TickerLayoutContext = {
  workspace?: TickerWorkspace;
  openLatestSnapshot?: () => void;
  runDeepAnalysis?: () => void;
  openLatestSnapshotPending?: boolean;
  runDeepAnalysisPending?: boolean;
};

type Scalar = string | number | boolean | null | undefined;

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
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatMaybeNumber(value: unknown, digits = 1): string {
  const amount = asNumber(value);
  if (amount == null) {
    return "—";
  }
  return amount.toFixed(digits);
}

function formatMetricValue(value: unknown, kind: "currency" | "percent" | "multiple" | "count" | "text" | "number" = "number"): string {
  const amount = asNumber(value);
  if (kind === "currency") {
    return formatCurrency(amount);
  }
  if (kind === "percent") {
    return formatPercent(amount);
  }
  if (kind === "multiple") {
    return amount == null ? "—" : `${amount.toFixed(2)}x`;
  }
  if (kind === "count") {
    return amount == null ? "—" : `${Math.round(amount)}`;
  }
  if (kind === "text") {
    return formatText(asText(value));
  }
  return amount == null ? "—" : amount.toFixed(1);
}

function formatAssumptionValue(value: unknown, unit: string | null | undefined): string {
  const amount = asNumber(value);
  if (amount == null) {
    return "—";
  }

  switch ((unit ?? "").toLowerCase()) {
    case "pct":
      return formatPercent(amount * 100);
    case "days":
      return `${amount.toFixed(1)} days`;
    case "x":
      return `${amount.toFixed(2)}x`;
    case "usd":
      return formatCurrency(amount);
    default:
      return amount.toFixed(2);
  }
}

function toDisplayValue(value: unknown, unit: string | null | undefined): number {
  const amount = asNumber(value);
  if (amount == null) {
    return 0;
  }
  return (unit ?? "").toLowerCase() === "pct" ? amount * 100 : amount;
}

function fromDisplayValue(value: number, unit: string | null | undefined): number {
  return (unit ?? "").toLowerCase() === "pct" ? value / 100 : value;
}

function inputStep(unit: string | null | undefined): number {
  switch ((unit ?? "").toLowerCase()) {
    case "pct":
      return 0.1;
    case "x":
      return 0.1;
    case "days":
      return 1;
    case "usd":
      return 1;
    default:
      return 0.1;
  }
}

function renderLoadingPanel(label: string) {
  return (
    <section className="panel">
      <h2>{label}</h2>
      <div className="skeleton-line skeleton" style={{ width: "90%" }} />
      <div className="skeleton-line skeleton" style={{ width: "75%" }} />
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
  columns: Array<{ key: string; label: string; kind?: "currency" | "percent" | "number" | "text" | "multiple" | "count" }>,
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
              {columns.map((column) => {
                const value = row[column.key];
                return <td key={column.key}>{formatMetricValue(value, column.kind ?? "text")}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function renderKeyValueTable(rows: Array<{ label: string; value: Scalar }>) {
  return renderValueTable(
    rows.map((row) => ({ metric: row.label, value: row.value })),
    [
      { key: "metric", label: "Metric", kind: "text" },
      { key: "value", label: "Value", kind: "text" },
    ],
  );
}

function renderCategoryBars(rows: Record<string, unknown>[], valueKey: string, labelKey = "label") {
  if (!rows.length) {
    return <p className="table-note">No chart series available.</p>;
  }
  const values = rows.map((row) => asNumber(row[valueKey]) ?? 0);
  const maxValue = Math.max(...values, 1);
  return (
    <div className="chart-stack category-bar-chart">
      {rows.map((row, index) => {
        const label = formatText(asText(row[labelKey]) ?? asText(row.scenario) ?? asText(row.risk_name) ?? String(index));
        const value = asNumber(row[valueKey]) ?? 0;
        return (
          <div key={`${label}-${index}`} className="chart-row">
            <span className="chart-label">{label}</span>
            <div className="chart-bar-shell">
              <div className="chart-bar" style={{ width: `${Math.max((value / maxValue) * 100, 4)}%` }} />
            </div>
            <strong>{formatMaybeNumber(value, 1)}</strong>
          </div>
        );
      })}
    </div>
  );
}

function asTextArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((entry) => asText(entry) ?? "").filter(Boolean);
}

type TimeSeriesConfig = {
  key: string;
  label: string;
  color: string;
  kind?: "currency" | "percent" | "multiple" | "number";
};

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

function normalizeTimeAxisValue(value: unknown, fallbackIndex: number): { label: string; sortValue: number } {
  const amount = asNumber(value);
  if (amount != null) {
    return {
      label: Number.isInteger(amount) ? `${amount}` : amount.toFixed(1),
      sortValue: amount,
    };
  }

  const text = asText(value);
  if (!text) {
    return { label: `Point ${fallbackIndex + 1}`, sortValue: fallbackIndex };
  }

  const timestamp = Date.parse(text);
  if (Number.isFinite(timestamp)) {
    return { label: formatDateLabel(text), sortValue: timestamp };
  }

  const numericText = Number(text);
  if (Number.isFinite(numericText)) {
    return { label: text, sortValue: numericText };
  }

  return { label: text, sortValue: fallbackIndex };
}

function renderTimeSeriesChart(
  rows: Record<string, unknown>[],
  options: {
    xKey: string;
    xAxisLabel: string;
    testId: string;
    series: TimeSeriesConfig[];
  },
) {
  if (!rows.length) {
    return <p className="table-note">No chart series available.</p>;
  }

  const points = rows
    .map((row, index) => {
      const axis = normalizeTimeAxisValue(row[options.xKey], index);
      return {
        ...axis,
        values: options.series.map((series) => ({ ...series, value: asNumber(row[series.key]) })),
      };
    })
    .sort((left, right) => left.sortValue - right.sortValue);

  const numericValues = points.flatMap((point) => point.values.map((entry) => entry.value).filter((value): value is number => value != null));
  if (!numericValues.length) {
    return <p className="table-note">No chart series available.</p>;
  }

    const width = 640;
    const height = 300;
    const margin = { top: 18, right: 68, bottom: 52, left: 26 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
  const rawMin = Math.min(...numericValues);
  const rawMax = Math.max(...numericValues);
  const rangePadding = rawMin === rawMax ? Math.max(Math.abs(rawMin) * 0.1, 1) : (rawMax - rawMin) * 0.12;
  const minValue = rawMin - rangePadding;
  const maxValue = rawMax + rangePadding;
  const xTickIndexes = buildTickIndexes(points.length, 6);
  const markerIndexes = buildTickIndexes(points.length, points.length > 40 ? 4 : 7);
  const denseSeries = points.length > 36;

    const xMin = points[0]?.sortValue ?? 0;
    const xMax = points[points.length - 1]?.sortValue ?? xMin + 1;
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

  const gridLines = Array.from({ length: 4 }, (_, index) => {
    const ratio = index / 3;
    const value = maxValue - ratio * (maxValue - minValue);
    return {
      key: `grid-${index}`,
      y: margin.top + ratio * plotHeight,
      label: formatMetricValue(value, options.series[0]?.kind ?? "number"),
    };
  });

  return (
    <div className="time-series-card time-series-chart" data-testid={options.testId}>
      <div className="time-series-legend">
        {options.series.map((series) => (
          <span key={series.key} className="time-series-legend-item">
            <span className="time-series-legend-swatch" style={{ backgroundColor: series.color }} />
            {series.label}
          </span>
        ))}
      </div>
      <svg className="time-series-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${options.xAxisLabel} time series`}>
        <defs>
          {options.series.map((series) => (
            <linearGradient
              key={`${options.testId}-${series.key}-gradient`}
              id={`${options.testId}-${series.key}-gradient`}
              x1="0%"
              y1="0%"
              x2="100%"
              y2="0%"
            >
              <stop offset="0%" stopColor={withAlpha(series.color, 0.54)} />
              <stop offset="48%" stopColor={series.color} />
              <stop offset="100%" stopColor={withAlpha(series.color, 0.82)} />
            </linearGradient>
          ))}
        </defs>
        {gridLines.map((line) => (
          <g key={line.key}>
            <line className="time-series-grid-line" x1={margin.left} x2={width - margin.right} y1={line.y} y2={line.y} />
            <text className="time-series-grid-label" x={width - margin.right + 4} y={line.y - 4} textAnchor="start">
              {line.label}
            </text>
          </g>
        ))}
        <line className="time-series-axis-line" x1={margin.left} x2={width - margin.right} y1={height - margin.bottom} y2={height - margin.bottom} />
        {options.series.map((series) => {
          const seriesValues = points
            .map((point) => point.values.find((entry) => entry.key === series.key)?.value)
            .filter((value): value is number => value != null);
          if (!seriesValues.length) {
            return null;
          }

            const coordinates = points
              .map((point) => {
                const value = point.values.find((entry) => entry.key === series.key)?.value;
                if (value == null) {
                  return null;
                }
                return `${toX(point.sortValue)},${toY(value)}`;
              })
            .filter((value): value is string => Boolean(value));
                const areaPoints = [
                  `${margin.left},${height - margin.bottom}`,
                  ...coordinates,
                  `${toX(points[points.length - 1]?.sortValue ?? xMax)},${height - margin.bottom}`,
                ];
          return (
            <g key={series.key}>
              {options.series.length === 1 ? (
                <polygon
                  className="time-series-area"
                  fill={withAlpha(series.color, 0.1)}
                  points={areaPoints.join(" ")}
                />
              ) : null}
              <polyline
                className="time-series-line"
                fill="none"
                stroke={`url(#${options.testId}-${series.key}-gradient)`}
                strokeWidth={denseSeries ? "2.4" : "2.8"}
                strokeLinejoin="round"
                strokeLinecap="round"
                points={coordinates.join(" ")}
              />
              {points.map((point, index) => {
                if (!markerIndexes.includes(index)) {
                  return null;
                }
                const value = point.values.find((entry) => entry.key === series.key)?.value;
                if (value == null) {
                  return null;
                }
                return (
                  <circle
                    key={`${series.key}-${point.label}`}
                    className="chart-point"
                    cx={toX(index)}
                    cy={toY(value)}
                    r={index === points.length - 1 ? 4.8 : denseSeries ? 2.2 : 3}
                    fill={series.color}
                  />
                );
              })}
            </g>
          );
        })}
        {xTickIndexes.map((index) => (
          <text key={`${points[index]?.label ?? index}-${index}`} className="time-series-axis-label" x={toX(index)} y={height - 14} textAnchor="middle">
            {points[index]?.label}
          </text>
        ))}
        <text className="time-series-axis-label chart-axis-label" x={width / 2} y={height - 26} textAnchor="middle">
          {options.xAxisLabel}
        </text>
      </svg>
      <div className="chart-foot">
        <span>{options.xAxisLabel} on x-axis</span>
        <span>{points.length} observations</span>
        <span>{denseSeries ? "Labels sampled for readability" : "Full window visible"}</span>
      </div>
    </div>
  );
}

function summarizeSeriesWindow(rows: Record<string, unknown>[]): string {
  if (!rows.length) {
    return "No observations available.";
  }

  const first = asText(rows[0]?.date ?? rows[0]?.year);
  const last = asText(rows[rows.length - 1]?.date ?? rows[rows.length - 1]?.year);
  return `${formatDateLabel(first)} → ${formatDateLabel(last)}`;
}

function renderSeriesWindowLabel(visibleCount: number, totalCount: number): string {
  if (!totalCount) {
    return "No series loaded.";
  }
  if (visibleCount >= totalCount) {
    return `Showing full history (${totalCount} rows).`;
  }
  return `Showing ${visibleCount} most recent rows of ${totalCount}.`;
}

function ScenarioCards({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows.length) {
    return <p className="table-note">Scenario summary will appear here when valuation data is available.</p>;
  }
  return (
    <div className="grid-cards">
      {rows.map((row) => {
        const label = String(row.scenario ?? "").toLowerCase();
        const scenarioClass = label.includes("bear") ? "scenario-bear" : label.includes("bull") ? "scenario-bull" : "scenario-base";
        const upsideVal = asNumber(row.upside_pct);
        return (
          <div key={String(row.scenario)} className={`mini-card ${scenarioClass}`}>
            <strong>{formatText(asText(row.scenario))}</strong>
            <span>Probability {formatPercent(asNumber(row.probability_pct))}</span>
            <p>{formatCurrency(asNumber(row.intrinsic_value))}</p>
            <p className={upsideVal != null ? (upsideVal >= 0 ? "val-positive" : "val-negative") : ""}>{formatPercent(upsideVal)}</p>
          </div>
        );
      })}
    </div>
  );
}

function buildSensitivityRows(table: unknown): Record<string, unknown>[] {
  return asRows(table).map((row) => {
    const values = asRecord(row.values) ?? {};
    return {
      wacc: row.wacc,
      ...values,
    };
  });
}

function SummaryPanel({
  summary,
  workspace,
}: {
  summary: Record<string, unknown> | null | undefined;
  workspace?: TickerWorkspace;
}) {
  const readiness = asRecord(summary?.readiness);
  const financeQuality = asRecord(summary?.finance_quality);
  const financeFlags = asRows(financeQuality?.flags);
  const financeStatus = asText(financeQuality?.status);
  return (
    <section className="page-stack">
      <section className="panel">
        <h2>Scenario Summary</h2>
        <ScenarioCards
          rows={[
            { scenario: "Bear", intrinsic_value: summary?.bear_iv, probability_pct: 25, upside_pct: -10 },
            { scenario: "Base", intrinsic_value: summary?.base_iv, probability_pct: 50, upside_pct: summary?.upside_pct_base },
            { scenario: "Bull", intrinsic_value: summary?.bull_iv, probability_pct: 25, upside_pct: 50 },
          ]}
        />
      </section>
      <section className="grid-cards">
        <article className="panel">
          <h2>Decision Snapshot</h2>
          <p>Current Price: {formatCurrency(asNumber(summary?.current_price ?? workspace?.current_price))}</p>
          <p>Weighted IV: {formatCurrency(asNumber(summary?.weighted_iv ?? workspace?.weighted_iv))}</p>
          <p>Analyst Target: {formatCurrency(asNumber(summary?.analyst_target ?? workspace?.analyst_target))}</p>
          <p>Conviction: {formatText(asText(summary?.conviction ?? workspace?.conviction))}</p>
          <p>Memo Date: {formatDateLabel(asText(summary?.memo_date ?? workspace?.latest_snapshot_date))}</p>
        </article>
        <article className="panel">
          <h2>Terminal Setup</h2>
          <p>Base IV: {formatCurrency(asNumber(summary?.base_iv ?? workspace?.base_iv))}</p>
          <p>Bear IV: {formatCurrency(asNumber(summary?.bear_iv ?? workspace?.bear_iv))}</p>
          <p>Bull IV: {formatCurrency(asNumber(summary?.bull_iv ?? workspace?.bull_iv))}</p>
          <p>Upside: {formatPercent(asNumber(summary?.upside_pct_base ?? (workspace?.upside_pct_base == null ? null : workspace.upside_pct_base * 100)))}</p>
        </article>
        <article className="panel">
          <h2>Integrity Flags</h2>
          <p>TV High Flag: <span className={readiness?.tv_high_flag ? "val-negative" : "val-positive"}>{readiness?.tv_high_flag ? "Flagged" : "Pass"}</span></p>
          <p>Revenue Quality: <span className={readiness?.revenue_data_quality_flag && readiness.revenue_data_quality_flag !== "clean" ? "val-negative" : "val-positive"}>{formatText(asText(readiness?.revenue_data_quality_flag)) ?? "Pass"}</span></p>
          <p>NWC Driver Flag: <span className={readiness?.nwc_driver_quality_flag ? "val-negative" : "val-positive"}>{readiness?.nwc_driver_quality_flag ? "Flagged" : "Pass"}</span></p>
        </article>
        <article className="panel">
          <h2>Finance Quality</h2>
          <p>
            Review State:{" "}
            <span className={financeStatus === "review_required" ? "val-negative" : financeStatus === "clean" ? "val-positive" : ""}>
              {financeStatus ? titleize(financeStatus) : "Not scored"}
            </span>
          </p>
          <p>High Flags: {asNumber(financeQuality?.high_count) ?? 0}</p>
          <p>Medium Flags: {asNumber(financeQuality?.medium_count) ?? 0}</p>
        </article>
      </section>
      {financeFlags.length ? (
        <section className="panel subtle">
          <h2>Professional Finance Review Gates</h2>
          <div className="grid-cards grid-cards--tight">
            {financeFlags.slice(0, 6).map((flag, index) => {
              const severity = asText(flag.severity);
              return (
                <article key={`${asText(flag.code) ?? "flag"}-${index}`} className="mini-card">
                  <strong className={severity === "high" ? "val-negative" : ""}>{severity ? titleize(severity) : "Flag"}</strong>
                  <span>{formatText(asText(flag.title))}</span>
                  <p>{formatText(asText(flag.detail))}</p>
                  <p>{formatText(asText(flag.pm_check))}</p>
                </article>
              );
            })}
          </div>
        </section>
      ) : null}
      {summary?.why_it_matters ? (
        <section className="panel subtle">
          <h2>Why This Matters</h2>
          <p>{formatText(asText(summary.why_it_matters))}</p>
        </section>
      ) : null}
    </section>
  );
}

function DcfPanel({ dcf }: { dcf: Record<string, unknown> | null | undefined }) {
  const scenarioRows = asRows(dcf?.scenario_summary);
  const forecastRows = asRows(dcf?.forecast_bridge);
  const driverRows = asRows(dcf?.driver_rows);
  const healthFlags = asRecord(dcf?.health_flags) ?? {};
  const terminalBridge = asRecord(dcf?.terminal_bridge);
  const evBridge = asRecord(dcf?.ev_bridge);
  const chartSeries = asRecord(dcf?.chart_series);
  const riskImpact = asRecord(dcf?.risk_impact);
  const modelIntegrity = asRecord(dcf?.model_integrity);

  return (
    <section className="page-stack">
      <section className="panel">
        <h2>Scenario Summary</h2>
        {renderValueTable(scenarioRows, [
          { key: "scenario", label: "Scenario", kind: "text" },
          { key: "probability_pct", label: "Probability", kind: "percent" },
          { key: "intrinsic_value", label: "Intrinsic Value", kind: "currency" },
          { key: "upside_pct", label: "Upside", kind: "percent" },
        ])}
      </section>
      <section className="grid-cards">
        <article className="panel">
          <h2>Key Drivers</h2>
          {renderValueTable(driverRows, [
            { key: "label", label: "Driver", kind: "text" },
            { key: "value", label: "Value", kind: "number" },
            { key: "source", label: "Source", kind: "text" },
          ])}
        </article>
        <article className="panel">
          <h2>Health Flags</h2>
          {renderKeyValueTable(Object.entries(healthFlags).map(([label, value]) => ({ label: titleize(label), value: String(Boolean(value)) })))}
        </article>
      </section>
      <section className="panel">
        <h2>Forecast Bridge</h2>
        {renderValueTable(forecastRows, [
          { key: "year", label: "Year", kind: "number" },
          { key: "revenue_mm", label: "Revenue (MM)", kind: "number" },
          { key: "growth_pct", label: "Growth", kind: "percent" },
          { key: "ebit_margin_pct", label: "EBIT Margin", kind: "percent" },
          { key: "fcff_mm", label: "FCFF (MM)", kind: "number" },
          { key: "roic_pct", label: "ROIC", kind: "percent" },
        ])}
      </section>
      <section className="grid-cards">
        <article className="panel">
          <h2>Terminal Bridge</h2>
          {renderKeyValueTable([
            { label: "Method", value: formatText(asText(terminalBridge?.method_used)) },
            { label: "Terminal Growth", value: formatPercent(asNumber(terminalBridge?.terminal_growth_pct)) },
            { label: "TV % of EV", value: formatPercent(asNumber(terminalBridge?.tv_pct_of_ev)) },
          ])}
        </article>
        <article className="panel">
          <h2>EV → Equity Bridge</h2>
          {renderKeyValueTable([
            { label: "Enterprise Value", value: formatMaybeNumber(evBridge?.enterprise_value_total_mm) },
            { label: "Equity Value", value: formatMaybeNumber(evBridge?.equity_value_mm) },
            { label: "IV / Share", value: formatCurrency(asNumber(evBridge?.intrinsic_value_per_share)) },
          ])}
        </article>
      </section>
      <section className="panel">
        <h2>Charts</h2>
        <h3>Scenario IV</h3>
        {renderCategoryBars(asRows(chartSeries?.scenario_iv), "intrinsic_value", "scenario")}
        <h3>FCFF / NOPAT Trend</h3>
        {renderTimeSeriesChart(asRows(chartSeries?.fcff_curve), {
          xKey: "year",
          xAxisLabel: "Year",
          testId: "time-series-chart-fcff",
          series: [
            { key: "fcff_mm", label: "FCFF (MM)", color: "#38bdf8", kind: "number" },
            { key: "nopat_mm", label: "NOPAT (MM)", color: "#f59e0b", kind: "number" },
          ],
        })}
        {asRows(chartSeries?.risk_overlay).length ? (
          <>
            <h3>Risk Overlay</h3>
            {renderCategoryBars(asRows(chartSeries?.risk_overlay), "stressed_iv", "risk_name")}
          </>
        ) : null}
      </section>
      <section className="panel">
        <h2>Sensitivity Tables</h2>
        <div className="grid-cards">
          <div>
            <h3>WACC × Terminal Growth</h3>
            {renderValueTable(buildSensitivityRows(asRecord(dcf?.sensitivity)?.wacc_x_terminal_growth), Object.keys(buildSensitivityRows(asRecord(dcf?.sensitivity)?.wacc_x_terminal_growth)[0] ?? { wacc: "" }).map((key) => ({ key, label: key === "wacc" ? "WACC" : key, kind: key === "wacc" ? "text" : "currency" })))}
          </div>
          <div>
            <h3>WACC × Exit Multiple</h3>
            {renderValueTable(buildSensitivityRows(asRecord(dcf?.sensitivity)?.wacc_x_exit_multiple), Object.keys(buildSensitivityRows(asRecord(dcf?.sensitivity)?.wacc_x_exit_multiple)[0] ?? { wacc: "" }).map((key) => ({ key, label: key === "wacc" ? "WACC" : key, kind: key === "wacc" ? "text" : "currency" })))}
          </div>
        </div>
      </section>
      <section className="panel">
        <h2>Model Integrity</h2>
        {renderKeyValueTable([
          { label: "TV High Flag", value: modelIntegrity?.tv_high_flag ? "Flagged" : "Pass" },
          { label: "Revenue Data Quality", value: formatText(asText(modelIntegrity?.revenue_data_quality_flag)) },
          { label: "NWC Driver Quality", value: modelIntegrity?.nwc_driver_quality_flag ? "Warning" : "OK" },
          { label: "Risk-Adjusted Expected IV", value: formatCurrency(asNumber(riskImpact?.risk_adjusted_expected_iv)) },
        ])}
      </section>
    </section>
  );
}

function ComparablesPanel({ comps }: { comps: Record<string, unknown> | null | undefined }) {
  const metricOptions = asRows(comps?.metric_options);
  const defaultMetric = asText(comps?.selected_metric_default) ?? asText(metricOptions[0]?.key) ?? "";
  const [selectedMetric, setSelectedMetric] = useState(defaultMetric);

  useEffect(() => {
    setSelectedMetric(defaultMetric);
  }, [defaultMetric]);

  const valuationRangeByMetric = asRecord(comps?.valuation_range_by_metric) ?? {};
  const selectedRange = asRecord(valuationRangeByMetric[selectedMetric]);
  const comparePayload = asRecord(comps?.target_vs_peers);
  const compareRows = Object.keys({ ...(asRecord(comparePayload?.target) ?? {}), ...(asRecord(comparePayload?.peer_medians) ?? {}) }).map((key) => ({
    metric: titleize(key),
    target: (asRecord(comparePayload?.target) ?? {})[key],
    peer_median: (asRecord(comparePayload?.peer_medians) ?? {})[key],
    delta: (asRecord(comparePayload?.deltas) ?? {})[key],
  }));
  const peerRows = asRows(comps?.peers);

  return (
    <section className="page-stack">
      <section className="grid-cards">
        <article className="panel">
          <h2>Peer Set</h2>
          <label className="form-label" htmlFor="comparables-metric">Valuation Metric</label>
          <select id="comparables-metric" className="form-select" value={selectedMetric} onChange={(event) => setSelectedMetric(event.target.value)}>
            {metricOptions.map((option) => (
              <option key={String(option.key)} value={String(option.key)}>
                {formatText(asText(option.label))}
              </option>
            ))}
          </select>
          <p>Primary Metric: {formatText(asText(selectedRange?.label))}</p>
          <p>Raw Peers: {formatMetricValue(asRecord(comps?.peer_counts)?.raw, "count")}</p>
          <p>Clean Peers: {formatMetricValue(asRecord(comps?.peer_counts)?.clean, "count")}</p>
        </article>
        <article className="panel">
          <h2>{formatText(asText(selectedRange?.label))}</h2>
          <p>Bear: {formatCurrency(asNumber(selectedRange?.bear))}</p>
          <p>Base: {formatCurrency(asNumber(selectedRange?.base))}</p>
          <p>Bull: {formatCurrency(asNumber(selectedRange?.bull))}</p>
          <p>Blended Base: {formatCurrency(asNumber(asRecord(comps?.valuation_range)?.blended_base))}</p>
        </article>
        <article className="panel">
          <h2>Market Context</h2>
          <p>Current Price: {formatCurrency(asNumber(asRecord(comps?.target)?.current_price))}</p>
          <p>Analyst Target: {formatCurrency(asNumber((asRows(asRecord(comps?.football_field)?.markers).find((marker) => asText(marker.label) === "Analyst Target Mean") ?? {}).value))}</p>
        </article>
      </section>
      <section className="panel">
        <h2>Target vs Peer Medians</h2>
        {renderValueTable(compareRows, [
          { key: "metric", label: "Metric", kind: "text" },
          { key: "target", label: "Target", kind: "number" },
          { key: "peer_median", label: "Peer Median", kind: "number" },
          { key: "delta", label: "Delta", kind: "number" },
        ])}
      </section>
      <section className="panel">
        <h2>Football Field</h2>
        {renderCategoryBars(asRows(asRecord(comps?.football_field)?.ranges), "base")}
      </section>
      <section className="panel">
        <h2>Peer Table</h2>
        {renderValueTable(peerRows, [
          { key: "ticker", label: "Ticker", kind: "text" },
          { key: "similarity_score", label: "Similarity", kind: "number" },
          { key: "model_weight", label: "Weight", kind: "percent" },
          { key: "tev_ebitda_ltm", label: "TEV / EBITDA LTM", kind: "multiple" },
          { key: "tev_ebit_fwd", label: "TEV / EBIT Fwd", kind: "multiple" },
          { key: "tev_ebit_ltm", label: "TEV / EBIT LTM", kind: "multiple" },
          { key: "pe_ltm", label: "P / E LTM", kind: "multiple" },
          { key: "revenue_growth", label: "Revenue Growth", kind: "percent" },
          { key: "ebit_margin", label: "EBIT Margin", kind: "percent" },
          { key: "net_debt_to_ebitda", label: "Net Debt / EBITDA", kind: "multiple" },
        ])}
      </section>
      <section className="panel">
        <h2>Audit Flags</h2>
        <ul className="clean-list">
          {asRows(comps?.audit_flags).length ? null : null}
          {(Array.isArray(comps?.audit_flags) ? comps?.audit_flags : []).length ? (
            (comps?.audit_flags as unknown[]).map((flag, index) => <li key={`${flag}-${index}`}>{formatText(asText(flag))}</li>)
          ) : (
            <li>No comps audit flags for this run.</li>
          )}
        </ul>
      </section>
    </section>
  );
}

function MultiplesPanel({ comps }: { comps: Record<string, unknown> | null | undefined }) {
  const historicalSummary = asRecord(comps?.historical_multiples_summary);
  const metricsMap = asRecord(historicalSummary?.metrics) ?? {};
  const metricKeys = Object.keys(metricsMap);
  const [selectedMetric, setSelectedMetric] = useState(metricKeys[0] ?? "");
  const [showFullSeries, setShowFullSeries] = useState(false);

  useEffect(() => {
    setSelectedMetric(metricKeys[0] ?? "");
  }, [historicalSummary?.metrics, metricKeys]);

  useEffect(() => {
    setShowFullSeries(false);
  }, [selectedMetric]);

  const payload = asRecord(metricsMap[selectedMetric]);
  const summary = asRecord(payload?.summary);
  const series = asRows(payload?.series);
  const visibleSeries = showFullSeries ? series : series.slice(-24);

  return (
    <section className="page-stack">
      <section className="panel">
        <div className="panel-toolbar">
          <div>
            <h2>Historical Multiples</h2>
            <p className="table-note">Switch the active series and review the current positioning versus history.</p>
          </div>
          <div style={{ minWidth: "240px" }}>
            <label className="form-label" htmlFor="historical-multiple-series">Historical Multiple Series</label>
            <select id="historical-multiple-series" className="form-select" value={selectedMetric} onChange={(event) => setSelectedMetric(event.target.value)}>
              {metricKeys.map((key) => (
                <option key={key} value={key}>
                  {titleize(key)}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="grid-cards">
          <div className="mini-card"><strong>Current</strong><p>{formatMetricValue(summary?.current, "multiple")}</p></div>
          <div className="mini-card"><strong>Median</strong><p>{formatMetricValue(summary?.median, "multiple")}</p></div>
          <div className="mini-card"><strong>Min</strong><p>{formatMetricValue(summary?.min, "multiple")}</p></div>
          <div className="mini-card"><strong>Max</strong><p>{formatMetricValue(summary?.max, "multiple")}</p></div>
          <div className="mini-card"><strong>Current Percentile</strong><p>{formatPercent((asNumber(summary?.current_percentile) ?? 0) * 100)}</p></div>
        </div>
      </section>
      <section className="panel">
        <div className="panel-toolbar">
          <div>
            <h2>Historical Multiple Series</h2>
            <p className="table-note">{summarizeSeriesWindow(series)}</p>
          </div>
          <div className="mini-card">
            <strong>Peer Current Reference</strong>
            <p>{formatMetricValue(summary?.peer_current, "multiple")}</p>
          </div>
        </div>
        {renderTimeSeriesChart(series, {
          xKey: "date",
          xAxisLabel: "Date",
          testId: "time-series-chart-multiples",
          series: [{ key: "multiple", label: titleize(selectedMetric) || "Multiple", color: "#38bdf8", kind: "multiple" }],
        })}
      </section>
      <section className="panel">
        <div className="panel-toolbar">
          <div>
            <h2>Series Table</h2>
            <p className="table-note">{renderSeriesWindowLabel(visibleSeries.length, series.length)}</p>
          </div>
          {series.length > 24 ? (
            <button type="button" className="ghost-button" onClick={() => setShowFullSeries((current) => !current)}>
              {showFullSeries ? "Show recent window" : "Show full history"}
            </button>
          ) : null}
        </div>
        {renderValueTable(visibleSeries, [
          { key: "date", label: "Date", kind: "text" },
          { key: "multiple", label: "Multiple", kind: "multiple" },
          { key: "price", label: "Price", kind: "currency" },
        ])}
      </section>
    </section>
  );
}

function AssumptionsPanel({
  assumptions,
  policy,
  policyRf,
  setPolicyRf,
  policyErp,
  setPolicyErp,
  onSavePolicy,
  policySavePending,
  selections,
  setSelections,
  customValues,
  setCustomValues,
  preview,
  previewPending,
  onPreview,
  onApply,
  applyPending,
  runStatus,
}: {
  assumptions: Record<string, unknown> | null | undefined;
  policy: ValuationPolicyPayload | null | undefined;
  policyRf: number;
  setPolicyRf: Dispatch<SetStateAction<number>>;
  policyErp: number;
  setPolicyErp: Dispatch<SetStateAction<number>>;
  onSavePolicy: () => void;
  policySavePending: boolean;
  selections: Record<string, string>;
  setSelections: Dispatch<SetStateAction<Record<string, string>>>;
  customValues: Record<string, number>;
  setCustomValues: Dispatch<SetStateAction<Record<string, number>>>;
  preview: Record<string, unknown> | null | undefined;
  previewPending: boolean;
  onPreview: () => void;
  onApply: () => void;
  applyPending: boolean;
  runStatus: Record<string, unknown> | null | undefined;
}) {
  const fields = asRows(assumptions?.fields);
  const auditRows = asRows(assumptions?.audit_rows);
  const pendingChanges = asRows(assumptions?.pending_changes);
  return (
    <section className="page-stack">
      <section className="grid-cards">
        <article className="panel"><h2>Current Base IV</h2><p>{formatCurrency(asNumber(assumptions?.current_iv_base))}</p></article>
        <article className="panel"><h2>Current Price</h2><p>{formatCurrency(asNumber(assumptions?.current_price))}</p></article>
        <article className="panel"><h2>Tracked Fields</h2><p>{fields.length}</p></article>
        <article className="panel"><h2>Current Expected IV</h2><p>{formatCurrency(asNumber(assumptions?.current_expected_iv))}</p></article>
      </section>
      <section className="panel">
        <div className="panel-toolbar">
          <div>
            <h2>Policy Defaults</h2>
            <p className="table-note">{formatText(asText(policy?.source_ref ?? "DB valuation policy"))}</p>
          </div>
          <button type="button" className="primary-button" onClick={onSavePolicy} disabled={policySavePending}>
            {policySavePending ? "Saving..." : "Save Policy"}
          </button>
        </div>
        <div className="valuation-form-grid">
          <div>
            <label className="form-label" htmlFor="policy-risk-free-rate">Risk-free rate</label>
            <input
              id="policy-risk-free-rate"
              className="form-input"
              type="number"
              step="0.001"
              value={policyRf}
              onChange={(event) => setPolicyRf(Number(event.target.value))}
            />
          </div>
          <div>
            <label className="form-label" htmlFor="policy-equity-risk-premium">Equity risk premium</label>
            <input
              id="policy-equity-risk-premium"
              className="form-input"
              type="number"
              step="0.001"
              value={policyErp}
              onChange={(event) => setPolicyErp(Number(event.target.value))}
            />
          </div>
        </div>
      </section>
      <section className="panel">
        <h2>Pending Changes</h2>
        {renderValueTable(
          pendingChanges.map((change) => ({
            id: change.change_id,
            field: change.assumption_name,
            current: change.current_value,
            proposed: change.proposed_value,
            source: change.source_ref,
            confidence: change.confidence,
            status: change.status,
          })),
          [
            { key: "id", label: "ID", kind: "number" },
            { key: "field", label: "Field", kind: "text" },
            { key: "current", label: "Current", kind: "number" },
            { key: "proposed", label: "Proposed", kind: "number" },
            { key: "source", label: "Source", kind: "text" },
            { key: "confidence", label: "Confidence", kind: "text" },
            { key: "status", label: "Status", kind: "text" },
          ],
        )}
      </section>
      <section className="stacked-cards">
        {fields.map((field) => {
          const options = ["default", ...(field.agent_value != null ? ["agent"] : []), "custom"];
          const mode = selections[String(field.field)] ?? String(field.initial_mode ?? "default");
          const customValue = customValues[String(field.field)] ?? toDisplayValue(field.effective_value ?? field.baseline_value, asText(field.unit));
          return (
            <article key={String(field.field)} className="panel">
              <div className="valuation-form-grid">
                <div>
                  <h2>{formatText(asText(field.label))}</h2>
                  <p>{formatText(asText(field.field))} · {formatText(asText(field.unit))}</p>
                </div>
                <div>
                  <label className="form-label" htmlFor={`assumption-mode-${String(field.field)}`}>Mode</label>
                  <select
                    id={`assumption-mode-${String(field.field)}`}
                    className="form-select"
                    value={mode}
                    onChange={(event) => setSelections((current) => ({ ...current, [String(field.field)]: event.target.value }))}
                  >
                    {options.map((option) => (
                      <option key={option} value={option}>{titleize(option)}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="form-label" htmlFor={`assumption-custom-${String(field.field)}`}>Custom Value</label>
                  <input
                    id={`assumption-custom-${String(field.field)}`}
                    className="form-input"
                    type="number"
                    step={inputStep(asText(field.unit))}
                    value={customValue}
                    disabled={mode !== "custom"}
                    onChange={(event) => setCustomValues((current) => ({ ...current, [String(field.field)]: Number(event.target.value) }))}
                  />
                </div>
              </div>
              <div className="grid-cards">
                <div className="mini-card">
                  <strong>Effective</strong>
                  <p>{formatAssumptionValue(field.effective_value, asText(field.unit))}</p>
                  <span>{formatText(asText(field.effective_source))}</span>
                </div>
                <div className="mini-card">
                  <strong>Default</strong>
                  <p>{formatAssumptionValue(field.baseline_value, asText(field.unit))}</p>
                  <span>{formatText(asText(field.baseline_source))}</span>
                </div>
                <div className="mini-card">
                  <strong>Agent</strong>
                  <p>{formatAssumptionValue(field.agent_value, asText(field.unit))}</p>
                  <span>{formatText(asText(field.agent_name))} · {formatText(asText(field.agent_confidence))}</span>
                </div>
              </div>
            </article>
          );
        })}
      </section>
      <section className="action-controls">
        <button type="button" className="ghost-button" onClick={onPreview} disabled={previewPending}>
          {previewPending ? "Previewing..." : "Preview Assumptions"}
        </button>
        <button type="button" className="primary-button" onClick={onApply} disabled={applyPending}>
          {applyPending ? "Queueing..." : "Apply Assumptions"}
        </button>
      </section>
      {preview ? (
        <section className="panel">
          <h2>Preview Delta</h2>
          <div className="grid-cards">
            {["bear", "base", "bull", "expected"].map((scenario) => {
              const proposed =
                scenario === "expected"
                  ? asNumber(preview.proposed_expected_iv)
                  : asNumber((asRecord(preview.proposed_iv) ?? {})[scenario]);
              const delta =
                scenario === "expected"
                  ? ((asNumber(preview.current_expected_iv) ?? 0) > 0 && proposed != null && asNumber(preview.current_expected_iv) != null
                    ? ((proposed / (asNumber(preview.current_expected_iv) ?? 1)) - 1) * 100
                    : null)
                  : asNumber((asRecord(preview.delta_pct) ?? {})[scenario]);
              return (
                <div key={scenario} className="mini-card">
                  <strong>{titleize(scenario)} IV</strong>
                  <p>{formatCurrency(proposed)}</p>
                  <span>{formatPercent(delta)}</span>
                </div>
              );
            })}
          </div>
          <h3>Resolved Values</h3>
          {renderValueTable(
            Object.entries(asRecord(preview.resolved_values) ?? {}).map(([field, meta]) => ({
              field,
              mode: asRecord(meta)?.mode,
              effective_before: asRecord(meta)?.effective_value,
              applied_value: asRecord(meta)?.value,
            })),
            [
              { key: "field", label: "Field", kind: "text" },
              { key: "mode", label: "Mode", kind: "text" },
              { key: "effective_before", label: "Before", kind: "number" },
              { key: "applied_value", label: "Applied", kind: "number" },
            ],
          )}
        </section>
      ) : null}
      <section className="panel">
        <h2>Audit History</h2>
        {renderValueTable(auditRows, Object.keys(auditRows[0] ?? { field: "", mode: "", action: "" }).map((key) => ({ key, label: titleize(key), kind: "text" })))}
      </section>
      {runStatus ? (
        <div className="run-status">
          <strong>{formatText(asText(runStatus.status))}</strong>
          <span>{formatText(asText(runStatus.message))}</span>
        </div>
      ) : null}
    </section>
  );
}

function WaccPanel({
  wacc,
  mode,
  setMode,
  selectedMethod,
  setSelectedMethod,
  weights,
  setWeights,
  preview,
  onPreview,
  onApply,
  previewPending,
  applyPending,
  runStatus,
}: {
  wacc: Record<string, unknown> | null | undefined;
  mode: string;
  setMode: Dispatch<SetStateAction<string>>;
  selectedMethod: string;
  setSelectedMethod: Dispatch<SetStateAction<string>>;
  weights: Record<string, number>;
  setWeights: Dispatch<SetStateAction<Record<string, number>>>;
  preview: WaccPreviewPayload | null | undefined;
  onPreview: () => void;
  onApply: () => void;
  previewPending: boolean;
  applyPending: boolean;
  runStatus: Record<string, unknown> | null | undefined;
}) {
  const methods = asRows(wacc?.methods);
  const auditRows = asRows(wacc?.audit_rows);
  const weightSum = Object.values(weights).reduce((sum, value) => sum + (Number.isFinite(value) ? value : 0), 0);
  const methodRows = methods.map((method) => ({
    ...method,
    wacc: asNumber(method.wacc) == null ? null : (asNumber(method.wacc) ?? 0) * 100,
    cost_of_equity: asNumber(method.cost_of_equity) == null ? null : (asNumber(method.cost_of_equity) ?? 0) * 100,
    cost_of_debt_after_tax: asNumber(method.cost_of_debt_after_tax) == null ? null : (asNumber(method.cost_of_debt_after_tax) ?? 0) * 100,
  }));
  const auditTableRows = auditRows.map((row) => ({
    created_at: row.event_ts ?? row.created_at,
    selected_method: row.selected_method ?? row.mode,
    expected_method_wacc: asNumber(row.effective_wacc) == null ? null : (asNumber(row.effective_wacc) ?? 0) * 100,
    wacc: asNumber(asRecord(row.preview)?.current_wacc) == null ? null : (asNumber(asRecord(row.preview)?.current_wacc) ?? 0) * 100,
  }));

  return (
    <section className="page-stack">
      <section className="grid-cards">
        <article className="panel"><h2>Current WACC</h2><p>{formatPercent(asNumber(wacc?.current_wacc) == null ? null : (asNumber(wacc?.current_wacc) ?? 0) * 100)}</p></article>
        <article className="panel"><h2>Proposed WACC</h2><p>{formatPercent(asNumber(wacc?.proposed_wacc) == null ? null : (asNumber(wacc?.proposed_wacc) ?? 0) * 100)}</p></article>
        <article className="panel"><h2>Method</h2><p>{titleize(asText(wacc?.method))}</p></article>
      </section>
      <section className="panel">
        <h2>Methodology mode</h2>
        <div className="action-controls">
          <button type="button" className={mode === "single_method" ? "primary-button" : "ghost-button"} onClick={() => setMode("single_method")}>Single Method</button>
          <button type="button" className={mode === "blended" ? "primary-button" : "ghost-button"} onClick={() => setMode("blended")}>Blended</button>
        </div>
        {mode === "single_method" ? (
          <>
            <label className="form-label" htmlFor="wacc-method">Method</label>
            <select id="wacc-method" className="form-select" value={selectedMethod} onChange={(event) => setSelectedMethod(event.target.value)}>
              {methods.map((method) => (
                <option key={String(method.method)} value={String(method.method)}>{titleize(asText(method.method))}</option>
              ))}
            </select>
          </>
        ) : (
          <div className="grid-cards">
            {methods.map((method) => (
              <div key={String(method.method)} className="mini-card">
                <strong>{titleize(asText(method.method))}</strong>
                <label className="form-label" htmlFor={`weight-${String(method.method)}`}>Weight</label>
                <input
                  id={`weight-${String(method.method)}`}
                  className="form-input"
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  value={weights[String(method.method)] ?? 0}
                  onChange={(event) => setWeights((current) => ({ ...current, [String(method.method)]: Number(event.target.value) }))}
                />
              </div>
            ))}
            <div className="mini-card"><strong>Weight Sum</strong><p>{weightSum.toFixed(2)}</p></div>
          </div>
        )}
      </section>
      <section className="panel">
        <h2>Available Methods</h2>
        {renderValueTable(methodRows, [
          { key: "method", label: "Method", kind: "text" },
          { key: "wacc", label: "WACC", kind: "percent" },
          { key: "cost_of_equity", label: "Cost Of Equity", kind: "percent" },
          { key: "cost_of_debt_after_tax", label: "Cost Of Debt After Tax", kind: "percent" },
          { key: "beta_value", label: "Beta", kind: "number" },
          { key: "beta_source", label: "Beta Source", kind: "text" },
        ])}
      </section>
      <section className="action-controls">
        <button type="button" className="ghost-button" onClick={onPreview} disabled={previewPending}>
          {previewPending ? "Previewing..." : "Preview WACC Selection"}
        </button>
        <button type="button" className="primary-button" onClick={onApply} disabled={applyPending}>
          {applyPending ? "Queueing..." : "Apply WACC Selection"}
        </button>
      </section>
      {preview ? (
        <section className="grid-cards">
          <article className="panel"><h2>Current WACC</h2><p>{formatPercent((asNumber(preview.current_wacc) ?? 0) * 100)}</p></article>
          <article className="panel"><h2>Proposed WACC</h2><p>{formatPercent((asNumber(preview.effective_wacc) ?? 0) * 100)}</p></article>
          <article className="panel"><h2>Current Base IV</h2><p>{formatCurrency(asNumber((asRecord(preview.current_iv) ?? {}).base))}</p></article>
          <article className="panel"><h2>Proposed Base IV</h2><p>{formatCurrency(asNumber((asRecord(preview.proposed_iv) ?? {}).base))}</p></article>
        </section>
      ) : null}
      <section className="panel">
        <h2>WACC Audit History</h2>
        {renderValueTable(auditTableRows, [
          { key: "created_at", label: "Created", kind: "text" },
          { key: "selected_method", label: "Method", kind: "text" },
          { key: "expected_method_wacc", label: "Expected WACC", kind: "percent" },
          { key: "wacc", label: "Current WACC", kind: "percent" },
        ])}
      </section>
      {runStatus ? (
        <div className="run-status">
          <strong>{formatText(asText(runStatus.status))}</strong>
          <span>{formatText(asText(runStatus.message))}</span>
        </div>
      ) : null}
    </section>
  );
}

function RecommendationsPanel({
  recommendations,
  selectedFields,
  setSelectedFields,
  preview,
  onPreview,
  onApply,
  previewPending,
  applyPending,
  runStatus,
}: {
  recommendations: RecommendationsPayload | undefined;
  selectedFields: string[];
  setSelectedFields: Dispatch<SetStateAction<string[]>>;
  preview: RecommendationsPreviewPayload | null | undefined;
  onPreview: () => void;
  onApply: () => void;
  previewPending: boolean;
  applyPending: boolean;
  runStatus: Record<string, unknown> | null | undefined;
}) {
  const recs = recommendations?.recommendations ?? [];
  const grouped = recs.reduce<Record<string, Record<string, unknown>[]>>((acc, rec) => {
    const agent = String(rec.agent ?? "other");
    acc[agent] = acc[agent] ?? [];
    acc[agent].push(rec);
    return acc;
  }, {});
  const agentLabels: Record<string, string> = {
    qoe: "Quality of Earnings",
    accounting_recast: "Accounting Recast",
    industry: "Industry",
    filings: "Filings Cross-Check",
  };

  return (
    <section className="page-stack">
      <section className="panel">
        <h2>Recommendations</h2>
        <p>Current base IV: {formatCurrency(asNumber(recommendations?.current_iv_base))} · Generated: {formatDateLabel(asText(recommendations?.generated_at))}</p>
      </section>
      {Object.entries(grouped).map(([agent, items]) => (
        <section key={agent} className="panel">
          <h2>{agentLabels[agent] ?? titleize(agent)}</h2>
          <div className="stacked-cards">
            {items.map((rec, index) => (
              <div key={`${agent}-${String(rec.field)}-${index}`} className="mini-card">
                <strong>{titleize(asText(rec.field))}</strong>
                <p>{formatText(asText(rec.rationale))}</p>
                <span>{formatText(asText(rec.citation))}</span>
                <p>Current → Proposed: {formatAssumptionValue(rec.current_value, null)} → {formatAssumptionValue(rec.proposed_value, null)}</p>
                <p>Confidence: {formatText(asText(rec.confidence))} · Source: {titleize(asText(rec.agent))} · Status: {formatText(asText(rec.status))}</p>
              </div>
            ))}
          </div>
        </section>
      ))}
      <section className="panel">
        <h2>What-If Preview</h2>
        <div className="stacked-cards">
          {recs.filter((rec) => asText(rec.status) === "pending").map((rec, index) => {
            const field = String(rec.field);
            const checked = selectedFields.includes(field);
            return (
              <label key={`${field}-${index}`} className="checkbox-row">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(event) =>
                    setSelectedFields((current) =>
                      event.target.checked ? [...current, field] : current.filter((value) => value !== field),
                    )
                  }
                />
                <span>{titleize(asText(rec.field))}</span>
              </label>
            );
          })}
        </div>
        <div className="action-controls">
          <button type="button" className="ghost-button" onClick={onPreview} disabled={previewPending}>
            {previewPending ? "Previewing..." : "Preview IV with selected approvals"}
          </button>
          <button type="button" className="primary-button" onClick={onApply} disabled={applyPending}>
            {applyPending ? "Queueing..." : "Apply Approved → valuation_overrides.yaml"}
          </button>
        </div>
        {preview ? (
          <div className="grid-cards">
            {["bear", "base", "bull"].map((scenario) => (
              <div key={scenario} className="mini-card">
                <strong>{titleize(scenario)} IV</strong>
                <p>{formatCurrency(asNumber((asRecord(preview.proposed_iv) ?? {})[scenario]))}</p>
                <span>{formatPercent(asNumber((asRecord(preview.delta_pct) ?? {})[scenario]))}</span>
              </div>
            ))}
          </div>
        ) : null}
      </section>
      {runStatus ? (
        <div className="run-status">
          <strong>{formatText(asText(runStatus.status))}</strong>
          <span>{formatText(asText(runStatus.message))}</span>
        </div>
      ) : null}
    </section>
  );
}

type PMQueueRunCard = {
  profile_name: string;
  status: string;
  reason?: string | null;
  observation_count?: number | null;
  queue_item_count?: number | null;
  errors?: AgenticHandoffRunError[];
  source_quality?: EvidenceSourceQuality | null;
};

function formatRunStatusLabel(status: string | null | undefined): string {
  switch (status) {
    case "completed_with_items":
      return "Completed With Queue Items";
    case "completed_no_items":
      return "Completed Without Queue Items";
    case "not_runnable":
      return "Not Runnable";
    default:
      return titleize(status);
  }
}

function runStatusBadgeStyle(status: string | null | undefined) {
  const common = {
    display: "inline-flex",
    alignItems: "center",
    gap: "6px",
    borderRadius: "999px",
    padding: "6px 12px",
    fontSize: "11px",
    fontWeight: "700",
    letterSpacing: "0.08em",
    textTransform: "uppercase" as const,
  };

  switch (status) {
    case "completed_with_items":
      return { ...common, color: "#fcd34d", border: "1px solid rgba(245, 158, 11, 0.45)", background: "rgba(245, 158, 11, 0.12)" };
    case "completed_no_items":
      return { ...common, color: "#86efac", border: "1px solid rgba(34, 197, 94, 0.45)", background: "rgba(34, 197, 94, 0.12)" };
    case "blocked":
      return { ...common, color: "#fca5a5", border: "1px solid rgba(239, 68, 68, 0.45)", background: "rgba(239, 68, 68, 0.12)" };
    case "failed":
      return { ...common, color: "#fb7185", border: "1px solid rgba(244, 63, 94, 0.45)", background: "rgba(244, 63, 94, 0.12)" };
    case "not_runnable":
      return { ...common, color: "#c4b5fd", border: "1px solid rgba(139, 92, 246, 0.45)", background: "rgba(139, 92, 246, 0.12)" };
    default:
      return { ...common, color: "#cbd5e1", border: "1px solid rgba(148, 163, 184, 0.35)", background: "rgba(148, 163, 184, 0.12)" };
  }
}

function sourceQualityBadgeStyle(sourceQuality: EvidenceSourceQuality | null | undefined) {
  const common = {
    display: "inline-flex",
    alignItems: "center",
    borderRadius: "999px",
    padding: "4px 10px",
    fontSize: "11px",
    fontWeight: "700",
    letterSpacing: "0.08em",
    textTransform: "uppercase" as const,
  };
  switch (sourceQuality) {
    case "real":
      return { ...common, color: "#86efac", border: "1px solid rgba(34, 197, 94, 0.4)", background: "rgba(34, 197, 94, 0.12)" };
    case "partial":
      return { ...common, color: "#fcd34d", border: "1px solid rgba(245, 158, 11, 0.4)", background: "rgba(245, 158, 11, 0.12)" };
    case "placeholder":
      return { ...common, color: "#fca5a5", border: "1px solid rgba(239, 68, 68, 0.4)", background: "rgba(239, 68, 68, 0.12)" };
    default:
      return { ...common, color: "#cbd5e1", border: "1px solid rgba(148, 163, 184, 0.3)", background: "rgba(148, 163, 184, 0.12)" };
  }
}

function proposalSummaryValue(proposal: Record<string, unknown>): string {
  const mode = asText(proposal.proposal_mode);
  const target = asNumber(proposal.proposed_target_value);
  const delta = asNumber(proposal.proposed_delta);
  if (mode === "delta" && delta != null) {
    return `${delta >= 0 ? "+" : ""}${delta.toFixed(3)} delta`;
  }
  if (target != null) {
    return target.toFixed(3);
  }
  return "—";
}

function ProposalPackCard({
  title,
  pack,
  accentColor,
}: {
  title: string;
  pack: Record<string, unknown> | null | undefined;
  accentColor: string;
}) {
  const proposals = asRows(asRecord(pack)?.proposals);
  if (!proposals.length) {
    return (
      <div
        className="mini-card"
        style={{ border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.02)", minHeight: "100%" }}
      >
        <strong style={{ color: accentColor }}>{title}</strong>
        <p style={{ marginBottom: 0, opacity: 0.7 }}>No proposal stored.</p>
      </div>
    );
  }

  return (
    <div
      className="mini-card"
      style={{
        border: `1px solid ${accentColor}33`,
        boxShadow: `inset 0 0 0 1px ${accentColor}1f`,
        background: "linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.015))",
        minHeight: "100%",
      }}
    >
      <strong style={{ color: accentColor }}>{title}</strong>
      <div style={{ display: "grid", gap: "10px", marginTop: "12px" }}>
        {proposals.map((proposal, index) => (
          <div
            key={`${title}-${String(proposal.assumption_name ?? index)}-${index}`}
            style={{ borderLeft: `3px solid ${accentColor}`, paddingLeft: "10px", display: "grid", gap: "4px" }}
          >
            <span style={{ fontSize: "11px", letterSpacing: "0.08em", textTransform: "uppercase", opacity: 0.6 }}>
              {titleize(asText(proposal.assumption_name))}
            </span>
            <strong>{proposalSummaryValue(proposal)}</strong>
            <span style={{ fontSize: "12px", opacity: 0.7 }}>Mode: {titleize(asText(proposal.proposal_mode))}</span>
            {asText(proposal.rationale) ? <span style={{ fontSize: "12px", opacity: 0.78 }}>{asText(proposal.rationale)}</span> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function PMQueuePanel({
  queuePayload,
  evidencePackets,
  statusFilter,
  setStatusFilter,
  editableValues,
  setEditableValues,
  profileRunCards,
  previewedItemIds,
  onRunProfile,
  onPreview,
  onEdit,
  onApprove,
  onReject,
  onDefer,
  previewPayload,
  actionPending,
}: {
  queuePayload: PMDecisionQueueListPayload | undefined;
  evidencePackets: EvidencePacketSummary[];
  statusFilter: string;
  setStatusFilter: Dispatch<SetStateAction<string>>;
  editableValues: Record<number, string>;
  setEditableValues: Dispatch<SetStateAction<Record<number, string>>>;
  profileRunCards: PMQueueRunCard[];
  previewedItemIds: number[];
  onRunProfile: (profileName: string) => void;
  onPreview: (itemId: number) => void;
  onEdit: (itemId: number, proposalPack: Record<string, unknown>) => void;
  onApprove: (itemId: number) => void;
  onReject: (itemId: number, reason: string) => void;
  onDefer: (itemId: number, reason: string) => void;
  previewPayload: PMDecisionQueuePreviewPayload | null | undefined;
  actionPending: boolean;
}) {
  const items = queuePayload?.items ?? [];
  const profiles = ["earnings_update", "company_analysis", "industry_analysis", "comps_analysis", "risk_review", "valuation_review"];

  const [itemTypeFilter, setItemTypeFilter] = useState<string>("all");
  const [importanceFilter, setImportanceFilter] = useState<string>("all");
  const [sourceQualityFilter, setSourceQualityFilter] = useState<string>("all");
  const [impactFilter, setImpactFilter] = useState<string>("all");
  const [confidenceFilter, setConfidenceFilter] = useState<string>("all");
  const [expandedItems, setExpandedItems] = useState<Record<number, boolean>>({});

  const packetById = useMemo(() => {
    const map = new Map<string, EvidencePacketSummary>();
    for (const packet of evidencePackets) {
      if (packet.packet_id != null) {
        map.set(String(packet.packet_id), packet);
      }
    }
    return map;
  }, [evidencePackets]);

  const anchorMap = useMemo(() => {
    const map = new Map<string, { type: string; label: string; content: string }>();
    for (const packet of evidencePackets) {
      for (const snippet of packet.snippets ?? []) {
        const snippetId = String(snippet.snippet_id || "");
        if (snippetId) {
          map.set(snippetId, {
            type: "Snippet",
            label: `Snippet: ${snippetId}`,
            content: String(snippet.text || ""),
          });
        }
      }
      for (const fact of packet.facts ?? []) {
        const factId = String(fact.fact_id || "");
        if (factId) {
          const unitText = fact.unit ? ` (${String(fact.unit)})` : "";
          map.set(factId, {
            type: "Fact",
            label: `Fact: ${String(fact.fact_name || "")}`,
            content: `${String(fact.value ?? "")}${unitText}`,
          });
        }
      }
      for (const sourceRef of packet.source_refs ?? []) {
        const sourceRefId = String(sourceRef.source_ref_id || "");
        if (sourceRefId) {
          map.set(sourceRefId, {
            type: "Source",
            label: `Source: ${String(sourceRef.source_label || "")}`,
            content: `${String(sourceRef.source_kind || "")} @ ${String(sourceRef.source_locator || "")}`,
          });
        }
      }
    }
    return map;
  }, [evidencePackets]);

  const filteredItems = items.filter((item) => {
    const statusMatch = statusFilter === "all" || String(item.status) === statusFilter;
    const typeMatch = itemTypeFilter === "all" || String(item.item_type) === itemTypeFilter;
    const importanceMatch = importanceFilter === "all" || String(item.qualitative_importance || "low") === importanceFilter;
    const impactMatch = impactFilter === "all" || String(item.valuation_impact_bucket || "low") === impactFilter;
    const confidenceMatch =
      confidenceFilter === "all" ||
      String(item.pm_confidence || item.translator_confidence || item.agent_confidence || "low") === confidenceFilter;
    const packetQualities = item.evidence_packet_ids
      .map((packetId) => packetById.get(String(packetId))?.run_metadata?.source_quality)
      .filter(Boolean);
    const sourceQualityMatch = sourceQualityFilter === "all" || packetQualities.includes(sourceQualityFilter as EvidenceSourceQuality);
    return statusMatch && typeMatch && importanceMatch && impactMatch && confidenceMatch && sourceQualityMatch;
  });

  const getQueueStatusBadgeStyle = (status: string | null) => {
    const common = {
      display: "inline-flex",
      alignItems: "center",
      gap: "6px",
      borderRadius: "999px",
      padding: "4px 10px",
      fontSize: "11px",
      fontWeight: "700",
      textTransform: "uppercase" as const,
      letterSpacing: "0.08em",
    };
    switch (status) {
      case "approved":
        return { ...common, border: "1px solid rgba(16, 185, 129, 0.45)", color: "#86efac", background: "rgba(16, 185, 129, 0.12)" };
      case "pending":
        return { ...common, border: "1px solid rgba(245, 158, 11, 0.45)", color: "#fcd34d", background: "rgba(245, 158, 11, 0.12)" };
      case "rejected":
        return { ...common, border: "1px solid rgba(239, 68, 68, 0.45)", color: "#fca5a5", background: "rgba(239, 68, 68, 0.12)" };
      case "deferred":
        return { ...common, border: "1px solid rgba(59, 130, 246, 0.45)", color: "#93c5fd", background: "rgba(59, 130, 246, 0.12)" };
      default:
        return { ...common, border: "1px solid rgba(148, 163, 184, 0.35)", color: "#cbd5e1", background: "rgba(148, 163, 184, 0.12)" };
    }
  };

  const getImportanceBadgeStyle = (importance: string | null) => {
    const common = {
      display: "inline-flex",
      alignItems: "center",
      borderRadius: "999px",
      padding: "4px 10px",
      fontSize: "11px",
      fontWeight: "700",
      textTransform: "uppercase" as const,
      letterSpacing: "0.08em",
    };
    switch (importance) {
      case "high":
        return { ...common, color: "#fdba74", background: "rgba(249, 115, 22, 0.15)" };
      case "medium":
        return { ...common, color: "#fde68a", background: "rgba(234, 179, 8, 0.15)" };
      default:
        return { ...common, color: "#cbd5e1", background: "rgba(148, 163, 184, 0.15)" };
    }
  };

  const toggleExpand = (itemId: number) => {
    setExpandedItems((prev) => ({ ...prev, [itemId]: !prev[itemId] }));
  };

  const previewedSet = useMemo(() => new Set(previewedItemIds), [previewedItemIds]);
  const conflictGroups = queuePayload?.conflict_groups ?? [];

  return (
    <section className="page-stack">
      <section className="panel">
        <div style={{ display: "flex", justifyContent: "space-between", gap: "16px", flexWrap: "wrap", alignItems: "flex-end" }}>
          <div style={{ maxWidth: "760px" }}>
            <h2>Run Agentic Handoff Profiles</h2>
            <p style={{ opacity: 0.8, fontSize: "14px", marginBottom: 0 }}>
              Each profile stays inside the observation boundary: deterministic evidence in, anchored observations out, deterministic queue translation after that.
            </p>
          </div>
          <div style={{ fontSize: "12px", opacity: 0.65 }}>Statuses stay visible until a fresh run replaces them.</div>
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))",
            gap: "14px",
            marginTop: "16px",
          }}
        >
          {profiles.map((profileName) => {
            const runCard = profileRunCards.find((card) => card.profile_name === profileName);
            const status = runCard?.status ?? "not_run";
            return (
              <article
                key={profileName}
                className="mini-card"
                style={{
                  border: "1px solid rgba(255,255,255,0.08)",
                  background: "linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.015))",
                  minHeight: "100%",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", alignItems: "flex-start" }}>
                  <div>
                    <strong>{titleize(profileName)}</strong>
                    <div style={{ fontSize: "12px", opacity: 0.62, marginTop: "4px" }}>Observation profile</div>
                  </div>
                  <span style={runStatusBadgeStyle(status)}>{status === "not_run" ? "Not Run" : formatRunStatusLabel(status)}</span>
                </div>
                <div style={{ display: "grid", gap: "8px", marginTop: "14px", fontSize: "13px" }}>
                  <div style={{ display: "flex", gap: "12px", flexWrap: "wrap" }}>
                    <span>Observations: {runCard?.observation_count ?? 0}</span>
                    <span>Queue items: {runCard?.queue_item_count ?? 0}</span>
                  </div>
                  {runCard?.source_quality ? (
                    <div>
                      <span style={sourceQualityBadgeStyle(runCard.source_quality)}>Source Quality: {runCard.source_quality}</span>
                    </div>
                  ) : null}
                  {runCard?.reason ? <div style={{ opacity: 0.75 }}>{titleize(runCard.reason)}</div> : null}
                  {runCard?.errors?.length ? (
                    <div style={{ display: "grid", gap: "6px" }}>
                      {runCard.errors.slice(0, 2).map((error, index) => (
                        <div key={`${profileName}-error-${index}`} style={{ borderLeft: "3px solid rgba(244, 63, 94, 0.7)", paddingLeft: "10px", opacity: 0.84 }}>
                          <strong>{formatText(asText(error.agent) ?? asText(error.code) ?? "Run error")}</strong>
                          <div>{formatText(asText(error.message))}</div>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
                <div style={{ marginTop: "16px" }}>
                  <button type="button" className="ghost-button" onClick={() => onRunProfile(profileName)} disabled={actionPending}>
                    Run {titleize(profileName)}
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section className="panel">
        <div style={{ display: "flex", justifyContent: "space-between", gap: "16px", flexWrap: "wrap", alignItems: "flex-end" }}>
          <div>
            <h2>Evidence Packets</h2>
            <p style={{ opacity: 0.8, fontSize: "14px", marginBottom: 0 }}>
              {evidencePackets.length} evidence packets stored in SQLite, including source quality and persisted observation outcomes.
            </p>
          </div>
        </div>
        {evidencePackets.length === 0 ? (
          <div className="mini-card" style={{ marginTop: "14px", textAlign: "center", padding: "28px", opacity: 0.68 }}>
            No evidence packets yet. Run a profile with real local data to materialize a reviewable packet.
          </div>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: "14px",
              marginTop: "14px",
            }}
          >
            {evidencePackets.slice(0, 8).map((packet, index) => {
              const runMetadata = (packet.run_metadata ?? {}) as EvidencePacketRunMetadata;
              const sourceQuality = runMetadata.source_quality;
              return (
                <div
                  key={`${String(packet.packet_id ?? index)}-${index}`}
                  className="mini-card"
                  style={{
                    borderLeft: "4px solid rgba(255,255,255,0.18)",
                    background: "linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.015))",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", alignItems: "flex-start" }}>
                    <strong>{titleize(packet.packet_kind)}</strong>
                    <span style={sourceQualityBadgeStyle(sourceQuality)}>{sourceQuality ?? "unknown"}</span>
                  </div>
                  <p style={{ marginBottom: "10px" }}>Profile: {titleize(packet.profile_name)}</p>
                  <div style={{ display: "grid", gap: "6px", fontSize: "12px", opacity: 0.76 }}>
                    <span>Generated: {formatDateLabel(packet.generated_at)}</span>
                    <span>Observations: {packet.observations?.length ?? 0}</span>
                    <span>Facts: {packet.facts?.length ?? 0}</span>
                    <span>Snippets: {packet.snippets?.length ?? 0}</span>
                    {runMetadata.status ? <span>Status: {formatRunStatusLabel(runMetadata.status)}</span> : null}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className="panel">
        <h2>PM Queue / Insights</h2>
        <div
          className="action-controls"
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: "16px",
            background: "rgba(255,255,255,0.02)",
            padding: "16px",
            borderRadius: "12px",
            border: "1px solid rgba(255,255,255,0.05)",
            marginBottom: "20px",
          }}
        >
          <label className="field-input" style={{ flex: "1 1 150px" }}>
            <span>Status Filter</span>
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="all">All</option>
              <option value="pending">Pending</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
              <option value="deferred">Deferred</option>
            </select>
          </label>

          <label className="field-input" style={{ flex: "1 1 150px" }}>
            <span>Item Type Filter</span>
            <select value={itemTypeFilter} onChange={(event) => setItemTypeFilter(event.target.value)}>
              <option value="all">All Types</option>
              <option value="advisory_finding">Advisory Finding</option>
              <option value="assumption_change_pack">Assumption Change Pack</option>
            </select>
          </label>

          <label className="field-input" style={{ flex: "1 1 150px" }}>
            <span>Importance Filter</span>
            <select value={importanceFilter} onChange={(event) => setImportanceFilter(event.target.value)}>
              <option value="all">All Importance</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </label>

          <label className="field-input" style={{ flex: "1 1 150px" }}>
            <span>Source Quality</span>
            <select value={sourceQualityFilter} onChange={(event) => setSourceQualityFilter(event.target.value)}>
              <option value="all">All Sources</option>
              <option value="real">Real</option>
              <option value="partial">Partial</option>
              <option value="placeholder">Placeholder</option>
            </select>
          </label>

          <label className="field-input" style={{ flex: "1 1 150px" }}>
            <span>Impact Bucket</span>
            <select value={impactFilter} onChange={(event) => setImpactFilter(event.target.value)}>
              <option value="all">All Impact</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </label>

          <label className="field-input" style={{ flex: "1 1 150px" }}>
            <span>Confidence</span>
            <select value={confidenceFilter} onChange={(event) => setConfidenceFilter(event.target.value)}>
              <option value="all">All Confidence</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </label>
        </div>

        <div
          className="mini-card"
          style={{
            marginBottom: "18px",
            background: "rgba(255,255,255,0.018)",
            border: "1px solid rgba(255,255,255,0.07)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", flexWrap: "wrap" }}>
            <div>
              <strong>Conflicts / Shared Drivers</strong>
              <p style={{ margin: "6px 0 0 0", opacity: 0.72, fontSize: "13px" }}>
                Queue items are grouped when multiple profiles touch the same deterministic assumption.
              </p>
            </div>
            <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap", fontSize: "12px" }}>
              <span style={sourceQualityBadgeStyle("real")}>real</span>
              <span style={sourceQualityBadgeStyle("partial")}>partial</span>
              <span style={sourceQualityBadgeStyle("placeholder")}>placeholder</span>
            </div>
          </div>
          {conflictGroups.length === 0 ? (
            <div style={{ marginTop: "12px", opacity: 0.62, fontSize: "13px" }}>No shared-driver clusters in the active pending queue.</div>
          ) : (
            <div style={{ display: "grid", gap: "10px", marginTop: "14px" }}>
              {conflictGroups.map((group) => (
                <div
                  key={group.group_id}
                  style={{
                    padding: "12px",
                    borderRadius: "10px",
                    border: group.conflict_level === "conflict" ? "1px solid rgba(245, 158, 11, 0.35)" : "1px solid rgba(96, 165, 250, 0.22)",
                    background: group.conflict_level === "conflict" ? "rgba(245, 158, 11, 0.08)" : "rgba(96, 165, 250, 0.06)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", flexWrap: "wrap" }}>
                    <strong>{titleize(group.assumption_name)}</strong>
                    <span style={{ fontSize: "12px", opacity: 0.75 }}>
                      {group.proposal_count} proposals · {group.profile_names.map(titleize).join(", ")}
                    </span>
                  </div>
                  <p style={{ margin: "6px 0 10px 0", opacity: 0.78, fontSize: "13px" }}>{group.review_note}</p>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "8px" }}>
                    {group.entries.map((entry) => (
                      <div key={`${group.group_id}-${entry.item_id}-${entry.profile_name}`} style={{ fontSize: "12px", padding: "8px", borderRadius: "8px", background: "rgba(0,0,0,0.18)" }}>
                        <strong>#{entry.item_id} · {titleize(String(entry.profile_name ?? ""))}</strong>
                        <div style={{ opacity: 0.76 }}>{titleize(String(entry.proposal_mode ?? ""))}: {entry.proposed_value == null ? "—" : entry.proposed_value}</div>
                        <div style={{ opacity: 0.6 }}>Status: {titleize(String(entry.status ?? ""))}</div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {filteredItems.length === 0 ? (
          <div className="mini-card" style={{ textAlign: "center", padding: "32px", opacity: 0.68 }}>
            No queue items match the active filters. Real evidence without approved translator output will keep the queue empty by design.
          </div>
        ) : (
          <div className="stacked-cards">
            {filteredItems.map((item) => {
              const itemId = Number(item.item_id ?? 0);
              const itemType = asText(item.item_type);
              const status = asText(item.status);
              const importance = asText(item.qualitative_importance || "low");
              const proposalPack = asRecord(item.proposal_pack);
              const editedPack = asRecord(item.pm_edited_proposal_pack);
              const approvedPack = asRecord(item.approved_proposal_pack);
              const activePack = editedPack ?? proposalPack;
              const activeProposals = asRows(activePack?.proposals);
              const firstProposal = activeProposals[0] ?? null;
              const anchorList = item.evidence_anchor_ids.map((anchor) => String(anchor));
              const previewAnchors = anchorList.slice(0, 2);
              const extraAnchorCount = Math.max(anchorList.length - previewAnchors.length, 0);
              const packetIds = item.evidence_packet_ids.map((packetId) => String(packetId));
              const relatedPackets = packetIds.map((packetId) => packetById.get(packetId)).filter(Boolean) as EvidencePacketSummary[];
              const packetQualities = Array.from(
                new Set(
                  relatedPackets
                    .map((packet) => packet.run_metadata?.source_quality)
                    .filter((quality): quality is EvidenceSourceQuality => Boolean(quality)),
                ),
              );
              const sourceQuality = packetQualities.length === 1 ? packetQualities[0] : packetQualities[0] ?? null;
              const defaultEditable = asNumber(firstProposal?.proposed_target_value) ?? asNumber(firstProposal?.proposed_delta) ?? null;
              const editableValue = editableValues[itemId] ?? (defaultEditable == null ? "" : `${defaultEditable}`);
              const isExpanded = expandedItems[itemId] || false;
              const requiresPreview = itemType === "assumption_change_pack" && activeProposals.length > 0;
              const previewReady = previewedSet.has(itemId);
              const previewForItem = previewPayload?.item_id === itemId ? previewPayload : null;
              const previewSkippedFields = previewForItem?.skipped_fields ?? asTextArray(asRecord(item.adapter_links)?.skipped_fields);
              const approvedValues = asRows(approvedPack?.proposals);
              const observationId = asText(asRecord(item.metadata)?.observation_id);
              const relatedObservations = relatedPackets.flatMap((packet) =>
                (packet.observations ?? []).filter((observation) => {
                  if (observationId && observation.observation_id === observationId) {
                    return true;
                  }
                  return observation.evidence_anchor_ids.some((anchor) => anchorList.includes(anchor));
                }),
              );
              const decisionHistory = item.decision_history ?? [];
              const previewResolvedValues = asRecord(previewForItem?.preview?.resolved_values);
              const previewConflicts = asRows(previewForItem?.preview?.conflicts);
              const adapterLinks = asRecord(item.adapter_links);

              return (
                <article
                  key={`queue-item-${itemId}`}
                  className="mini-card"
                  style={{
                    position: "relative",
                    background: "rgba(255,255,255,0.015)",
                    border: "1px solid rgba(255,255,255,0.08)",
                    padding: "20px",
                    borderRadius: "14px",
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "flex-start",
                      flexWrap: "wrap",
                      gap: "10px",
                      marginBottom: "8px",
                    }}
                  >
                    <div style={{ maxWidth: "720px" }}>
                      <strong style={{ fontSize: "16px" }}>{formatText(asText(item.title))}</strong>
                      <p style={{ fontSize: "14px", opacity: 0.9, lineHeight: "1.45", margin: "8px 0 0 0" }}>
                        {formatText(asText(item.summary))}
                      </p>
                    </div>
                    <div style={{ display: "flex", gap: "6px", alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
                      {sourceQuality ? <span style={sourceQualityBadgeStyle(sourceQuality)}>{sourceQuality}</span> : null}
                      <span style={getImportanceBadgeStyle(importance)}>{importance}</span>
                      <span style={getQueueStatusBadgeStyle(status)}>{status}</span>
                    </div>
                  </div>

                  {relatedObservations.length ? (
                    <div style={{ display: "grid", gap: "10px", marginBottom: "16px" }}>
                      <div style={{ fontSize: "12px", opacity: 0.62, textTransform: "uppercase", letterSpacing: "0.08em" }}>Observation Context</div>
                      {relatedObservations.slice(0, 3).map((observation) => (
                        <div key={`${itemId}-${observation.observation_id}`} style={{ padding: "10px 12px", background: "rgba(255,255,255,0.025)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: "10px" }}>
                          <div style={{ display: "flex", justifyContent: "space-between", gap: "10px", flexWrap: "wrap", fontSize: "12px", marginBottom: "6px" }}>
                            <strong>{titleize(observation.observation_type)}</strong>
                            <span style={{ opacity: 0.68 }}>
                              {observation.observation_kind} · {observation.agent_confidence ?? "unknown"} confidence · {observation.qualitative_importance ?? "unknown"} importance
                            </span>
                          </div>
                          <div style={{ opacity: 0.9 }}>{formatText(observation.claim)}</div>
                          {observation.evidence_rationale ? <div style={{ marginTop: "6px", opacity: 0.72 }}>Evidence: {formatText(observation.evidence_rationale)}</div> : null}
                          {observation.what_would_change_mind ? <div style={{ marginTop: "6px", opacity: 0.72 }}>Would change mind: {formatText(observation.what_would_change_mind)}</div> : null}
                        </div>
                      ))}
                    </div>
                  ) : null}

                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                      gap: "10px",
                      fontSize: "12px",
                      opacity: 0.78,
                      marginBottom: "16px",
                    }}
                  >
                    <div>
                      <strong style={{ opacity: 0.52 }}>Profile</strong>
                      <div>{titleize(asText(item.profile_name))}</div>
                    </div>
                    <div>
                      <strong style={{ opacity: 0.52 }}>Item Type</strong>
                      <div>{titleize(itemType)}</div>
                    </div>
                    <div>
                      <strong style={{ opacity: 0.52 }}>Target Drivers</strong>
                      <div>{activeProposals.map((proposal) => String(proposal.assumption_name ?? "—")).join(", ") || "—"}</div>
                    </div>
                    <div>
                      <strong style={{ opacity: 0.52 }}>Evidence Packets</strong>
                      <div>{packetIds.join(", ") || "—"}</div>
                    </div>
                  </div>

                  <div style={{ display: "grid", gap: "10px", marginBottom: "16px" }}>
                    <div style={{ fontSize: "12px", opacity: 0.62, textTransform: "uppercase", letterSpacing: "0.08em" }}>Inline Evidence</div>
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                        gap: "10px",
                      }}
                    >
                      {previewAnchors.map((anchor) => {
                        const match = anchorMap.get(anchor);
                        return (
                          <div
                            key={`${itemId}-${anchor}`}
                            style={{
                              padding: "10px 12px",
                              background: "rgba(255,255,255,0.025)",
                              border: "1px solid rgba(255,255,255,0.06)",
                              borderRadius: "10px",
                              borderLeft: "3px solid #60a5fa",
                            }}
                          >
                            <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", fontSize: "11px", marginBottom: "6px" }}>
                              <span style={{ color: "#7dd3fc", fontWeight: "700" }}>{match?.label || anchor}</span>
                              <span style={{ opacity: 0.55 }}>{match?.type || "Reference"}</span>
                            </div>
                            <div style={{ opacity: 0.88, fontStyle: match?.type === "Snippet" ? "italic" : "normal" }}>
                              {match?.content || "Linked evidence reference."}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                    {anchorList.length > 2 ? (
                      <button
                        type="button"
                        className="ghost-button"
                        style={{ justifySelf: "flex-start", fontSize: "12px", padding: "4px 8px", height: "auto" }}
                        onClick={() => toggleExpand(itemId)}
                      >
                        {isExpanded ? "Hide More Evidence" : `Show ${extraAnchorCount} More Evidence Anchors`}
                      </button>
                    ) : null}
                    {isExpanded ? (
                      <div style={{ display: "grid", gap: "8px" }}>
                        {anchorList.slice(2).map((anchor) => {
                          const match = anchorMap.get(anchor);
                          return (
                            <div key={`${itemId}-expanded-${anchor}`} style={{ padding: "10px 12px", background: "rgba(0,0,0,0.2)", borderRadius: "10px" }}>
                              <strong>{match?.label || anchor}</strong>
                              <div style={{ marginTop: "6px", opacity: 0.82 }}>{match?.content || "Linked evidence reference."}</div>
                            </div>
                          );
                        })}
                      </div>
                    ) : null}
                  </div>

                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                      gap: "12px",
                      marginBottom: "16px",
                    }}
                  >
                    <ProposalPackCard title="Original Proposal" pack={proposalPack} accentColor="#f59e0b" />
                    <ProposalPackCard title="PM Edited Proposal" pack={editedPack} accentColor="#38bdf8" />
                    <ProposalPackCard title="Approved Override" pack={approvedPack} accentColor="#34d399" />
                  </div>

                  {firstProposal ? (
                    <label className="field-input" style={{ marginBottom: "16px" }}>
                      <span>PM Edit Proposed Value</span>
                      <input
                        aria-label={`PM edit proposed value for item ${itemId}`}
                        type="number"
                        step="0.001"
                        value={editableValue}
                        style={{ background: "rgba(0,0,0,0.4)", border: "1px solid rgba(255,255,255,0.15)", color: "#fff" }}
                        onChange={(event) => setEditableValues((current) => ({ ...current, [itemId]: event.target.value }))}
                      />
                    </label>
                  ) : null}

                  {previewForItem?.preview ? (
                    <div style={{ display: "grid", gap: "10px", marginBottom: "16px" }}>
                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                          gap: "10px",
                        }}
                      >
                      <div className="mini-card" style={{ background: "rgba(56, 189, 248, 0.08)", border: "1px solid rgba(56, 189, 248, 0.2)" }}>
                        <strong>Previewed Base IV</strong>
                        <p style={{ fontSize: "22px", margin: "6px 0 2px 0", color: "#7dd3fc" }}>
                          {formatCurrency(asNumber((previewForItem.preview.proposed_iv ?? {}).base))}
                        </p>
                        <span style={{ opacity: 0.75 }}>Preview Item #{previewForItem.item_id}</span>
                      </div>
                      <div className="mini-card" style={{ background: "rgba(16, 185, 129, 0.08)", border: "1px solid rgba(16, 185, 129, 0.2)" }}>
                        <strong>Preview Delta</strong>
                        <p
                          style={{
                            fontSize: "22px",
                            margin: "6px 0 2px 0",
                            color: asNumber((previewForItem.preview.delta_pct ?? {}).base) >= 0 ? "#86efac" : "#fca5a5",
                          }}
                        >
                          {formatPercent(asNumber((previewForItem.preview.delta_pct ?? {}).base))}
                        </p>
                        <span style={{ opacity: 0.75 }}>Approval stays disabled until this preview exists.</span>
                      </div>
                      {approvedValues.length ? (
                        <div className="mini-card" style={{ background: "rgba(52, 211, 153, 0.08)", border: "1px solid rgba(52, 211, 153, 0.2)" }}>
                          <strong>Approved Target Values</strong>
                          <div style={{ display: "grid", gap: "4px", marginTop: "8px" }}>
                            {approvedValues.map((proposal, index) => (
                              <span key={`approved-target-${itemId}-${index}`}>
                                {titleize(asText(proposal.assumption_name))}: {proposalSummaryValue(proposal)}
                              </span>
                            ))}
                          </div>
                        </div>
                      ) : null}
                      </div>
                      {previewResolvedValues ? (
                        <div style={{ padding: "10px 12px", borderRadius: "10px", background: "rgba(255,255,255,0.025)", border: "1px solid rgba(255,255,255,0.06)", fontSize: "12px" }}>
                          <strong>Field-Level Resolved Values</strong>
                          <div style={{ display: "grid", gap: "6px", marginTop: "8px" }}>
                            {Object.entries(previewResolvedValues).map(([field, meta]) => {
                              const record = asRecord(meta);
                              return (
                                <div key={`${itemId}-resolved-${field}`} style={{ display: "flex", justifyContent: "space-between", gap: "12px", flexWrap: "wrap" }}>
                                  <span>{titleize(field)}</span>
                                  <span style={{ opacity: 0.78 }}>{asText(record?.proposed_value) ?? asText(record?.value) ?? JSON.stringify(meta)}</span>
                                </div>
                              );
                            })}
                          </div>
                          <div style={{ marginTop: "8px", opacity: 0.58 }}>Fingerprint: {previewForItem.preview_fingerprint ?? "—"} · {formatDateLabel(previewForItem.previewed_at)}</div>
                        </div>
                      ) : null}
                      {previewConflicts.length ? (
                        <div style={{ padding: "10px 12px", borderRadius: "10px", border: "1px solid rgba(245, 158, 11, 0.35)", background: "rgba(245, 158, 11, 0.08)", color: "#fcd34d", fontSize: "12px" }}>
                          Preview conflicts: {previewConflicts.map((conflict) => asText(conflict.assumption_name) ?? asText(conflict.reason) ?? "conflict").join(", ")}
                        </div>
                      ) : null}
                    </div>
                  ) : null}

                  {previewSkippedFields.length ? (
                    <div
                      style={{
                        marginBottom: "16px",
                        padding: "10px 12px",
                        borderRadius: "10px",
                        border: "1px solid rgba(245, 158, 11, 0.35)",
                        background: "rgba(245, 158, 11, 0.08)",
                        color: "#fcd34d",
                        fontSize: "12px",
                      }}
                    >
                      Skipped fields need manual follow-up before approval certainty improves: {previewSkippedFields.join(", ")}
                    </div>
                  ) : null}

                  {requiresPreview && !previewReady ? (
                    <div style={{ marginBottom: "12px", fontSize: "12px", opacity: 0.74 }}>
                      Preview this assumption change after the latest edit before approval unlocks.
                    </div>
                  ) : null}

                  {decisionHistory.length || adapterLinks?.approval_ref ? (
                    <div style={{ display: "grid", gap: "8px", marginBottom: "16px", fontSize: "12px" }}>
                      <div style={{ opacity: 0.62, textTransform: "uppercase", letterSpacing: "0.08em" }}>Decision Audit Trail</div>
                      {adapterLinks?.approval_ref ? <div style={{ color: "#86efac" }}>Approval Ref: {String(adapterLinks.approval_ref)}</div> : null}
                      {decisionHistory.slice(-4).map((event, index) => (
                        <div key={`${itemId}-history-${index}`} style={{ padding: "8px 10px", borderRadius: "8px", background: "rgba(0,0,0,0.18)" }}>
                          <strong>{titleize(asText(event.event) ?? "event")}</strong>
                          <span style={{ marginLeft: "8px", opacity: 0.65 }}>{formatDateLabel(asText(event.event_ts))} · {asText(event.actor) ?? "unknown"}</span>
                          {asText(event.reason) ? <div style={{ opacity: 0.78 }}>Reason: {formatText(asText(event.reason))}</div> : null}
                        </div>
                      ))}
                    </div>
                  ) : null}

                  <div className="action-controls" style={{ gap: "8px", flexWrap: "wrap" }}>
                    <button type="button" className="ghost-button" onClick={() => onPreview(itemId)} disabled={actionPending}>
                      Preview
                    </button>
                    {firstProposal ? (
                      <button
                        type="button"
                        className="ghost-button"
                        onClick={() => {
                          const editedNumber = Number(editableValue);
                          if (!Number.isFinite(editedNumber)) {
                            return;
                          }
                          const editedProposal = {
                            ...firstProposal,
                            proposal_mode: "target",
                            proposed_target_value: editedNumber,
                            proposed_delta: undefined,
                          };
                          onEdit(itemId, {
                            pack_id: String(activePack?.pack_id ?? `pack:edited:${itemId}`),
                            proposals: [editedProposal, ...activeProposals.slice(1)],
                          });
                        }}
                        disabled={actionPending}
                      >
                        Save Edit
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="primary-button"
                      onClick={() => onApprove(itemId)}
                      disabled={actionPending || (requiresPreview && !previewReady)}
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      className="ghost-button"
                      onClick={() => {
                        const reason = window.prompt("Reason for rejecting this queue item?");
                        if (reason?.trim()) {
                          onReject(itemId, reason.trim());
                        }
                      }}
                      disabled={actionPending}
                    >
                      Reject
                    </button>
                    <button
                      type="button"
                      className="ghost-button"
                      onClick={() => {
                        const reason = window.prompt("Reason for deferring this queue item?");
                        if (reason?.trim()) {
                          onDefer(itemId, reason.trim());
                        }
                      }}
                      disabled={actionPending}
                    >
                      Defer
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      {previewPayload?.preview ? (
        <section
          className="panel"
          style={{
            border: "1px solid rgba(96, 165, 250, 0.2)",
            background: "linear-gradient(135deg, rgba(96, 165, 250, 0.06) 0%, rgba(0,0,0,0) 100%)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", flexWrap: "wrap", alignItems: "flex-end" }}>
            <div>
              <h2>Queue Preview Impact Analysis</h2>
              <p style={{ marginBottom: 0, opacity: 0.76 }}>
                Previewed queue values must match the deterministic overrides you approve. Item #{previewPayload.item_id}.
              </p>
            </div>
            <span style={runStatusBadgeStyle("completed_with_items")}>Preview Ready</span>
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              gap: "14px",
              marginTop: "16px",
            }}
          >
            <div className="mini-card" style={{ background: "rgba(255,255,255,0.03)" }}>
              <span style={{ fontSize: "12px", opacity: 0.6 }}>Current Base IV</span>
              <p style={{ fontSize: "24px", fontWeight: "700", margin: "4px 0" }}>
                {formatCurrency(asNumber((previewPayload.preview.current_iv ?? {}).base))}
              </p>
            </div>
            <div className="mini-card" style={{ background: "rgba(56, 189, 248, 0.08)" }}>
              <span style={{ fontSize: "12px", opacity: 0.6 }}>Previewed Base IV</span>
              <p style={{ fontSize: "24px", fontWeight: "700", margin: "4px 0", color: "#7dd3fc" }}>
                {formatCurrency(asNumber((previewPayload.preview.proposed_iv ?? {}).base))}
              </p>
            </div>
            <div className="mini-card" style={{ background: "rgba(16, 185, 129, 0.08)" }}>
              <span style={{ fontSize: "12px", opacity: 0.6 }}>Impact Delta</span>
              <p
                style={{
                  fontSize: "24px",
                  fontWeight: "700",
                  margin: "4px 0",
                  color: asNumber((previewPayload.preview.delta_pct ?? {}).base) >= 0 ? "#86efac" : "#fca5a5",
                }}
              >
                {formatPercent(asNumber((previewPayload.preview.delta_pct ?? {}).base))}
              </p>
            </div>
          </div>
          {previewPayload.skipped_fields?.length ? (
            <div
              style={{
                marginTop: "14px",
                fontSize: "12px",
                color: "#fcd34d",
                borderLeft: "3px solid rgba(245, 158, 11, 0.7)",
                paddingLeft: "10px",
              }}
            >
              Preview skipped unresolvable fields: {previewPayload.skipped_fields.join(", ")}
            </div>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}

export function ValuationPage() {
  const { ticker = "" } = useParams();
  const {
    workspace,
    openLatestSnapshot,
    runDeepAnalysis,
    openLatestSnapshotPending,
    runDeepAnalysisPending,
  } = useOutletContext<TickerLayoutContext>();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const selected = (params.get("view") ?? "Summary") as ValuationTab;
  const [assumptionSelections, setAssumptionSelections] = useState<Record<string, string>>({});
  const [assumptionCustomValues, setAssumptionCustomValues] = useState<Record<string, number>>({});
  const [policyRf, setPolicyRf] = useState(0.045);
  const [policyErp, setPolicyErp] = useState(0.05);
  const [waccMode, setWaccMode] = useState("single_method");
  const [waccSelectedMethod, setWaccSelectedMethod] = useState("peer_bottom_up");
  const [waccWeights, setWaccWeights] = useState<Record<string, number>>({});
  const [selectedRecommendationFields, setSelectedRecommendationFields] = useState<string[]>([]);
  const [pmQueueStatusFilter, setPmQueueStatusFilter] = useState("all");
  const [pmQueueEditableValues, setPmQueueEditableValues] = useState<Record<number, string>>({});
  const [pmQueuePreviewPayload, setPmQueuePreviewPayload] = useState<PMDecisionQueuePreviewPayload | null>(null);
  const [pmQueuePreviewedItemIds, setPmQueuePreviewedItemIds] = useState<number[]>([]);
  const [profileRunResults, setProfileRunResults] = useState<Record<string, PMQueueRunCard>>({});
  const [assumptionsRunId, setAssumptionsRunId] = useState<string | null>(null);
  const [waccRunId, setWaccRunId] = useState<string | null>(null);
  const [recommendationsRunId, setRecommendationsRunId] = useState<string | null>(null);
  const [exportRunId, setExportRunId] = useState<string | null>(null);
  const [downloadedExportId, setDownloadedExportId] = useState<string | null>(null);

  const summaryQuery = useQuery({
    queryKey: ["ticker-valuation-summary", ticker],
    queryFn: () => getValuationSummary(ticker),
    enabled: Boolean(ticker) && selected === "Summary",
  });
  const dcfQuery = useQuery({
    queryKey: ["ticker-valuation-dcf", ticker],
    queryFn: () => getValuationDcf(ticker),
    enabled: Boolean(ticker) && selected === "DCF",
  });
  const compsQuery = useQuery({
    queryKey: ["ticker-valuation-comps", ticker],
    queryFn: () => getValuationComps(ticker),
    enabled: Boolean(ticker) && (selected === "Comparables" || selected === "Multiples"),
  });
  const assumptionsQuery = useQuery({
    queryKey: ["ticker-valuation-assumptions", ticker],
    queryFn: () => getValuationAssumptions(ticker),
    enabled: Boolean(ticker) && selected === "Assumptions",
  });
  const policyQuery = useQuery({
    queryKey: ["valuation-policy"],
    queryFn: () => getValuationPolicy(),
    enabled: selected === "Assumptions",
  });
  const waccQuery = useQuery({
    queryKey: ["ticker-valuation-wacc", ticker],
    queryFn: () => getWacc(ticker),
    enabled: Boolean(ticker) && selected === "WACC",
  });
  const recommendationsQuery = useQuery({
    queryKey: ["ticker-valuation-recommendations", ticker],
    queryFn: () => getRecommendations(ticker),
    enabled: Boolean(ticker) && selected === "Recommendations",
  });
  const evidencePacketsQuery = useQuery({
    queryKey: ["ticker-evidence-packets", ticker],
    queryFn: () => getEvidencePackets(ticker),
    enabled: Boolean(ticker) && selected === "PM Queue",
  });
  const pmQueueQuery = useQuery({
    queryKey: ["ticker-pm-decision-queue", ticker, pmQueueStatusFilter],
    queryFn: () =>
      getPmDecisionQueue(ticker, {
        status: pmQueueStatusFilter === "all" ? undefined : pmQueueStatusFilter,
      }),
    enabled: Boolean(ticker) && selected === "PM Queue",
  });

  useEffect(() => {
    if (!assumptionsQuery.data?.fields?.length) {
      return;
    }
    setAssumptionSelections(
      Object.fromEntries(
        assumptionsQuery.data.fields.map((field) => [field.field, field.initial_mode ?? "default"]),
      ),
    );
    setAssumptionCustomValues(
      Object.fromEntries(
        assumptionsQuery.data.fields.map((field) => [field.field, toDisplayValue(field.effective_value ?? field.baseline_value, field.unit)]),
      ),
    );
  }, [assumptionsQuery.data]);

  useEffect(() => {
    if (!waccQuery.data) {
      return;
    }
    setWaccMode(String(waccQuery.data.current_selection?.mode ?? "single_method"));
    setWaccSelectedMethod(String(waccQuery.data.current_selection?.selected_method ?? "peer_bottom_up"));
    setWaccWeights((waccQuery.data.current_selection?.weights as Record<string, number> | undefined) ?? {});
  }, [waccQuery.data]);

  useEffect(() => {
    if (!policyQuery.data?.global_defaults) {
      return;
    }
    setPolicyRf(Number(policyQuery.data.global_defaults.risk_free_rate ?? 0.045));
    setPolicyErp(Number(policyQuery.data.global_defaults.equity_risk_premium ?? 0.05));
  }, [policyQuery.data]);

  const assumptionsPreviewMutation = useMutation({
    mutationFn: () =>
      previewValuationAssumptions(ticker, {
        selections: assumptionSelections,
        custom_values: Object.fromEntries(
          Object.entries(assumptionCustomValues).map(([field, value]) => {
            const fieldMeta = assumptionsQuery.data?.fields.find((item) => item.field === field);
            return [field, fromDisplayValue(value, fieldMeta?.unit)];
          }),
        ),
      }),
  });
  const assumptionsApplyMutation = useMutation({
    mutationFn: () =>
      applyValuationAssumptions(ticker, {
        selections: assumptionSelections,
        custom_values: Object.fromEntries(
          Object.entries(assumptionCustomValues).map(([field, value]) => {
            const fieldMeta = assumptionsQuery.data?.fields.find((item) => item.field === field);
            return [field, fromDisplayValue(value, fieldMeta?.unit)];
          }),
        ),
      }),
    onSuccess: (payload) => setAssumptionsRunId(payload.run_id),
  });
  const policySaveMutation = useMutation({
    mutationFn: () =>
      saveValuationPolicy({
        global_defaults: {
          risk_free_rate: policyRf,
          equity_risk_premium: policyErp,
        },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["valuation-policy"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["ticker-valuation-assumptions", ticker] }).catch(() => undefined);
    },
  });

  const waccPreviewMutation = useMutation({
    mutationFn: () => previewWacc(ticker, { mode: waccMode, selected_method: waccSelectedMethod, weights: waccWeights }),
  });
  const waccApplyMutation = useMutation({
    mutationFn: () => applyWacc(ticker, { mode: waccMode, selected_method: waccSelectedMethod, weights: waccWeights }),
    onSuccess: (payload) => setWaccRunId(payload.run_id),
  });

  const recommendationsPreviewMutation = useMutation({
    mutationFn: () => previewRecommendations(ticker, { approved_fields: selectedRecommendationFields }),
  });
  const recommendationsApplyMutation = useMutation({
    mutationFn: () => applyRecommendations(ticker, { approved_fields: selectedRecommendationFields }),
    onSuccess: (payload) => setRecommendationsRunId(payload.run_id),
  });
  const runAgenticHandoffMutation = useMutation({
    mutationFn: (profileName: string) => runAgenticHandoffProfile(ticker, profileName),
    onSuccess: (payload) => {
      setProfileRunResults((current) => ({
        ...current,
        [payload.profile_name]: {
          profile_name: payload.profile_name,
          status: payload.status,
          reason: payload.reason ?? null,
          observation_count: payload.observation_count ?? 0,
          queue_item_count: payload.queue_item_count ?? 0,
          errors: payload.errors ?? [],
          source_quality: payload.evidence_packet?.run_metadata?.source_quality ?? null,
        },
      }));
      queryClient.invalidateQueries({ queryKey: ["ticker-evidence-packets", ticker] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["ticker-pm-decision-queue", ticker] }).catch(() => undefined);
    },
    onError: (error, profileName) => {
      setProfileRunResults((current) => ({
        ...current,
        [profileName]: {
          profile_name: profileName,
          status: "failed",
          reason: "request_failed",
          observation_count: 0,
          queue_item_count: 0,
          errors: [{ code: "request_failed", message: error instanceof Error ? error.message : "Unknown run failure" }],
        },
      }));
    },
  });
  const pmQueuePreviewMutation = useMutation({
    mutationFn: (itemId: number) => previewPmDecisionQueueItem(ticker, itemId),
    onSuccess: (payload) => {
      setPmQueuePreviewPayload(payload);
      setPmQueuePreviewedItemIds((current) => (current.includes(payload.item_id) ? current : [...current, payload.item_id]));
    },
  });
  const pmQueueEditMutation = useMutation({
    mutationFn: ({ itemId, proposalPack }: { itemId: number; proposalPack: Record<string, unknown> }) =>
      editPmDecisionQueueItem(ticker, itemId, proposalPack),
    onSuccess: (payload) => {
      setPmQueuePreviewedItemIds((current) => current.filter((value) => value !== payload.item_id));
      setPmQueuePreviewPayload((current) => (current?.item_id === payload.item_id ? null : current));
      queryClient.invalidateQueries({ queryKey: ["ticker-pm-decision-queue", ticker] }).catch(() => undefined);
    },
  });
  const pmQueueApproveMutation = useMutation({
    mutationFn: (itemId: number) => approvePmDecisionQueueItem(ticker, itemId),
    onSuccess: (payload) => {
      setPmQueuePreviewedItemIds((current) => current.filter((value) => value !== payload.item_id));
      queryClient.invalidateQueries({ queryKey: ["ticker-pm-decision-queue", ticker] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["ticker-valuation-assumptions", ticker] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["ticker-valuation-summary", ticker] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["ticker-valuation-dcf", ticker] }).catch(() => undefined);
    },
  });
  const pmQueueRejectMutation = useMutation({
    mutationFn: ({ itemId, reason }: { itemId: number; reason: string }) => rejectPmDecisionQueueItem(ticker, itemId, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ticker-pm-decision-queue", ticker] }).catch(() => undefined);
    },
  });
  const pmQueueDeferMutation = useMutation({
    mutationFn: ({ itemId, reason }: { itemId: number; reason: string }) => deferPmDecisionQueueItem(ticker, itemId, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ticker-pm-decision-queue", ticker] }).catch(() => undefined);
    },
  });
  const exportMutation = useMutation({
    mutationFn: () => createTickerExport(ticker, { format: "xlsx", source_mode: "loaded_backend_state" }),
    onSuccess: (payload) => setExportRunId(payload.run_id),
  });

  const assumptionsRunStatusQuery = useQuery({
    queryKey: ["valuation-assumptions-run", assumptionsRunId],
    queryFn: () => getRunStatus(assumptionsRunId ?? ""),
    enabled: Boolean(assumptionsRunId),
    refetchInterval: (query) => (query.state.data?.status === "completed" || query.state.data?.status === "failed" ? false : 1000),
  });
  const waccRunStatusQuery = useQuery({
    queryKey: ["valuation-wacc-run", waccRunId],
    queryFn: () => getRunStatus(waccRunId ?? ""),
    enabled: Boolean(waccRunId),
    refetchInterval: (query) => (query.state.data?.status === "completed" || query.state.data?.status === "failed" ? false : 1000),
  });
  const recommendationsRunStatusQuery = useQuery({
    queryKey: ["valuation-recommendations-run", recommendationsRunId],
    queryFn: () => getRunStatus(recommendationsRunId ?? ""),
    enabled: Boolean(recommendationsRunId),
    refetchInterval: (query) => (query.state.data?.status === "completed" || query.state.data?.status === "failed" ? false : 1000),
  });
  const exportRunStatusQuery = useQuery({
    queryKey: ["valuation-export-run", exportRunId],
    queryFn: () => getRunStatus(exportRunId ?? ""),
    enabled: Boolean(exportRunId),
    refetchInterval: (query) => (query.state.data?.status === "completed" || query.state.data?.status === "failed" ? false : 1000),
  });

  useEffect(() => {
    if (assumptionsRunStatusQuery.data?.status === "completed") {
      queryClient.invalidateQueries({ queryKey: ["ticker-valuation-assumptions", ticker] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["ticker-valuation-summary", ticker] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["ticker-valuation-dcf", ticker] }).catch(() => undefined);
    }
  }, [assumptionsRunStatusQuery.data?.status, queryClient, ticker]);

  useEffect(() => {
    if (waccRunStatusQuery.data?.status === "completed") {
      queryClient.invalidateQueries({ queryKey: ["ticker-valuation-wacc", ticker] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["ticker-valuation-summary", ticker] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["ticker-valuation-dcf", ticker] }).catch(() => undefined);
    }
  }, [queryClient, ticker, waccRunStatusQuery.data?.status]);

  useEffect(() => {
    if (recommendationsRunStatusQuery.data?.status === "completed") {
      queryClient.invalidateQueries({ queryKey: ["ticker-valuation-recommendations", ticker] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["ticker-valuation-assumptions", ticker] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["ticker-valuation-summary", ticker] }).catch(() => undefined);
    }
  }, [queryClient, recommendationsRunStatusQuery.data?.status, ticker]);
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

  const summary = summaryQuery.data;
  const dcf = dcfQuery.data as Record<string, unknown> | undefined;
  const comps = compsQuery.data as Record<string, unknown> | undefined;
  const evidencePackets = evidencePacketsQuery.data?.evidence_packets ?? [];
  const pmQueueProfileRunCards = useMemo(() => {
    const packetCards = new Map<string, PMQueueRunCard>();
    for (const packet of evidencePackets) {
      const metadata = packet.run_metadata ?? {};
      if (!metadata.status) {
        continue;
      }
      packetCards.set(packet.profile_name, {
        profile_name: packet.profile_name,
        status: metadata.status,
        reason: metadata.reason ?? null,
        observation_count: packet.observations?.length ?? metadata.observation_count ?? 0,
        queue_item_count: metadata.queue_item_count ?? 0,
        errors: metadata.errors ?? [],
        source_quality: metadata.source_quality ?? null,
      });
    }
    for (const [profileName, runCard] of Object.entries(profileRunResults)) {
      packetCards.set(profileName, runCard);
    }
    return Array.from(packetCards.values());
  }, [evidencePackets, profileRunResults]);

  const activePanel = useMemo(() => {
    switch (selected) {
      case "Summary":
        return summaryQuery.isPending && !summary ? renderLoadingPanel("Scenario Summary") : <SummaryPanel summary={summary as Record<string, unknown> | undefined} workspace={workspace} />;
      case "DCF":
        return dcfQuery.isPending && !dcf ? renderLoadingPanel("DCF") : <DcfPanel dcf={dcf} />;
      case "Comparables":
        return compsQuery.isPending && !comps ? renderLoadingPanel("Comparables") : <ComparablesPanel comps={comps} />;
      case "Multiples":
        return compsQuery.isPending && !comps ? renderLoadingPanel("Historical Multiples") : <MultiplesPanel comps={comps} />;
      case "Assumptions":
        return assumptionsQuery.isPending && !assumptionsQuery.data ? renderLoadingPanel("Assumptions") : (
          <AssumptionsPanel
            assumptions={assumptionsQuery.data as unknown as Record<string, unknown>}
            policy={policyQuery.data}
            policyRf={policyRf}
            setPolicyRf={setPolicyRf}
            policyErp={policyErp}
            setPolicyErp={setPolicyErp}
            onSavePolicy={() => policySaveMutation.mutate()}
            policySavePending={policySaveMutation.isPending}
            selections={assumptionSelections}
            setSelections={setAssumptionSelections}
            customValues={assumptionCustomValues}
            setCustomValues={setAssumptionCustomValues}
            preview={assumptionsPreviewMutation.data as unknown as Record<string, unknown> | undefined}
            previewPending={assumptionsPreviewMutation.isPending}
            onPreview={() => assumptionsPreviewMutation.mutate()}
            onApply={() => assumptionsApplyMutation.mutate()}
            applyPending={assumptionsApplyMutation.isPending}
            runStatus={assumptionsRunStatusQuery.data as unknown as Record<string, unknown> | undefined}
          />
        );
      case "WACC":
        return waccQuery.isPending && !waccQuery.data ? renderLoadingPanel("WACC") : (
          <WaccPanel
            wacc={waccQuery.data as unknown as Record<string, unknown>}
            mode={waccMode}
            setMode={setWaccMode}
            selectedMethod={waccSelectedMethod}
            setSelectedMethod={setWaccSelectedMethod}
            weights={waccWeights}
            setWeights={setWaccWeights}
            preview={waccPreviewMutation.data}
            onPreview={() => waccPreviewMutation.mutate()}
            onApply={() => waccApplyMutation.mutate()}
            previewPending={waccPreviewMutation.isPending}
            applyPending={waccApplyMutation.isPending}
            runStatus={waccRunStatusQuery.data as unknown as Record<string, unknown> | undefined}
          />
        );
      case "Recommendations":
        return recommendationsQuery.isPending && !recommendationsQuery.data ? renderLoadingPanel("Recommendations") : (
          <RecommendationsPanel
            recommendations={recommendationsQuery.data}
            selectedFields={selectedRecommendationFields}
            setSelectedFields={setSelectedRecommendationFields}
            preview={recommendationsPreviewMutation.data}
            onPreview={() => recommendationsPreviewMutation.mutate()}
            onApply={() => recommendationsApplyMutation.mutate()}
            previewPending={recommendationsPreviewMutation.isPending}
            applyPending={recommendationsApplyMutation.isPending}
            runStatus={recommendationsRunStatusQuery.data as unknown as Record<string, unknown> | undefined}
          />
        );
      case "PM Queue":
        return pmQueueQuery.isPending && !pmQueueQuery.data ? renderLoadingPanel("PM Queue / Insights") : (
          <PMQueuePanel
            queuePayload={pmQueueQuery.data}
            evidencePackets={evidencePackets}
            statusFilter={pmQueueStatusFilter}
            setStatusFilter={setPmQueueStatusFilter}
            editableValues={pmQueueEditableValues}
            setEditableValues={setPmQueueEditableValues}
            profileRunCards={pmQueueProfileRunCards}
            previewedItemIds={pmQueuePreviewedItemIds}
            onRunProfile={(profileName) => runAgenticHandoffMutation.mutate(profileName)}
            onPreview={(itemId) => pmQueuePreviewMutation.mutate(itemId)}
            onEdit={(itemId, proposalPack) => pmQueueEditMutation.mutate({ itemId, proposalPack })}
            onApprove={(itemId) => pmQueueApproveMutation.mutate(itemId)}
            onReject={(itemId, reason) => pmQueueRejectMutation.mutate({ itemId, reason })}
            onDefer={(itemId, reason) => pmQueueDeferMutation.mutate({ itemId, reason })}
            previewPayload={pmQueuePreviewPayload}
            actionPending={
              runAgenticHandoffMutation.isPending ||
              pmQueuePreviewMutation.isPending ||
              pmQueueEditMutation.isPending ||
              pmQueueApproveMutation.isPending ||
              pmQueueRejectMutation.isPending ||
              pmQueueDeferMutation.isPending
            }
          />
        );
      default:
        return renderLoadingPanel("Valuation");
    }
  }, [
    assumptionCustomValues,
    assumptionSelections,
    assumptionsApplyMutation,
    assumptionsPreviewMutation,
    assumptionsQuery.data,
    assumptionsQuery.isPending,
    assumptionsRunStatusQuery.data,
    comps,
    compsQuery.isPending,
    dcf,
    dcfQuery.isPending,
    recommendationsApplyMutation,
    recommendationsPreviewMutation,
    recommendationsQuery.data,
    recommendationsQuery.isPending,
    recommendationsRunStatusQuery.data,
    runAgenticHandoffMutation,
    pmQueueApproveMutation,
    pmQueueDeferMutation,
    pmQueueEditMutation,
    pmQueueEditableValues,
    pmQueuePreviewMutation,
    pmQueuePreviewPayload,
    pmQueuePreviewedItemIds,
    pmQueueQuery.data,
    pmQueueQuery.isPending,
    pmQueueProfileRunCards,
    pmQueueRejectMutation,
    pmQueueStatusFilter,
    profileRunResults,
    selected,
    selectedRecommendationFields,
    summary,
    summaryQuery.isPending,
    evidencePackets,
    waccApplyMutation,
    waccMode,
    waccPreviewMutation,
    waccQuery.data,
    waccQuery.isPending,
    waccRunStatusQuery.data,
    waccSelectedMethod,
    waccWeights,
    workspace,
  ]);

  const heroCurrentPrice = summary?.current_price ?? workspace?.current_price ?? assumptionsQuery.data?.current_price ?? null;
  const heroBaseIv = summary?.base_iv ?? workspace?.base_iv ?? assumptionsQuery.data?.current_iv_base ?? null;
  const heroUpside = summary?.upside_pct_base ?? (workspace?.upside_pct_base == null ? null : workspace.upside_pct_base * 100);
  const heroAnalystTarget = summary?.analyst_target ?? workspace?.analyst_target ?? null;
  const heroChips = [
    { label: "Action", value: formatText(workspace?.action) ?? "—" },
    { label: "Conviction", value: formatText(workspace?.conviction)?.toUpperCase?.() ?? "—" },
    { label: "Current Price", value: formatCurrency(heroCurrentPrice) },
    { label: "Base IV", value: formatCurrency(heroBaseIv) },
    { label: "Upside (Base)", value: formatPercent(heroUpside) },
    { label: "Analyst Target", value: formatCurrency(heroAnalystTarget) },
    { label: "Latest Snapshot", value: formatDateLabel(workspace?.latest_snapshot_date) },
  ];

  return (
    <section className="page-stack valuation-page">
      <header className="valuation-route-nav">
        <div className="section-nav section-nav--page">
          {valuationTabs.map((tab) => (
            <button key={tab} type="button" className={`section-chip${selected === tab ? " active" : ""}`} onClick={() => setParams({ view: tab })}>
              {tab}
            </button>
          ))}
        </div>
      </header>

      <PageHero
        kicker="Valuation"
        title={workspace?.company_name ?? ticker.toUpperCase()}
        subtitle="Compact valuation workspace with visible assumptions, WACC, DCF bridges, and comparable diagnostics."
        chips={heroChips}
        actions={
          <div className="action-row valuation-hero-actions">
            <button type="button" className="primary-button" onClick={openLatestSnapshot} disabled={openLatestSnapshotPending || !workspace?.snapshot_available}>
              {openLatestSnapshotPending ? "Opening..." : "Open Latest Snapshot"}
            </button>
            <button type="button" className="ghost-button" onClick={() => exportMutation.mutate()} disabled={exportMutation.isPending}>
              {exportMutation.isPending ? "Queueing..." : "Export Excel"}
            </button>
            <button type="button" className="ghost-button" onClick={runDeepAnalysis} disabled={runDeepAnalysisPending}>
              {runDeepAnalysisPending ? "Running..." : "Run Deep Analysis"}
            </button>
          </div>
        }
      />

      {exportRunStatusQuery.data ? (
        <div className="run-status">
          <strong>{formatText(asText(exportRunStatusQuery.data.status))}</strong>
          <span>{formatText(asText(exportRunStatusQuery.data.message)) ?? "Valuation workbook export is running in the background."}</span>
        </div>
      ) : null}

      {activePanel}
    </section>
  );
}
