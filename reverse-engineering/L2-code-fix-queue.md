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

## Active fix queue — 7 confirmed bugs (non-deprecated)

### S2 (scalability / operability / security — will bite in production)

| Issue | Test | Bug |
|-------|------|-----|
| RE-26 | test29 | `gate_events` has no retention/pruning — one row per `stage_lookup` call; will become the largest table (2–3 orders > `resolution_events`). |

### S3 (missing signal / UX / maintenance risk)

| Issue | Test | Bug |
|-------|------|-----|
| RE-17 | test24 | `memory_store` into an archived circle succeeds silently (no guard); the `isArchivedCircle` door exists but store never consults it. |
| RE-07 | test22 | `limit` truncation is silent — no flag tells the caller more matches existed. |
| RE-04 | test30 | Lexical rank arm is Latin-script-only — Korean/Japanese queries (and stored content) get zero lexical contribution. |
| RE-33 | test31 | `slow-queries.jsonl` is write-only — no doctor/CLI/MCP surface reads it. |

### S4 (cosmetic / by-design note)

| Issue | Test | Bug |
|-------|------|-----|
| RE-21 | test27 | `/api/graph` `graphDensity` counts `possible_duplicate_of` edges, inflating structural density. |
| RE-32 | test32 | `livingModelCard` discards the ranking score + per-signal breakdown — ordering is opaque. |

## Pending XFAIL confirmation (S2, `open` — join the active queue once E2E-confirmed)

| Issue | Status | Bug |
|-------|--------|-----|
| RE-43 | open | `monet repair` self-deadlocks on every English-only target — `recheckNonEnglish` opens a second connection while `applyRepair` holds exclusive ownership → `SQLITE_BUSY` (deterministic, single-process). |
| RE-44 | open | `monet materialize` renders an unsynthesized (dirty) skeleton concept's concatenated body as governing text — no `dirty`/`needsSynthesis` guard; silent wrong governing text on the always-on surface. |

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

- Active queue = 7 confirmed (E2E XFAIL), 0 speculative. Structural issues
  (`source` status, e.g. RE-42 S1 repair `--target`) are deliberately excluded
  here — they route to code-fix separately but are not E2E-observable.
- Deprecation path = 5 source-subsystem issues, deferred until sources are
  un-retired (reversible docs withdrawal, per the author).
- Re-verify the whole XFAIL set on each `@team-monet/monet` version bump; an
  XFAIL→XPASS flip means the bug shipped fixed and this table shrinks.
