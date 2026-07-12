import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProfessionalModelPanel } from "@/components/professional-model/ProfessionalModelPanel";
import type {
  ProfessionalModelKnownState,
  ProfessionalModelReviewPreview,
  ProfessionalModelSheetPayload,
  ProfessionalModelSummaryPayload,
  RunPayload,
} from "@/lib/types";

const PROFESSIONAL_MODEL_PATH = "/api/tickers/MSFT/professional-model";
const WORKBOOK_HASH = "workbook-hash-v1";
const ARTIFACT_HASH = WORKBOOK_HASH;
const ACTOR = "reviewer@example.com";
const MODEL_RUN_ID = 3;
const FORECAST_PERIODS = ["FY26E", "FY27E", "FY28E", "FY29E", "FY30E"];
const HASHES = {
  source_sha256: "source-hash-v1",
  model_input_sha256: "model-input-hash-v1",
  result_sha256: "result-hash-v1",
  manifest_sha256: "manifest-hash-v1",
  workbook_sha256: WORKBOOK_HASH,
  qa_report_sha256: "qa-report-hash-v1",
  review_evidence_sha256: null,
};
const TRANSPORT_IDENTITY = {
  model_run_id: MODEL_RUN_ID,
  hashes: HASHES,
};
const REVIEW_CONTRACT = {
  compatible: true,
  regeneration_required: false,
  issues: [],
};

const WORKBOOK_SHEETS = [
  "Cover",
  "Summary",
  "Sources",
  "Assumptions",
  "Historical_Data",
  "Segment_Build",
  "Income_Statement",
  "Balance_Sheet",
  "Cash_Flow",
  "Working_Capital",
  "PP&E_Intangibles",
  "Debt_Cash_Interest",
  "Capital_Allocation",
  "Taxes",
  "Shares_EPS",
  "Consensus_Bridge",
  "WACC",
  "DCF",
  "Comps",
  "SOTP",
  "Valuation",
  "Scenarios",
  "Sensitivities",
  "Accounting_QoE",
  "PM_Review_Queue",
  "Checks",
] as const;

const KNOWN_STATES: ProfessionalModelKnownState[] = [
  "UNVERIFIED",
  "BLOCKED",
  "NEEDS_PM_REVIEW",
  "PARTIAL",
  "FULL",
];

