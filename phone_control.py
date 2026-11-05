"""
Android phone control over ADB (Android Debug Bridge - Google's official
developer tool). Pair once with the QR code ("pair to phone", see
phone_pair.py) and Hinata can drive the phone: open any app, tap buttons
by their on-screen text, type, swipe, call contacts by name, text, take
screenshots, toggle Wi-Fi/Bluetooth, mirror the screen, and more.

Every function returns a short sentence to speak. handle() is the fast
regex path; anything it doesn't recognise returns None so the AI agent
can work it out with the phone tools instead.
"""

import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile

import config

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_state = {"serial": None, "adb": None, "packages": None, "packages_at": 0.0, "screen": None}
PLATFORM_TOOLS_URL = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"

APP_PACKAGES = {
    "swiggy": "in.swiggy.android", "zomato": "com.application.zomato",
    "zepto": "com.zeptoconsumerapp", "blinkit": "com.grofers.customerapp",
    "whatsapp": "com.whatsapp", "whatsapp business": "com.whatsapp.w4b",
    "youtube": "com.google.android.youtube", "youtube music": "com.google.android.apps.youtube.music",
    "instagram": "com.instagram.android", "facebook": "com.facebook.katana",
    "telegram": "org.telegram.messenger", "snapchat": "com.snapchat.android",
    "gallery": "com.google.android.apps.photos", "photos": "com.google.android.apps.photos",
    "settings": "com.android.settings", "chrome": "com.android.chrome",
    "gmail": "com.google.android.gm", "maps": "com.google.android.apps.maps",
    "spotify": "com.spotify.music", "play store": "com.android.vending",
    "camera": None, "phone": None, "dialer": None, "messages": None, "contacts": None,
    "clock": None, "calculator": None, "files": None,
}
GENERIC_INTENTS = {   # apps whose package differs per brand -> launch by intent
    "camera": ["-a", "android.media.action.STILL_IMAGE_CAMERA"],
    "phone": ["-a", "android.intent.action.DIAL"],
    "dialer": ["-a", "android.intent.action.DIAL"],
    "messages": ["-a", "android.intent.action.MAIN", "-c", "android.intent.category.APP_MESSAGING"],
    "contacts": ["-a", "android.intent.action.MAIN", "-c", "android.intent.category.APP_CONTACTS"],
    "calculator": ["-a", "android.intent.action.MAIN", "-c", "android.intent.category.APP_CALCULATOR"],
    "clock": ["-a", "android.intent.action.SHOW_ALARMS"],
    "files": ["-a", "android.intent.action.MAIN", "-c", "android.intent.category.APP_FILES"],
}
KEYS = {"home": 3, "back": 4, "call": 5, "end call": 6, "volume up": 24, "volume down": 25,
        "power": 26, "camera": 27, "menu": 82, "play pause": 85, "next": 87, "previous": 88,
        "mute": 164, "recents": 187, "wake": 224, "sleep": 223, "enter": 66, "delete": 67,
        "search": 84, "brightness up": 221, "brightness down": 220}


# ---------------------------------------------------------------- adb plumbing

def adb_path(download: bool = False) -> str | None:
    if _state["adb"] and os.path.isfile(_state["adb"]):
        return _state["adb"]
    # our own copy first (always recent), then the Android SDK, then whatever is on PATH
    candidates = [os.path.join(config.DATA_DIR, "platform-tools", "adb.exe"),
                  os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk", "platform-tools", "adb.exe"),
                  shutil.which("adb")]
    for c in candidates:
        if c and os.path.isfile(c):
            ver = _adb_version(c)
            if ver and ver < (33, 0):
                print(f"[phone] skipping old adb {'.'.join(map(str, ver))} at {c} (QR pairing needs 33+)")
                continue
            _state["adb"] = c
            print(f"[phone] using adb {'.'.join(map(str, ver)) if ver else '?'} at {c}")
            return c
    if download and os.name == "nt":
        return _download_platform_tools()
    return None


