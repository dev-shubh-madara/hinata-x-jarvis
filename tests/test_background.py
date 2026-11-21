"""Background mode: instant typing/keys, "go to <app>", listen mode, quiet replies.
Replays the command sequence from a hands-free demo and checks every keystroke."""
import os, sys, time, types, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()

log = []
kb = types.ModuleType("keyboard")
kb.send = lambda k: log.append(("paste", clip["v"]) if k == "ctrl+v" else ("key", k))
kb.write = lambda t, delay=0: log.append(("type", t))
kb.add_hotkey = lambda *a, **k: None
sys.modules["keyboard"] = kb
clip = {"v": "my old clipboard"}
pc_mod = types.ModuleType("pyperclip")
pc_mod.copy = lambda v: clip.__setitem__("v", v)
pc_mod.paste = lambda: clip["v"]
sys.modules["pyperclip"] = pc_mod

import config, commands, quick, wake, pc_actions

fails = 0
def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("OK  " if ok else "FAIL") + f" {name:55} -> {got!r}")

opened = []
pc_actions.open_target = lambda t: opened.append(t) or f"Opening {t}."
commands.pc.open_target = pc_actions.open_target
quick._windows = lambda: [(101, "Slack | general | Voderon", "slack"),
                          (102, "opencode - D:\\voderon", "windowsterminal"),
                          (103, "Untitled - Notepad", "notepad"),
                          (104, "main.py - hinata-x-jarvis - Visual Studio Code", "code")]
front = []
quick._bring_front = lambda h: front.append(h)

def run(said):
    """What happens when you say it after 'Hinata' (or in listen mode)."""
    log.clear(); opened.clear(); front.clear()
    rest = wake.decide(said)
    if rest is None:
        return None
    t0 = time.perf_counter()
    reply = commands.handle(rest)
    return reply, (time.perf_counter() - t0) * 1000

# ---- the demo, line by line
r = run("Hinata, open Notes.")
check("open Notes -> Notepad (a page to type on)", opened, ["notepad"])
r = run("Hinata, type this is a demo.")
check("type: exact words, no AI", log, [("type", "this is a demo")])
check(f"type: instant ({r[1]:.1f} ms)", r[1] < 60, True)
run("Hinata, enter.")
check("enter", log, [("key", "enter")])
run("Hinata, go to Slack.")
check("go to Slack focuses the running window", front, [101])
check("...instead of opening a new one", opened, [])
run("Hinata, type Hey, I'm not touching my trackpad or keyboard.")
check("keeps your capitals and commas", log, [("paste", "Hey, I'm not touching my trackpad or keyboard")])
run("Hinata go to opencode")
check("go to opencode (window title)", front, [102])
run("Hinata, type hey buddy, how's it going and press enter")
check("type ... and press enter", log, [("type", "hey buddy, how's it going"), ("key", "enter")])
run("Hinata, new line")
check("new line = shift+enter (doesn't send in chat apps)", log, [("key", "shift+enter")])
run("Hinata go to VS Code")
check("app alias (VS Code -> code.exe)", front, [104])
run("Hinata go to Spotify")
check("not running -> opens it", (front, opened), ([], ["spotify"]))
run("Hinata select all")
check("select all", log, [("key", "ctrl+a")])
run("Hinata, delete that")
check("delete that = delete last word", log, [("key", "ctrl+backspace")])
run("Hinata press tab 3 times")
check("press tab 3 times", log, [("key", "tab")] * 3)

long_text = "This is how you can run so many chats in Claude Code or Codex or Cursor without lifting your fingers"
run("Hinata, type " + long_text + ".")
check("long text is pasted in one go", log, [("paste", long_text)])
check("clipboard put back afterwards", clip["v"], "my old clipboard")

# speech-to-text ends every sentence with "." - that isn't typed; real ? and ! are; spoken punctuation is
for said, want in [("type see you tomorrow.", "see you tomorrow"), ("type see you tomorrow full stop", "see you tomorrow."),
                   ("type are you coming question mark", "are you coming?"), ("type we won exclamation mark", "we won!"),
                   ("type wait, what?", "wait, what?"), ("type we did it!", "we did it!")]:
    log.clear()
    quick.match(said.lower(), said)
    check(f"punctuation: {said!r}", log, [("type", want)])

# ---- how speech-to-text really mishears "Hinata," with a pause (from a spoken end-to-end run)
for heard, want in [("and not to type this as a demo.", "type this as a demo"), ("and not a go to slack.", "go to slack"),
                    ("and now to go to Open Code.", "go to Open Code"), ("Renata, open chrome", "open chrome"),
                    ("Hinata Type-H, I'm not touching", "Type-H, I'm not touching"),
                    ("and then open chrome", None), ("and now we go to the market", None), ("so type this", None),
                    ("I think type is wrong", None), ("My friend was saying Hinata is great character.", None)]:
    check(f"heard {heard[:34]!r}", wake.decide(heard), want)
log.clear()
commands.handle("Type-H, I'm not touching it")
check("'Type-H,' still types (instant path)", log, [("type", "H, I'm not touching it")])

# ---- a pause after the command word: she waits for the rest instead of acting on "open"
for rest, want in [("open", True), ("Open.", True), ("go to", True), ("type", True), ("open chrome", False),
                   ("type hello", False), ("enter", False), ("select all", False)]:
    check(f"incomplete: {rest!r}", wake.incomplete(rest), want)

# ---- listen mode: no name needed, chatter ignored
check("without her name, nothing happens", run("type hello"), None)
check("listen mode on", commands.handle("listen mode").startswith("Listen mode on"), True)
run("type hello")
check("listen mode: 'type hello' runs", log, [("type", "hello")])
run("enter")
check("listen mode: 'enter' runs", log, [("key", "enter")])
check("listen mode: chatter ignored", run("I think the match starts at eight"), None)
check("listen mode: her name still works", run("Hinata, select all")[0], "Done.")
run("stop listening")
check("stop listening", quick.in_listen_mode(), False)
check("after that her name is needed again", run("type hello"), None)
quick.listen_mode(True)
quick._listen["until"] = time.time() - 1
check("listen mode times out by itself", run("type hello"), None)

# ---- quiet replies
for reply, want in [("Opening Chrome.", False), ("Typed it.", False), ("Done.", False), ("Slack.", False),
                    ("I couldn't find anything like zebra.", True), ("Which file should I fix?", True),
                    ("The chat plug-in isn't running. Say 'reload my plugins'.", True), ("Sorry, I didn't catch that.", True)]:
    check(f"spoken in background mode: {reply[:32]!r}", quick.needs_voice(reply), want)

# ---- hologram switch
config.HOLOGRAM_ON_WAKE = False
check("hologram off by default", config.HOLOGRAM_ON_WAKE, False)
check("show hologram", (commands.handle("show hologram"), config.HOLOGRAM_ON_WAKE), ("Hologram on.", True))
check("hologram off", (commands.handle("hologram off"), config.HOLOGRAM_ON_WAKE)[1], False)

# ---- unknown things still go to the AI (not swallowed by the quick list)
check("'open the downloads folder' isn't a key press", quick.match("open the downloads folder", "open the downloads folder"), None)
check("'what's new' isn't a key press", quick.match("what's new", "what's new"), None)

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
