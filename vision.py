"""
Screen vision - Hinata looks at your screen and answers.

    "what is this video about?"      "how do I export this?"
    "what does this error mean?"     "read this for me"

Takes a screenshot, shrinks it, and asks a LOCAL vision model in Ollama
(no cloud, no key). The active window's title is added too - for a YouTube
video that alone often says what it's about.

Vision models that work (auto-detected, smallest first is fastest):
    ollama pull qwen2.5vl:3b      (~3 GB, recommended for a 6 GB GPU)
    ollama pull gemma3:4b         (~3.3 GB)
    ollama pull llava:7b
If none is installed, Hinata downloads VISION_MODEL in the background the
first time you ask.
"""

import base64
import ctypes
import io
import threading

import config
import nlu

VISION_HINTS = ("vl", "llava", "vision", "gemma3", "minicpm-v", "moondream", "bakllava", "granite3.2-vision")
_pull = {"running": False}


def _vision_model() -> str | None:
    wanted = (getattr(config, "VISION_MODEL", "") or "").strip()
    try:
        names = nlu.installed_models()
    except Exception:
        return None
    for n in names:
        if wanted and (n == wanted or n.startswith(wanted)):
            return n
    found = [n for n in names if any(h in n.lower() for h in VISION_HINTS)]
    found.sort(key=lambda n: ("3b" not in n and "4b" not in n, n))   # small = fast
    return found[0] if found else None


def _start_pull(model: str):
    if _pull["running"]:
        return
    _pull["running"] = True

    def run():
        try:
            print(f"[vision] downloading {model} ...")
            nlu._post("/api/pull", {"model": model, "stream": False}, timeout=(5, 3600))
            print(f"[vision] {model} ready")
        except Exception as e:
            print(f"[vision] download failed: {e}")
        finally:
            _pull["running"] = False
    threading.Thread(target=run, daemon=True, name="vision-pull").start()


def ensure_model():
    """Startup: download the vision model in the background if it's missing."""
    try:
        if not nlu.available(force=True):
            return
        have = _vision_model()
        if have:
            print(f"[vision] ready - {have}")
        else:
            _start_pull(getattr(config, "VISION_MODEL", "") or "qwen2.5vl:3b")
    except Exception as e:
        print(f"[vision] check failed: {e}")


def active_window_title() -> str:
    try:
        u = ctypes.windll.user32
        h = u.GetForegroundWindow()
        n = u.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, buf, n + 1)
        return buf.value
    except Exception:
        return ""


def _screenshot_b64(max_side: int = 1344) -> str:
    from PIL import ImageGrab
    img = ImageGrab.grab(all_screens=False).convert("RGB")
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=80)
    return base64.b64encode(out.getvalue()).decode()


def look(question: str, hide_overlay=None) -> str:
    """Answers a question about what's on screen right now."""
    if not nlu.available():
        return "My AI brain is offline, so I can't look at the screen right now."
    model = _vision_model()
    if not model:
        want = getattr(config, "VISION_MODEL", "") or "qwen2.5vl:3b"
        _start_pull(want)
        return (f"I need a vision model to see your screen. I'm downloading {want} now - "
                f"it takes a few minutes, then ask me again.")
    if hide_overlay:
        hide_overlay()                       # don't photograph the hologram itself
    title = active_window_title()
    try:
        img = _screenshot_b64()
    except Exception as e:
        return f"I couldn't take a screenshot: {e}"
    name = getattr(config, "USER_TITLE", "") or "the user"
    prompt = (f"This is a screenshot of the user's screen. Active window title: \"{title}\".\n"
              f"Question from {name}: {question or 'What is on my screen?'}\n"
              "Answer in plain spoken English, 1-3 short sentences, no markdown. If they ask how to do "
              "something in the app shown, give the exact clicks (menu names and where they are on screen).")
    try:
        r = nlu._post("/api/chat", {
            "model": model, "stream": False, "keep_alive": "10m",
            "messages": [{"role": "user", "content": prompt, "images": [img]}],
            "options": {"temperature": 0.2, "num_predict": 220, "num_ctx": 4096},
        }, timeout=(5, 120))
        r.raise_for_status()
        ans = nlu._strip_think(r.json().get("message", {}).get("content", "")).strip()
    except Exception as e:
        return f"I couldn't read the screen: {e}"
    print(f"[vision] {model}: {ans[:160]}")
    return ans or "I looked, but I'm not sure what that is."
