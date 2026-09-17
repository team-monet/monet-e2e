# Guardrail registry

> Rules the autonomous agent must follow. The agent may add new rules, but
> **must record the reason**. Git history is the audit log.

## Active guardrails

| ID | Rule | Added | Added by | Reason | Status |
|----|------|-------|----------|--------|--------|
| GR-01 | Never touch the real store — tests run in an isolated dir (`monet start -d ~/.monet-test`) | 2026-08-08 | John/Coda | Test isolation — protect real data | Active |
| GR-02 | No external publishing (PRs/deploys/public posts) | 2026-08-08 | John/Coda | No external actions without approval | Active |
| GR-03 | Progress is judged by data (test count/coverage/failure rate) | 2026-08-08 | John/Coda | "It improved" is not a metric | Active |
| GR-04 | On stagnation, try a different angle or notify the user | 2026-08-08 | John/Coda | Handle LLM repeated-run plateaus | Active |
| GR-05 | Every run must be recorded in the diary + metrics | 2026-08-08 | John/Coda | Observability — a human must be able to look back | Active |
| GR-06 | Tests must be re-run safe (unique circles/tokens, no state pollution; token-scope queries in unrestricted/cross-circle searches too) | 2026-08-08 | Coda | Run 1: re-running on the same circle made dedup merge into a previously-resolved concept and broke the contradiction test. Extended 2026-08-11: generic unrestricted queries break ranking-cutoff assertions once the shared DB accumulates similar content from prior runs | Active |
| GR-07 | Assertions must be falsifiable — no tautologies (e.g. `X or not X`, `x in (0, None) or x is not None`, membership/empty-string checks against a constant) | 2026-08-14 | Coda | Run 20 (issue #1): two always-true assertions in test01 inflated the "assertion count = quality" metric by ~0.5% while verifying nothing; fixed and registered as a standing rule | Active |
| GR-08 | Any source-derived claim must name its baseline: either a pinned commit/tag of `~/monet/monet`, or "dist `<version>`" for the shipped bundle. A bare "verified against main" is not evidence | 2026-09-14 | Coda | Run 110: the local clone was silently 39 commits behind `origin/main` (= Release 1.11.0); 32 of the 48 `*.ts` files cited across `reverse-engineering/*.md` had changed in that window, so `file:line` citations inherited from clone-era reads describe an older tree than the shipped product | Active |

| GR-09 | Every run must MEASURE the suite it reports: never carry a suite tally forward from a previous run, and never call the suite green without executing it in that run. A harness test whose pinned target no longer exists or no longer compiles against the monorepo is **STALE** (test exit 5, its own class) — not PASS, not FAIL — and provides NO coverage until re-baselined | 2026-09-18 | Coda | Run 118: standby records (114/116/117) each wrote "no bump → no re-suite" and carried `FAIL 0` forward, while 4 driver tests (test42/43/46/49) had been failing since the monorepo moved to `9fa38c2`; nothing had executed the tally. Suspending the suite is exactly how harness drift hides | Active |

## Change history

| Date | Change | Reason | Recorded by |
|------|--------|--------|-------------|
| 2026-08-08 | GR-01–GR-05 initially registered | Pilot start | Coda |
| 2026-08-08 | GR-06 added — re-run safety | Run 1 test06 re-run failure (circle state pollution) | Coda |
| 2026-08-11 | GR-06 extended — token-scope unrestricted queries | Run 6 test05 failure: generic cross-circle query + accumulated DB pushed fresh concept below ranking cutoff | Coda |
| 2026-08-14 | GR-07 added — falsifiable assertions (no tautologies) | Run 20 issue #1 fix: 2 dead assertions in test01 | Coda |
| 2026-09-14 | GR-08 added — pin the source-read baseline | Run 110 state check: clone 39 commits behind `origin/main` (1.11.0); 32/48 cited TS files changed since | Coda |
| 2026-09-18 | GR-09 added — measure the suite you report; `STALE` (exit 5) class for drifted tests | Run 118: a carried-forward `FAIL 0` hid 4 driver tests failing since the 2026-09-15 monorepo pull (`9fa38c2`) | Coda |
