"""
AI phone calls - "Call mom and tell her I'll be late today."

Hinata places the call from YOUR phone (ADB), the call audio comes to the
laptop through Windows **Phone Link** (Bluetooth calling), and she does the
talking: she listens to the other person, answers with the local AI, then
hangs up and saves a transcript.

    phone --(Bluetooth, Phone Link)--> laptop speakers  -> Hinata listens (loopback)
    Hinata's voice -> "CABLE Input" -> "CABLE Output" mic -> Phone Link -> the call

One-time setup (README > "AI phone calls"):
  1. Phone Link app on the laptop, linked to your phone, with Calls turned on (Bluetooth).
  2. Free VB-Audio Virtual Cable (vb-audio.com/Cable). In Windows Sound > Recording,
     set "CABLE Output" as the Default Communication Device (that's the mic Phone Link uses).
     Without the cable it still works: Hinata speaks from the speakers and the laptop mic
     picks her up - just less clean.
  3. pip install pyaudiowpatch miniaudio

She always says she's an AI assistant calling for you, and only calls after you say "confirm".
"""

import asyncio
import datetime as dt
import json
import os
import re
import threading
import time

import numpy as np

import config
import nlu
import phone_control as phone

RATE = 16000
_busy = threading.Event()


# ---------------------------------------------------------------- step 1: confirm

def prepare(who: str, message: str):
    from pc_actions import Confirm
    if not getattr(config, "CALL_AI_ENABLED", True):
        return "AI calls are turned off in config.py (CALL_AI_ENABLED)."
    if _busy.is_set():
        return "I'm already on a call, Boss."
    if not phone.ensure_connected():
        return phone.NOT_CONNECTED
    missing = _missing_libs()
    if missing:
        return f"For AI calls I need {missing}. Run: pip install pyaudiowpatch miniaudio, then restart me."
    found = phone.resolve_number(who)
    if not found:
        return f"I couldn't find {who} in your phone contacts."
    name, number = found
    msg = (message or "").strip() or "a quick message"
    return Confirm("ai_call", {"name": name, "number": number, "message": msg},
                   f"I'll call {name} and tell them: {msg}. Say confirm to call.")


def _missing_libs() -> str:
    miss = []
    for mod in ("pyaudiowpatch", "miniaudio"):
        try:
            __import__(mod)
        except ImportError:
            miss.append(mod)
    return " and ".join(miss)


# ---------------------------------------------------------------- step 2: the call

def start(payload: dict, speak_status=None, overlay=None) -> str:
    if _busy.is_set():
        return "I'm already on a call."
    _busy.set()
    threading.Thread(target=_call_thread, args=(payload, speak_status, overlay), daemon=True,
                     name="ai-call").start()
    return f"Calling {payload['name']} now, Boss. I'll tell you how it goes."


def _call_thread(p, speak_status, overlay):
    transcript, outcome = [], "The call didn't connect."
    audio = None
    try:
        audio = _Audio()
        phone.place_call(p["number"])
        print(f"[call] dialing {p['name']} ({p['number']})")
        if not _wait_answer(audio, timeout=45):
            outcome = f"{p['name']} didn't pick up."
            return
        if audio.speakerphone:
            _speaker_on()
        time.sleep(0.6)
        outcome = _conversation(p, audio, transcript)
    except Exception as e:
        print(f"[call] error: {e}")
        outcome = f"The call had a problem: {e}"
    finally:
        try:
            if call_state() not in ("DISCONNECTED", "IDLE"):
                phone.end_call()
        except Exception:
            pass
        if audio:
            audio.close()
        path = _save(p, transcript, outcome)
        _busy.clear()
        summary = outcome
        if transcript:
            theirs = [t for who, t in transcript if who != "Hinata"]
            if theirs:
                summary += f" {p['name']} said: {theirs[-1]}"
        print(f"[call] done - {summary}")
        if overlay:
            try:
                overlay.flash(f"Call with {p['name']} done - transcript saved", 8)
            except Exception:
                pass
        if path:
            try:
                os.startfile(path)                      # the transcript pops up, like FRIDAY
            except Exception:
                pass
        if speak_status:
            speak_status(summary)


