"""
Agent cursor - the real mouse and keyboard, with a glowing Hinata cursor on top.

Every click glides there smoothly (the real pointer moves with it), shows a
short label of what she's doing, ripples on the click, then does the real
click. Works without the visual too (AGENT_CURSOR = False, or not on Windows).

    import agent_cursor as ac
    ac.click(640, 410, "Opening Settings")
    ac.type_text("hello")
    ac.done()

Esc stops a running job: stopped() turns True and the agent ends its loop.
"""

import json
import math
import os
import subprocess
import sys
import threading
import time

import config

_lock = threading.RLock()
_proc = {"p": None}
_stop = {"flag": False, "hooked": False}
WIN = sys.platform == "win32"


# ---------------------------------------------------------------- the visual

def _send(obj):
    if not getattr(config, "AGENT_CURSOR", True):
        return
    with _lock:
        p = _proc["p"]
        if p is None or p.poll() is not None:
            try:
                here = os.path.dirname(os.path.abspath(__file__))
                p = subprocess.Popen([sys.executable, "-u", os.path.join(here, "cursor_proc.py")],
                                     stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                _proc["p"] = p
            except Exception as e:
                print(f"[cursor] visual cursor unavailable: {e}")
                return
        try:
            p.stdin.write(json.dumps(obj) + "\n")
            p.stdin.flush()
        except Exception:
            _proc["p"] = None


def label(text: str):
    _send({"op": "label", "text": text})


def done(text: str = ""):
    """Hide the cursor (after a short final label)."""
    if text:
        label(text)
        time.sleep(0.7)
    _send({"op": "hide"})


def quit_visual():
    _send({"op": "quit"})


# ---------------------------------------------------------------- stop with Esc

def _hook_esc():
    if _stop["hooked"]:
        return
    try:
        import keyboard
        keyboard.on_press_key("esc", lambda _e: _stop.update(flag=True))
        _stop["hooked"] = True
    except Exception:
        pass


def begin():
    """Call at the start of a job: clears the stop flag and arms Esc."""
    _stop["flag"] = False
    _hook_esc()
    x, y = position()
    _send({"op": "jump", "x": x, "y": y})


def stop():
    _stop["flag"] = True


def stopped() -> bool:
    return _stop["flag"]


# ---------------------------------------------------------------- real input

def position():
    if WIN:
        import ctypes

        class P(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = P()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y
    return 0, 0


def _set_pos(x, y):
    if WIN:
        import ctypes
        ctypes.windll.user32.SetCursorPos(int(x), int(y))


def _mouse(flags):
    if WIN:
        import ctypes
        ctypes.windll.user32.mouse_event(flags, 0, 0, 0, 0)


def _ease(t):
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def glide_ms(x0, y0, x1, y1) -> int:
    dist = math.hypot(x1 - x0, y1 - y0)
    speed = max(0.2, float(getattr(config, "AGENT_CURSOR_SPEED", 1.0) or 1.0))
    return int(min(900, 260 + dist * 0.45) / speed)


def move(x, y, text: str | None = None):
    """Glide the real pointer (and the glowing cursor) to x, y."""
    x0, y0 = position()
    ms = glide_ms(x0, y0, x, y)
    msg = {"op": "move", "x": x, "y": y, "ms": ms}
    if text is not None:
        msg["label"] = text
    _send(msg)
    if not WIN:
        return
    steps = max(1, ms // 8)
    t0 = time.perf_counter()
    for i in range(1, steps + 1):
        e = _ease(i / steps)
        arc = math.sin(math.pi * e) * min(60, math.hypot(x - x0, y - y0) * 0.08)
        _set_pos(x0 + (x - x0) * e, y0 + (y - y0) * e - arc)
        target = t0 + i * ms / steps / 1000
        delay = target - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
    _set_pos(x, y)


def click(x, y, text: str | None = None, double: bool = False, right: bool = False):
    move(x, y, text)
    time.sleep(0.06)
    _send({"op": "pulse"})
    down, up = (0x0008, 0x0010) if right else (0x0002, 0x0004)
    for _ in range(2 if double else 1):
        _mouse(down)
        time.sleep(0.03)
        _mouse(up)
        time.sleep(0.06)
    time.sleep(0.12)


def scroll(amount: int, text: str | None = None):
    """amount > 0 scrolls up, < 0 down (in wheel notches)."""
    if text:
        label(text)
    if WIN:
        import ctypes
        for _ in range(abs(int(amount))):
            ctypes.windll.user32.mouse_event(0x0800, 0, 0, 120 if amount > 0 else -120, 0)
            time.sleep(0.04)


def type_text(text: str, show: str | None = None):
    """Types text into the focused field. Long or non-English text is pasted (exact and fast)."""
    label(show or ("Typing: " + (text if len(text) < 22 else text[:20] + "...")))
    import keyboard
    if len(text) > 60 or any(ord(ch) > 127 for ch in text):
        try:
            import pyperclip
            old = None
            try:
                old = pyperclip.paste()
            except Exception:
                pass
            pyperclip.copy(text)
            time.sleep(0.05)
            keyboard.send("ctrl+v")
            time.sleep(0.25)
            if old is not None:
                threading.Timer(1.5, lambda: pyperclip.copy(old)).start()
            return
        except Exception:
            pass
    keyboard.write(text, delay=0.012)


def key(combo: str, show: str | None = None):
    if show:
        label(show)
    import keyboard
    keyboard.send(combo)
    time.sleep(0.12)


def center(rect):
    """(left, top, right, bottom) -> centre point."""
    l, t, r, b = rect
    return (l + r) // 2, (t + b) // 2
