import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getProfessionalModelSheet } from "@/lib/api";
import type {
  ProfessionalModelSheetFinding,
  ProfessionalModelSheetSummary,
} from "@/lib/types";

const PAGE_SIZE = 50;

type ProfessionalModelSheetReviewProps = {
  ticker: string;
  artifactHash: string;
  modelRunId?: string | number | null;
  sheets: ProfessionalModelSheetSummary[];
  selectedSheet: string;
  onSelectSheet: (sheet: string) => void;
  summaryFindings?: ProfessionalModelSheetFinding[];
};

function displayValue(value: unknown): string {
  if (value == null || value === "") {
    return "Not supplied";
  }
  if (typeof value === "boolean") {
    return value ? "True" : "False";
  }
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

function titleize(value: string | null | undefined): string {
  if (!value) {
    return "Not supplied";
  }
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function periodPresentation(value: string | null | undefined) {
  const normalized = value?.trim().toLowerCase() ?? "";
  if (normalized === "historical" || normalized === "actual") {
    return { label: "Historical", className: "is-historical" };
  }
  if (normalized === "forecast" || normalized === "estimate" || normalized === "estimated") {
    return { label: "Forecast", className: "is-forecast" };
  }
  return { label: titleize(value), className: "is-unclassified" };
}

export function ProfessionalModelSheetReview({
  ticker,
  artifactHash,
  modelRunId,
  sheets,
  selectedSheet,
  onSelectSheet,
  summaryFindings = [],
}: ProfessionalModelSheetReviewProps) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  useEffect(() => {
    setPage(1);
  }, [artifactHash, selectedSheet]);

  const filteredSheets = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) {
      return sheets;
    }
    return sheets.filter((sheet) => sheet.name.toLowerCase().includes(query));
  }, [search, sheets]);

  const sheetQuery = useQuery({
    queryKey: ["professional-model-sheet", ticker, modelRunId, artifactHash, selectedSheet, page, PAGE_SIZE],
    queryFn: () =>
      getProfessionalModelSheet(ticker, selectedSheet, page, PAGE_SIZE, artifactHash, modelRunId),
    enabled: Boolean(ticker && artifactHash && modelRunId && selectedSheet),
  });

  const payload = sheetQuery.data;
  const cells = payload?.cells ?? [];
  const totalCells = payload?.total_cells ?? 0;
  const totalPages =
    payload?.total_pages ??
    Math.max(1, Math.ceil(totalCells / Math.max(1, payload?.page_size ?? PAGE_SIZE)));
  const findings =
    payload?.findings ??
    summaryFindings.filter((finding) => !finding.sheet || finding.sheet === selectedSheet);

  return (
    <section className="panel professional-model-sheet-review" id="professional-model-sheet-review">
      <div className="professional-model-section-heading">
        <div>
          <p className="panel-caption">Workbook drill-down</p>
          <h2>Workbook Sheet Review</h2>
          <p>
            Backend workbook order is preserved. Formula text, cached values, formats, comments,
            lineage, and audit findings are rendered without recalculation.
          </p>
        </div>
        <div className="professional-model-sheet-count">
          <strong data-testid="professional-model-sheet-count" data-value={String(sheets.length)}>
            {sheets.length} sheets
          </strong>
          {sheets.length !== 26 ? (
            <span role="alert">Contract mismatch: expected 26 workbook sheets.</span>
          ) : (
            <span>Canonical workbook count</span>
          )}
        </div>
      </div>

      <div className="professional-model-sheet-layout">
        <aside className="professional-model-sheet-picker" aria-label="Workbook sheets">
          <label className="form-label" htmlFor="professional-model-sheet-search">
            Search sheets
          </label>
          <input
            id="professional-model-sheet-search"
            className="search-input"
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Find DCF, WACC, or Checks"
          />

          {sheets.length === 0 ? (
            <p className="table-note">No workbook sheets supplied by the backend.</p>
          ) : filteredSheets.length === 0 ? (
            <p className="table-note">No sheets match "{search}".</p>
          ) : (
            <ul className="professional-model-sheet-list">
              {filteredSheets.map((sheet, index) => {
                const originalIndex = sheets.findIndex((candidate) => candidate.name === sheet.name);
                const isSelected = selectedSheet === sheet.name;
                return (
                  <li key={sheet.name}>
                    <button
                      type="button"
                      className={`professional-model-sheet-button${isSelected ? " is-selected" : ""}`}
                      onClick={() => onSelectSheet(sheet.name)}
                      aria-pressed={isSelected}
                    >
                      <span className="professional-model-sheet-name">
                        <span>{String((sheet.order ?? originalIndex + 1)).padStart(2, "0")}</span>
                        <strong>{sheet.name}</strong>
                      </span>
                      <span className="professional-model-sheet-meta">
                        <span>{titleize(sheet.status)}</span>
                        <span>{sheet.finding_count ?? 0} findings</span>
                        <span>{sheet.formula_count ?? 0} formulas</span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </aside>

        <div className="professional-model-sheet-detail">
          {!selectedSheet ? (
            <div className="professional-model-empty">
              <strong>Select a workbook sheet</strong>
              <span>The backend did not provide a default sheet selection.</span>
            </div>
          ) : (
            <>
              <div className="panel-toolbar">
                <div>
                  <p className="panel-caption">Selected sheet</p>
                  <h3
                    data-testid="professional-model-selected-sheet"
                    data-value={selectedSheet}
                  >
                    {selectedSheet}
                  </h3>
                </div>
                <span className="table-note">
                  Page {page} of {totalPages} / {totalCells} cells
                </span>
              </div>

              {sheetQuery.isPending ? (
                <div className="professional-model-empty" aria-live="polite">
                  <strong>Loading selected sheet...</strong>
                  <span>Requesting paginated workbook cells and findings.</span>
                </div>
              ) : sheetQuery.isError ? (
                <div className="run-status error" role="alert">
                  <strong>Sheet preview could not be loaded.</strong>
                  <span>
                    {sheetQuery.error instanceof Error
                      ? sheetQuery.error.message
                      : "Unknown sheet request failure."}
                  </span>
                </div>
              ) : cells.length === 0 ? (
                <div className="professional-model-empty">
                  <strong>No cells returned for {selectedSheet}</strong>
                  <span>The sheet exists, but this page contains no preview cells.</span>
                </div>
              ) : (
                <div
                  className="table-shell professional-model-cell-table"
                  role="region"
                  aria-label={`${selectedSheet} cell preview`}
                  tabIndex={0}
                >
                  <table className="data-table">
                    <caption className="sr-only">
                      Paginated formula, value, format, and lineage preview for {selectedSheet}
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col">Cell</th>
                        <th scope="col">Period</th>
                        <th scope="col">Formula</th>
                        <th scope="col">Cached / value</th>
                        <th scope="col">Number format</th>
                        <th scope="col">Lineage / comments</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cells.map((cell) => {
                        const period = periodPresentation(cell.period_type);
                        const lineage = displayValue(cell.lineage);
                        const cached =
                          cell.cached_value !== undefined
                            ? cell.cached_value
                            : cell.displayed_value ?? cell.value;
                        return (
                          <tr key={cell.address} className={period.className}>
                            <th scope="row" className="professional-model-cell-address">
                              {cell.address}
                            </th>
                            <td>
                              <span className="professional-model-period-label">
                                {period.label}
                              </span>
                              {cell.classification ? (
                                <small>{titleize(cell.classification)}</small>
                              ) : null}
                            </td>
                            <td className="professional-model-formula-cell">
                              <code>{cell.formula || "No formula"}</code>
                            </td>
                            <td>{displayValue(cached)}</td>
                            <td>
                              <code>{cell.number_format || "Not supplied"}</code>
                            </td>
                            <td className="professional-model-lineage-cell">
                              <span>{lineage}</span>
                              {cell.comment ? <small>Comment: {cell.comment}</small> : null}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              <div className="professional-model-pagination" aria-label="Sheet preview pagination">
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                  disabled={page <= 1 || sheetQuery.isPending}
                >
                  Previous page
                </button>
                <span>
                  Page {page} of {totalPages}
                </span>
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
                  disabled={page >= totalPages || sheetQuery.isPending}
                >
                  Next page
                </button>
              </div>

              <section className="professional-model-findings" aria-labelledby="sheet-findings-title">
                <h3 id="sheet-findings-title">Exact audit findings</h3>
                {findings.length === 0 ? (
                  <p className="table-note">No audit findings supplied for this sheet.</p>
                ) : (
                  <ul className="professional-model-finding-list">
                    {findings.map((finding, index) => (
                      <li key={finding.finding_id ?? `${finding.reason_code}-${index}`}>
                        <div>
                          <code>{finding.reason_code}</code>
                          <span>{titleize(finding.status ?? finding.severity)}</span>
                          {finding.cell ? <span>Cell {finding.cell}</span> : null}
                        </div>
                        <p>{finding.message || "No finding explanation supplied."}</p>
                        {finding.remediation ? (
                          <small>Remediation: {finding.remediation}</small>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </section>
  );
}

