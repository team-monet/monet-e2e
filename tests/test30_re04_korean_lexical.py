#!/usr/bin/env python3
"""RE-04 (search-pipeline.md): lexical arm is Latin-script-only — Korean gets zero boost.

Reverse-engineering finding (v1.5.2 minified + v0.9.0 readable `lexical-overlap.ts`):
the lexical rank arm tokenizes with `/[a-z0-9][a-z0-9_-]{2,}/gu` — a LATIN-script-only
regex. It is used for BOTH the query probe tokens and the stored observation tokens
(`lexicalTokens`). Korean/Japanese text therefore produces an empty token set on both
sides: a Korean query's overlap fraction `p` is always 0, so `rank = score * (1 + p)`
degenerates to `rank = score` — no lexical contribution at all. English benefits from
both arms (embedding + lexical); Korean relies on embedding alone.

The deterministic, observable root cause is the WRITE side: English content populates
`observation_tokens`, Korean content does not (0 rows), so the lexical arm has nothing
to match Korean queries against.

This test documents the DESIRED contract: non-Latin (Korean) content should be lexically
represented (produce tokens) so that Korean queries receive the same lexical boost English
queries do.

Exit codes:
  0/1 = normal pass/fail (setup broke -> the test itself is wrong)
  2   = XFAIL: Korean content still produces zero lexical tokens (Latin-only tokenizer)
  3   = XPASS: Korean content now produces lexical tokens (tokenizer is multilingual)
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient

ISSUE = "RE-04"
CLI = os.environ.get("MONET_CLI") or "/Users/codalee/.local/share/monet-node22/lib/node_modules/@team-monet/monet/dist/cli.js"
NODE = os.environ.get("MONET_NODE_PATH") or "/opt/homebrew/opt/node@22/bin"

os.environ["MONET_CLI"] = CLI
os.environ["MONET_NODE_PATH"] = NODE

TS = str(int(time.time()))

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def sql(db, query):
    out = subprocess.run(["sqlite3", db, query], capture_output=True, text=True)
    return out.stdout.strip()


def main():
    base = tempfile.mkdtemp(prefix="monet-re04-e2e-")
    store = os.path.join(base, "store")
    os.makedirs(store)
    db = os.path.join(store, "monet.db")

    check("isolated_store", store.startswith(tempfile.gettempdir()), f"store={store}")

    bug_fixed = False
    en_id = ko_id = None
    try:
        c = MonetClient(store)
        try:
            c.initialize()

            # ---- CONTROL: English content populates observation_tokens ----
            r = c.call_json("memory_store", {
                "content": "The quarterly revenue report for the alpha project was finalized today.",
                "circle": f"e2e-re04-en-{TS}", "sourceRefs": ["e2e:test30"],
            })
            en_id = r.get("conceptId")
            check("english_stored", r.get("action") == "created" and bool(en_id), f"id={en_id}")

            # ---- PROBE: Korean content (same meaning) — DESIRED lexical tokens ----
            r = c.call_json("memory_store", {
                "content": "알파 프로젝트의 분기별 매출 보고서가 오늘 확정되었다.",
                "circle": f"e2e-re04-ko-{TS}", "sourceRefs": ["e2e:test30"],
            })
            ko_id = r.get("conceptId")
            check("korean_stored", r.get("action") == "created" and bool(ko_id), f"id={ko_id}")

            # Korean SEMANTIC retrieval still works (bge-m3 multilingual) — the gap
            # is lexical only, not a retrieval failure.
            sr = c.call_json("memory_search", {
                "query": "분기별 매출 보고서", "circle": f"e2e-re04-ko-{TS}", "limit": 5,
            })
            ko_hits = sr.get("results") or []
            check("korean_semantic_retrieval_works", any(h.get("id") == ko_id for h in ko_hits),
                  f"hits={[h.get('id') for h in ko_hits]}")
        finally:
            c.close()

        # Cross-check the lexical-token tables directly.
        en_cnt = int(sql(db, f"""
            SELECT COUNT(*) FROM observation_tokens ot
            JOIN observations o ON o.id = ot.observation_id
            WHERE o.concept_id = '{en_id}';
        """) or "0")
        ko_cnt = int(sql(db, f"""
            SELECT COUNT(*) FROM observation_tokens ot
            JOIN observations o ON o.id = ot.observation_id
            WHERE o.concept_id = '{ko_id}';
        """) or "0")

        check("english_content_has_lexical_tokens", en_cnt > 0, f"tokens={en_cnt}")
        print(f"  [RE-04] english tokens={en_cnt} korean tokens={ko_cnt}")

        # DESIRED contract: Korean content is lexically represented (tokens > 0).
        # The bug is present when the Latin-only tokenizer drops every Hangul token.
        bug_fixed = ko_cnt > 0
    finally:
        shutil.rmtree(base, ignore_errors=True)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if bug_fixed:
        print(f"\nRESULT: XPASS {ISSUE} — Korean content now produces lexical tokens (bug appears fixed)")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — Korean content produces zero lexical tokens, so Korean queries "
          f"get no lexical boost ({len(PASS)} setup checks passed)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
