# Monet L2 Code-Fix Queue (for John's prioritization)

> Consolidated, severity-ordered list of the **confirmed** behavioral bugs,
> each with its E2E XFAIL test that reproduces it. This is the promotion list:
> nothing here is speculative — every row is `confirmed` (E2E-reproduced, not
> just source-read). Promotion to a fix is John's call; this file is the input.

Status vocabulary matches `ISSUES.md`. Severity: S1 data loss / S2 scalability/
operability / S3 missing-signal / S4 cosmetic.

## ⚠️ Product-direction signal (2026-08-16) — source subsystem provisionally retired

The **source subsystem** (`monet source` CLI + `source_*` MCP tools) is
**"provisionally retired"** per the author's own commit message
(team-monet/monet `eafaf3c`, John Lee, 2026-08-15, shipped as v1.6.3): *"Stop
documenting the provisionally retired source subsystem … Documentation only —
the commands and MCP tools are untouched and still work. Withdrawing docs is
reversible; a user's dependency on a withdrawn feature is not."*

**RE-30, RE-29, RE-24 (S2), RE-23 (S3), and the RE-30-blocked RE-05 are all
source-subsystem (or source-search) issues — moved OFF the active fix queue and
onto a deprecation path (below).** If the subsystem is removed, the bugs become
moot; fix them ONLY if sources are revived. The three source E2E tests
(test25/26/28) remain in the suite as regression guardrails while the tools
still ship, but their XFAILs no longer imply an urgent fix.

## Active fix queue — 14 confirmed bugs (non-deprecated)

### S2 (scalability / operability / security — will bite in production)

