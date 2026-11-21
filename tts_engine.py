"""
Female voice for Hinata X Helper.

  * "neural" (default): Microsoft Edge neural voices via the free edge-tts
    package - natural female voice, no API key. Audio plays through pygame.
    Every phrase is cached on disk, so repeated replies ("Done.", "Opening
    Chrome.") start instantly.
  * "kokoro": an offline neural voice that runs on your laptop (kokoro_tts.py),
    no internet at all. Downloaded once (~330 MB) the first time it's used.
  * "system": the built-in Windows SAPI voice (Microsoft Zira), offline.
    Also used automatically whenever the other voices fail.

Speech runs on its own thread. speak() can be interrupted with stop() -
pressing the hotkey while she's talking cuts her off (barge-in).

Pipelining: the moment a sentence is queued its audio starts being made in
the background, so while she says sentence one, sentence two is already
being synthesized. Streaming replies (nlu.py) feed her one sentence at a
time, so she starts talking before the AI has finished thinking.
"""

import asyncio
import concurrent.futures
import hashlib
import io
import math
import os
import queue
import struct
import threading
import wave

import config

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

_q: "queue.Queue[tuple[str, object, threading.Event]]" = queue.Queue()
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="tts-synth")
_speaking = threading.Event()
_stop_flag = threading.Event()
_CACHE_DIR = os.path.join(config.DATA_DIR, "voice_cache")
os.makedirs(_CACHE_DIR, exist_ok=True)

_state = {"engine": None, "pygame": False, "sapi": None}

PRELOAD_PHRASES = ["Yes?", "Done.", "Sorry, I didn't catch that.", "On it.",
                   "Say confirm to go ahead, or cancel.", "Cancelled."]


# ---------------------------------------------------------------- neural voice

def _cache_path(text: str) -> str:
    key = f"{config.NEURAL_VOICE}|{config.VOICE_RATE}|{config.VOICE_PITCH}|{text}"
    return os.path.join(_CACHE_DIR, hashlib.sha1(key.encode("utf-8")).hexdigest() + ".mp3")


def _synth_neural(text: str) -> bytes:
    path = _cache_path(text)
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        with open(path, "rb") as f:
            return f.read()
    import edge_tts

    async def run():
        com = edge_tts.Communicate(text, config.NEURAL_VOICE,
                                   rate=config.VOICE_RATE, pitch=config.VOICE_PITCH)
        buf = bytearray()
        async for chunk in com.stream():
            if chunk.get("type") == "audio":
                buf.extend(chunk["data"])
        return bytes(buf)

    data = asyncio.run(asyncio.wait_for(run(), timeout=12))
    if not data:
        raise RuntimeError("neural voice returned no audio")
    if len(text) < 160:                      # cache short, likely-repeated phrases
        try:
            with open(path, "wb") as f:
                f.write(data)
        except OSError:
            pass
    return data


def _init_pygame() -> bool:
    if _state["pygame"]:
        return True
    try:
        import pygame
        pygame.mixer.init(frequency=24000)
        _state["pygame"] = True
    except Exception as e:
        print(f"[tts] pygame audio unavailable: {e}")
    return _state["pygame"]


def _play_mp3(data: bytes, fmt: str = "mp3"):
    import pygame
    pygame.mixer.music.load(io.BytesIO(data), fmt)
    pygame.mixer.music.play()
    clock = pygame.time.Clock()
    while pygame.mixer.music.get_busy():
        if _stop_flag.is_set():
            pygame.mixer.music.stop()
            break
        clock.tick(60)
    try:
        pygame.mixer.music.unload()
    except Exception:
        pass


# ---------------------------------------------------------------- system voice

def _sapi():
    if _state["sapi"] is not None:
        return _state["sapi"]
    import comtypes
    import comtypes.client
    comtypes.CoInitialize()
    voice = comtypes.client.CreateObject("SAPI.SpVoice")
    try:
        voices = voice.GetVoices()
        for i in range(voices.Count):
            tok = voices.Item(i)
            desc = (tok.GetDescription() or "").lower()
            gender = ""
            try:
                gender = (tok.GetAttribute("Gender") or "").lower()
            except Exception:
                pass
            if "zira" in desc or gender == "female":
                voice.Voice = tok
                break
    except Exception:
        pass
    voice.Rate = config.SYSTEM_VOICE_RATE
    _state["sapi"] = voice
    return voice


def _speak_system(text: str):
    v = _sapi()
    SVSFlagsAsync, SVSFPurgeBeforeSpeak = 1, 2
    v.Speak(text, SVSFlagsAsync)
    while not v.WaitUntilDone(50):
        if _stop_flag.is_set():
            v.Speak("", SVSFlagsAsync | SVSFPurgeBeforeSpeak)
            break


# ---------------------------------------------------------------- worker

