"""Big brain, skills, desktop agent safety, motion studio, video edit plans and the new routes."""
import os, sys, types, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
for var in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY"):
    os.environ.pop(var, None)
kb = types.ModuleType("keyboard"); keys = []
kb.send = lambda k: keys.append(k); kb.write = lambda t, delay=0: keys.append("write:" + t)
kb.add_hotkey = lambda *a, **k: None; kb.on_press_key = lambda *a, **k: None
sys.modules["keyboard"] = kb
import config
config.OUTPUT_DIR = tempfile.mkdtemp()
import brain, skills, desk_agent, motion, video_edit, commands as c, nlu
import agent_cursor as ac

fails = 0
def check(name, got, want=True):
    global fails
    ok = got == want
    fails += not ok
    print(("OK  " if ok else "FAIL") + f" {name:52} -> {got!r}"[:160])

# --- brain
check("json: plain", brain.parse_json('{"a": 1}'), {"a": 1})
check("json: fenced", brain.parse_json('```json\n{"a": [1, 2]}\n```'), {"a": [1, 2]})
check("json: chatter around it", brain.parse_json('Sure! {"do": "done", "say": "ok"} hope it helps'), {"do": "done", "say": "ok"})
check("json: trailing comma", brain.parse_json('{"a": [1, 2,],}'), {"a": [1, 2]})
check("json: garbage", brain.parse_json("no json here"), None)
check("key: claude", brain.detect_provider("sk-ant-api03-xyz"), "claude")
check("key: gemini", brain.detect_provider("AIzaSyB123"), "gemini")
check("key: groq", brain.detect_provider("gsk_abc"), "groq")
check("key: junk refused", "doesn't look like" in brain.save_key("hello"))
check("no key -> local", brain.provider(), None)
brain.test = lambda p: True
check("key saved", "saved and working" in brain.save_key("gsk_test123"))
check("key not in project folder", os.path.dirname(brain._FILE).startswith(os.environ["LOCALAPPDATA"]))
check("provider now groq", brain.provider(), "groq")
config.CLOUD_AI = "off"
check("CLOUD_AI off wins", brain.provider(), None)
config.CLOUD_AI = "auto"
brain.remove_key()
check("key removed", brain.provider(), None)

# --- skills
check("built-in skills load", {"study notes", "code project", "start my day", "focus mode"} <= {s.name for s in skills.load()})
check("md skill match", skills.match("make notes on semiconductors").name, "study notes")
check("py skill match", skills.match("start focus mode for 40 minutes").name, "focus mode")
check("no skill for chit-chat", skills.match("how are you"), None)
user_skill = os.path.join(skills.USER_DIR, "greet-team.md")
with open(user_skill, "w", encoding="utf-8") as f:
    f.write("---\nname: greet team\ndescription: test\ntriggers: greet the team\n---\nSay hello.")
check("user skill picked up live", skills.match("please greet the team").name, "greet team")
check("user skill body", skills.match("greet the team").body, "Say hello.")

# --- desktop agent safety
check("risky: send not asked", desk_agent.is_risky("Send", "open the chat with rahul"), True)
check("risky: send asked", desk_agent.is_risky("Send", "send hi to rahul"), False)
check("risky: delete", desk_agent.is_risky("Delete account", "change my profile photo"), True)
check("safe button", desk_agent.is_risky("Save", "save the file"), False)
clicks = []
ac.click = lambda x, y, text=None, double=False, right=False: clicks.append((x, y))
ac.move = lambda x, y, text=None: None
ac.key = lambda k, show=None: keys.append(k)
ac.type_text = lambda t, show=None: keys.append("type:" + t)
ac.label = lambda t: None
elems = [{"type": "ButtonControl", "name": "Send", "value": "", "rect": (0, 0, 20, 20), "password": False},
         {"type": "EditControl", "name": "Password", "value": "", "rect": (0, 30, 100, 50), "password": True},
         {"type": "ButtonControl", "name": "Dark mode", "value": "", "rect": (10, 60, 30, 80), "password": False}]
