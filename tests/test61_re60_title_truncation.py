#!/usr/bin/env python3
"""Scenario 61 / RE-60 (upstream #117): the derived CARD TITLE cuts at any period
that is not sandwiched between digits, so a memory that names a file, a domain or
an abbreviation loses everything after the dot.

`firstLine()` (packages/core/src/engine.ts, `yn` in the shipped bundle) derives every
concept's title — and from it the slug — with

    content.trim().split(/\\n|(?<!\\d)\\.|\\.(?!\\d)/)[0].trim()

A period survives only when a digit sits on BOTH sides (the intended `0.6.0` case).
Every other period ends the title: `app/card-image.ts` -> `app/card-image`,
`vite.config.ts` -> `vite`, `App.svelte` -> `App`, `example.ai` -> `example`.

This is a user-facing journey, not an internal one:
  * `memory_list` cards carry `title` -> the corrupted string;
  * `memory_search` cards carry ONLY `slug` (no title at all) and the slug is derived
    from the same truncated line, so the single triage surface a recalling agent gets
    reads `bump-vite` / `use-e` / `deploy-the-docs-to-example`;
  * the second surface is the arbitration line: a `kind="correction"` store that
    attaches returns `contradiction.detail = "correction: " + firstLine(content)`, so
    the evidence an agent reads to decide accept-new vs keep-current is truncated too
    (`correction: Correction: bump vite` — the file and the change are gone).

The test drives the LIVE `monet start` MCP surface against an isolated temp store and
asserts the DESIRED contract (the issue's own suggested direction: a sentence end is a
period followed by whitespace or end-of-input, so `0.6.0`, `app/card-image.ts`,
`App.svelte` and `example.ai` survive while real sentence ends still cut).

Arms intentionally NOT asserted (recorded as evidence only, so the guard cannot stay
red after a fix that does not address them):
  * `e.g.` — the suggested rule still cuts at `g.` followed by a space;
  * an email-led body — #117 records the current truncation as limiting a PII leak
    shape in titles (scrub-db.test.ts), and the suggested rule exposes the address;
    the desired wording there is a product decision, not a bug this guard can pin.

Exit codes per the run_all.py convention: 0 PASS, 2 XFAIL, 3 XPASS, 1 setup failure.
"""

import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient  # noqa: E402

CLI = os.environ.get(
    "MONET_CLI",
    os.path.expanduser(
        "~/.local/share/monet-node22/lib/node_modules/@team-monet/monet/dist/cli.js"
    ),
)
os.environ["MONET_CLI"] = CLI
os.environ.setdefault("MONET_NODE_PATH", "/opt/homebrew/opt/node@22/bin")
os.environ.setdefault("MONET_MODEL_CACHE", os.path.expanduser("~/.monet/models"))

TS = str(int(time.time()))
TOKEN = "R61T" + TS
CIRCLE = "e2e-r61-" + TS

