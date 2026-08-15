# MCP Server / Wire Layer (`mcp-server.ts`)

> Source: `packages/core/src/mcp-server.ts` (readable TS, `@team-monet/core` v0.9.0,
> 3 503 lines — the largest core file after `engine.ts`). This is the **wire layer**:
> it registers every MCP tool, shapes/limits every response to fit the host's
> tool-result budget, injects session orientation, and owns graceful shutdown.

## What it is

The MCP server module is the single operator-facing boundary between the engine
(`MonetCore`) and the MCP protocol. It does **not** implement memory semantics —
those live in `engine.ts` / `retrieval.ts` / `resolution.ts` / `gates.ts` etc. This
file's job is the *presentation and lifecycle* of those semantics:

1. **Tool roster** — registers the 23 MCP tools (17 `memory_*` + 4 `source_*` +
   `agent_context` + `stage_lookup`) and maps each to its `core.*` engine method.
2. **Result shaping** — every bounded response is fitted against `RESULT_MAX_CHARS`
   (40 000) with iterative `JSON.stringify` size checks (not naive count caps), and
   `ok()` is a last-resort valid-JSON envelope that never emits unparseable output.
3. **Auto-prewarm** — a one-shot per-process session-context block prepended to the
   first successful non-`agent_context` response, for agents that never call
   `agent_context`.
4. **Shutdown machinery** — in-flight tool-call tracking + a referenced-timer barrier
   + signal/EOF handlers so a long handler (e.g. `source_sync`) can't touch a closed DB.

## Tool roster (23 tools)

The definitive registration order (`server.tool(...)` call sites):

| # | Tool | Engine method | Category |
|---|------|---------------|----------|
| 1 | `memory_store` | `core.store()` | write |
| 2 | `memory_declare` | `core.declare()` | write |
| 3 | `memory_ratify` | `core.ratify()` | write |
| 4 | `memory_search` | `core.search()` | read |
| 5 | `memory_overview` | `core.overview()` / `core.conceptsForEntity()` | read |
| 6 | `memory_list` | `core.list()` | read |
| 7 | `memory_fetch` | `core.fetch()` | read |
| 8 | `stage_lookup` | `core.stageLookup()` | read |
| 9 | `memory_synthesize` | `core.synthesize()` | write |
| 10 | `memory_checkpoint` | `core.checkpoint()` | write |
| 11 | `memory_workstreams` | `core.*workstream*` | read |
| 12 | `memory_flag_contradiction` | `core.flagContradiction()` | write |
| 13 | `memory_resolve` | `core.resolveContradiction()` / pair-flags | write |
| 14 | `memory_detach` | `core.detach()` | write |
| 15 | `memory_reassign_circle` | `core.reassignCircle()` | write |
| 16 | `memory_retire` | `core.retire()` | write |
| 17 | `memory_restore` | `core.restore()` | write |
| 18 | `memory_circle_manage` | rename/merge/archive/unarchive/list | write/read |
| 19 | `source_list` | `core.listConnectorSources()` | read |
| 20 | `source_status` | `core.sourceStatus()` | read |
| 21 | `source_path` | `core.sourcePath()` | read |
| 22 | `source_sync` | `core.syncSource()` | write |
| 23 | `agent_context` | `core.prewarm()` | read |

