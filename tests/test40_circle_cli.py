#!/usr/bin/env python3
"""Scenario (CLI surface): `monet start` circle derivation — cli/circle.ts (test40).

The MCP stdio surface drives `monet start`, which calls `deriveCircle(projectDir)`
(cli.ts:70) and prints `Storage:`/`Circle:` to stderr before serving. That stderr
`Circle:` line is the ONLY CLI-observable surface for cli/circle.ts's deriveCircle
branch logic (god-mode override, folder-hash fallback, remote->circle map, Class A
alias-follow, Class B memory-keep). test35/37/39 covered config/install/gate; this
scenario covers the last big non-deprecated CLI gap (cli/circle.ts was 36.5%).

`monet start` is the MCP server (blocks), so we spawn it, read stderr until the
`Circle:` line appears, then kill. Safe against GR-01: every store is a fresh temp
dir via `-d`, never ~/.monet.

Arms (each uses a fresh store dir + a git repo whose origin is controlled):
A. MONET_CIRCLE env override wins outright -> returns the override, trimmed.
B. No git / no remote -> folder-hash fallback (deriveFolderCircle, e.g. <base>-<hash>).
C. Genuinely-new repo with an origin remote, no map/alias/memory -> defaultNameFromRemote
   (host-org-repo slug), and NO remote_circle_map row is persisted.
D. Mapped remote: a remote_circle_map row for the canonical key -> returns the mapped circle.
E. Class A: no map, but the folder-hash slug is aliased in circle_aliases -> follows the alias.
F. Class B: no map, no alias, but memory (a concept row) lives under the folder-hash slug
   -> keeps the slug and persists a remote_circle_map row (anti-orphan guard).
G. (folded into F) after the Class-B writeMap, a re-run resolves via readMap -> same circle.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient, CLI, NODE_PATH

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def start_read_circle(store_dir, project_dir=None, extra=None, timeout=40):
    """Spawn `monet start -d <store>` via the harness, read stderr until `Circle:`.

    Uses MonetClient's proven clean-shutdown path (close stdin -> graceful exit ->
    V8 coverage flush), which is what lets this test actually exercise the lines it
    claims to cover (GR-03). Returns (circle, stderr_tail).
    """
    saved = {k: os.environ.get(k) for k in ("MONET_PROJECT_DIR", "MONET_CIRCLE")}
    try:
        if project_dir:
            os.environ["MONET_PROJECT_DIR"] = project_dir
        if extra:
            os.environ.update(extra)
        c = MonetClient(store_dir)
        try:
            deadline = time.time() + timeout
            while time.time() < deadline:
                # give the reader thread time to drain stderr
                time.sleep(0.1)
                for ln in c.stderr_lines:
                    if "Circle:" in ln:
                        circle = ln.split("Circle:", 1)[1].strip()
                        return circle, "\n".join(c.stderr_lines)
            return None, "\n".join(c.stderr_lines)
        finally:
            c.close()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def git_init(dirpath, origin_url=None):
    """Init a git repo; optionally add an origin remote; always commit a file."""
    os.makedirs(dirpath, exist_ok=True)
    subprocess.run(["git", "init", "-q", dirpath], check=True)
    subprocess.run(["git", "-C", dirpath, "config", "user.email", "e2e@test"], check=True)
    subprocess.run(["git", "-C", dirpath, "config", "user.name", "e2e"], check=True)
    with open(os.path.join(dirpath, "file.txt"), "w") as f:
        f.write("hello\n")
    subprocess.run(["git", "-C", dirpath, "add", "-A"], check=True)
    subprocess.run(["git", "-C", dirpath, "commit", "-qm", "init"], check=True)
    if origin_url:
        subprocess.run(["git", "-C", dirpath, "remote", "add", "origin", origin_url], check=True)
    return dirpath


def add_origin(dirpath, origin_url):
    subprocess.run(["git", "-C", dirpath, "remote", "add", "origin", origin_url], check=True)


def db_path(store_dir):
    return os.path.join(store_dir, "monet.db")


def main():
    ORIGIN = "git@github.com:team-monet/e2e-circle.git"
    CANON = "github.com/team-monet/e2e-circle"  # canonicalRemoteKey(ORIGIN)

    # ---- A. MONET_CIRCLE override wins ----
    with tempfile.TemporaryDirectory() as td:
        store = os.path.join(td, "store")
        proj = git_init(os.path.join(td, "repo"), ORIGIN)
        circle, err = start_read_circle(store, proj, {"MONET_CIRCLE": "  my-override  "})
        check("A_override_circle", circle == "my-override", f"got={circle!r}")

    # ---- B. no git -> folder-hash fallback ----
    with tempfile.TemporaryDirectory() as td:
        store = os.path.join(td, "store")
        proj = os.path.join(td, "plain")  # NOT a git repo
        os.makedirs(proj)
        circle, err = start_read_circle(store, proj)
        check("B_folder_hash", circle is not None and not circle.startswith("github."),
              f"got={circle!r}")
        folder_slug_B = circle

    # ---- C. genuinely-new repo + origin remote -> defaultNameFromRemote, no map row ----
    with tempfile.TemporaryDirectory() as td:
        store = os.path.join(td, "store")
        proj = git_init(os.path.join(td, "repo"), ORIGIN)
        circle, err = start_read_circle(store, proj)
        check("C_default_remote_name", circle == "github.com-team-monet-e2e-circle",
              f"got={circle!r}")
        db = db_path(store)
        if os.path.exists(db):
            conn = sqlite3.connect(db)
            row = conn.execute(
                "SELECT count(*) FROM remote_circle_map WHERE remote_url=?", (CANON,)
            ).fetchone()
            conn.close()
            check("C_no_map_write_on_genuinely_new", (row[0] if row else 1) == 0,
                  f"map_rows={row}")
        else:
            check("C_no_map_write_on_genuinely_new", False, "no db created")

    # ---- D. mapped remote -> returns mapped circle ----
    with tempfile.TemporaryDirectory() as td:
        store = os.path.join(td, "store")
        proj = git_init(os.path.join(td, "repo"), ORIGIN)
        start_read_circle(store, proj)  # create schema + remote_circle_map table
        conn = sqlite3.connect(db_path(store))
        conn.execute("INSERT INTO remote_circle_map (remote_url, circle) VALUES (?,?)",
                     (CANON, "mapped-circle"))
        conn.commit()
        conn.close()
        circle, err = start_read_circle(store, proj)
        check("D_mapped", circle == "mapped-circle", f"got={circle!r}")

    # ---- E. Class A: no map, folder-hash slug aliased -> follow alias ----
    with tempfile.TemporaryDirectory() as td:
        # derive folder-hash slug for THIS repo dir by reading it before adding origin
        repo = os.path.join(td, "repo")
        store = os.path.join(td, "store")
        store_plain = os.path.join(td, "store_plain")
        git_init(repo)  # no origin yet -> deriveCircle returns folder-hash
        slug, _ = start_read_circle(store_plain, repo)
        check("E_folder_slug_derived", slug is not None, f"got={slug!r}")
        add_origin(repo, ORIGIN)
        start_read_circle(store, repo)  # create schema on the real store
        conn = sqlite3.connect(db_path(store))
        conn.execute(
            "INSERT INTO circle_aliases (from_name, to_name, status) VALUES (?,?,?)",
            (slug, "aliased-circle", "active"),
        )
        conn.commit()
        conn.close()
        circle, err = start_read_circle(store, repo)
        check("E_classA_follows_alias", circle == "aliased-circle",
              f"got={circle!r} (slug={slug})")

    # ---- F+G. Class B: no map/alias but memory under folder-hash slug -> keep slug + writeMap ----
    with tempfile.TemporaryDirectory() as td:
        repo = os.path.join(td, "repo")
        store = os.path.join(td, "store")
        store_plain = os.path.join(td, "store_plain")
        git_init(repo)  # no origin -> folder-hash slug
        slug, _ = start_read_circle(store_plain, repo)
        add_origin(repo, ORIGIN)
        start_read_circle(store, repo)  # schema on real store
        conn = sqlite3.connect(db_path(store))
        conn.execute(
            "INSERT INTO concepts (id, slug, title, body, kind, status, circle, embedding) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("c-classb", "e2e", "e2e", "e2e memory under folder slug", "fact", "active",
             slug, '[]'),
        )
        conn.commit()
        conn.close()
        circle, err = start_read_circle(store, repo)
        check("F_classB_keeps_slug", circle == slug, f"got={circle!r} (slug={slug})")
        conn = sqlite3.connect(db_path(store))
        row = conn.execute(
            "SELECT circle FROM remote_circle_map WHERE remote_url=?", (CANON,)
        ).fetchone()
        conn.close()
        check("F_classB_writeMap", row is not None and row[0] == slug, f"map_row={row}")
        circle2, err = start_read_circle(store, repo)
        check("G_reread_stable_via_map", circle2 == slug, f"got={circle2!r}")

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
