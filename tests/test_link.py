"""Hinata Link end-to-end: the real phone helper (with plain sh instead of Shizuku's rish)
talking to the real laptop code over TCP."""
import os, socket, subprocess, sys, tempfile, time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()

import link, hotspot, phone_control as pc

PORT = 18737
link.PORT = PORT
home = tempfile.mkdtemp()
os.makedirs(os.path.join(home, ".hinata"))
with open(os.path.join(home, ".hinata", "link.json"), "w") as f:
    f.write('{"key": "test-key-123"}')
env = dict(os.environ, HOME=home, HINATA_RISH="sh", HINATA_PORT=str(PORT))


def start_agent():
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "phone", "hinata_agent.py")], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close()
            return p
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("agent didn't start")


agent = start_agent()
hotspot.client_ips = lambda: ["127.0.0.1"]
fails = 0


def check(name, cond):
    global fails
    fails += not cond
    print(("OK  " if cond else "FAIL"), name)


try:
    check("wrong key refused", not link.connect(key="nope", quiet=True))
    check("connect with the setup key", link.connect(key="test-key-123", quiet=True))
    check("paired and alive", link.paired() and link.alive())
    check("phone_control sees the phone", pc.is_connected())

    r = pc.adb(["shell", "echo", "hello world", "it's me"])
    check("shell with quoting", r.stdout.strip() == "hello world it's me")
    check("single-string shell", pc.shell("echo $((6*7))") == "42")

    blob = bytes(range(256)) * 50
    src = os.path.join(home, "img.bin")
    with open(src, "wb") as f:
        f.write(blob)
    r = pc.adb(["exec-out", "cat", src], binary=True)
    check("binary exec-out (screenshots)", r.stdout == blob)

    dst = os.path.join(home, "pulled.bin")
    pc.adb(["pull", src, dst])
    check("pull", open(dst, "rb").read() == blob)

    big = pc.adb(["shell", "head -c 3000000 /dev/zero | tr '\\0' 'a'"], timeout=30)
    check("3 MB reply (UI dumps)", len(big.stdout) == 3000000)

    t = time.time()
    for _ in range(20):
        pc.shell("echo x")
    check(f"20 commands in {time.time() - t:.2f}s", time.time() - t < 5)

    k = b"test-key-123"
    s = socket.create_connection(("127.0.0.1", PORT))
    frame = link._pack(k, {"id": "fixed1", "t": time.time(), "op": "sh", "cmd": "echo once"})
    s.sendall(frame); a = link._unpack(k, s)
    s.sendall(frame); b = link._unpack(k, s)
    check("replayed request refused", a["rc"] == 0 and "replayed" in b.get("err", ""))
    s.close()

    agent.terminate(); agent.wait()
    agent = start_agent()                          # phone helper restarted (e.g. Termux reopened)
    link._state["last_ok"] = 0
    link._state["last_try"] = 0
    check("reconnects after the helper restarts", pc.shell("echo back") == "back")
finally:
    agent.terminate()

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