def _adb_version(exe: str):
    try:
        out = subprocess.run([exe, "version"], capture_output=True, text=True, timeout=8,
                             creationflags=_NO_WINDOW).stdout or ""
        m = re.search(r"Version (\d+)\.(\d+)", out)
        return (int(m.group(1)), int(m.group(2))) if m else None
    except Exception:
        return None


def restart_server():
    """Fixes a stuck adb (the usual cause of 'protocol fault' while pairing)."""
    adb(["kill-server"], serial=False, timeout=10)
    time.sleep(0.8)
    adb(["start-server"], serial=False, timeout=20)


def _download_platform_tools() -> str | None:
    """Fetches Google's official platform-tools (adb) into the app data folder."""
    import io
    import requests
    print("[phone] adb not found - downloading Google platform-tools...")
    try:
        r = requests.get(PLATFORM_TOOLS_URL, timeout=60)
        r.raise_for_status()
        zipfile.ZipFile(io.BytesIO(r.content)).extractall(config.DATA_DIR)
    except Exception as e:
        print(f"[phone] platform-tools download failed: {e}")
        return None
    path = os.path.join(config.DATA_DIR, "platform-tools", "adb.exe")
    if os.path.isfile(path):
        _state["adb"] = path
        return path
    return None


def adb(args: list[str], timeout: float = 15, serial: bool = True, binary: bool = False):
    exe = adb_path()
    if not exe:
        return subprocess.CompletedProcess(args, 127, stdout=b"" if binary else "",
                                           stderr="adb not found")
    cmd = [exe]
    if serial and _state["serial"]:
        cmd += ["-s", _state["serial"]]
    try:
        return subprocess.run(cmd + args, capture_output=True, text=not binary,
                              timeout=timeout, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, stdout=b"" if binary else "", stderr="timed out")


def shell(cmd: str, timeout: float = 15) -> str:
    return (adb(["shell", cmd], timeout=timeout).stdout or "").strip()


def connected_devices() -> list[str]:
    out = adb(["devices"], serial=False).stdout or ""
    return [ln.split()[0] for ln in out.splitlines()[1:]
            if len(ln.split()) > 1 and ln.split()[1] == "device"]


def is_connected() -> bool:
    devs = connected_devices()
    if not devs:
        _state["serial"] = None
        return False
    if _state["serial"] not in devs:
        # prefer the wireless connection we paired, else the first device
        wifi = [d for d in devs if ":" in d or "_adb-tls-connect" in d]
        _state["serial"] = (wifi or devs)[0]
        _state["screen"] = None
    return True


def ensure_connected() -> bool:
    if adb_path() is None:
        return False
    if is_connected():
        return True
    import phone_pair
    if phone_pair.quick_reconnect() or phone_pair.auto_reconnect(wait=2, deep=False):
        return is_connected()
    return False


NOT_CONNECTED = ("Your phone isn't connected. Say 'pair to phone' and scan the QR code, "
                 "or turn on Wireless debugging if you've paired before.")


# ---------------------------------------------------------------- full control
PHONE_RISKY = re.compile(
    r"\b(rm|rmdir|wipe|format|reboot|factory|uninstall|pm\s+(clear|disable|uninstall|hide)|"
    r"svc\s+power|dd|mkfs|setprop|settings\s+delete|am\s+force-stop\s+com\.android|input\s+(tap|swipe))\b", re.I)


def run_shell(command: str):
    """Run ANY adb shell command on the phone (am / pm / settings / input / cmd / dumpsys ...).
    Returns the output, or ('confirm', command) when it's destructive."""
    if not ensure_connected():
        return NOT_CONNECTED
    if PHONE_RISKY.search(command or ""):
        return ("confirm", command)
    return execute_shell(command)


def execute_shell(command: str) -> str:
    out = adb(["shell", command], timeout=25)
    txt = ((out.stdout or "") + (out.stderr or "")).strip()
    return txt[:1500] if txt else "Done."


def usb_device() -> str | None:
    """A phone plugged in with a cable (USB debugging on) - works on ANY network."""
    for d in connected_devices():
        if ":" not in d and "_adb-tls" not in d:
            return d
    return None


