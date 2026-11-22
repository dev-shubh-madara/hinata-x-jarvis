"""
Hinata X Helper - a fast, voice-controlled AI assistant for your Windows PC
and Android phone, with a real-time 3D holographic HUD.

    Ctrl+Shift+H  -> speak a command
    Ctrl+Shift+J      -> type a command
    Right-click the orb to quit.

Flow: hotkey -> hologram assembles -> listen -> instant pattern or local AI
agent runs the job -> she answers out loud -> hologram dissolves.
"""

import ctypes
import importlib
import sys
import threading
import time
import traceback

try:
    sr = importlib.import_module("speech_recognition")
except ImportError:
    sr = None

import config
import commands
import hotkey_listener
import quick
import nlu
import phone_control
import phone_pair
import session
import system_info
import tts_engine
from overlay import MicOverlay
from tts_engine import speak


class _Tee:
    """Mirror console output into hinata.log (handy for bug reports)."""
    def __init__(self, stream, log):
        self.stream, self.log = stream, log

    def write(self, data):
        for s in (self.stream, self.log):
            try:
                s.write(data)
                s.flush()
            except Exception:
                pass

    def flush(self):
        pass


def _start_log():
    import os
    try:
        log = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "hinata.log"),
                   "w", encoding="utf-8", buffering=1)
        sys.stdout = _Tee(sys.__stdout__, log)
        sys.stderr = _Tee(sys.__stderr__, log)
    except OSError:
        pass


def _dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)      # per-monitor, sharpest
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _brain_status(overlay) -> bool:
    ok = nlu.available(force=True)
    overlay.set_info("AI", (nlu.model_name() or "").upper()[:18] if ok else "OFFLINE")
    return ok


def _phone_status(overlay):
    if phone_control.adb_path() and phone_control.connected_devices():
        overlay.set_info("PHONE", "CONNECTED")
    else:
        overlay.set_info("PHONE", "PAIRED" if phone_pair._load() else "NOT PAIRED")


def _run(overlay, text: str):
    """Executes one command with live captions and timing."""
    print(f"[You] {text}")
    overlay.set_caption(you=text, reply="")
    overlay.set_state("thinking")
    t0 = time.perf_counter()
    if not nlu.available():
        _brain_status(overlay)
    first = {"t": None}

    def stream(sentence):                   # she starts talking on the first sentence
        if first["t"] is None:
            first["t"] = (time.perf_counter() - t0) * 1000
            print(f"[time] first words after {first['t']:.0f} ms")
            overlay.set_state("speaking")
        overlay.set_caption(reply=sentence)
        speak(sentence, wait=False)

    commands.set_streamer(stream)
    try:
        reply = commands.handle(text)
    finally:
        commands.set_streamer(None)
    outcome = commands.last_outcome()
    overlay.set_info("AI", (nlu.model_name() or "").upper()[:18] or "OFFLINE")   # live model name          # 'chat' | 'confirm' | 'action'
    ms = (time.perf_counter() - t0) * 1000
    print(f"[time] {ms:.0f} ms  ->  {outcome}")
    if outcome == "action":
        overlay.collapse()                     # work was done - get out of the way
    overlay.set_caption(reply=reply or "", ms=first["t"] or ms)
    if reply and commands.already_spoken():
        tts_engine.wait_idle()               # already said while streaming - just let her finish
    elif reply and outcome == "action" and getattr(config, "SILENT_ACTIONS", False) and not quick.needs_voice(reply):
        tts_engine.tick()                    # background mode: the work is the answer
    elif reply:
        overlay.set_state("speaking")
        speak(reply)
    _phone_status(overlay)
    return outcome


