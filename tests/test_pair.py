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
