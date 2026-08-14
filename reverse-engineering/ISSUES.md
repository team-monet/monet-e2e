# Monet Reverse-Engineering — Issue Registry

> Consolidated list of every issue found across the reverse-engineering effort.
> Detail lives in the per-module doc named under **Source**; this table is the
> one-line index.

## Status

- **open** — a real gap, product question, or maintenance risk found at the
  source level but not yet verified either way.
- **source** — verified by source reading only. A structural / code-quality
  issue that E2E cannot test (no observable behavior); routes to the code-fix
  (L2) queue, not the E2E verifier.
- **confirmed** — verified against the E2E test-suite (behavioral), not just
  source-level. The test named in `e2e_test` reproduces it.
- **fixed** — was a real bug (open/confirmed), now verified resolved in a
  specific Monet version (E2E XPASS + source-diff cross-check).
- **by-design** — documented behavior, a known trade-off, or future work.

## Severity (preliminary — source-level estimate; E2E-measured impact upgrades it)

- **S1** — data loss / corruption / silent wrong result.
- **S2** — scalability / operability (will bite in production) / security.
- **S3** — missing signal / UX / maintenance risk.
- **S4** — cosmetic / by-design note.

`e2e_test` names the test that proves the issue (an `XFAIL` test documents a
still-open bug and flips to `XPASS` when fixed); `—` = not yet E2E-verified.

