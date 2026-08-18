#!/usr/bin/env python3
"""RE-47 + RE-48 (resolution.ts + mcp-server.ts): ambiguous-band correction
mis-attaches and disputes, and the store ack hides the target identity.

Reverse-engineering finding (readable TS, upstream team-monet/monet #52): in the
ambiguous band (`tauAmbiguous <= obsScore < tauAttach`), `resolveIncoming`
(resolution.ts) exempts `kind="correction"` and ATTACHES it to the
evidence-nominated concept ("correction-attach" mode) on the premise that
"intent disambiguates" — then `storeInternal` (engine.ts:4810-4817) opens a
value-conflict contradiction, flipping the concept to `disputed`. But intent
disambiguates WHAT a correction asserts, not WHICH concept a weak (sub-tauAttach)
evidence match points at: an unrelated correction at cosine ~0.55-0.70 is
absorbed and marks an innocent concept contested. RE-47.

The blast radius is invisible because the MCP `memory_store` acknowledgement
(mcp-server.ts envelope) returns `conceptId`/`nearMatchId` (UUIDs) and
`nearMatchScore` but DROPS the `concept.slug`/`concept.title` the engine already
computed (`r.concept` = toConcept(row), engine.ts:4875-4888). A caller cannot
tell from the response that a merge landed somewhere unrelated. RE-48.

This test asserts the DESIRED contract (RE-48, deterministic): when a
`memory_store` lands an observation on an EXISTING concept (action `attached`
or `ambiguous`), the acknowledgement must disclose a human-readable target
identity (`title` or `slug`), so a mis-merge is visible without a second
`memory_fetch`. The ambiguous-band correction (RE-47) is reproduced and its
nearMatchScore/contradiction recorded as evidence.

Exit codes:
  0/1 = normal pass/fail (setup broke -> the test itself is wrong)
  2   = XFAIL: ack omits the target title/slug on attach (bug present)
  3   = XPASS: ack discloses the target identity on attach (bug appears fixed)
"""
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient

ISSUE = "RE-48"
CLI = os.environ.get("MONET_CLI") or "/Users/codalee/.local/share/monet-node22/lib/node_modules/@team-monet/monet/dist/cli.js"
NODE = os.environ.get("MONET_NODE_PATH") or "/opt/homebrew/opt/node@22/bin"
MODEL_CACHE = os.path.expanduser("~/.monet/models")

os.environ["MONET_CLI"] = CLI
os.environ["MONET_NODE_PATH"] = NODE
os.environ["MONET_MODEL_CACHE"] = MODEL_CACHE

# Fresh circle per run (GR-06): timestamp token prevents cross-run state pollution.
CIRCLE = "e2e-re48-" + str(int(time.time()))

BASE_CONTENT = (
    "Caching generated per-user content in an in-memory key-value store "
    "reduces database round-trips for read-heavy pages."
)
# near-identical -> strong attach (action "attached"), deterministic and model-robust.
STRONG_CORRECTION = (
    "Caching generated per-user content in an in-memory key-value store "
    "significantly reduces database round-trips for read-heavy pages."
)
# distinct-but-overlapping topic -> ambiguous band (nearMatchScore ~0.60 on bge-m3),
# reproducing the RE-47 mis-attach (verified empirically run 46).
AMBIGUOUS_CORRECTION = (
    "A caching layer for generated per-user content should invalidate by user "
    "id when the profile changes."
)

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


def discloses_target(ack):
    """True iff the ack names the attach target in a human-readable form."""
    if not isinstance(ack, dict):
        return False
    return any(k in ack and ack[k] for k in ("targetTitle", "targetSlug", "title", "slug"))


def main():
    base = tempfile.mkdtemp(prefix="monet-re48-e2e-")
    store = os.path.join(base, "store")
    os.makedirs(store)

    check("isolated_store", store.startswith(tempfile.gettempdir()), f"store={store}")

    disclosed = None  # None = no attach observed; True/False = disclosure on an attach
    re47_evidence = {}

    try:
        c = MonetClient(store)
        try:
            c.initialize()

            # ---- base concept ----
            r0 = c.call_json("memory_store", {"content": BASE_CONTENT, "circle": CIRCLE})
            base_id = r0.get("conceptId")
            check("base_created", r0.get("action") == "created" and bool(base_id), f"id={base_id}")

            # ---- Part A: STRONG attach (deterministic) -> RE-48 disclosure ----
            r1 = c.call_json("memory_store", {
                "content": STRONG_CORRECTION, "circle": CIRCLE, "kind": "correction"})
            a1 = r1.get("action")
            check("strong_correction_attached", a1 == "attached",
                  f"action={a1} id={r1.get('conceptId')}")
            if a1 in ("attached", "ambiguous"):
                disclosed = discloses_target(r1)
                print(f"  [RE-48] strong attach: disclosed={disclosed} "
                      f"ack keys={sorted(r1.keys())}")

            # ---- Part B: AMBIGUOUS band (RE-47 reproduction) ----
            r2 = c.call_json("memory_store", {
                "content": AMBIGUOUS_CORRECTION, "circle": CIRCLE, "kind": "correction"})
            a2 = r2.get("action")
            ns = r2.get("nearMatchScore")
            cont = r2.get("contradiction")
            re47_evidence = {"action": a2, "nearMatchScore": ns, "contradiction": cont}
            if a2 in ("attached", "ambiguous") and ns is not None:
                weak = ns < 0.70
                print(f"  [RE-47] ambiguous correction: action={a2} nearMatchScore={ns} "
                      f"weak(<0.70)={weak} contradictionOpen={bool(cont)}")
                d2 = discloses_target(r2)
                # RE-48 must hold on this attach too; fold into the verdict.
                disclosed = (disclosed is True) and d2
                print(f"  [RE-48] ambiguous attach: disclosed={d2} ack keys={sorted(r2.keys())}")
            else:
                print(f"  [note] ambiguous correction did not attach (action={a2}); "
                      f"score shifted under a model change — Part B skipped for disclosure")
        finally:
            c.close()
    finally:
        shutil.rmtree(base, ignore_errors=True)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if disclosed is True:
        print(f"\nRESULT: XPASS {ISSUE} — the store ack discloses the attach target's "
              f"title/slug (bug appears fixed)")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — the store ack omits the attach target's "
          f"title/slug (disclosed={disclosed}; a mis-merge is invisible without a "
          f"separate memory_fetch). RE-47 evidence: {json.dumps(re47_evidence)}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
