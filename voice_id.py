"""
Voice lock: Hinata only obeys your voice.

    "Hinata, learn my voice"   -> talk naturally for ~15 seconds, once
    "Hinata, voice lock off"   /  "voice lock on"
    "Hinata, forget my voice"

Every sentence she hears is turned into a voice fingerprint (a speaker
embedding from the 3D-Speaker ERes2Net model, run offline with sherpa-onnx,
~40 ms on the CPU) and compared with yours. If it isn't close enough she
ignores it before even transcribing it - other people, the TV, YouTube.

The model (~40 MB) downloads once from the sherpa-onnx GitHub releases. Your
voice print stays in %LOCALAPPDATA%\\HinataXHelper\\voice - numbers only, no
recording is kept. Every decision is logged with its score so the threshold
(VOICE_THRESHOLD in config.py) can be tuned to your real voice.
"""

import json
import os
import threading
import time

import config

MODEL_NAME = "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
MODEL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/" + MODEL_NAME
DIR = os.path.join(config.DATA_DIR, "voice")
MODEL_PATH = os.path.join(DIR, MODEL_NAME)
PROFILE = os.path.join(DIR, "my_voice.json")
RATE = 16000

_state = {"ex": None, "lock": threading.Lock(), "profile": None, "loaded": False}


# ---------------------------------------------------------------- maths (pure, tested)

def _norm(v):
    import numpy as np
    v = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n else v


def cosine(a, b) -> float:
    import numpy as np
    return float(np.dot(_norm(a), _norm(b)))


def make_profile(embeddings: list) -> dict:
    """Mean of several embeddings + how consistent they were."""
    import numpy as np
    embs = [_norm(e) for e in embeddings]
    mean = _norm(np.mean(embs, axis=0))
    selfs = [cosine(e, mean) for e in embs]
    return {"mean": mean.tolist(), "n": len(embs), "self_min": min(selfs), "self_avg": sum(selfs) / len(selfs),
            "created": time.time(), "model": MODEL_NAME}


def leave_one_out(embeddings: list) -> list[float]:
    """Each piece compared with the average of the OTHER pieces - a piece where someone else
    talked (or a fan roared) stands out here, instead of hiding inside the average."""
    import numpy as np
    embs = [_norm(e) for e in embeddings]
    out = []
    for i, e in enumerate(embs):
        others = [x for j, x in enumerate(embs) if j != i]
        out.append(cosine(e, np.mean(others, axis=0)) if others else 1.0)
    return out


GOOD_PIECE = 0.6
PIECE_SECONDS = 1.5


def chunks(pcm: bytes, seconds: float = 3.0) -> list[bytes]:
    """Splits voiced audio into equal pieces for enrolment."""
    step = int(RATE * 2 * seconds)
    out = [pcm[i:i + step] for i in range(0, len(pcm) - step + 1, step)]
    return out or ([pcm] if pcm else [])


# ---------------------------------------------------------------- model

def installed() -> bool:
    return os.path.isfile(MODEL_PATH) and os.path.getsize(MODEL_PATH) > 1_000_000


def download() -> bool:
    if installed():
        return True
    import requests
    os.makedirs(DIR, exist_ok=True)
    tmp = MODEL_PATH + ".part"
    with requests.get(MODEL_URL, stream=True, timeout=30) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    os.replace(tmp, MODEL_PATH)
    return installed()


def _extractor():
    with _state["lock"]:
        if _state["ex"] is None:
            if not installed() and not download():
                raise RuntimeError("voice model not downloaded")
            import sherpa_onnx
            cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=MODEL_PATH, num_threads=2)
            _state["ex"] = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
        return _state["ex"]


def embed(pcm: bytes):
    """16 kHz mono int16 -> voice fingerprint."""
    import numpy as np
    ex = _extractor()
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    s = ex.create_stream()
    s.accept_waveform(RATE, a)
    s.input_finished()
    return np.array(ex.compute(s), dtype=np.float32)


# ---------------------------------------------------------------- profile

def profile():
    if not _state["loaded"]:
        _state["loaded"] = True
        try:
            with open(PROFILE, encoding="utf-8") as f:
                _state["profile"] = json.load(f)
        except (OSError, ValueError):
            _state["profile"] = None
    return _state["profile"]


def enrolled() -> bool:
    return profile() is not None


def save_profile(p: dict):
    os.makedirs(DIR, exist_ok=True)
    with open(PROFILE, "w", encoding="utf-8") as f:
        json.dump(p, f)
    _state["profile"], _state["loaded"] = p, True