def call_state() -> str:
    """ACTIVE / DIALING / RINGING / DISCONNECTED / IDLE, from Android's telecom service."""
    out = phone.shell("dumpsys telecom | grep -iE 'state[=: ]' | head -20", timeout=6)
    for st in ("ACTIVE", "DIALING", "CONNECTING", "RINGING", "ON_HOLD", "DISCONNECTING"):
        if re.search(rf"\b{st}\b", out):
            return st
    reg = phone.shell("dumpsys telephony.registry | grep -m1 mCallState", timeout=6)
    if "mCallState=0" in reg.replace(" ", ""):
        return "IDLE"
    return "UNKNOWN"


def _speaker_on():
    """Speakerphone mode: loud speaker on the phone, so the laptop mic can hear the call."""
    try:
        r = phone.tap_text("speaker")
        if isinstance(r, str) and "can't see" in r:
            phone.tap_text("audio")                      # some dialers call it "Audio"
        for _ in range(6):
            phone.press_key("volume up")                 # call volume up
    except Exception as e:
        print(f"[call] speaker on failed: {e}")


def _wait_answer(audio, timeout=45) -> bool:
    """True once the call is ACTIVE (answered)."""
    end = time.time() + timeout
    seen_dial = False
    while time.time() < end:
        st = call_state()
        if st == "ACTIVE":
            return True
        if st in ("DIALING", "CONNECTING", "RINGING"):
            seen_dial = True
        elif seen_dial and st in ("IDLE", "DISCONNECTED"):
            return False                                  # rejected / busy
        time.sleep(1)
    return False


def _conversation(p, audio, transcript) -> str:
    user = config.USER_NAME or "my boss"
    goal = p["message"]
    msgs = [{"role": "system", "content": (
        f"You are {config.ASSISTANT_NAME}, a polite female AI assistant on a PHONE CALL with {p['name']}, "
        f"calling on behalf of {user}. Your job: {goal}. "
        "You already introduced yourself. Speak naturally and briefly (1-2 short sentences per turn), "
        "warm and respectful. Reply in the language the other person uses (English or Hindi/Hinglish). "
        "Never invent facts you weren't given; if asked something you don't know, say you'll ask "
        f"{user} to call back. {user}'s pronoun is '{_pron()}'. Once the message is delivered and acknowledged, say a short goodbye and end. "
        'Answer ONLY JSON: {"say": "<what to say>", "end": true|false}')}]
    me = config.ASSISTANT_NAME.split()[0]
    if re.match(r"(please )?(tell|inform|let)\b", goal, re.I):
        news = _third_person(goal)
        opener = (f"Hello {p['name']}, I'm {me}, {user}'s AI assistant. "
                  f"{user} is a bit busy, so {_pron()} asked me to let you know that {news[:1].lower() + news[1:]}")
    else:      # a question or anything else - let the AI word the opening line
        first = _think(msgs + [{"role": "user", "content": (
            f"(The call just connected. Say hello to {p['name']}, introduce yourself as {me}, {user}'s AI "
            "assistant, and start your job in the same breath.)")}])
        opener = first["say"]
    _say(audio, opener, transcript)
    msgs.append({"role": "assistant", "content": json.dumps({"say": opener, "end": False})})
    deadline = time.time() + 60 * float(getattr(config, "CALL_MAX_MINUTES", 4))
    silent = 0
    while time.time() < deadline:
        if call_state() in ("IDLE", "DISCONNECTED"):
            return f"I delivered the message and {p['name']} hung up."
        heard = audio.listen(max_wait=9, max_len=14)
        text = _stt(heard) if heard is not None else None
        if not text:
            silent += 1
            if silent >= 2:
                _say(audio, "I can't hear you clearly, so I'll ask him to call you back. Bye!", transcript)
                return f"The line was quiet - I left the message with {p['name']}."
            continue
        silent = 0
        transcript.append((p["name"], text))
        print(f"[call] {p['name']}: {text}")
        msgs.append({"role": "user", "content": text})
        reply = _think(msgs)
        _say(audio, reply["say"], transcript)
        msgs.append({"role": "assistant", "content": json.dumps(reply)})
        if reply["end"]:
            time.sleep(0.8)
            return f"I called {p['name']} and delivered your message."
    _say(audio, "I have to go now. Bye!", transcript)
    return f"I called {p['name']} - the call ran long, so I wrapped it up."


