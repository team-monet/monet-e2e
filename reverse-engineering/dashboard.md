# Monet Dashboard — server + client architecture (module 6)

> Reverse-engineering run 16 (2026-08-13). Source: installed 1.6.1
> (`/Users/codalee/.local/share/monet-node22/lib/node_modules/@team-monet/monet/dist/`,
> cli.js bundle). Verified LIVE against an empty store and the E2E test store
> (`-d ~/.monet-test`, 75 MB, ~990 concepts). All findings E2E/live-confirmed
> unless marked `[source-only]`.

## What this is

`monet dashboard` (alias: the `dashboard` CLI command) serves a **local-only
read-only web dashboard**: a vanilla-JS + Canvas SPA (no frameworks, no CDN)
that renders the memory store as a force-directed graph + tables
(concepts/entities/timeline/sources/health). It has **zero write endpoints** —
every route is a read.

Files (dist/dashboard/):
| File | Size | Role |
|------|------|------|
| `index.html` | 9.7 KB | SPA shell: topbar (circle selector, search, refresh), statbar, left rail (kind chips, flags, sliders), tabs, graph canvas, detail panel |
| `app.js` | 157 KB | client logic (constants, fetch, filters, force layout, tables, timeline, health, localStorage persistence) |
| `style.css` | 27 KB | styling |

## Server wiring (cli.js bundle)

CLI registration (`Ar.command("dashboard")`):
- `-p, --port <number>` default `7373`; `PORT` env overrides; validated
  `1..65535` (invalid → error + exit 1).
- `-d, --dir <path>` → sets `process.env.MONET_STORAGE_DIR` (same override
  `Cs()` honors for the rest of the CLI; `-d` then governs everything).
- Action: `startDashboard(port)`.

Module exports (bundle module `c0`):
`SQL: Ue, computeSourceSchedule: a0, conceptsHasSourceColumns: n0,
deriveSourceStatus: i0, sourceBackoffMs: o0, startDashboard: rG,
terminalOutcomes: s0`.

### Snapshot-isolation design (the core architecture)

The dashboard **never opens the live DB for queries**. Every API request:

1. `Hb()` — creates a fresh point-in-time copy of the store via
   better-sqlite3 `backup()`:
   - live DB opened `{readonly: true, fileMustExist: true}` (opening the live
     DB read-only is the only contact the dashboard has with it)
   - copied to `snap-<Date.now()>-<rand>.db` inside a per-server temp dir
     `Gu = mkdtempSync(join(os.tmpdir(), "monet-dash-"))`
   - **`os.tmpdir()` on macOS resolves to `$TMPDIR` → `/var/folders/...`,
     NOT `/tmp`** (verified live: server's snapshot dir was
     `/var/folders/v2/.../T/monet-dash-otrboo`).
2. Queries are run against the snapshot with `_t()` — a read-only
   `new better-sqlite3(path, {readonly:true})` + `prepare(sql).all()` helper.
3. `finally { unlinkSync(snapshot) }` — the copy is deleted after EVERY call.

Stale-temp hygiene (at module init): scans `os.tmpdir()` for `monet-dash-*`
dirs other than its own and removes any older than 1 hour.

Exit hygiene: `rmSync(Gu, {recursive, force})` on `exit`, `SIGINT`,
`SIGTERM`, and `uncaughtException` (verified: SIGINT removed the temp dir).

Consequences:
- **Consistency**: each response is a consistent point-in-time read (SQLite
  backup = WAL-consistent), never a torn read across tables.
- **No lock contention**: queries never hold the live DB open.
- **Per-request cost = full DB copy** (see RE-20 for measured numbers).

### HTTP server

`http.createServer` listening on **`127.0.0.1` only** (never `0.0.0.0`).
- **Host-header allowlist** `tG(host, port)`: strips `:\d+$`, lowercases,
  accepts ONLY `127.0.0.1`, `localhost`, `[::1]` (with or without the port).
  Any other Host → `403 {"error":"Forbidden: invalid Host header"}` (verified:
  `evil.example.com`, `127.0.0.2` → 403; `localhost:7399`, `[::1]` → pass).
  This is a solid DNS-rebinding defense.
- No CORS headers anywhere → browsers can't read cross-origin; and since all
  endpoints are read-only, even a no-cors blind POST/GET has no state-changing
  effect (no CSRF surface).
- Routes:
  | Path | Handler | Notes |
  |------|---------|-------|
  | `/`, `/index.html` | `Fb` static | allowlist `eG = {index.html, app.js, style.css}`; MIME `QZ`; `Cache-Control: no-cache, no-store, must-revalidate` (verified) |
  | `/app.js`, `/style.css` | `Fb` static | same |
  | `/api/graph[?includeRetired=1]` | `JZ` | full graph payload (below) |
  | `/api/entities[?includeRetired=1]` | `YZ` | `{entities, links}` |
  | `/api/sources` | `KZ` | source registry + sync state |
  | anything else | — | `404 {"error":"Not found","pathname":...}` (verified) |
