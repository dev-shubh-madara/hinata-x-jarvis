"""
Female voice for Hinata X Helper.

  * "neural" (default): Microsoft Edge neural voices via the free edge-tts
    package - natural female voice, no API key. Audio plays through pygame.
    Every phrase is cached on disk, so repeated replies ("Done.", "Opening
    Chrome.") start instantly.
  * "system": the built-in Windows SAPI voice (Microsoft Zira), offline.
    Also used automatically whenever the neural voice fails (no internet).

Speech runs on its own thread. speak() can be interrupted with stop() -
pressing the hotkey while she's talking cuts her off (barge-in).
"""

import asyncio
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

_q: "queue.Queue[tuple[str, threading.Event]]" = queue.Queue()
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


def _play_mp3(data: bytes):
    import pygame
    pygame.mixer.music.load(io.BytesIO(data), "mp3")
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

def _say(text: str):
    if config.TTS_ENGINE == "neural" and _init_pygame():
        try:
            _play_mp3(_synth_neural(text))
            return
        except Exception as e:
            print(f"[tts] neural voice failed ({e}) - using the Windows voice.")
    try:
        _speak_system(text)
    except Exception as e:
        print(f"[tts] no speech engine available ({e}) - reply printed only.")


def _worker():
    while True:
        text, done = _q.get()
        _stop_flag.clear()
        _speaking.set()
        try:
            _say(text)
        except Exception as e:
            print(f"[tts] speak failed: {e}")
        finally:
            _speaking.clear()
            done.set()


threading.Thread(target=_worker, daemon=True, name="tts").start()


# ---------------------------------------------------------------- public API

def speak(text: str, wait: bool = True):
    print(f"[{config.ASSISTANT_NAME}] {text}")
    if not text:
        return
    done = threading.Event()
    _q.put((text, done))
    if wait:
        done.wait(timeout=max(15, len(text) / 7))


def stop():
    """Cut off the current sentence and drop anything queued."""
    _stop_flag.set()
    try:
        while True:
            _, done = _q.get_nowait()
            done.set()
    except queue.Empty:
        pass


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