The 21 → 23 change (1.6.1) is `memory_retire` + `memory_restore` — they fill the
retire/delete gap (issue #62; see `retire-delete-gap.md`).

## Request lifecycle

- **Circle scoping** — `scope(circle?) = core.resolveCircleName(circle ?? dc)`, where
  `dc = core.getDefaultCircle()` is captured once at registration. A tool call without
  `circle` falls back to the runtime's configured default; `resolveCircleName()`
  transparently follows `circle_aliases`, so a stale name routes to the canonical
  circle (see `circle-routing.md`).
- **Write/read ack wrappers** — `mutOk(content, toolName, capturedBlock)` and
  `readOk(...)` both call `ok()` then `wrapSuccess()`; they differ only in name
  (read vs mutation, for tracing clarity).
- **Result envelopes** — `ok(content)` JSON-stringifies (pretty, 2-space). On success
  `content[0]` is the pure JSON result (byte-identical pre/post decoration, so
  `JSON.parse(content[0].text)` consumers like `mcp-smoke.ts` are preserved). The
  prewarm block ships as a *separate* `content[1]` text item — a host that drops
  extra content items degrades to no-prewarm, best-effort.
- **Error path** — `err(message)` returns `{content:[{text:message}], isError:true}`.
  Every handler wraps its body in try/catch and returns `err("<tool> failed: <msg>")`;
  source tools route through `sanitizeSourceError(e)` so the four `source_*` tools
  never leak internal paths/hostnames (see RE-23 in `sources-sync.md`).
- **Server-bound identity** — `sourceAuthorizationContext` (frozen) and `modelTag`
  are host-injected at registration, **never** accepted from a tool argument. Sources
  authorization is server-bound (the four `source_*` tools take only `sourceId`).

## Result shaping — the size-fit layer (dominant theme)

Every potentially-unbounded response is fitted against the ceiling **by serializing
the actual envelope and measuring**, not by trusting a fixed count cap (the file's
comments document a long "count cap alone is a hope, not a guarantee" review history):

- **`ok()` last resort** — if the serialized result exceeds `RESULT_MAX_CHARS`, it
  returns `{truncated:true, originalChars:N, note:"…the original payload was omitted."}`
  — a *whole-payload omission* with an explicit signal, deliberately NOT a byte-slice
  (slicing valid JSON at a byte offset leaves unparseable output).
- **`clip(s, max)`** — per-field truncation that appends a `…[truncated N chars]`
  marker and returns a `clipped` flag.
- **`fitObjectArray` / `fitStringArray` / `fitRecallEnvelope` / `fitOverviewEnvelope`**
  — iterative append-and-measure loops over arrays (search cards, memory_list rows,
  stage index, overview sections) so many small items survive and a few huge ones stop
  before the ceiling.
- **`memory_fetch`** — bounded at the source: `FETCH_MAX_OBS`, per-observation and
  per-body caps, an outline loop with `FETCH_OUTLINE_MAX_ENTRIES`, plus an
  `okNote`-reserved sizeBudget.
- **`stage_lookup`** — three-part defense (`STAGE_LOOKUP_RULES_CAP`/`BODY_CAP`/
  `REASON_CAP` imported from `gates.ts` — one shared definition so SQL and wire can't
  drift) + a size-fit loop over the *serialized* rules, plus a **3-tier omitted-rule
  recovery ladder** (`outline` → `ids` → `count-only`, with `-partial` variants)
  so a caller can always `memory_fetch` a rule it couldn't see.
- **`agent_context`** — a `grow()` loop that expands skeleton/mirror/stage counts
  against the same sizeBudget, preserving the "uncovered governing members first"
  priority order.

## Auto-prewarm (session orientation without `agent_context`)

- **One-shot per server process** (`prewarmed` flag). On the first successful
  non-`agent_context` response, a `=== MONET SESSION CONTEXT (auto-prewarm) ===` block
  is prepended (as a separate content item) — the stage-index "recognition cue"
  (`Stages you can recognize (ask stage_lookup): …`) plus an open-workstreams/inbox
  count line.
- **Snapshot-before-mutation** (`capturePrewarmSnapshot` is called *before* the
  handler runs) — the block never contains facts written in the same call. The
  snapshot is **consumed on success, discarded on error**, so a failing call never
  advances the one-shot.
- The stage-recognition cue is built **incrementally against its own line budget**
  (`STAGE_INDEX_PREWARM_LINE_MAX_CHARS`), so a few long stage names can't silently
  drop the entire cue — a non-empty prefix always survives.
- Disabled via `MONET_NO_AUTOPREWARM=1`; `agent_context` suppresses the block (its
  own payload *is* the orientation) and itself consumes the one-shot.

## Model-tag "one chain" (agent-scoped rule compensation)

`defaultModelTag` resolves from `opts.modelTag ?? process.env.MONET_MODEL_TAG`, with
**blank treated as absent** (an empty `MONET_MODEL_TAG=` from shell templating must not
clear a constructor-supplied tag). It is set once via `core.setRuntimeModelTag()` at
registration; the write path reads `core.getRuntimeModelTag()` **at call time**, so a
live mid-session tag switch is respected by both capture and delivery — closing a prior
bug where `stage_lookup` filtered by the default but `gate()`/`gateStats()` read a still-null
field and silently disagreed about which rules exist.

## Graceful shutdown machinery

- **In-flight tracking** — `registerMonetCoreTools` wraps `server.tool()` once, so
  every handler increments/decrements an `InFlightTracker`. `getGracefulShutdown`
  awaits `quiesce()` (default `IN_FLIGHT_QUIESCE_DEADLINE_MS` = 10 s) between
  `server.close()` and `core.close()`.
- **`withShutdownBarrier`** — a deliberately-un-`ref()`'d referenced timer keeps the
  event loop alive until shutdown work settles or `SHUTDOWN_BARRIER_DEADLINE_MS`
  (30 s) elapses — because Node doesn't await signal/`transport.onclose`/EOF callbacks.
- Signal handlers map to conventional exit codes (`SIGINT`→130, `SIGTERM`→143);
  stdin-EOF and signal handlers are disable-able per-instance (`processShutdownHandlers:false`,
  `stdinEofShutdown:false`) for multi-instance embeddings.
- **Long-sync disposition is deliberate**: a git-md sync (git 120 s timeout, 5-minute
  materialization deadline) can outlive both the 10 s quiesce and the 30 s barrier.
  Past them, `core.close()` proceeds and the handler's next DB touch fails against the
  closed connection — the *same recoverable* "failed attempt + staged-run supersession +
  retry" path a hard crash hits (WAL mode + durable run ledger guarantee no corruption).

## Key constants

| Constant | Value | Role |
|----------|-------|------|
| `MONET_SERVER_INSTRUCTIONS` | (system prompt) | Injected instructions: agent_context first, stage_lookup before acting, search→fetch, store vs declare/ratify boundary, checkpoint-as-it-happens |
| `RESULT_MAX_CHARS` | 40 000 | Hard ceiling on any serialized tool result (`ok()` whole-omission net) |
| `FETCH_MAX_OBS` | 20 | Most-recent observations returned by `memory_fetch` |
| `FETCH_OBS_MAX_CHARS` | 1 200 | Per-observation cap |
| `FETCH_BODY_MAX_CHARS` | 6 000 | Concept body cap |
| `FETCH_CONTRADICTION_MAX_CHARS` | 400 | Per-open-contradiction detail cap |
| `FETCH_CONTRADICTIONS_MAX` | 5 | Newest-first open-contradiction entries per fetch |
| `FETCH_OUTLINE_MAX_ENTRIES` | 200 | Source-concept outline upper bound (cheap size-fit loop bound) |
| `CIRCLE_NAME_MAX_CHARS` | 256 | (exported) every caller-controlled circle echo before writes |
| `WRITE_ACK_LIST_MAX` | 25 | Ack list fit (e.g. impeachedPrincipleIds) |
| `STAGE_ACK_PATTERNS_MAX` | 8 | stage-view pattern cap in write ack |
| `STAGE_ACK_TOKEN_MAX_CHARS` | 80 | per-pattern token clip |
| `STAGE_ACK_PATTERN_MAX_CHARS` | 300 | per-pattern clip |
| `WRITE_ACK_TEXT_MAX_CHARS` | 1 000 | stage-name clip in write ack |
| `ANOMALOUS_STORE_RESOLUTION_MODES` | {ambiguous-fork, fork-signal, blur-duplicate, species-fork, stage-fork} | resolution modes surfaced as anomalous in the store ack |
| `PREWARM_BLOCK_MAX_CHARS` | 2 500 | prewarm block budget |
| `STAGE_INDEX_PREWARM_MAX_SHOWN` | 15 | stage-recognition cue name cap |
| `STAGE_INDEX_PREWARM_LINE_MAX_CHARS` | 800 | cue line's own budget (incremental fit) |
| `STAGE_INDEX_PREWARM_TAIL_MARGIN_CHARS` | 20 | "+K more" tail headroom |
| `SHUTDOWN_BARRIER_DEADLINE_MS` | 30 000 | shutdown barrier deadline |
| `IN_FLIGHT_QUIESCE_DEADLINE_MS` | 10 000 | in-flight tool-call drain deadline |
| `SIGNAL_EXIT_CODE` | {SIGINT:130, SIGTERM:143} | 128+signal convention |
| `MONET_NO_AUTOPREWARM` | `"1"` | disable auto-prewarm |
| `MONET_CALLER_ID` + `MONET_PROJECT_ID` | (both required) | server-bound source authorization identity |
| `MONET_MODEL_TAG` | (blank = absent) | agent-scope compensation model tag |

## Issues found

- **RE-39 (S4, source)** — the "result truncated" note text is dead and duplicated:
  `RESULT_TRUNCATE_NOTE` (module scope) and a byte-identical local `okNote`
  (memory_fetch) are each referenced **only** via `.length` as sizeBudget headroom;
  neither string is ever emitted. When `ok()` actually exceeds the ceiling it emits a
  *different* wording (`"Result exceeded the host tool-result limit; the original
  payload was omitted."`). Net: two dead copies of a note + a wording divergence between
  the reserved note (which suggests narrowing/lowering `limit`/`memory_fetch`) and the
  actually-emitted note (which only says "payload omitted").
- **RE-40 (S4, source)** — `RegisterMonetCoreToolsOpts.checkpointNudge` is a deprecated
  no-op ("Checkpoint response nags are no longer emitted") still present in the public
  options interface — dead API surface.

## Relationship to other docs

- `memory_search` semantics → `search-pipeline.md`; `memory_resolve`/`flag` →
  `contradiction-processing.md`; `memory_circle_manage` → `circle-routing.md`;
  `source_*` → `sources-sync.md`; `stage_lookup`/gates → `gates.md`; skeleton/mirror →
  `skeleton-mirror.md`. This doc covers the *wire* concerns those modules deliberately
  leave out: the roster, the size-fit envelopes, prewarm, and shutdown.