function makeSummary(
  overrides: Partial<ProfessionalModelSummaryPayload> = {},
): ProfessionalModelSummaryPayload {
  return {
    ticker: "MSFT",
    state: "BLOCKED",
    decision_ready: false,
    decision_readiness: "Blocked by source integrity and explicit PM review gates.",
    transport_identity: TRANSPORT_IDENTITY,
    review_contract: REVIEW_CONTRACT,
    artifact: {
      filename: "MSFT_professional_model_v2.xlsx",
      artifact_hash: ARTIFACT_HASH,
      workbook_hash: WORKBOOK_HASH,
      manifest_hash: "manifest-hash-v1",
      model_input_hash: "model-input-hash-v1",
      result_hash: "result-hash-v1",
      source_hash: "source-hash-v1",
      source_run_id: 3,
      build_run_id: "build-run-v1",
      built_at: "2026-07-12T09:00:00Z",
      verified_at: "2026-07-12T09:05:00Z",
      size_bytes: 508_155,
    },
    calculation_verification: {
      status: "VERIFIED_WITH_BLOCKERS",
      verified: true,
      engine: "artifact-tool",
      message: "Formula caches were recalculated; source and PM gates remain open.",
      verified_at: "2026-07-12T09:05:00Z",
    },
    requirements: [
      {
        requirement_id: "source-integrity",
        label: "Source workbook integrity",
        status: "BLOCKED",
        owner: "Data pipeline",
        explanation: "The source workbook contains formula-reference errors.",
        remediation: "Refresh and re-ingest the exact CIQ workbook.",
        action_label: "Open Sources",
        sheet: "Sources",
      },
      {
        requirement_id: "pm-driver-review",
        label: "Base revenue-growth review",
        status: "NEEDS_PM_REVIEW",
        owner: "PM",
        explanation: "The Base revenue-growth path requires deliberate PM approval.",
        remediation: "Preview exact values, confirm the fingerprint, then decide.",
        action_label: "Review driver",
        sheet: "Assumptions",
      },
    ],
    blocker_groups: [
      {
        category: "source_integrity",
        label: "Source Integrity",
        count: 1,
        blockers: [
          {
            reason_code: "source_formula_errors:24",
            message: "The selected source run contains 24 formula-reference errors.",
            remediation: "Repair the source workbook and rebuild.",
          },
        ],
      },
      {
        category: "segments",
        label: "Segments",
        count: 1,
        blockers: [
          {
            reason_code: "source_or_pm_required:segment.revenue",
            message: "Segment revenue is not source-backed.",
          },
        ],
      },
      {
        category: "market_data",
        label: "Market Data",
        count: 1,
        blockers: [{ reason_code: "current_price_stale", message: "Current price is stale." }],
      },
      {
        category: "wacc",
        label: "WACC",
        count: 1,
        blockers: [{ reason_code: "wacc_degraded:degraded_fallback" }],
      },
      {
        category: "valuation",
        label: "Valuation",
        count: 1,
        blockers: [{ reason_code: "valuation_bridge_blocked" }],
      },
      {
        category: "pm_approvals",
        label: "PM Approvals",
        count: 1,
        blockers: [{ reason_code: "pm_approval_required:Base:revenue_growth" }],
      },
      {
        category: "calculation",
        label: "Calculation",
        count: 1,
        blockers: [{ reason_code: "recalculation_not_run" }],
      },
      {
        category: "other",
        label: "Other",
        count: 1,
        blockers: [{ reason_code: "other_contract_gate" }],
      },
    ],
    warnings: ["segments_unavailable"],
    checks: [
      {
        check_id: "balance_sheet",
        status: "PASS",
        difference_or_count: 0.000001,
        tolerance_or_expected: 0.1,
      },
      {
        check_id: "source_preflight",
        status: "BLOCKED",
        difference_or_count: 24,
        tolerance_or_expected: 0,
      },
    ],
    integrity: {
      sheet_count: 26,
      formula_count: 17_089,
      lineage_comments: 2_016,
      external_links: 0,
    },
    valuation_diagnostics: {
      "Diagnostic reverse-DCF implied growth": 16.9,
      "Diagnostic v1 Gordon growth": 194.41,
    },
    bridge: {
      "Add: cash": 32_105,
      "Component-based net claims": 13_521,
    },
    decision_useful: {
      current_price: 502.4,
      current_price_source: "CIQ",
      current_price_as_of: "2026-07-11",
      scenario_valuations: [
        { scenario: "Downside", value_per_share: 410, current_price: 502.4, upside_pct: -18.4 },
        { scenario: "Base", value_per_share: 540, current_price: 502.4, upside_pct: 7.5 },
        { scenario: "Upside", value_per_share: 650, current_price: 502.4, upside_pct: 29.4 },
      ],
      forecast_path: [
        { period: "FY26", period_type: "forecast", revenue: 310_000, ebit_margin: 0.46, eps: 15.2, fcff: 93_000 },
      ],
      what_price_implies: "The current price implies sustained double-digit cloud growth.",
      variant_estimate_gap: "Base revenue is 3% above consensus by FY28.",
      downside_mechanism: "Cloud deceleration and operating deleverage compress FCFF.",
    },
    sheets: WORKBOOK_SHEETS.map((name, index) => ({
      name,
      order: index + 1,
      status: index === 17 ? "BLOCKED" : "REVIEWED",
      finding_count: index === 17 ? 1 : 0,
      formula_count: index === 17 ? 412 : index * 10,
      cell_count: 500 + index,
    })),
    sheet_audit_findings: [
      {
        finding_id: "finding-dcf-1",
        reason_code: "dcf_input_gate",
        status: "BLOCKED",
        sheet: "DCF",
        cell: "C25",
        message: "DCF output remains blocked by an unapproved driver.",
        remediation: "Complete the Base revenue-growth review.",
      },
    ],
    reviews: [
      {
        review_id: "Base:revenue_growth",
        scenario: "Base",
        driver_key: "revenue_growth",
        driver_label: "Revenue growth",
        driver_definition: "Annual revenue growth assumption.",
        module: "revenue",
        unit: "percent",
        forecast_periods: FORECAST_PERIODS,
        method: "PM evidence review",
        source_ref: "CIQ frozen source",
        value_source: "pm_submitted_exact_path",
        artifact_current_path: [0.1, 0.11, 0.12, 0.13, 0.14],
        artifact_current_path_status: "available",
        proposed_path: [0.11, 0.12, 0.13, 0.14, 0.15],
        proposed_path_status: "proposed",
        requirement_hash: "requirement-hash-v1",
        contract_valid: true,
        contract_issues: [],
        status: "PENDING",
        stale: false,
        explanation: "Review the exact Base revenue-growth path.",
        driver_values: [0.11, 0.12, 0.13, 0.14, 0.15].map((value, index) => ({
          driver_key: "revenue_growth",
          label: "Revenue growth",
          value,
          unit: "percent",
          source_ref: "CIQ frozen source",
          period: FORECAST_PERIODS[index],
        })),
        permitted_actions: { preview: true, approve: true, reject: true },
      },
    ],
    permitted_actions: { download: true, rebuild: true, signoff: false },
    ...overrides,
  };
}

