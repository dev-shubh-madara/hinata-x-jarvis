"""
Instant desktop commands - the "hands off the keyboard" set.

    "Hinata, open Notes"            "Hinata, type this is a demo"
    "Hinata, enter"                 "Hinata, new line"
    "Hinata, go to Slack"           "Hinata, select all" / "copy" / "paste" / "undo"

No AI, no hologram, no talking back: the keys go to whatever window you're
in, usually within half a second of your last word.

Listen mode ("Hinata, listen mode") drops the need to say her name: every
command-shaped sentence ("open...", "type...", "enter") runs until you say
"stop listening" or go quiet for a minute. Normal talk around you is
ignored because it doesn't start with a command word.
"""

import re
import time

import config

KEYS = {
    "enter": "enter", "press enter": "enter", "hit enter": "enter", "submit": "enter", "send it": "enter",
    "new line": "shift+enter", "next line": "shift+enter", "line break": "shift+enter",
    "new paragraph": "enter, enter",
    "select all": "ctrl+a", "copy": "ctrl+c", "copy that": "ctrl+c", "copy it": "ctrl+c",
    "paste": "ctrl+v", "paste it": "ctrl+v", "paste that": "ctrl+v", "cut": "ctrl+x", "cut that": "ctrl+x",
    "undo": "ctrl+z", "undo that": "ctrl+z", "redo": "ctrl+y", "save": "ctrl+s", "save it": "ctrl+s",
    "save this": "ctrl+s", "find": "ctrl+f", "print": "ctrl+p",
    "backspace": "backspace", "delete": "delete", "delete that": "ctrl+backspace",
    "delete word": "ctrl+backspace", "delete last word": "ctrl+backspace",
    "delete line": "home, shift+end, backspace", "clear": "ctrl+a, backspace", "clear all": "ctrl+a, backspace",
    "tab": "tab", "escape": "esc", "space": "space",
    "new tab": "ctrl+t", "close tab": "ctrl+w", "next tab": "ctrl+tab", "previous tab": "ctrl+shift+tab",
    "reopen tab": "ctrl+shift+t", "refresh": "f5", "reload": "f5", "go back": "alt+left", "go forward": "alt+right",
    "scroll down": "page down", "scroll up": "page up", "top": "ctrl+home", "go to top": "ctrl+home",
    "bottom": "ctrl+end", "go to bottom": "ctrl+end", "zoom in": "ctrl+=", "zoom out": "ctrl+-",
    "close this": "alt+f4", "close window": "alt+f4", "close it": "alt+f4",
    "new window": "ctrl+n", "new file": "ctrl+n", "new chat": "ctrl+n", "new note": "ctrl+n",
    "switch window": "alt+tab", "last window": "alt+tab", "full screen": "f11",
    "bold": "ctrl+b", "italic": "ctrl+i", "underline": "ctrl+u",
    "snap left": "windows+left", "snap right": "windows+right",
}

# what can start a command in listen mode (no "Hinata" needed)
COMMAND_START = re.compile(
    r"^(open|launch|start|close|quit|type|write|enter|press|hit|new|next|previous|go|switch|select|copy|paste|"
    r"cut|undo|redo|save|delete|backspace|clear|scroll|search|google|play|pause|resume|stop|mute|unmute|volume|"
    r"brightness|minimi[sz]e|maximi[sz]e|snap|zoom|refresh|reload|tab|escape|bold|italic|underline|send|"
    r"submit|find|show|hide|lock|take|screenshot)\b", re.I)

_FILLER = re.compile(r"^(?:please |now |and |then |ok(?:ay)? |so )+|(?: please| now| for me)$", re.I)


def normalize(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip().strip(".!?,")).lower()
    return _FILLER.sub("", t).strip()


def match(t: str, raw: str):
    """A reply if this is an instant command, else None. t = lowercased text, raw = as spoken."""
    t = normalize(_glue(t))
    rawn = re.sub(r"^\s*(?:please |now |and |then |ok(?:ay)? |so )+", "", _glue((raw or "").strip()), flags=re.I)
    if t in KEYS:
        return press(KEYS[t])
    if (m := re.fullmatch(r"(?:press|hit) (\w[\w ]*?) (\d{1,2}) times", t)) and m.group(1) in KEYS:
        return press(", ".join([KEYS[m.group(1)]] * int(m.group(2))))
    if (m := re.fullmatch(r"(?:type|dictate)(?: this:| that:)?:? (.+)", t, re.S)):
        body = re.sub(r"^(?:type|dictate)(?: this:| that:)?:?\s+", "", rawn.strip(), flags=re.I) or m.group(1)
        body, then_enter = _split_enter(body)
        r = type_fast(spoken_punctuation(body))
        if then_enter:
            press("enter")
        return r
    if (m := re.fullmatch(r"(?:go to|switch to|focus|bring up|jump to) (.+?)(?: window| app)?", t)):
        return focus(m.group(1))
    return None


_SPOKEN = [(r"\s*(?:full stop|period)$", "."), (r"\s*question mark$", "?"), (r"\s*exclamation(?: mark)?$", "!"),
           (r"\s*comma$", ","), (r"\s*colon$", ":")]


def spoken_punctuation(body: str) -> str:
    """Speech-to-text puts a full stop on every sentence; that one isn't typed ("?" and "!" are kept,
    they only appear when you really asked or exclaimed). Say "full stop", "comma"... to add one."""
    body = body.rstrip()
    if body.endswith(".") and not body.endswith(".."):
        body = body[:-1].rstrip()
    for pat, mark in _SPOKEN:
        if re.search(pat, body, re.I):
            return re.sub(pat, mark, body, flags=re.I)
    return body


