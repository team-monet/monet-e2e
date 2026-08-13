# Monet Reverse-Engineering — Contradiction Processing (flag / mediate / dismiss)

> Status: **DOCUMENTED** (2026-08-12, run 11-RE). Source: `@team-monet/monet` v1.5.2
> (`dist/index.js`, minified esbuild bundle; core duplicated inside `dist/cli.js`).
> This documents the contradiction subsystem end-to-end (store-side auto-flag, manual
> `memory_flag_contradiction`, `memory_resolve` verdict paths incl. pair-flag dismissal)
> and answers the E2E agent's run-9/run-11 follow-ups (guard source, `reconciledBody`
> naming, `dismissed` vs `resolved` status strings — RE-13).

## TL;DR

A contradiction is a row in `contradictions` with a lifecycle status
`open → resolved | dismissed` (raw string literals — **no shared enum**, RE-13).
While ≥1 `open` contradiction exists for a concept, the concept's `status` column is
`'disputed'`; the column is **derived** — reconciled on every
`recomputeNativeConceptProjection()` as `CASE WHEN open_count > 0 THEN 'disputed' ELSE 'active' END`.

- **Openers**: (1) store-side auto-flag when a `kind="correction"` observation ATTACHES
  to an existing concept; (2) manual `memory_flag_contradiction` (kinds
  value-conflict / staleness / scope-conflict); (3) rule-correction cascade
  (`kind='impeachment'`, internal only).
- **Closers**: `memory_resolve` with a verdict — `accept-new` (correction wins,
  prior superseded), `keep-current` (correction retired, prior kept), `dismiss`
  (no verdict, row retained with `status='dismissed'`); plus auto-closes on
  retire/sync-tombstone/detach (write `'dismissed'`) and on ratify verdicts
  (impeachment → `'resolved'`).

## Where everything lives (exact offsets in dist/index.js v1.5.2)

| Piece | Location | Notes |
|-------|----------|-------|
| `contradictions` DDL | ~682395 | columns below |
| auto-flag on correction attach | store path ~728885 | `t.kind==="correction" && A && (Ne=this.flagContradiction(...))` |
| `flagContradiction(e, t={})` | ~740757 | opener (manual + auto) |
| `resolveContradiction(e, t)` | ~742055 | mediator; both verdict + dismiss branches |
| `dismissPossibleDuplicate(e,t,r)` | ~798850 | pair-flag dismissal (`memory_resolve` conceptA/B path) |
| `recomputeNativeConceptProjection(e,t)` | ~937411 | status derivation / confidence / confirmation |
| `getOpenContradictions(e,t)` / `countOpenContradictions(e)` | ~748634 | overview queue |
| `getOpenContradictionsForConcept(e,t)` / `countOpenContradictionsForConcept(e)` | ~749xxx | fetch-side open list |
| `disputedCount(e)` | ~795635 | overview `counts.disputed` |
| `GT(e)` card formatter | ~989556 | contradiction card fields |
| `memory_flag_contradiction` tool handler | ~1027799 | schema: kind enum [value-conflict, staleness, scope-conflict] |
| `memory_resolve` tool handler | ~1028624..1031400 | schema + param mapping below |
| impeachment close | ~862889 | `UPDATE ... kind='impeachment' AND status='open'` → `'resolved'` on ratify |

## Table schema (`contradictions`, @682395)

```sql
CREATE TABLE IF NOT EXISTS contradictions (
  id TEXT PRIMARY KEY,
  concept_id TEXT NOT NULL,
  observation_id TEXT,                      -- the correcting observation (NULL for manual flags w/o one)
  kind TEXT NOT NULL DEFAULT 'value-conflict',
  status TEXT NOT NULL DEFAULT 'open',
  detail TEXT NOT NULL DEFAULT '',
  resolution_obs_id TEXT,                   -- accept-new: correction id (it WON); keep-current: NULL (it LOST)
  contradicted_observation_id TEXT,         -- the named prior (loser on accept-new; kept prior on keep-current)
  detected_at INTEGER NOT NULL DEFAULT (unixepoch() * 1000),
  resolved_at INTEGER,
  resolved_by TEXT,
  updated_at INTEGER NOT NULL DEFAULT (unixepoch() * 1000),
  sync_revision INTEGER NOT NULL DEFAULT 1,
  sync_writer TEXT
);
```

Rows are **never deleted** — closers only set `status` (+ `resolved_at`/`resolved_by`).

## 1. Openers

