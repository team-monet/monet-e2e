# Monet Reverse-Engineering — Gates, Conformance & the Gate Journal

> Status: **DOCUMENTED** (2026-08-14, run 21). Source: `@team-monet/core` v0.9.0 TS
> (`src/gates.ts`, `src/gate-journal.ts`, `src/conformance.ts`, `src/script-gate.ts`).
> This is the first module documented from the READABLE TypeScript source rather than the
> minified `dist` bundle — all variable names below are the real ones, not reverse-engineered.
> The minified-bundle analysis (runs 2026-08-10..13) already captured the gate `gate_meta`
> generation counter and the `legacy-star` migration under `circle-routing.md`; this doc covers
> the full normative-hierarchy slice that lives in `gates.ts` and was never documented.

## What this slice is

Three artifacts make up the "normative hierarchy" layer (design of record
`docs/design/next-monet-skeleton-gates-recall.md` + `normative-hierarchy-2026-08-03.md`):

1. **Gates** (`gates.ts`, ~5.1K LOC) — stages + rule bindings + a deterministic trigger-pattern
   matcher. The "host intercepts the action and asks Monet" path.
2. **The gate journal** (`gate-journal.ts`) — an append-only JSONL file recording every
   interception and every outcome, so "broken silence" (a guard that declined to evaluate) is
   distinguishable from "normal silence".
3. **Conformance** (`conformance.ts`) — the "cheap half" of the conformance pass, computing which
   fired rules actually changed an action, from the journal alone.

The sync substrate for these (stages/rule_bindings in the graft payload, the v8 row-convergence
clock) is documented separately in `sync-graft.md`.

## Vocabulary (all enum unions, not tables)

| Enum | Values | Meaning |
|------|--------|---------|
| `RuleSeverity` | `advisory` \| `blocking` | failure MODE: advisory injects, blocking denies |
| `RuleScope` | `domain` \| `agent` | `domain` transfers across models; `agent` is a per-model compensation (carries `model_tag`) |
| `StageOrigin` | `correction` \| `declaration` \| `import` | how a stage was born |
| `RuleBindingOrigin` | `correction` \| `declaration` \| `projection` \| `import` | how a rule was bound; `projection` has no write path yet (vocabulary fixed ahead of the slice) |
| `GateJournalMouth` | `host-hook` \| `gate-cli` \| `core-gate` \| `stage-lookup` \| `declare-check` | which surface wrote the journal event |
| `GateJournalClaimType` | `source-observed` \| `parsed` \| `inferred` \| `corroborated` \| `unavailable` | HOW we know what an event claims |
| `GateJournalDisposition` | `silent` \| `stage-hit-no-rules` \| `advisory` \| `deny` \| `overflow` \| `declined:<reason>` | what a governing mechanism did |
| `ConformanceVerdict` | `changed` \| `conformed` \| `breached` \| `no-effect` \| `vacuous` | §4's verdict vocabulary |
| gate `matcher` | `mechanical` \| `recognized` | `gateQuery` (pattern fire) vs `stageLookup` (agent named a stage) |

## The trigger-pattern format

A pattern = `{ tool: string|null, tokens: string[] }`. Rendered: `Bash: git push --force`
(`tool:null` renders `*: terraform apply`).

- **Fires** when (a) the pattern's tool equals the context tool (or the pattern names no tool),
  AND (b) the pattern's tokens appear as a **contiguous run** anywhere in the context's token
  stream. `Bash: git push --force` fires on `git push --force origin main` and on
  `cd /x && git push --force origin dev`; stays silent on `git status`.
- **Deterministic**: the whole matcher is `===` over lowercased tokens — no scoring, no
  thresholds, no embedder, no clock. That is what lets a blocking rule be a safety boundary.
- **Normalization**: one function `normalizeMatchToken` applied to BOTH sides (context tokens and
  stored pattern tokens) handles case, ordinary quoting, backslash escapes, line continuations,
  shell comments, and newlines. Deliberately NOT handled: `-f` vs `--force`, `--force=true` vs
  `--force`, and ANSI-C `$'…'` quoting (a partial escape table would answer wrong).
- **No regex from user content**: the only regexes are fixed literals validating tool names.
  Pattern length is capped on write; match cost is linear in context length.

### Seeding (`seedTriggerPattern`)

A stage born from a correction seeds its pattern from the observed instance by three mechanical
steps: (1) split the tool prefix off the first `:` only when the text before is a bare
identifier; (2) tokenize shell-ishly (`&&`/`||`/`;`/`|` are their own tokens) and take the LONGEST
segment between separators (so `cd /x && git push --force origin main` seeds from the push, not
the cd); (3) keep command-word through the LAST flag-shaped token, dropping operands. A run that
would end up ALL flags is refused (born pattern-less, inert, surfaced in `unverifiedPatterns`).
Seeding is expected to be wrong sometimes; a dead pattern shows up in `gateStats().unverifiedPatterns`,
and declaration replaces a stage's patterns outright. Blocking severity is declaration-only, so a
bad seed can never produce a wrong deny.

## Schema (`GATE_SCHEMA_SQL`) — 5 tables

