"""
"Hey Hinata" - hands-free wake word.

While she's idle, every short burst of speech from the always-on mic is
transcribed (whisper on the GPU takes about 0.1 s for a two-second clip)
and checked for her name at the start. Two ways to use it:

    "Hinata"                          -> she opens and listens
    "Hinata, open Chrome and play lofi" -> she does it straight away,
                                          no second sentence needed

Only the first few words count, so a video or a friend saying "Hinata"
mid-sentence doesn't wake her. She ignores the mic while she's talking,
so her own voice can't wake her either. Works fully offline.
"""

import difflib
import re
import threading
import time

import config
import fast_stt

_FILLERS = {"hey", "hi", "hello", "ok", "okay", "yo", "oh", "so", "and", "um", "uh", "hmm", "a", "o"}
_state = {"paused": threading.Event(), "thread": None, "fired": 0.0}


def _names() -> list[str]:
    words = [w.lower() for w in getattr(config, "WAKE_WORDS", ["hinata"])]
    return words or ["hinata"]


def _close(word: str, name: str) -> bool:
    if word == name:
        return True
    return len(word) >= 4 and difflib.SequenceMatcher(None, word, name).ratio() >= 0.78


def match(text: str):
    """None if the text doesn't start with her name, else the rest of the command ('' if just her name)."""
    words = re.sub(r"[^a-z0-9' ]", " ", (text or "").lower()).split()
    i = 0
    while i < len(words) and words[i] in _FILLERS and i < 2:
        i += 1
    for name in _names():
        for j in range(i, min(i + 2, len(words))):             # allow one filler we didn't know
            one = words[j]
            two = one + (words[j + 1] if j + 1 < len(words) else "")   # "hi nata" -> "hinata"
            for cand, used in ((one, 1), (two, 2)):
                if _close(cand, name):
                    rest_words = words[j + used:]
                    while rest_words and rest_words[0] in ("x", "helper"):
                        rest_words = rest_words[1:]
                    # keep the user's original casing / punctuation for the rest
                    return _tail(text, len(rest_words))
    return None


def _tail(text: str, n_words: int) -> str:
    if n_words <= 0:
        return ""
    parts = (text or "").strip().split()
    return " ".join(parts[-n_words:]).strip(" ,.!?")


def pause():
    _state["paused"].set()


def resume():
    _state["paused"].clear()


def start(fire, is_speaking=lambda: False) -> bool:
    """Starts listening for her name. fire(rest) is called when she's woken."""
    if not getattr(config, "WAKE_WORD", True) or _state["thread"]:
        return bool(_state["thread"])
    m = fast_stt.mic()
    if not m.start():
        print("[wake] no microphone - wake word off")
        return False
    _state["thread"] = threading.Thread(target=_loop, args=(m, fire, is_speaking), daemon=True, name="wake")
    _state["thread"].start()
    print(f"[wake] say: {' / '.join(n.title() for n in _names())}")
    return True


def _loop(m, fire, is_speaking):
    q = m.subscribe()
    vad = fast_stt.make_vad()
    busy = lambda: _state["paused"].is_set() or is_speaking()          # noqa: E731
    while True:
        if busy():
            _drain(q)
            time.sleep(0.05)
            continue
        pcm = fast_stt.record(q, timeout=3600, vad=vad, end_ms=500, max_ms=12000, stop=busy)
        if pcm is None or busy():
            continue
        if len(pcm) < fast_stt.RATE * 2 * 0.25:                         # under 0.25 s: a click, not a word
            continue
        text = fast_stt.transcribe(pcm, prompt="Hinata. Hey Hinata, open Chrome.")
        rest = match(text or "")
        if rest is None:
            continue
        if time.time() - _state["fired"] < 1.0:
            continue
        _state["fired"] = time.time()
        print(f"[wake] heard {text!r}")
        try:
            fire(rest)
        except Exception as e:
            print(f"[wake] {e}")


def _drain(q):
    try:
        while True:
            q.get_nowait()
    except Exception:
        pass
