"""Voice lock: profile maths, the owner check, enrolment, spoken commands, and listening past other voices.
Uses a fake fingerprint function, so no model download is needed."""
import math, os, queue, struct, sys, types, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
kb = types.ModuleType("keyboard"); kb.send = lambda k: None; kb.write = lambda t, delay=0: None
kb.add_hotkey = lambda *a, **k: None
sys.modules["keyboard"] = kb
import numpy as np
import config, voice_id, commands, fast_stt

fails = 0
def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("OK  " if ok else "FAIL") + f" {name:55} -> {got!r}")

def tone(ms, freq, amp=8000):
    n = 16000 * ms // 1000
    return b"".join(struct.pack("<h", int(amp * math.sin(2 * math.pi * freq * i / 16000))) for i in range(n))

# fake fingerprint: "you" speak at 200 Hz, a stranger at 330 Hz (stands in for the real model)
YOU = np.array([1.0, 0.2, 0.1]); STRANGER = np.array([0.1, 0.3, 1.0])
def fake_embed(pcm):
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    pitch = np.argmax(np.abs(np.fft.rfft(a))) * 16000 / len(a)          # strongest frequency
    base = YOU if pitch < 260 else STRANGER
    return base + np.random.default_rng(len(pcm)).normal(0, 0.05, 3)

# ---- maths
p = voice_id.make_profile([YOU, YOU * 2, YOU + 0.01])
check("profile mean is unit length", round(float(np.linalg.norm(p["mean"])), 3), 1.0)
check("consistent samples score high", p["self_min"] > 0.99, True)
check("cosine same", round(voice_id.cosine(YOU, YOU * 3), 3), 1.0)
check("15 s splits into 5 x 3 s", len(voice_id.chunks(tone(15000, 200), 3.0)), 5)

# ---- not set up yet: everyone gets through (lock can't work without your voice print)
check("not enrolled -> lock inactive", voice_id.active(), False)
check("not enrolled -> anyone accepted", voice_id.is_owner(tone(1000, 330), fake_embed), True)

# ---- enrolment
check("too little speech", voice_id.enroll_from_pcm(tone(4000, 200), fake_embed).startswith("I only got 4 seconds"), True)
check("enrol from 15 s", voice_id.enroll_from_pcm(tone(15000, 200), fake_embed).startswith("Got it."), True)
check("voice print saved to disk", os.path.isfile(voice_id.PROFILE), True)
voice_id._state["loaded"] = False                                        # as after a restart
check("survives a restart", voice_id.enrolled(), True)
check("noisy enrolment warns", voice_id.enroll_from_pcm(tone(9000, 200) + tone(6000, 330), fake_embed).startswith("Saved, but"), True)
voice_id.enroll_from_pcm(tone(15000, 200), fake_embed)

# ---- the check
config.VOICE_LOCK = True
config.VOICE_THRESHOLD = 0.47
check("your voice accepted", voice_id.is_owner(tone(1200, 200), fake_embed), True)
check("other voice ignored", voice_id.is_owner(tone(1200, 330), fake_embed), False)
check("too short to judge -> ignored", voice_id.is_owner(tone(200, 200), fake_embed), False)
config.VOICE_LOCK = False
check("lock off -> everyone", voice_id.is_owner(tone(1200, 330), fake_embed), True)
config.VOICE_LOCK = True
def boom(pcm): raise RuntimeError("model missing")
check("model failure never locks you out", voice_id.is_owner(tone(1200, 200), boom), True)

# ---- listening keeps waiting through other voices, then takes yours
class FakeMic:
    def __init__(self, frames): self.frames = frames
    def start(self): return True
    def subscribe(self):
        q = queue.Queue()
        for f in self.frames: q.put(f)
        return q
    def unsubscribe(self, q): pass
fb = fast_stt.FRAME_BYTES
split = lambda pcm: [pcm[i:i + fb] for i in range(0, len(pcm) - fb + 1, fb)]
audio = tone(300, 200, 0) + tone(1200, 330) + tone(900, 200, 0) + tone(1200, 200) + tone(1500, 200, 0)
fast_stt._mic = FakeMic(split(audio))
real_embed = voice_id.embed
voice_id.embed = fake_embed
heard = []
real_transcribe = fast_stt.transcribe
fast_stt.transcribe = lambda pcm, prompt=None: heard.append(len(pcm)) or "open notepad"
check("stranger skipped, your command returned", fast_stt.listen(5, skip_ms=0), "open notepad")
check("only YOUR sentence was transcribed", len(heard) == 1 and heard[0] < len(tone(2200, 1)), True)
fast_stt._mic = FakeMic(split(tone(300, 200, 0) + tone(1200, 330) + tone(1500, 200, 0)))
check("only a stranger talks -> nothing", fast_stt.listen(1.5, skip_ms=0), None)
fast_stt.transcribe = real_transcribe

# ---- spoken commands
check("voice lock off", commands.handle("voice lock off"), "Voice lock off. I'll listen to everyone.")
check("voice lock on", commands.handle("turn on voice lock"), "Voice lock on. I only listen to you.")
voice_id.learn = lambda speak=None: "<learning>"
check("learn my voice", commands.handle("learn my voice"), "<learning>")
check("forget my voice", commands.handle("forget my voice").startswith("Done. I've forgotten your voice"), True)
check("after forgetting, lock can't turn on", commands.handle("voice lock on"), "I don't know your voice yet. Say 'learn my voice' first.")
voice_id.embed = real_embed

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
