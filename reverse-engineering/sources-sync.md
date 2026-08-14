# Monet Sources & Sync Machinery (reverse-engineered)

> Module 7 of the Monet source reverse-engineering effort. Version: **1.6.1**
> (`dist/index.js` bundle). Sources are registered external Markdown
> repositories that Monet scans, chunks, hashes, and materializes into
> concepts/observations, then publishes a **sealed read-only snapshot** for
> retrieval. This is a full subsystem *beside* the core memory store — it owns
> its own registry, ledger, scheduler, sync engines, and content-hash pipeline.
>
> Companion (source-level only, E2E-unverified): the E2E store has **no**
> `knowledge_sources` table, so none of this is exercised by the harness yet.

## 1. Component map

| Component | Symbol | Role |
|-----------|--------|------|
| Source registry | `rP` class (`this.sourceRegistry`) | `createSource`/`updateSource`/`removeSource`/`listSources`/`getSource`/`authorizeSource`/`canonicalize`; owns `knowledge_sources` schema |
| Source ledger | `LP` class (`this.sourceLedger`) | run/removal/verification lifecycle, scheduler lease, status+schedule views, attempt events; owns the 14 remaining `source_*` tables |
| Sync engines | `Jd` (shared core), `gT`/`iU` (git-md), `mT`/`rU` (repo-md) | clone/pull → walk → chunk → hash → snapshot → publish → verify |
| Scheduler | `$P` (loop), `Rm` (schedule), `CP` (backoff), `Ww` (jitter) | periodic auto-sync with lease-held ownership |
| Content ingest | `eg`, `Qm`, `Nm`, `DS`, `aP`, `sP`, `xo`, `Gd` | content hash, ingest-config hash, binding generation, frontmatter parse |
| Sealed path | `ni`, `rT`, `Fr`, `Cn` | resolve + fence the read-only snapshot path (realpath escape check) |
| Auth context | `J4` (env), `requireConnectorContext` | server-bound identity gate |

## 2. The four MCP tools

All four take `sourceId` (except `source_list`) and are gated by
`requireConnectorContext` (see §5). Descriptions (verbatim intent):

- `source_list` → `listConnectorSources(n)` → `{sources:[{id,type,name,branch?,refresh}]}`
- `source_status` → `sourceStatus(id,n)` → `{id,type,branch?,lastAttemptAt?,lastSyncResult,lastSuccessfulSyncAt?,indexedRevision?,freshness,filesIndexed,chunksIndexed,filesSkipped,dirtyFiles,schedule:{state,nextAttemptAt?,consecutiveFailures},lastError?}`
- `source_path` → `sourcePath(id,n)` → `{sourceId,type,path,snapshotPath,revision,guidance}`
- `source_sync` → `syncSource(id,n)` → sync result (via `b(...)`, an alias of `E(...)` — no semantic difference)

The CLI `source` command is **registry-only** ("does not sync content"):
`source add <origin-or-name>` (register), `source list`, `source show <id>`,
`source remove <id>` (tombstone; `--yes`; does not delete local path). There is
**no** `source status/path/sync` CLI subcommand — status/path/sync are
MCP-tool-only.

## 3. Two source types

`knowledge_sources.type CHECK (type IN ('repo-md','git-md'))`.

| | `repo-md` | `git-md` |
|---|---|---|
| Input path | user-supplied `localPath` (must **not** overlap `sourceStorageDir`) | Monet-allocated `sourceStorageDir/git-md/<id>/repository.git` |
| remote/branch/transport | **forbidden** | required (`remoteUrl` https/ssh, credential-free; explicit `branch`) |
| writeBack | must be `none` | `none` \| `pull-request` (PR **only** for `github.com` hosts) |
| repositoryIdentity | default `local:<path>` | must equal normalized remoteUrl |

