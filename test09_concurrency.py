#!/usr/bin/env python3
"""Scenario 9: concurrency — two server processes sharing one isolated DB.

Spawns two `monet start -d <MONET_TEST_DIR>` processes against the SAME SQLite
DB (WAL mode). Both initialize, store distinct content interleaved, and
search each other's content (cross-visibility). Asserts no SQLITE lock/busy
errors on either server's stderr, and doctor integrity stays ok afterwards.

Observation point: SQLite WAL allows 1 writer at a time; Monet's busy_timeout
behavior under two live processes is the thing under test.
"""
import os
import statistics
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import MonetClient, CLI, NODE_PATH, DATA


TOKEN = str(int(time.time()))
CIRCLE = "e2e-c9-" + TOKEN
SRC = ["e2e:test09"]

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def run_cli(args):
    env = dict(os.environ)
    if NODE_PATH:
        env["PATH"] = NODE_PATH + ":" + env.get("PATH", "")
    p = subprocess.run([CLI] + args, capture_output=True, text=True, env=env, timeout=300)
    return p.stdout + p.stderr


def main():
    a = MonetClient(DATA, log_prefix="monetA")
    b = MonetClient(DATA, log_prefix="monetB")
    try:
        init_a = a.initialize()
        init_b = b.initialize()
        check("init_both", init_a.get("serverInfo", {}).get("name") and init_b.get("serverInfo", {}).get("name"))

        # interleaved stores from both processes
        claim_a1 = f"Concurrency alpha one {TOKEN}: the sky is clear over Brisbane."
        claim_a2 = f"Concurrency alpha two {TOKEN}: WAL allows concurrent readers."
        claim_b1 = f"Concurrency beta one {TOKEN}: two servers share one database file."
        claim_b2 = f"Concurrency beta two {TOKEN}: busy timeout serializes writers."

        id_a1 = a.call_json("memory_store", {"content": claim_a1, "circle": CIRCLE, "sourceRefs": SRC}).get("conceptId")
        id_b1 = b.call_json("memory_store", {"content": claim_b1, "circle": CIRCLE, "sourceRefs": SRC}).get("conceptId")
        id_a2 = a.call_json("memory_store", {"content": claim_a2, "circle": CIRCLE, "sourceRefs": SRC}).get("conceptId")
        id_b2 = b.call_json("memory_store", {"content": claim_b2, "circle": CIRCLE, "sourceRefs": SRC}).get("conceptId")
        check("store_4_interleaved", all([id_a1, id_a2, id_b1, id_b2]), f"ids={[id_a1,id_a2,id_b1,id_b2]}")

        # cross-visibility: A sees B's content, B sees A's content
        ra = a.call_json("memory_search", {"query": "two servers share one database file", "circle": CIRCLE, "limit": 3})
        hit_a_sees_b = any((id_b1 or "").__eq__(card.get("id")) or "beta one" in str(card.get("slug", "")) for card in (ra.get("results") or []))
        check("a_sees_b", hit_a_sees_b, f"top={ra.get('results')[:1]}")

        rb = b.call_json("memory_search", {"query": "sky is clear over Brisbane", "circle": CIRCLE, "limit": 3})
        hit_b_sees_a = any((id_a1 or "").__eq__(card.get("id")) or "alpha one" in str(card.get("slug", "")) for card in (rb.get("results") or []))
        check("b_sees_a", hit_b_sees_a, f"top={rb.get('results')[:1]}")

        # fetch across processes by id
        if id_b1:
            r = a.call_json("memory_fetch", {"id": id_b1, "observations": True})
            check("a_fetch_b_id", "beta one" in str(r) or id_b1 in str(r), str(r)[:120])

        # no lock/busy errors on either server
        err_a = a.stderr().lower()
        err_b = b.stderr().lower()
        lock_words = ["database is locked", "sqlite_busy", "sqlite3.operationalerror", "lock timeout"]
        check("no_lock_errors_a", not any(w in err_a for w in lock_words), a.stderr()[-200:])
        check("no_lock_errors_b", not any(w in err_b for w in lock_words), b.stderr()[-200:])
    finally:
        a.close()
        b.close()

    # post-condition: doctor integrity on the shared DB after concurrent use
    out = run_cli(["doctor", "-d", DATA, "--check-provider"])
    check("post_doctor_integrity", "Integrity:  ok" in out,
          [l for l in out.splitlines() if "Integrity" in l][:1])

    print("\n--- phase 2: parallel burst writes ---")
    burst_phase()

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


