export interface WatchlistRow {
  ticker: string;
  company_name: string | null;
  price: number | null;
  iv_bear: number | null;
  iv_base: number | null;
  iv_bull: number | null;
  expected_iv: number | null;
  analyst_target: number | null;
  expected_upside_pct: number | null;
  upside_base_pct: number | null;
  latest_action: string | null;
  latest_conviction: string | null;
  latest_snapshot_date: string | null;
  model_applicability_status?: string | null;
}

export interface WatchlistPayload {
  rows: WatchlistRow[];
  shortlist?: WatchlistRow[];
  saved_row_count?: number;
  universe_row_count?: number;
  shortlist_size?: number;
  last_updated?: string | null;
  default_focus_ticker?: string | null;
}

export interface TickerWorkspace {
  ticker: string;
  company_name: string;
  sector: string | null;
  action: string | null;
  conviction: string | null;
  current_price: number | null;
  analyst_target?: number | null;
  bear_iv?: number | null;
  base_iv: number | null;
  bull_iv?: number | null;
  weighted_iv?: number | null;
  upside_pct_base: number | null;
  latest_snapshot_date: string | null;
  snapshot_available: boolean;
  last_snapshot_id?: number | null;
  latest_action?: string | null;
  latest_conviction?: string | null;
  ticker_dossier_contract_version?: string | null;
  ticker_dossier?: TickerDossierPayload;
}

export interface OverviewPayload {
  ticker: string;
  company_name: string;
  one_liner?: string | null;
  variant_thesis_prompt?: string | null;
  market_pulse?: string | null;
  valuation_pulse?: string | null;
  thesis_changes?: string[];
  next_catalyst?: string | null;
  ticker_dossier_contract_version?: string | null;
  ticker_dossier?: TickerDossierPayload;
}

export interface ArchivedSnapshotPayload {
  id: number;
  ticker: string;
  created_at: string;
  company_name?: string | null;
  sector?: string | null;
  action?: string | null;
  conviction?: string | null;
  current_price?: number | null;
  base_iv?: number | null;
  memo?: {
    company_name?: string | null;
    sector?: string | null;
    action?: string | null;
    conviction?: string | null;
    one_liner?: string | null;
    variant_thesis_prompt?: string | null;
    valuation?: {
      current_price?: number | null;
      base?: number | null;
      bear?: number | null;
      bull?: number | null;
      upside_pct_base?: number | null;
    } | null;
  } | null;
  ticker_dossier?: TickerDossierPayload;
}

export interface TickerDossierPayload {
  contract_name: "TickerDossier";
  contract_version: string;
  ticker: string;
  as_of_date: string;
  display_name: string;
  currency: string;
  latest_snapshot: {
    company_identity: {
      ticker: string;
      display_name: string;
      sector?: string | null;
      industry?: string | null;
      exchange?: string | null;
    };
    market_snapshot: {
      as_of_date: string;
      price?: number | null;
      market_cap?: number | null;
      enterprise_value?: number | null;
      beta?: number | null;
      analyst_target?: number | null;
      analyst_recommendation?: string | null;
      num_analysts?: number | null;
    };
    valuation_snapshot: {
      bear_iv?: number | null;
      base_iv?: number | null;
      bull_iv?: number | null;
      expected_iv?: number | null;
      current_price?: number | null;
      upside_pct?: number | null;
      scenario_probabilities?: Record<string, number | null>;
    };
    historical_series?: Record<string, Array<Record<string, unknown>>>;
    qoe_snapshot?: Record<string, unknown>;
    comps_snapshot?: Record<string, unknown>;
    source_lineage?: Record<string, unknown>;
  };
  loaded_backend_state: Record<string, unknown>;
  source_lineage: Record<string, unknown>;
  export_metadata: {
    source_mode: string;
    generated_at?: string | null;
    schema_version?: string | null;
    snapshot_id?: number | null;
    source_label?: string | null;
    template_strategy?: string | null;
  };
  optional_overlays: Record<string, unknown>;
}

export interface ValuationSummaryPayload {
  ticker: string;
  current_price?: number | null;
  base_iv?: number | null;
  bear_iv?: number | null;
  bull_iv?: number | null;
  weighted_iv?: number | null;
  upside_pct_base?: number | null;
  analyst_target?: number | null;
  conviction?: string | null;
  memo_date?: string | null;
  why_it_matters?: string | null;
  readiness?: Record<string, unknown> | null;
  summary?: Record<string, unknown> | null;
}

export interface AssumptionsPayload {
  ticker: string;
  available?: boolean;
  current_price?: number | null;
  current_iv_base?: number | null;
  current_expected_iv?: number | null;
  fields: Array<{
    field: string;
    label: string;
    unit: string;
    baseline_value: number | null;
    effective_value: number | null;
    agent_value: number | null;
    effective_source?: string | null;
    baseline_source?: string | null;
    agent_name?: string | null;
    agent_confidence?: string | null;
    agent_status?: string | null;
    initial_mode?: string | null;
  }>;
  audit_rows?: Array<Record<string, unknown>>;
}

export interface AssumptionsPreviewPayload {
  ticker: string;
  current_iv?: Record<string, number | null>;
  proposed_iv?: Record<string, number | null>;
  current_expected_iv?: number | null;
  proposed_expected_iv?: number | null;
  delta_pct?: Record<string, number | null>;
  resolved_values?: Record<string, Record<string, unknown>>;
}

