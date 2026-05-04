import type { ArchivedSnapshotPayload, OverviewPayload, TickerWorkspace } from "@/lib/types";

export function snapshotToWorkspace(
  snapshot: ArchivedSnapshotPayload,
  previous?: TickerWorkspace,
): TickerWorkspace {
  const memo = snapshot.memo ?? {};
  const valuation = memo.valuation ?? {};
  const dossier = snapshot.ticker_dossier;
  const latest = dossier?.latest_snapshot;
  const identity = latest?.company_identity;
  const market = latest?.market_snapshot;
  const dossierValuation = latest?.valuation_snapshot;

  return {
    ticker: dossier?.ticker ?? snapshot.ticker,
    company_name: dossier?.display_name ?? identity?.display_name ?? snapshot.company_name ?? memo.company_name ?? previous?.company_name ?? snapshot.ticker,
    sector: identity?.sector ?? snapshot.sector ?? memo.sector ?? previous?.sector ?? null,
    action: snapshot.action ?? memo.action ?? previous?.action ?? null,
    conviction: snapshot.conviction ?? memo.conviction ?? previous?.conviction ?? null,
    current_price: market?.price ?? dossierValuation?.current_price ?? snapshot.current_price ?? valuation.current_price ?? previous?.current_price ?? null,
    analyst_target: market?.analyst_target ?? previous?.analyst_target ?? null,
    bear_iv: dossierValuation?.bear_iv ?? valuation.bear ?? previous?.bear_iv ?? null,
    base_iv: dossierValuation?.base_iv ?? snapshot.base_iv ?? valuation.base ?? previous?.base_iv ?? null,
    bull_iv: dossierValuation?.bull_iv ?? valuation.bull ?? previous?.bull_iv ?? null,
    weighted_iv: dossierValuation?.expected_iv ?? previous?.weighted_iv ?? null,
    upside_pct_base: dossierValuation?.upside_pct ?? valuation.upside_pct_base ?? previous?.upside_pct_base ?? null,
    latest_snapshot_date: dossier?.as_of_date ?? snapshot.created_at ?? previous?.latest_snapshot_date ?? null,
    snapshot_available: true,
    last_snapshot_id: dossier?.export_metadata.snapshot_id ?? snapshot.id,
    latest_action: snapshot.action ?? memo.action ?? previous?.latest_action ?? null,
    latest_conviction: snapshot.conviction ?? memo.conviction ?? previous?.latest_conviction ?? null,
    ticker_dossier_contract_version: dossier?.contract_version ?? previous?.ticker_dossier_contract_version ?? null,
    ticker_dossier: dossier ?? previous?.ticker_dossier,
  };
}

export function snapshotToOverview(
  snapshot: ArchivedSnapshotPayload,
  previous?: OverviewPayload,
): OverviewPayload {
  const memo = snapshot.memo ?? {};
  const dossier = snapshot.ticker_dossier;
  const identity = dossier?.latest_snapshot.company_identity;

  return {
    ticker: dossier?.ticker ?? snapshot.ticker,
    company_name: dossier?.display_name ?? identity?.display_name ?? snapshot.company_name ?? memo.company_name ?? previous?.company_name ?? snapshot.ticker,
    one_liner: memo.one_liner ?? previous?.one_liner ?? null,
    variant_thesis_prompt: memo.variant_thesis_prompt ?? previous?.variant_thesis_prompt ?? null,
    market_pulse: previous?.market_pulse ?? null,
    valuation_pulse: previous?.valuation_pulse ?? null,
    thesis_changes: previous?.thesis_changes ?? [],
    next_catalyst: previous?.next_catalyst ?? null,
    ticker_dossier_contract_version: dossier?.contract_version ?? previous?.ticker_dossier_contract_version ?? null,
    ticker_dossier: dossier ?? previous?.ticker_dossier,
  };
}
