import os, sys, types, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import phone_pair as pp, phone_control as pc, hotspot, config
config.PAIR_METHOD = "qr"      # these scenarios test the QR flow
pc.adb_path=lambda download=False: "adb"
import subprocess
calls=[]
def fake_adb(args, **k):
    calls.append(args)
    if args[:2]==["mdns","services"]:
        return subprocess.CompletedProcess(args,0,stdout=f"{fake_adb.name}\t_adb-tls-pairing._tcp\t192.168.137.50:41000\n",stderr="")
    if args[0]=="pair": return subprocess.CompletedProcess(args,0,stdout="Successfully paired",stderr="")
    if "get-state" in args: return subprocess.CompletedProcess(args,0,stdout="device",stderr="")
    return subprocess.CompletedProcess(args,0,stdout="",stderr="")
fake_adb.name="x"
pc.adb=fake_adb
pc.usb_device=lambda: None
pc.connected_devices=lambda: ["192.168.137.50:5555"]
pc.is_connected=lambda: True
pc.shell=lambda c,**k:"RMX-P4Pro"
pc._state["serial"]="192.168.137.50:5555"
pp._browse=lambda *a,**k: []
pp._save=lambda d: None
hotspot.current_wifi=lambda: ("SRU-Student","Open")
hotspot.start=lambda: {"ssid":"SHUBH-LAPTOP 4821","password":"pa55word"}
cnt=iter([0,0,1])
hotspot.client_count=lambda: next(cnt,1)
pp.time.sleep=lambda s: None
orig=pp._service_name
def sn(n):
    r=orig(n); fake_adb.name=r+"suffix"; print("service name:",r); return r
pp._service_name=sn
class Panel:
    def __init__(s,t): s.t=t; s.cancelled=threading.Event(); s.use_code=threading.Event()
    def status(s,x): print("  status:",x)
    def close(s): pass
class OV:
    def show_qr(self,title,img,steps,footer="",**k):
        print("PANEL:",title,"|",footer); [print("   ",x) for x in steps]; return Panel(title)
print(pp.pair_with_qr(OV()))
# non-isolated
hotspot.current_wifi=lambda: ("Shubh_Home_5G","WPA2-Personal")
print(pp.pair_with_qr(OV()))
print(hotspot.wifi_qr_payload("My;Net","p:a"))

# ---- mDNS blocked by the firewall (laptop hotspot): Hinata must find the phone by itself
print("\n--- mDNS blocked: direct scan ---")
hotspot.current_wifi = lambda: ("SRU-Student", "Open")
hotspot.client_ips = lambda: ["192.168.137.77"]
cnt2 = iter([1])
hotspot.client_count = lambda: next(cnt2, 1)
pp._browse = lambda *a, **k: []
scans = []
pp._open_ports = lambda ip, **k: scans.append(ip) or [37111, 41999]
def adb2(args, **k):
    if args[:2] == ["mdns", "services"]:
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
    if args[0] == "pair":
        ok = args[1].endswith(":41999")            # 41999 is the pairing port
        return subprocess.CompletedProcess(args, 0, stdout="Successfully paired" if ok else "", stderr="" if ok else "failed")
    if "get-state" in args:
        return subprocess.CompletedProcess(args, 0, stdout="device", stderr="")
    if args[0] == "connect":
        pc._state["serial"] = args[1]
        return subprocess.CompletedProcess(args, 0, stdout=f"connected to {args[1]}", stderr="")
    return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
pc.adb = adb2
clock = [1000.0]
def fake_time():
    clock[0] += 4
    return clock[0]
pp.time.time = fake_time
res = pp.pair_with_qr(OV())
print(res)
assert "Connected to" in res, res
assert scans and scans[0] == "192.168.137.77"
print("DIRECT PAIR OK")

# ---- 'protocol fault' on the first try: Hinata restarts adb and retries
print("\n--- protocol fault then success ---")
restarts = []
pc.restart_server = lambda: restarts.append(1)
attempts = []
def adb3(args, **k):
    if args[0] == "pair":
        attempts.append(args[1])
        ok = len(attempts) >= 2
        return subprocess.CompletedProcess(args, 0, stdout="Successfully paired" if ok else "",
                                           stderr="" if ok else "error: protocol fault (couldn't read status message): No error")
    return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
pc.adb = adb3
ok, msg = pp._pair("192.168.137.77", 41999, "123456")
print(ok, msg, "restarts:", len(restarts))
assert ok and len(restarts) == 1
print("RETRY OK")


# ---- pairing-code flow (the default): user types "port code", Hinata pairs and connects by itself
print("\n--- pairing code ---")
config.PAIR_METHOD = "code"
hotspot.current_wifi = lambda: ("SRU-Student", "Open")
hotspot.client_ips = lambda: ["192.168.137.223"]
hotspot.client_count = lambda: 1
pc.usb_device = lambda: None
state = {"paired": False}
def adb4(args, **k):
    if args[0] == "pair":
        state["paired"] = args[1] == "192.168.137.223:41234" and args[2] == "482913"
        return subprocess.CompletedProcess(args, 0, stdout="Successfully paired" if state["paired"] else "", stderr="")
    if "get-state" in args:
        return subprocess.CompletedProcess(args, 0, stdout="device" if state["paired"] else "offline", stderr="")
    if args[0] == "connect":
        return subprocess.CompletedProcess(args, 0, stdout=f"connected to {args[1]}", stderr="")
    return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
pc.adb = adb4
pp._open_ports = lambda ip, **k: [41234, 46888]
pc.connected_devices = lambda: [pc._state["serial"]] if pc._state["serial"] else []
pc.is_connected = lambda: bool(pc._state["serial"])
pc._state["serial"] = None
class OV2(OV):
    def ask_text(self, prompt, title=""):
        print("ASK:", prompt.splitlines()[0][:60]); return "41234 482913"
res = pp.pair_with_qr(OV2())
print(res)
assert "Connected to" in res and pc._state["serial"] == "192.168.137.223:46888", (res, pc._state["serial"])
print("CODE PAIR OK")

# ---- firewall cutting the connection -> clear help, no endless loop
def adb5(args, **k):
    if args[0] == "pair":
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="error: protocol fault (couldn't read status message): No error")
    return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
pc.adb = adb5
pc.restart_server = lambda: None
res = pp.pair_with_qr(OV2())
print(res[:90])
assert "firewall" in res.lower()
print("FIREWALL MESSAGE OK")