- Handler errors → `500 {"error":"internal error"}` + console.error.
- On listen: prints banner (`Monet Dashboard http://127.0.0.1:<port>`,
  `Store: <db path>`) then **auto-opens the browser**: darwin → `open <url>`,
  win32 → `cmd /c start "" <url>`, else `xdg-open <url>` (wrapped in
  try/catch; execFile is async, failure is silent). Verified live via a fake
  `open` shim on PATH (`FAKE_OPEN_SKIP: http://127.0.0.1:7399`).

### Retired-hiding constant

`et = "status != 'retired'"` — injected into nearly every concept-scoped query
unless `includeRetired=1`. Retired concepts disappear from: concepts list,
live edges (via JOIN), counts, health, circle aggregates, entity links.
`includeRetired=1` removes the filter (verified: 990 → 992 concepts,
dirty 929 → 931 on the E2E store — the store holds 2 retired concepts).

## API payloads

### `/api/graph` → `JZ(includeRetired)`

- No DB at all → `VZ()`: empty shape `{generatedAt, counts:{all 0},
  health:{avgConfidence:null, graphDensity:null}, circles:[], aliases:[],
  concepts:[], observations:[], edges:[], contradictions:[], sessions:[],
  revisionsCount:[]}` (verified against empty store).
- Otherwise (from snapshot, ~15 queries):
  - `concepts` — full node rows: `id, slug, title, kind, status, confidence,
    circle, support_count, version, dirty, usefulness_score, created_at,
    updated_at, last_confirmed_at, source_refs, aliases, body`
    ORDER BY updated_at DESC (verified shape).
  - `observations` — `id, content, kind, circle, concept_id, session_id,
    author_agent_id, created_at, source_refs` ORDER BY created_at DESC.
  - `edges` — `id, src_id, dst_id, type, weight, origin, count, scope,
    created_at, last_reinforced_at`, JOINs concepts for the retired filter,
    `WHERE dismissed_at IS NULL`, ORDER BY weight DESC.
  - `contradictions` — full rows ORDER BY detected_at DESC.
  - `sessions`, `revisionsCount` (per-concept revision count + maxVersion),
    `aliases` (from_name, to_name, status).
  - `counts` — 12 subselects (shape verified live):
    `concepts, sourceConcepts, observations, edgesLive, edgesDismissed,
    entities, sessions, contradictionsOpen, contradictionsResolved, disputed,
    dirty, possibleDuplicatePairs`.
    - `sourceConcepts` detection is **schema-adaptive**: if the concepts table
      has BOTH `source_identity` and `active_observation_id` columns
      (`n0()`/`conceptsHasSourceColumns`) → source = `source_identity IS NOT
      NULL OR active_observation_id IS NOT NULL` (`t0`); else legacy
      `kind = 'source'`. (E2E store: schema has the columns, sourceConcepts 0.)
    - `edgesLive`/`possibleDuplicatePairs` JOIN concepts to honor the retired
      filter in the new schema path (not in `*IncludeRetired` variants).
  - `health` — `avgConfidence = AVG(CASE WHEN confidence IS NOT NULL THEN
    confidence END)`; `graphDensity = liveEdges * 1.0 / NULLIF(concepts,0)`
    (edges per concept; includes possible_duplicate_of edges — see RE-21).
    Verified: E2E store avgConfidence 0.6273, density 5.8091.
  - `circles` — per-scope aggregates merged through the alias map:
    `{canonicalName, conceptCount, observationCount, edgeCount, entityCount}`
    (entityCount = DISTINCT entity keys per circle after alias resolution;
    verified shape). Aliased circles fold into the canonical name.
  - Response envelope: `{generatedAt: Date.now(), counts, health, circles,
    aliases, concepts, observations, edges, contradictions, sessions,
    revisionsCount}` — one ~3.6 MB JSON for the 75 MB E2E store.

### `/api/entities` → `YZ(includeRetired)`

- `{entities: [...], links: [...]}` (verified).
- entities: `key, kind, surface, scope, df` ORDER BY df DESC (verified sample:
  `{key:"ref:e2e:test09-burst", kind:"path", surface:"e2e:test09-burst",
  scope:"e2e-c9b-...", df:21}`).
- links: `concept_id, entity_key, scope` via `concept_entities` JOIN concepts
  (retired filter); includeRetired drops the JOIN.

### `/api/sources` → `KZ()`

- No DB / no `knowledge_sources` table (schema guard: checks
  `knowledge_sources`, `source_sync_runs`, `source_attempt_events` exist) →
  `{sources:[], generatedAt}` (verified: E2E store lacks the table).
