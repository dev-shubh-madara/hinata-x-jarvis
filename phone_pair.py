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
    """adb connect - only True when the phone is really usable ('device', not offline/unauthorized)."""
    addr = f"{ip}:{port}"
    out = phone_control.adb(["connect", addr], serial=False, timeout=10)
    txt = ((out.stdout or "") + (out.stderr or "")).lower()
    if "connected to" not in txt:
        return False
    for _ in range(6):
        state = (phone_control.adb(["-s", addr, "get-state"], serial=False, timeout=5).stdout or "").strip()
        if state == "device":
            phone_control._state["serial"] = addr
            phone_control._state["screen"] = None
            return True
        time.sleep(0.5)
    phone_control.adb(["disconnect", addr], serial=False, timeout=5)
    print(f"[phone] {addr} connected but not usable ({state or 'no state'}) - phone not paired yet")
    return False


def quick_reconnect() -> bool:
    """Fast path (about 1 s): reconnect to the last phone address we used."""
    saved = _load()
    if saved.get("ip") and saved.get("port"):
        return _connect(saved["ip"], int(saved["port"]))
    return False


def auto_reconnect(wait: float = 5, deep: bool = True) -> bool:
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
    if not deep:
        return False                     # quick check only - the full scan runs on 'connect my phone'
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

FIREWALL_HELP = ("Your phone answered, but something on this laptop keeps cutting the secure pairing connection - "
                 "almost always the McAfee (or Windows) firewall on the hotspot network. Open McAfee > Firewall > "
                 "Internet connections for programs, add {adb} with Full access (or switch the firewall off for one "
                 "minute), then say 'pair to phone' again.")

STEPS = [
    "1. Phone and PC on the same Wi-Fi (college Wi-Fi? use PC Mobile hotspot)",
    "2. Settings > About phone > tap Build number 7x",
    "3. Settings > Developer options > Wireless debugging: ON",
    "4. Tap 'Pair device with QR code' and scan this",
]


def pair_with_qr(overlay) -> str:
    if overlay is None:
        return "I can't show the QR code right now - restart me and try again."
    method = str(getattr(config, "PAIR_METHOD", "link")).lower()
    if method == "link":
        import link
        if link.paired() and link.alive():
            return f"Your phone ({link.model()}) is already connected."
    elif phone_control.adb_path(download=True) is None:
        return ("I need Google's adb tool and couldn't download it. Install Android "
                "platform-tools and add it to PATH, then say 'pair to phone' again.")
    else:
        phone_control.restart_server()           # clean adb = no stale 'protocol fault'

    usb = phone_control.usb_device() if method != "link" else None
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

    if method == "link":
        return _pair_with_link(overlay, net_name, on_hotspot)
    if method != "qr":
        phone_ip = (hotspot.client_ips() or [""])[0] if on_hotspot else ""
        return _pair_with_code(overlay, phone_ip=phone_ip, net_name=net_name)

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
            if time.time() - started > 6 and last_scan == started:
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


LINK_STEPS = [
    "One-time setup on the phone:",
    "1. Install  Shizuku  (Play Store)  and  Termux  (F-Droid or GitHub)",
    "2. Shizuku: Start via Wireless debugging (it pairs the phone with itself)",
    "3. Shizuku > 'Use Shizuku in terminal apps' > Export files > Documents/sh",
    "4. Scan this QR with the camera, copy the text, paste it in Termux, press Enter",
    "5. Tap Allow when Termux / Shizuku ask - I connect by myself",
]


