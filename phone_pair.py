"""
"Pair to phone" - QR code pairing, the same method Android Studio uses.

How it works:
  1. Hinata shows a QR code that encodes a one-time pairing name + password
     (format WIFI:T:ADB;S:<name>;P:<password>;;).
  2. On the phone: Settings > Developer options > Wireless debugging >
     "Pair device with QR code", then scan it.
  3. The phone announces itself on your Wi-Fi (mDNS service
     _adb-tls-pairing._tcp). Hinata finds it, runs `adb pair`, then
     connects via the phone's _adb-tls-connect._tcp service.
  4. Done - the phone trusts this PC from now on. Next time, Hinata
     reconnects automatically whenever Wireless debugging is on.

Requirements: Android 11+, phone and PC on the same Wi-Fi, Developer options
enabled (tap Build number 7 times). adb is downloaded automatically if missing.
"""

import json
import os
import re
import secrets
import socket
import string
import threading
import time

import config
import hotspot
import phone_control

PAIR_TYPE = "_adb-tls-pairing._tcp.local."
CONNECT_TYPE = "_adb-tls-connect._tcp.local."
PAIR_TIMEOUT = 180
os.environ.setdefault("ADB_MDNS_OPENSCREEN", "1")     # adb's own built-in mDNS (works on more PCs)
_PHONE_FILE = os.path.join(config.DATA_DIR, "phone.json")


# ---------------------------------------------------------------- discovery

def _browse(service_type: str, wait: float, want=None) -> list[tuple[str, str, int]]:
    """Returns [(instance name, ip, port)] for mDNS services of service_type.
    Stops early once want(name) matches. Uses python-zeroconf, falling back
    to `adb mdns services`."""
    found: dict[str, tuple[str, str, int]] = {}
    done = threading.Event()
    try:
        from zeroconf import ServiceBrowser, Zeroconf

        zc = Zeroconf()

        class Listener:
            def _add(self, zc_, type_, name):
                info = zc_.get_service_info(type_, name, timeout=2000)
                if not info:
                    return
                addrs = [a for a in info.parsed_addresses() if ":" not in a] or info.parsed_addresses()
                if not addrs:
                    return
                inst = name.replace("." + type_, "")
                found[inst] = (inst, addrs[0], info.port)
                if want and want(inst):
                    done.set()

            def add_service(self, zc_, type_, name):
                self._add(zc_, type_, name)

            def update_service(self, zc_, type_, name):
                self._add(zc_, type_, name)

            def remove_service(self, zc_, type_, name):
                found.pop(name.replace("." + type_, ""), None)

        browser = ServiceBrowser(zc, service_type, Listener())
        done.wait(wait)
        browser.cancel()
        zc.close()
    except Exception as e:
        print(f"[pair] zeroconf unavailable ({e}) - using adb mdns.")
        end = time.time() + wait
        short = service_type.replace(".local.", "")
        while time.time() < end:
            out = phone_control.adb(["mdns", "services"], serial=False, timeout=5).stdout or ""
            for ln in out.splitlines():
                m = re.match(r"(\S+)\s+" + re.escape(short) + r"\.?\s+([\d.]+):(\d+)", ln.strip())
                if m:
                    found[m.group(1)] = (m.group(1), m.group(2), int(m.group(3)))
            if want and any(want(k) for k in found):
                break
            time.sleep(1)
    return list(found.values())


# ---------------------------------------------------------------- saved phone

def _save(info: dict):
    try:
        with open(_PHONE_FILE, "w", encoding="utf-8") as f:
            json.dump(info, f)
    except OSError:
        pass


