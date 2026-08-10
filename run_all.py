#!/usr/bin/env python3
"""Monet E2E suite runner: runs every testNN_*.py and aggregates results.

Usage: python3 run_all.py
Exit code 0 if every test passes, 1 otherwise.
"""
import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = sorted(glob.glob(os.path.join(HERE, "test??_*.py")))


def main():
    total = passed = 0
    results = []
    for t in TESTS:
        total += 1
        t0 = time.time()
        p = subprocess.run([sys.executable, t], capture_output=True, text=True, cwd=HERE, timeout=600)
        dt = time.time() - t0
        ok = p.returncode == 0
        if ok:
            passed += 1
        results.append((os.path.basename(t), ok, dt, p.stdout.strip().splitlines()[-1] if p.stdout.strip() else ""))
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {os.path.basename(t)} ({dt:.1f}s) {results[-1][3]}")
        if not ok:
            print(p.stdout[-800:])
            print(p.stderr[-800:])
    print(f"\nSUITE: {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
