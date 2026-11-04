import sys, types, os, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["LOCALAPPDATA"] = __import__("tempfile").mkdtemp()
kb = types.ModuleType("keyboard"); kb.send=lambda k: None; kb.write=lambda t, delay=0: None; kb.add_hotkey=lambda *a,**k: None
sys.modules["keyboard"] = kb
import nlu, phone_control as phone, phone_pair

# ---------- agent loop with a scripted model
nlu.available = lambda force=False: True
nlu._state.update(model="fake", tools=None)
script = []
def fake_chat(msgs, tools=None, json_format=False, num_predict=None):
    return script.pop(0)
nlu._chat = fake_chat
done = []
ex = lambda n, a: (done.append((n, a)) or f"did {n}")

script[:] = [{"content": "", "tool_calls": [{"function": {"name": "open_target", "arguments": {"target": "notepad"}}}]}]
print("single:", nlu.run_agent("open notepad please", ex), done, "calls left", len(script))

done.clear()
script[:] = [{"content": "", "tool_calls": [{"function": {"name": "open_target", "arguments": {"target": "notepad"}}}]},
             {"content": "", "tool_calls": [{"function": {"name": "type_text", "arguments": {"text": "hello"}}}]},
             {"content": "Opened Notepad and typed hello."}]
print("multi:", nlu.run_agent("open notepad and type hello", ex), [d[0] for d in done])

done.clear()
script[:] = [{"content": '{"tool": "get_info", "args": {"kind": "time"}}'}, {"content": "It's late, go sleep!"}]
print("json-in-content:", nlu.run_agent("what time", ex), done)

script[:] = [{"content": "Tokyo is the capital of Japan."}]
print("chat:", nlu.run_agent("capital of japan?", ex))

# no-tools model -> JSON mode
calls = {"n": 0}
def chat2(msgs, tools=None, json_format=False, num_predict=None):
    calls["n"] += 1
    if tools: raise nlu._NoTools()
    return {"content": '{"tool": "search_web", "args": {"query": "cats"}}'} if calls["n"] == 2 else {"content": '{"reply": "done"}'}
nlu._chat = chat2; nlu._state["tools"] = None; done.clear()
print("json mode:", nlu.run_agent("search cats", ex), done, "tools flag", nlu._state["tools"])

# ---------- phone with fake adb
XML = '''UI hierchary dumped to: /sdcard/hx_ui.xml<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation="0">
<node text="" content-desc="Search" clickable="true" bounds="[900,100][1000,200]" />
<node text="Vishal Jaiswal" content-desc="" clickable="true" bounds="[0,300][1080,450]" />
<node text="Type a message" content-desc="" clickable="true" bounds="[100,2200][800,2300]" />
<node text="" content-desc="Send" clickable="true" bounds="[950,2200][1060,2300]" />
</hierarchy>'''
log = []
def fake_adb(args, timeout=15, serial=True, binary=False):
    log.append(args)
    out = ""
    if args[:1] == ["devices"]: out = "List of devices attached\n192.168.1.5:41234\tdevice\n"
    elif args[:2] == ["exec-out", "cat"]: out = XML
    elif args[:1] == ["shell"] and "wm size" in args[1:]: out = "Physical size: 1080x2400"
    elif args[:1] == ["shell"] and args[1].startswith("content query"): out = "Row: 0 display_name=Vishal Jaiswal, data1=+91 98765 43210\nRow: 1 display_name=Mom, data1=99999"
    elif args[:1] == ["shell"] and args[1] == "pm list packages": out = "package:com.whatsapp\npackage:com.spotify.music\npackage:com.zhiliaoapp.musically\npackage:in.swiggy.android"
    elif args[:1] == ["shell"] and args[1] == "dumpsys battery": out = "  AC powered: false\n  USB powered: true\n  level: 77\n"
    return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")
phone.adb = fake_adb
phone.adb_path = lambda download=False: "/fake/adb"

for cmd in ["open whatsapp", "open swiggy", "tap vishal", "tap send", "type Hello Bro!", "scroll down", "call vishal", "text mom saying I am coming", "battery", "read my screen", "turn on wifi", "home", "volume up", "screenshot ignored?"]:
    log.clear()
    r = phone.handle(cmd)
    last = [a for a in log if a[:1] in (["shell"], ["exec-out"]) and "uiautomator" not in a and "cat" not in a]
    print(f"{cmd!r:32} -> {r!r:95.95} | {last[-1] if last else ''}")
print("escape:", phone._escape_input("Hi bro, what's up? (ok)"))

# ---------- QR payload
img = phone_pair.make_qr("WIFI:T:ADB;S:HINATA-AB12CD;P:123456;;")
print("qr image", img.size, img.mode)
# ---------- mdns fallback parser
phone_pair_adb_out = "List of discovered mdns services\nHINATA-AB12CD\t_adb-tls-pairing._tcp\t192.168.1.5:37099\n"
import re
m = re.match(r"(\S+)\s+" + re.escape("_adb-tls-pairing._tcp") + r"\.?\s+([\d.]+):(\d+)", phone_pair_adb_out.splitlines()[1].strip())
print("mdns parse:", m.groups())
