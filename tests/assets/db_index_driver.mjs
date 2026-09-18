// Pure-source driver for cli/db/index.ts (test43) — pins the storage-path
// resolution contract of every export, including the deliberately-divergent
// getMomentSpoolPath(). Bundled from source with esbuild (aliases
// @dbindex-src -> packages/cli/src/db/index.ts and @team-monet/core -> a
// GENERATED barrel that re-exports the REAL core modules, see test43), then
// executed with node@22. No store, no embedder, no ~/.monet touched (GR-01).
//
// RE-BASELINED (run 119) against upstream 9fa38c2. Two upstream moves broke the
// previous spelling of this driver:
//   - getGateMirrorPath / GATE_JOURNAL_FILENAME were RETIRED upstream, and the
//     deliberately-divergent path resolver moved with them: it is now
//     getMomentSpoolPath() + MOMENT_SPOOL_FILENAME ("moments.jsonl"). The
//     divergence itself is UNCHANGED (no project-local .monet rung, no
//     USERPROFILE fallback, home = os.homedir()) — the spool comment is
//     explicit that a shared record cannot survive two different resolutions.
//   - getStartupFailurePath() is NEW: it is DERIVED from the store path
//     (getDbPath + core's startupFailurePath), not assembled from a directory
//     plus a filename, so two stores in one directory can never share a record.
//
// The core alias is now a generated barrel over the REAL core sources instead
// of a hand-copied constant stub. The old stub is exactly how this test went
// STALE: core renamed its constant, the stub kept the old value, and the driver
// built clean while pinning a fiction. Importing the real module makes that
// impossible — only these two modules are re-exported, and both are pure
// (node:crypto / node:fs / node:path only), so no native dep is pulled in.
//
// Contract under test (all reverse-engineered from source, pinned as
// falsifiable assertions):
//   - getMonetDir rung order: MONET_STORAGE_DIR -> project-local ./.monet (only
//     if it EXISTS) -> HOME -> USERPROFILE -> baseDir.
//   - getDbPath / getMaterializePath = join(getMonetDir, const).
//   - getMomentSpoolPath DELIBERATELY diverges from getMonetDir: NOT routed
//     through it, no baseDir param, two rungs (MONET_STORAGE_DIR ->
//     os.homedir()/.monet). It therefore has NO project-local .monet rung and
//     NO USERPROFILE fallback. home = os.homedir(), which on POSIX follows
//     $HOME when set (matching the out-of-process writer contract) and
//     otherwise the passwd DB.
//   - getStartupFailurePath = startupFailurePath(getDbPath(baseDir)): a sidecar
//     OF THE STORE FILE (store name + STARTUP_FAILURE_SUFFIX resolved beside
//     it), never a per-directory name.
//   - ensureMonetDir mkdirSync(recursive), returns the resolved dir, idempotent,
//     honors the env rung, and — when NO env/home rung resolves — creates the
//     baseDir/.monet (the project-rung create path).
import path from "node:path";
import fs from "node:fs";
import os from "node:os";
import {
  getMonetDir,
  getDbPath,
  getMomentSpoolPath,
  getStartupFailurePath,
  getMaterializePath,
  ensureMonetDir,
} from "@dbindex-src";
import {
  MOMENT_SPOOL_FILENAME,
  STARTUP_FAILURE_SUFFIX,
  startupFailurePath,
} from "@team-monet/core";

const PASS = [];
const FAIL = [];

function check(name, cond, detail = "") {
  if (cond) {
    PASS.push(name);
    console.log(`  PASS ${name}` + (detail ? `  [${detail}]` : ""));
  } else {
    FAIL.push(name);
    console.log(`  FAIL ${name}` + (detail ? `  [${detail}]` : ""));
  }
}

// Sourced from the REAL core modules via the generated barrel, not hand-copied.
const SPOOL = MOMENT_SPOOL_FILENAME;
const SUFFIX = STARTUP_FAILURE_SUFFIX;
const DB = "monet.db";
const MAT = "materialize.json";

// Captured at load, before main() mutates env: the account's real home.
const realHome = os.homedir();

