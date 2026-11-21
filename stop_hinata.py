"""Stops every running Hinata / old Jarvis (any main.py started from a jarvis or Hinata folder)."""
import os
import sys

try:
    import psutil
except ImportError:
    print("psutil missing - can't look for running copies")
    sys.exit(0)

me = os.getpid()
stopped = 0
for p in psutil.process_iter(["pid", "name", "cmdline", "cwd"]):
    try:
        if p.info["pid"] == me:
            continue
        name = (p.info["name"] or "").lower()
        if not (name.startswith("python") or name in ("py.exe", "pyw.exe")):
            continue
        cmd = " ".join(p.info["cmdline"] or [])
        where = (p.info["cwd"] or "") + " " + cmd
        is_ours = ("main.py" in cmd or "hud_proc" in cmd or "cursor_proc" in cmd or "multiprocessing" in cmd) \
            and any(k in where.lower() for k in ("jarvis", "hinata"))
        if is_ours:
            print(f"stopped {p.info['pid']}: {cmd}  (in {p.info['cwd']})")
            p.kill()
            stopped += 1
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        continue
print(f"{stopped} Hinata/Jarvis process(es) stopped")
