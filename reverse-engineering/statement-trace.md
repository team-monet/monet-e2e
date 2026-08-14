# Statement tracing (SQL hang + slow-query diagnosis)

Source: `src/statement-trace.ts` (readable TS, `@team-monet/core` v0.9.0) + `src/storage.ts`
(wiring) + `src/__tests__/statement-trace.test.ts`, `src/__tests__/store-busy.test.ts`.

## What it is

A hunting instrument, not telemetry. It exists because a `monet start` server was observed
three times in ~24h pegged at 100% CPU inside a single `Statement::JS_all` that never returns,
holding SQLite's write lock and wedging every other client (monet-core#145). The obvious
instrument — time the call, log it if slow — is *structurally blind* to that failure, because
"if it was slow" runs after the call returns and the call never returns.

So the primary record is written **before** the statement runs, and cleared after:

- **In-flight marker** — one fixed-size file per *connection* (`inflight-<pid>-<connectionSeq>.json`),
  rewritten in place at offset 0 before every statement and truncated after it returns. While a
  statement is wedged the file keeps naming it (method, SQL, `startedAt`, nesting `depth`), so any
  outside reader — a shell, another server, a human — can read the culprit and how long it has been
  stuck. This is the whole point: the diagnosis must survive the process being unable to answer.
- **Slow log** (`slow-queries.jsonl`) — appended *after* a statement returns when it took longer
  than the threshold. Covers the other axis: retrieval that still answers but degrades as the corpus
  grows ("search gets worse as it accumulates"), which the in-flight marker cannot see because each
  statement completes.

The two are not redundant: one catches what never finishes, the other catches what finishes too late.

## Key behaviors

- **Env-gated, off by default.** `MONET_TRACE_SQL === "1"` turns it on; any other value (including
  unset, `"0"`, `"true"`) leaves it off. Cost when off is one boolean test in `prepare()` and no
  wrapper object. Cost when on is one `writeSync` to an already-open descriptor per statement (no
  open/close, no allocation beyond the marker buffer).
- **Never breaks a query.** Every write is best-effort inside a try/catch. If the marker descriptor
  cannot be opened, tracing degrades to the slow log alone rather than failing.
- **A stack, not a slot.** `begin`/`end` maintain a frame stack so nested statements (an
  `immediateTransaction` runs BEGIN IMMEDIATE, then body statements, then COMMIT) leave the marker
  naming the *innermost* SQL still executing, and fall back to "BEGIN IMMEDIATE" once the body
  finishes. Without the stack, the last inner statement would blank the marker and a hang in COMMIT
  (a real way to block on the write lock) would show an empty file.
- **One file per connection.** Two ports in one process keep independent frame stacks; sharing
  `inflight-<pid>.json` would let the inner connection's `end` truncate the outer transaction's
  marker. A reader globs `inflight-*.json`, not one name.
- **SQL clipped** to `STATEMENT_TRACE_SQL_MAX_CHARS` (truncate-then-write at offset 0 so a shorter
  new statement leaves no tail of the previous, longer one — a tail would parse as corrupt JSON
  exactly when read to diagnose a hang).
- **Trace files are 0600** (`openSync` mode + an explicit `fchmod`, because the mode argument only
  applies at creation and these files outlive the process). The live store was observed holding a
  0644 `inflight-*.json` next to a 0600 `gate-journal.jsonl`; the explicit chmod fixes inherited
  looser modes.
- **Traces all SQL mouths**, not just prepared statements: `prepare`, `run`, `get`, `all`, `exec`
  (97 call sites in core bypass `prepare`), `pragma` (checkpoint/integrity work, unbounded on a
  large store), `transaction`/`immediateTransaction`, and the async `backup`/`backupVerify` path
  (which runs while holding exclusive ownership — the worst place to be blind, #145 exactly). The
  tracer is built *before* the storage constructor's own setup pragmas because `journal_mode = WAL`
  can stall against a busy store at startup.
- **`readInflightStatements(dir)`** is the reader (#148): globs `inflight-*.json`, skips
  missing/half-written/foreign files, returns newest-first. It is **total and never throws**
  (it runs on a failure path already reporting something else). An empty result does NOT mean
  nothing holds the lock — it usually means tracing was off, which the caller must say rather than
  report "no holder".
- **Wired into the lock-contention path.** `storage.ts` reads the markers to name the lock holder
  when a startup cannot take the write lock ("database is locked" → *who* holds it and *since when*;
  SQLite reports contention, never the holder). It filters markers by `dbPath` so several stores
  sharing a directory don't mis-attribute.

## Parameters / constants

| Parameter | Value | Role |
|-----------|-------|------|
| `STATEMENT_SLOW_THRESHOLD_MS` | 1 000 | slow-log threshold |
| `STATEMENT_TRACE_SQL_MAX_CHARS` | 2 000 | SQL clip (marker + slow log) |
| `TRACE_FILE_MODE` | `0o600` | both files, enforced on open + on inherited files |
| `MONET_TRACE_SQL` | `"1"` | single on/off switch (no level) |
| in-flight filename | `inflight-<pid>-<connectionSeq>.json` | one per connection |
| slow-log filename | `slow-queries.jsonl` | append-only JSONL |
| marker schema | `v: 1` + `pid`, `method`, `startedAt`, `depth`, `sql`, optional `dbPath` | — |
| `StatementMethod` | `prepare` \| `run` \| `get` \| `all` \| `exec` \| `pragma` \| `transaction` \| `immediateTransaction` \| `backup` \| `backupVerify` | 10 mouths |

## Issues

- **RE-33** — the slow log (`slow-queries.jsonl`) is write-only. `readInflightStatements` gives the
  in-flight marker a consumer (the lock-contention path in `storage.ts`), but nothing in the
  codebase reads or surfaces the slow log — there is no `doctor`/CLI/MCP path to view
  "search degraded because N statements now exceed 1s". The instrument's second half (the
  retrieval-degradation diagnosis it was built to provide) has no consumer yet. See ISSUES.md.

## Verification

- `statement-trace.test.ts` pins: mid-flight marker names the running statement *from inside the
  call* (read the file mid-`begin`), no-tail rewriting, SQL clipping, `close()` clearing (idempotent,
  and a clean exit does not read as a hang), 0600 permissions incl. tightening an inherited 0644,
  slow-log threshold + "nothing when none slow", throws still clear the marker, all SQL mouths
  traced, transaction stack (BEGIN before callback, fallback to transaction after), per-connection
  marker isolation, exclusive-ownership path traced, close() still traced, prepare-vs-run frames,
  async verified backup bracketed, pass-through when untraced, `:memory:` never auto-traced.
- `store-busy.test.ts` pins `readInflightStatements` contract (parse/sort, empty on missing dir,
  skips foreign files, empty result semantics).
