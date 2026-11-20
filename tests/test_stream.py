"""Streaming replies: the first sentence is spoken before the model finishes; tool calls are never spoken."""
import json, os, sys, threading, time, types, tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
kb = types.ModuleType("keyboard"); kb.send = lambda k: None; kb.write = lambda t, delay=0: None
kb.add_hotkey = lambda *a, **k: None
sys.modules["keyboard"] = kb
import config, nlu, commands

fails = 0
def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("OK  " if ok else "FAIL") + f" {name:55} -> {got!r}")

SCRIPT = {"mode": "chat"}
TOKEN_DELAY = 0.08

class FakeOllama(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(200); self.send_header("Content-Type", "application/x-ndjson"); self.end_headers()
        def send(obj):
            self.wfile.write((json.dumps(obj) + "\n").encode()); self.wfile.flush()
        if not body.get("stream"):
            send({"message": {"role": "assistant", "content": "Not streamed."}, "done": True}); return
        if SCRIPT["mode"] == "tool":
            send({"message": {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "open_target", "arguments": {"target": "chrome"}}}]}, "done": False})
            send({"message": {"role": "assistant", "content": ""}, "done": True}); return
        if SCRIPT["mode"] == "think":
            words = "<think> the user wants a joke, keep it short </think> Why did the coder quit? He didn't get arrays.".split(" ")
        else:
            words = ("Black holes are regions where gravity is so strong that nothing escapes. "
                     "Not even light. They form when huge stars collapse.").split(" ")
        for w in words:
            send({"message": {"role": "assistant", "content": w + " "}, "done": False})
            time.sleep(TOKEN_DELAY)
        send({"message": {"role": "assistant", "content": ""}, "done": True})

srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
threading.Thread(target=srv.serve_forever, daemon=True).start()
config.OLLAMA_HOST = f"127.0.0.1:{srv.server_port}"
nlu._state.update(ok=True, model="fake", checked_at=time.time(), tools=True)
nlu.available = lambda force=False: True

# ---- quick answer streams sentence by sentence
heard = []
t0 = time.perf_counter()
first_at = {}
def ear(s):
    first_at.setdefault("t", time.perf_counter() - t0)
    heard.append(s)
reply = nlu.quick_answer("what is a black hole", on_sentence=ear)
total = time.perf_counter() - t0
check("three sentences, in order", heard, ["Black holes are regions where gravity is so strong that nothing escapes.",
                                           "Not even light.", "They form when huge stars collapse."])
check("first words long before the end", first_at["t"] < total * 0.75, True)
check("reply marked as already spoken", nlu.last_reply_spoken(), True)
check("full reply returned", reply.startswith("Black holes") and reply.endswith("collapse."), True)

# ---- a tool call is never read out
SCRIPT["mode"] = "tool"
heard.clear()
ran = []
reply = nlu.run_agent("open chrome", lambda n, a: ran.append((n, a)) or "Opening Chrome.", on_sentence=heard.append)
check("tool ran", ran, [("open_target", {"target": "chrome"})])
check("nothing spoken while streaming", heard, [])
check("tool reply not marked spoken", nlu.last_reply_spoken(), False)
check("tool result is the reply", reply, "Opening Chrome.")

# ---- <think> reasoning is never spoken
SCRIPT["mode"] = "think"
heard.clear()
nlu.quick_answer("tell me a joke", on_sentence=heard.append)
check("thinking is silent", heard, ["Why did the coder quit?", "He didn't get arrays."])

# ---- sentence splitter edge cases
out = []
sp = nlu.Sentences(out.append)
for piece in ['{"tool": "open_target", ', '"args": {"target": "x"}}']:
    sp.add(piece)
check("JSON answer is never spoken", (sp.finish(), out), ("", []))
out = []
sp = nlu.Sentences(out.append)
long = "So here is the thing about learning Python for your exams, you should start with loops and functions, then " \
       "practice files and dictionaries every day"
sp.add(long)
check("very long first sentence breaks at a comma", len(out) == 1 and out[0].endswith(","), True)

# ---- router: streamed reply is flagged so main.py doesn't say it twice
SCRIPT["mode"] = "chat"
said = []
commands.set_streamer(said.append)
config.QUICK_ANSWERS = True
reply = commands.handle("what is a black hole")
commands.set_streamer(None)
check("router knows it was spoken", commands.already_spoken(), True)
check("router streamed it", len(said), 3)
check("next command resets the flag", (commands.handle("cancel"), commands.already_spoken())[1], False)

# ---- tool routing keeps the prompt small enough for the model's context
import commands as _c  # noqa: F401  (loads the plug-in tools)
for said, need in [("open notepad and write a poem", "write_document"), ("play lofi on youtube", "play_media"),
                   ("go to github and click sign in", "browser_click"), ("read this error and fix it", "fix_code"),
                   ("on my phone open whatsapp", "phone_open_app"), ("what's 2 to the power 40", "run_python"),
                   ("remind me in 10 minutes to drink water", "set_timer"), ("hey how are you", "open_target")]:
    nlu._last_sel.clear()
    sel = nlu.select_tools(said, "phone" in said)
    names = [x["function"]["name"] for x in sel]
    size = len(json.dumps(sel)) // 3.6
    check(f"tools for {said[:30]!r}: has {need}, ~{size:.0f} tok", need in names and size < 2600, True)
check("all tools would overflow a 4k context", len(json.dumps(nlu.all_tools())) // 3.6 > 4096, True)
nlu._last_sel.clear()
nlu.select_tools("play lofi on youtube")
check("follow-up keeps last turn's tools", "media_control" in [x["function"]["name"] for x in nlu.select_tools("now pause it")], True)

# ---- voice pipeline: sentence 2 is synthesized while sentence 1 plays
import tts_engine
config.TTS_ENGINE = "neural"
played = []
def slow_synth(text):
    time.sleep(0.3); return (text.encode(), "mp3")
def slow_play(data, fmt="mp3"):
    end = time.time() + 0.3
    while time.time() < end:
        if tts_engine._stop_flag.is_set():
            return
        time.sleep(0.01)
    played.append(data.decode())
tts_engine._synth = slow_synth
tts_engine._play_mp3 = slow_play
tts_engine._init_pygame = lambda: True
t0 = time.perf_counter()
for s in ("One.", "Two.", "Three."):
    tts_engine.speak(s, wait=False)
tts_engine.wait_idle(10)
took = time.perf_counter() - t0
check("all three said, in order", played, ["One.", "Two.", "Three."])
check(f"pipelined (took {took:.2f}s, sequential = 1.8s)", took < 1.45, True)

played.clear()
for s in ("Long one.", "Never said.", "Never said either."):
    tts_engine.speak(s, wait=False)
time.sleep(0.45)
tts_engine.stop()                       # barge-in: you pressed the hotkey / said her name
tts_engine.wait_idle(5)
check("barge-in drops the rest", played, [])
tts_engine.speak("After barge-in.", wait=True)
check("she talks again after barge-in", played, ["After barge-in."])

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
