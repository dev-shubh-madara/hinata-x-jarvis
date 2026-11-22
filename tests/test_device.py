"""Laptop by default; the phone only after 'operate my mobile' (or 'on my phone ...')."""
import os, sys, types, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
kb = types.ModuleType("keyboard"); kb.send = lambda k: None; kb.write = lambda t, delay=0: None
kb.add_hotkey = lambda *a, **k: None
sys.modules["keyboard"] = kb
import config, commands, quick, nlu, whatsapp
import phone_control as phone

fails = 0
def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("OK  " if ok else "FAIL") + f" {name:58} -> {got!r}")

log = []
commands.pc.open_target = lambda t: log.append(("laptop open", t)) or f"Opening {t}."
whatsapp.prepare = lambda who, msg, overlay=None: log.append(("laptop whatsapp", who, msg)) or f"Sent to {who}."
phone.open_app = lambda n: log.append(("PHONE open", n)) or f"Opened {n} on your phone."
phone.ensure_connected = lambda: True
nlu.available = lambda force=False: False
def run(said):
    log.clear()
    reply = commands.handle(said)
    return log[:] , reply

# ---- the bug from the log: WhatsApp went to the phone
check("open WhatsApp and send message to Anik Hai",
      run("Now open WhatsApp and send message to Anik Hai.")[0], [("laptop whatsapp", "Anik", "Hai")])
check("open whatsapp and send hi to Anik", run("open whatsapp and send hi to Anik")[0], [("laptop whatsapp", "Anik", "Hi")])
check("send hello to Vishal on whatsapp", run("send hello to Vishal on whatsapp")[0], [("laptop whatsapp", "Vishal", "Hello")])
check("'...in my laptop' is stripped", run("open WhatsApp in my laptop")[0], [("laptop open", "WhatsApp")])
check("open whatsapp (no device said) -> laptop", run("open whatsapp")[0], [("laptop open", "whatsapp")])

# the AI never even sees phone tools for a laptop request...
names = [t["function"]["name"] for t in nlu.select_tools("I told you to open WhatsApp in my laptop and then send hi to Anik")]
check("AI tools for a laptop request: no phone tools", [n for n in names if n.startswith("phone_") or n in ("call_and_talk", "order_food")], [])
check("...but the laptop WhatsApp tool is there", "whatsapp_message" in names, True)
# ...and if it calls one anyway, it's refused during a laptop request
commands._phone_request["on"] = False
check("phone tool refused during a laptop request", commands.execute("call_and_talk", {"who": "Anik"}).startswith("That is a phone action"), True)
commands._phone_request["on"] = None

# ---- phone mode
check("'operate my mobile'", run("Hey Hinata, now operate my mobile")[1], "Okay, I'm on your phone now. Say 'operate my laptop' to come back.")
check("then 'open whatsapp' -> PHONE", run("open whatsapp")[0], [("PHONE open", "whatsapp")])
check("then 'open youtube' -> PHONE", run("open youtube")[0], [("PHONE open", "youtube")])
check("'...in my laptop' wins even in phone mode", run("open chrome in my laptop")[0], [("laptop open", "chrome")])
check("'operate my laptop'", run("operate my laptop")[1], "Back on your laptop.")
check("then 'open whatsapp' -> laptop again", run("open whatsapp")[0], [("laptop open", "whatsapp")])
check("one breath: 'operate my phone and open instagram'", run("operate my phone and open instagram")[0], [("PHONE open", "instagram")])
check("...mode stays on", quick.on_phone(), True)
commands.handle("okay, now get back to rest")
check("resting brings her back to the laptop", quick.on_phone(), False)
check("explicit 'on my phone open camera' still works", run("on my phone open camera")[0], [("PHONE open", "camera")])
check("...but only for that sentence", run("open camera")[0], [("laptop open", "camera")])

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
