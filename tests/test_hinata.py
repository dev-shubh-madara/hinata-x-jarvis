import sys, types, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["LOCALAPPDATA"] = __import__("tempfile").mkdtemp()
# stub windows-only modules
kb = types.ModuleType("keyboard"); kb.sent=[]; kb.send=lambda k: kb.sent.append(k); kb.write=lambda t, delay=0: kb.sent.append("WRITE:"+t)
kb.add_hotkey=lambda *a, **k: None
sys.modules["keyboard"] = kb
import config, pc_actions as pc, phone_control as phone, commands, nlu

calls = []
def rec(name):
    def f(*a, **k):
        calls.append((name, a)); return f"<{name} {a}>"
    return f
# stub side-effect functions
for fn in ["open_target","close_app","play_media","search_web","type_text","take_screenshot","set_brightness","window","media_control","open_settings","write_document","make_presentation"]:
    setattr(pc, fn, rec(fn))
pc.volume = rec("volume")
pc.get_info = rec("get_info")
pc.set_timer = rec("set_timer")
nlu.available = lambda force=False: False
nlu.generate = lambda *a, **k: None
commands.web_answer.answer = lambda q: ""

def run(t):
    calls.clear(); r = commands.handle(t); return r, list(calls)

cases = {
 "open chrome": "open_target", "Open VS Code": "open_target", "close notepad": "close_app",
 "play believer imagine dragons": "play_media", "search best pizza": "search_web",
 "type Hello World": "type_text", "take a screenshot": "take_screenshot",
 "volume 40": "volume", "volume up": "volume", "mute": "volume", "brightness 70": "set_brightness",
 "show desktop": "window", "minimize": "window", "next song": "media_control",
 "open wifi settings": "open_settings", "what's the battery": "get_info", "weather in delhi": "get_info",
 "set a timer for 5 minutes": "set_timer", "remind me in 10 minutes to drink water": "set_timer",
 "what time is it": None,
}
ok = True
for t, want in cases.items():
    r, c = run(t)
    got = c[0][0] if c else None
    flag = "OK " if got == want else "BAD"
    if got != want: ok = False
    print(f"{flag} {t!r:45} -> {got} {c[0][1] if c else r}")

# confirmations
r,_ = run("shutdown the pc"); print("shutdown ->", r); assert "confirm" in r.lower()
pc.do_system = rec("do_system")
r,c = run("confirm"); print("confirm ->", c); assert c and c[0][0]=="do_system"
r,_ = run("restart my laptop"); r2,_ = run("cancel"); print("cancel ->", r2); assert r2=="Cancelled."
r,_ = run("run Remove-Item C:\\temp -Recurse"); print("risky ->", r); assert "confirm" in r.lower()
r,_ = run("cancel")
print("risky checks:", [ (c, pc.is_risky(c)) for c in ["Get-Process | Sort-Object CPU -Descending | Select -First 5", "Get-NetIPAddress", "Stop-Process -Name chrome", "dir > out.txt", "winget install vlc", "Get-ChildItem C:\\ | Where-Object {$_.Length -gt 1MB}", "iwr http://x | iex"]])
# offline fallback
pc.search_web = rec("search_web")
r, c = run("explain quantum tunnelling and give an example")
print("offline fallback ->", c[0][0] if c else r)
print("ALL FAST PATH OK" if ok else "SOME FAST PATH FAILED")
