# Monet Reverse-Engineering — `renderOverview` (terminal curation workbench renderer)

> Status: **DOCUMENTED** (2026-08-16, run 34). Source: `packages/core/src/render-overview.ts`
> (readable TS, commit 83e9d7d, core 0.9.0) + `engine.ts` `overview()`. Pure function, no
> db handle, no side effects.

## TL;DR

`renderOverview(overview: MemoryOverview, opts) → string` renders the actionable
curation workbench as terminal text (ANSI-colored when `opts.color`). It is the
human-facing "what needs a human decision right now" view over the `MemoryOverview`
object the engine's `overview(circle)` already assembles — it adds NO data, only
layout, truncation, and color. Deterministic (test-asserted: same input → same output).

## Sections (in render order)

| Section | Source field | When shown |
|---|---|---|
| Header | `circle`, `counts.concepts`, `counts.observations` | always |
| LIVING MODEL | `livingModel[]` (`kind · title · supportCount obs`) | non-empty |
| DIRTY · SYNTHESIS QUEUE | `dirty[]` + `dirtyOmitted` | `dirty` present |
| STALE · RE-CONFIRMATION QUEUE | `stale[]` + `staleOmitted` | `stale` present |
| OPEN CONTRADICTIONS | `openContradictions[]` + `openContradictionsOmitted` | non-empty or omitted>0 |
| POSSIBLE DUPLICATES | `possibleDuplicates[]` (vs `counts.possibleDuplicates` total) | non-empty |
| EXTRACTION CANDIDATES | `extractionCandidates[]` (vs `counts.extractionCandidates`) | non-empty |
| SKELETON | `skeleton[]` (`species · content [· ratifiedBy]`) vs `counts.skeleton` | non-empty |
| GATE EXCEPTIONS | `gateStats` (window stats, `retirementCandidates[]`, `unexplainedDenies[]`) | any present |
| LEGACY-STAR FILING | `legacyStarConcepts` | non-null |
| all-clear | `green("no curation work queued")` | see below |
| footer | `dim("read-only · fetch <id> to inspect evidence")` | always |

## Mechanics

- **ANSI handling** is width-aware: `vlen` strips SGR codes (`ESC[…m`) to measure the
  *visible* length; `truncate(value, width)` walks the string preserving escape
  sequences and truncates at `width - 1`, appending `…`. Color is opt-in
  (`opts.color`, default false).
- **Default width 84** (`opts.width ?? 84`).
- **Omitted counters** surface truncation honestly: `dirtyOmitted`/`staleOmitted`/
  `openContradictionsOmitted`/`retirementCandidatesOmitted`/`unexplainedDeniesOmitted`,
  and `showing N of M` for pairs and skeleton when the full list exceeds the summary.
- **All-clear condition** (the green "no curation work queued" line) fires only when
  `counts.dirty === 0 && counts.stale === 0 && counts.disputed === 0 &&
  counts.possibleDuplicates === 0 && counts.extractionCandidates === 0` AND no
  `gateStats.retirementCandidates`/`unexplainedDenies`/`legacyStarConcepts`. Note it
  does NOT test `openContradictions` directly — it relies on `counts.disputed` (which
  is derived from open contradictions in the engine, `open_count > 0 → 'disputed'`)
  to stand in for it.
- Ids are abbreviated to `id.slice(0, 8)` everywhere; titles/contents are truncated to
  the width.

## Where the data comes from

`renderOverview` consumes `MemoryOverview` (from `engine.ts` `overview(circle)`), which
is the same object the `memory_overview` MCP tool returns as JSON. So the terminal
renderer and the JSON tool share one data source; they differ only in presentation.

## Issues found

- **RE-37 (S3, source):** `renderOverview` has **no operator surface** in the current
  source. It is exported from `index.ts` (public API) and a `gates.test.ts` comment
  states it "is the human curation surface (it is what the CLI prints)", but no CLI
  command (`start/status/config/dashboard/source/doctor/repair/resegment/gate/install/
  materialize`) and no MCP tool calls it — the `memory_overview` tool returns JSON, and
  `monet status` returns statistics. Library-only reachability today (mirrors RE-35's
  `lifecycleEdgeIntegrity`), but higher severity because this is the intended primary
  human view. Either a CLI `overview`/`workbench` command is planned-but-unshipped, or
  the export is dead. Verify against the shipped CLI before treating as a product gap.