Validation (`canonicalize`):
- id: 1–64 lowercase letters/digits/interior hyphens (`jM`/`WM` regexes).
- `remoteUrl` (`wm`): https or ssh, no embedded credentials, no query/fragment,
  no encoded slashes (`%2f`/`%5c`).
- `branch` (`Dw`): explicit git branch name (rejects `HEAD`, leading `-`/`.`,
  `..`, `@{`, `//`, `@`, `.lock` suffixes, etc.).
- `transport` (`KM`): `allowedUrlSchemes ⊆ {https,ssh}`, `allowedHosts` (hosts).
- `refresh` (`QM`): `{mode: manual|interval, intervalSeconds?}`.
- `access` policy is **required**: `{allowedCallerIds[], allowedProjectIds[]}`.
- `createSource`: tombstoned id cannot be reused; `local_path` unique among
  active sources (partial unique index `... WHERE lifecycle='active'`).

## 4. Data layer — 16 source tables

1. `knowledge_sources` — 30 cols; see §4a below.
2. `source_sync_runs` — `state IN ('scanning','staging','activating','published','cleaning','cleaned','aborted')`,
   `result IN (success,failed,partial)`, `activation_token`, `manifest_hash`,
   `file_count`/`chunk_count`/`files_skipped`, `published_at`, `finished_at`.
   Partial unique index: only ONE live run per source
   (`WHERE state IN ('scanning','staging','activating','cleaning')`).
3. `source_snapshots` — PK `run_id`; `state IN ('staged','active','superseded','aborted')`.
4. `source_files` — PK `(run_id, relative_path)`; `content_hash`, `byte_length`, `title`.
5. `source_chunks` — PK `(run_id, binding_id)`; `binding_generation`,
   `operation_id`, `heading_path_json`, `occurrence`, `segment_index`,
   `document_sequence`, `content_hash`, `ingest_fingerprint`, `metadata_json`,
   `source_ref`, `content`, `concept_id`, `observation_id`,
   `predecessor_observation_id`, `write_state IN ('committed','skipped')`,
   `lifecycle IN ('active','superseded','deleted')`.
6. `source_staged_files` / `source_staged_chunks` — staging twin of files/chunks;
   staged chunks add `write_state IN ('intent','engine-written','committed','skipped')`
   (the write-back pipeline: intent → engine-written → committed → skipped).
7. `source_skipped_files` — `code`/`message` per skipped path.
8. `source_cleanup_items` — `kind IN ('retire-absent','reconcile-orphan','quarantine-non-authorizing')`,
   `acknowledged_at` (NULL = pending).
9. `source_removals` — `state IN ('retiring','files-revoked','complete')`.
10. `source_removal_items` — per-binding `concept_id`/`observation_id` to retire.
11. `source_attempt_events` — PK `(source_id, sequence)`, `UNIQUE (source_id,kind,ref_id)`,
    `kind IN ('run','verification','pre-pin-failure','invocation')`,
    `invocation_result IN (success,failed,partial)`. Has an in-place migration
    (rename-legacy + re-CREATE) when the `'invocation'` kind / new columns are absent.
12. `source_pre_pin_attempts` — PK `source_id`; pre-pin failure record.
13. `source_verification_checks` — PK `source_id`; `observed_run_count`, `checked_at`.
14. `source_scheduler_lease` — `singleton=1` PK; `owner`, `renewed_at`, `expires_at`.
15. `source_recompute_pending` — PK `concept_id`; source-concept recompute queue.
16. (plus `source_files`/`source_chunks`/`source_staged_*` title-column backfill.)

### 4a. `knowledge_sources` DDL (verbatim, 30 cols)