PASS = []
FAIL = []
DESIRED = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def desired(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    if not cond:
        DESIRED.append(name)
    print(f"  [{'PASS' if cond else 'DESIRED-FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def evidence(msg):
    print(f"  [EVIDENCE] {msg}")


# (key, content, substrings the FULL first line must keep in the title, slug tokens)
ARMS = [
    ("file_ts",
     f"Updated app/card-image.ts downloadCardImage canvas exporter for {TOKEN}",
     ["app/card-image.ts"], ["card-image", "ts"]),
    ("file_config",
     f"Bump vite.config.ts target to es2022 for the {TOKEN} build",
     ["vite.config.ts"], ["vite", "config", "ts"]),
    ("component",
     f"Layout Height Collapse: Svelte mounts App.svelte at root, {TOKEN} note",
     ["App.svelte"], []),
    ("domain",
     f"Deploy docs to example.ai and mirror {TOKEN} on acme.dev",
     ["example.ai"], []),
]

# (key, content, substring the title MUST keep, substring the title must NOT keep, why)
# The negative half is what makes these controls real: a "fix" that simply stops cutting
# would keep the whole second sentence / second line and must be caught here.
CONTROLS = [
    ("version", f"monet-core 0.6.0 ships the temporal layer for {TOKEN}",
     "0.6.0", None, "a version number keeps its dots (the intended case)"),
    ("plain", f"Korean search works after the bge-m3 repair for {TOKEN}",
     "bge-m3", None, "no period anywhere: the title is the whole line"),
    ("sentence_end", f"Refactored the resolver. The old {TOKEN} path is gone.",
     "Refactored the resolver", "The old",
     "a real sentence end must still cut the title"),
    ("newline", f"First line about the {TOKEN} cache warmup\n"
                f"Second line that must never appear in a title",
     "First line about the", "Second line",
     "a newline must still cut the title"),
]

RECORD_ONLY = [
    ("abbrev", f"Use e.g. a lexicon entry instead of patching text, {TOKEN} runbook"),
    ("email", f"jane.doe@example.com reported the {TOKEN} crash while syncing"),
]


def main():
    base = tempfile.mkdtemp(prefix="monet-re60-title-")
    store = os.path.join(base, "store")
    os.makedirs(store)
    check("isolated_store", store.startswith(tempfile.gettempdir()), f"store={store}")

    client = MonetClient(store)
    try:
        client.initialize()
        tools = {t["name"] for t in client.tools_list().get("tools", [])}
        need = {"memory_store", "memory_search", "memory_list", "memory_fetch"}
        check("surface_present", need <= tools, f"missing={sorted(need - tools)}")

        stored = {}
        for key, content, *_ in ARMS + CONTROLS:
            ack = client.call_json("memory_store",
                                   {"content": content, "circle": CIRCLE,
                                    "sourceRefs": ["e2e:test61/r60"]})
            stored[key] = {"content": content, "id": ack.get("conceptId"),
                           "action": ack.get("action"), "ack": ack}
            check(f"stored_{key}", bool(ack.get("conceptId")),
                  f"action={ack.get('action')} id={ack.get('conceptId')}")
        for key, content in RECORD_ONLY:
            ack = client.call_json("memory_store",
                                   {"content": content, "circle": CIRCLE,
                                    "sourceRefs": ["e2e:test61/r60/record-only"]})
            stored[key] = {"content": content, "id": ack.get("conceptId"),
                           "action": ack.get("action"), "ack": ack}
            evidence(f"record-only arm {key}: action={ack.get('action')} "
                     f"id={ack.get('conceptId')}")

        # ---- read back through the card surfaces -------------------------------
        lst = client.call_json("memory_list", {"circle": CIRCLE, "limit": 50})
        cards = {c.get("id"): c for c in (lst.get("memories") or []) if isinstance(c, dict)}
        check("list_cards_returned", len(cards) >= len(ARMS) + len(CONTROLS),
              f"cards={len(cards)} total={lst.get('total')}")

        search = client.call_json("memory_search",
                                  {"query": f"{TOKEN}", "circle": CIRCLE, "limit": 20})
        hits = {h.get("id"): h for h in (search.get("results") or []) if isinstance(h, dict)}
        check("search_cards_returned", len(hits) >= 1, f"hits={len(hits)}")

        print("\n  --- title/slug as shipped (evidence table) ---")
        for key, text, *_ in ARMS + CONTROLS:
            card = cards.get(stored[key]["id"], {})
            hit = hits.get(stored[key]["id"], {})
            print(f"    {key:<16} content={text!r}")
            print(f"    {'':<16} title  ={card.get('title')!r}")
            print(f"    {'':<16} slug   ={card.get('slug')!r}"
                  + (f"  (search slug={hit.get('slug')!r})" if hit else "  (no search hit)"))
        sch = list(next(iter(hits.values())).keys()) if hits else []
        evidence(f"memory_search card keys = {sch} — the search surface carries no "
                 f"`title`; `slug` is derived from the same truncated line")
        check("search_card_carries_slug", "slug" in sch, f"keys={sch}")

        # ---- controls: behaviour that must SURVIVE a fix -----------------------
        for key, text, needle, must_not, why in CONTROLS:
            card = cards.get(stored[key]["id"], {})
            title = card.get("title") or ""
            ok = (needle in title) and (must_not is None or must_not not in title)
            check(f"control_{key}", ok,
                  f"title={title!r} must keep {needle!r}"
                  + (f" and must not keep {must_not!r}" if must_not else "") + f" — {why}")

        # ---- DESIRED: the file/domain the memory names must survive -----------
        for key, text, needles, slug_tokens in ARMS:
            card = cards.get(stored[key]["id"], {})
            title = card.get("title") or ""
            desired(f"title_keeps_{key}", all(n in title for n in needles),
                    f"title={title!r} must keep {needles}")
            if slug_tokens:
                hit = hits.get(stored[key]["id"], {})
                slug = hit.get("slug") or card.get("slug") or ""
                desired(f"search_slug_keeps_{key}",
                        all(t in slug for t in slug_tokens),
                        f"slug={slug!r} must keep {slug_tokens}")

        # ---- second surface: the contradiction detail used to arbitrate -------
        # engine.ts:5772 builds the arbitration line as `correction: ${firstLine(content)}`,
        # so the SAME defect truncates the evidence an agent reads when deciding
        # accept-new vs keep-current.
        base_ack = client.call_json(
            "memory_store",
            {"content": f"The build target for the {TOKEN} dashboard is es2020 today",
             "circle": CIRCLE, "sourceRefs": ["e2e:test61/r60/contradiction"]})
        corr_ack = client.call_json(
            "memory_store",
            {"content": f"Correction: bump vite.config.ts target to es2022 for the {TOKEN} build",
             "circle": CIRCLE, "kind": "correction",
             "sourceRefs": ["e2e:test61/r60/contradiction"]})
        corr = corr_ack.get("contradiction") or {}
        check("correction_attaches_and_opens_contradiction",
              corr_ack.get("action") == "attached" and bool(corr.get("id")),
              f"base={base_ack.get('action')} corr={corr_ack.get('action')} id={corr.get('id')}")
        detail = str(corr.get("detail") or "")
        evidence(f"contradiction.detail as shipped = {detail!r}")
        desired("contradiction_detail_keeps_the_file_the_correction_names",
                "vite.config.ts" in detail,
                f"detail={detail!r} must name the file the correction changes")

        # ---- record-only arms (never asserted) --------------------------------
        for key, _ in RECORD_ONLY:
            card = cards.get(stored[key]["id"], {})
            evidence(f"record-only arm {key}: title={card.get('title')!r} slug={card.get('slug')!r}")
        evidence("the suggested direction in #117 (split on a period followed by "
                 "whitespace/end) keeps 0.6.0 / app/card-image.ts / App.svelte / example.ai, "
                 "still cuts at `e.g. `, and exposes an email-led address in the title — "
                 "the last of those is a product decision, so it is recorded, not asserted.")
    finally:
        client.close()
        if os.environ.get("MONET_KEEP_STORE"):
            print(f"  KEPT store={store}")
        else:
            shutil.rmtree(base, ignore_errors=True)

    if DESIRED:
        print(f"\nRESULT: XFAIL — RE-60 (upstream #117) still present: {len(PASS)} checks held, "
              f"desired-but-unmet = {DESIRED}")
        return 2
    print(f"\nRESULT: XPASS — RE-60 fixed: derived titles keep the file/domain the memory "
          f"names ({len(PASS)} checks)")
    return 3


if __name__ == "__main__":
    sys.exit(main())
