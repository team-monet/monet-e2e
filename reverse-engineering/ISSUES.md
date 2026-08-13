# Monet Reverse-Engineering — Issue Registry

> Consolidated list of every issue found across the reverse-engineering effort.
> Detail lives in the per-module doc named under **Source**; this table is the
> one-line index. Status: `open` (real gap to fix/confirm), `confirmed`
> (E2E-verified), `by-design` (documented/known trade-off, or future work).

| ID | One-line summary | Source | Status |
|----|------------------|--------|--------|
| RE-01 | Dedup thresholds (tauAttach/tauAmbiguous) invisible to users — no CLI flag/env var/README; can't tune without patching source | dedup-resolution.md | open |
| RE-02 | Attach requires obsScore≥tauAttach AND centroidScore≥tauAmbiguous → a drifted centroid repels valid attaches into fork-signal | dedup-resolution.md | by-design |
| RE-03 | Resolution core fully duplicated between dist/index.js and dist/cli.js bundles (V1/sT vs xH/IN); patches must touch both | dedup-resolution.md | open |
| RE-04 | Lexical rank arm is Latin-script-only (`/[a-z0-9][a-z0-9_-]{2,}/`) → Korean/Japanese queries get zero lexical contribution | search-pipeline.md | open |
| RE-05 | Source concepts skip nativeScoreFloor (any score>0 enters) while native concepts below floor are dropped — intentional? | search-pipeline.md | open |
| RE-06 | Search is O(eligible segments) brute-force scan, no ANN index; cost grows linearly with store size | search-pipeline.md | by-design |
| RE-07 | `limit` truncation is silent — no flag tells the caller more matches existed | search-pipeline.md | open |
| RE-08 | Migration steps run outside one transaction (version is a milestone, not a ledger); half-migrated state reports old version | schema-migration.md | by-design |
| RE-09 | supportedSchemaVersion=12 hardcoded in 3+ places; next schema bump must touch all in lockstep or doctor silently degrades | schema-migration.md | open |
| RE-10 | Schema version 10 skipped (9→11 jump); external tooling assuming consecutive numbers must know the hole | schema-migration.md | open |
| RE-11 | user_version conflates schema and feature backfills (0→1 graph backfill gated on graphEnabled) | schema-migration.md | open |
| RE-12 | Migration sentinel `author_agent_id="schema-12-first-block-migration"` leaks into product attribution APIs | schema-migration.md | by-design |
| RE-13 | Contradiction statuses are raw string literals across 6+ functions, no shared enum | contradiction-processing.md | confirmed |
| RE-14 | Store-side auto-flag fires only when correction ATTACHES; a correction that creates (below tauAttach/forceNew) opens no contradiction | contradiction-processing.md | open |
| RE-15 | memory_fetch status/openContradictions depend on derived column; latent coupling if a closer ever skips recompute | contradiction-processing.md | by-design |
| RE-16 | Explicit-circle recall bypasses archive hide (active alias → archived name still resolves) | circle-routing.md | by-design |
| RE-17 | storeInternal has no archived-circle guard: memory_store into an archived circle succeeds silently | circle-routing.md | open |
| RE-18 | renameCircle doesn't refuse when `from` is an active alias to a third circle; upsert silently re-targets it | circle-routing.md | by-design |
| RE-19 | mergeCircle HARD-DELETES workstream concepts (no tombstone/confirmation), counts as `noop` | circle-routing.md | open |
| RE-20 | Every dashboard API request copies the whole store (~0.4–0.5s on 75MB); scales linearly, no cache/ETag | dashboard.md | by-design |
| RE-21 | graphDensity includes possible_duplicate_of edges, slightly inflating "structural density" | dashboard.md | open |
| RE-22 | Dashboard is local-only, read-only, Host-allowlisted — positive security posture, no remote-monitoring path | dashboard.md | by-design |
| RE-23 | 4 source MCP tools hard-gated on MONET_CALLER_ID/MONET_PROJECT_ID; unset → opaque failure, feature silently lost | sources-sync.md | open |
| RE-24 | updateSource lets `access` be mutated, silently de-authorizing the host that registered/syncs the source | sources-sync.md | open |
| RE-25 | MCP source_sync is synchronous/blocking (awaits full clone→chunk→hash→embed→publish→verify); can exceed MCP timeouts | sources-sync.md | by-design |
| RE-26 | gate_events has NO retention/pruning; grows with agent activity (2–3 orders > resolution_events), will become largest table | gates.md | open |
| RE-27 | Conformance "cheap half" can only emit `changed` for blocking denies; advisory fires stay `unavailable` → advisory rules un-retirable until judgment half ships | gates.md | by-design |
| RE-28 | gate_events.action_context stores raw intercepted commands verbatim (paths/hostnames/flags) — most privacy-sensitive column; local-only + scrub-covered | gates.md | by-design |

## Legend

- **open** — a real gap, a product question to confirm, or a maintenance risk to track.
- **confirmed** — verified against the E2E test-suite (not just source-level).
- **by-design** — documented behavior, a known trade-off, or future-work territory.

## Maintenance notes

- Re-check `open`/`confirmed` issues against each `@team-monet/monet` version bump (source diff).
- New issues get the next free `RE-NN`, a row here, and detail in the owning module doc.
- The `sources-sync.md` module doc records RE-23..25; `gates.md` records RE-26..28.
