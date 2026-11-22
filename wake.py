"""
"Hey Hinata" - hands-free wake word.

While she's idle, every short burst of speech from the always-on mic is
transcribed (whisper on the GPU takes about 0.1 s for a two-second clip)
and checked for her name at the start. Two ways to use it:

    "Hinata"                          -> she opens and listens
    "Hinata, open Chrome and play lofi" -> she does it straight away,
                                          no second sentence needed

Only the first few words count, so a video or a friend saying "Hinata"
mid-sentence doesn't wake her. In listen mode (quick.py) her name isn't
needed: any sentence that starts like a command ("open...", "type...",
"enter") runs, and everything else is ignored. She ignores the mic while she's talking,
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
    text = text or ""
    toks = [(m.group(0).lower(), m.start(), m.end()) for m in re.finditer(r"[A-Za-z0-9']+", text)]
    words = [w for w, _, _ in toks]
    i = 0
    while i < len(words) and words[i] in _FILLERS and i < 2:
        i += 1
    for name in _names():
        for j in range(i, min(i + 2, len(words))):             # allow one filler we didn't know
            one = words[j]
            two = one + (words[j + 1] if j + 1 < len(words) else "")   # "hi nata" -> "hinata"
            for cand, used in ((one, 1), (two, 2)):
                if _close(cand, name):
                    k = j + used
                    while k < len(words) and words[k] in ("x", "helper"):
                        k += 1
                    return _from(text, toks, k)
    return None


def _from(text: str, toks, k: int) -> str:
    """The original text from token k on, with its casing and punctuation."""
    if k >= len(toks):
        return ""
    return text[toks[k][1]:].strip(" ,.!?")


def _sounds_like_name(words) -> bool:
    """'and not to' / 'renata' / 'in a ta' - how speech-to-text mishears 'Hinata' after a pause."""
    joined = re.sub(r"[^a-z]", "", "".join(words))
    if len(joined) < 4:
        return False
    vowels = lambda x: re.sub(r"[aeiouy]+", "a", x).lstrip("h")       # noqa: E731
    for name in _names():
        if difflib.SequenceMatcher(None, vowels(joined), vowels(name)).ratio() >= 0.76:
            return True
    return False


def fuzzy_match(text: str):
    """Second chance when the name was misheard: 1-3 name-like words, then a real command word.
    The command word is what keeps ordinary talk from waking her."""
    import quick
    text = text or ""
    toks = [(m.group(0).lower(), m.start(), m.end()) for m in re.finditer(r"[A-Za-z0-9']+", text)]
    words = [w for w, _, _ in toks]
    for n in (1, 2, 3):
        if len(words) <= n:
            break
        rest = _from(text, toks, n)
        if _sounds_like_name(words[:n]) and quick.looks_like_command(rest):
            return rest
    return None


_BARE = re.compile(r"^(?:open|launch|start|close|type|write|dictate|go|go to|switch|switch to|bring up|focus|play|"
                   r"search|search for|google|find|send|message|call|remind me|set|turn on|turn off|show|hinata)$", re.I)


def incomplete(rest: str) -> bool:
    """Only a command word so far - you paused before saying what (e.g. 'open' ... 'chrome')."""
    return bool(_BARE.match((rest or "").strip(" .,!?")))


def route(text: str, seconds: float = 2.0):
    """What to do with one sentence from the mic. Returns (what, command):
        ("ignore", None)   - not for her (resting and no name, or chatter)
        ("awake", "")      - "Hey Hinata" on its own: awake until "get back to rest"
        ("rest", "")       - "okay, now get back to rest": back to resting at once
        ("run", command)   - do this command
    Resting is the default: then ONLY a sentence that starts with her name does anything."""
    import quick
    rest = decide(text)
    if rest is None:
        return "ignore", None
    if quick.is_rest(rest) or rest == "stop listening":
        quick.listen_mode(False)
        return "rest", ""
    if rest.strip(" .,!?").lower() in ("go", "hey", "hi", "yo", "ok", "okay") and seconds < 1.5:
        rest = ""                                     # a short "Hinata go/hey" is just her name
    if rest == "" and getattr(config, "WAKE_STAYS_AWAKE", True):
        quick.listen_mode(True, awake=True)
        return "awake", ""
    return "run", rest


def _say(text: str):
    try:
        import tts_engine
        tts_engine.speak(text, wait=False)
    except Exception:
        print(f"[Hinata] {text}")


def decide(text: str):
    """What to run for this sentence: the command after her name, or - in listen mode -
    the whole sentence if it starts like a command. None = not for her."""
    import quick
    if quick.in_listen_mode() and quick.is_rest(text):
        return "stop listening"                     # "okay, now get back to rest"
    rest = match(text)
    if rest is None:
        rest = fuzzy_match(text)
    if rest is not None:
        quick.keep_alive()
        return rest
    if quick.in_listen_mode():
        ok = quick.awake_accepts(text) if quick.is_awake() else quick.looks_like_command(text)
        if ok:
            quick.keep_alive()
            return text.strip(" ,.")
    return None


def _owner(pcm) -> bool:
    try:
        import voice_id
        return voice_id.is_owner(pcm)
    except Exception as e:
        print(f"[wake] voice check unavailable: {e}")
        return True


def _awake_sound():
    try:
        import tts_engine
        tts_engine.chime()
    except Exception:
        pass


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
        pcm = fast_stt.record(q, timeout=3600, vad=vad, end_ms=config.END_SILENCE_MS, max_ms=12000, stop=busy)
        if pcm is None or busy():
            continue
        if len(pcm) < fast_stt.RATE * 2 * 0.25:                         # under 0.25 s: a click, not a word
            continue
        if not _owner(pcm):                                              # voice lock: not your voice
            continue
        t0 = time.perf_counter()
        # only her name in the hint: example commands here made whisper add words you never
        # said ("Hinata" alone came out as "Hinata, go.")
        text = fast_stt.transcribe(pcm, prompt="Hey Hinata.")
        took = (time.perf_counter() - t0) * 1000
        what, rest = route(text or "", len(pcm) / (fast_stt.RATE * 2))
        if what == "ignore":
            continue
        if what == "awake":
            _awake_sound()
            print(f"[wake] heard {text!r} - awake, taking every command until 'get back to rest'")
            continue
        if what == "rest":
            print(f"[wake] heard {text!r} - resting; only her name wakes her now")
            _say("Okay, resting. Say Hey Hinata when you need me.")
            continue
        if incomplete(rest):                          # "Hinata, open..." <pause> "...Chrome"
            more = fast_stt.record(q, timeout=4, vad=vad, end_ms=config.END_SILENCE_MS, max_ms=10000, stop=busy)
            more_text = fast_stt.transcribe(more, prompt="Notepad. Chrome. VS Code. Hello.") \
                if more and _owner(more) else ""
            # only a short follow-up belongs to the command ("...Chrome"); a long sentence was someone talking
            if more_text and len(more_text.split()) <= 6:
                print(f"[wake] ...and {more_text!r}")
                rest = f"{rest.rstrip(' .,')} {more_text.strip()}"
        if time.time() - _state["fired"] < 1.0:
            continue
        _state["fired"] = time.time()
        print(f"[wake] heard {text!r}  ({len(pcm) / (fast_stt.RATE * 2):.1f}s audio, transcribed in {took:.0f} ms)")
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