- Otherwise: `sources` rows + per-source `activeRun` (joined via
  `active_run_id`), `lastSuccessAt` (`MAX(published_at) WHERE
  result='success'`), `liveRuns` (`state IN ('scanning','staging',
  'activating','cleaning')`), and the **last 128 attempt events per source**
  (`ROW_NUMBER() OVER (PARTITION BY source_id ORDER BY sequence DESC) rn <=
  128`).
- Each source response includes: `state, nextAttemptAt, consecutiveFailures`
  from `computeSourceSchedule` (a0) and `outcomes` from `terminalOutcomes`
  (s0).

#### Source-derived functions (source-only; live-verified only indirectly)

- `deriveSourceStatus` (i0): `lifecycle==='tombstoned'` → `'tombstoned'`;
  `applied_config_version == null` → `'pending-initial-sync'`;
  `applied_config_version === config_version` → `'active'`; else
  `'pending-replacement'`.
- `sourceBackoffMs` (o0): base **30 000 ms**, doubles per consecutive
  failure, capped at the refresh interval.
- `computeSourceSchedule` (a0): forced sync flag → `{state:'syncing',
  nextAttemptAt:null, consecutiveFailures:0}`; non-active or non-interval →
  `{state:'manual', ...}`; no runs → `{state:'due', nextAttemptAt:now}`;
  else `nextAttemptAt = attemptedAt + (last failed ? backoff(consecutive) :
  interval)`; `state = nextAttemptAt<=now ? 'due' : (last failed ?
  'backoff' : 'scheduled')`; `consecutiveFailures` = count of failures at the
  head of the run list (runs ordered newest-first).
- `terminalOutcomes` (s0): folds attempt-event kinds into a per-run terminal
  result list `{attemptedAt, result}` — `verification` → `'success'`;
  `pre-pin-failure` → `'failed'`; `invocation` → `invocation_result`
  (runId-deduped); other kinds with `runId` + `run_result != null` →
  `run_result` (deduped, attemptedAt = max(attemptedAt, runPublishedAt,
  runFinishedAt)).

## Client (app.js)

- **Data flow**: `fetchGraph(includeRetired)` → `fetch('/api/graph' + qs)`
  (qs = `?includeRetired=1` when the "Show retired" chip is on) → `DATA`;
  every render path consumes `getFilteredConcepts()` (client-side filter).
  Entities are cached per includeRetired mode (`ENTITIES` +
  `_entitiesMode`); a request **generation counter** (`_graphRequestGen`)
  drops stale responses.
- **Filters** (all client-side): search (title/slug/body substring), circle
  selector (from `DATA.circles`), kind chips (`KIND_COLORS` per kind), flag
  chips (disputed / show-retired / dirty / has-contradiction /
  possible-duplicate), min-confidence slider (0..1 step .05), edge-type
  toggles (`EDGE_TYPE_ORDER = ['related','follows','possible_duplicate_of',
  'about','co_occurred']`; `EDGE_DEFAULTS.related=true` drawn by default;
  `EDGE_DASHED = {'possible_duplicate_of'}`), min-edge-weight slider
  (0..10 step .5), entity overlay.
- **Graph tab**: custom force layout (`SIM` alpha 1 → alphaTarget 0,
  alphaDecay .015, velDecay .4), per-circle gravity
  (`circle==='all' ? 0.007 : 0.06`), charge `max(-6000, -1600 - 22n)`,
  link distance 130, clustering constants (`CLUSTER_K=14`, `CLUSTER_MIN=40`,
  `CLUSTER_MAX=160`, `MAX_ITER=1500`), a "follow" physics mode
  (`FOLLOW_HOP_LIMIT=2`, `FOLLOW_REST_LEN=130`, spring k .012, friction .85,
  settle threshold 1.5, max settle ticks 90).
  - **`GRAPH_NODE_LIMIT = 800`**: if the filtered node count exceeds 800 the
    layout is NOT run at all (no partial/best-effort) and a guard prompt is
    shown ("nothing is hidden, filter to a circle to draw the graph"). The
    comment documents the measured n² math (`k·n²`; 800 chosen to stay ~25%
    above the ~640-concept full store expected from the upcoming file=concept
    reshape). Full store or big circles (e.g. `obsidian-vault`) hit the cap by
    default; source rows count toward the cap (no-hiding ruling).
  - "Reset layout" clears all in-memory pins + saved positions for the
    current circle and re-runs layout.
- **Concepts tab**: renders EVERY concept row (source rows included — no-hiding
  ruling), measured ~60–100 ms for the full ~3 460-row store; no pagination;
  sortable columns (title, kind, circle, conf, support, degree, updated).