function makeSheetPayload(sheet = "Cover", page = 1): ProfessionalModelSheetPayload {
  if (page === 2) {
    return {
      ticker: "MSFT",
      sheet,
      page,
      page_size: 50,
      total_cells: 51,
      total_pages: 2,
      cells: [
        {
          address: "D51",
          period_type: "forecast",
          classification: "formula",
          formula: "=C51*(1+$B$7)",
          cached_value: 612.5,
          number_format: "$#,##0.0",
          lineage: "model:scenario:Base",
          comment: "Second preview page",
        },
      ],
      findings: [],
    };
  }

  return {
    ticker: "MSFT",
    sheet,
    page,
    page_size: 50,
    total_cells: 51,
    total_pages: 2,
    cells: [
      {
        address: "B4",
        period_type: "historical",
        classification: "source",
        cached_value: 100,
        number_format: "$#,##0.0",
        lineage: "ciq:run:3",
        comment: "Historical actual",
      },
      {
        address: "C4",
        period_type: "forecast",
        classification: "formula",
        formula: "=B4*(1+C2)",
        cached_value: 112,
        number_format: "$#,##0.0",
        lineage: { source_ref: "pmq:Base:revenue_growth" },
        comment: "PM-gated forecast",
      },
    ],
    findings:
      sheet === "DCF"
        ? [
            {
              finding_id: "finding-dcf-1",
              reason_code: "dcf_input_gate",
              status: "BLOCKED",
              sheet: "DCF",
              cell: "C25",
              message: "DCF output remains blocked by an unapproved driver.",
            },
          ]
        : [],
  };
}

type FetchCall = {
  method: string;
  path: string;
  search: string;
  body: string | null;
};

type MockApiOptions = {
  summary?: ProfessionalModelSummaryPayload | Record<string, unknown>;
  summaries?: Array<ProfessionalModelSummaryPayload | Record<string, unknown>>;
  review?: Record<string, unknown>;
  summaryStatus?: number;
  sheet?: ProfessionalModelSheetPayload;
  sheetStatus?: number;
  sheetResolver?: (sheet: string, page: number) => ProfessionalModelSheetPayload;
  preview?: ProfessionalModelReviewPreview | Record<string, unknown>;
  previewStatus?: number;
  approveStatus?: number;
  rejectStatus?: number;
  signoffStatus?: number;
  rebuild?: RunPayload;
  rebuildStatus?: number;
  runs?: RunPayload[];
};

type MockApi = {
  calls: FetchCall[];
  readonly summaryCalls: number;
};

