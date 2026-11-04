import os, sys, types, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import phone_pair as pp, phone_control as pc, hotspot
pc.adb_path=lambda download=False: "adb"
import subprocess
calls=[]
def fake_adb(args, **k):
    calls.append(args)
    if args[:2]==["mdns","services"]:
        return subprocess.CompletedProcess(args,0,stdout=f"{fake_adb.name}\t_adb-tls-pairing._tcp\t192.168.137.50:41000\n",stderr="")
    if args[0]=="pair": return subprocess.CompletedProcess(args,0,stdout="Successfully paired",stderr="")
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
