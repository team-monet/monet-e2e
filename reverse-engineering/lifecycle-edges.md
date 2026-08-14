# Lifecycle edges & ratifications (the normative substrate)

Source: `src/lifecycle-edges.ts` (readable TS, `@team-monet/core` v0.9.0) + its `__tests__`.

## What it is

A **separate append-only table pair** — `lifecycle_edges` + `ratifications` — that records the
*normative* substrate: which rules derive from which principles, which transcript span a rule's
authority comes from, which rule supersedes which, and the human rulings (ratifications) that
approved or retired them. The design of record ("Next Monet",
`docs/design/next-monet-skeleton-gates-recall.md`) makes authority **edges, not a flag**: impeachment,
audit, extraction-evidence exclusion, and mirror regeneration all run on them.

Three relation families (the `family` column): **derivation** (principle → rule), **provenance**
(rule → transcript `span://` URI), **supersession** (rule → rule).

## Why not `memory_edge`

Two structural reasons, verified against live code (cited by name, not line number):

1. `memory_edge` is *derived* state, disposable by maintenance. `unwindConceptGraph` runs an
   untyped `DELETE FROM memory_edge WHERE scope = ? AND (src_id = ? OR dst_id = ?)`, and
   `rederiveConceptGraph` recreates only the types it can re-derive from body/observations. The
   `possible_duplicate_of` carve-out that survives an unwind exists at only **2 of 7** unwind call
   sites; the other five (`recomputeSourceConceptBody`, `retireConcept`, the two sync-apply sites,
   `moveConcept`) have none. A normative edge stored there would be silently destroyed by an
   ordinary retire or circle move. A separate table is immune by construction — graph maintenance
   does not know it exists.
2. `memory_edge` already has `derived_from`/`supersedes` types that are *heuristic* (parsed from free
   text by `ASSERTED_RE`), while these edges are born from **acts** (a correction, a declaration, a
   ratification), never parsed from prose. Sharing rows or type names would conflate heuristic
   association with normative authority.

Consequences, all deliberate: these rows never participate in similarity-graph adjacency, hub
filtering, or edge-type histograms; they are append-only (no update path for family/src/dst, and
graph maintenance never deletes them); and they **do sync** (unlike `resolution_events`, a normative
record that failed to replicate would make two machines disagree about what governs).

## Key behaviors

- **Schema-level invariants** (SQL, not just API): the two paired `family = 'provenance'` CHECKs use
  SQLite's boolean-equality trick to make family and destination shape inseparable in both
  directions (a provenance edge cannot lack a span or carry a concept; a derivation/supersession
  edge cannot carry a span or lack a concept); self-edges are refused
  (`dst_concept_id IS NULL OR dst_concept_id != src_concept_id`); a ratification-born edge must carry
  a non-null `event_ref`; supersession is unique via a **partial** index
  (`WHERE family = 'supersession'`) — a rule has at most one *direct* successor, while chains form
  across rows (A superseded-by B, later B superseded-by C).
- **Governability predicate** (`ungovernableReason`) — one source of truth, shared by the local
  write path and the graft-side guard: a `source` concept, any connector-owned concept
  (`source_identity`/`active_observation_id` set), or a `workstream` cannot carry normative record
  (a workstream is derived cache, not a concept — it can neither govern nor be governed).
- **Cross-circle is checked at creation, not maintained.** An edge may only be born within one
  circle (a principle in one circle governing a rule in another is undecided, so refuse rather than
  guess). But nothing preserves that afterwards: an ordinary `reassignCircle` later moves one
  endpoint and leaves a cross-circle edge standing, because the row records the circle its *act*
  happened in and append-only forbids rewriting it. (A circle **rename** does follow — locality is
  renamed, not the concept moved.) Consumers must treat `circle` as provenance, never a live locality
  index. See RE-34.
- **Supersession cycle guard** — `supersessionCycle` walks forward from the proposed destination
  (cap `SUPERSESSION_WALK_CAP`); a chain that reaches the proposed source would close a ring, which
  is refused. One source of truth shared by the local throw and the graft loop (which skips rows
  rather than aborting the whole graft).
