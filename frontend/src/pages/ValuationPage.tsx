import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useOutletContext, useParams, useSearchParams } from "react-router-dom";

import { PageHero } from "@/components/PageHero";
import {
  applyRecommendations,
  applyValuationAssumptions,
  applyWacc,
  createTickerExport,
  getRecommendations,
  getRunStatus,
  getValuationAssumptions,
  getValuationComps,
  getValuationDcf,
  getValuationSummary,
  getWacc,
  previewRecommendations,
  previewValuationAssumptions,
  previewWacc,
} from "@/lib/api";
import { downloadCompletedExport, getCompletedExportId } from "@/lib/exportJobs";
import { formatCurrency, formatDateLabel, formatPercent, formatText } from "@/lib/format";
import type {
  RecommendationsPayload,
  RecommendationsPreviewPayload,
  TickerWorkspace,
  WaccPreviewPayload,
} from "@/lib/types";

const valuationTabs = ["Summary", "DCF", "Comparables", "Multiples", "Assumptions", "WACC", "Recommendations"] as const;
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
      </section>
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
  return (
    <section className="page-stack">
      <section className="grid-cards">
        <article className="panel"><h2>Current Base IV</h2><p>{formatCurrency(asNumber(assumptions?.current_iv_base))}</p></article>
        <article className="panel"><h2>Current Price</h2><p>{formatCurrency(asNumber(assumptions?.current_price))}</p></article>
        <article className="panel"><h2>Tracked Fields</h2><p>{fields.length}</p></article>
        <article className="panel"><h2>Current Expected IV</h2><p>{formatCurrency(asNumber(assumptions?.current_expected_iv))}</p></article>
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
  const [waccMode, setWaccMode] = useState("single_method");
  const [waccSelectedMethod, setWaccSelectedMethod] = useState("peer_bottom_up");
  const [waccWeights, setWaccWeights] = useState<Record<string, number>>({});
  const [selectedRecommendationFields, setSelectedRecommendationFields] = useState<string[]>([]);
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
    selected,
    selectedRecommendationFields,
    summary,
    summaryQuery.isPending,
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
