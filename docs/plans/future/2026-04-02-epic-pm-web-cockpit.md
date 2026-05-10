# Epic: PM Web Cockpit

| Field | Value |
|---|---|
| Status | Planned |
| Priority | P1 |
| Target release | v0.4.0 PM Web Cockpit |
| GitHub | Epic issue to be created |
| Last updated | 2026-04-02 |

## Problem

The React shell exists and is improving, but the product still does not fully feel like a sharp PM cockpit. The Overview surface in particular should be more informative at a glance and more tightly connected to valuation and research workflows.

## Smallest Valuable Outcome

The web app becomes the best fast-start surface for a ticker: quick company context, price history, valuation range, comps context, and recent news, all backed by cached ticker payloads.

## In Scope

- Overview redesign around facts, price history, valuation band, and news
- Cached/preloaded ticker route payloads
- Better scenario/comps visualization
- Clear click-through from summary surfaces into Valuation and Research
- Audit as the hub for artifacts, evidence, and diagnostics
- TUI companion definition after the web-first path is solid

## Out Of Scope

- Replacing the existing API layer
- Heavy design experimentation unrelated to investing workflow
- Mobile-first redesign as a primary goal

## Dependencies

- Canonical dossier contract
- Faster API preload/caching behavior
- Stable news/research payloads

## Acceptance Criteria

- Overview can render key company facts, price history, valuation range, and news from one coherent payload
- Route transitions feel immediate because of preload/caching work
- The valuation and comps surfaces are richer without becoming cluttered
- The web app is clearly the primary operator surface for lightweight research

## Notes

This epic is about workflow quality, not cosmetic polish for its own sake.
