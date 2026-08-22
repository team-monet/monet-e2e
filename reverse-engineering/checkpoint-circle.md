# Checkpoint / workstream-save module (memory_checkpoint)

> Reverse-engineered from readable TS source — `packages/core/src/mcp-server.ts`
> (the wired handler) + `packages/core/src/engine.ts` (the storage path).
> AGPL-3.0-only. Owns two issues: **RE-51** (archived-circle disclosure gap).

## Boundary / responsibility

`memory_checkpoint` is the save-side sibling of `memory_store` (writes) in the
recall lifecycle. A caller addresses ONE of `circle`/`inbox`/`workstream` (or a
combined inbox+workstream pair) and the tool persists a durable work/progress
row. Two writer families:

- **Workstream save** — `core.saveWorkstream(input, { circle })` writes a
  `kind='workstream'` concept (payload.status ∈ {active,done}; `open` slots
  mapped wire→engine via `{kind,text}→{slot,text}`).
- **Find capture** — `core.captureFind(inbox, { circle })` mutates the
  "reserved inbox" row (a workstream whose title is the inbox address); the
  physical UUID is deliberately unusable as an address.

### Wire handler (mcp-server.ts:1816-1853)

- Registered with `registerTool` (the only tool that bypasses the
  `server.tool` in-flight patch — checkpoint tracks its own in-flight work via
  `trackedCheckpointHandler`, Codex round 3 on #212).
- `resolvedCircle = scope(circle)` **is the only circle resolution** — it maps
  the caller's request to a real (possibly empty-string) circle name, but
  **NEVER consults `isArchivedCircle`**.
- Touch history: a session-declared workstream with only `kind`s (no id/title)
  resolves to the last-touched workstream for the circle via
  `touchedWorkstreamByCircle`, else the input is taken verbatim.
- Combined inbox+workstream: the handler runs `previewWorkstreamCheckpoint`
  (all-or-refusal dry-run) BEFORE `captureFind` mutates the inbox, so a
  deterministic refusal cannot strand an unreturned find. Only embed-time and
  concurrent-writer failures can split the pair, and both are disclosed by the
  error the caller receives.
- Receipt on success names the landing circle + the workstream
  `{id,title,opened,closed}` (workstream arm) or the inbox effect.

## RE-51 — archived-circle checkpoint writes with NO disclosure (confirmed 1.7.1)

**Bug** (upstream #81, sev:major): `memory_checkpoint` writes workstream saves
and find captures into an **archived circle with no `guidance`/`archived`
clause** on the receipt, and no refusal. Both `saveWorkstream` and `captureFind`
resolve the circle and write without consulting `isArchivedCircle`.

- The engine's ONLY archived-circle disclosure is the storeInternal guard from
  PR #78 (RE-17, `memory_store` path). Checkpoint/save never routes through it
  (`previewWorkstreamCheckpoint` and the save both take `{circle}` and write).
- Archive correctly hides store-wide recall, not writes — so the ROW is fine;
  the MISSING DISCLOSURE is the bug. A caller checkpointing into an archived
  circle gets a receipt naming the circle with no signal that the row now sits
  OUTSIDE store-wide recall (an entry recorded, then invisible to later
  search).
- Reproduction (isolated, run 65 E2E on installed 1.7.1): store anchor →
  `memory_circle_manage{archive}` → `memory_checkpoint{workstream}` on the
  archived circle → receipt `{circle, workstream:{id,title,opened,closed}}` (NO
  archived signal); DB `concepts` row (kind='workstream') genuinely lands in the
  archived circle name.
- **Desired contract (test54 XFAIL):** refuse cleanly, OR disclose the archived
  landing on the receipt (mirror RE-17's guidance-clause pattern).

**Status:** `confirmed`, e2e_test `test54`, severity S2. Sibling of RE-17
(store path); RE-51 is the checkpoint/save path — the two are the same
"archive is not consulted + no disclosure" family across writer surfaces.

## References / cross-module

- `circle-routing.md` — RE-16/17/18 archive semantics (archive = self-alias
  `status='archived'`, hides store-wide recall only; explicit-circle bypass).
- `mcp-server.md` — the wire layer (result shaping, `ok()`/`err()` receipt
  shaping, auto-prewarm).
- `storage.md` — the write path / hidden-writer contention context.