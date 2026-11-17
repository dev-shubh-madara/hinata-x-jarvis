"""WhatsApp, website reverse engineering, founder tools and quick answers: routing and safety."""
import os, sys, types, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
kb = types.ModuleType("keyboard"); keys = []
kb.send = lambda k: keys.append(k); kb.write = lambda t, delay=0: None; kb.add_hotkey = lambda *a, **k: None
sys.modules["keyboard"] = kb
import commands as c, whatsapp, team, nlu, webre

fails = 0
def check(name, got, want=True):
    global fails
    ok = got == want
    fails += not ok
    print(("OK  " if ok else "FAIL") + f" {name:52} -> {got!r}")

c._hide_hologram = lambda: None
opened = []
whatsapp._open_chat = lambda number, message="": opened.append((number, message))
whatsapp.time.sleep = lambda s: None
# never drive the real WhatsApp app from a test: these checks cover the phone-number path
_real_send_by_name = whatsapp.send_by_name
whatsapp.send_by_name = lambda who, message, auto_send=True: None

# --- WhatsApp, confirm-first mode (WHATSAPP_AUTO_SEND = False): nothing goes out until "confirm"
import config
config.WHATSAPP_AUTO_SEND = False
check("save contact", c.handle("save contact Vishal 98765 43210"), "Saved Vishal.")
r = c.handle("WhatsApp Vishal saying I will reach by 5 PM")
check("chat opened with number + text", opened[-1], ("919876543210", "I will reach by 5 PM"))
check("asks before sending", "Say confirm to send" in r)
check("nothing sent yet", keys, [])
check("confirm sends", c.handle("confirm"), "Sent to Vishal.")
check("enter pressed once", keys, ["enter"])
c.handle("open whatsapp and send a message to vishal that the meeting is at 6")
check("second phrasing", opened[-1], ("919876543210", "The meeting is at 6"))
check("cancel", c.handle("cancel"), "Cancelled.")
check("no send after cancel", keys, ["enter"])
r = whatsapp.prepare("nobody", "hi")
check("unknown contact: explains, sends nothing", "couldn't open nobody's chat" in r.lower() and keys == ["enter"])

# --- WhatsApp, default auto-send mode: found contact -> sent straight away, no question
config.WHATSAPP_AUTO_SEND = True
r = c.handle("WhatsApp Vishal saying I am on my way")
check("auto-send: chat opened", opened[-1], ("919876543210", "I am on my way"))
check("auto-send: sent without asking", r, "Sent to Vishal.")
check("auto-send: enter pressed", keys, ["enter", "enter"])
check("auto-send: nothing left pending", c._pending, None)

# --- picking the chat by name in the app never guesses between two people
items = [("Rahul Sharma", 1), ("Rahul College", 2), ("Vishal", 3), ("Mom", 4)]
check("by name: exact match", whatsapp.pick_chat("vishal", items), ("Vishal", 3))
check("by name: full name", whatsapp.pick_chat("rahul sharma", items), ("Rahul Sharma", 1))
check("by name: two Rahuls -> ask", whatsapp.pick_chat("rahul", items)[0], "?")
check("by name: unknown -> None", whatsapp.pick_chat("ravi", items), None)
check("by name: no partial-word match", whatsapp.pick_chat("om", items), None)

# --- website reverse engineering
seen = []
c._website = lambda text, clone: seen.append((webre.normalise_url(text), clone)) or "ok"
c.handle("reverse engineer stripe dot com")
c.handle("clone the website https://example.com/pricing")
check("reverse engineer route", seen[0], ("https://stripe.com", False))
check("clone route", seen[1], ("https://example.com/pricing", True))

# --- founder tools
check("add task", c.handle("add task Call the printer by Friday").startswith("Added"))
c.handle("add task send the pitch deck")
check("list tasks", "Call the printer by Friday" in c.handle("what are my tasks"))
check("task done", c.handle("task 1 done").startswith("Done: Call the printer"))
check("one left", len(team.open_tasks()), 1)
check("note", c.handle("note that the investor wants a demo video"), "Noted.")
check("read notes", "investor wants a demo video" in c.handle("read my notes"))

# --- quick answers: questions skip the agent, actions don't
for t, want in [("what is the capital of japan", True), ("explain recursion in simple words", True),
                ("open chrome", False), ("what is my ip address", False), ("what is this error", False),
                ("how do i make a website", False), ("who invented the telephone", True)]:
    check(f"plain question: {t}", c._is_plain_question(t), want)
nlu.available = lambda force=False: True
nlu.quick_answer = lambda text: "Tokyo."
nlu.run_agent = lambda *a, **k: "AGENT"
check("question -> quick answer", c.handle("what is the capital of japan"), "Tokyo.")
check("question keeps hologram open", c.last_outcome(), "chat")

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