def _pron(kind="he") -> str:
    he = (getattr(config, "USER_PRONOUN", "he") or "he").lower()
    table = {"he": {"he": "he", "his": "his", "him": "him"},
             "she": {"he": "she", "his": "her", "him": "her"},
             "they": {"he": "they", "his": "their", "him": "them"}}
    return table.get(he, table["he"])[kind]


def _third_person(goal: str) -> str:
    """'tell her I'll be late today' -> 'He will be late today.'"""
    g = goal.strip().rstrip(".")
    g = re.sub(r"^(please )?(tell|inform|let|ask) (her|him|them)( know)?( that)?\s*", "", g, flags=re.I)
    g = re.sub(r"\bI'm\b|\bI am\b", _pron() + (" are" if _pron() == "they" else " is"), g, flags=re.I)
    g = re.sub(r"\bI'll\b|\bI will\b", _pron() + " will", g, flags=re.I)
    g = re.sub(r"\bI\b", _pron(), g, flags=re.I)
    g = re.sub(r"\bmy\b", _pron("his"), g, flags=re.I)
    g = re.sub(r"\bme\b", _pron("him"), g, flags=re.I)
    return g[:1].upper() + g[1:] + "."


def _think(msgs) -> dict:
    try:
        r = nlu._post("/api/chat", {"model": nlu.model_name(), "messages": msgs, "stream": False,
                                    "format": "json", "keep_alive": nlu.KEEP_ALIVE,
                                    "options": {"temperature": 0.4, "num_predict": 120, "num_ctx": 4096}},
                      timeout=(5, 30))
        d = json.loads(nlu._strip_think(r.json().get("message", {}).get("content", "")) or "{}")
        say = str(d.get("say") or "").strip()
        if say:
            return {"say": say, "end": bool(d.get("end"))}
    except Exception as e:
        print(f"[call] think failed: {e}")
    return {"say": "Okay, I'll let him know. Thank you, bye!", "end": True}


def _say(audio, text, transcript):
    transcript.append(("Hinata", text))
    print(f"[call] Hinata: {text}")
    audio.play(_synth(text))


def _synth(text: str) -> bytes:
    import edge_tts
    hindi = bool(re.search(r"[ऀ-ॿ]", text))
    voice = "hi-IN-SwaraNeural" if hindi else config.NEURAL_VOICE

    async def run():
        buf = bytearray()
        async for chunk in edge_tts.Communicate(text, voice).stream():
            if chunk.get("type") == "audio":
                buf.extend(chunk["data"])
        return bytes(buf)
    return asyncio.run(asyncio.wait_for(run(), timeout=15))


def _stt(pcm16: bytes) -> str | None:
    import speech_recognition as sr
    try:
        audio = sr.AudioData(pcm16, RATE, 2)
        return sr.Recognizer().recognize_google(audio, language=getattr(config, "CALL_LANGUAGE", "en-IN"))
    except Exception:
        return None


