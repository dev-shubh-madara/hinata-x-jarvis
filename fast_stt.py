"""
Fast speech-to-text.

The old path opened the microphone on every command, waited 1.5 s of
silence and sent the audio to Google. This one keeps a single microphone
stream open all the time and decides when you've finished talking with a
voice activity detector (VAD), so she stops listening about 0.4 s after
your last word. The audio then goes to faster-whisper on the GPU.

    mic (always open, 30 ms frames)
       |-- wake.py looks for "Hinata" while she's idle
       '-- listen() records one command when she's awake

Nothing here needs the internet. If faster-whisper isn't installed the
recording still goes to Google, so it never gets worse than before.
"""

import collections
import queue
import threading
import time

import config

RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = RATE * FRAME_MS // 1000          # 480
FRAME_BYTES = FRAME_SAMPLES * 2                  # 16-bit mono


# ---------------------------------------------------------------- voice activity

class EnergyVAD:
    """Fallback VAD when webrtcvad isn't installed: adaptive noise floor."""

    def __init__(self, ratio: float = 2.6, floor: float = 120.0):
        self.ratio = ratio
        self.noise = floor
        self.floor = floor

    def __call__(self, frame: bytes) -> bool:
        import array
        import math
        s = array.array("h", frame)
        if not s:
            return False
        rms = math.sqrt(sum(x * x for x in s) / len(s))
        speech = rms > max(self.floor, self.noise * self.ratio)
        if not speech:                                   # follow the room's noise slowly
            self.noise = 0.95 * self.noise + 0.05 * rms
        return speech


def make_vad():
    try:
        import webrtcvad
        v = webrtcvad.Vad(int(getattr(config, "VAD_AGGRESSIVENESS", 2)))
        return lambda frame: v.is_speech(frame, RATE)
    except Exception:
        return EnergyVAD()


# ---------------------------------------------------------------- endpointing (pure, tested)

class Endpointer:
    """Feeds 30 ms frames, says when an utterance started and ended.

    start: 4 speech frames out of the last 6, about 120 ms (ignores clicks and taps)
    end:   end_ms of silence after at least min_speech_ms of speech
    """

    def __init__(self, end_ms=None, min_speech_ms=240, preroll_ms=300, max_ms=None):
        self.end_frames = max(1, int((end_ms or config.END_SILENCE_MS) / FRAME_MS))
        self.min_frames = max(1, int(min_speech_ms / FRAME_MS))
        self.max_frames = int((max_ms or config.PHRASE_TIME_LIMIT * 1000) / FRAME_MS)
        self.pre = collections.deque(maxlen=max(1, int(preroll_ms / FRAME_MS)))
        self.window = collections.deque(maxlen=6)
        self.frames: list[bytes] = []
        self.started = False
        self.voiced = 0
        self.silence = 0

    def feed(self, frame: bytes, speech: bool) -> bool:
        """True when the utterance is complete."""
        if not self.started:
            self.pre.append(frame)
            self.window.append(speech)
            if sum(self.window) >= 4:
                self.started = True
                self.frames = list(self.pre)
                self.voiced = sum(self.window)
            return False
        self.frames.append(frame)
        if speech:
            self.voiced += 1
            self.silence = 0
        else:
            self.silence += 1
        if len(self.frames) >= self.max_frames:
            return True
        return self.voiced >= self.min_frames and self.silence >= self.end_frames

    def audio(self) -> bytes:
        # trim the trailing silence - whisper is faster on shorter audio
        keep = len(self.frames) - max(0, self.silence - 3)
        return b"".join(self.frames[:keep])


# ---------------------------------------------------------------- the shared microphone

class MicStream:
    """One microphone stream for the whole app. Frames go to whoever is listening."""

    def __init__(self, device_index=None):
        self.device_index = device_index
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._thread = None
        self.ok = False
        self.error = ""

    def start(self) -> bool:
        if self._thread:
            return self.ok
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True, name="mic")
        self._thread.start()
        ready.wait(5)
        return self.ok

    def _run(self, ready):
        try:
            import pyaudio
            pa = pyaudio.PyAudio()
            stream = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True,
                             frames_per_buffer=FRAME_SAMPLES, input_device_index=self.device_index)
            self.ok = True
        except Exception as e:
            self.error = str(e)
            print(f"[mic] couldn't open the microphone: {e}")
            ready.set()
            return
        ready.set()
        print("[mic] always-on stream open (16 kHz, 30 ms frames)")
        while True:
            try:
                frame = stream.read(FRAME_SAMPLES, exception_on_overflow=False)
            except Exception as e:
                print(f"[mic] read error: {e}")
                time.sleep(0.2)
                continue
            with self._lock:
                subs = list(self._subs)
            for q in subs:
                if q.qsize() < 400:                  # a slow reader never blocks the mic
                    q.put(frame)

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)