### 1a. Store-side auto-flag (correction attach) — @728885
In the store write path, after attach/create resolution:

```js
let A;  // true when the observation ATTACHED to an existing concept (this.attach), false when created
...
if (t.kind === "correction" && A) {
  Ne = this.flagContradiction(M.id, { observationId: d, kind: "value-conflict", detail: `correction: ${Gr(e)}` });
  M = this.getRow(M.id);
}
// Ne?.id is recorded into ingest_operations.contradiction_id
```

- Fires **only when the correction attached** (`A=true`). A correction that fails to
  attach (similarity < tauAttach, or `resolution:"forceNew"`) creates its own concept
  and opens **no** contradiction → the challenge never reaches the prior concept's
  mediation flow (RE-14 candidate, product nuance).
- `Gr(e)` = first sentence of the body, ≤80 chars (77 + "…"); detail becomes
  `correction: <first sentence>`.

### 1b. Manual `memory_flag_contradiction` — handler @1027799
```js
{ conceptId: E, detail: b, observationId: y, kind: v, circle: w }
// kind enum: ["value-conflict","staleness","scope-conflict"]; default "value-conflict"
// validates circleOf(E) === circle; calls t.flagContradiction(E, {detail, observationId, kind})
// returns g({circle, contradictionId, conceptId, status, detail}, ...)
```

### 1c. `flagContradiction(e, t={})` — @740757
```js
flagContradiction(e, t = {}) {
  this.assertNoEmbedderMigrationReentry("flag a contradiction");
  let r = this.getRow(e);
  if (!r) throw ...;                       // concept not found
  if (we(r)) throw ...;                    // source concepts immutable
  if (r.status === "retired") throw ...;
  if (gn(this.db, e, "dispute (contradiction)"), r.kind === "rule") throw ...;  // rules: correct, don't flag
  let i = this.newId();
  let n = this.db.transaction(() => {
    INSERT INTO contradictions (id, concept_id, observation_id, kind, status, detail)
      VALUES (?, ?, ?, ?, 'open', ?)        // status literal 'open'
    UPDATE concepts SET status = 'disputed', confidence = max(.1, r.confidence - .3), updated_at
    UPDATE concepts SET arousal_score = arousal_score + 3, arousal_last_updated_at
    return SELECT * FROM contradictions WHERE id = ?
  })();
  return GT(n);                             // card: id/conceptId/observationId/kind/status/detail/resolutionObsId/...
}
```
Side effects: concept `status='disputed'`, **confidence −0.3 (floor 0.1)**, **arousal +3**.
`gn(..., "dispute (contradiction)")` = lifecycle guard (hd) that throws if e.g. blocked.

### 1d. Impeachment (rule-correct cascade, internal) — @873075
When a rule is corrected, the corrected rule's principle ancestors that are current
skeleton members get `flagContradiction(l, {kind:"impeachment", detail})`, deduped by
`kind='impeachment' AND status='open' AND instr(detail, ...)` probe. Impeachment is
**not** creatable via the manual tool (enum excludes it).

## 2. Mediation — `memory_resolve` handler @1028624..1031400

Tool schema:
```
contradictionId (string, optional — omit for pair dismissal)
decision       (enum ["accept-new","keep-current","dismiss"], optional — "Required contradiction verdict")
body           (string, optional)
contradictedObservationId (string, optional — "live, older, same-concept, distinct from the correction; invalid with dismiss")
resolvedBy     (string, optional)
circle         (string, optional)
conceptAId / conceptBId (string ×2, optional — pair-flag dismissal)
```

Param mapping (destructured): `{contradictionId:E, decision:b, body:y, contradictedObservationId:v, resolvedBy:w, circle:S, conceptAId:I, conceptBId:R}`.
**There is no `reconciledBody` parameter** — the tool prose says "reconciled body", the
actual param is `body` (answers E2E run-9 follow-up).

Dispatch:
1. **Pair-flag dismissal** — if `I!==undefined || R!==undefined`: both required;
   `contradictionId` and `contradictedObservationId` rejected as belonging to the other
   path; both concepts must exist and be in the session circle; calls
   `t.dismissPossibleDuplicate(I, R, w)`; ack `{action:"pair-flags-dismissed", rowsUpdated}`.
2. **Contradiction verdicts** — `contradictionId` + `decision` required;
   `t.circleOfContradiction(E)` must equal session circle; calls
   `t.resolveContradiction(E, {decision:b, body:y, by:w, contradictedObservationId:v})`.
   - `{alreadyClosed:true, contradictionStatus}` when the row was already closed.
   - else ack `{conceptId, status, version, confidence:toFixed(2)}` (from the concept card).

