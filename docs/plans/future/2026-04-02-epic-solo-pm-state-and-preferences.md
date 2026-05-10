# Epic: Solo PM State And Preferences

| Field | Value |
|---|---|
| Status | Planned |
| Priority | P2 |
| Target release | v0.5.0 Solo PM State |
| GitHub | Epic issue to be created |
| Last updated | 2026-04-02 |

## Problem

The product is still mostly session-local. Watchlists, defaults, and visual preferences need to persist cleanly if Alpha Pod is going to feel like a real working product rather than a stateless tool bundle.

## Smallest Valuable Outcome

A solo PM can log in, keep a persistent watchlist, and have theme and workflow defaults restored across sessions.

## In Scope

- Minimal auth for a single-user or invite-only setup
- Persistent watchlists
- Theme preference
- Saved view/export defaults
- Lightweight user-state storage

## Out Of Scope

- Team permissions
- Shared workspaces
- Complex account management
- Billing or public signup flows

## Dependencies

- Stable API routes
- Canonical watchlist and ticker surfaces
- Clear storage boundaries between product state and research/model data

## Acceptance Criteria

- User can sign in with a simple supported flow
- Watchlists persist across sessions
- Theme and core UI defaults are restored reliably
- User-state storage stays simple and clearly separated from deterministic valuation data

## Notes

This should remain intentionally small. The goal is a better solo operator experience, not multi-tenant SaaS complexity.
