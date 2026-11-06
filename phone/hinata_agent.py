#!/usr/bin/env python3
"""
Hinata Link - the phone side.

Runs in Termux. Listens on the local network and runs the commands Hinata
sends from the laptop, with ADB-shell rights given by Shizuku (through `rish`).
No wireless-debugging pairing with the PC is needed: Shizuku pairs the phone
with itself.

Every request must be signed with the secret key from Hinata's setup QR
(HMAC-SHA256) and be fresh, so nobody else on the network can send commands.

    python hinata_agent.py            # normally started by install.sh / ~/.bashrc
"""

import base64
import hashlib
import hmac
import json
import os
import socket
import socketserver
import struct
import subprocess
import threading
import time
import zlib

HOME = os.path.expanduser("~")
CONF = os.path.join(HOME, ".hinata", "link.json")
RISH = os.environ.get("HINATA_RISH") or os.path.join(HOME, ".hinata", "rish")
PORT = int(os.environ.get("HINATA_PORT", "8737"))
MAX_FRAME = 64 * 1024 * 1024
MAX_AGE = 300            # seconds a request stays valid (allows for clock drift)

_seen = {}               # request id -> time, to refuse replays
_seen_lock = threading.Lock()


def load_key() -> bytes:
    with open(CONF, encoding="utf-8") as f:
        return json.load(f)["key"].encode()


# ---------------------------------------------------------------- framing (same as the laptop's link.py)

def pack(key: bytes, obj: dict) -> bytes:
    body = zlib.compress(json.dumps(obj, separators=(",", ":")).encode(), 6)
    mac = hmac.new(key, body, hashlib.sha256).digest()
    return struct.pack(">I", len(body) + 32) + mac + body


def read_exact(sock, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf.extend(chunk)
    return bytes(buf)


def unpack(key: bytes, sock) -> dict:
    (n,) = struct.unpack(">I", read_exact(sock, 4))
    if n < 32 or n > MAX_FRAME:
        raise ConnectionError("bad frame")
    data = read_exact(sock, n)
    mac, body = data[:32], data[32:]
    if not hmac.compare_digest(mac, hmac.new(key, body, hashlib.sha256).digest()):
        raise PermissionError("wrong key")
    return json.loads(zlib.decompress(body))


# ---------------------------------------------------------------- running commands

def run_shell(cmd: str, timeout: float, binary: bool):
    """Runs `cmd` with ADB-shell rights through Shizuku's rish."""
    argv = ["sh", "-c", cmd] if RISH == "sh" else ["sh", RISH, "-c", cmd]     # "sh" = test mode
    try:
        p = subprocess.run(argv, capture_output=True, timeout=max(1.0, timeout))
        out, err, rc = p.stdout, p.stderr.decode(errors="replace"), p.returncode
    except subprocess.TimeoutExpired:
        out, err, rc = b"", "timed out", 124
    except FileNotFoundError:
        out, err, rc = b"", "rish not found - export it from Shizuku (see setup)", 127
    if "shizuku" in err.lower() and ("not running" in err.lower() or "permission" in err.lower()):
        err += "  [Open Shizuku and press Start]"
    return rc, out, err


def handle(req: dict) -> dict:
    rid = str(req.get("id", ""))
    now = time.time()
    if abs(now - float(req.get("t", 0))) > MAX_AGE:
        return {"id": rid, "rc": 1, "err": "request too old - check the phone's clock"}
    with _seen_lock:
        if rid in _seen:
            return {"id": rid, "rc": 1, "err": "replayed request"}
        _seen[rid] = now
        for k in [k for k, v in _seen.items() if now - v > MAX_AGE]:
            del _seen[k]
    op = req.get("op")
    if op == "hello":
        rc, out, err = run_shell("getprop ro.product.model", 8, False)
        return {"id": rid, "rc": 0, "model": out.decode(errors="replace").strip() or "your phone",
                "shizuku": rc == 0, "err": err}
    if op == "sh":
        rc, out, err = run_shell(str(req.get("cmd", "")), float(req.get("timeout", 20)), bool(req.get("bin")))
        return {"id": rid, "rc": rc, "out": base64.b64encode(out).decode(), "err": err[-2000:]}
    return {"id": rid, "rc": 1, "err": f"unknown op {op!r}"}


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        key = load_key()
        self.request.settimeout(600)
        try:
            while True:
                req = unpack(key, self.request)
                self.request.sendall(pack(key, handle(req)))
        except PermissionError:
            print(f"[agent] refused {self.client_address[0]} (wrong key)")
        except (ConnectionError, socket.timeout, OSError):
            pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    load_key()                                   # fail early if setup didn't run
    print(f"[agent] Hinata Link listening on port {PORT}  (rish: {RISH})")
    rc, out, err = run_shell("echo ok", 8, False)
    print("[agent] Shizuku:", "ready" if rc == 0 and b"ok" in out else f"NOT ready - {err.strip()}")
    with Server(("0.0.0.0", PORT), Handler) as srv:
        srv.serve_forever()


if __name__ == "__main__":
    main()
