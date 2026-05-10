import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
      expected_iv: 130,
      analyst_target: 140,
      expected_upside_pct: 30,
      upside_base_pct: 20,
      latest_action: "BUY",
      latest_conviction: "high",
      latest_snapshot_date: "2026-03-28",
    },
  ],
  saved_row_count: 1,
  universe_row_count: 1,
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
      industry: "Canonical Industry",
      exchange: "NYSE",
    },
    market_snapshot: {
      as_of_date: "2026-04-30",
      price: 111,
      analyst_target: 222,
      analyst_recommendation: "canonical-rating",
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

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url.endsWith("/api/watchlist")) {
        return new Response(JSON.stringify(watchlistPayload), { status: 200 });
      }

      if (url.endsWith("/api/tickers/IBM/workspace")) {
        return new Response(JSON.stringify(workspacePayload), { status: 200 });
      }

      if (url.endsWith("/api/tickers/IBM/overview")) {
        return new Response(
          JSON.stringify({
            ticker: "IBM",
            company_name: "IBM",
            one_liner: "Memo",
            variant_thesis_prompt: "Question?",
            thesis_changes: ["Moved to watchlist-first IA"],
            ticker_dossier: canonicalDossier,
            ticker_dossier_contract_version: "1.0.0",
          }),
          { status: 200 },
        );
      }

      if (url.endsWith("/api/tickers/IBM/valuation/summary")) {
        return new Response(
          JSON.stringify({
            ticker: "IBM",
            current_price: 100,
            base_iv: 120,
            bear_iv: 90,
            bull_iv: 150,
            weighted_iv: 126,
            upside_pct_base: 20,
            analyst_target: 140,
            conviction: "high",
            memo_date: "2026-03-28",
            why_it_matters: "Base case still implies upside with a controlled terminal value contribution.",
            readiness: { tv_high_flag: false, revenue_data_quality_flag: "company", nwc_driver_quality_flag: false },
            ticker_dossier: canonicalDossier,
            ticker_dossier_contract_version: "1.0.0",
          }),
          { status: 200 },
        );
      }

      if (url.endsWith("/api/tickers/IBM/valuation/dcf")) {
        return new Response(
          JSON.stringify({
            ticker: "IBM",
            scenario_summary: [
              { scenario: "bear", probability_pct: 25, intrinsic_value: 90, upside_pct: -10 },
              { scenario: "base", probability_pct: 50, intrinsic_value: 120, upside_pct: 20 },
              { scenario: "bull", probability_pct: 25, intrinsic_value: 150, upside_pct: 50 },
            ],
            forecast_bridge: [
              { year: 1, revenue_mm: 1000, growth_pct: 8, ebit_margin_pct: 12, fcff_mm: 90, roic_pct: 14 },
            ],
            terminal_bridge: { method_used: "blended", terminal_growth_pct: 3, tv_pct_of_ev: 68 },
            ev_bridge: { enterprise_value_total_mm: 1800, equity_value_mm: 1500, intrinsic_value_per_share: 120 },
            driver_rows: [{ label: "WACC", value: 8.2, unit: "pct", source: "company" }],
            health_flags: { tv_high_flag: false, nwc_driver_quality_flag: true },
            chart_series: {
              scenario_iv: [
                { scenario: "Bear", intrinsic_value: 90 },
                { scenario: "Base", intrinsic_value: 120 },
              ],
              fcff_curve: [
                { year: 2024, fcff_mm: 90, nopat_mm: 110 },
                { year: 2025, fcff_mm: 105, nopat_mm: 122 },
                { year: 2026, fcff_mm: 118, nopat_mm: 130 },
              ],
              risk_overlay: [{ risk_name: "Margin compression", stressed_iv: 104, probability: 0.3 }],
            },
            risk_impact: {
              available: true,
              base_iv: 120,
              risk_adjusted_expected_iv: 111,
              overlay_results: [{ risk_name: "Margin compression", stressed_iv: 104 }],
            },
            sensitivity: {
              wacc_x_terminal_growth: [{ wacc: "7.5%", values: { "2.0%": 112, "3.0%": 120 } }],
              wacc_x_exit_multiple: [{ wacc: "7.5%", values: { "10.0x": 114, "11.0x": 121 } }],
            },
            model_integrity: { tv_high_flag: false, revenue_data_quality_flag: "company", nwc_driver_quality_flag: false },
          }),
          { status: 200 },
        );
      }

      if (url.endsWith("/api/tickers/IBM/valuation/assumptions")) {
        return new Response(
          JSON.stringify({
            ticker: "IBM",
            current_price: 100,
            current_iv_base: 120,
            current_expected_iv: 126,
            fields: [
              {
                field: "wacc",
                label: "WACC",
                unit: "pct",
                baseline_value: 0.082,
                effective_value: 0.081,
                agent_value: 0.078,
                baseline_source: "sector_default",
                effective_source: "ticker_override",
                agent_name: "valuation",
                agent_confidence: "high",
                agent_status: "pending",
                initial_mode: "default",
              },
            ],
            audit_rows: [{ field: "wacc", mode: "agent", action: "apply" }],
          }),
          { status: 200 },
        );
      }

      if (url.endsWith("/api/tickers/IBM/valuation/assumptions/preview")) {
        return new Response(
          JSON.stringify({
            ticker: "IBM",
            current_iv: { bear: 90, base: 120, bull: 150 },
            proposed_iv: { bear: 94, base: 127, bull: 158 },
            current_expected_iv: 126,
            proposed_expected_iv: 133,
            delta_pct: { bear: 4.4, base: 5.8, bull: 5.3 },
            resolved_values: {
              wacc: { mode: "agent", effective_value: 0.081, value: 0.078 },
            },
          }),
          { status: 200 },
        );
      }

      if (url.endsWith("/api/tickers/IBM/valuation/wacc")) {
        return new Response(
          JSON.stringify({
            ticker: "IBM",
            current_wacc: 0.08,
            proposed_wacc: 0.075,
            method: "peer_bottom_up",
            current_selection: { mode: "single_method", selected_method: "peer_bottom_up", weights: {} },
            methods: [
              {
                method: "peer_bottom_up",
                wacc: 0.075,
                cost_of_equity: 0.102,
                cost_of_debt_after_tax: 0.041,
                beta_value: 1.12,
                beta_source: "peer_unlevered_median",
                assumptions: { equity_weight: 0.78, debt_weight: 0.22 },
              },
              {
                method: "industry_proxy",
                wacc: 0.079,
                cost_of_equity: 0.108,
                cost_of_debt_after_tax: 0.041,
                beta_value: 1.18,
                beta_source: "industry_proxy_beta",
                assumptions: { equity_weight: 0.8, debt_weight: 0.2 },
              },
            ],
            effective_preview: {
              wacc: 0.08,
              expected_method_wacc: 0.075,
              current_iv: { base: 120 },
              proposed_iv: { base: 127 },
            },
            audit_rows: [{ event_ts: "2026-03-28", selected_method: "peer_bottom_up", effective_wacc: 0.075 }],
          }),
          { status: 200 },
        );
      }

      if (url.endsWith("/api/tickers/IBM/valuation/wacc/preview")) {
        return new Response(
          JSON.stringify({
            ticker: "IBM",
            selection: { mode: "single_method", selected_method: "peer_bottom_up", weights: {} },
            current_wacc: 0.08,
            effective_wacc: 0.075,
            current_iv: { base: 120 },
            proposed_iv: { base: 127 },
            current_expected_iv: 126,
            proposed_expected_iv: 133,
          }),
          { status: 200 },
        );
      }

      if (url.endsWith("/api/tickers/IBM/valuation/comps")) {
        return new Response(
          JSON.stringify({
            ticker: "IBM",
            peer_counts: { raw: 12, clean: 9 },
            selected_metric_default: "tev_ebitda_fwd",
            metric_options: [
              { key: "tev_ebitda_fwd", label: "TEV / EBITDA Fwd" },
              { key: "pe_ltm", label: "P / E LTM" },
            ],
            valuation_range: { blended_base: 128 },
            valuation_range_by_metric: {
              tev_ebitda_fwd: { label: "TEV / EBITDA Fwd", bear: 100, base: 125, bull: 150 },
              pe_ltm: { label: "P / E LTM", bear: 95, base: 118, bull: 140 },
            },
            target: { current_price: 100 },
            football_field: {
              ranges: [{ label: "TEV / EBITDA Fwd", bear: 100, base: 125, bull: 150 }],
              markers: [{ label: "Current Price", type: "spot", value: 100 }],
            },
            target_vs_peers: {
              target: { tev_ebitda_fwd: 11.2, revenue_growth: 7.4 },
              peer_medians: { tev_ebitda_fwd: 10.1, revenue_growth: 6.2 },
              deltas: { tev_ebitda_fwd: 1.1, revenue_growth: 1.2 },
            },
            peers: [
              { ticker: "ACME", similarity_score: 0.92, model_weight: 0.25, tev_ebitda_ltm: 10.4, tev_ebit_fwd: 12.1, tev_ebit_ltm: 13.2, pe_ltm: 18.0, revenue_growth: 6.1, ebit_margin: 0.13, net_debt_to_ebitda: 1.2 },
            ],
            historical_multiples_summary: {
              available: true,
              metrics: {
                pe_trailing: {
                  summary: { current: 18.2, median: 16.7, min: 11.4, max: 22.3, current_percentile: 0.72, peer_current: 17.1 },
                  series: [
                    { date: "2024-01-01", multiple: 14.1, price: 82 },
                    { date: "2025-01-01", multiple: 16.4, price: 91 },
                    { date: "2026-01-01", multiple: 17.2, price: 98 },
                  ],
                },
              },
            },
            audit_flags: ["Peer set cleaned from 12 to 9"],
          }),
          { status: 200 },
        );
      }

      if (url.endsWith("/api/tickers/IBM/valuation/recommendations")) {
        return new Response(
          JSON.stringify({
            ticker: "IBM",
            available: true,
            generated_at: "2026-03-28T10:00:00+00:00",
            current_iv_base: 120,
            recommendations: [
              {
                agent: "qoe",
                field: "ebit_margin_start",
                current_value: 0.12,
                proposed_value: 0.135,
                confidence: "high",
                rationale: "Normalize EBIT after one-offs.",
                citation: "10-K note 7",
                status: "pending",
              },
            ],
          }),
          { status: 200 },
        );
      }

      if (url.endsWith("/api/tickers/IBM/valuation/recommendations/preview")) {
        return new Response(
          JSON.stringify({
            ticker: "IBM",
            current_iv: { bear: 90, base: 120, bull: 150 },
            proposed_iv: { bear: 92, base: 126, bull: 155 },
            delta_pct: { bear: 2.2, base: 5.0, bull: 3.3 },
          }),
          { status: 200 },
        );
      }

      if (url.endsWith("/api/tickers/IBM/market")) {
        return new Response(
          JSON.stringify({
            ticker: "IBM",
            historical_brief: {
              summary: "Local history from archived reports highlights pricing power and M&A integration risk.",
              period_start: "2023-03-28T00:00:00+00:00",
              period_end: "2026-03-28T00:00:00+00:00",
              event_timeline: [
                { date_label: "2025-10-12", source: "report_archive", category: "quarter_update", summary: "Margin held despite feed volatility." },
                { date_label: "2026-02-01", source: "report_archive", category: "research_stance", summary: "Research stance WATCH (low)." },
              ],
            },
            quarterly_headlines: [
              { date: "2026-03-01", source: "Reuters", title: "Cal-Maine raises questions on peak egg pricing", materiality_score: 92.5, materiality_bucket: "high", topic_bucket: "guidance" },
              { date: "2026-02-18", source: "Bloomberg", title: "Indiana deal broadens platform", materiality_score: 81.2, materiality_bucket: "high", topic_bucket: "m&a" },
            ],
            headlines: [
              { date: "2026-03-01", source: "Reuters", title: "Cal-Maine raises questions on peak egg pricing", materiality_score: 92.5, materiality_bucket: "high", topic_bucket: "guidance" },
              { date: "2026-02-18", source: "Bloomberg", title: "Indiana deal broadens platform", materiality_score: 81.2, materiality_bucket: "high", topic_bucket: "m&a" },
            ],
            analyst_snapshot: {
              recommendation: "hold",
              target_mean: 88,
              num_analysts: 6,
              current_price: 77.12,
            },
            sentiment_summary: {
              direction: "bearish",
              score: -0.22,
              raw_summary: "Narrative remains skeptical on durability of outsized egg pricing.",
              key_bullish_themes: ["Balance sheet flexibility", "Platform expansion"],
              key_bearish_themes: ["Mean-reverting egg prices", "Regulatory scrutiny"],
              risk_narratives: ["Peak-margin normalization could reset the multiple quickly."],
            },
            revisions: {
              available: true,
              eps_revision_30d_pct: 0.06,
              revenue_revision_30d_pct: 0.02,
              eps_revision_90d_pct: 0.11,
              estimate_dispersion: 0.14,
              revision_momentum: "strong_positive",
              num_analysts: 6,
              as_of_date: "2026-03-28",
            },
            macro: {
              regime: {
                label: "Neutral",
                probabilities: { "Risk-On": 0.24, Neutral: 0.58, "Risk-Off": 0.18 },
                as_of_date: "2026-03-28",
                available: true,
              },
              scenario_weights: { bear: 0.2, base: 0.6, bull: 0.2, regime: "Neutral" },
              snapshot: {
                available: true,
                series: {
                  VIXCLS: { latest_value: 18.2, latest_date: "2026-03-28" },
                  BAMLH0A0HYM2: { latest_value: 0.038, latest_date: "2026-03-28" },
                  T10Y2Y: { latest_value: 0.009, latest_date: "2026-03-28" },
                  FEDFUNDS: { latest_value: 0.0475, latest_date: "2026-03-28" },
                },
                as_of_date: "2026-03-28",
              },
              yield_curve: {
                available: true,
                as_of_date: "2026-03-28",
                maturities: [["3M", 0.25, 4.8], ["2Y", 2, 4.15], ["10Y", 10, 4.24], ["30Y", 30, 4.48]],
              },
            },
            factor_exposure: {
              available: true,
              market_beta: 0.72,
              r_squared: 0.41,
              annualized_alpha: 0.035,
              value_beta: 0.46,
              momentum_beta: -0.18,
              profitability_beta: 0.22,
              factor_attribution: { Mkt_RF: 0.54, HML: 0.26, Mom: -0.2 },
              summary_text: "Returns are partly explained by market beta and a moderate value tilt.",
            },
            audit_flags: ["Limited historical brief uses limited local evidence"],
          }),
          { status: 200 },
        );
      }

      if (url.endsWith("/api/tickers/IBM/research")) {
        return new Response(
          JSON.stringify({
            ticker: "IBM",
            tracker: {
              stance: {
                pm_action: "WATCH",
                pm_conviction: "low",
                summary_note: "Cost discipline improved, but acquisition execution still needs proof.",
                overall_status: "scheduled",
                last_reviewed_at: "2026-03-28T17:32:35+00:00",
                next_catalyst: { title: "DOJ remedy update", expected_date: "2026-05-15" },
              },
              what_changed: {
                summary_lines: ["Base IV moved by +6.00.", "1 catalyst added."],
              },
              pillar_board: [
                {
                  pillar_id: "pillar-scale",
                  title: "Scale Economics",
                  description: "Distribution density is starting to widen the cost advantage.",
                  pm_status: "watching",
                  latest_evidence_cue: "Gross margin held while feed costs normalized.",
                },
              ],
              catalyst_board: {
                urgent_open: [
                  {
                    catalyst_key: "doj-remedy",
                    title: "DOJ remedy update",
                    status: "open",
                    expected_date: "2026-05-15",
                    latest_evidence_cue: "Antitrust remedy could reset M&A optionality.",
                  },
                ],
                watching: [],
                resolved: [],
              },
              continuity: {
                latest_decision: { review_due_date: "2026-05-30", decision_note: "Hold for evidence on integration." },
                latest_review: { created_at: "2026-03-28T17:32:35+00:00", summary: "Margin and integration risks still open." },
                latest_checkpoint: { checkpoint_ts: "2026-03-28T17:00:00+00:00", valuation: { base_iv: 126, current_price: 100 } },
              },
              next_queue: {
                open_questions: [{ question: "What changes trough-cycle earnings durability?" }],
                open_question_count: 1,
                upcoming_catalysts: [{ title: "DOJ remedy update" }],
                upcoming_catalyst_count: 1,
                review_status: "scheduled",
                missing_evidence_flags: ["legacy_pillar_fallback"],
              },
            },
            notebook: {
              available: true,
              counts: {
                all: 3,
              },
              blocks_by_type: {
                thesis: [{ title: "Scale economics note", markdown_block: "Distribution density is compounding." }],
                risk: [{ title: "Integration risk", markdown_block: "Execution risk still unproven." }],
                catalyst: [{ title: "DOJ remedy update", markdown_block: "Key timing catalyst." }],
              },
            },
            publishable_memo_preview: `---
ticker: IBM
company_name: IBM
note_slug: publishable_memo
section_kind: publishable_memo
---

# 10 Publishable Memo

## Summary

## Business

## Thesis

## Valuation

## Risks

## Catalysts

## Sources
`,
          }),
          { status: 200 },
        );
      }

      if (url.endsWith("/api/tickers/IBM/audit")) {
        return new Response(
          JSON.stringify({
            ticker: "IBM",
            dcf_audit: {
              scenario_summary: [
                { scenario: "bear", intrinsic_value: 90 },
                { scenario: "base", intrinsic_value: 120 },
              ],
              driver_rows: [{ label: "WACC", value: 8.2, source: "company" }],
              health_flags: { tv_high_flag: false, nwc_driver_quality_flag: true },
              model_integrity: { tv_pct_of_ev: 68, tv_high_flag: false, revenue_data_quality_flag: "company", nwc_driver_quality_flag: false },
            },
            filings_browser: {
              retrieval_rows: [{ filing_type: "10-K", filing_date: "2026-02-01", source: "SEC", status: "loaded" }],
              coverage_summary: { statement_presence: { income_statement: true, cash_flow: true }, by_section_key: { mdna: 3, risk_factors: 2 } },
              retrieval_profiles: {
                filings: { fallback_mode: false, selected_chunk_count: 8, skipped_sections: [] },
                qoe: { fallback_mode: true, selected_chunk_count: 2, skipped_sections: ["notes"] },
              },
              agent_usage: {
                filings: [{ section_key: "mdna", filing_date: "2026-02-01", score: 0.92 }],
                qoe: [{ section_key: "risk_factors", filing_date: "2026-02-01", score: 0.71 }],
              },
            },
            comps: {
              peer_counts: { raw: 12, clean: 9 },
              primary_metric: "tev_ebitda_fwd",
              valuation_range_by_metric: {
                tev_ebitda_fwd: { label: "TEV / EBITDA Fwd", bear: 100, base: 125, bull: 150 },
              },
              target_vs_peers: {
                target: { tev_ebitda_fwd: 11.2, revenue_growth: 7.4 },
                peer_medians: { tev_ebitda_fwd: 10.1, revenue_growth: 6.2 },
              },
              historical_multiples_summary: {
                metrics: {
                  pe_trailing: {
                    summary: { current: 18.2, median: 16.7, current_percentile: 0.72, peer_current: 17.1, min: 11.4, max: 22.3 },
                  },
                },
              },
              audit_flags: ["Peer set cleaned from 12 to 9"],
              notes: "Forward TEV / EBITDA is the cleanest signal.",
            },
          }),
          { status: 200 },
        );
      }

      if (
        url.endsWith("/api/tickers/IBM/valuation/assumptions/apply") ||
        url.endsWith("/api/tickers/IBM/valuation/wacc/apply") ||
        url.endsWith("/api/tickers/IBM/valuation/recommendations/apply") ||
        url.endsWith("/api/tickers/IBM/snapshot/open-latest") ||
        url.endsWith("/api/tickers/IBM/analysis/run")
      ) {
        return new Response(JSON.stringify({ run_id: "run-123", status: "queued" }), { status: 202 });
      }

      if (url.endsWith("/api/runs/run-123")) {
        return new Response(JSON.stringify({ run_id: "run-123", status: "completed", result: { ok: true } }), { status: 200 });
      }

      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }) as unknown as typeof fetch,
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  queryClient.clear();
});

