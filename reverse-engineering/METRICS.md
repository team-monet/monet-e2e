# Reverse-Engineering Metrics

> Progress of the Monet source reverse-engineering effort (agent-ops cron).
> "Progress" = documented modules / identified parameters / found issues, by data.
> Related: root `METRICS.md` tracks E2E test-suite metrics.

## Core metrics

| Date | Modules documented | Thresholds/params identified | Issues found | Notes |
|------|-------------------|------------------------------|--------------|-------|
| 2026-08-10 | 1 — store resolution pipeline (dedup) | 6 (tauAttach, tauAmbiguous, edgeSimMin, nativeScoreFloor, wi=6, lexical boost H1=1.0) | 3 (RE-01..RE-03) | Priority-1 answered: dedup threshold located in per-model config map `pU` + `applyEmbedderDerivedThresholds`; decision fn `V1`. See `dedup-resolution.md` |
| 2026-08-11 | 2 — search pipeline (`memory_search`) | 10 (+4: default limit=5, lexical tokenizer regex (Latin-only), Ar=40000 response cap, nt=256 circle-name max) | 7 (+4: RE-04..RE-07) | Full read-side flow: store.search → oT (best-obs cosine) → q1 lexical rank boost → floor filter → default-circle tiebreak; source concepts bypass floor; Korean queries get NO lexical boost (regex Latin-only). See `search-pipeline.md` |
| 2026-08-11 | 3 — schema migration & versioning | 21 (+11: user_version ladder 0→12, supportedSchemaVersion=12, sync/graft protocol=15, first-block sentinel zT, migrated obs id scheme, content prefix, graph-backfill gate <1, first-block window [9,12), assessment `e===12`, exclusive-lock probe ±1, closure-trigger 7→8 bump) | 12 (+5: RE-08..RE-12) | No migration table — `PRAGMA user_version` scalar ladder 0→12 with idempotent `table_info`-guarded DDL; First Block pin conversion at 12 carries sentinel author; doctor/repair hardcode supported=12 (3+ places); version 10 skipped; graph backfill conflates 0→1. See `schema-migration.md` |
| 2026-08-12 | 4 — contradiction processing (flag/mediate/dismiss) | 34 (+13: decision enum [accept-new,keep-current,dismiss], status vocab {open,resolved,dismissed}, pair-flag edge types [possible_duplicate_of,extraction_candidate], flag confidence −.3 floor .1, flag arousal +3, resolve arousal +1, disputed confidence cap .5, confidence factor .6+.1/session+.2/resolved, LT=200 detail trunc, 2s last-confirmed window, disputed-status derivation CASE, anti-guess guard condition, keep-current ≥1-prior rule) | 15 (+3: RE-13..RE-15) | Full contradiction lifecycle in source: store-side auto-flag on correction ATTACH, manual flag (kinds value-conflict/staleness/scope-conflict), internal impeachment; `resolveContradiction` holds BOTH verdict branches (status literals 'resolved'/'dismissed', no enum — RE-13 confirmed); concept status is DERIVED via recomputeNativeConceptProjection (`CASE open_count>0 THEN 'disputed' ELSE 'active'`); dismiss ignores body (E2E run-11 next-step pre-answered); pair-flag dismissal writes memory_edge.dismissed_at. See `contradiction-processing.md` |
| 2026-08-12 | 5 — circle routing & aliases lifecycle | 42 (+8: `W`='*' reserved global-breadth marker, `rd`='legacy-star' legacy-* dest base, alias status vocab {active,archived} self-row archive, listCircles LIMIT 20, merge resolution {auto,forceNew} default forceNew, legacy dest suffix -2..N, 3 gate-generation triggers on alias insert/update/delete, single-hop alias resolution rule) | 19 (+4: RE-16..RE-19) | Circles are IMPLICIT namespaces (no registry table); `circle_aliases` is the only circle-side table (alias/archive rows). `resolveCircle` = single-hop active-alias lookup, applied at every circle-scoped entry point. rename/merge write alias from→to + repoint to_name rows (graph kept flat); merge HARD-DELETES workstreams (RE-19); archive = self-alias status='archived' hiding store-wide recall only (RE-16 explicit-circle bypass, RE-17 no store guard); renameCircle re-targets existing alias rows (RE-18); legacy-`*` auto-migrated on open to legacy-star[-N]. See `circle-routing.md` |
| 2026-08-13 | 6 — dashboard (server + client) | 54 (+12: dashboard port default 7373, Host allowlist {127.0.0.1,localhost,[::1]}, snapshot-per-request (full SQLite backup + unlink; temp dir monet-dash-* under os.tmpdir()), retired filter `et`='status != retired', source detection `t0`, graphDensity formula liveEdges/NULLIF(concepts,0), sourceBackoff base 30000 ms ×2 cap=interval, attempt-events window 128, GRAPH_NODE_LIMIT=800, clustering {K=14,min=40,max=160,MAX_ITER=1500}, localStorage monet-dash:v1/LS_SCHEMA_V=8, graph charge/gravity consts) | 22 (+3: RE-20..RE-22) | Last undocumented module → ALL 6 DOCUMENTED. `monet dashboard` = local-only read-only vanilla-JS SPA; every API call snapshots the whole DB (better-sqlite3 backup, readonly open) → query → unlink; no write endpoints; Host-allowlist 403; browser auto-open. Verified LIVE: empty-store VZ shape, E2E store counts (990 concepts / 2978 obs / 5751 edges / 13 open contra / density 5.81), includeRetired delta, 403/404 shapes, snapshot+exit cleanup, 0.44–0.51 s per request on 75 MB store (RE-20). See `dashboard.md` |
| 2026-08-13 | 7 — sources & sync machinery | 78 (+24: source type enum repo-md/git-md, writeBack none/pull-request, refresh manual/interval + default interval 3600s, freshness window manual 86400s / interval max(60,2×interval), backoff CP base 30000 ×2 cap=interval, jitter Ww sha256%-deterministic, initial-delay min(30000,10% interval), run state enum 7, run result enum success/failed/partial, snapshot state enum 4, lifecycle enum active/tombstoned, content hash iP monet-src-content/v1:sha256:, ingest domain nP monet-src-ingest/v1, op domain oP monet-src-op/v2, content-model v5 Zd, parse-deadline cap CS=100000, chunk write_state enum 4, chunk lifecycle enum 3, cleanup-item kind enum 3, attempt-event kind enum 4, removal state enum 3, auth env vars MONET_CALLER_ID/MONET_PROJECT_ID, git-md allocator sourceStorageDir/git-md/<id>/repository.git, transport schemes https/ssh + PR-writeBack github.com-only, source-id regex 1-64 lowercase/interior-hyphens, live-run unique index) | 25 (+3: RE-23..RE-25) | New module → 7 DOCUMENTED. Sources = registered external Markdown repos scanned/chunked/hashed/materialized into concepts, published as a sealed read-only snapshot (`current` symlink + realpath escape check). Auth is server-bound via env (`MONET_CALLER_ID`/`MONET_PROJECT_ID`) matching per-source `allowed_caller_ids`×`allowed_project_ids`. Fenced/tokenized/hash-checked publish pipeline (beginRun→stageManifest→beginActivation→publishRun→recordVerification) + scheduler with lease + exp backoff + deterministic jitter. 16 source_* tables. See `sources-sync.md` |
| 2026-08-14 | 9 — gates/conformance/journal + sync/graft (FIRST module documented from the readable TS source) | 110 (+32: 3 schema CHECK safety boundaries, 9 enum unions, 6 stage_lookup caps, 5 gate-mirror/journal consts, SYNC_PAYLOAD_PROTOCOL_VERSION=15, v8 row-convergence clock, user_version rung names 1..12, RETIREMENT_PAIR_FLAG_NAMED_MAX=3, PAIR_FLAG_EDGE_TYPES) | 3 (+3: RE-26..RE-28) | Gates/stages/rule-bindings + deterministic trigger-pattern matcher + gate journal + conformance "cheap half" documented from READABLE TS (`@team-monet/core` v0.9.0) not minified dist; sync/graft payload ceiling reconciled (`Gf`=15). Also created the missing `ISSUES.md` (RE-01..RE-28). See `gates.md` + `sync-graft.md` |

