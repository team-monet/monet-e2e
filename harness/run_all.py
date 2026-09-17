#!/usr/bin/env python3
"""Monet E2E suite runner: runs every test in ../tests/ and aggregates results.

Usage: python3 harness/run_all.py

Per-test exit codes (the authoritative signal):
  0 = PASS   — all assertions held.
  1 = FAIL   — unexpected failure (real regression or a broken test). Fails suite.
  2 = XFAIL  — expected failure: the test documents a KNOWN OPEN bug (tagged
               with an RE-XX id). NOT a suite failure; the bug is still present.
  3 = XPASS  — unexpected pass: a known-bug test now passes, i.e. the bug
               appears FIXED. Suite stays green, but a loud warning is emitted
               so the issue status can be updated.
  4 = INCONCLUSIVE — the test could not reach a verdict (e.g. a lock/timeout
               hit the probe, or a known-bug guard partially flipped). NOT a
               suite failure and NOT a flip signal: re-run on a quiet machine.
               Never treat 4 as "fixed" or as "still broken".
  5 = STALE  — the test could not reach what it pinned (a driver target source
               that upstream deleted/renamed, a pure-source build that no longer
               compiles against the monorepo, or a driver expectation that
               predates an upstream behaviour flip). NOT a product verdict: the
               harness drifted. Suite stays green but prints a loud STALE block
               — these tests must be re-baselined, and until then they provide
               NO coverage. Never record a STALE test as PASS in metrics.

Suite exit: 0 if there are no FAILs (XFAIL/XPASS/INCONCLUSIVE/STALE do not fail
the suite), else 1.
"""
import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = sorted(glob.glob(os.path.join(HERE, "..", "tests", "test??_*.py")))


def _result_line(stdout):
    """Extract the per-test `RESULT:` summary line, wherever it appears.

    Some tests print diagnostic lines (e.g. `OBSERVED versions: [...]`) AFTER
    their `RESULT:` line, so simply taking the last line misreports the
    summary. Grep for the `RESULT:` prefix instead; fall back to the last
    non-empty line if no `RESULT:` line is present.
    """
    lines = [ln for ln in stdout.strip().splitlines() if ln.strip()]
    for ln in reversed(lines):
        if ln.startswith("RESULT:"):
            return ln
    return lines[-1] if lines else ""


def main():
    total = passed = xfail = xpass = inconclusive = stale = 0
    failures = []
    stale_tests = []
    for t in TESTS:
        total += 1
        t0 = time.time()
        p = subprocess.run([sys.executable, t], capture_output=True, text=True, cwd=os.path.dirname(t), timeout=600)
        dt = time.time() - t0
        rc = p.returncode
        name = os.path.basename(t)
        line = _result_line(p.stdout)
        if rc == 0:
            passed += 1
            print(f"[PASS ] {name} ({dt:.1f}s) {line}")
        elif rc == 2:
            xfail += 1
            print(f"[XFAIL] {name} ({dt:.1f}s) {line}")
        elif rc == 3:
            xpass += 1
            print(f"[XPASS] {name} ({dt:.1f}s) {line}  <<< bug appears FIXED — update issue status")
        elif rc == 4:
            inconclusive += 1
            print(f"[INCON] {name} ({dt:.1f}s) {line}  <<< no verdict — re-run, do NOT flip")
        elif rc == 5:
            stale += 1
            stale_tests.append(name)
            print(f"[STALE] {name} ({dt:.1f}s) {line}  <<< harness drifted — re-baseline; provides NO coverage")
            print(p.stdout[-500:])
        else:
            failures.append(name)
            print(f"[FAIL ] {name} ({dt:.1f}s) {line}")
            print(p.stdout[-800:])
            print(p.stderr[-800:])

    print(f"\nSUITE: {passed}/{total} passed", end="")
    if xfail:
        print(f", {xfail} xfail (known open bugs — expected)", end="")
    if xpass:
        print(f", {xpass} XPASS (bug appears fixed)", end="")
    if inconclusive:
        print(f", {inconclusive} INCONCLUSIVE (no verdict — re-run, do not flip)", end="")
    if stale:
        print(f", {stale} STALE (harness drifted — re-baseline)", end="")
    print()
    if xpass:
        print("⚠️  XPASS detected: a known-bug test now passes. The corresponding RE issue")
        print("    may be fixed in this Monet version — verify and update its status to closed.")
    if inconclusive:
        print("⚠️  INCONCLUSIVE test(s): a guard reached no verdict (lock/timeout/partial flip).")
        print("    Re-run those tests before recording any flip or regression.")
    if stale:
        print(f"⚠️  STALE test(s) — {', '.join(stale_tests)}")
        print("    These could not reach what they pinned (deleted/renamed source, build no")
        print("    longer compiles against the monorepo, or expectations predating a behaviour")
        print("    flip). They provide NO coverage until re-baselined, and their RESULT line is")
        print("    NOT evidence about the product: never record them as PASS, and never cite")
        print("    them as proof that a shipped behaviour is unchanged.")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
