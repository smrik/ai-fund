import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { queryClient } from "@/app/queryClient";
import { router } from "@/app/router";

const watchlistPayload = {
  rows: [
    {
      ticker: "IBM",
      company_name: "IBM",
      price: 100,
      iv_bear: 80,
      iv_base: 120,
      iv_bull: 150,
      expected_iv: 126,
      analyst_target: 140,
      expected_upside_pct: 26,
      upside_base_pct: 20,
      latest_action: "BUY",
      latest_conviction: "high",
      latest_snapshot_date: "2026-03-28",
    },
  ],
  saved_row_count: 1,
  universe_row_count: 1,
  shortlist_size: 10,
  last_updated: "2026-03-28",
  default_focus_ticker: "IBM",
};

const canonicalDossier = {
  contract_name: "TickerDossier",
  contract_version: "1.0.0",
  ticker: "IBM",
  as_of_date: "2026-04-30",
  display_name: "Canonical Machines",
  currency: "USD",
  latest_snapshot: {
    company_identity: {
      ticker: "IBM",
      display_name: "Canonical Machines",
      sector: "Canonical Sector",
    },
    market_snapshot: {
      as_of_date: "2026-04-30",
      price: 111,
      analyst_target: 222,
    },
    valuation_snapshot: {
      bear_iv: 120,
      base_iv: 155,
      bull_iv: 210,
      expected_iv: 166,
      current_price: 112,
      upside_pct: 0.35,
    },
  },
  loaded_backend_state: { backend_name: "test", source_mode: "latest_snapshot" },
  source_lineage: {},
  export_metadata: { source_mode: "latest_snapshot", snapshot_id: 44 },
  optional_overlays: {},
} as const;

const workspacePayload = {
  ticker: "IBM",
  company_name: "IBM",
  sector: "Technology",
  action: "BUY",
  conviction: "high",
  current_price: 100,
  base_iv: 120,
  upside_pct_base: 0.2,
  latest_snapshot_date: "2026-03-28",
  snapshot_available: true,
  ticker_dossier: canonicalDossier,
  ticker_dossier_contract_version: "1.0.0",
};

function renderRoute(path: string) {
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={createMemoryRouter(router.routes, { initialEntries: [path] })} />
    </QueryClientProvider>,
  );
}

function buildResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  queryClient.clear();
});

