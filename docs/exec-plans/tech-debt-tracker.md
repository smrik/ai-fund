# Tech Debt Tracker

Items tracked here get addressed on a rolling basis — not queued forever.
When fixed, move to the relevant sprint's completed log.

---

## Active Debt

| ID | Location | Issue | Priority | Added |
|---|---|---|---|---|
| TD-01 | `src/stage_02_valuation/batch_runner.py:151` | `ebit_margin_override` is `None` for all sectors — fallback is 15% hardcoded regardless of sector | High | 2026-03-06 |
| TD-02 | `src/stage_02_valuation/batch_runner.py:158` | `growth_mid = growth_near * 0.65` — mechanical fade with no business logic | Medium | 2026-03-06 |
| TD-03 | `src/stage_00_data/market_data.py` | `get_peer_multiples()` returns self only — no real peer data | High | 2026-03-06 |
| TD-04 | `src/stage_02_valuation/wacc.py:25` | `RISK_FREE_RATE = 0.045` hardcoded — should pull live 10Y Treasury | Medium | 2026-03-06 |
| TD-05 | `src/stage_03_judgment/base_agent.py:8` | Uses OpenAI SDK (`from openai import OpenAI`) — agents should use Anthropic SDK | High | 2026-03-06 |
| TD-06 | `config/settings.py:41` | `MIN_MARKET_CAP_MM = 2000` conflicts with Stage 1 filter's `500` floor — two sources of truth | Medium | 2026-03-06 |
| TD-07 | `src/stage_02_valuation/templates/dcf_model.py:103-115` | Bear/bull scenario multipliers are generic (0.6x/0.75x) — should be company-specific (Sprint 6) | Low | 2026-03-06 |

---

## Resolved Debt

| ID | Resolution | Sprint | Date |
|---|---|---|---|
| — | — | — | — |

