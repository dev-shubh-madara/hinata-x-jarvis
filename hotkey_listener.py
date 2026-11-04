"""
Triggers and speech-to-text.

Two global hotkeys:
  HOTKEY       -> speak a command
  TYPE_HOTKEY  -> type a command into the command bar (fastest)

Pressing the voice hotkey while Hinata is talking cuts her off (barge-in).
Speech-to-text is Google (free, online) by default or faster-whisper
(offline, uses your GPU) - see STT_ENGINE in config.py.
"""

import queue

import speech_recognition as sr

import config
import tts_engine

_triggers: "queue.Queue[str]" = queue.Queue()
_whisper = {"model": None, "failed": False}


def _fire(kind: str):
    if tts_engine.is_speaking():
        tts_engine.stop()
    # collapse repeated presses into one trigger
    if _triggers.qsize() < 2:
        _triggers.put(kind)


def install_hotkeys():
    import keyboard
    # Alt combos (esp. Alt+Space) leak to the focused window and pop its system
    # menu, so swallow the keys (suppress) and warn if the user picks one.
    for hk in (config.HOTKEY, config.TYPE_HOTKEY):
        if "alt" in hk.lower():
            print(f"[hotkey] Warning: '{hk}' uses Alt and may open window menus. Try ctrl+shift+h.")
    keyboard.add_hotkey(config.HOTKEY, _fire, args=("voice",), suppress=True)
    keyboard.add_hotkey(config.TYPE_HOTKEY, _fire, args=("type",), suppress=True)
    print(f"[hotkey] Voice: {config.HOTKEY}   Type: {config.TYPE_HOTKEY}")


def wait_for_trigger() -> str:
    """Blocks until a hotkey fires. Returns 'voice' or 'type'."""
    return _triggers.get()


def calibrate(recognizer: sr.Recognizer, mic: sr.Microphone):
    with mic as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.8)
    recognizer.dynamic_energy_threshold = True
    recognizer.dynamic_energy_ratio = 1.3          # don't drift so high that soft words count as silence
    recognizer.pause_threshold = config.END_OF_SPEECH_PAUSE   # silence needed before she acts
    recognizer.phrase_threshold = 0.2
    recognizer.non_speaking_duration = min(0.5, config.END_OF_SPEECH_PAUSE)
    print(f"[calibration] energy_threshold set to {recognizer.energy_threshold:.0f}")


def _load_whisper():
    if _whisper["model"] is not None or _whisper["failed"]:
        return _whisper["model"]
    try:
        from faster_whisper import WhisperModel
        try:
            model = WhisperModel(config.WHISPER_MODEL, device="cuda", compute_type="float16")
            where = "GPU"
        except Exception:
            model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
            where = "CPU"
        _whisper["model"] = model
        print(f"[stt] faster-whisper '{config.WHISPER_MODEL}' loaded on {where}.")
    except Exception as e:
        _whisper["failed"] = True
        print(f"[stt] faster-whisper unavailable ({e}) - using Google speech.")
    return _whisper["model"]


def preload():
    if config.STT_ENGINE == "whisper":
        _load_whisper()


def _transcribe_whisper(audio: sr.AudioData) -> str | None:
    import numpy as np
    model = _load_whisper()
    if model is None:
        return None
    raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    lang = config.SPEECH_LANGUAGE.split("-")[0]
    segments, _ = model.transcribe(pcm, language=lang, beam_size=1, vad_filter=True)
    text = " ".join(s.text for s in segments).strip()
    return text or None


def drain():
    """Forget hotkey presses made while she was busy (e.g. barge-in taps)."""
    try:
        while True:
            _triggers.get_nowait()
    except queue.Empty:
        pass


def capture_command(recognizer: sr.Recognizer, mic: sr.Microphone, timeout=None) -> str | None:
    """Records and transcribes one command. None if nothing usable was heard."""
    print("[mic] Listening...")
    with mic as source:
        try:
            audio = recognizer.listen(source, timeout=config.LISTEN_TIMEOUT if timeout is None else timeout,
                                      phrase_time_limit=config.PHRASE_TIME_LIMIT)
        except sr.WaitTimeoutError:
            print("[mic] Heard nothing.")
            return None

    if config.STT_ENGINE == "whisper":
        try:
            text = _transcribe_whisper(audio)
            if text:
                return text
        except Exception as e:
            print(f"[stt] whisper failed: {e}")

    try:
        return recognizer.recognize_google(audio, language=config.SPEECH_LANGUAGE)
    except sr.UnknownValueError:
        print("[mic] Couldn't understand the audio.")
        return None
    except sr.RequestError as e:
        print(f"[mic] Speech service error (needs internet): {e}")
        return None