def _synth(text: str):
    """(audio bytes, format) for the configured engine. Runs ahead of playback.

    kokoro: offline voice for every sentence it fully knows, the neural voice
            for the rest (Kokoro skips words it doesn't know).
    neural: Edge voice; if the internet is down, the offline voice takes over.
    """
    import kokoro_tts
    if config.TTS_ENGINE == "kokoro" and kokoro_tts.covers(text):
        try:
            return kokoro_tts.synth(text), "wav"
        except Exception as e:
            print(f"[tts] offline voice failed ({e}) - trying the neural voice.")
    try:
        return _synth_neural(text), "mp3"
    except Exception as e:
        if kokoro_tts.installed():
            print(f"[tts] neural voice failed ({e}) - using the offline voice.")
            return kokoro_tts.synth(text), "wav"
        raise


def _say(text: str, future=None):
    if config.TTS_ENGINE in ("neural", "kokoro") and _init_pygame():
        try:
            data, fmt = future.result(timeout=15) if future is not None else _synth(text)
            if not _stop_flag.is_set():
                _play_mp3(data, fmt)
            return
        except Exception as e:
            print(f"[tts] neural voice failed ({e}) - using the Windows voice.")
    try:
        _speak_system(text)
    except Exception as e:
        print(f"[tts] no speech engine available ({e}) - reply printed only.")


def _worker():
    while True:
        text, future, done = _q.get()
        if not _barge["cut"]:
            _stop_flag.clear()
        _speaking.set()
        try:
            if not _stop_flag.is_set():
                _say(text, future)
        except Exception as e:
            print(f"[tts] speak failed: {e}")
        finally:
            if _q.empty():
                _speaking.clear()
                _barge["cut"] = False
            done.set()


threading.Thread(target=_worker, daemon=True, name="tts").start()


# ---------------------------------------------------------------- public API

_barge = {"cut": False}


def speak(text: str, wait: bool = True):
    print(f"[{config.ASSISTANT_NAME}] {text}")
    if not text:
        return
    done = threading.Event()
    future = None
    if config.TTS_ENGINE in ("neural", "kokoro"):
        future = _pool.submit(_synth, text)          # start making the audio right now
    _barge["cut"] = False
    _q.put((text, future, done))
    if wait:
        done.wait(timeout=max(15, len(text) / 7))


def wait_idle(timeout: float = 60.0):
    """Blocks until everything queued has been said (used after a streamed reply)."""
    import time
    end = time.time() + timeout
    while (not _q.empty() or _speaking.is_set()) and time.time() < end:
        time.sleep(0.03)


def stop():
    """Cut off the current sentence and drop anything queued."""
    _stop_flag.set()
    _barge["cut"] = True
    try:
        while True:
            _, future, done = _q.get_nowait()
            if future is not None:
                future.cancel()
            done.set()
    except queue.Empty:
        pass
    if _q.empty():
        _speaking.clear()


def is_speaking() -> bool:
    return _speaking.is_set()


def preload():
    """Warm the voice cache in the background so common replies are instant."""
    if config.TTS_ENGINE != "neural":
        return

    def run():
        for p in PRELOAD_PHRASES:
            try:
                _synth_neural(p)
            except Exception:
                return
    threading.Thread(target=run, daemon=True, name="tts-preload").start()


# ---------------------------------------------------------------- chime

def _chime_path() -> str:
    path = os.path.join(config.DATA_DIR, "chime.wav")
    if os.path.isfile(path):
        return path
    rate, frames = 22050, []
    for i, (freq, dur) in enumerate(((880, 0.07), (1320, 0.11))):
        n = int(rate * dur)
        for k in range(n):
            env = math.sin(math.pi * k / n)
            frames.append(int(9000 * env * math.sin(2 * math.pi * freq * k / rate)))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", s) for s in frames))
    return path


def chime():
    if not config.CHIME:
        return
    try:
        import winsound
        winsound.PlaySound(_chime_path(), winsound.SND_FILENAME | winsound.SND_ASYNC)
    except Exception:
        pass


# ---------------------------------------------------------------- tick (background mode "done")

def _tick_path() -> str:
    path = os.path.join(config.DATA_DIR, "tick.wav")
    if not os.path.exists(path):
        import math
        import struct
        import wave
        rate = 22050
        frames = []
        for i in range(int(rate * 0.07)):
            t = i / rate
            env = math.exp(-t * 60)
            frames.append(int(9000 * env * math.sin(2 * math.pi * 1320 * t)))
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(struct.pack(f"<{len(frames)}h", *frames))
    return path


def tick():
    """A soft 70 ms 'done' sound."""
    if not getattr(config, "CHIME", True):
        return
    try:
        import winsound
        winsound.PlaySound(_tick_path(), winsound.SND_FILENAME | winsound.SND_ASYNC)
    except Exception:
        pass
