"""
Hinata Link - the laptop side.

Talks to the small helper running on the phone (phone/hinata_agent.py in
Termux, with Shizuku for ADB-shell rights). The laptop connects *to* the phone
over the laptop hotspot / same Wi-Fi, so there is no wireless-debugging pairing
and nothing has to get through the laptop's firewall.

phone_control.adb() routes its "shell", "exec-out" and "pull" calls through
here whenever the link is up, so every phone feature keeps working unchanged.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import socket
import struct
import subprocess
import threading
import time
import zlib

import config

PORT = 8737
REPO_RAW = "https://raw.githubusercontent.com/dev-shubh-madara/hinata-x-jarvis/main/phone/install.sh"
_FILE = os.path.join(config.DATA_DIR, "link.json")
_lock = threading.RLock()
_state = {"sock": None, "ip": None, "model": None, "last_ok": 0.0, "last_try": 0.0}


# ---------------------------------------------------------------- saved settings

def _load() -> dict:
    try:
        with open(_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(d: dict):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f)


def paired() -> bool:
    return bool(_load().get("key"))


def new_key() -> str:
    """A fresh secret for a new phone setup (kept until the phone confirms)."""
    d = _load()
    d["pending_key"] = secrets.token_urlsafe(24)
    _save(d)
    return d["pending_key"]


def setup_command(key: str) -> str:
    return f"curl -fsSL {REPO_RAW} | bash -s {key}"


# ---------------------------------------------------------------- framing (same as hinata_agent.py)

def _pack(key: bytes, obj: dict) -> bytes:
    body = zlib.compress(json.dumps(obj, separators=(",", ":")).encode(), 6)
    return struct.pack(">I", len(body) + 32) + hmac.new(key, body, hashlib.sha256).digest() + body


def _read_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf.extend(chunk)
    return bytes(buf)


def _unpack(key: bytes, sock) -> dict:
    (n,) = struct.unpack(">I", _read_exact(sock, 4))
    data = _read_exact(sock, n)
    mac, body = data[:32], data[32:]
    if not hmac.compare_digest(mac, hmac.new(key, body, hashlib.sha256).digest()):
        raise PermissionError("phone answered with a different key")
    return json.loads(zlib.decompress(body))


# ---------------------------------------------------------------- connection

def _candidates(extra=()) -> list[str]:
    import hotspot
    ips = list(extra)
    saved = _load().get("ip")
    if saved:
        ips.append(saved)
    try:
        ips += hotspot.client_ips()
    except Exception:
        pass
    if len(ips) <= 1:                         # normal Wi-Fi at home: try nearby devices too
        try:
            me = socket.gethostbyname(socket.gethostname())
            if me.count(".") == 3 and not me.startswith("127."):
                ips += hotspot.arp_neighbors(me.rsplit(".", 1)[0] + ".")[:6]
        except Exception:
            pass
    seen, out = set(), []
    for ip in ips:
        if ip and ip not in seen:
            seen.add(ip)
            out.append(ip)
    return out[:8]


def _hello(ip: str, key: str, timeout: float = 1.5):
    s = socket.create_connection((ip, PORT), timeout=timeout)
    s.settimeout(10)
    kb = key.encode()
    s.sendall(_pack(kb, {"id": secrets.token_hex(8), "t": time.time(), "op": "hello"}))
    res = _unpack(kb, s)
    return s, res


def connect(key: str | None = None, ips=(), quiet: bool = False) -> bool:
    """Finds the phone helper and opens a connection. key=None uses the saved key."""
    d = _load()
    key = key or d.get("key")
    if not key:
        return False
    with _lock:
        _close()
        for ip in _candidates(ips):
            try:
                s, res = _hello(ip, key)
            except PermissionError:
                if not quiet:
                    print(f"[link] {ip} has a different key - scan the setup QR again")
                continue
            except Exception:
                continue
            _state.update(sock=s, ip=ip, model=res.get("model"), last_ok=time.time())
            d.update(key=key, ip=ip, model=res.get("model"))
            d.pop("pending_key", None)
            _save(d)
            if not quiet:
                shz = "" if res.get("shizuku") else "  (Shizuku isn't running - open Shizuku > Start)"
                print(f"[link] connected to {res.get('model')} at {ip}{shz}")
            return True
    return False


def _close():
    s = _state.get("sock")
    _state["sock"] = None
    if s:
        try:
            s.close()
        except Exception:
            pass


def alive(retry: bool = True) -> bool:
    """True when the phone helper answers. Reconnects (cheaply) when needed."""
    if not paired():
        return False
    with _lock:
        if _state["sock"] and time.time() - _state["last_ok"] < 20:
            return True
        if _state["sock"]:
            try:
                _request({"op": "hello"}, timeout=4)
                return True
            except Exception:
                _close()
        if not retry or time.time() - _state["last_try"] < 3:
            return False
        _state["last_try"] = time.time()
        return connect(quiet=True)


def model() -> str:
    return _state.get("model") or _load().get("model") or "your phone"


def _request(payload: dict, timeout: float = 20) -> dict:
    key = _load()["key"].encode()
    s = _state["sock"]
    if not s:
        raise ConnectionError("not connected")
    payload = dict(payload, id=secrets.token_hex(8), t=time.time())
    s.settimeout(timeout + 5)
    s.sendall(_pack(key, payload))
    res = _unpack(key, s)
    _state["last_ok"] = time.time()
    return res


def run(cmd: str, timeout: float = 20, binary: bool = False) -> subprocess.CompletedProcess:
    """Runs a shell command on the phone (ADB-shell rights). Same shape as subprocess.run."""
    with _lock:
        for attempt in range(2):
            try:
                if not _state["sock"] and not connect(quiet=True):
                    break
                res = _request({"op": "sh", "cmd": cmd, "timeout": timeout, "bin": binary}, timeout)
                out = base64.b64decode(res.get("out") or "")
                return subprocess.CompletedProcess(cmd, int(res.get("rc", 1)),
                                                   stdout=out if binary else out.decode(errors="replace"),
                                                   stderr=res.get("err", ""))
            except Exception as e:
                _close()
                if attempt:
                    print(f"[link] command failed: {e}")
    return subprocess.CompletedProcess(cmd, 1, stdout=b"" if binary else "", stderr="phone link not connected")


# ---------------------------------------------------------------- adb-compatible bridge

def _quote(a: str) -> str:
    if a and all(c.isalnum() or c in "@%+=:,./-_" for c in a):
        return a
    return "'" + a.replace("'", "'\"'\"'") + "'"


def adb_compat(args: list[str], timeout: float, binary: bool):
    """Turns the adb calls phone_control makes into commands for the phone helper."""
    if not args:
        return None
    head = args[0]
    if head in ("shell", "exec-out"):
        rest = args[1:]
        cmd = rest[0] if len(rest) == 1 else " ".join(_quote(a) for a in rest)
        return run(cmd, timeout=timeout, binary=binary)
    if head == "pull" and len(args) >= 3:
        res = run(f"cat {_quote(args[1])}", timeout=timeout, binary=True)
        if res.returncode == 0:
            with open(args[2], "wb") as f:
                f.write(res.stdout)
        return subprocess.CompletedProcess(args, res.returncode, stdout="", stderr=res.stderr)
    return None                      # devices/connect/pair... are not used over the link