def _load() -> dict:
    try:
        with open(_PHONE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _connect(ip: str, port: int) -> bool:
    out = phone_control.adb(["connect", f"{ip}:{port}"], serial=False, timeout=10)
    txt = (out.stdout or "") + (out.stderr or "")
    ok = "connected to" in txt.lower()
    if ok:
        phone_control._state["serial"] = f"{ip}:{port}"
        phone_control._state["screen"] = None
    return ok


def auto_reconnect(wait: float = 5) -> bool:
    """Reconnects a previously paired phone (Wireless debugging must be on)."""
    if phone_control.adb_path() is None:
        return False
    if phone_control.connected_devices():
        return phone_control.is_connected()
    saved = _load()
    services = _browse(CONNECT_TYPE, wait,
                       want=(lambda n: True) if not saved.get("ip") else None)
    services.sort(key=lambda s: s[1] != saved.get("ip"))   # last phone's IP first
    for _name, ip, port in services:
        if _connect(ip, port):
            saved.update(ip=ip, port=port)
            _save(saved)
            print(f"[phone] reconnected to {ip}:{port}")
            return True
    # mDNS blocked (firewall / hotspot): try the saved IP and nearby devices directly
    ips = [saved["ip"]] if saved.get("ip") else []
    ips += [ip for ip in _candidate_ips(bool(hotspot.client_ips())) if ip not in ips]
    for ip in ips[:6]:
        if saved.get("port") and _connect(ip, int(saved["port"])):
            return True
        for port in _open_ports(ip):
            if _connect(ip, port):
                saved.update(ip=ip, port=port)
                _save(saved)
                print(f"[phone] reconnected to {ip}:{port} (direct)")
                return True
    return False


def auto_reconnect_background():
    if config.PHONE_AUTO_RECONNECT and _load():
        threading.Thread(target=auto_reconnect, kwargs={"wait": 6},
                         daemon=True, name="phone-reconnect").start()


# ---------------------------------------------------------------- QR

def make_qr(payload: str):
    import qrcode
    qr = qrcode.QRCode(border=2, box_size=12, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1a1033", back_color="#ffffff")
    img = img.get_image() if hasattr(img, "get_image") else getattr(img, "_img", img)
    return img.convert("RGB")


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "?"


ISOLATED_HELP = ("Your Wi-Fi '{ssid}' blocks devices from talking to each other (college/open Wi-Fi does this), "
                 "so wireless pairing can't work on it. Fix: on the PC open Settings > Network > Mobile hotspot, "
                 "turn it ON, connect your PHONE to that hotspot, then say 'pair to phone' again. "
                 "Or plug the phone in with a USB cable (USB debugging on) - that works on any network.")

STEPS = [
    "1. Phone and PC on the same Wi-Fi (college Wi-Fi? use PC Mobile hotspot)",
    "2. Settings > About phone > tap Build number 7x",
    "3. Settings > Developer options > Wireless debugging: ON",
    "4. Tap 'Pair device with QR code' and scan this",
]


def pair_with_qr(overlay) -> str:
    if overlay is None:
        return "I can't show the QR code right now - restart me and try again."
    if phone_control.adb_path(download=True) is None:
        return ("I need Google's adb tool and couldn't download it. Install Android "
                "platform-tools and add it to PATH, then say 'pair to phone' again.")
    phone_control.restart_server()               # clean adb = no stale 'protocol fault'

    usb = phone_control.usb_device()
    if usb:                                     # cable plugged in - no QR needed
        phone_control._state["serial"] = usb
        phone_control._state["screen"] = None
        model = phone_control.shell("getprop ro.product.model") or "your phone"
        return f"Connected to {model} over USB. Say 'on my phone' before any command."

    # 1) which Wi-Fi is the laptop on right now?
    ssid, auth = hotspot.current_wifi()
    print(f"[phone] laptop Wi-Fi: {ssid or 'none'} ({auth or '?'})")
    net_name = ssid
    on_hotspot = False
    if hotspot.is_isolated(ssid, auth) or not ssid:
        # college / open Wi-Fi blocks phone<->laptop traffic: make the laptop the Wi-Fi
        why = (f"'{ssid}' blocks devices from seeing each other" if ssid else "the laptop isn't on Wi-Fi")
        print(f"[phone] {why} - starting the laptop's Mobile hotspot")
        hs = hotspot.start()
        if "error" in hs:
            print(f"[phone] hotspot failed: {hs['error']}")
            return ISOLATED_HELP.format(ssid=ssid or "this network")
        net_name = hs["ssid"]
        on_hotspot = True
        joined = _join_hotspot(overlay, hs, why)
        if joined is not None:
            return joined
    blocked = None

    name = _service_name(net_name)
    password = "".join(secrets.choice(string.digits) for _ in range(6))
    try:
        img = make_qr(f"WIFI:T:ADB;S:{name};P:{password};;")
    except Exception as e:
        return f"I couldn't draw the QR code ({e}). Run: pip install qrcode"

    steps = [f"1. Phone must be on the Wi-Fi:  {net_name}"] + STEPS[1:]
    panel = overlay.show_qr("PAIR YOUR PHONE", img, steps,
                            footer=f"Laptop Wi-Fi: {net_name}  -  waiting for your phone...")
    try:
        deadline = time.time() + PAIR_TIMEOUT
        target = None
        started = last_scan = time.time()
        paired_direct = None
        while time.time() < deadline and not panel.cancelled.is_set():
            if panel.use_code.is_set():
                panel.close()
                return _pair_with_code(overlay)
            hits = _browse(PAIR_TYPE, 3, want=lambda n: n.startswith(name))
            target = next((h for h in hits if h[0].startswith(name)), None)
            if not target:                       # firewall can hide mDNS from Python - ask adb too
                out = phone_control.adb(["mdns", "services"], serial=False, timeout=5).stdout or ""
                for ln in out.splitlines():
                    m = re.match(r"(\S+)\s+_adb-tls-pairing\._tcp\.?\s+([\d.]+):(\d+)", ln.strip())
                    if m and m.group(1).startswith(name):
                        target = (m.group(1), m.group(2), int(m.group(3)))
            if target:
                break
            # Windows Firewall often blocks the phone's mDNS announcement (always on the hotspot).
            # Plan B: find the phone ourselves and knock on its ports until the pairing one answers.
            if time.time() - started > 6 and time.time() - last_scan > 8:
                last_scan = time.time()
                panel.status("Looking for your phone directly...")
                done = _scan_and_pair(on_hotspot, password, panel)
                if done:
                    paired_direct = done
                    break
                panel.status(f"Laptop Wi-Fi: {net_name}  -  waiting for your phone...")
        if panel.cancelled.is_set():
            return "Okay, cancelled phone pairing."
        if paired_direct:
            ip, ports = paired_direct
            return _finish_direct(ip, ports, panel)
        if not target and blocked:
            return ISOLATED_HELP.format(ssid=blocked)
        if not target:
            return ("I didn't see your phone. Check that both are on the same Wi-Fi "
                    "and you scanned from Wireless debugging, not the camera app.")

        _, ip, port = target
        panel.status(f"Phone found at {ip} - pairing...")
        ok, msg = _pair(ip, port, password)
        if not ok:
            panel.status("Trying another way...")
            done = _scan_and_pair(on_hotspot, password, panel, only_ip=ip)
            if done:
                return _finish_direct(done[0], done[1], panel)
            print(f"[pair] QR pairing failed ({msg}) - switching to pairing code")
            panel.close()
            return ("QR pairing didn't go through (" + msg[:80] + "). " + _pair_with_code(overlay))

        panel.status("Paired! Connecting...")
        connected = False
        for _ in range(4):
            if phone_control.connected_devices():
                connected = phone_control.is_connected()
                break
            services = _browse(CONNECT_TYPE, 4, want=lambda n: True)
            services.sort(key=lambda s: s[1] != ip)
            for _n, cip, cport in services:
                if cip == ip and _connect(cip, cport):
                    connected = True
                    break
            if connected:
                break
        if not connected and blocked:
            return ISOLATED_HELP.format(ssid=blocked)
        if not connected:
            return ("Paired, but I couldn't open the connection yet. Keep Wireless debugging on "
                    "and say 'connect my phone' in a moment.")

        model = phone_control.shell("getprop ro.product.model") or "your phone"
        _save({"ip": ip, "port": int(phone_control._state["serial"].split(":")[-1])
               if ":" in (phone_control._state["serial"] or "") else 0,
               "model": model, "paired_at": int(time.time())})
        panel.status(f"Connected to {model}")
        time.sleep(1.2)
        return (f"Connected to {model}. Say 'on my phone' before any command, like "
                f"'on my phone open WhatsApp' or 'call Vishal on my phone'.")
    finally:
        panel.close()


def _pair(ip: str, port: int, password: str, tries: int = 3) -> tuple[bool, str]:
    """adb pair with retries. 'protocol fault' is usually a stuck adb server - restart it and retry."""
    msg = ""
    for i in range(tries):
        res = phone_control.adb(["pair", f"{ip}:{port}", password], serial=False, timeout=15)
        out = ((res.stdout or "") + (res.stderr or "")).strip()
        if "success" in out.lower():
            return True, out
        msg = out or "no answer"
        print(f"[pair] attempt {i + 1} at {ip}:{port} failed: {msg}")
        if "wrong password" in msg.lower():
            break
        if i < tries - 1:
            phone_control.restart_server()
            time.sleep(1.0)
    return False, msg


def _candidate_ips(on_hotspot: bool) -> list[str]:
    if on_hotspot:
        return hotspot.client_ips()[:6]
    me = _local_ip()
    if me.count(".") != 3:
        return []
    near = hotspot.arp_neighbors(me.rsplit(".", 1)[0] + ".")
    gateway_like = {me.rsplit(".", 1)[0] + "." + x for x in ("1", "254")}
    return [ip for ip in near if ip not in gateway_like and ip != me][:8]


def _open_ports(ip: str, lo: int = 30000, hi: int = 65535, timeout: float = 0.6) -> list[int]:
    """TCP ports open on the phone (wireless debugging uses random high ports)."""
    import asyncio

    async def probe(port, sem):
        async with sem:
            try:
                _r, w = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
                w.close()
                return port
            except Exception:
                return None

    async def run():
        sem = asyncio.Semaphore(1200)
        found = await asyncio.gather(*(probe(p, sem) for p in range(lo, hi + 1)))
        return [p for p in found if p]
    try:
        return asyncio.run(run())
    except Exception as e:
        print(f"[pair] port scan failed: {e}")
        return []


def _scan_and_pair(on_hotspot: bool, password: str, panel, only_ip: str = ""):
    """Pairs without mDNS. Returns (ip, open_ports) on success, else None."""
    for ip in ([only_ip] if only_ip else _candidate_ips(on_hotspot)):
        t0 = time.time()
        ports = _open_ports(ip)
        print(f"[pair] {ip}: open ports {ports[:10]} ({time.time() - t0:.1f}s)")
        for port in ports:
            panel.status(f"Phone found at {ip} - pairing...")
            ok, _msg = _pair(ip, port, password, tries=2)
            if ok:
                print(f"[pair] paired directly with {ip}:{port}")
                return ip, [p for p in ports if p != port]
    return None


def _finish_direct(ip: str, ports: list[int], panel) -> str:
    panel.status("Paired! Connecting...")
    time.sleep(1.5)
    tries = ports or []
    if not any(_connect(ip, p) for p in tries):
        for p in _open_ports(ip):                     # the connect port can change after pairing
            if _connect(ip, p):
                break
    if not phone_control.is_connected():
        return ("Paired! Now say 'connect my phone' - or check that Wireless debugging is still on.")
    model = phone_control.shell("getprop ro.product.model") or "your phone"
    serial = phone_control._state["serial"] or ""
    _save({"ip": ip, "port": int(serial.split(":")[-1]) if ":" in serial else 0,
           "model": model, "paired_at": int(time.time())})
    panel.status(f"Connected to {model}")
    time.sleep(1.2)
    return (f"Connected to {model}. Say 'on my phone' before any command, like "
            f"'on my phone open WhatsApp' or 'call Vishal on my phone'.")


def _service_name(net: str) -> str:
    """Pairing name shown on the phone = the laptop's current Wi-Fi name + a short code."""
    base = re.sub(r"[^A-Za-z0-9]+", "-", net or "HINATA").strip("-")[:24] or "HINATA"
    return f"{base}-HX" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))


