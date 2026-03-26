# Global Macro Context Skill

This skill guides the MacroAgent when refreshing `data/macro_context.md`.
It defines what to search for, what to extract, and what format to write.

## Macro Variables to Monitor (in priority order)

### 1. Rates & Fed
- Fed Funds Rate: current target range, next meeting expectations
- 10-year UST yield: level and 1-month change
- 2s10s curve: steepening or inverting?
- Real rate (10Y TIPS yield)
- Market-implied rate path: CME FedWatch, number of 2025/2026 cuts priced

### 2. Inflation
- Latest CPI (headline and core YoY)
- Latest PCE (headline and core YoY)
- PPI trend (leading for CPI by ~3 months)
- Breakeven inflation (5Y5Y forward)

### 3. Growth & Labour
- Latest GDP print (quarter, annualised rate)
- ISM Manufacturing PMI (leading for industrial activity)
- ISM Services PMI
- NFP (non-farm payrolls) — last two months
- Unemployment rate
- Atlanta Fed GDPNow estimate for current quarter

### 4. Credit & Risk Appetite
- IG credit spread (CDX.IG or BAML IG OAS)
- HY credit spread (CDX.HY or BAML HY OAS)
- VIX level and 1-month trend
- Dollar index (DXY) — matters for multinationals and commodities

### 5. Commodities
- WTI crude oil (spot price and 12-month strip)
- Natural gas Henry Hub
- Copper (LME) — global growth proxy
- Gold — risk-off/inflation hedge signal

### 6. Geopolitical / Event Risk
- Active conflicts with market impact (supply chain, commodity, energy)
- Trade policy: tariffs, export controls, nearshoring
- Major central bank policy changes outside Fed (ECB, BoJ, PBOC)
- Upcoming known macro events (Fed meetings, CPI prints, elections)

## Output Format for macro_context.md

Write in this exact structure so it is easy for agents to parse:

```
# Macro Context — [DATE]

## Rates & Fed
- Fed Funds Rate: X.XX–X.XX%
- 10Y UST: X.XX% ([+/- X]bp vs. 1 month ago)
- 2s10s: [inverted/flat/steepening] at [X]bp
- Cuts priced 2025: [N] cuts | Fed next meeting: [DATE, expectation]

## Inflation
- CPI (latest): [X.X%] headline, [X.X%] core
- PCE (latest): [X.X%] headline, [X.X%] core
- Trend: [accelerating/decelerating/stable]

## Growth & Labour
- GDP (latest): [X.X%] QoQ annualised (Q[X] [YEAR])
- ISM Mfg: [XX.X] ([expanding/contracting])
- ISM Services: [XX.X]
- NFP (last month): [+/- XXX,XXX] jobs | Unemployment: [X.X%]
- GDPNow Q[X]: [X.X%]

## Credit & Risk
- IG spread: [XXX]bp | HY spread: [XXX]bp
- VIX: [XX.X]
- DXY: [XXX.X]

## Commodities
- WTI: $[XX.XX] | Nat Gas: $[X.XX]
- Copper: $[X,XXX]/tonne
- Gold: $[X,XXX]/oz

## Geopolitical / Event Risk
- [Bullet list of current risks and upcoming events]

## Market Implications (2–3 sentences)
[Agent's synthesis: what matters most for equity investors right now]
```

## Search Queries to Run
Run these searches (latest 1 week) and synthesise into the above format:
1. "Federal Reserve interest rates current [month year]"
2. "CPI PCE inflation latest [month year]"
3. "NFP jobs report GDP growth [month year]"
4. "credit spreads VIX risk appetite [month year]"
5. "crude oil copper gold prices [month year]"
6. "geopolitical risk trade tariffs market [month year]"