## 3. `resolveContradiction(e, t)` — @742055 (both verdict + dismiss in ONE function)

```js
resolveContradiction(e, t) {
  this.assertNoEmbedderMigrationReentry("resolve a contradiction");
  let r = SELECT * FROM contradictions WHERE id = e; if (!r) return null;
  if (r.status !== "open") return { alreadyClosed: !0, contradictionStatus: r.status };
  let i = r.concept_id;
  // guards: source concepts / retired concepts immovable
  if (t.contradictedObservationId !== undefined && t.decision === "dismiss") throw
    "a dismissal reaches no verdict, so naming a loser is meaningless...";
  let n = this.ensureSession();
  let o = this.db.transaction(() => {
    let s = Date.now();
    if (t.decision === "dismiss") {
      // -------- DISMISS: no verdict, no body, no supersession, no revision --------
      UPDATE contradictions SET status = 'dismissed', resolved_at = ?, resolved_by = ? WHERE id = e
        .run(s, t.by ?? null, e);
    } else {
      // -------- VERDICT path (accept-new / keep-current) --------
      // validate the correcting observation (r.observation_id): exists, same concept, live
      // live = superseded_by IS NULL AND superseded_at IS NULL
      let c = live observation ids of concept i (ORDER BY created_at, rowid);
      let d = r.observation_id === null ? c.length : c.indexOf(r.observation_id);
      let l = c.slice(0, d);                       // priors PREDATING the correction
      if (t.contradictedObservationId !== undefined) {
        // must exist, same concept, live, NOT equal to the correction itself,
        // and in l (predates the correction); r.observation_id === null -> error
      }
      if (t.decision === "keep-current" && l.length === 0) throw
        "no live observation predating the correction to keep. Use decision:\"accept-new\", or \"dismiss\".";
      let u = decision === "keep-current" ? (r.observation_id ? [{loser: r.observation_id, successor: null}] : [])
            : t.contradictedObservationId !== undefined ? [{loser: t.contradictedObservationId, successor: r.observation_id}]
            : (r.observation_id !== null && l.length === 1) ? [{loser: l[0], successor: r.observation_id}] : [];
      let p = u.map(m => m.loser), h = decision === "accept-new" ? r.observation_id : null;
      // ANTI-GUESS GUARD (E2E run-9 finding 13b, exact condition):
      if (t.decision === "accept-new" && r.observation_id !== null
          && t.contradictedObservationId === undefined && p.length === 0
          && l.length > 0 && (t.body === undefined || t.body.trim() === "")) throw
        "cannot resolve this contradiction with accept-new and no reconciled body: the concept has "
        + l.length + " live prior observations and nothing records which one was contradicted, ...";
      if (u.length > 0) {
        UPDATE observations SET superseded_by = ?, superseded_at = ? WHERE id = ? AND concept_id = ?;
        // zero-live-obs safety: if no live observation remains -> throw "would leave concept with zero live observations"
      }
      if (t.body !== undefined) {
        let m = getRow(i), f = m.version + 1, g = m.kind === "workstream" ? m.title : Gr(t.body) || m.title;
        UPDATE concepts SET body = ?, title = ?, version = ?, updated_at WHERE id = i;   // body replaced
        this.writeRevision(i, f, t.body);        // +1 concept_revisions row (E2E 13c/14c)
      }
      UPDATE contradictions SET status = 'resolved', resolution_obs_id = ?, contradicted_observation_id = ?,
             resolved_at = ?, resolved_by = ? WHERE id = e
        .run(h, t.contradictedObservationId ?? null, s, t.by ?? null, e);   // status literal 'resolved'
      UPDATE concepts SET last_confirmed_at = ?, last_confirmed_session_id = ? WHERE id = i;
      UPDATE concepts SET arousal_score = arousal_score + 1, arousal_last_updated_at = ? WHERE id = i;
    }
    return this.recomputeNativeConceptProjection(i, this.nextSyncTimestamp()), mt(this.getRow(i));
  })();
  return this.refreshGateSidecar(), o;
}
```

### Verdict semantics (source-confirmed, matches E2E findings 13/14)

