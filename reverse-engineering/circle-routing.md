# Circle routing & aliases lifecycle

> Source-level documentation of circle resolution, alias/rename/merge/archive
> semantics, and the legacy `*` (star-circle) migration. Verified against
> `@team-monet/monet` v1.5.2 `dist/index.js` (2026-08-12, RE run 14).
> Related: `schema-migration.md` (circle_aliases DDL origin, sync columns),
> `search-pipeline.md` (store-wide vs explicit-circle recall).

## Architecture: circles are IMPLICIT namespaces

- There is **no circles registry table**. A circle "exists" iff some row
  references it: `concepts.circle`, `observations.circle`,
  `entities.scope`, `lifecycle_edges.circle`, `ratifications.circle`,
  `knowledge_sources.circle`, or a `circle_aliases` row.
- `circle_aliases` is the **only** circle-side table. Columns:
  `from_name TEXT PRIMARY KEY`, `to_name TEXT NOT NULL`,
  `status TEXT NOT NULL DEFAULT 'active'`, `created_at`, `updated_at`,
  `sync_revision`, `sync_writer`; index `idx_ca_to(to_name)`.
  Only two statuses are ever written: `'active'` (alias/rename target,
  archive self-row) and `'archived'` (archive marker). Rows are never
  deleted by user ops — archive/unarchive flip status, rename/merge upsert.
- `var W = "*"` — the **reserved global-breadth marker**. `*` is NOT a
  circle: concepts/workstreams/sources may not live in it, `defaultCircle`
  may not be `*`, aliases may not name it on either side, and
  rename/merge/archive/unarchive/reassign all refuse it. `memory_declare`
  is the ONE legitimate consumer: `circle:'*'` declares a global-breadth
  member, which is stored at the default circle with
  `skeleton_breadth='global'` and is delivered for every circle
  (`WHERE (c.circle = ? OR c.skeleton_breadth = 'global')`).
- `var rd = "legacy-star"` — fallback destination base name for the
  legacy-`*` migration (see below).

## resolveCircle — the single routing primitive

```js
resolveCircle(e){
  let t = this.db.prepare(
    "SELECT to_name FROM circle_aliases WHERE from_name = ? AND status = 'active'"
  ).get(e);
  return t ? t.to_name : e;
}
resolveCircleName(e){ return this.resolveCircle(e); }
```

- **Single-hop only**: alias chains (`a→b`, `b→c`) do NOT transitively
  resolve; `resolveCircle(a)` returns `b`, never `c`. The graph is kept
  flat by rename/merge, which repoint `to_name` rows (below).
- Resolution requires `status='active'` — an **archived** alias row does
  not resolve (returns the input name).
- Applied at the head of every circle-scoped entry point: `store`/
  `storeInternal`, `storeSource`, `search` (when `circle` given),
  `checkpoint`, `saveWorkstream`, `listStale`, `listDirty`, `dirtyCount`,
  `listMemories`, `reassignCircle`, `overview`, `ratify`, gate ops,
  `prewarm`, `skeleton*`, `getWorkstreamById`, `getActiveWorkstreams`,
  `listSessions`, etc. One canonical resolution point; nothing else
  re-implements alias lookup.

## renameCircle(from, to)

Guards (in order): `*` on either side → throw; `from===to` → `noop`;
same sharing scope; no registered source participants
(`knowledge_sources.circle IN (from,to)`); no source concepts
(`kind='source' OR source_identity IS NOT NULL OR active_observation_id
IS NOT NULL`) in `from`; no retired concepts in `from`; the circle must
exist (`concepts OR circle_aliases(from OR to side) OR
lifecycle_edges/ratifications`), else "circle not found".

Transaction:
1. `moveCircleScopedTables(from, to, syncTs, deviceId)` — moves
   `concepts.circle`, `observations.circle`, `memory_edge` scope
   (`moveEdgeScope`), `lifecycle_edges.circle` +
   `ratifications.circle` (with sync bump), `knowledge_sources.circle`,
   `entities.scope` (re-keyed, `df` merged on conflict), `concept_entities`
   re-pointed, workstream slugs canonicalized to `workstream:<to>`,
   `lastConceptByCircle` cache re-keyed.
2. `rule_bindings.circle` updated for every moved concept (sync bump).
3. Alias upsert: `INSERT INTO circle_aliases (from_name,to_name,status)
   VALUES (?,?,'active') ON CONFLICT(from_name) DO UPDATE SET
   to_name=?, status='active'` — i.e. row `from→to`.
   **Behavior note:** if `from` was itself an active alias to a third
   circle (`from→x`), the ON CONFLICT overwrite **re-targets** that row
   to `to` (there is NO refusal like archiveCircle's alias guard — see
   RE-18).
