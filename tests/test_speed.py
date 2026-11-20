"""Speed pack: end-of-speech detection, wake word matching, one-breath commands."""
import math, os, struct, sys, time, types, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
kb = types.ModuleType("keyboard"); kb.send = lambda k: None; kb.write = lambda t, delay=0: None
kb.add_hotkey = lambda *a, **k: None
sys.modules["keyboard"] = kb
if "speech_recognition" not in sys.modules:
    try:
        import speech_recognition  # noqa: F401
    except ImportError:
        sr = types.ModuleType("speech_recognition")
        sr.Recognizer = sr.Microphone = object
        sr.AudioData = object
        sr.WaitTimeoutError = sr.UnknownValueError = sr.RequestError = Exception
        sys.modules["speech_recognition"] = sr
import config, fast_stt, wake, hotkey_listener

fails = 0
def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("OK  " if ok else "FAIL") + f" {name:55} -> {got!r}")


def tone(ms, amp):
    n = fast_stt.RATE * ms // 1000
    return b"".join(struct.pack("<h", int(amp * math.sin(2 * math.pi * 220 * i / fast_stt.RATE))) for i in range(n))


def frames(pcm):
    b = fast_stt.FRAME_BYTES
    return [pcm[i:i + b] for i in range(0, len(pcm) - b + 1, b)]


# ---- endpointer: 600 ms silence, 900 ms speech, then silence
audio = tone(600, 0) + tone(900, 8000) + tone(2000, 0)
vad = fast_stt.EnergyVAD()
ep = fast_stt.Endpointer(end_ms=450)
done_at = None
for i, f in enumerate(frames(audio)):
    if ep.feed(f, vad(f)):
        done_at = i
        break
speech_end = (600 + 900) // fast_stt.FRAME_MS
check("ends after speech, not before", done_at is not None and done_at > speech_end, True)
check("ends within ~0.5 s of the last word", done_at is not None and (done_at - speech_end) * 30 <= 540, True)
check("keeps the speech (+preroll)", len(ep.audio()) >= len(tone(900, 1)), True)
check("trailing silence trimmed", len(ep.audio()) < len(tone(900 + 300 + 450, 1)), True)

# a short click is not speech
ep = fast_stt.Endpointer(end_ms=450)
vad = fast_stt.EnergyVAD()
clicked = [ep.feed(f, vad(f)) for f in frames(tone(500, 0) + tone(60, 9000) + tone(1500, 0))]
check("60 ms click never starts an utterance", ep.started, False)

# a 90 ms click (under the 150 ms minimum) starts an utterance but is too short: it's dropped and the timeout still works
import queue
q = queue.Queue()
for f in frames(tone(200, 0) + tone(90, 9000) + tone(2500, 0)):
    q.put(f)
t0 = time.time()
check("short blip alone -> None (not a 30 s wait)", fast_stt.record(q, timeout=0.5, vad=fast_stt.EnergyVAD(), end_ms=450), None)
check("...and returns quickly", time.time() - t0 < 2.5, True)
q = queue.Queue()
for f in frames(tone(200, 0) + tone(90, 9000) + tone(800, 0) + tone(900, 8000) + tone(1500, 0)):
    q.put(f)
pcm = fast_stt.record(q, timeout=3, vad=fast_stt.EnergyVAD(), end_ms=450)
check("blip then a real command -> the command", bool(pcm) and len(pcm) < len(tone(900 + 300 + 500, 1)), True)
q = queue.Queue()
for f in frames(tone(180, 9000) + tone(2500, 0)):            # her chime, right as listening starts
    q.put(f)
check("her own chime is skipped", fast_stt.record(q, timeout=0.5, vad=fast_stt.EnergyVAD(), skip_ms=220), None)
q = queue.Queue()
for f in frames(tone(300, 0) + tone(200, 8000) + tone(1500, 0)):   # a quick "no"
    q.put(f)
check("a short 'no' (200 ms) still counts", bool(fast_stt.record(q, timeout=2, vad=fast_stt.EnergyVAD(), skip_ms=220)), True)

# the endpoint timeout: nobody speaks
import queue
q = queue.Queue()
for f in frames(tone(300, 0)):
    q.put(f)
check("silence -> None after timeout", fast_stt.record(q, timeout=0.3, vad=fast_stt.EnergyVAD()), None)

# record() returns the utterance from a queue
q = queue.Queue()
for f in frames(tone(400, 0) + tone(700, 8000) + tone(1200, 0)):
    q.put(f)
pcm = fast_stt.record(q, timeout=2, vad=fast_stt.EnergyVAD(), end_ms=450)
check("record() returns audio", bool(pcm) and len(pcm) > len(tone(600, 1)), True)

# whisper hallucinations on silence are dropped
check("hallucination dropped", fast_stt.clean("Thank you."), "")
check("real text kept", fast_stt.clean("open chrome"), "open chrome")

# ---- wake word
config.WAKE_WORDS = ["hinata", "jarvis"]
for text, want in [
    ("Hinata", ""),
    ("Hey Hinata.", ""),
    ("Hinata, open Chrome.", "open Chrome"),
    ("hey hinata open chrome and play lofi", "open chrome and play lofi"),
    ("Hi Nata, what's the time?", "what's the time"),
    ("Hinatta play some music", "play some music"),
    ("Okay Jarvis, lock the PC", "lock the PC"),
    ("Hinata X Helper open notepad", "open notepad"),
    ("I was telling Hinata about it", None),
    ("open chrome", None),
    ("my sister watched Naruto and Hinata was there", None),
    ("", None),
    ("Hindi song chalao", None),
]:
    check(f"wake: {text!r}", wake.match(text), want)

# ---- one-breath command reaches the session as its first sentence
hotkey_listener.fire_wake("open notepad")
check("wake fires a voice trigger", hotkey_listener.wait_for_trigger(), "voice")
check("first listen returns the same-breath command", hotkey_listener.capture_command(None, None, 5), "open notepad")
check("only once", hotkey_listener.take_first_text(), "")

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
