import type { ArchivedSnapshotPayload, OverviewPayload, TickerWorkspace } from "@/lib/types";

export function snapshotToWorkspace(
  snapshot: ArchivedSnapshotPayload,
  previous?: TickerWorkspace,
): TickerWorkspace {
  const memo = snapshot.memo ?? {};
  const valuation = memo.valuation ?? {};

  return {
    ticker: snapshot.ticker,
    company_name: snapshot.company_name ?? memo.company_name ?? previous?.company_name ?? snapshot.ticker,
    sector: snapshot.sector ?? memo.sector ?? previous?.sector ?? null,
    action: snapshot.action ?? memo.action ?? previous?.action ?? null,
    conviction: snapshot.conviction ?? memo.conviction ?? previous?.conviction ?? null,
    current_price: snapshot.current_price ?? valuation.current_price ?? previous?.current_price ?? null,
    analyst_target: previous?.analyst_target ?? null,
    bear_iv: valuation.bear ?? previous?.bear_iv ?? null,
    base_iv: snapshot.base_iv ?? valuation.base ?? previous?.base_iv ?? null,
    bull_iv: valuation.bull ?? previous?.bull_iv ?? null,
    weighted_iv: previous?.weighted_iv ?? null,
    upside_pct_base: valuation.upside_pct_base ?? previous?.upside_pct_base ?? null,
    latest_snapshot_date: snapshot.created_at ?? previous?.latest_snapshot_date ?? null,
    snapshot_available: true,
    last_snapshot_id: snapshot.id,
    latest_action: snapshot.action ?? memo.action ?? previous?.latest_action ?? null,
    latest_conviction: snapshot.conviction ?? memo.conviction ?? previous?.latest_conviction ?? null,
  };
}

export function snapshotToOverview(
  snapshot: ArchivedSnapshotPayload,
  previous?: OverviewPayload,
): OverviewPayload {
  const memo = snapshot.memo ?? {};

  return {
    ticker: snapshot.ticker,
    company_name: snapshot.company_name ?? memo.company_name ?? previous?.company_name ?? snapshot.ticker,
    one_liner: memo.one_liner ?? previous?.one_liner ?? null,
    variant_thesis_prompt: memo.variant_thesis_prompt ?? previous?.variant_thesis_prompt ?? null,
    market_pulse: previous?.market_pulse ?? null,
    valuation_pulse: previous?.valuation_pulse ?? null,
    thesis_changes: previous?.thesis_changes ?? [],
    next_catalyst: previous?.next_catalyst ?? null,
  };
}