function mkdtemp(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix + "-"));
}

function setEnv(k, v) {
  if (v === undefined) delete process.env[k];
  else process.env[k] = v;
}

function freshEnv() {
  setEnv("MONET_STORAGE_DIR", undefined);
  setEnv("HOME", undefined);
  setEnv("USERPROFILE", undefined);
}

function main() {
  // --- Core constants (pinned literally ONCE, in the module that owns them) ---
  check("spool_filename_value", SPOOL === "moments.jsonl", String(SPOOL));
  check("startup_failure_suffix_value", SUFFIX === ".startup-failure.json", String(SUFFIX));

  // --- Scenario 1: MONET_STORAGE_DIR wins; everything roots there ---
  setEnv("MONET_STORAGE_DIR", mkdtemp("s1-store"));
  setEnv("HOME", mkdtemp("s1-home"));
  const proj1 = mkdtemp("s1-proj"); // no .monet inside
  const storage = process.env.MONET_STORAGE_DIR;

  check("monetdir_env_wins", getMonetDir(proj1) === storage, getMonetDir(proj1));
  check("monetdir_env_wins_noarg", getMonetDir() === storage);
  check("dbpath_under_env", getDbPath() === path.join(storage, DB), getDbPath());
  check("spool_under_env", getMomentSpoolPath() === path.join(storage, SPOOL), getMomentSpoolPath());
  check("materialize_under_env", getMaterializePath() === path.join(storage, MAT), getMaterializePath());
  check("startupfail_under_env", getStartupFailurePath() === path.join(storage, DB + SUFFIX), getStartupFailurePath());

  // --- Scenario 2: project-local ./.monet (already existing) beats home ---
  setEnv("MONET_STORAGE_DIR", undefined);
  const proj2 = mkdtemp("s2-proj");
  fs.mkdirSync(path.join(proj2, ".monet"));
  const home2 = mkdtemp("s2-home");
  setEnv("HOME", home2);

  check("monetdir_project_exists", getMonetDir(proj2) === path.join(proj2, ".monet"), getMonetDir(proj2));
  check("dbpath_under_project", getDbPath(proj2) === path.join(proj2, ".monet", DB), getDbPath(proj2));
  check("materialize_under_project", getMaterializePath(proj2) === path.join(proj2, ".monet", MAT), getMaterializePath(proj2));
  // the startup-failure record IS store-derived, so it does follow the project rung:
  check(
    "startupfail_under_project",
    getStartupFailurePath(proj2) === path.join(proj2, ".monet", DB + SUFFIX),
    getStartupFailurePath(proj2),
  );
  // ...while the spool does NOT (the documented divergence, asserted below too):
  check("spool_ignores_project_rung", getMomentSpoolPath() === path.join(home2, ".monet", SPOOL), getMomentSpoolPath());

  // --- Scenario 3: no project .monet -> HOME ---
  const proj3 = mkdtemp("s3-proj"); // NO .monet inside
  check("monetdir_home_fallback", getMonetDir(proj3) === path.join(home2, ".monet"), getMonetDir(proj3));

  // --- Scenario 4: no HOME -> USERPROFILE ---
  setEnv("HOME", undefined);
  const up = mkdtemp("s4-up");
  setEnv("USERPROFILE", up);
  check("monetdir_userprofile_fallback", getMonetDir(proj3) === path.join(up, ".monet"), getMonetDir(proj3));

  // --- Scenario 5: neither HOME nor USERPROFILE -> baseDir ---
  setEnv("USERPROFILE", undefined);
  check("monetdir_basedir_fallback", getMonetDir(proj3) === path.join(proj3, ".monet"), getMonetDir(proj3));

  // --- Scenario 6: getMomentSpoolPath divergence (the documented, deliberate one) ---
  // The spool is NOT routed through getMonetDir: it has no project-local .monet
  // rung and no USERPROFILE fallback. Home = os.homedir(), which on POSIX
  // follows $HOME when set and otherwise the passwd DB.
  freshEnv();
  const projJ = mkdtemp("s6-proj");
  fs.mkdirSync(path.join(projJ, ".monet")); // project-local store exists
  // getMonetDir honors the project rung...
  check("monetdir_project_rung", getMonetDir(projJ) === path.join(projJ, ".monet"), getMonetDir(projJ));
  // ...but the spool ignores it (no project rung) -> real home (passwd DB, HOME absent):
  check("spool_ignores_project_monet", getMomentSpoolPath() === path.join(realHome, ".monet", SPOOL), getMomentSpoolPath());
  check("spool_diverges_from_monetdir", getMomentSpoolPath() !== path.join(projJ, ".monet", SPOOL), getMomentSpoolPath());
  // USERPROFILE is NOT a home source for the spool:
  setEnv("USERPROFILE", mkdtemp("s6-up"));
  check("spool_ignores_userprofile", getMomentSpoolPath() === path.join(realHome, ".monet", SPOOL), getMomentSpoolPath());
  freshEnv();
  // HOME present -> os.homedir() == HOME (matches the out-of-process writer contract):
  const homeJ = mkdtemp("s6-home");
  setEnv("HOME", homeJ);
  check("spool_follows_home_env", getMomentSpoolPath() === path.join(homeJ, ".monet", SPOOL), getMomentSpoolPath());
  // env rung wins for the spool too:
  setEnv("MONET_STORAGE_DIR", storage);
  check("spool_env_rung", getMomentSpoolPath() === path.join(storage, SPOOL), getMomentSpoolPath());

  // --- Scenario 7: ensureMonetDir creates / returns / idempotent ---
  // home-rung create:
  freshEnv();
  const home7 = mkdtemp("s7-home");
  setEnv("HOME", home7);
  const proj7 = mkdtemp("s7-proj"); // no .monet
  const created = ensureMonetDir(proj7);
  check("ensure_creates_home_rung", created === path.join(home7, ".monet") && fs.existsSync(created), created);
  check("ensure_idempotent", ensureMonetDir(proj7) === created, "second call no throw");
  // baseDir-rung create (no env, no home -> project .monet is created):
  freshEnv();
  const proj9 = mkdtemp("s7-proj9");
  const c9 = ensureMonetDir(proj9);
  check("ensure_creates_project_rung", c9 === path.join(proj9, ".monet") && fs.existsSync(c9), c9);
  // env-rung create (recursive nested path):
  setEnv("MONET_STORAGE_DIR", path.join(mkdtemp("s7-env"), "nested", "deep"));
  const envCreated = ensureMonetDir();
  check("ensure_env_recursive", fs.existsSync(envCreated) && envCreated === process.env.MONET_STORAGE_DIR, envCreated);

  // --- Scenario 8: the startup-failure record is a sidecar OF A STORE ---
  // Cores own spelling (`startupFailurePath` is re-exported into this bundle
  // from the REAL core module), so these assertions pin the SHAPE, not a copy.
  const sidecar = startupFailurePath("/tmp/x/monet.db");
  check("startupfail_sidecar_shape", sidecar === "/tmp/x/" + DB + SUFFIX, sidecar);
  // The bug class this closes: one directory holding two stores (a dev server's
  // monet-core.db beside monet.db) must NOT share one record path.
  const a = startupFailurePath("/tmp/x/monet.db");
  const b = startupFailurePath("/tmp/x/monet-core.db");
  check("startupfail_distinct_per_store", a !== b && a.endsWith(SUFFIX) && b.endsWith(SUFFIX), `${a} != ${b}`);
  // Relative input is resolved before the sidecar is composed:
  const rel = startupFailurePath(path.join("rel", "monet.db"));
  check("startupfail_relative_resolved", rel === path.resolve("rel", "monet.db") + SUFFIX, rel);
  // and cli/db/index.ts composes it with its OWN store path (env rung):
  setEnv("MONET_STORAGE_DIR", mkdtemp("s8-store"));
  check(
    "startupfail_composed_from_dbpath",
    getStartupFailurePath() === getDbPath() + SUFFIX,
    getStartupFailurePath(),
  );

  console.log(`\nRESULT: ${PASS.length} passed, ${FAIL.length} failed`);
  return FAIL.length ? 1 : 0;
}

process.exit(main());
