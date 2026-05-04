import type {
  ArchivedSnapshotPayload,
  OverviewPayload,
  TickerDossierPayload,
  TickerWorkspace,
  ValuationSummaryPayload,
} from "@/lib/types";

function percentPoints(value: number | null | undefined): number | null {
  if (value == null) {
    return null;
  }
  return value >= -1 && value <= 1 ? value * 100 : value;
}

function valuationPulse(dossier: TickerDossierPayload): string | null {
  const valuation = dossier.latest_snapshot.valuation_snapshot;
  const market = dossier.latest_snapshot.market_snapshot;
  const currentPrice = market.price ?? valuation.current_price ?? null;
  if (valuation.base_iv == null || currentPrice == null) {
    return null;
  }
  return `Base IV $${valuation.base_iv.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} versus current price $${currentPrice.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}.`;
}

export function normalizeTickerWorkspace(payload: TickerWorkspace): TickerWorkspace {
  const dossier = payload.ticker_dossier;
  if (!dossier) {
    return payload;
  }
  const latest = dossier.latest_snapshot;
  const identity = latest.company_identity;
  const market = latest.market_snapshot;
  const valuation = latest.valuation_snapshot;
  const snapshotId = dossier.export_metadata.snapshot_id ?? payload.last_snapshot_id ?? payload.snapshot_id ?? null;

  return {
    ...payload,
    ticker: dossier.ticker,
    company_name: dossier.display_name ?? identity.display_name,
    sector: identity.sector ?? null,
    current_price: market.price ?? valuation.current_price ?? null,
    analyst_target: market.analyst_target ?? null,
    bear_iv: valuation.bear_iv ?? null,
    base_iv: valuation.base_iv ?? null,
    bull_iv: valuation.bull_iv ?? null,
    weighted_iv: valuation.expected_iv ?? null,
    upside_pct_base: valuation.upside_pct ?? null,
    latest_snapshot_date: dossier.as_of_date,
    snapshot_available: snapshotId != null,
    last_snapshot_id: snapshotId,
    snapshot_id: snapshotId,
    ticker_dossier_contract_version: dossier.contract_version,
    ticker_dossier: dossier,
  };
}

export function normalizeOverviewPayload(payload: OverviewPayload): OverviewPayload {
  const dossier = payload.ticker_dossier;
  if (!dossier) {
    return payload;
  }
  const identity = dossier.latest_snapshot.company_identity;
  const canonicalPulse = valuationPulse(dossier);
  return {
    ...payload,
    ticker: dossier.ticker,
    company_name: dossier.display_name ?? identity.display_name,
    valuation_pulse: canonicalPulse ?? payload.valuation_pulse ?? null,
    workspace: payload.workspace ? normalizeTickerWorkspace(payload.workspace) : payload.workspace,
    ticker_dossier_contract_version: dossier.contract_version,
    ticker_dossier: dossier,
  };
}

export function normalizeValuationSummaryPayload(payload: ValuationSummaryPayload): ValuationSummaryPayload {
  const dossier = payload.ticker_dossier;
  if (!dossier) {
    return payload;
  }
  const market = dossier.latest_snapshot.market_snapshot;
  const valuation = dossier.latest_snapshot.valuation_snapshot;
  const currentPrice = market.price ?? valuation.current_price ?? null;
  return {
    ...payload,
    ticker: dossier.ticker,
    current_price: currentPrice,
    base_iv: valuation.base_iv ?? null,
    bear_iv: valuation.bear_iv ?? null,
    bull_iv: valuation.bull_iv ?? null,
    weighted_iv: valuation.expected_iv ?? null,
    upside_pct_base: percentPoints(valuation.upside_pct),
    analyst_target: market.analyst_target ?? null,
    memo_date: dossier.as_of_date,
    why_it_matters: valuationPulse(dossier) ?? payload.why_it_matters ?? null,
    ticker_dossier_contract_version: dossier.contract_version,
    ticker_dossier: dossier,
  };
}

export function snapshotDossier(snapshot: ArchivedSnapshotPayload): TickerDossierPayload | undefined {
  return snapshot.ticker_dossier;
}