_mic: MicStream | None = None


def mic() -> MicStream:
    global _mic
    if _mic is None:
        _mic = MicStream(getattr(config, "MIC_DEVICE_INDEX", None))
    return _mic


def record(frames: "queue.Queue", timeout: float, vad=None, end_ms=None, max_ms=None,
           stop=lambda: False) -> bytes | None:
    """Reads frames until one utterance is complete. None if nobody spoke within timeout."""
    vad = vad or make_vad()
    ep = Endpointer(end_ms=end_ms, max_ms=max_ms)
    t_end = time.time() + timeout
    while True:
        if stop():
            return None
        try:
            frame = frames.get(timeout=0.25)
        except queue.Empty:
            if not ep.started and time.time() > t_end:
                return None
            continue
        if ep.feed(frame, vad(frame)):
            return ep.audio()
        if not ep.started and time.time() > t_end:
            return None


# ---------------------------------------------------------------- transcription

_whisper = {"model": None, "failed": False, "lock": threading.Lock()}


def load_whisper():
    with _whisper["lock"]:
        if _whisper["model"] is not None or _whisper["failed"]:
            return _whisper["model"]
        try:
            from faster_whisper import WhisperModel
            name = config.WHISPER_MODEL
            try:
                model = WhisperModel(name, device="cuda", compute_type="float16")
                where = "GPU"
            except Exception:
                model = WhisperModel(name, device="cpu", compute_type="int8")
                where = "CPU"
            _whisper["model"] = model
            print(f"[stt] faster-whisper '{name}' ready on {where}")
            # first call is slow (CUDA kernels) - do it now, not on your first command
            import numpy as np
            list(model.transcribe(np.zeros(RATE, dtype=np.float32), beam_size=1)[0])
        except Exception as e:
            _whisper["failed"] = True
            print(f"[stt] faster-whisper unavailable ({e}) - using Google speech")
        return _whisper["model"]


_PROMPT = "Hinata, open Chrome. Play a song on YouTube. Send a WhatsApp message to Vishal."


def transcribe(pcm: bytes, prompt: str = _PROMPT) -> str | None:
    """16 kHz mono int16 -> text. Whisper on the GPU, Google as the fallback."""
    if not pcm:
        return None
    model = load_whisper()
    if model is not None:
        try:
            import numpy as np
            audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            lang = (config.SPEECH_LANGUAGE or "en").split("-")[0]
            segs, _ = model.transcribe(audio, language=lang, beam_size=1, best_of=1, temperature=0.0,
                                       condition_on_previous_text=False, without_timestamps=True,
                                       initial_prompt=prompt, vad_filter=False)
            text = " ".join(s.text for s in segs).strip()
            return clean(text) or None
        except Exception as e:
            print(f"[stt] whisper failed: {e}")
    try:
        import speech_recognition as sr
        return sr.Recognizer().recognize_google(sr.AudioData(pcm, RATE, 2), language=config.SPEECH_LANGUAGE)
    except Exception as e:
        print(f"[stt] Google speech failed: {e}")
        return None


# whisper's habit of inventing these on silence / noise
_HALLUCINATIONS = {"thank you.", "thanks for watching!", "thank you for watching.", "you", "bye.", ".",
                   "thanks for watching.", "subscribe", "please subscribe."}


def clean(text: str) -> str:
    t = (text or "").strip()
    if t.lower() in _HALLUCINATIONS:
        return ""
    return t


def listen(timeout: float, stop=lambda: False) -> str | None:
    """One spoken command from the always-on mic. Returns text or None."""
    m = mic()
    if not m.start():
        return None
    q = m.subscribe()
    try:
        t0 = time.perf_counter()
        pcm = record(q, timeout, stop=stop)
        if pcm is None:
            print("[mic] Heard nothing.")
            return None
        t1 = time.perf_counter()
        text = transcribe(pcm)
        print(f"[stt] {len(pcm) / (RATE * 2):.1f}s audio, endpoint {(t1 - t0):.2f}s, "
              f"transcribe {(time.perf_counter() - t1) * 1000:.0f} ms -> {text!r}")
        return text
    finally:
        m.unsubscribe(q)