def voice_loop(overlay: MicOverlay):
    recognizer = mic = None
    fast = config.STT_ENGINE == "fast" and _fast_mic(overlay)
    if not fast and sr is None:
        overlay.set_info("MIC", "NO SPEECHRECOGNITION")
    elif not fast:
        try:
            recognizer = sr.Recognizer()
            mic = sr.Microphone()
            hotkey_listener.calibrate(recognizer, mic)
            overlay.set_info("MIC", "READY")
        except Exception as e:
            print(f"[main] Microphone problem: {e}")
            overlay.set_info("MIC", "NOT FOUND")
            recognizer = mic = None

    hotkey_listener.install_hotkeys()
    if fast:
        import wake
        quick.on_awake_change(overlay.awake_changed)     # slim AWAKE strip while "Hey Hinata" mode is on
        if wake.start(hotkey_listener.fire_wake, is_speaking=tts_engine.is_speaking):
            overlay.set_info("WAKE", "SAY HINATA")
    brain_ok = _brain_status(overlay)
    _phone_status(overlay)
    greeting = f"{config.ASSISTANT_NAME} is online."
    if not brain_ok:
        greeting += " My AI brain is offline, so I'll handle the basics only."
    speak(greeting)

    while True:
        kind = hotkey_listener.wait_for_trigger()
        try:
            _pause_wake(True)
            if kind == "voice" and recognizer is None and not fast:
                overlay.force_expand()
                overlay.set_state("speaking")
                speak(f"I can't hear you - no microphone. Press {config.TYPE_HOTKEY.replace('+', ' ')} to type instead.")
                continue
            why = session.run_session(
                overlay=overlay,
                typed=(kind == "type"),
                listen=lambda timeout: hotkey_listener.capture_command(recognizer, mic, timeout),
                ask_command=overlay.ask_command,
                run_command=lambda text: _run(overlay, text),
                speak=speak,
                chime=(lambda: None) if hotkey_listener.has_first_text() else tts_engine.chime,
                drain=hotkey_listener.drain,
                is_end=commands.is_end_phrase,
                is_rest=quick.is_rest,
                on_rest=lambda: quick.listen_mode(False),
                # woken by her name: one command, then back to resting (no open mic afterwards).
                # The hotkey keeps the old back-and-forth conversation.
                conversation_mode=config.CONVERSATION_MODE and not hotkey_listener.from_wake(),
                first_timeout=config.LISTEN_TIMEOUT,
                follow_timeout=config.CONVO_LISTEN_TIMEOUT,
                idle_seconds=config.CONVO_IDLE_SECONDS,
            )
            print(f"[session] ended: {why}")
        except Exception as e:
            traceback.print_exc()
            overlay.set_state("speaking")
            speak(f"Something went wrong: {e}")
        finally:
            overlay.collapse()
            _pause_wake(False)


def _fast_mic(overlay) -> bool:
    """Opens the always-on microphone used by the fast speech engine and the wake word."""
    import fast_stt
    if fast_stt.mic().start():
        overlay.set_info("MIC", "ALWAYS ON")
        return True
    print(f"[main] fast speech unavailable ({fast_stt.mic().error}) - using Google speech")
    config.STT_ENGINE = "google"
    return False


def _pause_wake(on: bool):
    """The wake word sleeps while a session is listening, so a command isn't heard twice."""
    try:
        import wake
        wake.pause() if on else wake.resume()
    except Exception:
        pass


def _warm_up():
    """Everything slow happens here, in the background, so commands are instant later."""
    system_info.preload()
    nlu.warm_up()
    tts_engine.preload()
    hotkey_listener.preload()
    try:
        import kokoro_tts
        import file_index
        kokoro_tts.warm_up()
        import voice_id
        voice_id.warm_up()
        if not voice_id.enrolled():
            print("[voice] voice lock not set up yet - say 'Hinata, learn my voice'")
        file_index.start_background()            # all-drives index, quietly, at low priority
    except Exception as e:
        print(f"[warmup] {e}")
    phone_pair.auto_reconnect_background()
    try:
        import vision
        vision.ensure_model()
    except Exception as e:
        print(f"[vision] {e}")


_instance_lock = None


def _already_running() -> bool:
    """Only one Hinata at a time - autostart + a manual start would fight over the hotkeys."""
    global _instance_lock
    try:
        k32 = ctypes.windll.kernel32
        _instance_lock = k32.CreateMutexW(None, False, "Local\\HinataXHelper.SingleInstance")
        return k32.GetLastError() == 183          # ERROR_ALREADY_EXISTS
    except Exception:
        return False


def main():
    if _already_running():
        print("Hinata X Helper is already running - press Ctrl+Shift+H to talk to her.")
        return
    _start_log()
    try:
        import hud_proc
        hud_proc.no_throttle()          # keep Windows from putting Hinata in Efficiency mode
    except Exception:
        pass
    if sys.platform != "win32":
        print("Hinata X Helper controls Windows - run it on a Windows PC.")
    _dpi_aware()
    overlay = MicOverlay(assistant_name=config.ASSISTANT_NAME)
    commands.set_overlay(overlay)
    commands.set_speaker(lambda msg: speak(msg, wait=False))
    threading.Thread(target=_warm_up, daemon=True, name="warmup").start()
    threading.Thread(target=voice_loop, args=(overlay,), daemon=True, name="voice").start()
    overlay.start()


if __name__ == "__main__":
    main()