def wifi_blocks_pairing() -> str | None:
    """Windows: detects open / campus Wi-Fi, which almost always isolates devices."""
    try:
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True,
                             text=True, timeout=5, creationflags=_NO_WINDOW).stdout or ""
    except Exception:
        return None
    ssid = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.M)
    auth = re.search(r"^\s*Authentication\s*:\s*(.+)$", out, re.M)
    name = ssid.group(1).strip() if ssid else ""
    open_net = bool(auth and "open" in auth.group(1).lower())
    campus = bool(re.search(r"student|campus|guest|college|univ|hostel|public|free", name, re.I))
    return name if (open_net or campus) else None


# ---------------------------------------------------------------- screen helpers

def screen_size() -> tuple[int, int]:
    if _state["screen"]:
        return _state["screen"]
    m = re.search(r"(\d+)x(\d+)", shell("wm size"))
    size = (int(m.group(1)), int(m.group(2))) if m else (1080, 2400)
    _state["screen"] = size
    return size


def _ui_nodes() -> list[dict]:
    """Every element currently on screen with its text and tap position."""
    adb(["shell", "uiautomator", "dump", "/sdcard/hx_ui.xml"], timeout=10)
    raw = adb(["exec-out", "cat", "/sdcard/hx_ui.xml"], timeout=10).stdout or ""
    start = raw.find("<?xml")
    if start < 0:
        start = raw.find("<hierarchy")
    if start < 0:
        return []
    try:
        root = ET.fromstring(raw[start:])
    except ET.ParseError:
        return []
    nodes = []
    for n in root.iter("node"):
        label = (n.get("text") or "").strip() or (n.get("content-desc") or "").strip()
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", n.get("bounds") or "")
        if not label or not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        if x2 <= x1 or y2 <= y1:
            continue
        nodes.append({"label": label, "x": (x1 + x2) // 2, "y": (y1 + y2) // 2, "b": (x1, y1, x2, y2),
                      "clickable": n.get("clickable") == "true"})
    return nodes


def _best_node(nodes, target: str):
    q = target.lower().strip()
    best, best_score = None, 0
    for n in nodes:
        lab = n["label"].lower()
        if lab == q:
            score = 100
        elif lab.startswith(q):
            score = 80
        elif q in lab:
            score = 60 - min(30, len(lab) - len(q)) * 0.5
        elif all(w in lab for w in q.split()):
            score = 40
        else:
            continue
        score += 5 if n["clickable"] else 0
        if score > best_score:
            best, best_score = n, score
    return best


# ---------------------------------------------------------------- actions

def _need():
    return None if ensure_connected() else NOT_CONNECTED


def _packages() -> list[str]:
    if _state["packages"] and time.time() - _state["packages_at"] < 600:
        return _state["packages"]
    out = shell("pm list packages")
    pk = [ln.replace("package:", "").strip() for ln in out.splitlines() if ln.startswith("package:")]
    _state["packages"], _state["packages_at"] = pk, time.time()
    return pk


def open_app(name: str) -> str:
    if (err := _need()):
        return err
    key = name.lower().strip()
    if key in GENERIC_INTENTS:
        adb(["shell", "am", "start"] + GENERIC_INTENTS[key])
        return f"Opened {name} on your phone."
    pkg = APP_PACKAGES.get(key)
    if not pkg:
        q = re.sub(r"[^a-z0-9]", "", key)
        scored = []
        for p in _packages():
            last = p.split(".")[-1]
            flat = p.replace(".", "")
            if q == last:
                scored.append((100, p))
            elif q in last:
                scored.append((80 - len(last), p))
            elif q in flat:
                scored.append((50 - len(p) * 0.1, p))
        if scored:
            pkg = max(scored)[1]
    if not pkg:
        return f"I couldn't find an app called {name} on your phone."
    r = adb(["shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"])
    if "No activities found" in (r.stdout or "") + (r.stderr or ""):
        return f"{name} is installed but can't be opened directly."
    return f"Opened {name} on your phone."