let unexpectedRequests: string[] = [];
const queryClients: QueryClient[] = [];

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function installStrictFetch(options: MockApiOptions = {}): MockApi {
  const calls: FetchCall[] = [];
  let summaryCalls = 0;
  let runCalls = 0;

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl = input instanceof Request ? input.url : String(input);
      const url = new URL(rawUrl, "http://localhost");
      const method = (init?.method ?? "GET").toUpperCase();
      const body = typeof init?.body === "string" ? init.body : null;
      calls.push({ method, path: url.pathname, search: url.search, body });

      if (method === "GET" && url.pathname === PROFESSIONAL_MODEL_PATH) {
        const sequence = options.summaries;
        const payload = sequence?.[Math.min(summaryCalls, sequence.length - 1)] ?? options.summary ?? makeSummary();
        summaryCalls += 1;
        if ((options.summaryStatus ?? 200) >= 400) {
          return jsonResponse({ detail: "Professional model summary exploded." }, options.summaryStatus);
        }
        return jsonResponse(payload);
      }

      if (method === "GET" && url.pathname === `${PROFESSIONAL_MODEL_PATH}/review`) {
        return jsonResponse(options.review ?? { requirements: [], permitted_actions: {} });
      }

      const sheetPrefix = `${PROFESSIONAL_MODEL_PATH}/sheets/`;
      if (method === "GET" && url.pathname.startsWith(sheetPrefix)) {
        if ((options.sheetStatus ?? 200) >= 400) {
          return jsonResponse({ detail: "Selected sheet exploded." }, options.sheetStatus);
        }
        const sheet = decodeURIComponent(url.pathname.slice(sheetPrefix.length));
        const startRow = Number(url.searchParams.get("start_row") ?? "1");
        const rowLimit = Number(url.searchParams.get("row_limit") ?? "50");
        const page = Math.floor((startRow - 1) / rowLimit) + 1;
        return jsonResponse(
          options.sheetResolver?.(sheet, page) ?? options.sheet ?? makeSheetPayload(sheet, page),
        );
      }

      if (
        method === "POST" &&
        url.pathname === `${PROFESSIONAL_MODEL_PATH}/review/preview`
      ) {
        if ((options.previewStatus ?? 200) >= 400) {
          return jsonResponse({ detail: "Preview is stale." }, options.previewStatus);
        }
        return jsonResponse(
          options.preview ?? {
            ticker: "MSFT",
            review_id: "Base:revenue_growth",
            scenario: "Base",
            fingerprint: "preview-fingerprint-v1",
            stale: false,
            status: "PREVIEWED",
            preview_id: 41,
            artifact_hash: ARTIFACT_HASH,
            message: "Exact driver values are bound to the current workbook hash.",
            driver_values: makeSummary().reviews?.[0].driver_values ?? [],
            permitted_actions: { preview: true, approve: true, reject: true },
          },
        );
      }

      if (
        method === "POST" &&
        url.pathname === `${PROFESSIONAL_MODEL_PATH}/review/approve`
      ) {
        if ((options.approveStatus ?? 200) >= 400) {
          return jsonResponse({ detail: "Preview fingerprint is stale." }, options.approveStatus);
        }
        return jsonResponse({
          ticker: "MSFT",
          status: "APPROVED",
          message: "Review approved.",
          review: {
            review_id: "Base:revenue_growth",
            scenario: "Base",
            status: "APPROVED",
            stale: false,
          },
        });
      }

      if (
        method === "POST" &&
        url.pathname === `${PROFESSIONAL_MODEL_PATH}/review/reject`
      ) {
        if ((options.rejectStatus ?? 200) >= 400) {
          return jsonResponse({ detail: "Review rejection failed." }, options.rejectStatus);
        }
        return jsonResponse({ ticker: "MSFT", status: "REJECTED", message: "Review rejected." });
      }

      if (method === "POST" && url.pathname === `${PROFESSIONAL_MODEL_PATH}/signoff`) {
        if ((options.signoffStatus ?? 200) >= 400) {
          return jsonResponse({ detail: "Sign-off failed." }, options.signoffStatus);
        }
        return jsonResponse({ ticker: "MSFT", status: "SIGNED_OFF", decision_ready: true });
      }

      if (method === "POST" && url.pathname === `${PROFESSIONAL_MODEL_PATH}/rebuild`) {
        if ((options.rebuildStatus ?? 202) >= 400) {
          return jsonResponse({ detail: "Rebuild could not be queued." }, options.rebuildStatus);
        }
        return jsonResponse(options.rebuild ?? { run_id: "rebuild-run-1", status: "queued" }, 202);
      }

      if (method === "GET" && url.pathname === "/api/runs/rebuild-run-1") {
        const statuses = options.runs ?? [
          { run_id: "rebuild-run-1", status: "running", progress: 0.5 },
          {
            run_id: "rebuild-run-1",
            status: "completed",
            progress: 1,
            result: { artifact_hash: "artifact-hash-v2", workbook_hash: "workbook-hash-v2" },
          },
        ];
        const payload = statuses[Math.min(runCalls, statuses.length - 1)];
        runCalls += 1;
        return jsonResponse(payload);
      }

      const unexpected = `${method} ${url.pathname}${url.search}`;
      unexpectedRequests.push(unexpected);
      throw new Error(`Unexpected fetch request: ${unexpected}`);
    }) as unknown as typeof fetch,
  );

  const api: MockApi = {
    calls,
    get summaryCalls() {
      return summaryCalls;
    },
  };
  return api;
}

