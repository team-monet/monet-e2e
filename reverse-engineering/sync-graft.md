# Monet Reverse-Engineering — Sync & Graft Protocol (multi-machine delta)

> Status: **DOCUMENTED** (2026-08-14, run 21). Source: `@team-monet/core` v0.9.0 TS
> (`src/sync-types.ts`, `engine.ts` `exportDelta`/`graftRows`/`batchDedup`/`initSyncIdentity`).
> This closes the `Gf=15` unknown noted in `schema-migration.md`: it is
> `SYNC_PAYLOAD_PROTOCOL_VERSION`, the graft PAYLOAD protocol ceiling — a separate constant from
> the DB `PRAGMA user_version` ladder.

## Two version ladders, deliberately separate

- **DB `user_version` ladder** (PRAGMA, scalar 0→12, no migration table — see `schema-migration.md`):
  `1` graph backfill, `2` temporal, `3` V-A arousal, `4` first_block, `5` sync primitives (slice 1a),
  `6` source-concept prerequisites, `7` source registry, `8` sync closure (replay-safe multi-writer),
  `9` source ledger, `11` source file-concept (rung 10 is SKIPPED — reusing it would have collided
  with the prior `SOURCE_LEDGER_SCHEMA_VERSION = 9` naming; actually the gap is because a withdrawn
  migration #187 briefly held 13 and the ladder is explicit-numbered), `12` first-block retirement.
- **`SYNC_PAYLOAD_PROTOCOL_VERSION = 15`** — the payload protocol ceiling. `exportDelta` stamps it;
  `graftRows` REFUSES anything above it. The refusal is the point: before this, a payload claiming any
  version was treated as v8, so a sender carrying tables a receiver had never heard of had rows
  silently dropped while its cursor advanced — permanent, silent loss. Bump whenever the payload
  gains a table OR a column that "carries an act". Changelog: `11` +lifecycle_edges/ratifications,
  `12` +stages/rule_bindings, `13` +concepts.skeleton_breadth, `14` first_block retired,
  `15` +ratifications.entrance/battery.

## The row-convergence clock (v8)

Mutable rows carry `(sync_revision, sync_writer)` — a per-writer convergence clock. `sync_updated_at`
is the RECEIVER's relay watermark; the sender's `sync_updated_at` and the receiver's are two
incomparable clock domains, so a bare timestamp comparison cannot decide convergence for mutable
columns. `(revision, writer)` is the "house pattern" (used by circle_aliases, first_block,
lifecycle_edges, stages, rule_bindings). `sync_writer` is a stable per-store writer id used to break
equal-revision ties. Grow-only fields (e.g. `stages.verified`) sit OUTSIDE that contest.

`initSyncIdentity` seeds the sync timestamp from `Math.max(Date.now(), maxPersistedSyncTimestamp())`
so a fresh store can never rewind the watermark.

## The payload (`GraftPayload`, `sync-types.ts`)

Carries every evidence-layer table (row types mirror the exact SQLite column names): `observations`,
`concepts`, `conceptRevisions`, `contradictions`, `edges`, `circleAliases`, `entities`,
`conceptEntities`, plus v8 additions — `edgeComponents` (per-writer edge contributions; aggregate
`edges` retained for legacy consumers), `deletions` (durable hard deletion), `conceptActivity`
(commutative per-writer usefulness/arousal contributions), `tombstones`, `restorations`,
`sessions`, `lifecycleEdges`, `ratifications`, `stages`, `ruleBindings`. Header fields: `since`
(inclusive watermark, 0 = full export), `exportedAt`, `deviceId`, `embedderModelId` (must match the
receiver or graft is REJECTED — cross-space cosine would be garbage).

Deliberately ABSENT from the payload: `gate_events` (local instrumentation — merging two machines'
action streams under one timeline would make every rate a lie), `resolution_events` (logs one
device's embedder decisions), `firstBlock` is legacy-only (schema-12 receivers convert eligible
rows to observations without reviving pins).

## Export (`exportDelta(since)`)

Read-only, one transaction. Reads the cursor first (`syncExportedAt`) to establish the SQLite read
snapshot, so every timestamped query is upper-bounded by it — a writer committing mid-export is left
for the next delta. Every table query filters `kind != 'source' AND source_identity IS NULL AND
active_observation_id IS NULL AND status != 'retired'` (native concepts only; source concepts are
connector-owned and never leave the machine). Exported concepts close over their immutable
evidence/revision ledger (`closureIds` → observations/revisions/contradictions) so a restoration is
self-contained. Normative substrate (lifecycle_edges, ratifications) replicates INDEPENDENTLY of
endpoint liveness: retired endpoints are NOT excluded, and both endpoints join LEFT (not INNER) so a
dangling edge re-exports through a relay chain (A→B→C).

## Import (`graftRows`) + post-sync sweep (`batchDedup`)

`graftRows` validates the payload against the LOCAL identity: `assertPinSatisfied` (a mismatched
constructor embedder would stamp the WRONG `embedderModelId`), `EmbedderMismatchError` on model
mismatch, refusal above `SYNC_PAYLOAD_PROTOCOL_VERSION`, and native-only validation
(`assertGraftPayloadIsNativeOnly`). Per-row `ON CONFLICT` clauses depend on the `uq_edge` index
(its existence is asserted at open as a safety check). Grafted concepts are marked dirty when their
winning observation binding changed (`GraftResult.conceptsMarkedDirty`).

`batchDedup` is the post-sync cross-machine sweep that closes duplicate links: it emits
`possible_duplicate_of` edges (and deliberately NOT `extraction_candidate` — that is flagged AT
rule birth, and a dedup sweep is not a birth).

## Parameters (this module)

| Parameter | Value | Where | Role |
|-----------|-------|-------|------|
| `SYNC_PAYLOAD_PROTOCOL_VERSION` | 15 | `engine.ts` const | graft payload ceiling (changelog 11→15) |
| user_version ladder | 0→12 (10 skipped) | `engine.ts` consts | DB schema milestone scalar |
| `GRAPH_SCHEMA_VERSION` | 1 | const | one-time graph backfill gate |
| `TEMPORAL_SCHEMA_VERSION` | 2 | const | temporal layer gate |
| `AROUSAL_SCHEMA_VERSION` | 3 | const | V-A arousal layer gate |
| `FIRST_BLOCK_SCHEMA_VERSION` | 4 | const | first_block table gate |
| `SYNC_SCHEMA_VERSION` | 5 | const | sync engine primitives gate |
| `SOURCE_SCHEMA_VERSION` | 6 | const | source-concept prerequisites gate |
| `SOURCE_REGISTRY_SCHEMA_VERSION` | 7 | const | durable knowledge_sources gate |
| `SYNC_CLOSURE_SCHEMA_VERSION` | 8 | const | replay-safe multi-writer sync contract |
| `SOURCE_LEDGER_SCHEMA_VERSION` | 9 | const | source scan/materialize/activation ledger |
| `SOURCE_FILE_CONCEPT_SCHEMA_VERSION` | 11 | const | file=concept reshape gate |
| `FIRST_BLOCK_RETIREMENT_SCHEMA_VERSION` | 12 | const | first-block retirement (PINNED, not tracking MONET_SCHEMA_VERSION) |
| `RETIREMENT_PAIR_FLAG_NAMED_MAX` | 3 | `engine.ts` | pair partners a retirement refusal names before "and N more" |
| `PAIR_FLAG_EDGE_TYPES` | `possible_duplicate_of`, `extraction_candidate` | `engine.ts` | pair-flag set treated alike everywhere |
| `EmbedderMismatchError` | thrown on model mismatch | `graftRows` | cross-space graft is rejected, never silently corrupted |

## Issues found

- None new beyond RE-26..RE-28 (gates module) — the sync protocol's refusal-ceiling and
  native-only validation are already-correct safety boundaries. The one latent risk noted is that
  `sync_revision`/`sync_writer` are nullable on legacy payloads (pre-v8), so a mixed-version mesh
  must be tolerated by receivers via the `>=` (not `>`) watermark on lifecycle events.