line, fin, rep = desk_agent.act({"do": "click", "id": 1}, elems, "open rahul's chat")
check("risky click stops and asks", (fin, type(rep).__name__, clicks), (True, "Confirm", []))
line, fin, rep = desk_agent.act({"do": "type", "id": 2, "text": "secret"}, elems, "log in")
check("never types into password box", (fin, "type:secret" in keys), (True, False))
line, fin, rep = desk_agent.act({"do": "click", "id": 3}, elems, "turn on dark mode")
check("normal click happens", clicks, [(20, 70)])
line, fin, rep = desk_agent.act({"do": "click", "id": 9}, elems, "x")
check("bad id is reported, not clicked", (fin, len(clicks)), (False, 1))
line, fin, rep = desk_agent.act({"do": "key", "keys": "alt+f4"}, elems, "turn on dark mode")
check("alt+f4 blocked unless asked", "alt+f4" in keys, False)
check("done ends the loop", desk_agent.act({"do": "done", "say": "All set."}, elems, "x")[1:], (True, "All set."))

# --- motion
p = motion.validate({"title": "Test", "scenes": [
    {"type": "nonsense", "headline": "Hi", "duration": 99, "mascot": "dragon"},
    {"type": "big_number", "number": "Rs 4,00", "headline": "Money"},
    {"type": "phone", "messages": ["hey", "hi", {"from": "me", "text": "yo"}]},
    {"type": "list"}]})
check("unknown type -> title", p["scenes"][0]["type"], "title")
check("duration clamped", p["scenes"][0]["duration"], 15)
check("unknown mascot -> none", p["scenes"][0]["mascot"], "none")
check("number cleaned", p["scenes"][1]["number"], "400")
check("plain-string messages accepted", [m["from"] for m in p["scenes"][2]["messages"]], ["them", "me", "me"])
check("empty list gets items", len(p["scenes"][3]["items"]) >= 2)
check("colours are hex", all(v.startswith("#") and len(v) == 7 for k, v in p["style"].items() if k != "font"))
check("empty project still plays", len(motion.validate({})["scenes"]), 1)
check("size from words: youtube", motion._size_from("a youtube video about cats"), "wide")
check("size from words: reel", motion._size_from("make a reel about dosa"), "vertical")
fb = motion.validate(motion._fallback("make a motion video about my bakery"))
check("offline fallback storyboard", len(fb["scenes"]) >= 3 and fb["scenes"][-1]["type"] == "outro")

# --- video edit plans
check("edit: cut range", video_edit.plan("cut my last video from 0:10 to 0:45"), [{"op": "trim", "start": 10.0, "end": 45.0}])
check("edit: first seconds", video_edit.plan("remove the first 5 seconds of my video"), [{"op": "trim", "start": 5.0, "end": None}])
check("edit: reel + captions", [o["op"] for o in video_edit.plan("make my last video a reel with captions")], ["vertical", "captions"])
check("edit: speed", video_edit.plan("speed up my last video 2x"), [{"op": "speed", "factor": 2.0}])
check("edit: join", video_edit.plan("join my last 2 videos"), [{"op": "join", "count": 2}])
check("edit: whatsapp compress", video_edit.plan("compress this video for whatsapp"), [{"op": "compress"}])

# --- routing
called = []
motion.make_async = lambda brief, speak=None: called.append(("motion", brief)) or "motion started"
video_edit.edit = lambda text, speak=None: called.append(("edit", text)) or "edited"
desk_agent.run = lambda goal, history=None: called.append(("desk", goal)) or "desk done"
c._hide_hologram = lambda: None
import threading
_real_thread = threading.Thread
class _NowThread:
    def __init__(self, target=None, daemon=None, **k): self.t = target
    def start(self): self.t()
threading.Thread = _NowThread
check("route: motion video", c.handle("make a motion video about my startup Voderon"), "motion started")
check("route: motion brief kept", called[-1], ("motion", "make a motion video about my startup Voderon"))
c.handle("make my last video a reel with captions")
check("route: video edit (not motion)", called[-1], ("edit", "make my last video a reel with captions"))
c.handle("take over and turn on dark mode in settings")
check("route: desktop agent", called[-1], ("desk", "turn on dark mode in settings"))
c.handle("on my laptop, open notepad and write a poem")
check("route: 'on my laptop' agent", called[-1], ("desk", "open notepad and write a poem"))
check("route: skills list", c.handle("what are your skills").startswith("I have"))
threading.Thread = _real_thread

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