4. Repoint: `UPDATE circle_aliases SET to_name=? WHERE to_name=?`
   (`to` ← `from`) — every alias that pointed at the old name now points
   at the new one, keeping the graph one-hop-flat.
5. `refreshGateSidecar()`.

Returns `{from,to,action:'renamed',conceptsUpdated,observationsUpdated,
edgesUpdated,entitiesUpdated}`.

## mergeCircle(from, into, {resolution})

- `resolution`: `'forceNew'` (default) or `'auto'`. Guards mirror rename
  (`*`, sharing scope, registered sources, source concepts, retired) but
  check **both** circles.
- Per concept in `from` (ORDER BY rowid):
  - **workstreams are SKIPPED in the per-concept loop and relocated by the
    whole-circle move** — `moveCircleScopedTables` moves them (reported as
    `moved`, or `merged` when the source workstream drains into an existing
    destination workstream via `workstreamMerges`). This is the **1.6.1 fix
    for RE-19** (re-verified against `engine.ts` 2026-08-14): v1.5.2
    hard-deleted them (`hardDeleteNativeConcept`) and counted `noop`; they
    now survive the merge with open items intact.
  - everything else goes through `reassignCircle(id, into,
    {resolution})`: `forceNew` keeps near matches distinct and flags them
    (`possible_duplicate_of` edge), `auto` deduplicates into the target.
- Alias upsert `from→into` + repoint `to_name=from → into` (same as rename).
- Returns `{from, into, conceptResults:[{action:'moved'|'merged'|'noop',
  conceptId, fromCircle, toCircle, observationsMoved}],
  counts:{moved, merged, noop, error:0}}`.
- **`counts.error` is hardcoded 0** (still true in 1.6.1), but now by-design:
  the whole merge runs under one `immediateTransaction` that rolls back
  atomically on any item failure, so a per-item error count is moot.

## archiveCircle / unarchiveCircle

```js
archiveCircle(e){
  // refuse '*'
  let t = SELECT to_name, status FROM circle_aliases WHERE from_name = e;
  if (t && t.to_name !== e && t.status === 'active')
    throw "cannot archive 'e': it is an alias pointing to 't.to_name' — archive the canonical circle instead";
  INSERT INTO circle_aliases (from_name,to_name,status) VALUES (?,?,'archived')
    ON CONFLICT(from_name) DO UPDATE SET to_name=?, status='archived';  // e→e
}
unarchiveCircle(e){ /* same alias guard */ UPDATE circle_aliases SET status='active' WHERE from_name=?; }
```

- Archive = **self-alias row `e→e` with `status='archived'`**. Unarchive
  flips status back to `'active'` (which also makes `e` resolvable as its
  own alias).
- Hide semantics: store-wide recall filters via
  `LEFT JOIN circle_aliases archived ON archived.from_name=c.circle AND
  archived.status='archived' ... AND archived.from_name IS NULL`
  — applied in `search` (no-circle branch), `listCircles`, overview/recent
  listings. **Explicit-circle access is NOT filtered** (RE-16) and
  **`storeInternal` has no archived guard** (RE-17).
- Both refuse `*` and refuse operating on an active alias that points to a
  different circle (must archive the canonical circle).

## migrateLegacyStarCircle — open-time auto-migration

Runs on **every open** (constructor/migrate path, after schema DDL and
sync-column backfill; before the gate-sidecar refresh).

- Detects any population still living in circle `'*'`: concepts,
  knowledge_sources (table-guarded), lifecycle_edges OR ratifications,
  circle_aliases `from_name='*'`, circle_aliases `to_name='*'`. None → no-op.
- Else `immediateTransaction`:
  1. `destination = chooseLegacyStarDestination()` — `rd` = `"legacy-star"`,
     or `legacy-star-2`, `-3`, … while the name collides with any
     concept circle, alias name (either side), knowledge-source circle,
     lifecycle edge, or ratification.
  2. `moveCircleScopedTables('*', dest, ts, deviceId)`.
  3. `DELETE FROM circle_aliases WHERE from_name='*'` (FROM side is
     vacated and must stay unresolvable now that `*` is reserved).
  4. `UPDATE circle_aliases SET to_name=dest WHERE to_name='*'`
     (repoint star targets).
  5. Gate generation bump (`Vr`) if anything changed.
- After a successful move, `console.error` advisories (not logs) report
  how many concepts / knowledge sources / normative rows moved, and that a
  `*`-named circle was legal before 1.3.1's reservation.

## listCircles (and memory_circle_manage list action)

- Native concepts + authorized source publications; per circle:
  `{circle, concepts, lastActivity, archived}`; `LIMIT 20`, ordered
  `lastActivity DESC, circle ASC`; archived excluded unless
  `includeArchived:true`; optional `exclude` param.
- `memory_circle_manage` `list` action calls with `includeArchived:true`.