## Module inventory

| Module | File(s) | Status | Doc |
|--------|---------|--------|-----|
| Store resolution / dedup pipeline (`resolutionCandidates`, `rankByCentroid`, `nominateByObservation`, `oT`, `q1`, `V1`, `sT`) | dist/index.js (+ cli.js bundle) | **DOCUMENTED** | `dedup-resolution.md` |
| Embedder config map (`pU`/`XH`) & threshold application | dist/index.js, dist/cli.js | **DOCUMENTED** | `dedup-resolution.md` |
| Search pipeline (`memory_search`, `search()`, `oT`/`scoreNativeConcepts`, `q1` lexical arm, `B1`/`scoreSourceConcepts`, `nativeScoreFloor`, `resolveCircle`, `EF`/`bF`) | dist/index.js | **DOCUMENTED** | `search-pipeline.md` |
| Schema migration 4→12 | dist/index.js, dist/cli.js | **DOCUMENTED** | `schema-migration.md` |
| Contradiction processing (`flagContradiction`, `resolveContradiction`, `dismissPossibleDuplicate`, auto-flag on correction attach, impeachment, `recomputeNativeConceptProjection` status derivation, `memory_resolve`/`memory_flag_contradiction` handlers) | dist/index.js | **DOCUMENTED** | `contradiction-processing.md` |
| Circle routing & aliases (`resolveCircle`/`resolveCircleName`, `circle_aliases` table + triggers, `renameCircle`, `mergeCircle`, `archiveCircle`/`unarchiveCircle`, `listCircles`, `moveCircleScopedTables`, `chooseLegacyStarDestination`, `migrateLegacyStarCircle`, `memory_circle_manage` handler, `*`/`W` reserved marker + `skeleton_breadth='global'`) | dist/index.js | **DOCUMENTED** | `circle-routing.md` |
| Dashboard (server: `dashboard` command wiring, snapshot isolation Hb, read-only query `_t`, HTTP routes, Host allowlist, /api/graph\|entities\|sources payloads + all Ue SQL, source-derived fns i0/a0/o0/s0; client: filters, force layout, GRAPH_NODE_LIMIT, clustering, localStorage persistence) | dist/cli.js (bundle), dist/dashboard/{index.html,app.js,style.css} | **DOCUMENTED** | `dashboard.md` |
| Sources & sync (source registry `rP`, source ledger `LP`, sync engines `Jd`/`gT`/`mT`/`iU`/`rU`, scheduler `$P`/`Rm`/`CP`/`Ww`, content hashing `eg`/`Qm`/`Nm`/`DS`, sealed path `ni`/`rT`, auth context `J4`/`requireConnectorContext`; 4 MCP tools source_list/status/path/sync; CLI `source add/list/show/remove`; 16 source_* tables) | dist/index.js, dist/cli.js | **DOCUMENTED** | `sources-sync.md` |
| Gates / conformance / gate journal (`stages`, `rule_bindings`, `gate_events`, `gate_event_stages`, `gate_meta`; trigger-pattern matcher `matchesTriggerPattern`, `gateQuery`/`evaluateGate`, `stageLookup`/`evaluateStageLookup`, gate mirror `materializeGateMirror`/`inspectSidecar`, `GATE_MIRROR_FORMAT`=4; gate journal `gate-journal.jsonl`; conformance `computeConformance`/`tallyByRule`/`retirementCandidates`) | src/gates.ts, src/gate-journal.ts, src/conformance.ts | **DOCUMENTED** | `gates.md` |
| Sync & graft protocol (`GraftPayload` v8/v15, `exportDelta`, `graftRows`, `batchDedup`, `initSyncIdentity`; `SYNC_PAYLOAD_PROTOCOL_VERSION`=15; v8 row-convergence clock `sync_revision`/`sync_writer`; native-only validation; embedder-mismatch rejection; multi-writer `edgeComponents`/`deletions`/`conceptActivity`/`tombstones`/`restorations`) | src/sync-types.ts, engine.ts | **DOCUMENTED** | `sync-graft.md` |