def _glue(text: str) -> str:
    """Speech-to-text sometimes writes 'Type-H, ...' or 'Type: ...' - make it 'Type H, ...'."""
    return re.sub(r"^(\s*(?:type|dictate))[-:,]+\s*", r"\1 ", text, flags=re.I)


def _split_enter(body: str):
    """'hello there and press enter' -> ('hello there', True)"""
    m = re.search(r"[,.]?\s+(?:and )?(?:press |hit )?(?:enter|send it)[.!]?$", body, re.I)
    if m and len(body) > m.end() - m.start():
        return body[:m.start()], True
    return body, False


# ---------------------------------------------------------------- keys + typing

def press(combo: str) -> str:
    import keyboard
    for step in [c.strip() for c in combo.split(",") if c.strip()]:
        keyboard.send(step)
        time.sleep(0.03)
    return "Done."


def type_fast(text: str) -> str:
    """Short text is typed; long text is pasted in one go (instant) and the clipboard put back."""
    text = text.strip()
    if not text:
        return "What should I type?"
    if len(text) <= 40:
        import keyboard
        keyboard.write(text, delay=0.002)
        return "Typed it."
    try:
        import pyperclip
        old = None
        try:
            old = pyperclip.paste()
        except Exception:
            pass
        pyperclip.copy(text)
        press("ctrl+v")
        time.sleep(0.15)
        if old is not None:
            pyperclip.copy(old)
    except Exception:
        import keyboard
        keyboard.write(text, delay=0.002)
    return "Typed it."


# ---------------------------------------------------------------- windows

def _windows():
    """[(hwnd, title, exe)] of visible top-level windows."""
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not u32.IsWindowVisible(hwnd) or u32.GetWindow(hwnd, 4):        # skip owned popups
            return True
        n = u32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(hwnd, buf, n + 1)
        out.append((hwnd, buf.value, _exe_name(hwnd)))
        return True

    u32.EnumWindows(cb, 0)
    return out


def _exe_name(hwnd) -> str:
    try:
        import ctypes
        import psutil
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return psutil.Process(pid.value).name().lower().replace(".exe", "")
    except Exception:
        return ""


ALIASES = {"vs code": "code", "vscode": "code", "visual studio code": "code", "notes": "notepad",
           "word": "winword", "excel": "excel", "powerpoint": "powerpnt", "terminal": "windowsterminal",
           "file explorer": "explorer", "files": "explorer", "edge": "msedge", "whatsapp": "whatsapp",
           "open code": "opencode", "chrome": "chrome", "browser": "chrome"}


def best_window(name: str, windows):
    """Picks the window whose title or program best matches what you said."""
    q = name.lower().strip()
    exe_q = ALIASES.get(q, q.replace(" ", ""))
    best, score = None, 0.0
    for hwnd, title, exe in windows:
        tl = title.lower()
        s = 0.0
        if exe and (exe == exe_q or exe.startswith(exe_q)):
            s = 3
        elif q in tl:
            s = 2 + (0.5 if tl.startswith(q) or tl.endswith(q) else 0)
        elif all(w in tl for w in q.split()):
            s = 1.5
        elif exe_q and exe_q in tl.replace(" ", ""):
            s = 1
        if s > score:
            best, score = hwnd, s
    return best


def focus(name: str) -> str:
    """Brings a running app/window to the front; opens it if it isn't running."""
    try:
        hwnd = best_window(name, _windows())
    except Exception:
        hwnd = None
    if hwnd:
        _bring_front(hwnd)
        return f"{name.title()}."
    import pc_actions
    return pc_actions.open_target(name)


def _bring_front(hwnd):
    import ctypes
    u32 = ctypes.windll.user32
    if u32.IsIconic(hwnd):
        u32.ShowWindow(hwnd, 9)                         # SW_RESTORE
    # Windows only lets the foreground app hand over focus; a tap of Alt makes us "foreground"
    u32.keybd_event(0x12, 0, 0, 0)
    u32.keybd_event(0x12, 0, 2, 0)
    u32.SetForegroundWindow(hwnd)


# ---------------------------------------------------------------- listen mode

_listen = {"until": 0.0}


def listen_mode(on: bool):
    _listen["until"] = time.time() + _idle() if on else 0.0


def _idle() -> float:
    return 60 * float(getattr(config, "LISTEN_MODE_IDLE_MINUTES", 2))


def in_listen_mode() -> bool:
    return time.time() < _listen["until"]


def keep_alive():
    """Each command in listen mode pushes the idle cut-off back."""
    if in_listen_mode():
        _listen["until"] = time.time() + _idle()


def looks_like_command(text: str) -> bool:
    t = normalize(text)
    return bool(t) and (t in KEYS or bool(COMMAND_START.match(t)))


# ---------------------------------------------------------------- what still gets spoken

_WRONG = re.compile(r"^(?:sorry|i couldn'?t|i can'?t|i don'?t|which|what should|there'?s no|no |it failed|failed|"
                    r"error|the \S+ plug-in|i'?m still)|\b(?:not found|didn'?t work|isn'?t running|couldn'?t find|"
                    r"failed|not installed)\b", re.I)


def needs_voice(reply: str) -> bool:
    """In background mode a finished action is silent; problems and questions are still spoken."""
    r = (reply or "").strip()
    return bool(r) and (bool(_WRONG.search(r)) or r.endswith("?"))