# buttons that spend money - Hinata never taps these without your spoken "confirm"
PAY_RE = re.compile(r"(place\s*order|\bpay\b|proceed\s*to\s*pay|swipe\s*to\s*(pay|order)|"
                    r"confirm\s*(order|&\s*pay|and\s*pay|payment)|make\s*payment|buy\s*now|complete\s*(order|payment))",
                    re.I)


def order_total(nodes=None) -> str:
    """Best guess of the amount to pay, read off the screen."""
    nodes = nodes if nodes is not None else _ui_nodes()
    amounts = []
    for n in nodes:
        for m in re.finditer(r"(?:₹|rs\.?)\s*([\d,]+(?:\.\d\d)?)", n["label"], re.I):
            try:
                amounts.append(float(m.group(1).replace(",", "")))
            except ValueError:
                pass
    return f"₹{max(amounts):,.0f}" if amounts else ""


def _pay_check(node, nodes):
    if node and PAY_RE.search(node["label"]):
        return ("confirm_pay", (node["x"], node["y"], node["label"]), order_total(nodes))
    return None


def tap_text(target: str):
    if (err := _need()):
        return err
    nodes = _ui_nodes()
    node = _best_node(nodes, target)
    if not node:
        return f"I can't see '{target}' on your phone's screen."
    if (guard := _pay_check(node, nodes)):
        return guard
    adb(["shell", "input", "tap", str(node["x"]), str(node["y"])])
    return f"Tapped {node['label'][:40]}."


def pay_question(guard) -> str:
    _kind, (_x, _y, label), total = guard
    amt = f" The total looks like {total}." if total else ""
    return f"That's the '{label[:30]}' button - it spends money.{amt} Say confirm to pay, or cancel."


def tap_point(x: int, y: int) -> str:
    adb(["shell", "input", "tap", str(int(x)), str(int(y))])
    return "Tapped."


def after_payment(wait: float = 7) -> str:
    """Reads the screen after paying to tell you if the order went through."""
    time.sleep(wait)
    txt = " ".join(n["label"] for n in _ui_nodes()).lower()
    if re.search(r"order (placed|confirmed|received)|preparing|on (its|the) way|confirmed", txt):
        return "It's confirmed, Boss. Your order is placed."
    if re.search(r"upi|enter pin|mpin|gpay|phonepe|paytm", txt):
        return "The payment app is open - enter your UPI PIN on the phone to finish. I never touch PINs."
    return "I tapped pay. Check your phone to make sure the order went through."


def order_food(item: str, app: str = "swiggy", restaurant: str = "") -> str:
    """Opens Swiggy / Zomato and searches the dish - the AI then picks and adds it."""
    if (err := _need()):
        return err
    app = (app or "swiggy").lower().strip()
    if app not in ("swiggy", "zomato"):
        app = "swiggy"
    wake_unlock()
    res = open_app(app)
    if "couldn't" in res:
        return f"{app.title()} isn't installed on your phone."
    time.sleep(4)
    nodes = _ui_nodes()
    bar = _best_node(nodes, "search for") or _best_node(nodes, "search") or _best_node(nodes, "restaurant")
    if bar:
        adb(["shell", "input", "tap", str(bar["x"]), str(bar["y"])])
        time.sleep(1.2)
    type_text(f"{item} {restaurant}".strip())
    time.sleep(0.4)
    press_key("enter")
    time.sleep(3)
    return ("Searched " + app.title() + f" for {item}. " + read_screen() +
            " NEXT: tap a nearby, well-rated restaurant or dish (phone_tap), tap ADD, then View Cart, "
            "then tap the pay / place order button - the user will be asked to confirm the amount.")


def tap_xy(x: float, y: float) -> str:
    """x, y can be pixels or fractions of the screen (0-1)."""
    if (err := _need()):
        return err
    w, h = screen_size()
    px = int(x * w) if x <= 1 else int(x)
    py = int(y * h) if y <= 1 else int(y)
    nodes = _ui_nodes()
    hit = [n for n in nodes if n["b"][0] <= px <= n["b"][2] and n["b"][1] <= py <= n["b"][3]]
    hit.sort(key=lambda n: (n["b"][2] - n["b"][0]) * (n["b"][3] - n["b"][1]))   # smallest = the button
    if hit and (guard := _pay_check(hit[0], nodes)):
        return guard
    adb(["shell", "input", "tap", str(px), str(py)])
    return "Tapped."


