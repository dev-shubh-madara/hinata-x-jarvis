"""Runs every test script: python tests/run_all.py"""
import glob, os, subprocess, sys

here = os.path.dirname(os.path.abspath(__file__))
bad = []
for f in sorted(glob.glob(os.path.join(here, "test_*.py"))):
    r = subprocess.run([sys.executable, f], capture_output=True, text=True, timeout=120)
    print(f"{'PASS' if r.returncode == 0 else 'FAIL'}  {os.path.basename(f)}")
    if r.returncode:
        bad.append(f)
        print(r.stdout[-1500:], r.stderr[-1500:])
print(f"\n{len(bad)} failed" if bad else "\nall tests passed")
sys.exit(1 if bad else 0)
