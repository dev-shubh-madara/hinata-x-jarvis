import sys, types, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["LOCALAPPDATA"] = __import__("tempfile").mkdtemp()
kb = types.ModuleType("keyboard"); kb.send=lambda k: None; kb.write=lambda t, delay=0: None; kb.add_hotkey=lambda *a, **k: None
sys.modules["keyboard"] = kb
import config, pc_actions as pc, phone_control as phone, phone_pair, commands, nlu, session

# ---- stub side effects
for fn in ["open_target","close_app","play_media","search_web","type_text","take_screenshot","set_brightness","window","media_control","open_settings","write_document","make_presentation"]:
    setattr(pc, fn, lambda *a, _f=fn, **k: f"<{_f}>")
pc.volume = lambda *a, **k: "<volume>"
pc.do_system = lambda a: f"<do_system {a}>"
pc.get_info = lambda kind, city="": f"<info {kind}>"
pc.set_timer = lambda *a, **k: "<timer>"
phone_pair.pair_with_qr = lambda ov: "<QR shown>"
commands.web_answer.answer = lambda q: ""
commands.time.sleep = lambda s: None

class FakeOverlay:
    def __init__(self): self.log = []
    def collapse(self): self.log.append("collapse")
    def expand(self): self.log.append("expand")
    def set_state(self, s): pass
    def set_info(self, k, v): self.log.append(f"{k}={v}")
    def set_caption(self, **k): pass
ov = FakeOverlay(); commands.set_overlay(ov)

# AI brain: scripted. 'chat' replies without calling a tool; others call a tool via execute()
nlu.available = lambda force=False: True
def fake_agent(text, execute, should_stop=lambda: False, phone_hint=False):
    t = text.lower()
    if "make a ppt" in t:     return execute("make_presentation", {"topic": "x"})
    if "qr" in t or "pair" in t: return execute("pair_phone", {})
    if "weather" in t:        return execute("get_info", {"kind": "weather"})
    return "I'm doing great, thanks for asking!"        # pure chat - no tool
nlu.run_agent = fake_agent

def outcome(text):
    ov.log.clear()
    reply = commands.handle(text)
    return commands.last_outcome(), reply

cases = [
 ("how are you",                   "chat"),
 ("tell me a joke",                "chat"),
 ("what time is it",               "chat"),     # read-out only -> stays open
 ("what's the weather in delhi",   "chat"),
 ("open chrome",                   "action"),
 ("play believer",                 "action"),
 ("volume 40",                     "action"),
 ("make a ppt about space and add images", "action"),
 ("show me the phone qr",          "action"),
 ("pair to phone",                 "action"),
 ("on my phone open whatsapp",     "action"),
 ("search best laptops",           "action"),
]
bad = 0
for text, want in cases:
    got, reply = outcome(text)
    flag = "OK " if got == want else "BAD"
    bad += got != want
    print(f"{flag} {text!r:42} -> {got:7} | {str(reply)[:50]}")

# QR path hides the hologram first
ov.log.clear(); commands.handle("pair to phone"); print("pair_phone collapsed hologram first:", ov.log[:1] == ["collapse"])
ov.log.clear(); commands.handle("show me the phone qr"); print("AI pair_phone collapsed hologram first:", ov.log[:1] == ["collapse"])

# confirmation flow stays open, then closes once it is executed
got, r = outcome("shut down the pc");   print("shutdown ask ->", got, "|", r); assert got == "confirm"
got, r = outcome("yes do it");          print("confirm      ->", got, "|", r); assert got == "action"
outcome("restart my laptop")
got, r = outcome("cancel");             print("cancel       ->", got, "|", r); assert got == "chat"

# end phrases
for p, want in [("Okay Hinata, let's continue with our work", True), ("ok hinata lets continue with our work", True),
                ("that's all", True), ("bye Hinata", True), ("thanks hinata", True), ("let's get back to work", True),
                ("continue with our work", True),
                ("open chrome", False), ("close chrome", False), ("let's continue the story about dragons", False),
                ("what is work", False), ("how are you", False)]:
    got = commands.is_end_phrase(p)
    print(("OK " if got == want else "BAD"), f"end phrase {p!r:48} -> {got}"); bad += got != want

# ---------------------------------------------------------------- session loop (fake mic)
def run(script, typed=False, **kw):
    ov2 = FakeOverlay(); spoken = []; heard = list(script); t = [0.0]
    def listen(timeout): 
        t[0] += timeout if (heard and heard[0] is None) else 1.0
        return heard.pop(0) if heard else None
    def run_command(text):
        reply = commands.handle(text); out = commands.last_outcome()
        if out == "action": ov2.log.append("collapse")
        spoken.append(f"[{out}] {reply}"); return out
    why = session.run_session(overlay=ov2, typed=typed, listen=listen, ask_command=lambda: listen(1), run_command=run_command,
                              speak=lambda m: spoken.append("SAY: " + m), is_end=commands.is_end_phrase,
                              clock=lambda: t[0], **kw)
    return why, spoken, ov2.log

why, sp, log = run(["how are you", "tell me a joke", "okay Hinata, let's continue with our work"])
print("\nCHAT x2 then end phrase ->", why, "|", sp, "| collapsed early:", "collapse" in log); assert why == "ended" and "collapse" not in log

why, sp, log = run(["how are you", "open chrome"])
print("CHAT then work          ->", why, "|", sp, "| collapsed:", "collapse" in log); assert why == "action" and "collapse" in log

why, sp, log = run(["show me the phone qr"])
print("QR request              ->", why, "| collapsed:", "collapse" in log); assert why == "action"

why, sp, log = run(["shut down", "no wait cancel", "how are you", None, None, None, None], idle_seconds=20, follow_timeout=8)
print("confirm/cancel/chat/idle->", why, "|", sp)

why, sp, log = run([None]);   print("nothing heard first     ->", why, "|", sp); assert why == "nothing heard"
why, sp, log = run(["what time is it", "open notepad"]); print("read-out then work      ->", why); assert why == "action"
why, sp, log = run(["how are you", "open chrome"], conversation_mode=False)
print("conversation_mode=False ->", why, "(closes after the first reply)"); assert why == "action" and len(sp) == 1
why, sp, log = run(["how are you", "tell me more", None], typed=True)
print("typed chat then Esc     ->", why, "| expanded only after first text:", log[:3])
print("\nALL PASSED" if not bad else f"\n{bad} FAILED")