| Issue | Test | Bug |
|-------|------|-----|
| RE-26 | test29 | `gate_events` has no retention/pruning — one row per `stage_lookup` call; will become the largest table (2–3 orders > `resolution_events`). |
| RE-43 | test33 | `monet repair` self-deadlocks on every English-only target — `recheckNonEnglish` opens a second connection while `applyRepair` holds exclusive ownership → `SQLITE_BUSY` (deterministic, single-process). Fails closed (backup retained). |
| RE-44 | test34 | `monet materialize` renders an unsynthesized (dirty) skeleton concept's concatenated body as governing text — no `dirty`/`needsSynthesis` guard; silent wrong governing text on the always-on surface. |
| RE-45 | test36 | `busy_timeout=5000` starved by concurrent write bursts; `memory_fetch` is a hidden writer — the unprotected usefulness-bump UPDATE (and optional inline synthesize) fail the whole fetch under contention, so a pure read returns `database is locked`. |
| RE-47 | test38 | `correction-attach` exemption (resolution.ts:261-277) attaches a `kind="correction"` in the ambiguous band (sub-tauAttach) to the evidence-nominated concept and disputes it — intent disambiguates WHAT a correction asserts, not WHICH concept a weak (0.55–0.70) cosine points at. A wrong correction is absorbed AND marks an innocent concept `disputed`. **Fix is a product decision** (fork instead of attach, or raise the correction floor — upstream #52 "suggested directions" #2/#3). |
| RE-51 | test54 | `memory_checkpoint` writes (workstream `saveWorkstream` / find `captureFind`) into an ARCHIVED circle with NO disclosure — neither path consults `isArchivedCircle` (the storeInternal guard from PR #78 / RE-17 is the only archived check), and the receipt names the landing circle with no `guidance`/`archived` clause → a checkpointed row sits OUTSIDE store-wide recall invisibly. Write is correct; missing disclosure is the bug (upstream #81, sev:major). Sibling of RE-17 on the checkpoint/save path. Fix = add the archived disclosure/refusal to both save+capture. |

### S3 (missing signal / UX / maintenance risk)

| Issue | Test | Bug |
|-------|------|-----|
| RE-17 | test24 | `memory_store` into an archived circle succeeds silently (no guard); the `isArchivedCircle` door exists but store never consults it. |
| RE-07 | test22 | `limit` truncation is silent — no flag tells the caller more matches existed. |
| RE-04 | test30 | Lexical rank arm is Latin-script-only — Korean/Japanese queries (and stored content) get zero lexical contribution. |
| RE-33 | test31 | `slow-queries.jsonl` is write-only — no doctor/CLI/MCP surface reads it. |
| RE-48 | test38 | `memory_store` ack omits the attach target's title/slug — the MCP envelope drops the `concept.slug`/`title` the engine already computes, so a mis-merge is invisible without a separate `memory_fetch`. Trivial fix (thread slug/title into the envelope on an attach/ambiguous resolution). |
| RE-52 | test55 | `monet install` CRASHES (unhandled JS TypeError) instead of refusing cleanly on a malformed `hooks.PostToolUse*` section — `validateSettingsShape` (install-cli.ts:1019) validates ONLY `PreToolUse` and early-returns `{ok:true}` when it is absent, so PostToolUse values skip shape-validation and reach `upsertHandlerForEvent`, whose `group.hooks.filter(...)` throws (`i.filter is not a function` / `(t ?? []) is not iterable`). Desired: refuse cleanly like the wrong-shape PreToolUse arms (test37 F/G). Fix = extend shape-validation to PostToolUse*. |

### S4 (cosmetic / by-design note)

| Issue | Test | Bug |
|-------|------|-----|
| RE-21 | test27 | `/api/graph` `graphDensity` counts `possible_duplicate_of` edges, inflating structural density. |
| RE-32 | test32 | `livingModelCard` discards the ranking score + per-signal breakdown — ordering is opaque. |

## Deprecation path (on-hold — fix only if the source subsystem is revived)

> Source-subsystem issues, `provisionally retired` (`eafaf3c`, v1.6.3). The
> commands still ship, so the E2E XFAILs stay as guardrails, but fixing them is
> deferred until sources are un-retired.

| Issue | Test | Severity | Bug |
|-------|------|----------|-----|
| RE-30 | test25 | S2 | `source_sync` fails `EACCES` on macOS — `sealSnapshot` chmods the tree `0o500` then `renameSync` into place; APFS refuses the in-place rename of a non-writable dir. **Blocks RE-05.** |
| RE-29 | test25 | S2 | `sourceStorageDir` hard-defaults to `~/.monet/sources` and is NOT scoped by `-d` — isolated-source work silently writes to prod. |
| RE-24 | test28 | S2 | `source update --allow-caller <other>` REPLACES the caller list and silently de-authorizes the acting caller (rc=0, no warning). |
| RE-23 | test26 | S3 | `monet start` derives a fallback identity when `MONET_CALLER_ID`/`MONET_PROJECT_ID` are unset, so `source_list` silently returns `[]` — the identity mismatch is not discoverable. |
| RE-05 | — | S4 | Source concepts skip `nativeScoreFloor` (any score>0 enters) while native concepts below floor are dropped — unverifiable until RE-30 is fixed. |

## Structural (source-status) issues — L2 design-decision queue

> `source`-status findings: no clean behavioral XFAIL (E2E can't assert a desired
> contract that doesn't exist yet), but each is a real fix candidate needing a code
> or design change. Promoted by the supervisor's DIRECTION `L2 코드수정 대기열`,
> not by an XFAIL flip. John's call on whether/how.

| Issue | Severity | Problem | Design options / fix locus |
|-------|----------|---------|----------------------------|
| RE-42 | S1 | `monet repair --target` accepts any unrecognized string as an exact model id → silent unmeasured repin (`mean` pooling, legacy thresholds, fallback budgets); typo reads as a network error. Needs core to expose a "known profile" accessor (registry is module-private). | repair-cli.ts `resolveTargetAlias` + a profile-registry check |
| RE-46 | S2 | No `interrupt`/progress handler (better-sqlite3 11.10.0 API) bounds *holding* a lock; `inspectStoredEmbeddingRows`/`readLiveEmbeddingRows` materializes every row's full embedding JSON via `.all()` before folding. | storage.ts / embedding-state.ts |
| RE-50 | S2 | Startup failure cannot say why it died — `server.connect()` (mcp-server.ts:3491) is the first MCP-utterable moment; `ensureEmbedderPin()` + entry-point store-open/model-load run before it, so every cause reads as "Connection closed". Fail-closed is deliberate, so this is a design commitment. | Degraded serving mode vs out-of-band diagnosis vs narrowing the causes (upstream #13 options 1/2/3) |

## Dependencies / unblock ordering

- **RE-30 → RE-05**: RE-05 is the last `open` behavioral issue and cannot be
  E2E-verified until `source_sync` works on macOS (RE-30). Both are on the
  deprecation path, so this dependency is also on-hold.
- **RE-29 + RE-30 share test25**: both live in the sources/sync path; a single
  sources-sync hardening pass can address both — deferred with the subsystem.

## Already fixed (removed from the queue)

- RE-19 (S2, mergeCircle hard-deletes workstreams) — **fixed in 1.6.1**, verified
  XPASS via test23.

## Notes

- Active queue = 14 confirmed (E2E XFAIL), 0 speculative. Structural issues
  (`source` status, e.g. RE-42 S1 repair `--target`) are deliberately excluded
  here — they route to code-fix separately but are not E2E-observable.
- Deprecation path = 5 source-subsystem issues, deferred until sources are
  un-retired (reversible docs withdrawal, per the author).
- Re-verify the whole XFAIL set on each `@team-monet/monet` version bump; an
  XFAIL→XPASS flip means the bug shipped fixed and this table shrinks.