| Aspect | accept-new | keep-current | dismiss |
|--------|-----------|--------------|---------|
| status written | `'resolved'` | `'resolved'` | `'dismissed'` |
| `resolution_obs_id` | correction id (h) | NULL | NULL (row untouched) |
| loser superseded | named prior, or sole prior (conservative), or none (body required) | the correction itself (`superseded_by=NULL, superseded_at=now`) | none |
| body | optional; if given replaces concept body + title + `writeRevision(version+1)` | same | **ignored entirely** (no validation, no revision — E2E run-11 next-step #2 pre-answered) |
| body required? | ONLY when ≥2 live priors predate the correction AND no contradictedObservationId AND no body (anti-guess guard) | n/a (but ≥1 prior required) | NO (works on multi-obs concepts) |
| last_confirmed_at / arousal | set / +1 | set / +1 | NOT touched |
| needsSynthesis | untouched (stays True — re-armed by the correction attach) | same | same |
| concept status after | 'active' via recompute (0 open left) | same | same |

The **anti-guess guard** is a hard rule inside `resolveContradiction` (not the handler):
fires only for `accept-new` when the correction has **≥2 live priors** (`l.length>0` and
no automatic sole-prior loser selected, i.e. `p.length===0`), no `contradictedObservationId`,
and no `body`. Boundary matches E2E: prior=1 → OK body-less (sole prior auto-superseded);
prior≥2 → refused without body; `dismiss` never guarded.

`keep-current` on a contradiction with no prior (`l.length===0`) is refused
("no live observation predating the correction to keep").

## 4. Pair-flag dismissal — `dismissPossibleDuplicate(e,t,r)` @798850

Operates on `memory_edge`, NOT `contradictions`:
- Edge types: `Lz = ["possible_duplicate_of", "extraction_candidate"]` (@662903; `zf` = quoted SQL list).
- Validations: both concepts exist, not source concepts, same circle.
- Transaction: if no undismissed flag edge between the pair → `{dismissed:true, rowsUpdated:0}`
  (idempotent no-op); else
  `UPDATE memory_edge SET dismissed_at = ?, dismissed_by = ?, sync_updated_at = ? WHERE scope = ? AND type IN (possible_duplicate_of, extraction_candidate) AND dismissed_at IS NULL AND (bidirectional pair)`.
- Ack: `{action:"pair-flags-dismissed", conceptAId, conceptBId, rowsUpdated}`.

### 4a. Retire guard — undismissed pair flags block `memory_retire` (Finding 21, E2E run 17)

E2E-verified 2026-08-13 (test20): `memory_retire` on a concept that carries an
undismissed `possible_duplicate_of` / `extraction_candidate` pair flag is
REFUSED, not auto-closed:

```
cannot retire <id>: it carries 1 undismissed pair flag(s) (a duplicate or
extraction question about it and another memory), which retiring would erase
rather than answer — paired with <partner> (possible_duplicate_of) — withdraw
it through memory_resolve with conceptAId="<id>" and conceptBId set to a
partner above
```

- The refusal fires BEFORE the `retireConcept` auto-close of open contradiction
  rows (section 7): the concept is not retired, no rows are touched.
- Recovery = dismiss the pair first via `memory_resolve{conceptAId, conceptBId}`
  (section 4) → ack `{action:"pair-flags-dismissed", rowsUpdated:2}` → then
  `memory_retire` succeeds.
- Rationale (from the error text): retiring would "erase rather than answer"
  the open duplicate/extraction question — the guard preserves the pair
  question for a human verdict.
- Determinism note: two same-circle `memory_store` calls with distinct content
  but a shared token routinely produce a `possible_duplicate_of` pair flag
  (observed 3/3 in run 17), so the guard is easy to trigger in tests.

## 5. Status derivation & confidence — `recomputeNativeConceptProjection` @937411

Called at the end of every resolve/dismiss (and many other mutation paths). Derives:
- `open_count` / `resolved_count` / `last_resolved_at` from `contradictions WHERE concept_id = ?`.
- `o = (open_count ?? 0) > 0`.
- Both the empty-obs branch and the main branch write:
  `status = CASE WHEN o THEN 'disputed' ELSE 'active' END` — **the concept status column
  is derived from open contradictions, not independently managed**.
- Confidence (main branch): `l = min(1, .6 + max(0, distinctSessions-1)*.1 + resolved_count*.2)`,
  `u = o ? min(.5, l) : l` — **disputed caps confidence at 0.5**; each resolved
  contradiction adds 0.2 to the confidence factor.
- `last_confirmed_at` reconciliation uses a **2-second heuristic window**
  (`last_confirmed_at - E.created_at < 2000` ms) to detect the confirming session.

## 6. Read surfaces

- `getOpenContradictions(e, t)` — circle-scoped, `status='open'`, non-source concepts,
  `ORDER BY detected_at ASC, id ASC`, optional LIMIT; detail truncated at `LT=200`
  (`…[truncated]`). Feeds `memory_overview.openContradictions` (+`openContradictionsOmitted`).
- `countOpenContradictions(e)` — same filter, COUNT.
- `getOpenContradictionsForConcept(e, t)` — fetch-side, newest-first (`detected_at DESC`).
- `disputedCount(e)` — `COUNT(*) WHERE status='disputed' AND kind!='source' ...` →
  `memory_overview.counts.disputed`.
- `memory_fetch` card (@1018800): adds `status` + `openContradictions`
  **only when the column is `'disputed'`** (`k.status==="disputed"?{status, openContradictions:[...]}:{}`).
  After a resolve (column back to 'active') the fields vanish — consistent with E2E 13d
  (nuance: the fetch card DOES surface dispute while disputed; "not a fetch-card field"
  holds post-resolution).

## 7. Auto-closes outside `memory_resolve`

| Path | Writes |
|------|--------|
| `retireConcept` (@768213) | `status='dismissed'`, `resolved_by='retireConcept'` for open rows |
| sync tombstone graft (@910344) | `status='dismissed'`, `resolved_by='sync-tombstone'` |
| detach / concept-move paths (@781211, @781557, @781978) | re-point `concept_id` or `status='dismissed'`; restore `'active'` when open count hits 0 |
| ratify verdicts (@862889) | impeachment rows → `status='resolved'` (only `kind='impeachment'`) |

## Issues found

- **RE-13 (CONFIRMED from E2E run-11 follow-up)**: contradiction statuses
  (`'open'` / `'resolved'` / `'dismissed'`) are raw string literals scattered across
  6+ functions (`flagContradiction` insert, `resolveContradiction` ×2 branches,
  `retireConcept`, sync-tombstone, detach, impeachment-close,
  `recomputeNativeConceptProjection` count CASE, `getOpenContradictions` filters).
  **No shared enum / constant map.** The two verdicts write different statuses
  (`'dismissed'` vs `'resolved'`) but from the SAME function — not version-dependent in
  v1.5.2, and the drift risk is contained relative to cross-module duplication, but any
  status rename/extension must touch every literal (also `resolved_by` sentinels
  `'retireConcept'`/`'sync-tombstone'` are magic strings).
- **RE-14 (new)**: store-side auto-flag fires only when the correction **attaches**
  (`A=true`). A `kind="correction"` store that creates a new concept (below tauAttach,
  or `forceNew`) opens no contradiction — the correction is silently isolated from the
  prior concept's mediation flow. Product question: should a failed-attach correction
  at least surface a possible-duplicate or a note?
- **RE-15 (new, minor)**: `memory_fetch`'s `status`/`openContradictions` fields depend on
  the derived column being reconciled. Any path that opens/closes contradictions without
  a subsequent `recomputeNativeConceptProjection` would leave the column stale; today all
  closers do recompute (verified), so this is a latent coupling, not a live bug.

## E2E cross-references (verified against tests 6/14/15)

- test06 (single-prior contradiction, accept-new body-less OK) — matches: prior=1 → sole
  prior auto-superseded, guard not armed.
- test14 finding 13b (multi-obs accept-new refused without body) — exact guard condition
  captured above; synthesize state irrelevant (guard keys only on observation count).
- test14 finding 13c (resolve-with-body → status=active, +1 revision row) — body branch
  replaces body and `writeRevision(version+1)`; status restore via recompute.
- test15 finding 14 (dismiss: row retained `status='dismissed'`, resolved_by set, kind
  kept, body/obs/revisions untouched) — dismiss branch confirmed; note the resolve ack
  still returns a concept card (recompute + mt run for dismiss too).
- Run-11 next-step #2 pre-answer: `dismiss` WITH a `body` is accepted by the handler and
  **silently ignored** by `resolveContradiction` (no revision, no validation error).
- test20 (run 17): retire-guard Finding 21 — `memory_retire` REFUSED on a concept with an
  undismissed pair flag; `memory_resolve{conceptAId,conceptBId}` → `pair-flags-dismissed`
  (rowsUpdated 2) → retire succeeds. First E2E of the pair-flag dismissal path
  (section 4) end-to-end, plus live dashboard filter delta (concepts 2→1,
  includeRetired=1 → 2).