def forget() -> str:
    try:
        os.remove(PROFILE)
    except OSError:
        pass
    _state["profile"], _state["loaded"] = None, True
    return "Done. I've forgotten your voice, so I'll listen to everyone again."


def active() -> bool:
    return bool(getattr(config, "VOICE_LOCK", True)) and enrolled()


# ---------------------------------------------------------------- the check

MIN_SECONDS = 0.35          # shorter than this can't be judged - a click, not a word


def score(pcm: bytes, embed_fn=None) -> float:
    p = profile()
    return cosine((embed_fn or embed)(pcm), p["mean"])


def is_owner(pcm: bytes, embed_fn=None) -> bool:
    """True if this sounds like you (or the lock is off / not set up)."""
    if not active():
        return True
    if len(pcm) < RATE * 2 * MIN_SECONDS:
        return False
    t0 = time.perf_counter()
    try:
        s = score(pcm, embed_fn)
    except Exception as e:
        print(f"[voice] check failed ({e}) - letting it through")
        return True
    th = float(getattr(config, "VOICE_THRESHOLD", 0.47))
    ok = s >= th
    print(f"[voice] {'you' if ok else 'NOT you - ignored'} (score {s:.2f}, need {th:.2f}, "
          f"{(time.perf_counter() - t0) * 1000:.0f} ms)")
    return ok


# ---------------------------------------------------------------- enrolment

def enroll_from_pcm(pcm: bytes, embed_fn=None) -> str:
    """Builds your voice print from ~15 s of your speech."""
    seconds = len(pcm) / (RATE * 2)
    if seconds < 8:
        return f"I only got {seconds:.0f} seconds of your voice. I need about 15 - say 'learn my voice' again."
    # short pieces, so a few seconds of someone else land in pieces of their own and can be dropped
    embs = [(embed_fn or embed)(c) for c in chunks(pcm, PIECE_SECONDS)]
    loo = leave_one_out(embs)
    import statistics
    bar = max(GOOD_PIECE, statistics.median(loo) - 0.08) if len(loo) >= 3 else GOOD_PIECE
    keep = [e for e, sc in zip(embs, loo) if sc >= bar]
    print("[voice] piece scores: " + ", ".join(f"{x:.2f}" for x in loo))
    if len(keep) < 3:
        return ("Your recording was too mixed up - noise or more than one voice. "
                "Say 'learn my voice' again in a quiet room, with only you talking.")
    p = make_profile(keep)
    save_profile(p)
    print(f"[voice] learned from {p['n']} of {len(embs)} pieces, consistency {p['self_avg']:.2f}")
    if len(keep) < 0.75 * len(embs):              # a quarter or more didn't match: someone else / noise
        return (f"Saved, but part of the recording didn't sound like you - maybe someone else or noise - so I left "
                f"it out and used {len(keep)} of {len(embs)} pieces. For the best lock, say 'learn my voice' "
                "again in a quiet room.")
    return "Got it. From now on I only listen to your voice. Say 'voice lock off' any time to turn it off."


def record_enrolment(seconds: float = 15.0, timeout: float = 40.0, on_progress=None) -> bytes:
    """Records only the frames with speech in them until `seconds` of your voice is collected."""
    import fast_stt
    m = fast_stt.mic()
    if not m.start():
        return b""
    q = m.subscribe()
    vad = fast_stt.make_vad()
    need = int(seconds * 1000 / fast_stt.FRAME_MS)
    got: list[bytes] = []
    end = time.time() + timeout
    try:
        while len(got) < need and time.time() < end:
            try:
                f = q.get(timeout=0.5)
            except Exception:
                continue
            if vad(f):
                got.append(f)
                if on_progress and len(got) % int(5000 / fast_stt.FRAME_MS) == 0:
                    on_progress(len(got) * fast_stt.FRAME_MS / 1000)
    finally:
        m.unsubscribe(q)
    return b"".join(got)


def learn(speak=None) -> str:
    """The spoken 'learn my voice' flow."""
    try:
        if not installed():
            if speak:
                speak("One moment, I'm getting my voice recognition model.")
            download()
        _extractor()
    except Exception as e:
        return f"I couldn't set up voice recognition: {e}"
    if speak:
        speak("Talk to me naturally for about fifteen seconds. Tell me about your day, your projects, anything.")
    pcm = record_enrolment()
    return enroll_from_pcm(pcm)


def warm_up():
    """Loads the model in the background so the first check isn't slow."""
    if not active():
        return
    threading.Thread(target=lambda: _safe(lambda: embed(b"\0\0" * RATE)), daemon=True, name="voice-warm").start()


def _safe(fn):
    try:
        fn()
    except Exception as e:
        print(f"[voice] {e}")
