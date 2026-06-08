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
  snapshot_id?: number | null;
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
  workspace?: TickerWorkspace;
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
  finance_quality?: {
    status?: string | null;
    high_count?: number | null;
    medium_count?: number | null;
    flags?: Array<{
      code?: string | null;
      severity?: string | null;
      title?: string | null;
      detail?: string | null;
      pm_check?: string | null;
    }>;
  } | null;
  summary?: Record<string, unknown> | null;
  ticker_dossier_contract_version?: string | null;
  ticker_dossier?: TickerDossierPayload;
}

export interface AssumptionsPayload {
  ticker: string;
  available?: boolean;
  current_price?: number | null;
  current_iv_base?: number | null;
  current_expected_iv?: number | null;
  ciq_lineage?: Record<string, unknown> | null;
  default_resolution?: {
    status?: string | null;
    high_count?: number | null;
    medium_count?: number | null;
    fields?: Array<Record<string, unknown>>;
  } | null;
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
  pending_changes?: Array<Record<string, unknown>>;
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

export interface ValuationPolicyPayload {
  contract_version?: string;
  policy_id?: number | null;
  created_at?: string | null;
  actor?: string | null;
  global_defaults: {
    risk_free_rate?: number | null;
    equity_risk_premium?: number | null;
  };
  sector_defaults?: Record<string, Record<string, number>>;
  source_ref?: string | null;
  notes?: string | null;
}

export interface ValuationPolicyPreviewPayload {
  current_policy?: ValuationPolicyPayload;
  proposed_policy?: ValuationPolicyPayload;
  changed_fields?: Record<string, Record<string, unknown>>;
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

export type AgenticHandoffRunStatus =
  | "blocked"
  | "failed"
  | "completed_no_items"
  | "completed_with_items"
  | "not_runnable";

export type EvidenceSourceQuality = "real" | "partial" | "placeholder";

export interface AgenticHandoffRunError extends Record<string, unknown> {
  code?: string | null;
  agent?: string | null;
  message?: string | null;
}

export interface EvidencePacketRunMetadata extends Record<string, unknown> {
  source_quality?: EvidenceSourceQuality | null;
  status?: AgenticHandoffRunStatus | null;
  reason?: string | null;
  errors?: AgenticHandoffRunError[];
  observation_count?: number | null;
  queue_item_count?: number | null;
}

export interface AgenticHandoffRunPayload {
  ticker: string;
  profile_name: string;
  status: AgenticHandoffRunStatus;
  reason?: string | null;
  evidence_packet?: EvidencePacketSummary;
  observation_count?: number;
  queue_item_count?: number;
  queue_item_ids?: number[];
  errors?: AgenticHandoffRunError[];
}

export interface AssumptionChangeProposal {
  assumption_name: string;
  proposal_mode: "delta" | "target";
  proposed_delta?: number | null;
  proposed_target_value?: number | null;
  rationale?: string | null;
  metadata?: Record<string, unknown>;
}

export interface AssumptionChangePack {
  pack_id: string;
  proposals: AssumptionChangeProposal[];
}

export interface PMDecisionQueueItem {
  item_id: number;
  ticker: string;
  profile_name: string;
  item_type: "advisory_finding" | "assumption_change_pack";
  status: "pending" | "previewed" | "approved" | "rejected" | "deferred";
  qualitative_importance?: "low" | "medium" | "high" | null;
  valuation_impact_bucket?: "low" | "medium" | "high" | null;
  title: string;
  summary?: string | null;
  evidence_anchor_ids: string[];
  evidence_packet_ids: string[];
  proposal_pack?: AssumptionChangePack | null;
  pm_edited_proposal_pack?: AssumptionChangePack | null;
  approved_proposal_pack?: AssumptionChangePack | null;
  agent_confidence?: "low" | "medium" | "high" | null;
  translator_confidence?: "low" | "medium" | "high" | null;
  pm_confidence?: "low" | "medium" | "high" | null;
  adapter_links?: Record<string, unknown>;
  decision_history?: Array<Record<string, unknown>>;
  metadata?: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface PMDecisionQueueConflictEntry {
  item_id?: number | null;
  profile_name?: string | null;
  status?: string | null;
  title?: string | null;
  summary?: string | null;
  assumption_name: string;
  proposal_mode?: string | null;
  proposed_value?: number | null;
  proposal?: AssumptionChangeProposal | null;
  qualitative_importance?: string | null;
  agent_confidence?: string | null;
  translator_confidence?: string | null;
  valuation_impact_bucket?: string | null;
  source_quality?: EvidenceSourceQuality | null;
  evidence_packet_ids?: string[];
  evidence_anchor_ids?: string[];
  last_preview_at?: string | null;
  last_preview_fingerprint?: string | null;
}

export interface PMDecisionQueueConflictGroup {
  group_id: string;
  ticker: string;
  assumption_name: string;
  profile_names: string[];
  item_ids: number[];
  proposal_count: number;
  distinct_value_count: number;
  conflict_level: "cluster" | "conflict";
  review_note: string;
  entries: PMDecisionQueueConflictEntry[];
}

export interface EvidencePacketSummary {
  packet_id?: number | null;
  ticker: string;
  profile_name: string;
  packet_kind: string;
  bundle_id?: string | null;
  generated_at: string;
  source_refs?: Array<{ source_ref_id: string; source_kind: string; source_label: string; source_locator: string }>;
  facts?: Array<{ fact_id: string; fact_name: string; value: unknown; unit?: string | null }>;
  snippets?: Array<{ snippet_id: string; source_ref_id: string; text: string }>;
  observations?: Array<{
    observation_id: string;
    observation_kind: "qualitative" | "numeric";
    observation_type: string;
    claim: string;
    evidence_anchor_ids: string[];
    text_snippet_ids: string[];
    qualitative_importance?: "low" | "medium" | "high" | null;
    agent_confidence?: "low" | "medium" | "high" | null;
    materiality?: "low" | "medium" | "high" | null;
    thesis_implication?: string | null;
    driver_implication?: string | null;
    evidence_rationale?: string | null;
    pm_question?: string | null;
    what_would_change_mind?: string | null;
    metadata?: Record<string, unknown>;
  }>;
  run_metadata?: EvidencePacketRunMetadata;
}

export interface EvidencePacketsPayload {
  ticker: string;
  evidence_packets: EvidencePacketSummary[];
}

export interface PMDecisionQueueListPayload {
  ticker: string;
  items: PMDecisionQueueItem[];
  conflict_groups?: PMDecisionQueueConflictGroup[];
  filters?: {
    status?: string | null;
    item_type?: string | null;
    qualitative_importance?: string | null;
    valuation_impact_bucket?: string | null;
  };
}

export interface PMDecisionQueuePreviewPayload {
  ticker: string;
  item_id: number;
  item?: PMDecisionQueueItem;
  preview?: {
    ticker: string;
    current_iv?: Record<string, number | null>;
    proposed_iv?: Record<string, number | null>;
    delta_pct?: Record<string, number | null>;
    resolved_values?: Record<string, Record<string, unknown>>;
    conflicts?: Array<Record<string, unknown>>;
  };
  skipped_fields?: string[];
  preview_fingerprint?: string | null;
  previewed_at?: string | null;
}

export interface PMDecisionQueueActionPayload {
  ticker: string;
  item_id: number;
  status: PMDecisionQueueItem["status"];
  reason?: string | null;
  item: PMDecisionQueueItem;
  pm_edited_proposal_pack?: AssumptionChangePack | null;
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
  analyst_prep?: AnalystPrepPack | null;
}

export interface MissingDataFlag {
  flag_id: string;
  label: string;
  severity: "low" | "medium" | "high" | string;
  reason: string;
  suggested_check?: string | null;
  source?: string | null;
}

export interface ThesisBridgeCard {
  card_id: string;
  title: string;
  claim: string;
  business_evidence_summary: string;
  model_implication: string;
  linked_assumption_fields: string[];
  evidence_anchor_ids: string[];
  numeric_fact_refs?: string[];
  source_quality: string;
  agent_confidence?: string | null;
  deterministic_confidence?: string | null;
  counter_evidence?: string | null;
  what_would_change_mind?: string | null;
}

export interface ModelDriverBridgeCard {
  assumption_name: string;
  label: string;
  current_value?: number | null;
  proposed_or_effective_value?: number | null;
  source?: string | null;
  rationale: string;
  valuation_impact?: Record<string, unknown> | null;
  evidence_anchor_ids: string[];
  pm_review_status: string;
}

export interface CompsJudgmentCard {
  title: string;
  peer_set_quality: string;
  peer_count?: number | null;
  primary_metric?: string | null;
  target_vs_peer_median?: Record<string, unknown>;
  premium_discount_argument?: string | null;
  exit_multiple_support?: string | null;
  warnings: string[];
  evidence_anchor_ids: string[];
}

export interface SegmentDriverRow {
  segment: string;
  revenue_growth?: number | null;
  margin?: number | null;
  revenue_mix?: number | null;
  source_ref?: string | null;
  quality: "real" | "partial" | "missing" | string;
}

export interface AnalystPrepPack {
  contract_version?: string;
  ticker: string;
  generated_at?: string | null;
  source_quality: string;
  thesis_cards: ThesisBridgeCard[];
  driver_cards: ModelDriverBridgeCard[];
  comps_card?: CompsJudgmentCard | null;
  missing_data: MissingDataFlag[];
  segment_driver_rows?: SegmentDriverRow[];
  evidence_packet_ids: number[];
  evidence_map?: Array<Record<string, unknown>>;
  conflict_groups?: Array<Record<string, unknown>>;
  export_metadata?: Record<string, unknown>;
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
