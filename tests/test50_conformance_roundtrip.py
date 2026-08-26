#!/usr/bin/env python3
"""Test the conformance_ask / conformance_answer MCP round-trip (new in 1.7.0).

Upstream issue #28 wired the "conformance judgment half" onto MCP in 1.7.0
(release that also fully removed the sources subsystem). This is the wire
contract of that half:

  * A *moment* is a governed interception (an action that consulted a gate
    stage + read a rule + then acted). Moments are recorded in the store-backed
    `governed_moments` table via the moment spool (`<storage>/moments.jsonl`).
    A moment that was READ (a rule was delivered to the agent) and then ACTED
    on (an outcome landed) OWES a conformance question.
  * `conformance_ask(momentId)` records that the agent put the question to the
    user (sets `asked_at`); it ATTACHES to an observed judicable moment and
    never creates one (UnknownMomentError reaches the caller when the id is
    unknown or the moment is not judicable).
  * `conformance_answer(momentId, answer)` records the user's verdict, answer ∈
    {followed, not-followed} (sets `answer` + `answered_at`). A DIFFERENT
    answer is REFUSED (ConflictingAnswerError); repeating the same answer is
    allowed.
  * A tool response carries an ASK signal naming the moments that owe a
    question, until they stop owing one (cleared by asking).

In an isolated `monet start -d <store>` there is no gate-hook wrapper, so no
moment is produced by store-side MCP calls (store moments open+close
synchronously with no rule read). To exercise the REAL ledger path we seed the
moment spool with hook-format records (run-start + interception + read +
outcome — exactly what the install-cli wrapper/hook writes), which the server
folds into a judicable `governed_moments` row on the next MCP call.

This directly reassesses RE-27: the judgment half now ships. Evidence captured
below — conformance_answer records a per-moment followed/not-followed verdict
into governed_moments (and its tallies), but exposes NO rule-retirement /
advisory-dismissal surface, so advisory rules still have no retirement path
from this mechanism.

Exit codes: 0 = PASS (surface works), 1 = FAIL (unexpected).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient

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


def sql(db, q):
    return subprocess.run(["sqlite3", db, q], capture_output=True, text=True).stdout.strip()


def spool_seed(spool, records):
    with open(spool, "a") as f:
        for ln in records:
            f.write(json.dumps(ln) + "\n")


def seed_judicable(spool, moment_id, rule_id, circle, at="2026-08-21T00:00:00.000Z"):
    """Hook-format moment that is opened, read (timely), and acted on -> judicable."""
    run = "run-e2e-" + uuid.uuid4().hex[:12]
    return [
        {"v": 1, "runId": run, "seq": 0, "kind": "run-start", "writerRole": "e2e", "at": at},
        {"v": 1, "runId": run, "seq": 1, "kind": "interception", "momentId": moment_id, "at": at,
         "toolUseId": "tu-" + moment_id[:8], "circle": circle, "sessionId": None, "surface": "Bash",
         "actionSha256": "a" * 64, "actionRendering": "prod deploy", "actionChars": 15,
         "actionClipped": False, "stageId": "stage-e2e", "ruleIds": [rule_id],
         "disposition": "advised", "deliveredRuleIds": [rule_id]},
        {"v": 1, "runId": run, "seq": 2, "kind": "read", "momentId": moment_id, "ruleId": rule_id,
         "namedStageId": "stage-e2e", "circle": circle, "readAt": at},
        {"v": 1, "runId": run, "seq": 3, "kind": "outcome", "momentId": moment_id,
         "toolUseId": "tu-" + moment_id[:8], "outcomeStatus": "ok", "outcomeAt": at,
         "outcomeSha256": "b" * 64},
    ]


def main():
    base = tempfile.mkdtemp(prefix="monet-conformance-e2e-")
    store = os.path.join(base, "store")
    os.makedirs(store)
    db = os.path.join(store, "monet.db")
    spool = os.path.join(store, "moments.jsonl")

    check("isolated_store", store.startswith(tempfile.gettempdir()), f"store={store}")

    c = MonetClient(store)
    try:
        c.initialize()
        tools = {t["name"] for t in c.tools_list().get("tools", [])}

        # Version tolerance: pre-1.7.0 has no conformance half -> skip cleanly.
        if "conformance_ask" not in tools or "conformance_answer" not in tools:
            print("SKIP: conformance_ask/answer not present in this Monet build")
            return 0

        # Discover the server's active circle (the ASK signal scopes to it).
        ac = c.call_json("agent_context")
        default_circle = ac.get("circle") if isinstance(ac, dict) else None
        if not default_circle:
            # fallback: the circle a bare store call records on its moment
            c.call_json("memory_store", {"content": "circle-probe-" + TS})
            default_circle = sql(db, "SELECT circle FROM governed_moments WHERE surface='memory_store' ORDER BY at DESC LIMIT 1;")
        check("default_circle_discovered", bool(default_circle), f"circle={default_circle}")

        is_err = lambda r: isinstance(r, dict) and "_rawText" in r

        # ---- Moment A: followed ----
        midA = str(uuid.uuid4())
        ruleA = str(uuid.uuid4())
        spool_seed(spool, seed_judicable(spool, midA, ruleA, default_circle))

        # 1.9.0 change (gate retired): the moment spool is no longer FOLDED eagerly
        # at store-time into a governed_moments row, and the store-time ASK signal
        # (which used to name moments that owe a conformance question on a success
        # response) is gone. Materialization is now LAZY: `conformance_ask` reads the
        # spool and mints/updates the row on demand. Pin the lazy contract:
        c.call("memory_store", {"content": "fold-A-" + TS}, timeout=120)
        row_pre = sql(db, "SELECT opened FROM governed_moments WHERE moment_id='%s';" % midA)
        check("seed_not_prematerialized_lazy", row_pre == "",
              f"pre-ask row={row_pre!r}; no eager fold (moments materialize at ask)")

        # conformance_ask -> {recorded: ask, momentId}; this LAZILY materializes a
        # judicable row from the spool (opened, rule_reads, outcome).
        ack = c.call_json("conformance_ask", {"momentId": midA})
        check("conformance_ask_ack", ack.get("recorded") == "ask" and ack.get("momentId") == midA,
              f"ack={json.dumps(ack)}")
        check("asked_at_written", bool(sql(db, "SELECT asked_at FROM governed_moments WHERE moment_id='%s';" % midA)))

        # After ask: the seed DID fold to a judicable row (opened=1, its rule
        # appears in rule_reads, outcome_at recorded) — the spool read survived the
        # lazy path.
        row = sql(db, "SELECT opened, rule_reads, outcome_at FROM governed_moments WHERE moment_id='%s';" % midA)
        cols = row.split("|")
        judicable = len(cols) == 3 and cols[0] == "1" and "{" in cols[1] and ruleA in cols[1] and cols[2]
        check("materialized_judicable_on_ask", judicable, f"row={row!r}")

        # conformance_answer "followed" -> {recorded: answer, answer: followed}
        ack = c.call_json("conformance_answer", {"momentId": midA, "answer": "followed"})
        check("conformance_answer_followed", ack.get("recorded") == "answer" and ack.get("answer") == "followed"
              and ack.get("momentId") == midA, f"ack={json.dumps(ack)}")
        dbv = sql(db, "SELECT answer, answered_at FROM governed_moments WHERE moment_id='%s';" % midA)
        check("answer_persisted", dbv.startswith("followed|") and "|" in dbv and dbv[9:] != "", f"db={dbv!r}")

    finally:
        c.close()

    # Reopen a fresh connection to the same store for the remaining asserts.
    c2 = MonetClient(store)
    try:
        c2.initialize()

        default_circle = sql(db, "SELECT circle FROM governed_moments WHERE surface='memory_store' ORDER BY at DESC LIMIT 1;")
        midB = str(uuid.uuid4())
        ruleB = str(uuid.uuid4())
        spool_seed(spool, seed_judicable(spool, midB, ruleB, default_circle))
        c2.call_json("memory_store", {"content": "fold-B-" + TS})  # fold B into the ledger
        c2.call_json("conformance_ask", {"momentId": midB})

        # Verdict vocabulary: not-followed is a distinct, recorded value.
        ack = c2.call_json("conformance_answer", {"momentId": midB, "answer": "not-followed"})
        check("conformance_answer_not_followed", ack.get("answer") == "not-followed", f"ack={json.dumps(ack)}")
        check("not_followed_persisted", sql(db, "SELECT answer FROM governed_moments WHERE moment_id='%s';" % midB) == "not-followed")

        # ---- Negative / boundary contract ----
        # 1. Unknown moment -> refused loudly (attaches, never creates).
        r = c2.call_json("conformance_ask", {"momentId": str(uuid.uuid4())})
        check("ask_unknown_refused", is_err(r) and "never creates" in r["_rawText"], f"raw={r.get('_rawText','')[:80]!r}")
        r = c2.call_json("conformance_answer", {"momentId": str(uuid.uuid4()), "answer": "followed"})
        check("answer_unknown_refused", is_err(r) and "in the record" in r["_rawText"], f"raw={r.get('_rawText','')[:80]!r}")

        # 2. Invalid enum value -> MCP input-validation error.
        r = c2.call_json("conformance_answer", {"momentId": midB, "answer": "maybe"})
        check("invalid_enum_refused", is_err(r) and "Invalid enum value" in r["_rawText"]
              and "followed" in r["_rawText"] and "not-followed" in r["_rawText"], f"raw={r.get('_rawText','')[:100]!r}")

        # 3. Conflicting answer (different from the recorded one) -> refused; same answer -> allowed.
        r = c2.call_json("conformance_answer", {"momentId": midB, "answer": "followed"})
        check("conflicting_answer_refused", is_err(r) and "already answered" in r["_rawText"], f"raw={r.get('_rawText','')[:100]!r}")
        r = c2.call_json("conformance_answer", {"momentId": midB, "answer": "not-followed"})
        check("same_answer_repeat_allowed", r.get("recorded") == "answer" and r.get("answer") == "not-followed",
              f"r={json.dumps(r)}")

        # A moment that was read + acted + answered no longer OWES its question; in the
        # 1.9.0 lazy model a re-ask is still accepted, but the durable contract is that
        # re-asking never ERASES the recorded answer (the verdict survives a re-ask).
        r2 = c2.call_json("conformance_ask", {"momentId": midB})
        check("reask_keeps_answer",
              r2.get("recorded") == "ask" and
              sql(db, "SELECT answer FROM governed_moments WHERE moment_id='%s';" % midB) == "not-followed",
              f"reask={json.dumps(r2)}")

        # 5. RE-27 evidence: the conformance half exposes ONLY ask + answer (a per-moment
        #    verdict); there is no conformance retirement / advisory-dismissal surface — so
        #    advisory rules still have no retirement path from this mechanism.
        conf_tools = sorted(t for t in (tools or set()) if "conformance" in t)
        check("conformance_surface_is_ask_and_answer_only", conf_tools == ["conformance_answer", "conformance_ask"],
              f"conf_tools={conf_tools}")
    finally:
        c2.close()

    shutil.rmtree(base, ignore_errors=True)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
        return 1
    print(f"\nRESULT: PASS — conformance_ask/answer round-trip works on the wired 1.7.0 surface "
          f"({len(PASS)} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())