def _save(p, transcript, outcome) -> str | None:
    if not transcript:
        return None
    try:
        folder = os.path.join(config.OUTPUT_DIR, "Calls")
        os.makedirs(folder, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M")
        path = os.path.join(folder, f"{stamp}_{re.sub(r'[^A-Za-z0-9]+', '_', p['name'])}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"Call with {p['name']} ({p['number']}) - {dt.datetime.now():%d %b %Y, %H:%M}\n")
            f.write(f"Task: {p['message']}\nResult: {outcome}\n\n")
            for who, text in transcript:
                f.write(f"{who}: {text}\n")
        return path
    except Exception as e:
        print(f"[call] couldn't save transcript: {e}")
        return None


# ---------------------------------------------------------------- audio in / out

class _Audio:
    """Plays Hinata's voice into the call and listens to the other person (speaker loopback)."""

    def __init__(self):
        import pyaudiowpatch as pa
        self.pa = pa.PyAudio()
        mode = str(getattr(config, "CALL_AUDIO", "speakerphone")).lower()
        self.speakerphone = mode != "phonelink"
        if self.speakerphone:
            # no Phone Link needed: phone on loudspeaker, laptop mic listens, laptop speakers talk
            dev = self.pa.get_default_input_device_info()
            self.in_index, self.in_rate, self.in_ch = dev["index"], 16000, 1
            self.out_dev = None
            print(f"[call] speakerphone mode - listening on: {dev['name']}")
        else:
            loop = self.pa.get_default_wasapi_loopback()
            self.in_index = loop["index"]
            self.in_rate = int(loop["defaultSampleRate"])
            self.in_ch = max(1, int(loop["maxInputChannels"]))
            self.out_dev = self._find_output(getattr(config, "CALL_PLAYBACK_DEVICE", ""))
            print(f"[call] Phone Link mode - listening on: {loop['name']}")
        self.noise = 300.0

    def _find_output(self, want):
        if not want:
            return None
        best = None
        for i in range(self.pa.get_device_count()):
            d = self.pa.get_device_info_by_index(i)
            if d.get("maxOutputChannels", 0) > 0 and want.lower() in d["name"].lower():
                api = self.pa.get_host_api_info_by_index(d["hostApi"])["name"]
                if "MME" in api:                       # MME resamples for us
                    return i
                best = best if best is not None else i
        if best is None:
            print(f"[call] '{want}' not found - Hinata will speak from the default speakers "
                  "(install VB-Audio Virtual Cable for a cleaner call)")
        return best

    def play(self, mp3: bytes):
        import miniaudio
        dec = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=24000)
        import pyaudiowpatch as pa
        st = self.pa.open(format=pa.paInt16, channels=1, rate=24000, output=True,
                          output_device_index=self.out_dev)
        try:
            st.write(dec.samples.tobytes())
        finally:
            st.stop_stream()
            st.close()
        time.sleep(0.25)

    def listen(self, max_wait=9.0, max_len=14.0) -> bytes | None:
        """Waits for the other person to speak, records until they pause. 16 kHz mono PCM."""
        import pyaudiowpatch as pa
        chunk = int(self.in_rate * 0.05)
        st = self.pa.open(format=pa.paInt16, channels=self.in_ch, rate=self.in_rate, input=True,
                          input_device_index=self.in_index, frames_per_buffer=chunk)
        frames, talking, quiet, t0 = [], False, 0.0, time.time()
        try:
            while True:
                raw = st.read(chunk, exception_on_overflow=False)
                x = np.frombuffer(raw, dtype=np.int16).reshape(-1, self.in_ch).mean(axis=1)
                level = float(np.sqrt(np.mean(x * x))) if x.size else 0.0
                if not talking:
                    self.noise = self.noise * 0.95 + level * 0.05
                    if level > max(400.0, self.noise * 3):
                        talking, quiet = True, 0.0
                        frames.append(x)
                    elif time.time() - t0 > max_wait:
                        return None
                    continue
                frames.append(x)
                quiet = quiet + 0.05 if level < max(300.0, self.noise * 2) else 0.0
                if quiet > 0.9 or time.time() - t0 > max_wait + max_len:
                    break
        finally:
            st.stop_stream()
            st.close()
        mono = np.concatenate(frames)
        n_out = int(len(mono) * RATE / self.in_rate)          # resample to 16 kHz
        res = np.interp(np.linspace(0, len(mono) - 1, n_out), np.arange(len(mono)), mono)
        return np.clip(res, -32768, 32767).astype(np.int16).tobytes()

    def close(self):
        try:
            self.pa.terminate()
        except Exception:
            pass