def swipe(direction: str) -> str:
    if (err := _need()):
        return err
    w, h = screen_size()
    cx, cy = w // 2, h // 2
    d = direction.lower()
    # "scroll down" = content moves up = finger swipes up
    moves = {"up": (cx, int(h * .75), cx, int(h * .25)), "scroll down": (cx, int(h * .75), cx, int(h * .25)),
             "down": (cx, int(h * .25), cx, int(h * .75)), "scroll up": (cx, int(h * .25), cx, int(h * .75)),
             "left": (int(w * .85), cy, int(w * .15), cy), "right": (int(w * .15), cy, int(w * .85), cy)}
    m = moves.get(d) or moves.get(d.replace("swipe ", "")) or moves["up"]
    adb(["shell", "input", "swipe"] + [str(v) for v in m] + ["280"])
    return f"Swiped {direction}."


def _escape_input(text: str) -> str:
    out = []
    for ch in text:
        if ch == " ":
            out.append("%s")
        elif ch in "()<>|;&*\\~\"'`$?#![]{}":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def type_text(text: str) -> str:
    if (err := _need()):
        return err
    if not text.isascii():
        return "Your phone keyboard only accepts plain English letters through ADB."
    adb(["shell", "input", "text", _escape_input(text)])
    return "Typed it on your phone."


def press_key(name: str) -> str:
    if (err := _need()):
        return err
    code = KEYS.get(name.lower().strip())
    if code is None:
        return f"I don't know the phone key '{name}'."
    adb(["shell", "input", "keyevent", str(code)])
    return f"Pressed {name}."


def find_contact(name: str) -> tuple[str, str] | None:
    out = shell("content query --uri content://com.android.contacts/data/phones "
                "--projection display_name:data1", timeout=10)
    q = name.lower().strip()
    best = None
    for ln in out.splitlines():
        m = re.search(r"display_name=(.*?), data1=(.*)$", ln)
        if not m:
            continue
        disp, num = m.group(1).strip(), re.sub(r"[^\d+]", "", m.group(2))
        if disp.lower() == q:
            return disp, num
        if best is None and q in disp.lower():
            best = (disp, num)
    return best


def resolve_number(who: str) -> tuple[str, str] | None:
    digits = re.sub(r"[^0-9+]", "", who)
    if len(digits) >= 5:
        return who, digits
    return find_contact(who)


def dial(who: str) -> tuple[str, str | None]:
    """Opens the dialer pre-filled. Returns (reply, number or None)."""
    if (err := _need()):
        return err, None
    found = resolve_number(who)
    if not found:
        return f"I couldn't find {who} in your phone contacts.", None
    disp, number = found
    adb(["shell", "am", "start", "-a", "android.intent.action.DIAL", "-d", f"tel:{number}"])
    return f"Ready to call {disp}. Say confirm to call, or cancel.", number


def place_call(number: str) -> str:
    adb(["shell", "am", "start", "-a", "android.intent.action.CALL", "-d", f"tel:{number}"])
    return "Calling now."


def end_call() -> str:
    return press_key("end call")


def compose_sms(who: str, message: str) -> tuple[str, bool]:
    if (err := _need()):
        return err, False
    found = resolve_number(who)
    if not found:
        return f"I couldn't find {who} in your phone contacts.", False
    disp, number = found
    adb(["shell", "am", "start", "-a", "android.intent.action.SENDTO", "-d", f"smsto:{number}",
         "--es", "sms_body", message, "--ez", "exit_on_sent", "true"])
    return f"Message to {disp} is ready: {message}. Say confirm to send, or cancel.", True


def send_composed() -> str:
    time.sleep(0.4)
    node = _best_node(_ui_nodes(), "send")
    if node:
        adb(["shell", "input", "tap", str(node["x"]), str(node["y"])])
        return "Sent."
    return "The message is open - I couldn't find the send button, so tap it on your phone."