- **Ratification (verdict, entrance, battery) rules live in ONE place** (`classifyRatificationPair`),
  after the same defect arrived three times on PR #144 (a rule added to the local write path but not
  the relay path, or the reverse). The two callers differ only in what they do about a violation:
  a local write **throws** (the author is present), a relayed row **degrades to "unrecorded"** (one
  bad ratification must not stop a sync).
- **The four-gate battery** (`BATTERY_GATES` = generates / covers / transfers / exits) is what a
  principle must pass to enter the skeleton *by extraction*. The entrance vocabulary splits
  monet-core#142's three indistinguishable states: `declaration` = sovereignty replaces the battery
  (never ran, by right); `extraction` + approve = ran and passed; `extraction` + reject = ran and
  rejected. The rules enforce **form, never content** (Monet cannot know whether an answer is true,
  only whether one exists):
  - an extraction approval/rejection must carry a complete battery (all four gates, each once, each
    a boolean `passed`, no duplicates, no extra gates);
  - a declaration must NOT carry one (a battery there would be a test nobody ran);
  - `retire` answers to neither entrance (it ends a membership, not a judgment);
  - a battery with no entrance is refused; a failed gate is mechanically inadmissible on the
    extraction approval path (rejections keep their failed answers — which gate refused is the whole
    value of one).
- **`created_at` takes the persisted sync clock** (`nextSyncTimestamp`), not `Date.now()` — the
  clock is strictly monotonic, so two edges written in the same millisecond still order
  deterministically (these rows are read as a *record of acts in sequence*). Convergence for the
  one mutable column (`circle`) uses the `(sync_revision, sync_writer)` house pattern, not a bare
  `sync_updated_at` (the local and incoming relay clocks are different domains).
- **Migration** — `ratifications` was born carrying every column; `migrateRatificationColumns`
  (idempotent, `table_info`-guarded, `ALTER TABLE ADD COLUMN` with a duplicate-column swallow) adds
  `entrance` + `battery`. Legacy rows are left NULL deliberately: NULL says the true thing (the
  verdict predates the field, and how it entered was never recorded structurally) rather than a
  guess dressed as a record.

## Parameters / constants

| Parameter | Value | Role |
|-----------|-------|------|
| `LifecycleEdgeFamily` | `derivation` \| `provenance` \| `supersession` | 3 relation families |
| `LifecycleEdgeBirth` | `correction` \| `declaration` \| `projection` \| `ratification` \| `extraction` | 5 birth acts |
| `RatificationVerdict` | `approve` \| `reject` \| `retire` \| `re-ratify` | 4 human verdicts |
| `RatificationEntrance` | `extraction` \| `declaration` | how a verdict entered (#142) |
| `BATTERY_GATES` | `generates` / `covers` / `transfers` / `exits` | 4-gate extraction battery |
| `SUPERSESSION_WALK_CAP` | 1000 | cycle-walk refusal cap |
| supersession uniqueness | partial unique index on `(src_concept_id)` | one direct successor per rule |
| `dst_span` format | `span://` URI (rejected if `parseSpan` fails) | provenance destination |

## Issues

- **RE-34** — cross-circle is checked at creation but **not maintained**: an ordinary
  `reassignCircle` (or `moveConcept`) after edge creation moves one endpoint into another circle and
  leaves the edge standing with a `circle` value that no longer names both endpoints. The source
  documents this as intentional (append-only + `circle` is provenance), but it is a latent
  footgun for any consumer that filters edges by circle. `by-design` (S4) — recorded for visibility.
  See ISSUES.md.

## Verification

`lifecycle-edges.test.ts` (1703-line contract test) pins the schema invariants, the three-family
shape, the governability refusals (source/workstream endpoints), cross-circle refusal at creation,
supersession uniqueness + incumbent naming + cycle walk, the ratification (verdict, entrance,
battery) classification matrix, and the migration's legacy-NULL behavior.