def _pair_with_link(overlay, net_name: str, on_hotspot: bool) -> str:
    """Hinata Link: the phone runs a small helper (Termux + Shizuku); no adb pairing at all."""
    import link
    key = link.new_key()
    cmd = link.setup_command(key)
    try:
        img = make_qr(cmd)
    except Exception as e:
        return f"I couldn't draw the QR code ({e}). Run: pip install qrcode"
    steps = LINK_STEPS + ([f"Phone must be on the Wi-Fi:  {net_name}"] if net_name else [])
    panel = overlay.show_qr("CONNECT YOUR PHONE", img, steps,
                            footer="Waiting for your phone...",
                            subtitle="Hinata Link - works without wireless-debugging pairing",
                            alt_label="Copy setup text")
    print("[link] waiting for the phone helper (setup QR shown)")
    try:
        deadline = time.time() + 900                      # first setup installs Python: give it time
        while time.time() < deadline and not panel.cancelled.is_set():
            if panel.use_code.is_set():
                panel.use_code.clear()
                try:
                    import pyperclip
                    pyperclip.copy(cmd)
                    panel.status("Copied - send it to your phone (WhatsApp / Phone Link) and paste in Termux")
                except Exception:
                    print(f"[link] setup command: {cmd}")
                    panel.status("Copy failed - the setup text is in hinata.log")
            if link.connect(key=key, quiet=True):
                panel.status(f"Connected to {link.model()}!")
                time.sleep(1.2)
                print(f"[link] connected to {link.model()} at {link._state['ip']}")
                return (f"Connected to {link.model()} through Hinata Link. Say 'on my phone' before any "
                        "command, like 'on my phone open WhatsApp'.")
            time.sleep(3)
        if panel.cancelled.is_set():
            return "Okay, cancelled phone setup."
        return ("Your phone didn't connect yet. Finish the steps on the phone, then say 'connect my phone'.")
    finally:
        panel.close()


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
             "2. Then I'll ask for the pairing code automatically"]
    panel = overlay.show_qr("STEP 1 - JOIN LAPTOP WI-FI", img, steps,
                            footer=f"Hotspot {hs['ssid']} is ON - waiting for your phone...",
                            subtitle="Connect your phone to the laptop's Wi-Fi", code_button=False)
    try:
        deadline = time.time() + PAIR_TIMEOUT
        while time.time() < deadline:
            if panel.cancelled.is_set():
                return "Okay, cancelled phone pairing."
            if panel.use_code.is_set() or hotspot.client_count() > 0:
                panel.status("Phone joined! Next: the pairing code...")
                time.sleep(1.2)
                return None
            time.sleep(1.5)
        return "Your phone didn't join the laptop's Wi-Fi in time. Say 'pair to phone' to try again."
    finally:
        panel.close()


def _parse_code_input(text: str, phone_ip: str):
    """Accepts '482913 41234', '192.168.137.5:41234 482913', '41234 482913'... -> (ip, port, code)."""
    t = text.strip()
    m = re.search(r"(\d+\.\d+\.\d+\.\d+)\s*:\s*(\d{2,5})", t)
    ip, port = (m.group(1), int(m.group(2))) if m else (phone_ip, 0)
    rest = t[:m.start()] + " " + t[m.end():] if m else t
    nums = re.findall(r"\d+", rest)
    code = next((n for n in nums if len(n) == 6), "")
    if not port:
        port = next((int(n) for n in nums if n != code and 1024 <= int(n) <= 65535 and len(n) <= 5), 0)
    return ip, port, code


def _clean_form(ip_text: str, port_text: str, code_text: str):
    """Forgiving: '192.168.137.5:41234' in the IP box, '482 913' as the code, extra spaces... all fine."""
    ip, port = "", 0
    m = re.search(r"(\d+\.\d+\.\d+\.\d+)(?:\s*:\s*(\d{2,5}))?", ip_text or "")
    if m:
        ip = m.group(1)
        port = int(m.group(2)) if m.group(2) else 0
    p = re.sub(r"\D", "", port_text or "")
    m2 = re.search(r":\s*(\d{2,5})", port_text or "")       # someone typed ip:port in the port box
    if m2:
        p = m2.group(1)
    if p and 1 <= int(p) <= 65535:
        port = int(p)
    code = re.sub(r"\D", "", code_text or "")
    return ip, port, code