- **Entities tab**: `{surface, kind, circle, df, #concepts}` table.
- **Timeline tab**: canvas sparkline (concepts by created_at) + list, 180px.
- **Sources tab**: source registry table w/ status chips (SOURCE_STATUS_META:
  active / pending-initial-sync / pending-replacement / tombstoned / …),
  attempt-kind labels (`run`→sync, `invocation`→invoked sync,
  `verification`, `pre-pin-failure`).
- **Health tab**: stat chips from `counts` + `health`
  (avg conf % with ok/warn classes at >.7/>.4, density, disputed,
  open contradictions) + open-contradictions section.
- **Detail panel**: concept card with markdown-ish body rendering that
  tokenizes fenced code blocks (`\x00CODE<n>\x00` placeholders) before
  stripping other formatting.
- **Persistence**: localStorage `monet-dash:v1`, schema `LS_SCHEMA_V = 8`
  (bumped 2026-06-20; __v:7→8 migration strips only poisoned `cam_*`
  camera entries). Saves filters + camera/pins per circle; restored on init;
  `beforeunload` saves.

## Verification notes (live, 2026-08-13)

- Empty store (`-d /tmp/monet-dash-verify/store`, no DB): `/api/graph` →
  exact `VZ()` empty shape; `/api/sources` → `{sources:[],generatedAt}`;
  `/api/entities` → `{entities:[],links:[]}`; 404 shape; 403 Host tests;
  `Cache-Control: no-cache, no-store, must-revalidate` on `/`.
- E2E store (`-d ~/.monet-test`, 75 MB): counts
  `{concepts:990, sourceConcepts:0, observations:2978, edgesLive:5751,
  edgesDismissed:0, entities:6564, sessions:464, contradictionsOpen:13,
  contradictionsResolved:72, disputed:9, dirty:929,
  possibleDuplicatePairs:184}`; health `{avgConfidence:0.6273,
  graphDensity:5.8091}`; 295 circles; includeRetired=1 → concepts 992,
  dirty 931 (2 retired rows); entities 6564 / links 7802; sources empty
  (E2E store has no `knowledge_sources` table).
- Snapshot lifecycle: after several requests the snapshot dir contained no
  `.db` files; after SIGINT the whole `monet-dash-*` dir was gone.
- Timing (75 MB store): `/api/graph` 0.44–0.51 s per request, 3.6 MB JSON;
  `/api/entities` 0.39 s; `/api/sources` 0.49 s (42-byte response — pays the
  same snapshot copy cost).

## Findings (RE-20..RE-22)

- **RE-20 (perf, by design but worth knowing)** — every API request copies
  the entire store (SQLite backup) before querying; nothing is cached
  server-side and no ETag/304 is sent. Measured: 75 MB store → ~0.4–0.5 s
  per request regardless of response size. Scales linearly with store size;
  a multi-GB store would make the dashboard sluggish. Mitigations if it ever
  matters: cache a snapshot for N seconds (invalidate on write), or query a
  long-lived read-only connection (WAL allows concurrent readers) with a
  per-request transaction.
- **RE-21 (metric semantics)** — `graphDensity` = live edges / concepts
  counts `possible_duplicate_of` edges (they are live, non-dismissed edges).
  On the E2E store that's 184/5751 ≈ 3.2% of edges — the density metric
  includes duplicate-pair edges, so "graph density" is slightly inflated by
  dedup noise. Not a bug, but the metric name overstates structural density.
  **E2E-confirmed 2026-08-15 (test27, XFAIL):** a 2-concept store with a
  bidirectional `possible_duplicate_of` pair reports `graphDensity = 3.5`
  (= 7 edgesLive / 2 concepts) while structural density excluding the 2 dup
  edges is `2.5` — the dup edges inflate density by `dup_edges/concepts`
  (1.0 here, a 40% overstatement on this tiny store). The test asserts the
  DESIRED contract (`graphDensity == (edgesLive − dup_edges)/concepts`) and
  stays XFAIL until the metric excludes dedup pair-flag edges.
- **RE-22 (security posture, positive)** — dashboard is local-only
  (127.0.0.1), Host-allowlisted, read-only (no write endpoints), no CORS, no
  auth needed because nothing can be mutated. `monet dashboard` is safe to
  run on a shared workstation; there is no remote-monitoring path (a
  deliberate trade-off: to inspect a remote store you must be on the box).

## Module inventory note

Dashboard was the last undocumented module in the inventory; with this doc all
6 modules are DOCUMENTED. Next candidates: (a) re-check RE-09/RE-13/RE-14
against a future version bump; (b) E2E dashboard smoke test (empty-store
endpoint shapes, 403 Host, snapshot cleanup) as a test20 candidate — cheap
and would pin the behavior; (c) sources machinery (`knowledge_sources`,
`source_sync_runs`, `source_attempt_events` tables + scheduler) is only
source-documented so far — the E2E store lacks those tables, so a source-
injection E2E would be the first data-layer verification of a0/i0/o0/s0.
