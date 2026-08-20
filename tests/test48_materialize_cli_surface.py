#!/usr/bin/env python3
"""test48: cli/materialize-cli.ts surface scenario (monet-e2e#22).

Drives the `monet materialize` CLI surface — `add` / `remove` / `list` /
(re)generate — that the suite currently reaches only via test34's dirty-skeleton
XFAIL (add --circle + materialize). This scenario covers the full lifecycle plus
the error branches, all via run_cli against an isolated MONET_STORAGE_DIR:

  add    --global / --circle registration + all guard refusals (neither, both,
         '*' circle, padded circle, duplicate, same-destination alias)
  (regenerate) block written with scope-appropriate Principles/Preferences
  list   fresh -> stale (store change) -> block-missing (surface deleted)
  remove registered + unregistered refusal
  materialize error branches: store-not-a-readable-file, lossy UTF-8 decode,
         dangling symlink

Reference behavior pinned here is the CURRENT (working) surface contract — this
is a green scenario (exit 0 on full pass), not an XFAIL: it asserts the surface
works as documented and lifts materialize-cli.ts line coverage.

Exit codes:
  0 = all checks pass
  1 = any unexpected failure (setup or assertion)
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.expanduser("~/.monet-test/harness"))
from mcp_client import MonetClient

CLI = os.environ.get("MONET_CLI") or "/Users/codalee/.local/share/monet-node22/lib/node_modules/@team-monet/monet/dist/cli.js"
NODE = os.environ.get("MONET_NODE_PATH") or "/opt/homebrew/opt/node@22/bin"
os.environ["MONET_CLI"] = CLI
os.environ["MONET_NODE_PATH"] = NODE
MODEL_CACHE = os.path.expanduser("~/.monet/models")

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def run_cli(args, store, base, timeout=60):
    env = dict(os.environ)
    env["PATH"] = NODE + ":" + env.get("PATH", "")
    env["MONET_STORAGE_DIR"] = store
    env["MONET_PROJECT_DIR"] = base
    env["MONET_MODEL_CACHE"] = MODEL_CACHE
    p = subprocess.run([CLI] + args, capture_output=True, text=True, env=env, timeout=timeout)
    return p


def main():
    base = tempfile.mkdtemp(prefix="monet-c48-")
    store = os.path.join(base, "store")
    os.makedirs(store)
    circle = "e2e-c48-" + str(int(time.time()))

    circ_md = os.path.join(base, "CIRC.md")
    glob_md = os.path.join(base, "GLOB.md")

    check("isolated_store", store.startswith(tempfile.gettempdir()), f"store={store}")
    check("isolated_circle", circle not in ("", "global", "*"), circle)

    try:
        # ---- setup: skeleton members (principle + preference local, one global) ----
        c = MonetClient(store)
        try:
            c.initialize()
            r = c.call_json("memory_declare", {
                "species": "principle", "circle": circle,
                "content": "Always verify a migration before running it in production."})
            check("declare_principle_created", r.get("action") == "created" and bool(r.get("conceptId")))
            r = c.call_json("memory_declare", {
                "species": "preference", "circle": circle,
                "content": "Prefers short status meetings over long ones."})
            check("declare_preference_created", r.get("action") == "created" and bool(r.get("conceptId")))
            r = c.call_json("memory_declare", {
                "species": "principle", "circle": "*",
                "content": "Global principle: keep the system simple above all."})
            check("declare_global_created", r.get("action") == "created" and bool(r.get("conceptId")))
        finally:
            c.close()

        # ---- add (register) ----
        p = run_cli(["materialize", "add", circ_md, "--circle", circle], store, base)
        check("add_circle_rc0", p.returncode == 0, f"rc={p.returncode} {p.stderr.strip()[-120:]}")
        check("add_circle_msg", f"Registered {circ_md} (circle:{circle})" in p.stdout, f"out={p.stdout.strip()[-120:]}")

        p = run_cli(["materialize", "add", circ_md, "--circle", circle], store, base)
        check("add_duplicate_refused", p.returncode != 0 and "surface already registered" in (p.stdout + p.stderr))

        p = run_cli(["materialize", "add", glob_md, "--global"], store, base)
        check("add_global_rc0", p.returncode == 0 and f"Registered {glob_md} (global)" in p.stdout,
              f"rc={p.returncode} out={p.stdout.strip()[-100:]}")

        # ---- add guard refusals ----
        noside = os.path.join(base, "NOSIDE.md")
        p = run_cli(["materialize", "add", noside], store, base)
        check("add_no_scope_refused", p.returncode != 0 and "requires exactly one of --global or --circle" in (p.stdout + p.stderr))
        p = run_cli(["materialize", "add", noside, "--global", "--circle", circle], store, base)
        check("add_both_scope_refused", p.returncode != 0 and "requires exactly one of --global or --circle" in (p.stdout + p.stderr))
        p = run_cli(["materialize", "add", noside, "--circle", "*"], store, base)
        check("add_star_circle_refused", p.returncode != 0 and "reserved global-breadth marker" in (p.stdout + p.stderr))
        p = run_cli(["materialize", "add", noside, "--circle", f"  {circle}  "], store, base)
        check("add_padded_circle_refused", p.returncode != 0 and "leading or trailing whitespace" in (p.stdout + p.stderr))

        # ---- materialize (regenerate all) ----
        p = run_cli(["materialize"], store, base)
        check("materialize_rc0", p.returncode == 0, f"rc={p.returncode} {p.stderr.strip()[-120:]}")
        check("materialize_stdout_both", "Materialized" in p.stdout and circ_md in p.stdout and glob_md in p.stdout)
        circ_text = open(circ_md, encoding="utf-8").read()
        glob_text = open(glob_md, encoding="utf-8").read()
        check("circ_block_scope", "scope=circle:" in circ_text, "")
        check("circ_has_principles", "# Principles" in circ_text)
        check("circ_has_preferences", "# Preferences" in circ_text)
        check("glob_block_scope", "scope=global" in glob_text)
        check("glob_has_principles", "# Principles" in glob_text and "keep the system simple" in glob_text)
        manifest = open(os.path.join(store, "materialize.json"), encoding="utf-8").read()
        check("manifest_has_surfaces", '"surfaces"' in manifest and '"materialized"' in manifest)
        check("manifest_has_both_keys", circ_md in manifest and glob_md in manifest)

        # ---- list: fresh ----
        p = run_cli(["materialize", "list"], store, base)
        check("list_rc0", p.returncode == 0, f"rc={p.returncode} {p.stderr.strip()[-120:]}")
        fresh_lines = [ln for ln in p.stdout.splitlines() if ln.startswith("fresh\t")]
        check("list_fresh_two", len(fresh_lines) == 2, f"fresh_lines={len(fresh_lines)}")

        # ---- store change -> stale ----
        c = MonetClient(store)
        try:
            c.initialize()
            c.call_json("memory_declare", {
                "species": "preference", "circle": circle,
                "content": "Prefers batched deploys over rolling ones."})
        finally:
            c.close()
        p = run_cli(["materialize", "list"], store, base)
        circ_line = [ln for ln in p.stdout.splitlines() if circ_md in ln]
        glob_line = [ln for ln in p.stdout.splitlines() if glob_md in ln]
        check("list_stale_circ", any(ln.startswith("stale\t") for ln in circ_line), f"{circ_line}")
        check("list_fresh_glob", any(ln.startswith("fresh\t") for ln in glob_line), f"{glob_line}")

        # ---- surface deleted -> block-missing ----
        os.remove(circ_md)
        p = run_cli(["materialize", "list"], store, base)
        circ_line = [ln for ln in p.stdout.splitlines() if circ_md in ln]
        check("list_block_missing", any(ln.startswith("block-missing\t") for ln in circ_line), f"{circ_line}")
        # restore so remove tests see a live surface
        run_cli(["materialize"], store, base)
        check("re_materialize_restores", os.path.exists(circ_md))

        # ---- remove ----
        p = run_cli(["materialize", "remove", glob_md], store, base)
        check("remove_glob_rc0", p.returncode == 0 and f"Removed {glob_md}" in p.stdout, f"rc={p.returncode} out={p.stdout.strip()}")
        manifest = open(os.path.join(store, "materialize.json"), encoding="utf-8").read()
        check("remove_updates_manifest", glob_md not in manifest, "")
        p = run_cli(["materialize", "remove", glob_md], store, base)
        check("remove_unregistered_refused", p.returncode != 0 and "surface is not registered" in (p.stdout + p.stderr))

        # ---- materialize error branches (isolated fresh registrations) ----
        # store-not-a-readable-file
        d2 = os.path.join(base, "store2"); os.makedirs(d2)
        extra = os.path.join(base, "EXTRA.md")
        p = run_cli(["materialize", "add", extra, "--circle", circle], d2, base)
        check("add_extra_registered", p.returncode == 0, "")
        os.mkdir(os.path.join(d2, "monet.db"))  # a DIRECTORY where the db file belongs
        p = run_cli(["materialize"], d2, base)
        check("materialize_store_not_readable", p.returncode != 0 and "not a readable database file" in (p.stdout + p.stderr),
              f"rc={p.returncode} {p.stderr.strip()[-140:]}")

        # lossy UTF-8 surface
        lossy = os.path.join(base, "LOSSY.md")
        with open(lossy, "wb") as fh:
            fh.write(b"untouched \xff\xfe bytes\n")
        p = run_cli(["materialize", "add", lossy, "--circle", circle], store, base)
        check("add_lossy_registered", p.returncode == 0, "")
        p = run_cli(["materialize"], store, base)
        check("materialize_lossy_refused", p.returncode != 0 and "not losslessly UTF-8-decodable" in (p.stdout + p.stderr),
              f"rc={p.returncode} {p.stderr.strip()[-140:]}")

        # dangling symlink
        dangling = os.path.join(base, "DANGLING.md")
        os.symlink(os.path.join(base, "no-such-target.md"), dangling)
        p = run_cli(["materialize", "add", dangling, "--circle", circle], store, base)
        check("add_dangling_registered", p.returncode == 0, "")
        p = run_cli(["materialize"], store, base)
        check("materialize_dangling_refused", p.returncode != 0 and "dangling symbolic link" in (p.stdout + p.stderr),
              f"rc={p.returncode} {p.stderr.strip()[-140:]}")

        # same-destination alias
        target = os.path.join(base, "TARGET.md")
        link = os.path.join(base, "LINK.md")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("shared target\n")
        os.symlink(target, link)
        p = run_cli(["materialize", "add", link, "--circle", circle], store, base)
        check("add_link_registered", p.returncode == 0, "")
        p = run_cli(["materialize", "add", target, "--circle", circle], store, base)
        check("add_alias_refused", p.returncode != 0 and "same-destination aliases" in (p.stdout + p.stderr),
              f"rc={p.returncode} {p.stderr.strip()[-140:]}")

    finally:
        shutil.rmtree(base, ignore_errors=True)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
        return 1
    print(f"\nRESULT: PASS — materialize-cli surface scenario green ({len(PASS)} assertions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
