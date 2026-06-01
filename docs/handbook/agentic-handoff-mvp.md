# Agentic Handoff MVP

This page is the operator handbook for the Evidence Packet -> Agent Observation -> Translator -> PM Decision Queue workflow.

## Goal

Use the MVP loop to test real tickers safely while keeping the deterministic boundary intact:

- evidence packets are deterministic
- one grounded observation runner produces anchored observations only
- translator behavior is deterministic
- PM approval is the only path into applied overrides

## Fast Smoke Check

Run the isolated smoke command first:

```powershell
rtk python scripts/manual/smoke_agentic_handoff_mvp.py --ticker IBM
```

Default behavior:

- uses a temporary SQLite snapshot instead of the live `data/alpha_pod.db`
- uses fixture-backed collector shims for networked evidence sources plus local stub observations for runnable profiles
- approves assumption-change queue items only inside that temporary snapshot

Optional live-agent mode:

```powershell
rtk python scripts/manual/smoke_agentic_handoff_mvp.py --ticker IBM --live-agents
```

Use live mode only when local credentials and network access are intentionally available.

## Audit Shape

Every runnable profile uses the same judgment-layer runner:

```text
profile config + deterministic evidence packet
-> GroundedObservationAgent extraction prompt
-> GroundedObservationAgent formatting prompt
-> anchored observations
-> deterministic translator
-> PM Decision Queue
-> PM approve
-> explicit apply to deterministic assumptions
```

The profile changes the evidence payload, prompt guidance, allowed observation types, allowed assumption fields, and translator rule group. It does not change the LLM runner class.

## v0.1 Alpha Decision Room

The PM Queue is the alpha review room for agentic output. Use it to answer six questions before approving anything:

1. What changed?
2. Which profile proposed it?
3. Which packet facts, snippets, and observations support it?
4. Which other profiles touch the same deterministic field?
5. What did the deterministic preview resolve or skip?
6. What was approved, rejected, deferred, or edited?

The `Conflicts / Shared Drivers` panel groups pending assumption-change queue items by deterministic driver, such as `revenue_growth_near`, `wacc`, or `exit_multiple`. A `conflict` means profiles propose different values for the same driver; a `cluster` means multiple profiles touch the same driver and should be reviewed together.

Each queue item now surfaces:

- observation claim, confidence, importance, evidence rationale, and what would change the agent's mind
- packet provenance, including source quality and packet hash metadata
- field-level preview details, including resolved values, skipped fields, conflicts, preview timestamp, and preview fingerprint
- decision history for edits, approvals, rejections, and deferrals
- reject/defer reasons entered by the PM

Approval remains preview-gated. If the proposal or deterministic input snapshot changes after preview, approval returns a conflict response and the PM must preview again. Approval records the PM decision; a separate apply action mutates deterministic assumptions exactly once.

## What The Smoke Check Verifies

The script fails if any of these invariants break:

1. Placeholder evidence creates a PM Queue item.
2. Previewed assumption targets do not exactly match the approved deterministic override targets.
3. The translator cannot run the public handoff path without the source evidence packet.

The script also prints:

- new packet count
- new observation count
- new queue item count
- per-profile run status
- skipped fields from preview resolution
- blocked or failed profile notes

## Recommended PM Review Loop

After the smoke check passes:

1. Open the React shell and go to `Valuation -> PM Queue`.
2. Run one profile at a time on the target ticker.
3. Check the profile run status card first.
4. Review evidence packet source quality before trusting any queue item.
5. For assumption-change items, always preview after the latest PM edit.
6. Review shared-driver clusters before approving isolated items.
7. Approve only when the preview values look correct.
8. Apply an approved item only when it should enter deterministic assumptions.
9. Use reject or defer with a short reason for items that should not flow into deterministic overrides.

## Reading Statuses

- `completed_with_items`: observations translated into queue items
- `completed_no_items`: run completed but nothing translated into queue items
- `blocked`: packet did not have enough real evidence to run safely
- `failed`: agent execution failed and the error stayed visible
- `not_runnable`: explicit unsupported profile; this should only appear for unknown or intentionally disabled future profiles
- `previewed`: queue item has a fresh deterministic preview and can be approved unless fields were skipped

## Known MVP Limitations

- The default smoke script uses fixture-backed evidence collectors and stub observations; it proves workflow safety, not model quality.
- A profile can be `blocked` when local ticker evidence is incomplete even if the rest of the stack is healthy.
- Queue approvals still write to SQLite, so live manual testing should stay deliberate even though the smoke script itself is isolated.
- Agent prompt/output artifacts are stored in packet run metadata for alpha auditability. Packet lists expose only artifact availability and status; fetch raw audit material deliberately with `GET /api/tickers/{ticker}/evidence-packets/{packet_id}/agent-artifact`. Do not paste secrets or private credentials into evidence packets.
