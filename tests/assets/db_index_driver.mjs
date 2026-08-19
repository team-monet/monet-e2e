// Pure-source driver for cli/db/index.ts (test43) — pins the storage-path
// resolution contract of every function, including the deliberately-divergent
// getGateJournalPath(). Bundled from source with esbuild (aliases
// @dbindex-src -> packages/cli/src/db/index.ts and @team-monet/core -> a stub
// exporting just GATE_JOURNAL_FILENAME), then executed with node@22. No store,
// no embedder, no ~/.monet touched (GR-01).
//
// Contract under test (all reverse-engineered from source, pinned as
// falsifiable assertions):
//   - getMonetDir rung order: MONET_STORAGE_DIR -> project-local ./.monet (only
//     if it EXISTS) -> HOME -> USERPROFILE -> baseDir.
//   - getDbPath / getGateMirrorPath / getMaterializePath = join(getMonetDir, const).
//   - getGateJournalPath DELIBERATELY diverges from getMonetDir: NOT routed
//     through it, no baseDir param, two rungs (MONET_STORAGE_DIR ->
//     os.homedir()/.monet). It therefore has NO project-local .monet rung and
//     NO USERPROFILE fallback. home = os.homedir(), which on POSIX follows
//     $HOME when set (matching the generated hook wrapper) and otherwise the
//     passwd DB.
//   - ensureMonetDir mkdirSync(recursive), returns the resolved dir, idempotent,
//     honors the env rung, and — when NO env/home rung resolves — creates the
//     baseDir/.monet (the project-rung create path).
import path from "node:path";
import fs from "node:fs";
import os from "node:os";
import {
  getMonetDir,
  getDbPath,
  getGateMirrorPath,
  getGateJournalPath,
  getMaterializePath,
  ensureMonetDir,
} from "@dbindex-src";

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

const GATE_J = "gate-journal.jsonl"; // = GATE_JOURNAL_FILENAME from core
const DB = "monet.db";
const MIRROR = "gate-mirror.json";
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
  // --- Scenario 1: MONET_STORAGE_DIR wins; everything roots there ---
  setEnv("MONET_STORAGE_DIR", mkdtemp("s1-store"));
  setEnv("HOME", mkdtemp("s1-home"));
  const proj1 = mkdtemp("s1-proj"); // no .monet inside
  const storage = process.env.MONET_STORAGE_DIR;

  check("monetdir_env_wins", getMonetDir(proj1) === storage, getMonetDir(proj1));
  check("monetdir_env_wins_noarg", getMonetDir() === storage);
  check("dbpath_under_env", getDbPath() === path.join(storage, DB), getDbPath());
  check("mirror_under_env", getGateMirrorPath() === path.join(storage, MIRROR), getGateMirrorPath());
  check("materialize_under_env", getMaterializePath() === path.join(storage, MAT), getMaterializePath());
  check("journal_under_env", getGateJournalPath() === path.join(storage, GATE_J), getGateJournalPath());

  // --- Scenario 2: project-local ./.monet (already existing) beats home ---
  setEnv("MONET_STORAGE_DIR", undefined);
  const proj2 = mkdtemp("s2-proj");
  fs.mkdirSync(path.join(proj2, ".monet"));
  const home2 = mkdtemp("s2-home");
  setEnv("HOME", home2);

  check("monetdir_project_exists", getMonetDir(proj2) === path.join(proj2, ".monet"), getMonetDir(proj2));
  check("dbpath_under_project", getDbPath(proj2) === path.join(proj2, ".monet", DB), getDbPath(proj2));
  check("mirror_under_project", getGateMirrorPath(proj2) === path.join(proj2, ".monet", MIRROR), getGateMirrorPath(proj2));
  check("materialize_under_project", getMaterializePath(proj2) === path.join(proj2, ".monet", MAT), getMaterializePath(proj2));

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

  // --- Scenario 6: getGateJournalPath divergence (the documented, deliberate one) ---
  // The journal is NOT routed through getMonetDir: it has no project-local
  // .monet rung and no USERPROFILE fallback. Home = os.homedir(), which on
  // POSIX follows $HOME when set and otherwise the passwd DB.
  freshEnv();
  const projJ = mkdtemp("s6-proj");
  fs.mkdirSync(path.join(projJ, ".monet")); // project-local store exists
  // getMonetDir honors the project rung...
  check("monetdir_project_rung", getMonetDir(projJ) === path.join(projJ, ".monet"), getMonetDir(projJ));
  // ...but the journal ignores it (no project rung) -> real home (passwd DB, HOME absent):
  check("journal_ignores_project_monet", getGateJournalPath() === path.join(realHome, ".monet", GATE_J), getGateJournalPath());
  check("journal_diverges_from_monetdir", getGateJournalPath() !== path.join(projJ, ".monet", GATE_J), getGateJournalPath());
  // USERPROFILE is NOT a home source for the journal:
  setEnv("USERPROFILE", mkdtemp("s6-up"));
  check("journal_ignores_userprofile", getGateJournalPath() === path.join(realHome, ".monet", GATE_J), getGateJournalPath());
  freshEnv();
  // HOME present -> os.homedir() == HOME (matches the generated hook wrapper):
  const homeJ = mkdtemp("s6-home");
  setEnv("HOME", homeJ);
  check("journal_follows_home_env", getGateJournalPath() === path.join(homeJ, ".monet", GATE_J), getGateJournalPath());
  // env rung wins for the journal too:
  setEnv("MONET_STORAGE_DIR", storage);
  check("journal_env_rung", getGateJournalPath() === path.join(storage, GATE_J), getGateJournalPath());

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

  console.log(`\nRESULT: ${PASS.length} passed, ${FAIL.length} failed`);
  return FAIL.length ? 1 : 0;
}

process.exit(main());