## Sync / graft integration

- `circle_aliases` converges with the house `(sync_revision, sync_writer)`
  pattern (`graftRows` upsert guarded by `excluded.sync_revision >
  circle_aliases.sync_revision OR (= AND writer >)`); graft refuses `*` on
  either side.
- Sync payload (`pz`) exports **active** aliases only as `{from,to}` plus
  a `circles` set = concept circles (excluding `*`) ∪ all alias from/to
  names (any status).
- `gate_meta.generation` is bumped by triggers
  `trg_circle_aliases_bump_on_insert` / `_on_update` (OF to_name, status) /
  `_on_delete` — alias changes invalidate gate caches.

## Issues found (RE-16..RE-19)

- **RE-16** — Explicit-circle recall bypasses the archive hide.
  `search(circle=X)`, `listMemories(circle=X)`, and explicit-circle
  variants select `WHERE circle = resolvedName` with NO archived join; the
  archived LEFT-JOIN filter applies only to store-wide (no-circle)
  queries. Additionally, because `resolveCircle` ignores `status='archived'`
  rows, an **active alias pointing to an archived circle name** resolves to
  that name and returns its concepts. Hide is recall-default, not a hard
  boundary.
- **RE-17** — `storeInternal` has no archived-circle guard: `memory_store`
  into an archived circle succeeds silently and the concept lands in a
  hidden circle (invisible to store-wide recall until unarchived). Archive
  hides recall, not writes. **E2E-confirmed 2026-08-14** (`test24`):
  store into an archived circle returns `action='ambiguous'` with a live
  `conceptId`, and the concept lands in the archived circle (DB
  `concepts.circle` = the archived name). Note the engine does have an
  `isArchivedCircle` helper, but it is consulted only by
  `assertArchivedCircleMoveAllowed` (reassignCircle's archived-destination
  door for circle-local blocking rules) — `storeInternal` never calls it.
- **RE-18** — `renameCircle` does not refuse when `from` is an active
  alias pointing to a third circle (archiveCircle does). The ON CONFLICT
  upsert silently re-targets that alias row to the new name. Documented
  behavior; likely to surprise.
- **RE-19** — ~~`mergeCircle` HARD-DELETES workstream concepts~~
  **FIXED in 1.6.1** (E2E XPASS `test23` + `engine.ts` cross-check,
  2026-08-14). v1.5.2 hard-deleted workstream concepts
  (`hardDeleteNativeConcept`) and counted them `noop` — a destructive merge
  path for workstreams only, with no confirmation or tombstone. In 1.6.1 the
  per-concept loop skips `kind='workstream'` and `moveCircleScopedTables`
  relocates them (`moved`, or `merged` into an existing destination
  workstream), preserving open items byte-intact. The `counts.error`
  hardcoded-0 note remains but is now by-design (atomic `immediateTransaction`
  rollback makes a per-item error count moot).
- **RE-56** — `reassignCircle` moves a concept into an ARCHIVED circle with no
  archived-landing disclosure. Its only archived intervention is
  `assertArchivedCircleMoveAllowed` (engine.ts:4165), which REFUSES only
  circle-local live blocking RULES being moved to an archived destination;
  every other concept (incl. a principle/preference without a live blocking
  rule) moves freely bar the reserved `*` breadth-guard, and the receipt
  `{action, conceptId, fromCircle, toCircle, observationsMoved}` names the
  destination circle but no `guidance`/`archived`/`landedInArchivedCircle`
  clause — so the caller is not told the row now sits OUTSIDE store-wide
  recall. The move itself is intended (reassigning into an archived circle is
  a legitimate way to shelve a concept); the gap is disclosure parity with the
  #101 checkpoint fix (which added `landedInArchivedCircle`+`guidance` to
  `memory_checkpoint`, RE-51). Upstream #101 names reassignCircle as a
  remaining undisclosed path alongside declare() (RE-55). Structural (the
  archive-move already has the assert door; the disclosure gap is entangled
  with it — no clean separate MCP behavioral surface) → L2 (S3), registered
  2026-08-31 (monet-e2e#32).

## Verified constants

| Constant | Value | Role |
|----------|-------|------|
| `W` | `"*"` | reserved global-breadth marker (not a circle) |
| `rd` | `"legacy-star"` | legacy-`*` migration destination base |
| alias statuses | `active`, `archived` | only two ever written; rows never deleted by user ops |
| `listCircles` cap | 20 | `LIMIT 20`, lastActivity DESC |
| merge `resolution` | `auto` / `forceNew` (default) | dedup vs keep-distinct-and-flag |
| legacy dest suffix | `-2`, `-3`, … | collision-avoidance from `rd` |
| gate triggers | 3 | insert / update(to_name,status) / delete on circle_aliases |