def open_url(url: str) -> str:
    if (err := _need()):
        return err
    if not url.startswith("http"):
        url = "https://" + url if "." in url and " " not in url else \
            f"https://google.com/search?q={url.replace(' ', '+')}"
    adb(["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url])
    return "Opened it on your phone."


def screenshot() -> str:
    if (err := _need()):
        return err
    data = adb(["exec-out", "screencap", "-p"], timeout=20, binary=True).stdout
    if not data:
        return "I couldn't capture your phone's screen."
    path = os.path.join(config.OUTPUT_DIR, f"phone_screenshot_{int(time.time())}.png")
    with open(path, "wb") as f:
        f.write(data)
    try:
        os.startfile(path)
    except Exception:
        pass
    return "Took a phone screenshot and opened it on your PC."


def read_screen() -> str:
    """Visible text on the phone - lets the AI 'see' what's on screen."""
    if (err := _need()):
        return err
    labels, seen = [], set()
    for n in _ui_nodes():
        if n["label"] not in seen:
            seen.add(n["label"])
            labels.append(n["label"])
    return ("On screen: " + "; ".join(labels[:60])) if labels else "The phone screen has no readable text."


def battery() -> str:
    if (err := _need()):
        return err
    out = shell("dumpsys battery")
    lvl = re.search(r"level: (\d+)", out)
    ac = re.search(r"(AC|USB|Wireless) powered: true", out)
    if not lvl:
        return "I couldn't read your phone's battery."
    return f"Your phone is at {lvl.group(1)} percent{', charging' if ac else ''}."


def toggle(feature: str, on: bool) -> str:
    if (err := _need()):
        return err
    f = feature.lower()
    state = "enable" if on else "disable"
    if "wifi" in f or "wi-fi" in f:
        shell(f"svc wifi {state}")
    elif "bluetooth" in f:
        r = shell(f"cmd bluetooth_manager {state}")
        if "Unknown" in r or "not found" in r.lower():
            shell(f"svc bluetooth {state}")
    elif "data" in f:
        shell(f"svc data {state}")
    elif "airplane" in f or "flight" in f:
        shell(f"cmd connectivity airplane-mode {state}")
    elif "rotation" in f:
        shell(f"settings put system accelerometer_rotation {1 if on else 0}")
    elif "torch" in f or "flash" in f:
        return "Android doesn't allow switching the torch from a PC - open quick settings instead."
    else:
        return f"I can't toggle {feature} on your phone."
    return f"Turned {'on' if on else 'off'} {feature} on your phone."


def set_brightness(percent: int) -> str:
    if (err := _need()):
        return err
    shell("settings put system screen_brightness_mode 0")
    shell(f"settings put system screen_brightness {max(1, min(255, int(percent * 2.55)))}")
    return f"Phone brightness set to {percent} percent."


def wake_unlock() -> str:
    if (err := _need()):
        return err
    press_key("wake")
    time.sleep(0.3)
    w, h = screen_size()
    adb(["shell", "input", "swipe", str(w // 2), str(int(h * .85)), str(w // 2), str(int(h * .3)), "250"])
    return "Woke your phone. If it has a PIN, enter it on the phone."


def notifications() -> str:
    if (err := _need()):
        return err
    shell("cmd statusbar expand-notifications")
    return "Opened your phone's notifications."


def mirror() -> str:
    if (err := _need()):
        return err
    exe = shutil.which(config.SCRCPY_PATH) or (config.SCRCPY_PATH if os.path.isfile(config.SCRCPY_PATH) else None)
    if not exe:
        return "Screen mirroring needs scrcpy. Install it with: winget install Genymobile.scrcpy"
    env = dict(os.environ)
    if adb_path():
        env["ADB"] = adb_path()
    subprocess.Popen([exe, "-s", _state["serial"], "--window-title", "Hinata - Phone",
                      "--stay-awake", "--max-fps", "60"], env=env, creationflags=_NO_WINDOW)
    return "Mirroring your phone on the PC. You can control it with your mouse."


def screen_record(seconds: int = 10) -> str:
    if (err := _need()):
        return err
    seconds = max(3, min(170, int(seconds)))
    remote = "/sdcard/hx_record.mp4"
    shell(f"screenrecord --time-limit {seconds} {remote}", timeout=seconds + 10)
    local = os.path.join(config.OUTPUT_DIR, f"phone_record_{int(time.time())}.mp4")
    adb(["pull", remote, local], timeout=60)
    return f"Recorded {seconds} seconds of your phone screen. It's in your Hinata Output folder."


# ---------------------------------------------------------------- fast regex path

def handle(text: str):
    """Quick phone commands. Returns a reply, a ('confirm', kind, payload, reply)
    tuple when confirmation is needed, or None if the AI should handle it."""
    o = text.strip().rstrip(".")
    t = o.lower()
    if not t:
        return "What should I do on your phone?"
    keep = lambda m, i: o[m.start(i):m.end(i)]   # noqa: E731  original-case slice

    if re.fullmatch(r"(show|mirror)( me)?( my)?( phone)?( screen)?|screen mirror|mirror", t):
        return mirror()
    if (m := re.fullmatch(r"open (?:the )?(.+?)(?: app)?", t)) and "." not in m.group(1):
        return open_app(m.group(1))
    if (m := re.fullmatch(r"(?:tap|click|press) (?:on )?(.+)", t)) and m.group(1) not in KEYS:
        r = tap_text(m.group(1))
        return ("confirm", "phone_pay", r[1], pay_question(r)) if isinstance(r, tuple) else r
    if (m := re.fullmatch(r"(?:type|write) (.+)", t)):
        return type_text(keep(m, 1))
    if (m := re.fullmatch(r"(?:swipe|scroll) (up|down|left|right)", t)):
        word = "scroll " + m.group(1) if t.startswith("scroll") else m.group(1)
        return swipe(word)
    if (m := re.fullmatch(r"call (.+)", t)):
        reply, number = dial(m.group(1))
        return ("confirm", "phone_call", number, reply) if number else reply
    if (m := re.fullmatch(r"(?:text|message|sms) (.+?) (?:saying|that) (.+)", t)) or \
            (m := re.fullmatch(r"(?:send )?(?:a )?(?:text|message) to (.+?) (?:saying|that) (.+)", t)):
        reply, ok = compose_sms(m.group(1), keep(m, 2))
        return ("confirm", "phone_sms", None, reply) if ok else reply
    if (m := re.fullmatch(r"(?:search|google)(?: for)? (.+)", t)):
        return open_url(m.group(1))
    if "screenshot" in t:
        return screenshot()
    if (m := re.search(r"record (?:the )?(?:screen|phone)(?: for (\d+) seconds?)?", t)):
        return screen_record(int(m.group(1) or 10))
    if "battery" in t:
        return battery()
    if re.search(r"read (?:my |the )?screen|what'?s on (?:my |the )?screen", t):
        return read_screen()
    if "notification" in t:
        return notifications()
    if re.fullmatch(r"(wake|unlock)( up)?( my)?( phone)?", t):
        return wake_unlock()
    if (m := re.fullmatch(r"(?:turn|switch) (on|off) (?:the )?(.+)", t)) or \
            (m := re.fullmatch(r"(?:turn|switch) (?:the )?(.+) (on|off)", t)):
        a, b = m.groups()
        on_off, feat = (a, b) if a in ("on", "off") else (b, a)
        return toggle(feat, on_off == "on")
    if (m := re.search(r"brightness (?:to )?(\d+)", t)):
        return set_brightness(int(m.group(1)))
    if re.fullmatch(r"(end|hang up|cut)( the)? call", t) or t == "hang up":
        return end_call()
    if t in ("lock", "lock it", "lock phone", "lock the phone", "screen off"):
        return press_key("power")
    for k in ("volume up", "volume down", "home", "back", "recents", "mute", "next", "previous"):
        if t in (k, f"go {k}", f"press {k}", f"{k} button"):
            return press_key(k)
    if t in ("pause", "play", "resume", "play pause"):
        return press_key("play pause")
    return None