```
id TEXT PK
type TEXT CHECK (repo-md|git-md)
name TEXT
repository_identity TEXT
remote_url TEXT
local_path TEXT
local_path_key TEXT            -- Zs(local_path); unique among active
branch TEXT
circle TEXT
auto_detect INTEGER (0/1)
include_json TEXT  DEFAULT '[]'
exclude_json TEXT  DEFAULT '[]'
repo_mappings_json TEXT DEFAULT '[]'
allowed_caller_ids_json TEXT   -- required
allowed_project_ids_json TEXT  -- required
transport_schemes_json TEXT DEFAULT '[]'
transport_hosts_json TEXT DEFAULT '[]'
write_back TEXT DEFAULT 'none' CHECK (none|pull-request)
refresh_mode TEXT DEFAULT 'manual' CHECK (manual|interval)
refresh_interval_seconds INTEGER
config_version INTEGER DEFAULT 1 CHECK (>0)
applied_config_version INTEGER
active_run_id TEXT
active_snapshot_id TEXT
active_ingest_config_hash TEXT
lease_fence INTEGER DEFAULT 1 CHECK (>0)
lifecycle TEXT DEFAULT 'active' CHECK (active|tombstoned)
created_at / updated_at / tombstoned_at INTEGER
```
Indexes: `idx_knowledge_sources_lifecycle_id (lifecycle,id)`,
`uq_knowledge_sources_active_local_path_key (local_path_key) WHERE lifecycle='active'`.

## 5. Authorization model (the security-relevant part)