- **`stages`** — store-global (NO circle column): `id`, `name` (normalized, UNIQUE), `trigger_patterns`
  (JSON), `origin`, `verified` (0/1, grow-only), timestamps + `sync_revision`/`sync_writer`.
- **`rule_bindings`** — `concept_id` PK (one rule = one stage), `stage_id`, `severity`, `scope`,
  `model_tag`, `origin`, `declared_by`, `reason`, `circle` (locality; `*` = breadth), timestamps +
  clock. **Two schema-level safety boundaries live here as CHECK constraints:**
  - `CHECK (severity != 'blocking' OR origin = 'declaration')` — blocking is declaration-only.
  - `CHECK (circle != '*' OR origin IN ('declaration','correction'))` — global reach is
    declaration-or-governed-inheritance only.
  - `CHECK ((scope = 'agent') = (model_tag IS NOT NULL))` — agent-scoped rule must carry a model tag.
- **`gate_events`** — one row per intercepted action (INCLUDING silences). `id` is SQLite rowid
  (instrumentation must not consume the concept id sequence). Columns: `action_context` (raw,
  verbatim), `matched_stage_id` (highest-severity stage that answered), `rule_count`, `max_severity`,
  `latency_us`, `circle`, `truncated`, `overflow`, `matcher`. Local-only and unsynced (like
  `resolution_events`); wall-clock time, not the persisted sync clock.
- **`gate_event_stages`** — every stage a query matched (not just the one that answered), so
  `byStage` fire-rates don't undercount broad stages that matched alongside a higher-severity one.
- **`gate_meta`** — singleton `(generation)` counter, bumped in the SAME transaction as every
  mutation that can change the mirror output. The mirror header carries this generation; comparing
  header vs counter answers "is this mirror current" without hashing the world.

## Gate evaluation (`gateQuery` / `evaluateGate`)

`evaluateGate` returns `{ result, pending }`; `gateQuery` = evaluate + commit. `commitGateWrites`
inserts one `gate_events` row (+ `gate_event_stages` rows) only after the full verdict — there is
no row for "arrived and declined" in `gate_events` (that gap is exactly what the journal file fills).
`evaluateGateFromMirror` answers the whole gate offline from the mirror file.

`stageLookup` (`evaluateStageLookup`) is the "recognized" matcher — the agent named a stage
explicitly (the `stage_lookup` MCP tool / `monet gate` CLI path), advisory by design, journaled as
`disposition:"deny"` with `enforced:false` when a blocking rule is merely DELIVERED but nothing
is stopped.

## The gate mirror (sidecar)

`materializeGateMirror` writes every LIVE rule (advisory AND blocking) plus the full stage registry
to a local JSON file (`gateSidecarPath`, `GATE_MIRROR_FORMAT = 4`). It is a MIRROR, not a copy:
the store is master; the file is regenerated at every declaration, never edited, never read back as
authority, and safe to delete. It exists so a host CLI can answer the whole gate offline (server
down). `inspectSidecar` returns a staleness verdict (`SidecarStaleness`) by comparing the file's
generation header against `gate_meta.generation`. `storeIdentity` (the sync device id) is stamped in.

## The gate journal (`gate-journal.ts`)

A file (`gate-journal.jsonl`), NOT a table — because the busiest mouth (the Claude Code hook
wrapper) is sqlite-write-free by ruling and runs before any store is opened.

- **Two lines per evaluation**: an `arrival` line at the mouth (before any guard) and a
  `disposition` line at exit, sharing an `id`. An arrival with no matching disposition is itself a
  finding (a crash/OOM/kill between the two is the exact failure worth recording).
- `GATE_JOURNAL_FORMAT = 1`, `GATE_JOURNAL_FILENAME = "gate-journal.jsonl"`.
- **Rotation**: `GATE_JOURNAL_MAX_BYTES = 64 MiB`, rotate-before-append, serialized across processes
  via an exclusive `wx` lock file with `ROTATE_LOCK_STALE_MS = 60_000` staleness clearing.
  `.prev` keeps exactly one prior generation (bounded at 2x the cap).
- **Clipping**: `GATE_JOURNAL_CONTEXT_MAX_CHARS = 2048`; over that, the line carries a prefix +
  `actionContextSha256` (sha256 of the whole) + true `actionContextChars`, so identity is preserved
  without reproducing a multi-MB payload (a real run produced a single 12 MB line before this).
- **Total failure-swallowing**: every append failure is swallowed deliberately — recording is a
  duty to the record, never one to the user's action; the journal must never block or crash an
  evaluation. `path === null` is the no-op default (so tests/evals never write into a real store).

## Conformance (`conformance.ts`)

The "cheap half" of the conformance pass. §4 gives "changed the action" an OBSERVABLE definition:
a rule changed the action iff the record shows the governed act's outcome diverging from the act as
intercepted, in the direction the rule names. Of the five verdicts, only ONE is decidable from the
journal by pure observation:

- A **blocking deny** → `changed` (observed: the host's contract is that the call does not proceed).
- Everything else (advisory `conformed`/`breached`, `vacuous`) needs a rule's MEANING read against
  an act → semantic judgment, assigned to a future "judgment half" (§7.4). These are recorded as
  `unavailable` (a queryable backlog), NEVER silently skipped.

`computeConformance(lines)` is pure (parsed lines → annotations, no store/clock), idempotent by
fire-event id, and monotone on retry (a `retriedUnchanged: false` may upgrade to `true` once a later
occurrence is seen, never the reverse). Key non-obvious correctness facts it encodes:

- `deny` with `enforced:false` is NOT a deny (the stage-lookup advisory path) — it falls through to
  advisory treatment.
- A mixed-severity fire credits only the BLOCKING rules (`blockingRuleIds`), not every id on the
  event.
- Retry detection joins an event's action across mouths by `parentId` chains followed to the ROOT
  (three-deep interception: host-hook → gate-cli → core-gate), and keeps only the two most recent
  occurrences in DISTINCT chains.
- `retirementCandidates` = `fires > 0 AND changed + conformed = 0 AND awaitingJudgment = 0` — the
  design's process-ratchet watch. `no-effect` counts as measured-and-moved-nothing (a standing grant
  that arose and went unexercised IS retirement evidence).

## Parameters (this module)

| Parameter | Value | Where | Role |
|-----------|-------|-------|------|
| `MAX_STAGE_PATTERNS` | 32 | `assertPatternCountWithinCap` | pattern-count cap per stage |
| `STAGE_NAME_MAX_CHARS` | 500 | `normalizeStageName` | stage name cap |
| `MODEL_TAG_MAX_CHARS` | 200 | `BindRuleInput` | model-tag cap |
| `STAGE_LOOKUP_RULES_CAP` | 200 | `stageLookup` | rules returned by stage_lookup |
| `STAGE_LOOKUP_BODY_CAP` | 6000 | `stageLookup` | rule body cap |
| `STAGE_LOOKUP_REASON_CAP` | 1200 | `stageLookup` | reason cap |
| `STAGE_LOOKUP_OUTLINE_CAP` | 500 | `stageLookup` | outline cap |
| `STAGE_INDEX_CAP` | 2000 | `stageLookup` | stage-index cap |
| `DISPUTED_PARENTS_CAP` | 8 | `ruleOutlineForStage` | disputed-parents cap |
| `COMMAND_BOUNDARY` | `"\n"` | `parseActionContext` | action-context command boundary |
| `GATE_MIRROR_FORMAT` | 4 | `materializeGateMirror` | mirror file format version |
| `GATE_JOURNAL_FORMAT` | 1 | `gate-journal.ts` | journal line schema version |
| `GATE_JOURNAL_MAX_BYTES` | 64 MiB | `rotateIfNeeded` | journal rotation cap (2x this on disk) |
| `GATE_JOURNAL_CONTEXT_MAX_CHARS` | 2048 | `clipActionContext` | verbatim context ceiling |
| `ROTATE_LOCK_STALE_MS` | 60 000 | `rotateIfNeeded` | rotation-lock staleness clearing |
| blocking-is-declaration-only | `CHECK (severity != 'blocking' OR origin = 'declaration')` | `GATE_SCHEMA_SQL` | deny power cannot be self-assigned (schema-level) |
| breadth-is-declaration-only | `CHECK (circle != '*' OR origin IN ('declaration','correction'))` | `GATE_SCHEMA_SQL` | global reach cannot be minted by import/capture |
| agent-scope-implies-tag | `CHECK ((scope = 'agent') = (model_tag IS NOT NULL))` | `GATE_SCHEMA_SQL` | per-model compensations carry a tag |

## Issues found

- **RE-26 (scalability, confirmed):** `gate_events` has NO retention/pruning — the source comment states
  "on a busy store it will become the largest one" (2–3 orders of magnitude more rows than
  `resolution_events`; grows with agent activity, not memory volume). Retention is explicitly
  deferred, with `SOURCE_ATTEMPT_EVENT_RETENTION` (128 immutable receipts/source) named as the
  precedent to copy. Not a bug today, but a real operability gap on busy stores. **E2E-CONFIRMED (2026-08-15, test29):** 131 `stage_lookup` calls (recognized matcher) → 131 `gate_events` rows, and no retention/prune surface exists in `gate`/`doctor`/`status`/`resegment`/`--help` or the 23 MCP tools. XFAIL.
- **RE-27 (measurement half-vacuum, by-design):** the conformance "cheap half" can only ever emit
  `changed` for blocking denies. Every advisory fire is recorded `unavailable` (awaiting the future
  "judgment half"), so `retirementCandidates` can never retire an ADVISORY rule — the process-ratchet
  watch is effectively blocking-only today. Honest, but means the retirement query is silent on the
  advisory population until §7.4 ships.
- **RE-28 (privacy surface, by-design/mitigated):** `gate_events.action_context` stores the RAW
  intercepted action verbatim (command lines, `/Users/...` paths, hostnames, flags) — the most
  privacy-sensitive column in the store. Local-only/unsynced by construction, and the schema-driven
  scrub closure covers it automatically, but it is a documented exposure surface to be aware of when
  anything is derived from the store for sharing.