def _join_hotspot(overlay, hs: dict, why: str):
    """Shows a normal Wi-Fi QR so the phone joins the laptop's hotspot. None = joined."""
    try:
        img = make_qr(hotspot.wifi_qr_payload(hs["ssid"], hs["password"]))
    except Exception as e:
        return f"I couldn't draw the QR code ({e}). Run: pip install qrcode"
    steps = [f"Your Wi-Fi: {why}, so I turned on the laptop's own Wi-Fi.",
             "1. Open your phone CAMERA and scan this QR - join the Wi-Fi",
             f"   (or join manually:  {hs['ssid']}   password  {hs['password']})",
             "2. Then I'll show the pairing QR automatically"]
    panel = overlay.show_qr("STEP 1 - JOIN LAPTOP WI-FI", img, steps,
                            footer=f"Hotspot {hs['ssid']} is ON - waiting for your phone...",
                            subtitle="Connect your phone to the laptop's Wi-Fi", code_button=False)
    try:
        deadline = time.time() + PAIR_TIMEOUT
        while time.time() < deadline:
            if panel.cancelled.is_set():
                return "Okay, cancelled phone pairing."
            if panel.use_code.is_set() or hotspot.client_count() > 0:
                panel.status("Phone joined! Opening the pairing QR...")
                time.sleep(1.2)
                return None
            time.sleep(1.5)
        return "Your phone didn't join the laptop's Wi-Fi in time. Say 'pair to phone' to try again."
    finally:
        panel.close()


