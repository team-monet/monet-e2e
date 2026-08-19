#!/usr/bin/env python3
"""RE-49 (mcp-server.ts): stage_lookup clips body/reason but discloses no
truncation to the caller.

Reverse-engineering finding (readable TS, upstream team-monet/monet #59): the
`stage_lookup` MCP tool clips a rule's `body` (STAGE_LOOKUP_BODY_CAP=6000) and
`reason` (STAGE_LOOKUP_REASON_CAP=1200) via clip() (mcp-server.ts:146-150), which
returns `{text, clipped}` and writes an inline `...[truncated N chars]` marker.
But the stage_lookup handler (mcp-server.ts:1595-1625) uses only `.text` and
DISCARDS the `.clipped` flag — no `bodyTruncated`/`reasonTruncated` field is
emitted. `conceptId` IS returned, so the recovery path (`memory_fetch`) exists
but is undisclosed; the tool description promises "omission recovery fields",
but those cover omitted RULES (`rulesOmitted`), not a clipped rule body.

`memory_fetch` already solves this exact problem (emits `bodyTruncated:true`
and instructs "recover from observations"), so stage_lookup is inconsistent
with the sibling surface that shares the same clip() primitive.

This test asserts the DESIRED contract (deterministic): when stage_lookup
clips a delivered rule's body, the response must disclose that truncation (a
truthy `bodyTruncated` on the rule, mirroring memory_fetch) so a caller can
`memory_fetch(conceptId)` to recover the full body. Currently absent -> XFAIL.

Exit codes:
  0/1 = normal pass/fail (setup broke -> the test itself is wrong)
  2   = XFAIL: body is clipped but no bodyTruncated signal is disclosed (bug present)
  3   = XPASS: bodyTruncated is disclosed on a clipped body (bug appears fixed)
"""
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient

ISSUE = "RE-49"
CLI = os.environ.get("MONET_CLI") or "/Users/codalee/.local/share/monet-node22/lib/node_modules/@team-monet/monet/dist/cli.js"
NODE = os.environ.get("MONET_NODE_PATH") or "/opt/homebrew/opt/node@22/bin"
MODEL_CACHE = os.path.expanduser("~/.monet/models")

os.environ["MONET_CLI"] = CLI
os.environ["MONET_NODE_PATH"] = NODE
os.environ["MONET_MODEL_CACHE"] = MODEL_CACHE

# Fresh stage per run (GR-06): timestamp token prevents cross-run state pollution.
TS = str(int(time.time()))
STAGE = f"e2e-re49-stage-{TS}"
CIRCLE = f"e2e-re49-{TS}"

# STAGE_LOOKUP_BODY_CAP = 6_000 (gates.ts:2019). A body comfortably above it
# guarantees the wire-layer clip fires (else the test cannot observe anything).
LONG_BODY = "The full governing text of this rule is deliberately long so the wire layer must clip it. " * 90

PASS = []
FAIL = []


def check(name, cond, detail=""):
    """Setup precondition — must hold or the test itself is broken (exit 1)."""
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


TRUNCATE_MARK = "[truncated "


def clipped_body_disclosed(rules):
    """True iff, for every delivered rule whose body carries the truncation
    marker, a truthy disclosure field (bodyTruncated/reasonTruncated) is present
    on that rule. Mirror of memory_fetch's bodyTruncated contract."""
    if not rules:
        return False
    for rule in rules:
        body = rule.get("body")
        if isinstance(body, str) and TRUNCATE_MARK in body:
            if not (rule.get("bodyTruncated") or rule.get("reasonTruncated")):
                return False
    return True


def main():
    base = tempfile.mkdtemp(prefix="monet-re49-e2e-")
    store = os.path.join(base, "store")
    os.makedirs(store)

    check("isolated_store", store.startswith(tempfile.gettempdir()), f"store={store}")
    check("long_body_over_cap", len(LONG_BODY) > 6_000, f"len={len(LONG_BODY)} (BODY_CAP=6000)")

    observed = None  # None = clip did not fire (setup invalid); dict = observed rule sample
    try:
        c = MonetClient(store)
        try:
            c.initialize()

            # ---- setup: a stage + an advisory rule with an over-cap body ----
            r = c.call_json("memory_declare", {
                "species": "stage", "stage": STAGE,
                "patterns": ["e2e re49 trigger"], "sourceRefs": ["e2e:test41"],
            })
            check("stage_declared", r.get("species") == "stage" and r.get("stage", {}).get("name") == STAGE,
                  f"resp={r.get('stage')}")

            r = c.call_json("memory_declare", {
                "species": "rule", "stage": STAGE, "scope": "domain",
                "content": LONG_BODY, "severity": "advisory",
                "sourceRefs": ["e2e:test41"],
            })
            check("rule_declared", r.get("species") == "rule", f"resp={r}")

            # ---- the firing path ----
            hit = c.call_json("stage_lookup", {"stage": STAGE})
            check("stage_lookup_hit", hit.get("matched") is True, f"matched={hit.get('matched')}")
            rules = hit.get("rules") or []
            check("rule_delivered", len(rules) >= 1, f"rules={len(rules)}")

            if rules:
                sample = rules[0]
                body = sample.get("body") or ""
                if TRUNCATE_MARK in body:
                    # The clip fired: body carried the marker. Record what we saw.
                    observed = {
                        "body_clipped": True,
                        "marker_present": True,
                        "rule_keys": sorted(sample.keys()),
                        "has_bodyTruncated": bool(sample.get("bodyTruncated")),
                        "has_reasonTruncated": bool(sample.get("reasonTruncated")),
                        "bodyLen": len(body),
                    }
                    print(f"  [RE-49] body clipped, marker present; rule keys={observed['rule_keys']} "
                          f"bodyTruncated={observed['has_bodyTruncated']} "
                          f"reasonTruncated={observed['has_reasonTruncated']}")
                else:
                    observed = {"body_clipped": False, "marker_present": False, "bodyLen": len(body)}
                    print(f"  [note] delivered rule body was NOT clipped (len={len(body)}); "
                          f"cannot observe the disclosure gap")
        finally:
            c.close()
    finally:
        shutil.rmtree(base, ignore_errors=True)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if observed is None or not observed["marker_present"]:
        print(f"\nRESULT: SETUP-INVALID — the clip did not fire (observed={observed}); "
              f"cannot assert the disclosure contract")
        return 1
    if observed.get("has_bodyTruncated") or observed.get("has_reasonTruncated"):
        print(f"\nRESULT: XPASS {ISSUE} — stage_lookup discloses bodyTruncated/reasonTruncated "
              f"on a clipped body (bug appears fixed): {observed}")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — stage_lookup clipped the rule body (marker present) but "
          f"disclosed NO bodyTruncated/reasonTruncated signal ({len(PASS)} setup checks passed, "
          f"observed={observed}); the truncated body has no disclosed recovery path despite "
          f"conceptId being returned")
    return 2


if __name__ == "__main__":
    sys.exit(main())