function renderRoute(path: string) {
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={createMemoryRouter(router.routes, { initialEntries: [path] })} />
    </QueryClientProvider>,
  );
}

describe("frontend routes", () => {
  it("renders the watchlist landing page with the saved batch actions", async () => {
    renderRoute("/watchlist");

    expect(await screen.findByRole("heading", { name: "Universe Tracker" })).toBeInTheDocument();
    expect(await screen.findByText("Ranked Universe")).toBeInTheDocument();
    expect(screen.getByText("Last Updated")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open IBM" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh Deterministic Batch" })).toBeInTheDocument();
    expect(screen.getByText("Rating")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "IBM" })).not.toBeInTheDocument();
  });

  it("renders a shared ticker nav and a consistent overview hero", async () => {
    renderRoute("/ticker/IBM/overview");

    expect(await screen.findByRole("heading", { name: "Canonical Machines" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "IBM" })).toBeInTheDocument();
    expect(screen.getByText("$155.00")).toBeInTheDocument();
    expect(screen.getByText("+35.0%")).toBeInTheDocument();
    expect(screen.getByText("Variant Thesis")).toBeInTheDocument();
    expect(screen.getByText("Latest Snapshot")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Latest Snapshot" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run Deep Analysis" })).toBeInTheDocument();
  });

  it("shows valuation sub-navigation including assumptions and wacc", async () => {
    renderRoute("/ticker/IBM/valuation?view=Assumptions");

    expect(await screen.findByRole("heading", { name: "Canonical Machines" })).toBeInTheDocument();
    expect(screen.getByText("$111.00")).toBeInTheDocument();
    expect(screen.getAllByText("$155.00").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Assumptions" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "WACC" })).toBeInTheDocument();
  });

  it("fetches only the relevant endpoint for assumptions, wacc, comparables, multiples, and recommendations", async () => {
    vi.unstubAllGlobals();

    const hits = {
      workspace: 0,
      summary: 0,
      dcf: 0,
      comps: 0,
      assumptions: 0,
      assumptionsPreview: 0,
      wacc: 0,
      waccPreview: 0,
      recommendations: 0,
    };

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);

        if (url.endsWith("/api/tickers/IBM/workspace")) {
          hits.workspace += 1;
          return new Response(JSON.stringify(workspacePayload), { status: 200 });
        }

        if (url.endsWith("/api/tickers/IBM/valuation/summary")) {
          hits.summary += 1;
          return new Response(JSON.stringify({ ticker: "IBM" }), { status: 200 });
        }

        if (url.endsWith("/api/tickers/IBM/valuation/dcf")) {
          hits.dcf += 1;
          return new Response(JSON.stringify({ ticker: "IBM" }), { status: 200 });
        }

        if (url.endsWith("/api/tickers/IBM/valuation/comps")) {
          hits.comps += 1;
          return new Response(JSON.stringify({ ticker: "IBM", historical_multiples_summary: { available: true, metrics: {} } }), { status: 200 });
        }

        if (url.endsWith("/api/tickers/IBM/valuation/assumptions")) {
          hits.assumptions += 1;
          return new Response(JSON.stringify({ ticker: "IBM", current_price: 100, current_iv_base: 120, fields: [] }), { status: 200 });
        }

        if (url.endsWith("/api/tickers/IBM/valuation/assumptions/preview")) {
          hits.assumptionsPreview += 1;
          return new Response(JSON.stringify({ ticker: "IBM" }), { status: 200 });
        }

        if (url.endsWith("/api/tickers/IBM/valuation/wacc")) {
          hits.wacc += 1;
          return new Response(JSON.stringify({ ticker: "IBM", current_wacc: 0.08, proposed_wacc: 0.075, method: "peer_bottom_up", methods: [] }), {
            status: 200,
          });
        }

        if (url.endsWith("/api/tickers/IBM/valuation/wacc/preview")) {
          hits.waccPreview += 1;
          return new Response(JSON.stringify({ ticker: "IBM" }), { status: 200 });
        }

        if (url.endsWith("/api/tickers/IBM/valuation/recommendations")) {
          hits.recommendations += 1;
          return new Response(JSON.stringify({ ticker: "IBM", recommendations: [] }), { status: 200 });
        }

        if (url.endsWith("/api/tickers/IBM/snapshot/open-latest") || url.endsWith("/api/tickers/IBM/analysis/run")) {
          return new Response(JSON.stringify({ ok: true }), { status: 200 });
        }

        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }) as unknown as typeof fetch,
    );

    renderRoute("/ticker/IBM/valuation?view=Assumptions");

    expect(await screen.findByRole("heading", { name: "Canonical Machines" })).toBeInTheDocument();
    await waitFor(() => expect(hits.assumptions).toBeGreaterThan(0));
    expect(hits.summary).toBe(0);
    expect(hits.dcf).toBe(0);
    expect(hits.comps).toBe(0);

    cleanup();
    queryClient.clear();
    hits.workspace = 0;
    hits.summary = 0;
    hits.dcf = 0;
    hits.comps = 0;
    hits.assumptions = 0;
    hits.assumptionsPreview = 0;
    hits.wacc = 0;
    hits.waccPreview = 0;
    hits.recommendations = 0;

    renderRoute("/ticker/IBM/valuation?view=WACC");

    expect(await screen.findByRole("heading", { name: "Canonical Machines" })).toBeInTheDocument();
    await waitFor(() => expect(hits.wacc).toBeGreaterThan(0));
    expect(hits.summary).toBe(0);
    expect(hits.dcf).toBe(0);
    expect(hits.comps).toBe(0);

    cleanup();
    queryClient.clear();
    hits.workspace = 0;
    hits.summary = 0;
    hits.dcf = 0;
    hits.comps = 0;
    hits.assumptions = 0;
    hits.assumptionsPreview = 0;
    hits.wacc = 0;
    hits.waccPreview = 0;
    hits.recommendations = 0;
    renderRoute("/ticker/IBM/valuation?view=Comparables");
    expect(await screen.findByRole("heading", { name: "Canonical Machines" })).toBeInTheDocument();
    await waitFor(() => expect(hits.comps).toBeGreaterThan(0));
    expect(hits.summary).toBe(0);
    expect(hits.dcf).toBe(0);

    cleanup();
    queryClient.clear();
    hits.workspace = 0;
    hits.summary = 0;
    hits.dcf = 0;
    hits.comps = 0;
    hits.assumptions = 0;
    hits.assumptionsPreview = 0;
    hits.wacc = 0;
    hits.waccPreview = 0;
    hits.recommendations = 0;
    renderRoute("/ticker/IBM/valuation?view=Multiples");
    expect(await screen.findByRole("heading", { name: "Canonical Machines" })).toBeInTheDocument();
    await waitFor(() => expect(hits.comps).toBeGreaterThan(0));

    cleanup();
    queryClient.clear();
    hits.workspace = 0;
    hits.summary = 0;
    hits.dcf = 0;
    hits.comps = 0;
    hits.assumptions = 0;
    hits.assumptionsPreview = 0;
    hits.wacc = 0;
    hits.waccPreview = 0;
    hits.recommendations = 0;
    renderRoute("/ticker/IBM/valuation?view=Recommendations");
    expect(await screen.findByRole("heading", { name: "Canonical Machines" })).toBeInTheDocument();
    await waitFor(() => expect(hits.recommendations).toBeGreaterThan(0));
    expect(hits.summary).toBe(0);
    expect(hits.comps).toBe(0);
  });

  it("keeps ticker navigation shared and valuation sub-navigation local to the page", async () => {
    const { container } = renderRoute("/ticker/IBM/valuation?view=Summary");

    expect(await screen.findByRole("heading", { name: "Canonical Machines" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Latest Snapshot" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run Deep Analysis" })).toBeInTheDocument();
    expect(container.querySelector(".ticker-strip")).not.toBeInTheDocument();
    expect(container.querySelector(".ticker-layout > .ticker-tabs")).toBeInTheDocument();
    expect(container.querySelector(".valuation-route-nav")).toBeInTheDocument();
    expect(container.querySelector(".valuation-route-nav .section-nav")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("href", "/ticker/IBM/overview");
    expect(screen.getByRole("link", { name: "Market" })).toHaveAttribute("href", "/ticker/IBM/market");
    expect(screen.getByRole("link", { name: "Research" })).toHaveAttribute("href", "/ticker/IBM/research");
    expect(screen.getByRole("link", { name: "Audit" })).toHaveAttribute("href", "/ticker/IBM/audit");
  });

  it("renders data-rich valuation content for dcf, comparables, and multiples tabs", async () => {
    const { container } = renderRoute("/ticker/IBM/valuation?view=DCF");

    expect(await screen.findByText("Scenario Summary")).toBeInTheDocument();
    expect(screen.getByText("Forecast Bridge")).toBeInTheDocument();
    expect(screen.getByText("Health Flags")).toBeInTheDocument();
    expect(screen.getByText("Sensitivity Tables")).toBeInTheDocument();
    expect(screen.getByText("FCFF / NOPAT Trend")).toBeInTheDocument();
    expect(container.querySelectorAll(".time-series-chart")).toHaveLength(1);
    expect(container.querySelector(".time-series-chart .chart-axis-label")).toHaveTextContent("Year");
    expect(container.querySelectorAll(".time-series-chart .chart-point")).not.toHaveLength(0);

    cleanup();
    const { container: comparablesContainer } = renderRoute("/ticker/IBM/valuation?view=Comparables");
    expect(await screen.findByText("Target vs Peer Medians")).toBeInTheDocument();
    expect(screen.getByText("Valuation Metric")).toBeInTheDocument();
    expect(screen.getByText("Football Field")).toBeInTheDocument();
    expect(screen.getByText("Peer Table")).toBeInTheDocument();
    expect(comparablesContainer.querySelectorAll(".category-bar-chart")).not.toHaveLength(0);

    cleanup();
    const { container: multiplesContainer } = renderRoute("/ticker/IBM/valuation?view=Multiples");
    expect(await screen.findByText("Historical Multiples")).toBeInTheDocument();
    expect(screen.getAllByText("Historical Multiple Series").length).toBeGreaterThan(0);
    expect(multiplesContainer.querySelectorAll(".time-series-chart")).toHaveLength(1);
    expect(multiplesContainer.querySelector(".time-series-chart .chart-axis-label")).toHaveTextContent("Date");
  });

  it("renders interactive assumptions, wacc, and recommendations workbenches", async () => {
    renderRoute("/ticker/IBM/valuation?view=Assumptions");

    expect(await screen.findByText("Tracked Fields")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "WACC" })).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview Assumptions" })).toBeInTheDocument();
    expect(screen.getByText("Audit History")).toBeInTheDocument();

    cleanup();
    renderRoute("/ticker/IBM/valuation?view=WACC");
    expect(await screen.findByText("Methodology mode")).toBeInTheDocument();
    expect(screen.getByText("Available Methods")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview WACC Selection" })).toBeInTheDocument();
    expect(screen.getByText("WACC Audit History")).toBeInTheDocument();

    cleanup();
    renderRoute("/ticker/IBM/valuation?view=Recommendations");
    expect(await screen.findByText("What-If Preview")).toBeInTheDocument();
    expect(screen.getByText("Quality of Earnings")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview IV with selected approvals" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply Approved → valuation_overrides.yaml" })).toBeInTheDocument();
  });

  it("lets the user preview assumptions, wacc, and recommendations from the valuation route", async () => {
    renderRoute("/ticker/IBM/valuation?view=Assumptions");
    expect(await screen.findByRole("button", { name: "Preview Assumptions" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Preview Assumptions" }));
    expect(await screen.findByText("Preview Delta")).toBeInTheDocument();

    cleanup();
    renderRoute("/ticker/IBM/valuation?view=WACC");
    expect(await screen.findByRole("button", { name: "Preview WACC Selection" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Preview WACC Selection" }));
    expect(await screen.findByText("Proposed Base IV")).toBeInTheDocument();

    cleanup();
    renderRoute("/ticker/IBM/valuation?view=Recommendations");
    expect(await screen.findByRole("button", { name: "Preview IV with selected approvals" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Preview IV with selected approvals" }));
    expect(await screen.findByText("Bear IV")).toBeInTheDocument();
  });

  it("sends the selected recommendation fields when applying approvals", async () => {
    vi.unstubAllGlobals();

    const requests: Array<{ url: string; body: string | null }> = [];

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, body: typeof init?.body === "string" ? init.body : null });

        if (url.endsWith("/api/tickers/IBM/workspace")) {
          return new Response(JSON.stringify(workspacePayload), { status: 200 });
        }

        if (url.endsWith("/api/tickers/IBM/valuation/recommendations")) {
          return new Response(
            JSON.stringify({
              ticker: "IBM",
              available: true,
              generated_at: "2026-03-28T10:00:00+00:00",
              current_iv_base: 120,
              recommendations: [
                {
                  agent: "qoe",
                  field: "ebit_margin_start",
                  current_value: 0.12,
                  proposed_value: 0.135,
                  confidence: "high",
                  rationale: "Normalize EBIT after one-offs.",
                  citation: "10-K note 7",
                  status: "pending",
                },
              ],
            }),
            { status: 200 },
          );
        }

        if (url.endsWith("/api/tickers/IBM/valuation/recommendations/apply")) {
          return new Response(JSON.stringify({ run_id: "run-123", status: "queued" }), { status: 202 });
        }

        if (url.endsWith("/api/runs/run-123")) {
          return new Response(JSON.stringify({ run_id: "run-123", status: "completed", result: { ok: true } }), { status: 200 });
        }

        if (url.endsWith("/api/tickers/IBM/snapshot/open-latest") || url.endsWith("/api/tickers/IBM/analysis/run")) {
          return new Response(JSON.stringify({ ok: true }), { status: 200 });
        }

        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }) as unknown as typeof fetch,
    );

    renderRoute("/ticker/IBM/valuation?view=Recommendations");

    expect(await screen.findByText("What-If Preview")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Apply Approved → valuation_overrides.yaml" }));

    await waitFor(() => {
      const applyRequest = requests.find((request) => request.url.endsWith("/api/tickers/IBM/valuation/recommendations/apply"));
      expect(applyRequest).toBeDefined();
      expect(applyRequest?.body).toBe(JSON.stringify({ approved_fields: ["ebit_margin_start"] }));
    });
  });

  it("renders the other ticker surfaces without blowing up the route shell", async () => {
    const { container: marketContainer } = renderRoute("/ticker/IBM/market");
    expect(await screen.findByRole("heading", { name: "Canonical Machines" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "News & Revisions" })).toBeInTheDocument();
    expect(await screen.findByText("Recommendation")).toBeInTheDocument();
    expect(await screen.findByText("Historical Timeline")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Macro" }));
    expect(await screen.findByText("Market Regime")).toBeInTheDocument();
    expect(await screen.findByText("Yield Curve")).toBeInTheDocument();
    expect(marketContainer.querySelectorAll(".time-series-chart")).toHaveLength(1);
    expect(marketContainer.querySelector(".time-series-chart .chart-axis-label")).toHaveTextContent("Maturity");
    fireEvent.click(screen.getByRole("button", { name: "Sentiment" }));
    expect(await screen.findByText("Bullish Themes")).toBeInTheDocument();
    expect(await screen.findByText("Bearish Themes")).toBeInTheDocument();
    expect(await screen.findByText("What Drives The Score")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Factor Exposure" }));
    expect(await screen.findByRole("heading", { name: "Market Beta" })).toBeInTheDocument();
    expect(await screen.findByText("How to Read These Factor Stats")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "News & Revisions" }));
    expect(await screen.findByText("Revision Momentum")).toBeInTheDocument();
    expect(await screen.findByText("Est. Dispersion")).toBeInTheDocument();

    cleanup();
    renderRoute("/ticker/IBM/research");
    expect(await screen.findByRole("heading", { name: "Canonical Machines" })).toBeInTheDocument();
    expect(await screen.findByText("Cost discipline improved, but acquisition execution still needs proof.")).toBeInTheDocument();
    expect(await screen.findByText("Draft memo available (7 sections: Summary, Business, Thesis, Valuation, Risks, Catalysts, Sources).")).toBeInTheDocument();
    expect(await screen.findByText("WATCH")).toBeInTheDocument();
    expect(await screen.findByText("3")).toBeInTheDocument();
    expect(await screen.findByText("Thesis Pillars")).toBeInTheDocument();
    expect(await screen.findByText("Scale Economics")).toBeInTheDocument();
    expect(await screen.findByText("Upcoming Catalysts")).toBeInTheDocument();
    expect((await screen.findAllByText("DOJ remedy update")).length).toBeGreaterThan(0);
    expect(await screen.findByText("Notebook Highlights")).toBeInTheDocument();
    expect(await screen.findByText("Scale economics note")).toBeInTheDocument();
    expect(screen.queryByText(/note_slug:/i)).not.toBeInTheDocument();

    cleanup();
    renderRoute("/ticker/IBM/audit");
    expect(await screen.findByRole("heading", { name: "Canonical Machines" })).toBeInTheDocument();
    expect(await screen.findByText("DCF Integrity")).toBeInTheDocument();
    expect(await screen.findByText("Filings Coverage")).toBeInTheDocument();
    expect(await screen.findByText("Historical Multiples Audit")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Filings" }));
    expect(await screen.findByText("Fallback Mode")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Flags" }));
    expect(await screen.findByText("Peer set cleaned from 12 to 9")).toBeInTheDocument();
  });

  it("shows an audit loading shell until the payload arrives", async () => {
    vi.unstubAllGlobals();

    let resolveAudit: ((value: Response) => void) | null = null;

    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);

        if (url.endsWith("/api/tickers/IBM/workspace")) {
          return Promise.resolve(new Response(JSON.stringify(workspacePayload), { status: 200 }));
        }

        if (url.endsWith("/api/tickers/IBM/audit")) {
          return new Promise<Response>((resolve) => {
            resolveAudit = resolve;
          });
        }

        return Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 200 }));
      }) as unknown as typeof fetch,
    );

    renderRoute("/ticker/IBM/audit");
    expect(await screen.findByText("Loading audit")).toBeInTheDocument();

    resolveAudit?.(
      new Response(
        JSON.stringify({
          ticker: "IBM",
          dcf_audit: {
            scenario_summary: [{ scenario: "base", intrinsic_value: 120 }],
            driver_rows: [{ label: "WACC", value: 8.2, source: "company" }],
            health_flags: { tv_high_flag: false },
            model_integrity: { tv_pct_of_ev: 68, tv_high_flag: false, revenue_data_quality_flag: "company", nwc_driver_quality_flag: false },
          },
          filings_browser: {
            retrieval_rows: [{ filing_type: "10-K", filing_date: "2026-02-01", source: "SEC", status: "loaded" }],
            coverage_summary: { statement_presence: { income_statement: true }, by_section_key: { mdna: 3 } },
            retrieval_profiles: { filings: { fallback_mode: false, selected_chunk_count: 8, skipped_sections: [] } },
          },
          comps: {
            peer_counts: { raw: 12, clean: 9 },
            historical_multiples_summary: { metrics: {} },
            audit_flags: ["Peer set cleaned from 12 to 9"],
          },
        }),
        { status: 200 },
      ),
    );

    expect(await screen.findByText("DCF Integrity")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Loading audit")).not.toBeInTheDocument());
  });
});