def _pair_with_code(overlay) -> str:
    """Fallback when QR/mDNS is blocked: the classic pairing-code flow."""
    addr = overlay.ask_text("On your phone: Wireless debugging > 'Pair device with pairing code'.\n"
                            "Enter the IP address & port shown there (e.g. 192.168.1.42:37251):",
                            title="Pair with code")
    if not addr or ":" not in addr:
        return "Okay, cancelled phone pairing."
    code = overlay.ask_text("Enter the 6-digit Wi-Fi pairing code:", title="Pair with code")
    if not code:
        return "Okay, cancelled phone pairing."
    ip, _, port = addr.strip().rpartition(":")
    ok, msg = _pair(ip.strip(), int(port) if port.isdigit() else 0, re.sub(r"\D", "", code))
    if not ok:
        return (f"Pairing failed: {msg[:120]}. Check the code (it changes each time) and that McAfee or "
                "Windows Firewall isn't blocking adb.exe.")
    ip = ip.strip()
    if auto_reconnect(wait=6) or phone_control.is_connected():
        _save({"ip": ip, "paired_at": int(time.time())})
        return "Your phone is paired and connected."
    conn = overlay.ask_text("Paired! Now enter the IP address & port at the TOP of the "
                            "Wireless debugging screen:", title="Pair with code")
    if conn and ":" in conn and _connect(*conn.strip().rsplit(":", 1)):
        _save({"ip": ip, "paired_at": int(time.time())})
        return "Your phone is paired and connected."
    return "Paired, but not connected yet. Say 'connect my phone' to retry."


def connect_existing() -> str:
    if phone_control.adb_path() is None:
        return "Pair first - say 'pair to phone'."
    if phone_control.is_connected() or auto_reconnect(wait=6):
        model = phone_control.shell("getprop ro.product.model") or "your phone"
        return f"Connected to {model}."
    return ("I couldn't find your phone. Turn on Wireless debugging and make sure it's on "
            "the same Wi-Fi - or say 'pair to phone' to pair again.")