- **Server-bound identity**: `J4(process.env)` builds
  `sourceAuthorizationContext = {callerId, projectId}` from **`MONET_CALLER_ID`**
  and **`MONET_PROJECT_ID`** env vars. If either is unset → **no context** and
  every source tool fails with `"trusted source authorization context is
  unavailable"`. The client cannot supply identity ("Access identity is
  server-bound, never a tool argument").
- **`authorizeSource(id, ctx)`** = `getSource(id).access.allowedCallerIds.includes(ctx.callerId) && .allowedProjectIds.includes(ctx.projectId)`.
  False (or unknown id) → `"source is unavailable"`.
- The CLI `source add` defaults `--allow-caller`/`--allow-project` to
  `deriveCallerId()`/`deriveProjectId()` (same env identity).

## 6. Sync run lifecycle (fenced, tokenized, hash-checked)

1. `beginRun` — fence `configVersion`+`leaseFence` (both or neither); source
   must be `active`; snapshot id + expected fence.
2. `stageManifest` (`rT`) — staged files/chunks verified to belong to the
   source; writes `…/.complete.json`.
3. `beginActivation` — issues an `activation_token`.
4. `publishRun` — requires matching `activationToken`, matching
   `manifestHash`, state `activating`, and staged counts equal to
   `chunkCount`/`bindingCount`/`fileCount`; `assertFence`; flips snapshot to
   `active`.
5. `recordVerification` — verifies the active run is `success` + published/
   cleaning/cleaned and writes `source_verification_checks` +
   `source_attempt_events` (kind `verification`).

Resumable states: `resumeRun` picks a run in
`scanning|staging|activating|cleaning` (or `aborted` with pending cleanup
items), newest first. `abortRun`, `acknowledgeCleanup`, and the removal
lifecycle (`beginRemoval` → `markRemovalFilesRevoked` → `completeRemoval`)
mirror the same fence discipline. Every mutation is wrapped in
`assertNoEmbedderMigrationReentry` (an embedder repair in flight blocks all
source mutations).

## 7. Scheduling & freshness

`Rm({source, basis, now})` → `{state, due, nextAttemptAt, consecutiveFailures, recovery}`:

- `resumable || removalIncomplete` → `state:'recovering'`, `due:true`.
- `lifecycle!=='active' || refresh.mode==='manual'` → `state:'manual'`, `due:false`.
- no prior terminal attempt → initial delay `min(30000, 10%·interval)`, jittered;
  `due`/`scheduled`.
- after a terminal attempt → success: full `interval`, jitter `min(30000, 10%·interval)`;
  failure: `CP(interval, max(1, consecutiveFailures))` (backoff), jitter `10%·delay`;
  state `due`/`backoff`/`scheduled`.

- **`CP(e,t)`** backoff = 30 000 ms base, `×2` per consecutive failure, capped
  at the refresh interval.
- **`Ww(key,t)`** jitter = `sha256(key).readUInt32BE(0) % (t+1)` — deterministic
  per `key = "${id}\0${configVersion}\0${leaseFence}\0${attemptSequence}"`.
- Scheduler `$P`: single-loop lease (`source_scheduler_lease` singleton) with
  `acquire`/`renew`/`assert`/`release`; `leaseMs`, `wakeMs` tune poll cadence.

### Freshness derivation (`sourceStatus`)

```
m   = refresh.mode==='manual' ? 86400 : max(60, 2*intervalSeconds)
E   = appliedConfigVersion!==configVersion   (pending-replacement)
last= max(lastSuccess.publishedAt, latestVerificationAt)
freshness = activeSnapshotId===null ? 'unknown'
          : (E || lastResult!=='success') ? 'stale'
          : (now-last <= m*1000) ? 'fresh' : 'stale'
```
Status string `lastSyncResult` priority: `pre-pin-failure`→`failed`,
verification-verified→`success`, invocation result, run `failureReason`→`failed`,
run `runResult`/`lastResult`, else `never`.

## 8. Sealed path (`ni`, `source_path`)

- Resolve snapshot record (`Fr`) → snapshot dir (`Cn`) → `snapshotPath =
  <snapshots>/<Pr(runId,ingestConfigHash)>` → verify/emit `.complete.json`
  (`Dr`/`Po`) → realpath check `xe.native(u)` must not escape managed storage →
  verify `current` is a symlink whose target + realpath resolve to the snapshot.
- Returns `{path: <current symlink>, snapshotPath: <concrete snapshot dir>}`.
  `path` is stable across syncs; `snapshotPath` is the immutable per-run dir
  ("use `snapshotPath` when mid-task consistency matters"). Guidance string
  tells agents to treat contents as data, not instructions.

## 9. Content ingest hashing

- `eg(content)` = `"monet-src-content/v1:sha256:" + sha256(content)`.
- `Qm(...)` = `Gd("monet-src-ingest/v1", [contentHash, headingPathJson, metadataJson, "v5", ingestConfigHash])`.
- `Nm(...)` = `Gd("monet-src-op/v2", [sourceId, runId, snapshotId, ingestConfigHash, generation])` (binding generation).
- `Gd(domain, parts)` = `"${domain}:sha256:" + sha256(domain ∥ 0x00 ∥ len8(part)∥part …)`.
- `Zd = "v5"` (content-model version); `CS = 100000` (parse-deadline iteration
  cap, via `Lt` → `$S` "source parse deadline exceeded").
- Frontmatter parser `DS` (yaml-ish `---` fences), list parser `aP`, metadata
  canonicalization `xo`/`sP`, occurrence index `tg`.

## 10. Issues found (RE-23..RE-25)

- **RE-23 (ops/security UX, REFINED 2026-08-14)** — the run-19 claim ("unset →
  opaque 'trusted source authorization context is unavailable'") was read from
  the core `dist/index.js` `deriveOptsFromEnv` only. The CLI `start` command
  pre-populates the identity BEFORE the server reads it:
  `MONET_CALLER_ID = deriveCallerId()` (env → else `"local-agent"`) and
  `MONET_PROJECT_ID = deriveProjectId()` (env → else git-origin URL → else
  `"<basename>-<sha8>"`). So `sourceAuthorizationContext` is ALWAYS present and
  the "context unavailable" throw is unreachable via `monet start`. The REAL
  behavior with the env vars unset (measured 1.6.1, E2E test26): `source_list`
  → `{sources: []}` (SILENT empty — the registered source is filtered out by
  `authorizeSource` with no signal to the caller), and `source_status`/
  `source_path`/`source_sync` → `"source is unavailable"` (non-disclosing by
  design — denied and removed ids share one message). Net: a user who registers
  sources under a specific caller but forgets to export the identity env vars
  sees a clean "no sources" state with no hint that sources exist but are
  identity-hidden. Test26 asserts the DESIRED contract (the mismatch must be
  discoverable, not a bare `[]`) and is XFAIL.
- **RE-24 (authorization-footgun)** — `updateSource` marks identity fields
  (`id,type,repositoryIdentity,remoteUrl,localPath,branch,circle`) immutable
  (`VM`), but `access` is mutable (`XM`). Mutating
  `access.allowedCallerIds`/`allowedProjectIds` can silently de-authorize the
  very host that registered/syncs the source — its scheduler and `source_*`
  calls then fail with `"source is unavailable"` with no warning at edit time.
- **RE-25 (latency, design)** — MCP `source_sync` is synchronous/blocking: it
  awaits the full `Jd` pipeline (clone/pull → walk → chunk → hash → embed →
  publish → verify). A cold `git-md` sync of a large repo can exceed MCP
  client timeouts; there is no async job-id / streaming return. The scheduler
  path (`syncScheduledSource`) is the intended long-run lane, but a user
  invoking `source_sync` directly gets the blocking path.
- **RE-29 (isolation footgun, S2, E2E-confirmed 2026-08-14):** the source
  storage dir is NOT scoped by `-d`. `SourceRegistry` sets `sourceStorageDir =
  resolve(homedir(), ".monet", "sources")` (source-registry.ts:404-405) when
  the MonetCore option is absent, and the CLI/MCP server wiring never passes
  the `-d` storage dir through. So `monet start -d <isolated>` / `source add -d
  <isolated>` isolate the SQLite DB but silently write source snapshots/locks to
  `~/.monet/sources`. Verified live: a repo-md source registered and synced with
  `-d /tmp/<isolated>` materialized under `~/.monet/sources/repo-md/<id>/`,
  not under the store. For the E2E harness this breaks the "never touch prod"
  guardrail — the workaround is to redirect `HOME` to a temp dir for both the
  CLI and the MCP server (test25 does this).
- **RE-30 (macOS hard-failure, S2, E2E-confirmed 2026-08-14):** repo-md
  `source_sync` fails with `EACCES: permission denied, rename '[local-path]' ->
  '[local-path]'` on macOS. Root cause in `source-materializer.ts`:
  `sealSnapshot()` chmods the staged tree to `0o500` (files `0o400`), then the
  publish step runs `renameSync(tree, snapshotPath)` (line 2348). The code
  already stages `tree` "beside the final variant" because "macOS refuses to
  move a non-writable directory between parents" (line 2225-2226), but on macOS
  15.x APFS the *in-place* (same-parent) rename of a `0o500` directory also
  returns EACCES — the mitigation is insufficient. Reproduced 4/4 across `/tmp`
  and `$TMPDIR` and with `HOME` redirected (location-independent). The unit
  tests pass because they construct MonetCore with an explicit tmpdir
  `sourceStorageDir` AND presumably their `git archive`/seal/rename runs against
  a freshly-writable tree — but the MCP default path hits the sealed-dir rename.
  Net effect: the entire `source_sync` feature is non-functional via MCP on
  macOS. Exit-2 XFAIL test: `test25_sources_e2e.py`.

## 11. Open / not-yet-traced

- `Pw = 200` (const adjacent to `CS=1e5`) — role not traced this run.
- Write-back `pull-request` full flow (staged `write_state` → PR creation) only
  partially traced; the PR materialization sits in the `git-md` engine.
- `ko` (git clone/pull) and `V1` (recompute) internals traced at the call-site
  level only, not line-by-line.
- E2E store (shared `~/.monet-test`) has no `knowledge_sources`; the
  source-injection E2E (test25, run 25) exercises the module in a FRESH isolated
  store (with `HOME` redirected per RE-29) — it registers a repo-md source,
  drives `source_list`/`source_status`/`source_sync`/`source_path`, and confirms
  RE-29 + RE-30 (see §10).