def _pair_with_code(overlay, phone_ip: str = "", net_name: str = "") -> str:
    """Pairing with the 6-digit Wi-Fi pairing code (works even where QR discovery is blocked)."""
    where = f"  (phone on Wi-Fi '{net_name}')" if net_name else ""
    prompt = ("On your phone" + where + ":\nDeveloper options > Wireless debugging > "
              "'Pair device with pairing code'.\n\nCopy the numbers from that popup into the boxes below.")
    ip = port = code = None
    for attempt in range(3):
        vals = overlay.ask_fields(prompt, [
            ("IP address", ip or phone_ip, ""),
            ("Port", str(port) if port else "", "the number after ':'"),
            ("Pairing code", "", "6 digits")], title="Pair with code")
        if not vals:
            return "Okay, cancelled phone pairing."
        ip, port, code = _clean_form(*vals)
        missing = [n for n, ok in (("IP address", ip), ("port", port), ("6-digit pairing code", len(code) == 6))
                   if not ok]
        print(f"[pair] form -> ip={ip or '?'} port={port or '?'} code={'ok' if len(code) == 6 else len(code)}")
        if not missing:
            break
        prompt = ("Missing or wrong: " + ", ".join(missing) + ".\n\nOn the phone's 'Pair with pairing code' "
                  "popup: the top line is IP address:PORT (e.g. 192.168.137.223:41234) and the big "
                  "number is the 6-digit code.")
    else:
        return "I still need the IP, port and 6-digit code. Say 'pair to phone' to try again."
    print(f"[pair] pairing code -> {ip}:{port}")
    ok, msg = _pair(ip, port, code, tries=2)
    if not ok:
        if "protocol fault" in msg.lower() or "connection" in msg.lower() and "refused" not in msg.lower():
            return FIREWALL_HELP.format(adb=phone_control.adb_path() or "adb.exe")
        return (f"Pairing failed: {msg[:120]}. The code and port change every time you open that screen - "
                "say 'pair to phone' and type the new ones.")

    # paired! now open the actual connection (different port - shown at the top of Wireless debugging)
    time.sleep(1.5)
    for p in _open_ports(ip):
        if p != port and _connect(ip, p):
            break
    if not phone_control.is_connected():
        conn = overlay.ask_text("Paired! Last step: type the IP address & port shown at the TOP of the "
                                "Wireless debugging screen (e.g. 192.168.137.5:39857):", title="Pair with code")
        c_ip, c_port, _ = _parse_code_input(conn or "", ip)
        if not (c_port and _connect(c_ip or ip, c_port)):
            return "Paired, but not connected yet. Say 'connect my phone' in a moment."
    model = phone_control.shell("getprop ro.product.model") or "your phone"
    serial = phone_control._state["serial"] or ""
    _save({"ip": ip, "port": int(serial.split(":")[-1]) if ":" in serial else 0,
           "model": model, "paired_at": int(time.time())})
    return (f"Connected to {model}. Say 'on my phone' before any command, like "
            f"'on my phone open WhatsApp'.")


def connect_existing() -> str:
    import link
    if link.paired():
        if link.alive() or link.connect():
            return f"Connected to {link.model()}."
        return ("I can't reach your phone. On the phone: be on the same Wi-Fi as the laptop (or its hotspot), "
                "open Shizuku and press Start if needed, then open Termux. Then say 'connect my phone'.")
    if phone_control.adb_path() is None:
        return "Pair first - say 'pair to phone'."
    if phone_control.is_connected() or auto_reconnect(wait=6):
        model = phone_control.shell("getprop ro.product.model") or "your phone"
        return f"Connected to {model}."
    return ("I couldn't find your phone. Turn on Wireless debugging and make sure it's on "
            "the same Wi-Fi - or say 'pair to phone' to pair again.")