function renderPanel(options: MockApiOptions = {}) {
  const api = installStrictFetch(options);
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  queryClients.push(queryClient);
  const view = render(
    <QueryClientProvider client={queryClient}>
      <ProfessionalModelPanel ticker="MSFT" />
    </QueryClientProvider>,
  );
  return { ...view, api, queryClient };
}

beforeEach(() => {
  unexpectedRequests = [];
});

afterEach(() => {
  cleanup();
  for (const queryClient of queryClients.splice(0)) {
    queryClient.clear();
  }
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  expect(unexpectedRequests).toEqual([]);
});

describe("ProfessionalModelPanel", () => {
  it.each(KNOWN_STATES)("renders backend readiness state %s without reinterpretation", async (state) => {
    renderPanel({
      summary: makeSummary({
        state,
        decision_ready: state === "FULL",
        decision_readiness: state === "FULL" ? "Backend marks this artifact decision-ready." : `Backend state is ${state}.`,
      }),
    });

    expect(await screen.findByTestId("professional-model-state")).toHaveAttribute("data-value", state);
    expect(screen.getByTestId("professional-model-decision-ready")).toHaveAttribute("data-value", String(state === "FULL"));
    expect(await screen.findByText(state === "FULL" ? "Backend marks this artifact decision-ready." : `Backend state is ${state}.`)).toBeInTheDocument();
  });

  it.each([
    ["missing", undefined],
    ["unknown", "PASS"],
  ])("fails closed for a %s readiness state", async (_label, state) => {
    renderPanel({ summary: makeSummary({ state }) });

    const contractAlert = await screen.findByRole("alert");
    expect(contractAlert).toHaveTextContent(/readiness state|contract/i);
    expect(screen.queryByText("FULL", { exact: true })).not.toBeInTheDocument();

    for (const name of [/download/i, /rebuild/i, /sign.?off/i]) {
      const button = screen.queryByRole("button", { name });
      if (button) {
        expect(button).toBeDisabled();
      }
    }
  });

  it("normalizes raw live summary and review payloads into the workbench contract", async () => {
    const { api } = renderPanel({
      summary: {
        ticker: "MSFT",
        normalized_state: "NEEDS_PM_REVIEW",
        decision_readiness: false,
        model_run_id: 3,
        hashes: {
          workbook_sha256: WORKBOOK_HASH,
          source_sha256: "source-hash-live",
          manifest_sha256: "manifest-hash-live",
          model_input_sha256: "model-input-hash-live",
          result_sha256: "result-hash-live",
        },
        artifact_identity: {
          workbook_filename: "MSFT_professional_model_live.xlsx",
          workbook_bytes: 508_155,
        },
        calculation_verification: {
          status: "VERIFIED",
          verified: true,
          cache_engine: "LibreOffice",
          recalculation_state: { message: "Workbook caches were recalculated." },
        },
        full_state_requirements: [
          {
            requirement: "pm_driver_review",
            status: "NEEDS_PM_REVIEW",
            owner: "PM",
            evidence: { required: 1, approved: 0, open_keys: ["Base:revenue_growth"] },
            remediation: "Preview and decide the exact five-year path.",
          },
        ],
        blockers: {
          counts: { pm_approvals: 1 },
          groups: { pm_approvals: ["pm_approval_required:Base:revenue_growth"] },
        },
        warnings: ["pm_review_open"],
        checks: [{ check_id: "source_preflight", status: "PASS" }],
        integrity: { sheet_count: 26 },
        sheets: WORKBOOK_SHEETS.map((name, index) => ({
          name,
          index,
          visibility: "visible",
          formula_count: index * 10,
          nonempty_cell_count: 500 + index,
        })),
        sheet_audit: { findings: [] },
        permitted_actions: { download: true, rebuild: true, signoff: false },
      },
      review: {
        requirements: [
          {
            approval_key: "Base:revenue_growth",
            scenario: "Base",
            driver: "revenue_growth",
            status: "pending",
            reviewed_values: [0.11, 0.12, 0.13, 0.14, 0.15],
            stale_reasons: [],
          },
        ],
        permitted_actions: {
          review_preview: true,
          review_approve: true,
          review_reject: true,
        },
      },
    });

    expect(await screen.findByTestId("professional-model-state")).toHaveAttribute(
      "data-value",
      "NEEDS_PM_REVIEW",
    );
    expect(screen.getByTestId("professional-model-source-run-id")).toHaveAttribute("data-value", "3");
    expect(screen.getByTestId("professional-model-workbook-hash")).toHaveAttribute(
      "data-value",
      WORKBOOK_HASH,
    );
    expect(screen.getByTestId("professional-model-sheet-count")).toHaveAttribute("data-value", "26");
    expect(
      await screen.findByRole("button", {
        name: "Preview exact driver values for Base: Revenue Growth",
      }),
    ).toBeEnabled();
    expect(
      screen.getAllByRole("spinbutton", {
        name: /Base: Revenue Growth Year \d reviewed value/,
      }),
    ).toHaveLength(5);
    expect(
      api.calls.some(
        (call) => call.method === "GET" && call.path === `${PROFESSIONAL_MODEL_PATH}/review`,
      ),
    ).toBe(true);
  });

  it("preserves all 26 sheets, searches, selects a preview, and paginates", async () => {
    const { api } = renderPanel();

    expect(await screen.findByTestId("professional-model-sheet-count")).toHaveAttribute("data-value", "26");
    const picker = screen.getByRole("complementary", { name: "Workbook sheets" });
    const initialItems = within(picker).getAllByRole("listitem");
    expect(initialItems).toHaveLength(26);
    expect(initialItems[0]).toHaveTextContent("Cover");
    expect(initialItems[25]).toHaveTextContent("Checks");

    fireEvent.change(within(picker).getByRole("searchbox", { name: "Search sheets" }), {
      target: { value: "DCF" },
    });
    const filteredItems = within(picker).getAllByRole("listitem");
    expect(filteredItems).toHaveLength(1);
    expect(filteredItems[0]).toHaveTextContent("DCF");
    fireEvent.click(within(filteredItems[0]).getByRole("button"));

    await waitFor(() =>
      expect(screen.getByTestId("professional-model-selected-sheet")).toHaveAttribute("data-value", "DCF"),
    );
    const preview = await screen.findByRole("region", { name: "DCF cell preview" });
    expect(within(preview).getByText("=B4*(1+C2)")).toBeInTheDocument();
    expect(within(preview).getByText("112")).toBeInTheDocument();
    expect(within(preview).getAllByText("$#,##0.0").length).toBeGreaterThan(0);
    expect(within(preview).getByText("Historical")).toBeInTheDocument();
    expect(within(preview).getByText("Forecast")).toBeInTheDocument();
    expect(screen.getByText("dcf_input_gate")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("=C51*(1+$B$7)")).toBeInTheDocument();
    await waitFor(() => {
      expect(
        api.calls.some(
          (call) =>
            call.method === "GET" &&
            call.path === `${PROFESSIONAL_MODEL_PATH}/sheets/DCF` &&
            call.search === "?start_row=51&start_column=1&row_limit=50&column_limit=20",
        ),
      ).toBe(true);
    });
  });

  it("keeps blocker reason codes collapsed until their backend group is expanded", async () => {
    renderPanel();

    expect(await screen.findByRole("heading", { name: "Blocker Workbench" })).toBeInTheDocument();
    expect(screen.queryByText("source_formula_errors:24")).not.toBeInTheDocument();
    const sourceButton = screen.getByRole("button", { name: /Source Integrity/i });
    expect(sourceButton).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(sourceButton);
    expect(sourceButton).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByText("source_formula_errors:24")).toBeVisible();
    expect(screen.getByText(/24 formula-reference errors/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /PM Approvals/i })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: /Calculation/i })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getAllByRole("button", { expanded: false }).length).toBeGreaterThanOrEqual(7);
  });

  it("requires an artifact-bound preview, fingerprint, and deliberate confirmation before approval", async () => {
    const { api } = renderPanel();

    expect(await screen.findByRole("heading", { name: "PM Approval Workflow" })).toBeInTheDocument();
    const approveButton = screen.getByRole("button", { name: "Approve Base" });
    expect(approveButton).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Preview exact driver values for Base" }));

    const previewRegion = await screen.findByRole("region", { name: "Base review preview" });
    expect(within(previewRegion).getByText("preview-fingerprint-v1")).toBeInTheDocument();
    expect(screen.getAllByRole("spinbutton", { name: /Base Year \d reviewed value/ })).toHaveLength(5);
    expect(within(previewRegion).getByText("Year 2")).toBeInTheDocument();
    expect(within(previewRegion).getByText("0.12")).toBeInTheDocument();
    await waitFor(() => {
      const previewCall = api.calls.find((call) => call.path.endsWith("/review/preview"));
      expect(previewCall?.body).toBe(
        JSON.stringify({
          approval_key: "Base:revenue_growth",
          reviewed_values: [0.11, 0.12, 0.13, 0.14, 0.15],
          actor: ACTOR,
        }),
      );
    });

    const confirmation = screen.getByRole("checkbox", { name: /confirm/i });
    expect(approveButton).toBeDisabled();
    fireEvent.click(confirmation);
    expect(approveButton).toBeEnabled();
    fireEvent.click(approveButton);

    await waitFor(() => {
      const approveCall = api.calls.find((call) => call.path.endsWith("/review/approve"));
      expect(approveCall?.body).toBe(
        JSON.stringify({
          preview_id: 41,
          reviewed_value_fingerprint: "preview-fingerprint-v1",
          actor: ACTOR,
          rationale: "Approved after exact-value preview and deliberate confirmation.",
        }),
      );
    });
  });

  it("shows stale approval state and keeps approval disabled", async () => {
    const summary = makeSummary();
    summary.reviews = [
      {
        ...summary.reviews![0],
        status: "STALE",
        stale: true,
        fingerprint: "obsolete-fingerprint",
        permitted_actions: { preview: true, approve: false, reject: true },
      },
    ];
    renderPanel({
      summary,
      preview: {
        ticker: "MSFT",
        review_id: "Base:revenue_growth",
        scenario: "Base",
        fingerprint: "obsolete-fingerprint",
        preview_id: 42,
        artifact_hash: ARTIFACT_HASH,
        stale: true,
        status: "STALE",
        message: "The approval preview is stale.",
        driver_values: summary.reviews![0].driver_values ?? [],
        permitted_actions: { preview: true, approve: false, reject: true },
      },
    });

    expect((await screen.findAllByText(/stale/i)).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Preview exact driver values for Base" }));
    expect(await screen.findByText("Stale approval preview")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /confirm/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Approve Base" })).toBeDisabled();
  });

  it("discards a preview whose artifact hash does not match the open workbook", async () => {
    renderPanel({
      preview: {
        ticker: "MSFT",
        review_id: "Base:revenue_growth",
        scenario: "Base",
        preview_id: 99,
        fingerprint: "preview-fingerprint-other-artifact",
        artifact_hash: "different-workbook-hash",
        stale: false,
        status: "PREVIEWED",
        message: "This response belongs to another workbook.",
        driver_values: makeSummary().reviews?.[0].driver_values ?? [],
        permitted_actions: { preview: true, approve: true, reject: true },
      },
    });

    expect(await screen.findByRole("heading", { name: "PM Approval Workflow" })).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Preview exact driver values for Base" }),
    );

    expect(
      await screen.findByText("Discarded a stale preview because the workbook artifact changed."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Base review preview" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve Base" })).toBeDisabled();
  });

  it("obeys backend signoff permission even when visible requirements pass", async () => {
    const summary = makeSummary({
      state: "FULL",
      decision_ready: true,
      requirements: makeSummary().requirements?.map((requirement) => ({ ...requirement, status: "PASS" })),
      permitted_actions: { download: true, rebuild: true, signoff: false },
    });
    renderPanel({ summary });

    expect(await screen.findByRole("button", { name: "Final PM Sign-Off" })).toBeDisabled();
  });

  it("sends exact live-contract bodies for successful rejection and final sign-off", async () => {
    const summary = makeSummary({
      state: "FULL",
      decision_ready: true,
      requirements: makeSummary().requirements?.map((requirement) => ({
        ...requirement,
        status: "PASS",
      })),
      permitted_actions: { download: true, rebuild: true, signoff: true },
    });
    const { api } = renderPanel({ summary });

    expect(await screen.findByRole("heading", { name: "PM Approval Workflow" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Rejection reason" }), {
      target: { value: "The five-year growth path is not supportable." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Reject Base" }));

    await waitFor(() => {
      const rejectCall = api.calls.find((call) => call.path.endsWith("/review/reject"));
      expect(rejectCall?.body).toBe(
        JSON.stringify({
          approval_key: "Base:revenue_growth",
          actor: ACTOR,
          rationale: "The five-year growth path is not supportable.",
        }),
      );
    });
    expect(await screen.findByText("Review rejected.")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox", { name: "Final sign-off rationale" }), {
      target: { value: "All gates are complete for this exact workbook." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Final PM Sign-Off" }));

    await waitFor(() => {
      const signoffCall = api.calls.find((call) => call.path.endsWith("/signoff"));
      expect(signoffCall?.body).toBe(
        JSON.stringify({
          workbook_sha256: WORKBOOK_HASH,
          actor: ACTOR,
          rationale: "All gates are complete for this exact workbook.",
        }),
      );
    });
  });

  it("polls a rebuild to completion and refetches the new artifact identity", async () => {
    const rebuilt = makeSummary({
      artifact: {
        ...(makeSummary().artifact ?? {}),
        artifact_hash: "artifact-hash-v2",
        workbook_hash: "workbook-hash-v2",
        filename: "MSFT_professional_model_v2_rebuilt.xlsx",
      },
    });
    const { api } = renderPanel({ summaries: [makeSummary(), rebuilt] });

    fireEvent.click(await screen.findByRole("button", { name: /rebuild/i }));
    await waitFor(
      () => {
        expect(api.calls.filter((call) => call.path === "/api/runs/rebuild-run-1").length).toBeGreaterThanOrEqual(2);
      },
      { timeout: 5_000 },
    );
    await waitFor(() => expect(api.summaryCalls).toBeGreaterThanOrEqual(2), { timeout: 5_000 });
    expect(await screen.findByTestId("professional-model-workbook-hash")).toHaveAttribute(
      "data-value",
      "workbook-hash-v2",
    );

    const rebuildCall = api.calls.find((call) => call.path.endsWith("/professional-model/rebuild"));
    expect(rebuildCall?.body).toBe(
      JSON.stringify({
        model_run_id: 3,
        actor: ACTOR,
        rationale: "Requested from the Professional Model workbench.",
      }),
    );
    expect(api.calls.some((call) => call.path.endsWith("/approve"))).toBe(false);
  });

  it("downloads the exact dedicated backend artifact URL", async () => {
    renderPanel();

    expect((await screen.findAllByText("MSFT_professional_model_v2.xlsx")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(WORKBOOK_HASH).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("link", { name: "Download exact workbook" })).toHaveAttribute(
      "href",
      `${PROFESSIONAL_MODEL_PATH}/download`,
    );
  });

  it("renders a summary API error without requesting a sheet", async () => {
    const { api } = renderPanel({ summaryStatus: 500 });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/summary exploded|could not be loaded/i);
    expect(api.calls.some((call) => call.path.includes("/sheets/"))).toBe(false);
  });

  it("keeps a sheet API error scoped to the selected-sheet workbench", async () => {
    renderPanel({ sheetStatus: 500 });

    const alert = await screen.findByText("Sheet preview could not be loaded.");
    expect(alert.closest("[role='alert']")).toHaveTextContent(/Selected sheet exploded/i);
    expect(screen.getByTestId("professional-model-sheet-count")).toHaveAttribute("data-value", "26");
  });

  it("renders honest empty summary and selected-sheet states", async () => {
    const emptySummary = makeSummary({
      state: "UNVERIFIED",
      decision_ready: false,
      requirements: [],
      blocker_groups: [],
      blockers: [],
      sheets: [],
      sheet_audit_findings: [],
      reviews: [],
      permitted_actions: { download: false, rebuild: false, signoff: false },
    });
    renderPanel({ summary: emptySummary });

    expect(await screen.findByText("No workbook sheets supplied by the backend.")).toBeInTheDocument();
    expect(screen.getByText(/No requirements|requirements.*not supplied/i)).toBeInTheDocument();
    expect(screen.getByText("The backend returned no active blocker groups.")).toBeInTheDocument();

    cleanup();
    queryClients.splice(0).forEach((client) => client.clear());

    renderPanel({
      summary: makeSummary({ sheets: [makeSummary().sheets![0]] }),
      sheet: { ticker: "MSFT", sheet: "Cover", page: 1, page_size: 50, total_cells: 0, total_pages: 1, cells: [], findings: [] },
    });
    expect(await screen.findByText("No cells returned for Cover")).toBeInTheDocument();
  });
});
