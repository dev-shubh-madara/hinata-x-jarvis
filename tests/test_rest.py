"""Resting vs awake: after "get back to rest" NOTHING is acted on until her name is said again.
Replays real sentences from a session log (game audio, friends talking, misheard words) in order."""
import os, sys, types, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
kb = types.ModuleType("keyboard"); kb.send = lambda k: None; kb.write = lambda t, delay=0: None
kb.add_hotkey = lambda *a, **k: None
sys.modules["keyboard"] = kb
import config, quick, wake, session

fails = 0
def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("OK  " if ok else "FAIL") + f" {name:62} -> {got!r}")

config.AWAKE_IDLE_MINUTES = 0
quick.listen_mode(False)

# (what the mic heard, seconds of audio, what should happen)
REAL_LOG = [
    ("Hinata, go.",                                                  0.8, ("awake", "")),       # just her name, misheard
    ("Play a song on YouTube.",                                      0.6, ("run", "Play a song on YouTube")),
    ("Ok, get rest back again.",                                     3.8, ("rest", "")),
    # --- resting from here: none of this may do anything
    ("Turn off your cell phone now because I am playing game.",      2.9, ("ignore", None)),
    ("No.",                                                          0.3, ("ignore", None)),
    ("Ok, now get back to rest.",                                    2.3, ("ignore", None)),
    ("Okay, bye.",                                                   1.5, ("ignore", None)),
    ("The boy will be a sidekick and the chicken will be something else.", 2.4, ("ignore", None)),
    ("Maro, strada, mayo, siyo.",                                    1.8, ("ignore", None)),
    ("Play a game.",                                                 1.4, ("ignore", None)),
    ("Play a song on YouTube. Send a WhatsApp message to Vishal.",   0.7, ("ignore", None)),
    ("Arey, mother chuu.",                                           1.0, ("ignore", None)),
    # --- her name wakes her for exactly one command
    ("Hinata, what happened?",                                       3.1, ("run", "what happened")),
    ("Play a game.",                                                 1.4, ("ignore", None)),   # back to resting
    ("Hinata, sit down for now. I am playing game. Don't disturb me.", 3.0, ("rest", "")),
    ("Open Chrome",                                                  1.0, ("ignore", None)),
    # --- "Hey Hinata": awake until told to rest
    ("Hey Hinata.",                                                  0.9, ("awake", "")),
    ("Open Chrome.",                                                 1.0, ("run", "Open Chrome")),
    ("type hello",                                                   0.8, ("run", "type hello")),
    ("What's the time?",                                             0.9, ("run", "What's the time?")),
    ("lol that was so funny",                                        1.2, ("ignore", None)),    # chatter, even awake
    ("Okay, now get back to rest.",                                  2.0, ("rest", "")),
    ("Open Chrome.",                                                 1.0, ("ignore", None)),
    ("type hello",                                                   0.8, ("ignore", None)),
    ("What's the time?",                                             0.9, ("ignore", None)),
    ("Hinata, open Notepad.",                                        1.2, ("run", "open Notepad")),
    ("type hello",                                                   0.8, ("ignore", None)),    # one command only
]
for heard, secs, want in REAL_LOG:
    state = "awake" if quick.is_awake() else "resting"
    check(f"[{state:7}] {heard[:48]!r}", wake.route(heard, secs), want)

# ---- every way of saying it, from any state
for bye in ["Okay, now get back to rest.", "get back to rest", "go to sleep", "you can rest now", "that's all",
            "stop listening", "Hinata, get back to rest", "ok get rest back", "sit down for now, don't disturb me",
            "be quiet", "aaram karo"]:
    quick.listen_mode(True, awake=True)
    check(f"rest phrase {bye!r}", (wake.route(bye, 1.5)[0], quick.in_listen_mode()), ("rest", False))
for not_rest in ["Hinata, rest my case: open the restaurant website", "what is the rest of the syllabus"]:
    quick.listen_mode(True, awake=True)
    check(f"not a rest order {not_rest[:40]!r}", wake.route(not_rest, 2)[0], "run")
quick.listen_mode(False)

# ---- a session woken by her name never keeps listening after a chat reply
class Ov:
    def __getattr__(self, n): return lambda *a, **k: None
heard = iter(["what's the weather", "The boy will be a sidekick", "Maro strada"])
listened = []
def listen(timeout):
    listened.append(timeout)
    return next(heard, None)
why = session.run_session(overlay=Ov(), typed=False, listen=listen, ask_command=lambda: None,
                          run_command=lambda t: "chat", speak=lambda t: None,
                          conversation_mode=False, is_rest=quick.is_rest)
check("woken by name: one answer, then she stops listening", (why, len(listened)), ("action", 1))

# ---- rest inside a hotkey conversation ends it at once (it used to go to the AI)
heard = iter(["how are you", "Ok, now get back to rest.", "this must never be heard"])
said, ran = [], []
quick.listen_mode(True, awake=True)
why = session.run_session(overlay=Ov(), typed=False, listen=lambda t: next(heard, None), ask_command=lambda: None,
                          run_command=lambda t: ran.append(t) or "chat", speak=said.append,
                          conversation_mode=True, is_rest=quick.is_rest, on_rest=lambda: quick.listen_mode(False))
check("hotkey chat + rest: ends with 'rest'", why, "rest")
check("...the rest phrase never reached the AI", ran, ["how are you"])
check("...she says she's resting", said[-1], "Okay, resting. Say Hey Hinata when you need me.")
check("...and awake mode is off", quick.in_listen_mode(), False)

# ---- confirm still waits for your answer even in one-command sessions
heard = iter(["shut down", "confirm"])
ran = []
why = session.run_session(overlay=Ov(), typed=False, listen=lambda t: next(heard, None), ask_command=lambda: None,
                          run_command=lambda t: ran.append(t) or ("confirm" if t == "shut down" else "action"),
                          speak=lambda t: None, conversation_mode=False)
check("'shut down' -> waits for 'confirm'", ran, ["shut down", "confirm"])

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
