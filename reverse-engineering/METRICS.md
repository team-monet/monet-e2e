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
| 2026-08-14 | 10 — living-model ranking (temporal layer + V-A weighting) | 130 (+20: usefulness tau 60d, arousal tau 120d, arousal floor 0.1, arousal weight 0.5, recency half-life 14d, staleAfterMs default 30d, livingModel conceptLimit 5, arousal floor crossover ~276d, cross-session confidence +0.1 cap 1.0, arousal event deltas flag+3/resolve+1/dismiss+0/cross-session-attach+1, merge-carry usefulness-additive+arousal-MAX+fetch_at-MAX, partial-detach no-temporal-carry, RELIABLE_EMBED_TOKENS 280, reliableSegmentTokensOf finite>=1 else 280, tokenIdf clamp max(0,log(N/(1+df))), lexicalOverlap per-observation probe-normalized, span:// URI scheme + bijective parse/format, claude-code anchor L<start>-L<end>, synthesis body-only no-summary) | 32 (+2: RE-31..RE-32) | Temporal layer (last_confirmed_at vs updated_at split, confirmation vs structural-touch), staleness (30d), V-A weighting (usefulness fetch-driven + arousal conflict-driven, each with decay + arousal floor), livingModelScore multiplicative blend (confidence × usefulness × recency × arousal), merge/detach/sync temporal carry, plus companion seams embed-budget/lexical-overlap/spans/synthesis. Documented from readable TS. See `living-model-ranking.md` |
| 2026-08-15 | 14 — statement tracing + embed window guard + lifecycle edges + skeleton mirror (4 modules, readable TS) | 160 (+30: STATEMENT_SLOW_THRESHOLD_MS 1000, STATEMENT_TRACE_SQL_MAX_CHARS 2000, TRACE_FILE_MODE 0o600, MONET_TRACE_SQL env switch, StatementMethod 10 mouths, inflight-<pid>-<seq>.json + slow-queries.jsonl, marker schema v:1+depth+dbPath, NON_LATIN_LETTER_TOLERANCE 0.2, paragraph/sentence boundary regexes, hardCut whitespace pref ws>fit*0.6, joiner +1 token, segmentTokenBudget min(reliable,window)+null-unbounded, window guard tokens>inputWindow + subject content\\|query + storeSource bypass, 3 lifecycle families, 5 births, 4 verdicts, 2 entrances, BATTERY_GATES 4 gates, SUPERSESSION_WALK_CAP 1000, supersession partial unique index, dst_span span://, MATERIALIZE_MANIFEST materialize.json, BEGIN/END markers, 3 mirror stale reasons, skeletonStateHash canonical ordering) | 34 (+2: RE-33..RE-34) | Statement tracing (in-flight marker before-run + slow log after-return; #145 wedge diagnosis) + embed window guard (RELIABLE_EMBED_TOKENS advisory@write/enforced@segmenter; write/query over-window refusal; Latin-script gate 0.2) + lifecycle edges/ratifications (normative substrate, separate append-only tables, 4-gate extraction battery, supersession cycle guard) + skeleton mirror (materialize stale detection). Documented from readable TS. See `statement-trace.md` + `embed-window-guard.md` + `lifecycle-edges.md` + `skeleton-mirror.md` |
| 2026-08-15 | 16 — diagnostics (doctor/repair preflight) + source chunker (2 modules, readable TS) | 181 (+21: MONET_SCHEMA_VERSION=12 single const, MALFORMED_EMBEDDING_SAMPLE_LIMIT 20, safety assessment vocab {missing,safe,unsafe,unknown}, PIN_SOURCES {created,backfilled,migrated}, migration abandon classification {safe,refused,unsupported,unknown}, diagnostic failure reason {locked,not-sqlite,unreadable}, snapshot temp prefix monet-readonly-diagnostic-*, non-Latin sample quotas 3 obs+2 concept, conditional readonly open, DEFAULT_SOURCE_MAX_CHUNKS 100000, MIN_SOURCE_SECTION_BYTES 200, hashSourceDomain NUL+8-byte-BE framing, frontmatter flat-model rules, sourceHeadingAnchor _root/_untitled NFC slug, sourceRef <path>#<anchor>~<occurrence>, documentSequence 1-based post-merge, minimum-merge direction+cap-over-minimum, splitUtf8 code-point iteration, fence atomic fail-closed, quick_check single-ok gate, sqlite open timeout 5000) | 36 (+2: RE-35..RE-36) | `diagnostics.ts` = the `monet doctor`/`repair` embedder-state preflight (safety assessment ladder, #188 snapshot isolation — read-write throwaway copy when no WAL, read-only real file when WAL present, non-Latin scan over 4 populations, migration abandon classification) + report-only lifecycle-edge integrity sweep (RE-35: no operator surface). `source-chunker.ts` = Markdown → deterministic chunks (fail-closed flat frontmatter, ATX-only sections, min-chunk merge, line-boundary segmentation with atomic fences, content/ingest/op hashing, sourceRef). RE-36: splitUtf8 splits by code point not grapheme. See `diagnostics.md` + `source-chunker.md` |
| 2026-08-16 | 18 (+2: render-overview, extract-entities) — 3 docs cross-checked vs readable TS (1 corrected for drift) + 2 new modules documented | 205 (+24) | 38 (+2: RE-37, RE-38) | Run 34 (DIRECTION priority #1 + #2, issues #7 + #8): (1) minified-doc drift cross-check — `search-pipeline.md` + `dedup-resolution.md` verified NO drift (every constant/SQL/`MODEL_PROFILES`≡`pU`/`DEFAULT_MODEL`≡`uU`/`applyEmbedderDerivedThresholds` value-for-value identical vs `retrieval.ts`/`resolution.ts`/`lexical-overlap.ts`/`embedding-onnx.ts`/`engine.ts`); `schema-migration.md` had REAL drift (ladder refactored into NAMED version-gated migrations `GRAPH=1…FIRST_BLOCK_RETIREMENT=12`; "no-op bump" labels 2→3/3→4/5→6/6→7 wrong; corrected in-place); RE-09/RE-10 reconfirmed (`source`). (2) documented `render-overview.ts` (terminal curation renderer; RE-37: no operator surface, S3) + `extract-entities.ts` (entity extraction for `about` edges; RE-38: .ts/.mjs mirror, S4). (3) added `L2-code-fix-queue.md` (11 confirmed bugs severity-ordered). |
| 2026-08-16 (run 35) | 19 (+1: mcp-server wire layer) | 231 (+26) | 40 (+2: RE-39, RE-40) | Run 35: documented `mcp-server.ts` (3 503 lines — the largest core file after engine.ts), the MCP **wire layer** the module docs deliberately left out. Covers the 23-tool roster (17 memory_* + 4 source_* + agent_context + stage_lookup; 21→23 = memory_retire+restore), the size-fit result-shaping layer (RESULT_MAX_CHARS=40 000 whole-payload-omission `ok()` net, iterative JSON.stringify size-fit not count caps, stage_lookup 3-tier omitted-rule recovery outline→ids→count-only), auto-prewarm one-shot (snapshot-before-mutation, consumed-on-success/discarded-on-error), model-tag "one chain" (blank=absent, read-at-call-time), server-bound source auth (never a tool arg), and graceful-shutdown machinery (in-flight quiesce 10 s + referenced-timer barrier 30 s + signal exit codes). New issues RE-39 (truncation-note text dead+duplicated — only `.length` used, never emitted, diverges from ok()'s actual wording) + RE-40 (checkpointNudge deprecated no-op in public opts). See `mcp-server.md` |
| 2026-08-16 (run 38) | 22 (+3: storage, embedding, store-embedder) | 257 (+26) | 41 (+1: RE-41) | Run 38: documented the three remaining undocumented readable-TS modules NOT in the DIRECTION halt list (queued by run 35): `storage.ts` (StoragePort seam + BetterSqlitePort; WAL+busy_timeout 5000 shared topology; StoreBusyError holder-naming via readInflightStatements filtered by dbPath; exclusive-ownership dance for repair with warmSchemaRead + user_version±1 probe; verified repair backup quick_check+chmod 0600+hard-link no-clobber; readStoredEmbedderPin/readStoredVectorPresence read-only peeks), `embedding.ts` (EmbeddingProvider model-adapter seam + 4 per-space flags inputWindow/countTokens/needsLexicalArm/readsOnlyLatinScript; HashingEmbeddingProvider tokenizer-versioned v1 ASCII/v2 Unicode, FNV-1a sign hashing, modelId hashing:dim:tok; cosine/blend/blendWeighted/embToJson/jsonToEmb/isZeroVector/normalize), `store-embedder.ts` (chooseStoreEmbedder three-state startup decision — pinned/legacy/fresh — and the no-silent-downgrade refusal; FreshStoreEmbedderUnavailableError/PinnedStoreEmbedderUnavailableError). New issue RE-41 (cosine() Math.min silently re-opens cross-space compare, latent S4). See `storage.md` + `embedding.md` + `store-embedder.md` |
| 2026-08-16 (run 39) | 24 (+2: repair-cli, materialize-cli) | 275 (+18) | 44 (+3: RE-42, RE-43, RE-44) | Run 39: documented the two CLI modules implicated by the upstream issue batch (JohnOnLee, 2026-08-16). `repair-cli.ts` = `monet doctor`/`repair`/`resegment` recovery surface (backup-first, refuse-loud orchestration of inspectStoredEmbedderState/instantiateEmbedderForPin/MonetCore; resolveTargetAlias → checkProvider → one-way non-Latin guard → recheckNonEnglish under exclusive ownership → migrateEmbeddings + reported-not-thrown resegment). `materialize-cli.ts` = `monet materialize add/remove/list` standing-file skeleton renderer (materialize.json manifest, breadth-disjoint scope, marker-poisoning + same-destination + CAS guards, canonicalSkeletonState hash). Registered 3 findings: RE-42 (repair --target accepts arbitrary id → silent unmeasured repin, S1/source/upstream #15), RE-43 (repair self-deadlock on English-only target, S2/open/upstream #14), RE-44 (materialize renders dirty skeleton body, S2/open/upstream #23). See `repair-cli.md` + `materialize-cli.md` |
| 2026-08-17..18 (runs 40-46) | 24 (unchanged — E2E XFAIL conversions + upstream verification, no new module docs) | 275 (unchanged) | 48 (+4: RE-45, RE-46, RE-47, RE-48) | Runs 40-46: verification loop + upstream triage, no new module documentation. RE-43/RE-44 converted to XFAIL (test33/test34) and CONFIRMED (run 40). Upstream #19/#20 independently verified against `storage.ts` → **RE-45** (memory_fetch hidden writer — unprotected usefulness-bump UPDATE + inline synthesize fail a pure read under contention, S2) + **RE-46** (no `interrupt`/progress handler + `.all()` full-embedding materialization, S2/source) (run 43); RE-45 converted to XFAIL test36 and CONFIRMED (run 44). Upstream #52 triaged against `resolution.ts`/`engine.ts`/`mcp-server.ts` → **RE-47** (`correction-attach` exempts `kind="correction"` in the ambiguous band → mis-attach + false dispute, S2) + **RE-48** (`memory_store` ack drops the target `slug`/`title` the engine already computes → mis-merge invisible, S3), both XFAIL test38 (run 46). Issues 44 → 48. |

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
| Living-model ranking (temporal layer `last_confirmed_at`/`last_confirmed_session_id` + confirmation-vs-touch split; staleness `staleAfterMs`/`getStaleConcepts`/`listStale`; V-A weighting `usefulness_score`/`usefulness_last_fetched_at`/`arousal_score`/`arousal_last_updated_at` + decay + arousal floor; `livingModelScore` blend; `livingModelCard`; merge/detach/sync temporal carry) | src/engine.ts | **DOCUMENTED** | `living-model-ranking.md` |

| Statement tracing (`createStatementTracer`, `readInflightStatements`, `statementTraceEnabled`, in-flight marker `inflight-<pid>-<seq>.json`, slow log `slow-queries.jsonl`, `StatementMethod` 10 mouths; wired into `storage.ts` lock-contention holder naming) | src/statement-trace.ts, src/storage.ts | **DOCUMENTED** | `statement-trace.md` |
| Embed budget & window guard (`RELIABLE_EMBED_TOKENS`, `reliableSegmentTokensOf`, `segmentTokenBudget`, `segmentObservation`, `hardCut`, `nonLatinLetterShare`, `assertWithinEmbedderWindow`, `assertEmbedderReadsScript`, `ContentExceedsEmbedderWindowError`) | src/embed-budget.ts, src/observation-segmenter.ts, src/script-gate.ts, src/engine.ts | **DOCUMENTED** | `embed-window-guard.md` |
| Lifecycle edges & ratifications (`addLifecycleEdge`, `recordRatification`, `classifyRatificationPair`, `assertBatteryShape`, `supersessionCycle`, `ungovernableReason`, `getLifecycleEdges`, `walkDerivation`, `getRatifications`; `lifecycle_edges`+`ratifications` tables) | src/lifecycle-edges.ts | **DOCUMENTED** | `lifecycle-edges.md` |
| Skeleton mirror (`skeletonStateHash`, `inspectSkeletonMirrors`, `hasCoveringSkeletonSurface`, `MirrorStaleReason`) | src/skeleton-mirror.ts | **DOCUMENTED** | `skeleton-mirror.md` |
| Diagnostics — embedder-state preflight (`inspectStoredEmbedderState`, `assess`, `inspectPin`/`inspectPopulations`/`inspectMigration`/`inspectNonLatin`, `StoredEmbedderStateDiagnosticError`; `inspectLifecycleEdgeIntegrity`) + live-vector inventory (`inspectLiveEmbeddingPopulation(s)`, `parseFiniteEmbeddingJson`, `LIVE_EMBEDDING_SQL`) | src/diagnostics.ts, src/embedding-state.ts, src/schema-version.ts | **DOCUMENTED** | `diagnostics.md` |
| Source chunker (`chunkSourceText`, `parseFrontmatter`, `sectionsFromMarkdown`, `mergeUndersizedSections`, `segmentSection`/`splitUtf8`, `hashSourceDomain`, `computeSourceIngestFingerprint`/`computeSourceContentHash`/`computeSourceOperationId`, `sourceHeadingAnchor`/`makeSourceRef`/`deriveSourceFileTitle`) | src/source-chunker.ts | **DOCUMENTED** | `source-chunker.md` |
| Render overview / curation workbench (`renderOverview`) | src/render-overview.ts | **DOCUMENTED** | `render-overview.md` |
| Entity extraction (`extractEntities`, `singularize`, `stripKoreanParticle`, `normalizeToken`, `KOREAN_PARTICLES`, `LEXICON`, `STOPWORDS`) | src/extract-entities.ts (+ `.mjs` mirror) | **DOCUMENTED** | `extract-entities.md` |
| MCP wire layer (`registerMonetCoreTools` 23-tool roster, `ok()`/`err()`/`clip()` result shaping, `fitObjectArray`/`fitStringArray`/`fitRecallEnvelope`/`fitOverviewEnvelope`, `wrapSuccess` auto-prewarm, `capturePrewarmSnapshot`, `buildPrewarmBlock`, `deriveOptsFromEnv`, `withShutdownBarrier`/`getInFlightTracker` graceful shutdown) | src/mcp-server.ts | **DOCUMENTED** | `mcp-server.md` |
| Storage port & driver (`StoragePort` seam, `BetterSqlitePort`, `storeContentionError`/`StoreBusyError`, `acquireExclusiveOwnership`/`releaseExclusiveOwnership`, `createVerifiedBackup`/`publishVerifiedBackup`, `readStoredEmbedderPin`, `readStoredVectorPresence`) | src/storage.ts | **DOCUMENTED** | `storage.md` |
| Embedding provider seam & vector math (`EmbeddingProvider`, `EmbeddingThresholds`, `validateEmbeddingProviderOutput`, `HashingEmbeddingProvider`, `HASHING_TOKENIZERS`, `cosine`/`blend`/`blendWeighted`/`embToJson`/`jsonToEmb`/`isZeroVector`/`normalize`/`hash32`) | src/embedding.ts | **DOCUMENTED** | `embedding.md` |
| Store embedder selection (`chooseStoreEmbedder`, `requireSemanticOrExplicitLexical`, `FreshStoreEmbedderUnavailableError`, `PinnedStoreEmbedderUnavailableError`) | src/store-embedder.ts | **DOCUMENTED** | `store-embedder.md` |
| Repair / doctor / resegment CLI (`registerRecoveryCommands`, `runDoctor`, `runRepair`, `applyRepair`, `resolveTargetAlias`, `checkProvider`, `reconcileProviderWithStore`, `ensureInspectableForRepair`, `recheckNonEnglish`, `defaultRecoveryDependencies`) | src/repair-cli.ts | **DOCUMENTED** | `repair-cli.md` |
| Materialize CLI (`registerMaterializeCommands`, `materializeOne`, `deliveredMembers`, `renderSkeletonBlock`, `canonicalSkeletonState`, `findSkeletonBlock`, `readMaterializeManifest`, `freshnessFromStore`) | src/materialize-cli.ts | **DOCUMENTED** | `materialize-cli.md` |

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
| `USEFULNESS_DECAY_TAU_DAYS` | 60 | engine.ts | usefulness decay tau (fetch clock) |
| `AROUSAL_DECAY_TAU_DAYS` | 120 | engine.ts | arousal decay tau (spike clock) |
| `AROUSAL_FLOOR_FRAC` | 0.1 | engine.ts | arousal decay floor: ≥10% of cumulative arousal survives idle |
| `AROUSAL_WEIGHT_LIVING` | 0.5 | engine.ts | arousal boost factor in livingModelScore |
| recency half-life | 14 days (`exp(-ageDays/14)`) | livingModelScore | inline magic number (RE-31) |
| `staleAfterMs` | default 30 days (constructor opt) | engine.ts | staleness window; `COALESCE(last_confirmed_at, updated_at)` clock |
| livingModel `conceptLimit` | 5 | overview() | living-model slice cap |
| livingModel sort | score DESC, tiebreak `id ASC` | overview() | deterministic ordering |
| arousal floor crossover | ~276 d (`tau×ln(1/0.1)`) | derived | floor dominates pure decay past here |
| cross-session attach confidence | +0.1, cap 1.0 | attach path | damping: same-session attach is +0 |
| arousal event deltas | flag +3 / resolve accept-new +1 / keep-current +1 / dismiss +0 / cross-session attach +1 | engine.ts | spike sites (test A.1) |
| merge-carry temporal rule | usefulness additive, `usefulness_last_fetched_at` MAX, arousal MAX, `arousal_last_updated_at` MAX, `last_confirmed_at` MAX (+session) | mergeConceptInto | nothing lost (test A.4) |
| partial-detach carry | NO temporal fields carried (moved obs = old evidence); full split `lca = min(pre, max(created_at remaining))` | detach | source can't evade stale-review |
| `RELIABLE_EMBED_TOKENS` | 280 | embed-budget.ts | reliable retrieval-size floor (advisory at write, enforced in segmenter) |
| `reliableSegmentTokensOf` | honour finite ≥1 else 280 | embed-budget.ts | ONE shared validation (PR #171) |
| `tokenIdf` | `max(0, log(conceptCount/(1+df)))` | lexical-overlap.ts | clamped at zero — ubiquitous token neutral (PR #156) |
| `lexicalOverlap` unit | per-observation, maxed; normalized by PROBE | lexical-overlap.ts | union would cost small concepts 71.9% of evidence |
| span URI scheme | `span://host/session#anchor`, host unescaped, session+anchor percent-encoded, parse/format bijective | spans.ts | provenance-edge address; compared by string equality |
| `claude-code` anchor | `L<start>-L<end>` 1-based inclusive JSONL lines | spans.ts | only interpreted host; others opaque |
| synthesis shape | body only, NO summary | synthesis.ts | summary reads like an answer (#232) |

| `STATEMENT_SLOW_THRESHOLD_MS` | 1 000 | statement-trace.ts | slow-log threshold |
| `STATEMENT_TRACE_SQL_MAX_CHARS` | 2 000 | statement-trace.ts | SQL clip (marker + slow log) |
| `TRACE_FILE_MODE` | `0o600` | statement-trace.ts | both trace files, open + inherited fchmod |
| `MONET_TRACE_SQL` | `"1"` | statement-trace.ts | single on/off switch, off by default |
| `StatementMethod` | prepare, run, get, all, exec, pragma, transaction, immediateTransaction, backup, backupVerify | statement-trace.ts | 10 traced SQL mouths |
| in-flight marker name | `inflight-<pid>-<connectionSeq>.json` | statement-trace.ts | one per connection; reader globs |
| slow-log name | `slow-queries.jsonl` | statement-trace.ts | append-only, write-only (RE-33) |
| marker schema | `v:1` + pid/method/startedAt/depth/sql + optional dbPath | statement-trace.ts | reader-parsed record |
| `NON_LATIN_LETTER_TOLERANCE` | 0.2 | script-gate.ts | Latin-only gate (share of non-Latin letters) |
| paragraph boundary | `/\n\s*\n+/u` | observation-segmenter.ts | finest claim boundary |
| sentence boundary | `/(?<=[.!?。！？])\s+|\n+/u` | observation-segmenter.ts | secondary boundary |
| hardCut whitespace preference | `ws > fit * 0.6` | observation-segmenter.ts | word-boundary cut over mid-word |
| joiner cost | +1 token per `\n` join | observation-segmenter.ts | segment never over budget |
| `reliableSegmentTokensOf` rule | finite && >= 1 else 280 | embed-budget.ts | one shared validation |
| `segmentTokenBudget` | `min(reliable, window)`, null when unbounded | observation-segmenter.ts | per-provider segment budget |
| window-guard predicate | `tokens > inputWindow` | engine.ts | refuse before any embed |
| `ContentExceedsEmbedderWindowError` | subject `content`/`query`, `tokens`/`maxInputTokens`/`reliableTokens` | engine.ts | surfaced refusal + remedy |
| storeSource window bypass | skip guard (no author to retry) | engine.ts | chunk budget lives in the chunker |
| `LifecycleEdgeFamily` | derivation, provenance, supersession | lifecycle-edges.ts | 3 normative relation families |
| `LifecycleEdgeBirth` | correction, declaration, projection, ratification, extraction | lifecycle-edges.ts | 5 birth acts |
| `RatificationVerdict` | approve, reject, retire, re-ratify | lifecycle-edges.ts | 4 human verdicts |
| `RatificationEntrance` | extraction, declaration | lifecycle-edges.ts | how a verdict entered (#142) |
| `BATTERY_GATES` | generates, covers, transfers, exits | lifecycle-edges.ts | 4-gate extraction battery |
| `SUPERSESSION_WALK_CAP` | 1000 | lifecycle-edges.ts | cycle-walk refusal cap |
| supersession uniqueness | partial unique index on `(src_concept_id)` | lifecycle-edges.ts | one direct successor per rule |
| `dst_span` format | `span://` URI (parseSpan-validated) | lifecycle-edges.ts | provenance destination |
| `MATERIALIZE_MANIFEST` | `materialize.json` | skeleton-mirror.ts | standing-surface registry |
| BEGIN/END markers | `<!-- BEGIN monet:skeleton -->` / `<!-- END monet:skeleton -->` | skeleton-mirror.ts | block hash span |
| `MirrorStaleReason` | block-missing, block-edited, store-moved | skeleton-mirror.ts | 3 stale causes |
| `skeletonStateHash` ordering | code-unit `<`/`>`, no whitespace, exact key order | skeleton-mirror.ts | canonical hash |
| `MONET_SCHEMA_VERSION` | 12 (single named const) | schema-version.ts | latest build-servable schema (readable source; RE-09 is a dist-bundle duplicate concern) |
| `MALFORMED_EMBEDDING_SAMPLE_LIMIT` | 20 | embedding-state.ts | bounded deterministic malformed-vector sample (count stays exact) |
| safety assessment vocab | missing / safe / unsafe / unknown | diagnostics.ts | `assess()` verdict ladder |
| `PIN_SOURCES` | created / backfilled / migrated | diagnostics.ts | valid `embedder_pin_source` values |
| migration abandon classification | safe / refused / unsupported / unknown | diagnostics.ts | `inspectMigration().abandon` |
| diagnostic failure reason | locked / not-sqlite / unreadable | diagnostics.ts | `StoredEmbedderStateDiagnosticError` (by SQLite error code) |
| snapshot temp prefix | `monet-readonly-diagnostic-*` under `os.tmpdir()` | diagnostics.ts | no-WAL throwaway copy for read-only diagnosis |
| non-Latin sample quotas | 3 observation ids + 2 concept ids | diagnostics.ts | per-population samples (not first-come) |
| conditional readonly open | `readonly: snapshotDir === undefined` | diagnostics.ts | copy read-write (no WAL) / real file read-only (WAL present) |
| integrity gate | `PRAGMA quick_check` → single `ok` row | diagnostics.ts | else `{status:"failed"}`; repair refuses to mutate |
| sqlite open opts | `timeout: 5000`, `fileMustExist: true` | diagnostics.ts | diagnosis connection |
| `DEFAULT_SOURCE_MAX_CHUNKS` | 100 000 | source-chunker.ts | per-file output cardinality budget |
| `MIN_SOURCE_SECTION_BYTES` | 200 | source-chunker.ts | undersized-section merge floor (inclusive) |
| `hashSourceDomain` framing | domain + NUL + 8-byte BE length prefix per field | source-chunker.ts | unaliasable field-vector hash |
| frontmatter flat-model | `---`/`...` delims; flat `key: value` only; flat scalar list any-key (v4); `rawValueWasQuoted` gate | source-chunker.ts | fail-closed; block/nested/flow-map refused |
| `sourceHeadingAnchor` | `_root` (empty) / NFC-lowercase slug / `_untitled` fallback | source-chunker.ts | deterministic heading identity |
| `sourceRef` | `<encoded path>#<encoded anchor>~<occurrence>` | source-chunker.ts | path-local reference |
| `documentSequence` | 1-based, assigned at emission time (post-merge) | source-chunker.ts | true document-order key |
| minimum-merge direction | forward (drop identity) / backward at EOF (keep identity); cap wins over minimum | source-chunker.ts | undersized-section merge |
| `splitUtf8` | code-point iteration, `[]` on over-budget single cp | source-chunker.ts | grapheme-unsafe (RE-36) |
| fence atomicity | fence never split; over-budget fence → fail-closed `chunk-budget-exceeded` | source-chunker.ts | segmentation invariant |

| `renderOverview` default width | 84 | render-overview.ts | terminal wrap width (`opts.width ?? 84`) |
| ANSI truncation | `…` at `width-1`, SGR codes preserved | render-overview.ts | visible-length-aware truncate |
| `EntityKind` | `path` \| `lib` \| `id` \| `err` \| `noun` | extract-entities.ts | entity type; anchors `about` edges |
| entity weight | structural 3 / lib 2 / noun 1 | extract-entities.ts | `rarity × kindBoost` edge weighting |
| entity key form | `${kind}:${surface}` — noun/lib lowercased, path/id/err case-preserved | extract-entities.ts | join column for `about` edges |
| `LEXICON` | 42 canonical lib names, null-prototype | extract-entities.ts | `lib` entities (constructor-crash-safe) |
| structural regexes | PATH_FILE/PATH_SLASH/ERRCODE/CAMEL/SNAKE/DOTTED (paths before dotted) | extract-entities.ts | pass 1 (weight 3, spans stripped) |
| `WORD` | `/[a-z][a-z0-9]*/g` (Latin-only) | extract-entities.ts | lexicon scan over lowercased text |
| word segmentation | `Intl.Segmenter(undefined,{granularity:"word"})` (full ICU) | extract-entities.ts | non-Latin nouns (#187); runtime-stable not cross-runtime |
| NFC normalize | before noun pass | extract-entities.ts | composed vs decomposed = one key (PR #189) |
| noun split | `/[^\p{L}\p{N}\p{M}]+/u` | extract-entities.ts | punctuation-bearing ICU words (PR #189) |
| `HAS_LETTER` | `/\p{L}/u` | extract-entities.ts | drop numeric-only tokens |
| `tooShort` | length < 2 | extract-entities.ts | script-neutral floor (was 3, PR #189) |
| `STOPWORDS` | English fn words + code chatter + 2-letter + non-Latin JP/KR/ZH | extract-entities.ts | never entities |
| `KOREAN_PARTICLES` | 36 entries | extract-entities.ts | closed-class 조사 |
| `stripKoreanParticle` | longest-match, `len - plen >= 2` guard | extract-entities.ts | 주식/주식을/주식은 → one entity |
| `KOREAN_PARTICLE_SET` | whole-token particle check | extract-entities.ts | isolate "에서" etc. |
| `HANGUL_ONLY` | `/^\p{Script=Hangul}+$/u` | extract-entities.ts | script dispatch → Korean strip |
| `singularize` | ≤3 no-op; `(us\|is\|os\|as\|ss)$` no-op; `ies→y`; `(sses\|shes\|ches\|xes\|zes)$` strip 2; `s` strip 1 | extract-entities.ts | English plural stripping |
| `RARE_DF_MAX` | 5 | engine.ts | rare structural anchor alone justifies `about` edge |
| `EDGE_MIN_STRENGTH` | 2.0 | engine.ts | else summed `rarity×kindBoost` must reach this |
| `strongAlone` | `kind !== "noun" && df <= RARE_DF_MAX` | engine.ts | hub-gate bypass for rare structural |
| `isHubDf` | df vs concept-count hub threshold | engine.ts | skip `about`-edge only (keep `concept_entities` row + df) |
| `.mjs` mirror | byte-for-byte `extractEntities` duplicate, mirror-identity test | extract-entities.mjs | plain-node `scrub-db.mjs` re-extraction |

| `MONET_SERVER_INSTRUCTIONS` | (injected system prompt) | mcp-server.ts | agent_context-first / stage_lookup-before-acting / search→fetch / store-vs-declare / checkpoint-as-it-happens |
| `RESULT_MAX_CHARS` | 40 000 | mcp-server.ts | hard ceiling on any serialized tool result; `ok()` whole-payload-omission net |
| `FETCH_MAX_OBS` | 20 | mcp-server.ts | most-recent observations returned by `memory_fetch` |
| `FETCH_OBS_MAX_CHARS` | 1 200 | mcp-server.ts | per-observation cap |
| `FETCH_BODY_MAX_CHARS` | 6 000 | mcp-server.ts | concept body cap |
| `FETCH_CONTRADICTION_MAX_CHARS` | 400 | mcp-server.ts | per-open-contradiction detail cap |
| `FETCH_CONTRADICTIONS_MAX` | 5 | mcp-server.ts | newest-first open-contradiction entries per fetch |
| `FETCH_OUTLINE_MAX_ENTRIES` | 200 | mcp-server.ts | source-concept outline upper bound (cheap size-fit loop bound) |
| `CIRCLE_NAME_MAX_CHARS` | 256 (exported) | mcp-server.ts | caller-controlled circle echo bound before writes |
| `WRITE_ACK_LIST_MAX` | 25 | mcp-server.ts | ack list fit (e.g. impeachedPrincipleIds) |
| `STAGE_ACK_PATTERNS_MAX` | 8 | mcp-server.ts | stage-view pattern cap in write ack |
| `STAGE_ACK_TOKEN_MAX_CHARS` | 80 | mcp-server.ts | per-pattern token clip |
| `STAGE_ACK_PATTERN_MAX_CHARS` | 300 | mcp-server.ts | per-pattern clip |
| `WRITE_ACK_TEXT_MAX_CHARS` | 1 000 | mcp-server.ts | stage-name clip in write ack |
| `ANOMALOUS_STORE_RESOLUTION_MODES` | ambiguous-fork \\| fork-signal \\| blur-duplicate \\| species-fork \\| stage-fork | mcp-server.ts | resolution modes surfaced as anomalous in store ack |
| `PREWARM_BLOCK_MAX_CHARS` | 2 500 | mcp-server.ts | prewarm block budget |
| `STAGE_INDEX_PREWARM_MAX_SHOWN` | 15 | mcp-server.ts | stage-recognition cue name cap |
| `STAGE_INDEX_PREWARM_LINE_MAX_CHARS` | 800 | mcp-server.ts | cue line's own budget (incremental fit, whole-line-drop fix) |
| `STAGE_INDEX_PREWARM_TAIL_MARGIN_CHARS` | 20 | mcp-server.ts | "+K more" tail headroom |
| `SHUTDOWN_BARRIER_DEADLINE_MS` | 30 000 | mcp-server.ts | referenced-timer shutdown barrier deadline |
| `IN_FLIGHT_QUIESCE_DEADLINE_MS` | 10 000 | mcp-server.ts | in-flight tool-call drain deadline |
| `SIGNAL_EXIT_CODE` | SIGINT 130 / SIGTERM 143 | mcp-server.ts | 128+signal exit-code convention |
| `MONET_NO_AUTOPREWARM` | `"1"` | mcp-server.ts | disable auto-prewarm |
| `MONET_CALLER_ID`+`MONET_PROJECT_ID` | both required | mcp-server.ts | server-bound source auth identity |
| `MONET_MODEL_TAG` | blank = absent | mcp-server.ts | agent-scope compensation model tag (trim+blank→undefined) |
| `checkpointNudge` | deprecated no-op | mcp-server.ts | RE-40 dead API surface in RegisterMonetCoreToolsOpts |

| `journal_mode` | `WAL` | storage.ts | shared MCP-server + CLI topology |
| `busy_timeout` | 5 000 ms | storage.ts | contention wait budget |
| exclusive probe | `user_version` ±1 (INT32_MAX 2 147 483 647 guard) | storage.ts | reversible real write to retain the exclusive lock |
| `locking_mode` | `EXCLUSIVE` (acquire) / `NORMAL` (release) | storage.ts | repair ownership dance |
| `warmSchemaRead` | `SELECT name FROM sqlite_schema LIMIT 1` | storage.ts | real page access before/after mode switch |
| backup partial name | `.<name>.partial-<pid>-<uuid>` | storage.ts | per-call unique, cleaned on any failure |
| backup mode | `chmod 0600` | storage.ts | published backup file |
| `quick_check` gate | single `ok` row | storage.ts | else `VerifiedBackupVerificationError` |
| backup publish | hard-link (`link`), EEXIST → refuse | storage.ts | atomic + no-clobber (vs rename) |
| peek open | `readonly: true, fileMustExist: true` | storage.ts | no create/migrate/journal-mode change |
| holder filter | `readInflightStatements(dirname).filter(h => h.dbPath === dbPath)` | storage.ts | multi-store directory safety |
| `HASHING_TOKENIZER_VERSION` | 2 | embedding.ts | fresh-default tokenizer |
| hashing `dim` default | 256 | embedding.ts | vector width |
| hashing `modelId` | `hashing:dim=<dim>:tok=<ver>` | embedding.ts | vector-space identity for graft rejection |
| hashing `tauAttach` / `tauAmbiguous` | `.55` / `.40` | embedding.ts | lexical cosine bands (looser than semantic) |
| feature weights | word 1.0, char-trigram 0.5 | embedding.ts | hashing features |
| sign hashing | `(h & 1) === 0 ? +1 : -1` | embedding.ts | collision-bias reduction |
| `hash32` | FNV-1a (offset 0x811c9dc5, prime 0x01000193) | embedding.ts | feature → bucket |
| `cosine` length | `Math.min(a.length, b.length)` | embedding.ts | dot over common prefix (RE-41) |
| `normalize` zero-guard | `Math.sqrt(mag) \|\| 1` | embedding.ts | all-zero stays all-zero |
| tokenizer v1 | `[a-z0-9\s]` strip (ASCII-only) | embedding.ts | resurrected for old pinned stores |
| tokenizer v2 | `[^\p{L}\p{N}\s]` strip (Unicode `u`) | embedding.ts | keeps Korean/CJK/Cyrillic |
| pin source | `sync_meta.embedder_model_id` (singleton row) | store-embedder.ts | durable embedder identity |
| vector presence | `observations` any row OR `concepts` non-null `embedding` | store-embedder.ts | `true`/`false`/`null` |
| `MONET_EMBEDDER` | `onnx` (default) \| `hashing` (explicit lexical opt-in) | store-embedder.ts | embedder selection env |
| empty-store recovery | `readStoredVectorPresence === false` | store-embedder.ts | pin-load failure defers to engine re-pin |

| `RECOVERY_SCHEMA` | `monet.recovery.v1` | repair-cli.ts | doctor/repair JSON envelope schema |
| `PROBE_TEXT` | `"Monet embedding-provider recovery preflight"` | repair-cli.ts | provider preflight probe input |
| repair backup path | `<dir>/backups/monet-before-repair-<UTC>-<uuid>.db` | repair-cli.ts | verified backup destination |
| repair modes | `target` \\| `resume` \\| `abandon` (exactly one) | repair-cli.ts | `selectMode` |
| apply/yes coupling | `--apply` requires `--yes`; `--yes` only with `--apply` | repair-cli.ts | repair never prompts |
| `resolveTargetAlias` cases | `onnx` / `hashing` / blank / `dim:` prefix; else verbatim (RE-42) | repair-cli.ts | --target → model id |
| one-way non-Latin guard | `provider?.readsOnlyLatinScript === true` + `--accept-non-latin-loss` | repair-cli.ts | refuse English-only move stranding non-Latin rows |
| `guardedMode` | `target` OR (`resume` && migration `active` && `rewriteProgress === "not-started"`) | repair-cli.ts | guard also covers not-started resume |
| `recheckNonEnglish` | built only when `guardedMode && targetIsEnglishOnly && !acceptNonLatinLoss` | repair-cli.ts | re-reads non-Latin count under exclusive ownership |
| resegment-after-migration | reported, not thrown; runs outside migration transaction; idempotent | repair-cli.ts | pre-#155 granularity fix in the same command |
| `BEGIN_MARKER` / `END_MARKER` | `<!-- BEGIN monet:skeleton` / `<!-- END monet:skeleton -->` | materialize-cli.ts | managed-block span (hash span = first BEGIN byte → final `>` byte) |
| `MaterializeScope` | `"global"` \\| `{ circle: <name> }` (circle `*` refused) | materialize-cli.ts | surface scope |
| `MaterializeFreshness` | `fresh` / `stale` / `block-missing` / `never-materialized` | materialize-cli.ts | `materialize list` states |
| `DeliveredMember` | `{ conceptId, species: principle\\|preference, body, breadth: global\\|local }` | materialize-cli.ts | breadth-disjoint delivery (global file vs project file) |
| `canonicalSkeletonState` | sha256 of canonical JSON: conceptId-sorted, keys `conceptId,body,breadth`, no whitespace | materialize-cli.ts | mirror-stale comparison hash |
| materialize manifest | `<storeHome>/materialize.json`; `materialized` key = raw absolute path (never normalized) | materialize-cli.ts | cross-package registry/manifest |
| materialize write CAS | best-effort byte-snapshot compare-and-swap before rename (surface + registry) | materialize-cli.ts | refuse concurrent edit, don't clobber |
| materialize errors | `MaterializeCliError` / `RegistryConflict` / `MarkerCollision` / `DestinationAlias` / `LossyDecode` | materialize-cli.ts | refusal vocabulary |

## Stagnation detection

- 3 consecutive runs with 0 new modules/params → switch module (search → migration → circles → contradictions → dashboard).
- Found issues should be re-checked after each @team-monet/monet version bump (source diff).
