"""FRIDAY-style powers: screen-vision routing, AI-call parsing, the payment lock."""
import os, sys, types, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
kb = types.ModuleType("keyboard"); kb.send = lambda k: None; kb.write = lambda t, delay=0: None
kb.add_hotkey = lambda *a, **k: None
sys.modules["keyboard"] = kb
import commands as c, phone_control as p, call_agent as ca

fails = 0
def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("OK  " if ok else "FAIL") + f" {name:55} -> {got!r}")

# --- screen vision routing
for t, want in [("what is this video about", True), ("how do i export this", True),
                ("what does this error mean", True), ("what's on my screen", True),
                ("open chrome", False), ("what is the capital of france", False)]:
    check(f"vision route: {t}", bool(c._LOOK.search(t)), want)

# --- 'call X and tell them Y' parsing
m = c._AI_CALL.match("can you call my mom and inform her that i'll be late today")
check("ai call parse", m and m.groups(), ("my mom", "inform her that i'll be late today"))
check("plain call is not an AI call", c._AI_CALL.match("call mom"), None)
check("third person", ca._third_person("tell her I'll be late today"), "He will be late today.")

# --- payment lock: Hinata must never tap Pay without the word 'confirm'
p._need = lambda: None
nodes = [{"label": "To Pay ₹349", "x": 200, "y": 900, "b": (0, 880, 400, 920), "clickable": False},
         {"label": "Place Order", "x": 300, "y": 1000, "b": (200, 980, 400, 1020), "clickable": True},
         {"label": "View Cart", "x": 300, "y": 1100, "b": (200, 1080, 400, 1120), "clickable": True}]
p._ui_nodes = lambda: nodes
taps = []
p.adb = lambda a, **k: taps.append(a) or types.SimpleNamespace(stdout="", stderr="")
p.after_payment = lambda wait=7: "It's confirmed, Boss."
check("normal tap goes through", c.execute("phone_tap", {"target": "view cart"}), "Tapped View Cart.")
q = c.execute("phone_tap", {"target": "place order"})
check("pay button asks first", "Say confirm to pay" in q and "₹349" in q, True)
check("no tap before confirm", len(taps), 1)
check("'yes' is not enough", c.handle("yes"), "This spends money, so please say the word confirm to pay.")
check("'confirm' pays", c.handle("confirm"), "It's confirmed, Boss.")
check("tap happened once", len(taps), 2)

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