## Identified parameters (running list)

| Parameter | Value (per model) | Where | Role |
|-----------|-------------------|-------|------|
| `tauAttach` | bge-m3:cls:q8 **.70**; bge-small-en .78; all-MiniLM .72; multilingual .70; hashing .55; fallback .55 | `pU` map + `applyEmbedderDerivedThresholds` | similarity ≥ → attach/dedup |
| `tauAmbiguous` | bge-m3:cls:q8 **.50**; bge-small-en .50; all-MiniLM .50; multilingual .50; hashing .40; fallback .40 | same | ambiguous-fork band lower bound; possible_duplicate_of edge min |
| `edgeSimMin` | bge-m3:cls:q8 **.60**; bge-small-en .70; else .45/.40 | same | `related` edge lower bound |
| `nativeScoreFloor` | bge-m3 .40; bge-small-en .35; default .12 (`W1`) | `Z1`/`pU` | search result filter floor |
| `wi` | 6 | const | top-k candidate window |
| lexical boost `H1` | 1.0 | const `H1` in `j1` | rank boost `score*(1+H1*p)` |
| `W1`/`Z1` default floor | .12 | const | clamp for nativeScoreFloor |
| `reliableSegmentTokens` | bge-m3 768; bge-small-en 380 | `pU` | embedder window segmentation |
| default `limit` | 5 | `search()` | `t.limit ?? 5` (silent truncation) |
| lexical tokenizer | `/[a-z0-9][a-z0-9_-]{2,}/gu` | `Im` in `q1` | Latin-only; Korean query → empty token set → no boost |
| `Ar` | 40 000 | `bF`/`Wm` | response JSON size cap → resultsTruncated/resultsOmitted |
| `nt` | 256 | tool schema | max circle-name length |
| user_version ladder | 0→12 (10 skipped) | `Ff..UT` consts | schema milestone scalar (sole versioning) |
| `supportedSchemaVersion` | 12 | cli.js inspector ×2 (hardcoded) | doctor display + repair preflight cap |
| sync/graft protocol version | 15 (`Gf`) | `graftRows` | export payload version cap (≠ schema) |
| first-block sentinel `zT` | `"schema-12-first-block-migration"` | const | author_agent_id of migrated pins |
| migrated obs id `HT` | `fb-migration:` + sha256(id\0sha256(summary))[:32] | migrateFirstBlockPins | deterministic re-runnable id |
| migrated obs content `FT` | `First Block pin (surface retired 2026-08-02): ` | const | content prefix |
| graph backfill gate | user_version < 1 | runGraphBackfillIfPending | 0→1 milestone (feature-conflated) |
| first-block migration window | [9, 12) → 12 | migrateFirstBlockPins | when conversion runs |
| doctor assessment schema check | `e === 12` | `dW` cli.js | verdict gate (hardcoded) |
| exclusive-lock probe | user_version ±1 | acquireExclusiveOwnership | repair ownership dance |
| contradiction `decision` enum | accept-new / keep-current / dismiss | `memory_resolve` tool schema | required verdict; invalid combos rejected in `resolveContradiction` |
| contradiction status vocab | open / resolved / dismissed | string literals (6+ fns, no enum) | row lifecycle; rows never deleted |
| pair-flag edge types | possible_duplicate_of, extraction_candidate | `Lz` const (@662903) | `memory_edge` flags cleared by `dismissPossibleDuplicate` |
| flag confidence penalty | −0.3, floor 0.1 | `flagContradiction` | concept confidence on dispute |
| flag arousal delta | +3 | `flagContradiction` | dispute activation boost |
| resolve arousal delta | +1 | `resolveContradiction` (verdict only) | mediation activation bump |
| disputed confidence cap | 0.5 | `recomputeNativeConceptProjection` (`u = o ? min(.5, l) : l`) | open contradiction caps concept confidence |
| confidence factor | .6 + .1·(sessions−1) + .2·resolved | same | per-concept confidence multiplier |
| overview detail truncation | 200 (`LT`) | `getOpenContradictions` | `…[truncated]` marker |
| last-confirmed window | 2000 ms | `recomputeNativeConceptProjection` | session-match heuristic for confirmation |
| concept status derivation | `CASE open_count>0 THEN 'disputed' ELSE 'active' END` | recomputeNativeConceptProjection (both branches) | status column is DERIVED, not independently managed |
| anti-guess guard | accept-new + no contradictedObsId + no auto-loser + ≥2 priors + no body → refuse | `resolveContradiction` | body required to supersede an arbitrary prior |
| keep-current prior rule | requires ≥1 live prior predating the correction | same | else refuse ("nothing to keep") |
| `W` (circle marker) | `"*"` | const `W` | reserved global-breadth marker — never a circle; concepts/workstreams/sources/aliases/rename/merge/archive refuse it; `memory_declare circle:'*'` → `skeleton_breadth='global'` |
| `rd` (legacy dest) | `"legacy-star"` | const `rd` | legacy-`*` migration destination base name |
| alias status vocab | `active`, `archived` | `circle_aliases.status` | active = alias/rename target; archived = self-row archive marker; rows never deleted by user ops |
| `listCircles` cap | 20 | `listCircles` | `LIMIT 20`, lastActivity DESC, circle ASC |
| merge resolution enum | `auto` / `forceNew` (default) | `mergeCircle` | auto dedups; forceNew keeps distinct + flags possible_duplicate_of |
| legacy dest suffix | `-2`, `-3`, … | `chooseLegacyStarDestination` | collision-avoidance loop from `rd` |
| gate alias triggers | 3 (insert / update OF to_name,status / delete) | schema DDL | `circle_aliases` mutations bump `gate_meta.generation` |
| alias resolution depth | 1 (single hop) | `resolveCircle` | `a→b→c` does NOT resolve to c; rename/merge repoint keeps graph flat |
| dashboard port | 7373 | `dashboard` CLI (`-p`/`PORT` env) | local HTTP server port (validated 1..65535) |
| dashboard Host allowlist | {`127.0.0.1`,`localhost`,`[::1]`} ± port | `tG` | Host-header gate; anything else → 403; DNS-rebinding defense |
| dashboard snapshot mode | per-request full SQLite backup + unlink | `Hb`/`JZ`/`YZ`/`KZ` | read-only isolation; copy in `monet-dash-*` under `os.tmpdir()` (macOS: `/var/folders/...`, NOT /tmp); 1h stale-dir cleanup; exit cleanup on SIGINT/SIGTERM/uncaughtException |
| retired filter `et` | `status != 'retired'` | const | injected into all concept-scoped dashboard SQL unless `includeRetired=1` |
| source-concept detection `t0` | `source_identity IS NOT NULL OR active_observation_id IS NOT NULL` | counts SQL (+`n0` schema check) | schema-adaptive; legacy fallback `kind='source'` |
| graphDensity formula | `liveEdges * 1.0 / NULLIF(concepts, 0)` | health SQL | edges-per-concept; includes possible_duplicate_of edges (RE-21) |
| sourceBackoff base | 30 000 ms, ×2/failure, cap=refresh interval | `o0` | source retry backoff |
| attempt-events window | 128 | `sourceAttemptEvents` | `ROW_NUMBER() ... rn <= 128` per source |
| `GRAPH_NODE_LIMIT` | 800 | app.js | auto-layout cap; over cap → guard prompt, NO partial simulation |
| clustering consts | K=14, min=40, max=160, MAX_ITER=1500 | app.js | large-graph cluster rendering |
| localStorage schema | `monet-dash:v1`, `LS_SCHEMA_V`=8 | app.js | filter/camera/pin persistence (v8 migration strips poisoned cam_*) |
| graph layout consts | charge `max(-6000,-1600−22n)`, gravity `all?0.007:0.06`, linkDist 130, alphaDecay .015, velDecay .4 | app.js | force-layout tuning |
| source type enum | `repo-md` \| `git-md` | `knowledge_sources.type` CHECK | two registered source kinds |
| writeBack enum | `none` \| `pull-request` (PR only for `github.com` git-md) | `canonicalize`/schema | write-back policy |
| refresh mode | `manual` \| `interval` (CLI default interval, 3600 s) | `QM`/`canonicalize` | auto-sync cadence |
| freshness window | manual 86400 s; interval `max(60, 2×interval)` | `sourceStatus` | fresh/stale cutoff |
| backoff `CP` | base 30 000 ms, ×2/failure, cap = interval | `CP` | failure retry delay |
| jitter `Ww` | `sha256(key).readUInt32BE(0) % (max+1)`, key=`id␀configVer␀fence␀attemptSeq` | `Ww` | deterministic schedule spread |
| initial-delay | `min(30000, 10%·interval)` | `Rm` | first-attempt defer |
| run state enum | scanning/staging/activating/published/cleaning/cleaned/aborted | `source_sync_runs.state` | run lifecycle |
| run result enum | success/failed/partial | `source_sync_runs.result` | terminal result |
| snapshot state enum | staged/active/superseded/aborted | `source_snapshots.state` | snapshot lifecycle |
| source lifecycle | active/tombstoned | `knowledge_sources.lifecycle` | tombstoned ids not reusable |
| content hash prefix `iP` | `monet-src-content/v1:sha256:` | `eg` | per-chunk content id |
| ingest hash domain `nP` | `monet-src-ingest/v1` | `Qm` | ingest-config hash |
| op hash domain `oP` | `monet-src-op/v2` | `Nm` | binding generation |
| content-model version `Zd` | `"v5"` | `Qm`/`scan_config_version` | chunker version gate |
| parse-deadline cap `CS` | 100 000 | `Lt`/`$S` | frontmatter parse iteration cap |
| chunk write_state enum | intent/engine-written/committed/skipped | `source_staged_chunks` | write-back pipeline |
| chunk lifecycle enum | active/superseded/deleted | `source_chunks` | chunk retirement |
| cleanup-item kind enum | retire-absent/reconcile-orphan/quarantine-non-authorizing | `source_cleanup_items` | post-publish cleanup |
| attempt-event kind enum | run/verification/pre-pin-failure/invocation | `source_attempt_events` | status signals |
| removal state enum | retiring/files-revoked/complete | `source_removals` | tombstone removal |
| auth env vars | `MONET_CALLER_ID` + `MONET_PROJECT_ID` | `J4` | server-bound identity (both required) |
| git-md allocator | `sourceStorageDir/git-md/<id>/repository.git` | `canonicalize` | Monet-owned local path |
| transport policy | schemes ⊆ {https,ssh}, hosts | `KM`/`wm` | git-md remote allowlist |
| source-id regex | 1–64 lowercase letters/digits/interior hyphens | `jM`/`WM` | portable id constraint |
| live-run uniqueness | one run per source in scanning/staging/activating/cleaning | partial unique index | single in-flight sync |
| `RuleSeverity` | `advisory` \| `blocking` | gates.ts | failure MODE: advisory injects, blocking denies |
| `RuleScope` | `domain` \| `agent` | gates.ts | domain transfers across models; agent = per-model compensation (carries model_tag) |
| `StageOrigin` | `correction` \| `declaration` \| `import` | gates.ts | how a stage was born |
| `RuleBindingOrigin` | `correction` \| `declaration` \| `projection` \| `import` | gates.ts | how a rule was bound; `projection` has no write path yet |
| `GateJournalMouth` | `host-hook` \| `gate-cli` \| `core-gate` \| `stage-lookup` \| `declare-check` | gate-journal.ts | which surface wrote the journal event |
| `GateJournalClaimType` | `source-observed` \| `parsed` \| `inferred` \| `corroborated` \| `unavailable` | gate-journal.ts | HOW we know what an event claims |
| `GateJournalDisposition` | `silent` \| `stage-hit-no-rules` \| `advisory` \| `deny` \| `overflow` \| `declined:*` | gate-journal.ts | what a governing mechanism did |
| `ConformanceVerdict` | `changed` \| `conformed` \| `breached` \| `no-effect` \| `vacuous` | conformance.ts | §4's verdict vocabulary |
| gate `matcher` | `mechanical` \| `recognized` | gates.ts | gateQuery (pattern fire) vs stageLookup (agent named a stage) |
| `MAX_STAGE_PATTERNS` | 32 | gates.ts | pattern-count cap per stage |
| `STAGE_NAME_MAX_CHARS` | 500 | gates.ts | stage name cap (normalized, UNIQUE) |
| `MODEL_TAG_MAX_CHARS` | 200 | gates.ts | agent-scope model-tag cap |
| `STAGE_LOOKUP_RULES_CAP` | 200 | gates.ts | rules returned by stage_lookup |
| `STAGE_LOOKUP_BODY_CAP` | 6000 | gates.ts | stage_lookup rule-body cap |
| `STAGE_LOOKUP_REASON_CAP` | 1200 | gates.ts | stage_lookup reason cap |
| `STAGE_LOOKUP_OUTLINE_CAP` | 500 | gates.ts | stage_lookup outline cap |
| `STAGE_INDEX_CAP` | 2000 | gates.ts | stage_lookup stage-index cap |
| `DISPUTED_PARENTS_CAP` | 8 | gates.ts | rule-outline disputed-parents cap |
| `GATE_MIRROR_FORMAT` | 4 | gates.ts | gate mirror (sidecar) file format |
| `GATE_JOURNAL_FORMAT` | 1 | gate-journal.ts | journal line schema version |
| `GATE_JOURNAL_MAX_BYTES` | 64 MiB (2x on disk) | gate-journal.ts | journal rotation cap |
| `GATE_JOURNAL_CONTEXT_MAX_CHARS` | 2048 | gate-journal.ts | verbatim context ceiling (else sha256+len) |
| `ROTATE_LOCK_STALE_MS` | 60 000 | gate-journal.ts | rotation-lock staleness clearing |
| blocking-is-declaration-only | `CHECK (severity != 'blocking' OR origin = 'declaration')` | GATE_SCHEMA_SQL | deny power cannot be self-assigned (schema-level) |
| breadth-is-declaration-only | `CHECK (circle != '*' OR origin IN ('declaration','correction'))` | GATE_SCHEMA_SQL | global reach cannot be minted by import/capture |
| agent-scope-implies-tag | `CHECK ((scope = 'agent') = (model_tag IS NOT NULL))` | GATE_SCHEMA_SQL | per-model compensations carry a tag |
| `SYNC_PAYLOAD_PROTOCOL_VERSION` | 15 (changelog 11→15) | engine.ts | graft payload ceiling (the `Gf`=15 unknown, now closed) |
| user_version rung names | 1 graph, 2 temporal, 3 arousal, 4 first_block, 5 sync, 6 source-concept, 7 source-registry, 8 sync-closure, 9 source-ledger, 11 source-file-concept, 12 first-block-retirement (10 skipped) | engine.ts | named ladder rungs |
| `RETIREMENT_PAIR_FLAG_NAMED_MAX` | 3 | engine.ts | pair partners named before "and N more" |
| `PAIR_FLAG_EDGE_TYPES` | `possible_duplicate_of`, `extraction_candidate` | engine.ts | pair-flag set treated alike everywhere |
| sync row-convergence clock | `(sync_revision, sync_writer)` | sync-types.ts | v8 mutable-row convergence (house pattern) |
| `EmbedderMismatchError` | thrown on embedderModelId mismatch | graftRows | cross-space graft rejected, never silently corrupted |

## Stagnation detection

- 3 consecutive runs with 0 new modules/params → switch module (search → migration → circles → contradictions → dashboard).
- Found issues should be re-checked after each @team-monet/monet version bump (source diff).
