# Monet Repair / Doctor / Resegment CLI (`repair-cli.ts`)

> `monet doctor`, `monet repair`, `monet resegment` — the embedder-recovery
> surface. Readable TS `packages/cli/src/repair-cli.ts` (1204 lines), core 0.9.0.
> Cross-referenced against upstream issues #14 / #15 (filed JohnOnLee 2026-08-16,
> recreated from the private monet-client tracker).

## What it is

Three CLI commands built on a single testable dependency seam
(`RecoveryCliDependencies`). The module is the *operator* surface for the
embedder-pin machinery that `diagnostics.ts` (the `doctor` preflight) and
`storage.ts` (exclusive-ownership + verified backup) provide. It is **not** a
semantics layer — it orchestrates `inspectStoredEmbedderState`,
`instantiateEmbedderForPin`, `BetterSqlitePort`, and `MonetCore` in a
backup-first, refuse-loud order.

## Commands

| Command | Purpose |
|---------|---------|
| `monet doctor [-d dir] [--json] [--check-provider]` | Read-only diagnosis of pin / vectors / migration / non-Latin count. Exit 2 when not `safe`. |
| `monet repair --target <id> \| --resume \| --abandon` | Preview or apply a verified, backup-first embedder rewrite. |
| `monet resegment [-d dir] [--circle name]` | Rebuild observation segments in the current space (the pre-#155 granularity fix, now shipped). |

## Doctor path (`runDoctor`)

- `inspectOrThrow` wraps `inspectStoredEmbedderState` (never opens a port → no
  lock is ever taken on this path).
- `--check-provider` loads the exact pinned provider (`checkProvider`) and runs
  `reconcileProviderWithStore` — the width-compatibility proof (provider `dim`
  vs the store's one uniform live width). `unproven`/`incompatible` is a
  verdict, not a crash.
- Output is human or one stable JSON object under `RECOVERY_SCHEMA`
  (`monet.recovery.v1`). Exit code: 0 safe, 1 error, 2 not-safe.

## Repair path (`runRepair`)

Sequence, in order:

1. `selectMode` — exactly one of `--target` / `--resume` / `--abandon`.
   `--apply` requires `--yes` (repair never prompts); `--yes` is valid only with
   `--apply`.
2. `ensureInspectableForRepair` — refuses nonexistent store, failed integrity,
   newer-than-supported schema, or `unknown` pin/migration.
3. `resolveTargetAlias` maps the `--target` string (see the RE-42 hazard below).
4. `checkProvider` preflights the target: `instantiateEmbedderForPin` → probe
   embed of `PROBE_TEXT` → `validateEmbeddingProviderOutput`. Unavailable →
   refuse with next commands.
5. No-op detection: empty-unpinned store, or store already on the target pin with
   `assessment === "safe"` → preview reports `repairRequired: false`.
6. **One-way non-Latin guard** — see the guard box below.
7. `applyRepair` (see below).

### `applyRepair` (the write)

`createPort` → `createVerifiedBackup(destination)` (takes exclusive SQLite
ownership) → `recheckNonEnglish` (re-reads the non-Latin count **under** that
ownership) → `createCore` → `migrateEmbeddings` → `resegmentObservations`.

Two deliberate choices worth recording:

- **Resegment-after-migration** runs in the same command, *outside* the
  migration transaction (migration drops `observation_segments` rather than
  re-embedding). It is reported, **not thrown**: the migration already committed,
  so a resegment failure must not look like a failed migration (which would send
  an operator to restore a backup they don't need). Retry is `monet resegment`.
- **Failure capture** aggregates the operation error *and* a close error
  (`AggregateError` when both), re-inspects the store, and throws
  `RepairOperationError` carrying `{dbPath, inspection, provider, nextCommands,
  backup}` so the surfaced error always names a recovery path.

### The one-way non-Latin guard (targetEnglishOnly)

Before `--apply`, a move onto an English-only target
(`provider?.readsOnlyLatinScript === true`) is refused when the store holds
non-Latin rows, unless `--accept-non-latin-loss` is passed. Three hardening
notes in the source: (a) `--yes` cannot stand in for this decision — it is an
explicit *second* flag; (b) **unknown is not zero** — a failed non-Latin scan
refuses rather than failing open; (c) `guardedMode` also covers a `resume`
whose sentinel is `rewriteProgress: "not-started"` (the operator never saw the
refusal the first time).

## Resegment path

Standalone `resegment` command. Refuses: nonexistent store (checked *before*
`createPort`, which would otherwise create an empty file), failed integrity,
an `active` migration sentinel (the pin is a promise, not a fact), or a pin
whose provider is not proven compatible with the stored width. Idempotent by
protocol (segments deleted + reinserted per observation in one transaction).

## Parameters

- `RECOVERY_SCHEMA` = `monet.recovery.v1` (JSON envelope schema).
- `PROBE_TEXT` = `"Monet embedding-provider recovery preflight"` (provider probe).
- Backup path = `<dir>/backups/monet-before-repair-<UTC>-<uuid>.db`.
- Repair modes = `target` / `resume` / `abandon` (exactly one).
- `resolveTargetAlias` special-cases = `onnx` / `hashing` / blank / `dim:` prefix.
- Guard = `provider?.readsOnlyLatinScript === true` + `--accept-non-latin-loss`.
- `guardedMode` = `target` OR (`resume` && migration `active` && `rewriteProgress === "not-started"`).
- `recheckNonEnglish` = constructed only when `guardedMode && targetIsEnglishOnly && !acceptNonLatinLoss`.

## Issues

- **RE-42 (S1, source → upstream #15):** `resolveTargetAlias` returns any
  unrecognized string verbatim as "an exact model ID"; nothing between there and
  the irreversible `migrateEmbeddings` asks whether the string names a model
  profile this build actually describes. `instantiateEmbedderForPin` accepts any
  `owner/repo`-shaped id, `dim` is corrected by measurement (so no mismatch
  trips), and `readsOnlyLatinScript` is `undefined` for an unregistered target
  (so the one-way English-only guard **cannot fire for exactly the inputs it
  exists to catch**). Two shapes: (a) a typo → a download error misread as a
  network problem; (b) a loadable-but-unregistered id → the store is silently
  repinned into an unmeasured space (`mean` pooling, `LEGACY_UNMEASURED_THRESHOLDS`,
  fallback budgets), with the verified backup as the only mitigation. Fix
  constraint: the profile registry (`MODEL_PROFILES`) is module-private in core,
  so the gate belongs on this CLI surface and needs core to expose a
  "is-this-a-known-profile" accessor.
- **RE-43 (S2, open → upstream #14):** `recheckNonEnglish` calls
  `inspectStoredEmbedderState(dbPath)`, which opens a **second** better-sqlite3
  connection, while `applyRepair`'s port still holds exclusive ownership
  (`createVerifiedBackup` retains it; `releaseExclusiveOwnership` is only in the
  catch path). The second open waits out `timeout: 5000` and fails
  `SQLITE_BUSY`. Deterministic self-deadlock for every English-only target (the
  recheck closure only exists for that intersection). Only workaround is
  `--accept-non-latin-loss`, which switches off the very guard the recheck exists
  to enforce. Fails closed (no rewrite, backup retained) — hence S2 not S1.