describe("export flows", () => {
  it("renders the audit export hub, queues ticker exports, and refreshes history", async () => {
    const requests: Array<{ url: string; body: string | null }> = [];
    let exportCompleted = false;
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, body: typeof init?.body === "string" ? init.body : null });

        if (url.endsWith("/api/tickers/IBM/workspace")) {
          return buildResponse(workspacePayload);
        }
        if (url.endsWith("/api/tickers/IBM/audit")) {
          return buildResponse({
            ticker: "IBM",
            dcf_audit: {
              scenario_summary: [{ scenario: "base", intrinsic_value: 120 }],
              model_integrity: { tv_pct_of_ev: 68, tv_high_flag: false, revenue_data_quality_flag: "company", nwc_driver_quality_flag: false },
            },
            filings_browser: {
              retrieval_rows: [{ filing_type: "10-K", filing_date: "2026-02-01", source: "SEC", status: "loaded" }],
              coverage_summary: { statement_presence: { income_statement: true }, by_section_key: { mdna: 3 } },
            },
            comps: {
              peer_counts: { raw: 12, clean: 9 },
              target_vs_peers: { target: { tev_ebitda_fwd: 11.2 }, peer_medians: { tev_ebitda_fwd: 10.1 } },
              historical_multiples_summary: { metrics: {} },
              audit_flags: ["Peer set cleaned from 12 to 9"],
            },
          });
        }
        if (url.endsWith("/api/tickers/IBM/exports") && (init?.method ?? "GET") === "POST") {
          return buildResponse({ run_id: "run-export", status: "queued" }, 202);
        }
        if (url.endsWith("/api/tickers/IBM/exports")) {
          return buildResponse({
            exports: exportCompleted
              ? [
                  {
                    export_id: "exp-html-1",
                    ticker: "IBM",
                    scope: "ticker",
                    status: "completed",
                    export_format: "html",
                    source_mode: "latest_snapshot",
                    title: "IBM HTML export",
                    created_at: "2026-03-31T09:00:00+00:00",
                    artifacts: [{ artifact_key: "html_report", title: "IBM Memo", is_primary: true }],
                  },
                ]
              : [],
          });
        }
        if (url.endsWith("/api/runs/run-export")) {
          exportCompleted = true;
          return buildResponse({
            run_id: "run-export",
            status: "completed",
            result: { export_id: "exp-html-1" },
          });
        }

        return buildResponse({ ok: true });
      }) as unknown as typeof fetch,
    );

    renderRoute("/ticker/IBM/audit");

    expect(await screen.findByRole("heading", { name: "Canonical Machines" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Exports" }));
    expect(await screen.findByText("Recent Exports")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Export HTML Memo" }));

    await waitFor(() =>
      expect(
        requests.some(
          (request) =>
            request.url.endsWith("/api/tickers/IBM/exports") &&
            request.body === JSON.stringify({ format: "html", source_mode: "latest_snapshot" }),
        ),
      ).toBe(true),
    );
    expect(await screen.findByText("IBM HTML export")).toBeInTheDocument();
    expect(clickSpy).toHaveBeenCalled();
  });

  it("adds valuation and research shortcut exports", async () => {
    const requests: Array<{ url: string; body: string | null }> = [];
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    let nextExportId = "exp-xlsx-1";

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, body: typeof init?.body === "string" ? init.body : null });

        if (url.endsWith("/api/tickers/IBM/workspace")) {
          return buildResponse(workspacePayload);
        }
        if (url.endsWith("/api/tickers/IBM/valuation/summary")) {
          return buildResponse({
            ticker: "IBM",
            current_price: 100,
            base_iv: 120,
            upside_pct_base: 20,
            analyst_target: 140,
            ticker_dossier: canonicalDossier,
            ticker_dossier_contract_version: "1.0.0",
          });
        }
        if (url.endsWith("/api/tickers/IBM/research")) {
          return buildResponse({
            ticker: "IBM",
            tracker: { stance: { pm_action: "WATCH", pm_conviction: "low", summary_note: "Memo ready.", overall_status: "scheduled" } },
            notebook: { counts: { all: 1 }, blocks_by_type: { thesis: [{ title: "Scale economics", markdown_block: "Density matters." }] } },
            publishable_memo_preview: "# Memo\n\n## Summary\n\nDraft",
          });
        }
        if (url.endsWith("/api/tickers/IBM/exports") && (init?.method ?? "GET") === "POST") {
          return buildResponse({ run_id: `run-${nextExportId}`, status: "queued" }, 202);
        }
        if (url.endsWith(`/api/runs/run-${nextExportId}`)) {
          const currentExportId = nextExportId;
          nextExportId = nextExportId === "exp-xlsx-1" ? "exp-html-1" : nextExportId;
          return buildResponse({
            run_id: `run-${currentExportId}`,
            status: "completed",
            result: { export_id: currentExportId },
          });
        }
        if (url.endsWith("/api/tickers/IBM/snapshot/open-latest") || url.endsWith("/api/tickers/IBM/analysis/run")) {
          return buildResponse({ ok: true });
        }

        return buildResponse({ exports: [] });
      }) as unknown as typeof fetch,
    );

    renderRoute("/ticker/IBM/valuation");
    expect(await screen.findByRole("heading", { name: "Canonical Machines" })).toBeInTheDocument();
    expect(screen.getAllByText("$155.00").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Export Excel" }));

    await waitFor(() =>
      expect(
        requests.some(
          (request) =>
            request.url.endsWith("/api/tickers/IBM/exports") &&
            request.body === JSON.stringify({ format: "xlsx", source_mode: "loaded_backend_state" }),
        ),
      ).toBe(true),
    );
    expect(clickSpy).toHaveBeenCalledTimes(1);

    cleanup();
    queryClient.clear();

    renderRoute("/ticker/IBM/research");
    expect(await screen.findByRole("heading", { name: "Canonical Machines" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Export HTML Memo" }));

    await waitFor(() =>
      expect(
        requests.some(
          (request) =>
            request.url.endsWith("/api/tickers/IBM/exports") &&
            request.body === JSON.stringify({ format: "html", source_mode: "loaded_backend_state" }),
        ),
      ).toBe(true),
    );
    expect(clickSpy).toHaveBeenCalledTimes(2);
  });

  it("shows explicit watchlist export actions and queues batch exports", async () => {
    const requests: Array<{ url: string; body: string | null }> = [];
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    let exportCompleted = false;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, body: typeof init?.body === "string" ? init.body : null });

        if (url.endsWith("/api/watchlist")) {
          return buildResponse(watchlistPayload);
        }
        if (url.endsWith("/api/watchlist/exports") && (init?.method ?? "GET") === "POST") {
          return buildResponse({ run_id: "run-watchlist-export", status: "queued" }, 202);
        }
        if (url.endsWith("/api/watchlist/exports")) {
          return buildResponse({
            exports: exportCompleted
              ? [
                  {
                    export_id: "batch-html-1",
                    scope: "batch",
                    status: "completed",
                    export_format: "html",
                    source_mode: "saved_watchlist",
                    title: "Watchlist HTML export",
                    created_at: "2026-03-31T09:00:00+00:00",
                  },
                ]
              : [],
          });
        }
        if (url.endsWith("/api/runs/run-watchlist-export")) {
          exportCompleted = true;
          return buildResponse({
            run_id: "run-watchlist-export",
            status: "completed",
            result: { export_id: "batch-html-1" },
          });
        }

        return buildResponse({ ok: true });
      }) as unknown as typeof fetch,
    );

    renderRoute("/watchlist");

    expect(await screen.findByRole("heading", { name: "Universe Tracker" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Export Watchlist HTML" }));

    await waitFor(() =>
      expect(
        requests.some(
          (request) =>
            request.url.endsWith("/api/watchlist/exports") &&
            request.body === JSON.stringify({ format: "html", source_mode: "saved_watchlist", shortlist_size: 10 }),
        ),
      ).toBe(true),
    );
    expect(await screen.findByText("Watchlist HTML export")).toBeInTheDocument();
    expect(clickSpy).toHaveBeenCalled();
  });
});