export interface WaccPayload {
  ticker: string;
  available?: boolean;
  current_wacc?: number | null;
  proposed_wacc?: number | null;
  method?: string | null;
  current_selection?: {
    mode?: string | null;
    selected_method?: string | null;
    weights?: Record<string, number>;
  };
  effective_preview?: Record<string, unknown>;
  methods?: Array<Record<string, unknown>>;
  audit_rows?: Array<Record<string, unknown>>;
}

export interface WaccPreviewPayload {
  ticker: string;
  selection?: Record<string, unknown>;
  current_wacc?: number | null;
  effective_wacc?: number | null;
  current_iv?: Record<string, number | null>;
  proposed_iv?: Record<string, number | null>;
  current_expected_iv?: number | null;
  proposed_expected_iv?: number | null;
  method_result?: Record<string, unknown>;
}

export interface DcfFcffPoint {
  year: number | string;
  fcff_mm?: number | null;
  nopat_mm?: number | null;
}

export interface HistoricalMultiplePoint {
  date: string;
  price?: number | null;
  multiple?: number | null;
}

export interface ValuationDcfPayload extends Record<string, unknown> {
  ticker: string;
  scenario_summary?: Array<Record<string, unknown>>;
  forecast_bridge?: Array<Record<string, unknown>>;
  driver_rows?: Array<Record<string, unknown>>;
  health_flags?: Record<string, unknown> | null;
  terminal_bridge?: Record<string, unknown> | null;
  ev_bridge?: Record<string, unknown> | null;
  chart_series?: {
    scenario_iv?: Array<Record<string, unknown>>;
    fcff_curve?: DcfFcffPoint[];
    risk_overlay?: Array<Record<string, unknown>>;
  } | null;
  sensitivity?: Record<string, unknown> | null;
  risk_impact?: Record<string, unknown> | null;
  model_integrity?: Record<string, unknown> | null;
}

export interface ValuationCompsPayload extends Record<string, unknown> {
  ticker: string;
  peer_counts?: Record<string, number | null>;
  selected_metric_default?: string | null;
  metric_options?: Array<Record<string, unknown>>;
  valuation_range?: Record<string, unknown> | null;
  valuation_range_by_metric?: Record<string, unknown> | null;
  target?: Record<string, unknown> | null;
  football_field?: Record<string, unknown> | null;
  target_vs_peers?: Record<string, unknown> | null;
  peers?: Array<Record<string, unknown>>;
  historical_multiples_summary?: {
    available?: boolean;
    metrics?: Record<
      string,
      {
        summary?: Record<string, unknown> | null;
        series?: HistoricalMultiplePoint[];
      }
    >;
    audit_flags?: string[];
  } | null;
  audit_flags?: string[];
  notes?: string | null;
}

export interface RecommendationsPayload {
  ticker: string;
  available?: boolean;
  generated_at?: string | null;
  current_iv_base?: number | null;
  recommendations: Array<Record<string, unknown>>;
}

export interface RecommendationsPreviewPayload {
  ticker: string;
  current_iv?: Record<string, number | null>;
  proposed_iv?: Record<string, number | null>;
  delta_pct?: Record<string, number | null>;
}

export interface MarketPayload {
  ticker: string;
  available?: boolean;
  headline_count?: number;
  analyst_snapshot?: Record<string, unknown> | null;
  historical_brief?: {
    summary?: string | null;
    period_start?: string | null;
    period_end?: string | null;
    event_timeline?: Array<Record<string, unknown>>;
  } | null;
  quarterly_headlines?: Array<Record<string, unknown>>;
  headlines?: Array<Record<string, unknown>>;
  sentiment_summary?: Record<string, unknown> | null;
  revisions?: Record<string, unknown> | null;
  macro?: {
    regime?: Record<string, unknown> | null;
    scenario_weights?: Record<string, unknown> | null;
    snapshot?: Record<string, unknown> | null;
    yield_curve?: Record<string, unknown> | null;
  } | null;
  factor_exposure?: Record<string, unknown> | null;
  audit_flags?: string[];
}

export interface ResearchPayload {
  ticker: string;
  tracker?: Record<string, unknown> | null;
  notebook?: Record<string, unknown> | null;
  publishable_memo_preview?: string | null;
}

export interface AuditPayload {
  ticker: string;
  dcf_audit?: Record<string, unknown> | null;
  filings_browser?: Record<string, unknown> | null;
  comps?: Record<string, unknown> | null;
}

export type ExportFormat = "html" | "xlsx";
export type TickerExportSourceMode = "latest_snapshot" | "loaded_backend_state";
export type WatchlistExportSourceMode = "saved_watchlist";

export interface ExportArtifact {
  artifact_key: string;
  artifact_role?: string | null;
  title?: string | null;
  path?: string | null;
  mime_type?: string | null;
  size_bytes?: number | null;
  is_primary?: boolean;
  metadata?: Record<string, unknown>;
}

export interface SavedExport {
  export_id: string;
  scope: string;
  ticker?: string | null;
  status: string;
  export_format: ExportFormat;
  source_mode: string;
  template_strategy?: string | null;
  title?: string | null;
  bundle_dir?: string | null;
  primary_artifact_key?: string | null;
  created_by?: string | null;
  snapshot_id?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
  metadata?: Record<string, unknown>;
  artifacts?: ExportArtifact[];
}

export interface ExportListPayload {
  exports: SavedExport[];
}

export interface TickerExportRequest {
  format: ExportFormat;
  source_mode: TickerExportSourceMode;
  template_strategy?: string | null;
}

export interface WatchlistExportRequest {
  format: ExportFormat;
  source_mode: WatchlistExportSourceMode;
  shortlist_size?: number;
}

export interface RunPayload {
  run_id: string;
  status?: string;
  progress?: number;
  message?: string | null;
  result?: unknown;
  error?: string | null;
}