| ID | One-line summary | Source | Status | e2e_test | severity |
|----|------------------|--------|--------|----------|----------|
| RE-01 | Dedup thresholds (tauAttach/tauAmbiguous) invisible to users — no CLI flag/env var/README; can't tune without patching source | dedup-resolution.md | open | — | S3 |
| RE-02 | Attach requires obsScore≥tauAttach AND centroidScore≥tauAmbiguous → a drifted centroid repels valid attaches into fork-signal | dedup-resolution.md | by-design | — | S4 |
| RE-03 | Resolution core fully duplicated between dist/index.js and dist/cli.js bundles (V1/sT vs xH/IN); patches must touch both | dedup-resolution.md | source | — | S3 |
| RE-04 | Lexical rank arm is Latin-script-only (`/[a-z0-9][a-z0-9_-]{2,}/`) → Korean/Japanese queries get zero lexical contribution | search-pipeline.md | open | — | S3 |
| RE-05 | Source concepts skip nativeScoreFloor (any score>0 enters) while native concepts below floor are dropped — intentional? | search-pipeline.md | open | — | S4 |
| RE-06 | Search is O(eligible segments) brute-force scan, no ANN index; cost grows linearly with store size | search-pipeline.md | by-design | — | S4 |
| RE-07 | `limit` truncation is silent — no flag tells the caller more matches existed | search-pipeline.md | confirmed | test22 | S3 |
| RE-08 | Migration steps run outside one transaction (version is a milestone, not a ledger); half-migrated state reports old version | schema-migration.md | by-design | — | S4 |
| RE-09 | supportedSchemaVersion=12 hardcoded in 3+ places; next schema bump must touch all in lockstep or doctor silently degrades | schema-migration.md | open | — | S3 |
| RE-10 | Schema version 10 skipped (9→11 jump); external tooling assuming consecutive numbers must know the hole | schema-migration.md | open | — | S4 |
| RE-11 | user_version conflates schema and feature backfills (0→1 graph backfill gated on graphEnabled) | schema-migration.md | open | — | S3 |
| RE-12 | Migration sentinel `author_agent_id="schema-12-first-block-migration"` leaks into product attribution APIs | schema-migration.md | by-design | — | S4 |
| RE-13 | Contradiction statuses are raw string literals across 6+ functions, no shared enum | contradiction-processing.md | source | — | S3 |
| RE-14 | Store-side auto-flag fires only when correction ATTACHES; a correction that creates (below tauAttach/forceNew) opens no contradiction | contradiction-processing.md | confirmed | test18 | S3 |
| RE-15 | memory_fetch status/openContradictions depend on derived column; latent coupling if a closer ever skips recompute | contradiction-processing.md | by-design | — | S4 |
| RE-16 | Explicit-circle recall bypasses archive hide (active alias → archived name still resolves) | circle-routing.md | by-design | — | S4 |
| RE-17 | storeInternal has no archived-circle guard: memory_store into an archived circle succeeds silently | circle-routing.md | confirmed | test24 | S3 |
| RE-18 | renameCircle doesn't refuse when `from` is an active alias to a third circle; upsert silently re-targets it | circle-routing.md | by-design | — | S4 |
| RE-19 | mergeCircle HARD-DELETES workstream concepts (no tombstone/confirmation), counts as noop | circle-routing.md | fixed | test23 | S2 |
| RE-20 | Every dashboard API request copies the whole store (~0.4–0.5s on 75MB); scales linearly, no cache/ETag | dashboard.md | by-design | — | S3 |
| RE-21 | graphDensity includes possible_duplicate_of edges, slightly inflating "structural density" | dashboard.md | open | — | S4 |
| RE-22 | Dashboard is local-only, read-only, Host-allowlisted — positive security posture, no remote-monitoring path | dashboard.md | by-design | — | S4 |
| RE-23 | `monet start` derives a fallback identity (`local-agent` / `<basename>-<sha8>`) when MONET_CALLER_ID/MONET_PROJECT_ID are unset, so `source_list` silently returns `[]` and `source_status`/`source_path`/`source_sync` return the non-disclosing "source is unavailable" — the identity mismatch is NOT discoverable (a caller sees a clean "no sources" state) | sources-sync.md | confirmed | test26 | S3 |
| RE-24 | updateSource lets `access` be mutated, silently de-authorizing the host that registered/syncs the source | sources-sync.md | open | — | S2 |
| RE-25 | MCP source_sync is synchronous/blocking (awaits full clone→chunk→hash→embed→publish→verify); can exceed MCP timeouts | sources-sync.md | by-design | — | S4 |
| RE-26 | gate_events has NO retention/pruning; grows with agent activity (2–3 orders > resolution_events), will become largest table | gates.md | open | — | S2 |
| RE-27 | Conformance "cheap half" can only emit `changed` for blocking denies; advisory fires stay `unavailable` → advisory rules un-retirable until judgment half ships | gates.md | by-design | — | S4 |
| RE-28 | gate_events.action_context stores raw intercepted commands verbatim (paths/hostnames/flags) — most privacy-sensitive column; local-only + scrub-covered | gates.md | by-design | — | S3 |
| RE-29 | `-d` isolates the SQLite DB but NOT source storage — `sourceStorageDir` hard-defaults to `~/.monet/sources` via `homedir()` with no `-d` scoping / CLI/env override; isolated-source work silently writes to prod | sources-sync.md | confirmed | — | S2 |
| RE-30 | repo-md `source_sync` fails `EACCES` on macOS — `sealSnapshot` chmods the tree `0o500` then `renameSync` into place; APFS refuses the in-place rename of a non-writable dir, so the stage-beside-variant mitigation (source-materializer.ts:2225) is insufficient on macOS 15.x | sources-sync.md | confirmed | test25 | S2 |
| RE-31 | V-A living-model tunables hardcoded module constants, not constructor opts (usefulness tau=60d, arousal tau=120d, arousal floor 0.1, arousal weight 0.5, recency half-life 14d inline) — can't tune without patching source; recency 14 is a bare magic number vs the named usefulness/arousal taus | living-model-ranking.md | open | — | S3 |
| RE-32 | `livingModelCard` discards the ranking score + per-signal breakdown (returns id/title/kind/confidence/supportCount) — the ordering is opaque: a caller sees that a concept ranks high but not why (recency vs usefulness vs arousal) | living-model-ranking.md | open | — | S4 |

## Maintenance notes

- **E2E verification loop (2026-08-14):** behavioral `open` issues are converted
  into XFAIL tests (`run_all.py` exit 2 = known-bug documented, expected; exit 3
  = XPASS, bug appears fixed). The test name is recorded in `e2e_test`; when a
  test flips XFAIL→XPASS the issue status moves to closed and severity is
  re-assessed against the measured impact.
- Structural issues (`source` status) cannot be E2E-verified — they route to the
  code-fix (L2) queue, whose changes are then regression-gated by the E2E suite.
- Re-check `open`/`confirmed` issues against each `@team-monet/monet` version
  bump (source diff).
- New issues get the next free `RE-NN`, a row here, and detail in the owning
  module doc.
- The `sources-sync.md` module doc records RE-23..25; `gates.md` records RE-26..28.
- **Sources E2E isolation (2026-08-14):** `sourceStorageDir` = `resolve(homedir(),
  ".monet", "sources")` and is NOT wired to `-d` (RE-29). To test sources without
  touching prod `~/.monet/sources`, redirect `HOME` to a temp dir for BOTH the
  CLI `source add` and the MCP server subprocess (test25 does this; the
  `source_storage_isolated_via_home` check proves the redirect worked).
