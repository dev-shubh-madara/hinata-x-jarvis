"""
Offline voice: Kokoro running on the laptop through sherpa-onnx.

No internet and no cloud, so her voice works on college Wi-Fi that blocks
things, on a plane, anywhere. Set TTS_ENGINE = "kokoro" in config.py, or
say "switch to offline voice".

The model (~330 MB) downloads once from the sherpa-onnx GitHub releases
into %LOCALAPPDATA%\\HinataXHelper\\kokoro. Names Kokoro doesn't know
(Hinata, Warangal...) are taught in KOKORO_LEXICON below, otherwise it
silently skips them.
"""

import io
import os
import tarfile
import threading
import wave

import config

URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/kokoro-multi-lang-v1_0.tar.bz2"
DIR = os.path.join(config.DATA_DIR, "kokoro")
MODEL_DIR = os.path.join(DIR, "kokoro-multi-lang-v1_0")

# a few voices that suit her (speaker ids in kokoro v1.0)
VOICES = {"heart": 3, "bella": 2, "nicole": 6, "nova": 7, "sarah": 9, "sky": 10, "emma": 21, "alice": 20}

# word -> phonemes, for names Kokoro would otherwise skip
KOKORO_LEXICON = """\
hinata h ɪ n ˈ ɑ t ə
jarvis ʤ ˈ ɑ ɹ v ɪ s
shubh ʃ ˈ ʊ b
voderon v ˈ O d ə ɹ ɑ n
warangal w ˈ ɔ ɹ ə ŋ ɡ ə l
lofi l ˈ O f i
github ɡ ˈ ɪ t h ʌ b
whatsapp w ˈ ʌ t s æ p
youtube j ˈ u t u b
"""

_state = {"tts": None, "lock": threading.Lock(), "failed": "", "words": None}


def installed() -> bool:
    return os.path.isfile(os.path.join(MODEL_DIR, "model.onnx"))


def download(progress=print) -> bool:
    """Downloads and unpacks the model. True when it's ready."""
    if installed():
        return True
    import requests
    os.makedirs(DIR, exist_ok=True)
    tmp = os.path.join(DIR, "kokoro.tar.bz2.part")
    progress("Downloading my offline voice, about 330 MB. One time only.")
    with requests.get(URL, stream=True, timeout=30) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    with tarfile.open(tmp, "r:bz2") as t:
        root = os.path.realpath(DIR)
        for m in t.getmembers():                       # never write outside the folder
            if not os.path.realpath(os.path.join(DIR, m.name)).startswith(root + os.sep):
                raise RuntimeError(f"unsafe path in the archive: {m.name}")
        t.extractall(DIR)
    os.remove(tmp)
    return installed()


def _lexicon_path() -> str:
    path = os.path.join(DIR, "hinata-lexicon.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(KOKORO_LEXICON)
    return path


def _load():
    with _state["lock"]:
        if _state["tts"] is not None:
            return _state["tts"]
        if not installed() and not download():
            raise RuntimeError("offline voice not downloaded")
        import sherpa_onnx
        m = MODEL_DIR + os.sep
        lex = ",".join([_lexicon_path(), m + "lexicon-us-en.txt", m + "lexicon-zh.txt"])
        cfg = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
            kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                model=m + "model.onnx", voices=m + "voices.bin", tokens=m + "tokens.txt",
                data_dir=m + "espeak-ng-data", dict_dir=m + "dict", lexicon=lex),
            num_threads=max(2, min(6, (os.cpu_count() or 4) // 2))))
        _state["tts"] = sherpa_onnx.OfflineTts(cfg)
        print("[tts] offline Kokoro voice ready")
        return _state["tts"]


def _words() -> set:
    if _state["words"] is None:
        words = set()
        for line in KOKORO_LEXICON.splitlines():
            if line.strip():
                words.add(line.split()[0])
        try:
            with open(os.path.join(MODEL_DIR, "lexicon-us-en.txt"), encoding="utf-8") as f:
                for line in f:
                    words.add(line.split(" ", 1)[0])
        except OSError:
            pass
        _state["words"] = words
    return _state["words"]


def covers(text: str) -> bool:
    """True if Kokoro knows every word (it silently skips the ones it doesn't)."""
    import re
    if not installed():
        return False
    known = _words()
    toks = re.findall(r"[A-Za-z']+|\d+", text or "")
    return bool(toks) and all(t.lower() in known for t in toks)


def speaker_id() -> int:
    v = str(getattr(config, "KOKORO_VOICE", "heart")).lower()
    return VOICES.get(v, int(v) if v.isdigit() else 3)


def synth(text: str) -> bytes:
    """Text -> WAV bytes (24 kHz mono)."""
    tts = _load()
    speed = float(getattr(config, "KOKORO_SPEED", 1.08))
    a = tts.generate(text, sid=speaker_id(), speed=speed)
    return to_wav(a.samples, a.sample_rate)


def to_wav(samples, rate: int) -> bytes:
    try:
        import numpy as np
        pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1, 1) * 32767).astype("<i2")
    except ImportError:
        import array
        pcm = array.array("h", (max(-32768, min(32767, int(x * 32767))) for x in samples))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def warm_up():
    """Loads the model in the background so the first reply isn't slow."""
    if config.TTS_ENGINE != "kokoro":
        return
    def run():
        try:
            synth("Ready.")
        except Exception as e:
            _state["failed"] = str(e)
            print(f"[tts] offline voice unavailable: {e}")
    threading.Thread(target=run, daemon=True, name="kokoro-warm").start()