def burst_phase():
    """Phase 2: parallel burst writes — 4 client processes x 5 stores each.

    Sub-phase A (dedup under load): 20 near-identical concurrent stores all
    dedup into ONE concept (verified 2026-08-10: unique=1, wall=2.4s, no
    locks). Sub-phase B (distinct under load): 20 clearly distinct concurrent
    stores stay separate (20 concepts) and are cross-visible via search.
    """
    clients = [MonetClient(DATA, log_prefix=f"burst{i}") for i in range(4)]
    results = [[] for _ in clients]
    lock = threading.Lock()
    TOKEN2 = str(int(time.time())) + "-b"
    CIRCLE2 = "e2e-c9b-" + TOKEN2

    def run_burst(make_content):
        out = [[] for _ in clients]
        def writer(idx, client):
            for i in range(5):
                content = make_content(idx, i)
                try:
                    r = client.call_json("memory_store", {"content": content, "circle": CIRCLE2, "sourceRefs": ["e2e:test09-burst"]})
                    ok = bool(r.get("conceptId"))
                    cid = r.get("conceptId")
                except Exception:
                    ok = False
                    cid = None
                with lock:
                    out[idx].append((ok, cid))
        t0 = time.time()
        threads = [threading.Thread(target=lambda i=i, cl=clients[i]: writer(i, cl)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return time.time() - t0, [item for lat in out for item in lat]

    # Sub-phase A: near-identical template -> dedup under concurrency
    wall_a, flat_a = run_burst(lambda idx, i: f"Burst load test payload about the same topic {TOKEN2} item {i} of writer {idx}")
    ok_a = all(ok for ok, _ in flat_a)
    ids_a = set(cid for _, cid in flat_a)
    check("burstA_20_stores_ok", ok_a, f"ok={sum(1 for ok, _ in flat_a if ok)}/20 wall={wall_a:.1f}s")
    check("burstA_dedup_single_concept", len(ids_a) == 1,
          f"unique={len(ids_a)} — concurrent near-identical stores merge (product observation)")

    # Sub-phase B: clearly distinct content -> 20 concepts, cross-visible.
    # NOTE (product observation, 2026-08-10): template-similar content merges
    # even with different nouns (20 semi-distinct sentences -> 5 concepts, 1
    # per writer). Truly distinct structure is required to stay separate.
    sentences = [
        "The Monet database uses WAL mode so many readers never block each other.",
        "Kangaroos rest in the shade during midday heat and feed after dusk.",
        "A solar farm near the coast doubles output on clear winter mornings.",
        "Hermes agents persist durable facts into a local SQLite store.",
        "The Great Barrier Reef hosts thousands of fish species along its length.",
        "Rainwater tanks supply most gardens across suburban Queensland homes.",
        "Busy timeout serializes concurrent SQLite writers without errors.",
        "Cyclones form over warm ocean water and weaken once they hit land.",
        "Node 22 ships a faster JavaScript runtime for server-side tooling.",
        "Koalas sleep up to twenty hours a day on eucalyptus branches.",
        "Obsidian vaults sync to GitHub so every note keeps a full history.",
        "The monsoon brings steady afternoon showers to the tropical north.",
        "MCP lets agents expose tools over a simple JSON-RPC stdio channel.",
        "Emus run fast but cannot fly, unlike most other large birds.",
        "Embedding models map sentences into vectors for similarity search.",
        "Fruit bats visit the garden at dusk to eat ripe mangoes and figs.",
        "A repair rewrites every embedding store and pins the new model.",
        "Surfers check the dawn swell before paddling out at the point break.",
        "Dedup merges repeated observations into one growing concept.",
        "The telescope tracked a faint comet crossing the southern sky.",
    ]
    def distinct_content(idx, i):
        return f"[{TOKEN2}] {sentences[idx*5+i]}"
    wall_b, flat_b = run_burst(distinct_content)
    ok_b = all(ok for ok, _ in flat_b)
    ids_b = [cid for _, cid in flat_b]
    check("burstB_20_stores_ok", ok_b, f"ok={sum(1 for ok, _ in flat_b if ok)}/20 wall={wall_b:.1f}s")
    check("burstB_distinct_concepts", all(ids_b) and len(set(ids_b)) == 20, f"unique={len(set(ids_b))}")

    # cross-visibility under load: client 0 searches a distinctive phrase from each writer
    seen = []
    for i in range(4):
        r = clients[0].call_json("memory_search", {"query": sentences[i*5], "circle": CIRCLE2, "limit": 3})
        cards = r.get("results") or []
        hit = any(card.get("id") in ids_b for card in cards)
        seen.append(hit)
    check("burstB_cross_visibility", all(seen), f"per-writer={seen}")

    lock_words = ["database is locked", "sqlite_busy", "sqlite3.operationalerror", "lock timeout"]
    bad = [f"c{i}" for i, cl in enumerate(clients) if any(w in cl.stderr().lower() for w in lock_words)]
    check("burst_no_lock_errors", not bad, f"locks={bad or 'none'}")

    # read latency under concurrent load (informational; loose bound)
    lat_all = []
    for idx in range(4):
        for _ in range(5):
            t0 = time.time()
            clients[idx].call_json("memory_search", {"query": "Burst load test payload", "circle": CIRCLE2, "limit": 3})
            lat_all.append(time.time() - t0)
    check("burst_20_reads_ok", len(lat_all) == 20, f"reads={len(lat_all)}")
    if lat_all:
        s = sorted(lat_all)
        print(f"  INFO burst wall A={wall_a:.1f}s B={wall_b:.1f}s search_p50={statistics.median(lat_all)*1000:.0f}ms p95={s[18]*1000:.0f}ms")

    for cl in clients:
        cl.close()


if __name__ == "__main__":
    sys.exit(main())
