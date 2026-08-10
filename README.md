# Monet E2E

End-to-end test suite for [Monet](https://github.com/team-monet/monet) — local-first, MCP-native memory for AI agents.

This repository continuously exercises Monet against a real server process and a real SQLite store: what an agent stores today must be retrievable tomorrow, in isolation, under concurrency, and across schema migrations.

## Repository layout

```
.
├── harness/          # reusable test harness
│   ├── mcp_client.py          # zero-dependency MCP stdio client (env-configurable)
│   ├── run_all.py             # suite runner: runs every test in ../tests/
│   └── make_fixture_schema4.py# generator for the old-schema (1.2.4) fixture
├── tests/            # one self-contained scenario per file (testNN_*.py)
├── diary/            # run-by-run narrative (what, why, result, next)
├── METRICS.md        # progression table — the source of truth for coverage
├── GUARDRAILS.md     # operating rules for the autonomous agent
└── .github/ISSUE_TEMPLATE/    # bug / test suggestion / feedback
```

## How this repository is maintained

This repo is maintained by an **autonomous agent** running on a schedule (currently 08:00 and 20:00 AEST), with a human in the loop for decisions and external actions. Understanding this model helps you interpret the commit history and the state of the repo.

**The agent's per-run loop:**

1. **Read state** — `METRICS.md`, `GUARDRAILS.md`, and recent `diary/` entries to understand where the suite stands.
2. **Check issues** — lists open issues in this repo. New issues are handled first: reproduce, add/fix a test, update docs.
3. **Decide** — what to work on this run. Priority: open issues → failing tests → new scenarios.
4. **Execute** — runs the suite against an isolated data dir (never the real store, GR-01) using the real MCP client (initialize → tools/list → store → search).
5. **Record** — appends to `diary/`, updates `METRICS.md` (tests / coverage / failure rate), and adds guardrails when a new rule is needed.
6. **Sync** — commits and pushes to this repo. All public-facing content (docs, commit messages) is in English.

**What that means for you:**

- **`METRICS.md` is the living status report** — check it for current coverage instead of any table in this README (which is why this README doesn't restate scenario lists; they go stale).
- **Every commit is attributable to a run** — the diary entry for that date explains what happened and why.
- **Guardrails are rules, not suggestions** — GR-01 (isolation) and GR-06 (re-run safety) are the two that matter most if you add tests.
- **Issues are the feedback channel** — file a bug, suggest a scenario, or ask anything. The agent picks up new issues on its next run, and replies on the issue.

## Requirements

- Python 3.9+
- Node.js (18+; the Monet package is a Node CLI)
- The Monet npm package installed globally:
  ```sh
  npm install -g @team-monet/monet
  ```
- For the schema-migration test you also need an old `@team-monet/monet@1.2.4` install — see "Schema fixture" below.

## Running

```sh
export MONET_CLI=$(which monet)          # optional: path to Monet CLI (defaults to `monet` on PATH)
export MONET_NODE_PATH=/path/to/node/bin # optional: node bin dir to prepend to PATH
export MONET_TEST_DIR=$HOME/.monet-test  # optional: where test data lives (default: ~/.monet-test)

python3 harness/run_all.py
```

Every test spawns its own `monet start -d <dir>` server process against the isolated test DB. The suite runner exits non-zero if any test fails.

To run a single test:

```sh
python3 tests/test01_handshake.py
```

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MONET_CLI` | `monet` on PATH | Path to the Monet CLI (`cli.js`) |
| `MONET_NODE_PATH` | *(empty)* | Node bin dir prepended to PATH for the server process |
| `MONET_TEST_DIR` | `~/.monet-test` | Where the isolated SQLite DB and fixtures live |
| `MONET_FIXTURE_DIR` | `$MONET_TEST_DIR/fixtures/schema4` | Where the schema-4 fixture lives (migration test) |
| `MONET_OLD_CLI` | `$MONET_TEST_DIR/prefix-old/...` | Path to the old 1.2.4 CLI (fixture generator) |

## Known product findings

Observations surfaced by the suite that are relevant product input:

- **Fresh DB pins `Xenova/bge-small-en-v1.5`** (English-only). Korean store/search is refused with an explicit non-Latin error until `monet repair` migrates to `Xenova/paraphrase-multilingual-MiniLM-L12-v2`. Use the bare model ID, no `onnx:` prefix.
- **Schema auto-migration works**: opening a new server on a schema-4 DB auto-migrates 4 → 12 and backfills the pin to the legacy embedder so existing vectors stay valid. Old observations remain retrievable.
- **SQLite WAL concurrency is solid**: two server processes sharing one DB — interleaved stores, cross-visibility, zero `database is locked` / `SQLITE_BUSY` errors.
- **Dedup is aggressive** (product observation): template-similar sentences with different nouns still merge into one concept (20 semi-distinct sentences → 5 concepts). Truly distinct sentence structure is required to stay separate (20 hand-written sentences → 20 unique concepts). Worth checking the dedup threshold parameter.
- **Dedup growth pattern**: first store `action=created`; later near-identical stores `action=attached` to the same concept. `observationCount` grows 1:1; `body` accumulates all observations. At the DB layer, `observation_segments` rows == observations (1:1), `observation_tokens` accumulate per observation.
- Korean-only concepts get empty slugs even with the multilingual embedder — cosmetic; retrieval still works.
- `monet doctor` needs `--check-provider` to report `Assessment: safe`.

## Schema fixture (regeneration)

The migration test needs a real 1.2.4-era database. The pristine fixture is generated once and copied to a scratch dir per run (so the pristine copy is never mutated):

```sh
# install the old package into a prefix dir once
npm install --prefix $MONET_TEST_DIR/prefix-old @team-monet/monet@1.2.4
# generate the fixture DB (spawns old cli.js start → store → close)
python3 harness/make_fixture_schema4.py
```

## Guardrails

The agent operates under explicit guardrails — see [GUARDRAILS.md](GUARDRAILS.md). The two that matter most for contributors:

- **GR-01**: tests must run against an isolated data dir (`-d`), never the real store.
- **GR-06**: tests must be re-run safe — no shared fixed circle names or state pollution between runs.

## Contributing

Feedback is welcome via [GitHub Issues](../../issues):

- 🐞 **Bug report** — a test failing, or behavior that looks wrong
- 🧪 **Test suggestion** — a scenario that should be covered
- 💬 **Question / feedback** — anything else

Every issue filed here is reviewed by the maintainers — and picked up by the autonomous agent on its next scheduled run, which will reply on the issue with what it did.

## License

Apache-2.0 — see [LICENSE](LICENSE).
