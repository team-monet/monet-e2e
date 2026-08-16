# Monet Materialize CLI (`materialize-cli.ts`)

> `monet materialize [add|remove|list]` — the standing-file skeleton renderer.
> Readable TS `packages/cli/src/materialize-cli.ts` (719 lines), core 0.9.0.
> Cross-referenced against upstream issue #23 (JohnOnLee 2026-08-16).

## What it is

The CLI half of the skeleton-mirror mechanism: it renders the store's governing
skeleton (ratified principles + preferences) into a managed block inside
registered "standing files" (e.g. `AGENTS.md`), and records block/state hashes
so `agent_context` can report `mirrorStale`. The core half — `skeletonBodies()`
/ `inspectSkeletonMirrors()` — lives in `engine.ts` / `skeleton-mirror.ts`.

## Surface model

- A **surface** = `{ path: <absolute>, scope }` where `scope` is `"global"` or
  `{ circle: <name> }`. Registered via `materialize add <path> --global | --circle`.
- The **registry/manifest** is `<storeHome>/materialize.json`:
  `{ surfaces: [], materialized: {} }`. The `materialized` key is the **raw
  absolute path string** — never realpath-resolved, case-folded, or
  Unicode-normalized (a cross-package interchange contract that core's prewarm
  also reads).
- Scope and delivered members are **breadth-disjoint**: a global surface delivers
  only `breadth === "global"` members, a circle surface only `breadth === "local"`
  members — so global members aren't double-delivered into every project file.

## Render pipeline (`materializeOne`)

1. Read the surface (lossless-UTF-8 check; dangling symlink and non-UTF-8 both
   refuse rather than rewrite through U+FFFD).
2. Locate the existing `<!-- BEGIN monet:skeleton … -->` … `<!-- END monet:skeleton -->`
   span (`findSkeletonBlock`; malformed/duplicated markers throw).
3. `deliveredMembers` = `core.skeletonBodies()` filtered by breadth.
4. `renderSkeletonBlock` → `# Principles` / `# Preferences` sections, each
   member's `body` emitted verbatim, joined by `\n\n`.
5. `nextSurfaceText` splices the block in place (preserving all surrounding
   bytes) or appends it with minimal separators.
6. `writeSurface` → `atomicWriteFile` (reused from install-cli) with a
   **best-effort CAS**: compare destination bytes to the read snapshot
   immediately before rename; concurrent edit → refuse, don't overwrite.

## Freshness & minimization

- `materialize list` prints `fresh` / `stale` / `block-missing` /
  `never-materialized` per surface; three states need no store open (computed
  from manifest + file alone), the store is opened only when a previously
  materialized block needs its `skeletonState` re-checked.
- `materializeOne` short-circuits when `prior.skeletonState === skeletonState`
  and `prior.blockHash === sha256(existing span)` — the "minimization" principle
  (nothing to regenerate → retain all bytes and hashes).

## Guards (poisoning / aliasing / concurrency)

- **Marker poisoning** — scope label, circle name, and every member body are
  checked for the control-marker substrings; a rendered block must contain
  exactly one marker pair.
- **Same-destination aliases** — `canonicalSurfaceDestination` (realpath walk)
  detects two registered paths resolving to one file and refuses both (add +
  materialize).
- **Reserved `*` circle** — `circle '*'` is the global-breadth marker, never a
  queryable circle; refused with a pointer to `--global`.
- **Registry CAS** — the manifest write also compares against its read snapshot
  (a concurrent add/remove is refused, not clobbered).

## Parameters

- `BEGIN_MARKER` = `"<!-- BEGIN monet:skeleton"`, `END_MARKER` = `"<!-- END monet:skeleton -->"`.
- `MaterializeScope` = `"global"` | `{ circle: <name> }` (circle `*` refused).
- `MaterializeFreshness` = `fresh` / `stale` / `block-missing` / `never-materialized`.
- `DeliveredMember` = `{ conceptId, species: "principle"|"preference", body, breadth: "global"|"local" }`.
- `canonicalSkeletonState` = `sha256` of canonical JSON: members sorted by
  `conceptId` (code-unit `<`/`>`), keys `conceptId, body, breadth`, no whitespace.
- Registry/manifest = `<storeHome>/materialize.json`; `materialized` key = raw absolute path.
- Write CAS = best-effort byte-snapshot compare-and-swap before rename (surface + registry).
- Error classes = `MaterializeCliError` / `RegistryConflict` / `MarkerCollision` /
  `DestinationAlias` / `LossyDecode`.

## Issues

- **RE-44 (S2, open → upstream #23):** `deliveredMembers` → `renderSkeletonBlock`
  emits `member.body` verbatim, and `skeletonBodies()`/`skeletonMemberRows`
  (engine.ts) select `c.body` with a filter on `status='active'` + latest
  `verdict IN ('approve','re-ratify')` but **no `dirty`/`needsSynthesis` guard**.
  So a skeleton principle amended via `memory_declare` (attach → dirty → body =
  unreconciled concatenation of old + new paragraphs) is materialized as
  *governing text*, and `mirrorStale` reports green on the same turn because the
  block hash faithfully matches the store value. A surface emits a verdict
  ("mirror current") where it holds a not-known ("mirror matches a body nobody
  reconciled"). Fix shape: refuse to materialize while any skeleton member is
  dirty (name the concept + what to run), or synthesize-on-read before rendering.
