"""
Hinata Motion - AI motion studio.

"make a motion video about my startup Voderon"  ->  a team of agents builds it:

  Director   writes the storyboard: scenes, headlines, mascots, colours, voice lines
  Designer   checks the style - colours, sizes, mascots - and fixes anything broken
  Voice      records each voice line with the neural voice
  Animator   times every scene to its voice line
  Reviewer   opens the frames and shrinks any text that would spill out
  Renderer   draws every frame in a hidden browser and encodes the MP4
  Mixer      lays the voice (and your music) under the picture

The studio (http://127.0.0.1:8740) shows it all live: preview, timeline, the
code of each scene, easing curve, sliders, mascots - and you can edit any of it
by hand or by voice ("make scene 2 red", "make it faster"), then render again.
Videos go to D:\\Hinata_Output\\Motion.
"""

import json
import mimetypes
import os
import re
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import config

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "motion")
ROOT = os.path.join(config.OUTPUT_DIR, "Motion")
TYPES = ("title", "statement", "big_number", "list", "phone", "split", "outro")
MASCOTS = ("blob", "bot", "cloud", "drop", "box", "none")
MOODS = ("happy", "wow", "wave", "think")
SIZES = {"vertical": (1080, 1920), "wide": (1920, 1080), "square": (1080, 1080)}
AGENTS = ("Director", "Designer", "Voice", "Animator", "Reviewer", "Renderer", "Mixer")
PALETTES = [
    {"bg": "#f6f1e7", "fg": "#17131f", "accent": "#c6f432", "accent2": "#7b5cff"},
    {"bg": "#fff4ec", "fg": "#1d1a24", "accent": "#ffcf3f", "accent2": "#ff5a5f"},
    {"bg": "#eef4ff", "fg": "#0f1730", "accent": "#7ce0c3", "accent2": "#3d6bff"},
    {"bg": "#14121c", "fg": "#f5f2ff", "accent": "#c6f432", "accent2": "#ff7ac6"},
    {"bg": "#fdf7ff", "fg": "#221433", "accent": "#ffb3e6", "accent2": "#8f5bff"},
]

_status: dict[str, dict] = {}
_lock = threading.RLock()
_server = {"httpd": None}


# ---------------------------------------------------------------- projects

def _dir(pid: str) -> str:
    return os.path.join(ROOT, re.sub(r"[^A-Za-z0-9_-]", "", pid))


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "video").lower()).strip("-")[:32] or "video"
    return f"{s}-{time.strftime('%m%d-%H%M%S')}"


def load(pid: str) -> dict | None:
    try:
        with open(os.path.join(_dir(pid), "project.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save(project: dict) -> dict:
    project = validate(project)
    d = _dir(project["id"])
    os.makedirs(os.path.join(d, "audio"), exist_ok=True)
    project["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(d, "project.json"), "w", encoding="utf-8") as f:
        json.dump(project, f, indent=1, ensure_ascii=False)
    return project


def projects() -> list[dict]:
    out = []
    try:
        for pid in os.listdir(ROOT):
            p = load(pid)
            if p:
                out.append({"id": pid, "title": p.get("title", pid), "updated": p.get("updated", ""),
                            "video": os.path.exists(os.path.join(_dir(pid), "video.mp4"))})
    except OSError:
        pass
    return sorted(out, key=lambda x: x["updated"], reverse=True)


def latest_id():
    ps = projects()
    return ps[0]["id"] if ps else None


# ---------------------------------------------------------------- status (what the studio shows)

def status(pid: str) -> dict:
    with _lock:
        return _status.setdefault(pid, {"agents": {a: "idle" for a in AGENTS}, "log": [],
                                        "render": {"state": "idle", "progress": 0.0}, "busy": False})


def log(pid: str, agent: str, text: str, state: str = "working"):
    st = status(pid)
    with _lock:
        st["agents"][agent] = state
        st["log"].append({"t": time.strftime("%H:%M:%S"), "agent": agent, "text": text})
        del st["log"][:-80]
    print(f"[motion] {agent}: {text}")


# ---------------------------------------------------------------- validation (Designer)

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _hex(v, default):
    v = str(v or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{3}", v):
        v = "#" + "".join(ch * 2 for ch in v[1:])
    return v if _HEX.match(v) else default


def _num(v, default, lo, hi):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def validate(p: dict) -> dict:
    """Makes any project safe to play: known types, real colours, sane durations."""
    p = dict(p or {})
    p["id"] = p.get("id") or _slug(p.get("title", "video"))
    p["title"] = str(p.get("title") or "Untitled")[:80]
    p["size"] = p.get("size") if p.get("size") in SIZES else getattr(config, "MOTION_SIZE", "vertical")
    pal = PALETTES[sum(map(ord, p["title"])) % len(PALETTES)]
    st = p.get("style") if isinstance(p.get("style"), dict) else {}
    p["style"] = {k: _hex(st.get(k), pal[k]) for k in ("bg", "fg", "accent", "accent2")}
    p["style"]["font"] = re.sub(r"[^A-Za-z0-9 ]", "", str(st.get("font") or ""))[:40]
    p["speed"] = _num(p.get("speed"), 1.0, 0.5, 2.0)
    e = p.get("ease")
    p["ease"] = [float(x) for x in e] if isinstance(e, list) and len(e) == 4 and all(
        isinstance(x, (int, float)) for x in e) else [0.22, 1, 0.36, 1]
    scenes = []
    for i, s in enumerate(p.get("scenes") or []):
        if not isinstance(s, dict):
            continue
        s = dict(s)
        s["type"] = s.get("type") if s.get("type") in TYPES else "title"
        s["headline"] = str(s.get("headline") or "")[:140]
        s["sub"] = str(s.get("sub") or "")[:200]
        s["voice"] = str(s.get("voice") or "")[:400]
        s["duration"] = round(_num(s.get("duration"), 3.5, 1.2, 15), 2)
        s["mascot"] = s.get("mascot") if s.get("mascot") in MASCOTS else "none"
        s["mascot_color"] = _hex(s.get("mascot_color"), ["#ff6b6b", "#ff9f43", "#5f8bff", "#3ecf8e", "#c56cf0"][i % 5])
        s["mood"] = s.get("mood") if s.get("mood") in MOODS else "happy"
        s["mascot_scale"] = _num(s.get("mascot_scale"), 1.0, 0.4, 2.0)
        for k in ("mascot_x", "mascot_y"):
            if s.get(k) is not None:
                s[k] = _num(s.get(k), 6, -20, 90)
        if s.get("ease") is not None and not (isinstance(s["ease"], list) and len(s["ease"]) == 4):
            s.pop("ease")
        if s.get("bg"):
            s["bg"] = _hex(s["bg"], "")
            if not s["bg"]:
                s.pop("bg")
        if s["type"] == "big_number":
            s["number"] = re.sub(r"[^0-9.]", "", str(s.get("number") or "")) or "100"
            s["prefix"] = str(s.get("prefix") or "")[:6]
            s["suffix"] = str(s.get("suffix") or "")[:8]
        if s["type"] == "list":
            s["items"] = [str(x)[:60] for x in (s.get("items") or []) if str(x).strip()][:5] or ["First point", "Second point"]
        if s["type"] == "phone":
            msgs = []
            for m in s.get("messages") or []:
                if isinstance(m, dict) and str(m.get("text") or "").strip():
                    msgs.append({"from": "me" if m.get("from") == "me" else "them", "text": str(m["text"])[:90]})
                elif isinstance(m, str) and m.strip():
                    msgs.append({"from": "them" if len(msgs) % 2 == 0 else "me", "text": m[:90]})
            s["messages"] = msgs[:5] or [{"from": "them", "text": "Hey!"}, {"from": "me", "text": "Hi there"}]
            s["chat_name"] = str(s.get("chat_name") or "Chat")[:24]
        if s.get("transition") not in ("fade", "slide", "zoom", "wipe"):
            s.pop("transition", None)
        if not s["headline"] and s["type"] not in ("phone",):
            s["headline"] = p["title"]
        scenes.append(s)
    p["scenes"] = scenes[:14] or [{"type": "title", "headline": p["title"], "sub": "", "voice": "", "duration": 3,
                                   "mascot": "blob", "mascot_color": "#ff6b6b", "mood": "wave", "mascot_scale": 1}]
    if p.get("music") and not os.path.isfile(str(p["music"])):
        p["music"] = ""
    return p


# ---------------------------------------------------------------- Director

DIRECTOR = (
    "You are the director of a short animated explainer/ad, like the ones agencies make with cute mascots and bold "
    "kinetic type. Plan it as JSON only:\n"
    '{"title": "...", "size": "vertical|wide|square", '
    '"style": {"bg": "#hex", "fg": "#hex", "accent": "#hex", "accent2": "#hex"}, '
    '"scenes": [ {"type": "title|statement|big_number|list|phone|split|outro", "headline": "...", "sub": "...", '
    '"number": "400", "prefix": "Rs ", "suffix": "", "items": ["..."], "chat_name": "...", '
    '"messages": [{"from": "them|me", "text": "..."}], "mascot": "blob|bot|cloud|drop|box|none", '
    '"mascot_color": "#hex", "mood": "happy|wow|wave|think", "voice": "what the narrator says", "duration": 3.5} ]}\n'
    "Rules: 5 to 8 scenes. Start with a hook (statement or big_number), end with an outro that has a call to action "
    "in sub. Headlines: max 7 words, punchy; wrap the 1-2 most important words in [square brackets] to highlight "
    "them. Voice lines: natural spoken English, 6-16 words each, matching the scene. Use a mascot in most scenes, "
    "same mascot kind throughout for a consistent character. Light, friendly colours unless asked otherwise; "
    "bg and fg must contrast strongly. Durations 2.5-5 seconds. Only the fields each type needs."
)


def _size_from(text: str):
    t = text.lower()
    if re.search(r"\b(wide|landscape|youtube video|16 ?: ?9|horizontal)\b", t):
        return "wide"
    if re.search(r"\b(square|1 ?: ?1|instagram post|feed post)\b", t):
        return "square"
    if re.search(r"\b(reel|short|shorts|vertical|story|tiktok|9 ?: ?16)\b", t):
        return "vertical"
    return None


def _fallback(brief: str) -> dict:
    topic = re.sub(r"^(?:make|create|generate|build)?\s*(?:a|an|me a)?\s*(?:motion|animated|explainer|promo|ad)?\s*"
                   r"(?:video|reel|animation|ad)?\s*(?:about|for|on|of)?\s*", "", brief, flags=re.I).strip() or brief
    t = topic[:1].upper() + topic[1:]
    return {"title": t[:60], "scenes": [
        {"type": "statement", "headline": f"Meet [{t[:40]}]", "voice": f"Meet {t}.", "mascot": "blob", "mood": "wave"},
        {"type": "split", "headline": "Made to make life [easier]", "sub": "Let me show you!", "mascot": "blob",
         "voice": "It's made to make your life easier."},
        {"type": "list", "headline": "Why people love it", "items": ["Fast", "Simple", "Made for you"], "mascot": "blob",
         "voice": "It's fast, simple, and made for you."},
        {"type": "outro", "headline": f"[{t[:30]}]", "sub": "Try it today", "mascot": "blob", "mood": "wave",
         "voice": "Try it today."}]}


def direct(pid: str, brief: str, size: str | None = None) -> dict:
    import brain
    log(pid, "Director", f"Planning the storyboard with {brain.describe()}")
    plan = brain.ask_json(f"Brief: {brief}\n\nWrite the storyboard JSON.", DIRECTOR, max_tokens=3000, timeout=180)
    if not isinstance(plan, dict) or not plan.get("scenes"):
        log(pid, "Director", "The brain gave no usable plan - using a simple storyboard", "done")
        plan = _fallback(brief)
    else:
        log(pid, "Director", f"Storyboard ready: {len(plan['scenes'])} scenes", "done")
    plan["id"] = pid
    plan["brief"] = brief
    plan["size"] = size or _size_from(brief) or plan.get("size") or getattr(config, "MOTION_SIZE", "vertical")
    log(pid, "Designer", "Checking colours, sizes and mascots")
    plan = validate(plan)
    log(pid, "Designer", "Style locked", "done")
    return plan


# ---------------------------------------------------------------- Voice + Animator

def _ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def media_seconds(path: str) -> float:
    ff = _ffmpeg()
    if not ff:
        return 0.0
    r = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", r.stderr or "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def _sapi_to_wav(text: str, path: str):
    """Offline fallback: the built-in Windows voice, saved to a .wav file."""
    if os.name != "nt":
        return None
    try:
        import comtypes.client
        v = comtypes.client.CreateObject("SAPI.SpVoice")
        for tok in v.GetVoices():
            if "zira" in tok.GetDescription().lower():
                v.Voice = tok
                break
        st = comtypes.client.CreateObject("SAPI.SpFileStream")
        st.Open(path, 3)
        v.AudioOutputStream = st
        v.Speak(text)
        st.Close()
        return path
    except Exception as e:
        print(f"[motion] Windows voice failed: {e}")
        return None


def voice(project: dict) -> dict:
    """Records every voice line and stretches each scene to fit its line."""
    pid = project["id"]
    adir = os.path.join(_dir(pid), "audio")
    os.makedirs(adir, exist_ok=True)
    lines = [s for s in project["scenes"] if s.get("voice")]
    if not lines or not project.get("narration", True):
        log(pid, "Voice", "No narration in this video", "done")
        return project
    log(pid, "Voice", f"Recording {len(lines)} lines")
    try:
        import tts_engine
    except Exception:
        tts_engine = None
    ok = 0
    for i, s in enumerate(project["scenes"]):
        s.pop("voice_file", None)
        s.pop("voice_len", None)
        if not s.get("voice") or tts_engine is None:
            continue
        path = os.path.join(adir, f"scene{i + 1}.mp3")
        try:
            data = tts_engine._synth_neural(s["voice"])
            with open(path, "wb") as f:
                f.write(data)
        except Exception as e:
            print(f"[motion] neural voice failed for line {i + 1} ({e}) - trying the Windows voice")
            path = _sapi_to_wav(s["voice"], os.path.join(adir, f"scene{i + 1}.wav"))
        if path and os.path.exists(path):
            s["voice_file"] = os.path.basename(path)
            s["voice_len"] = round(media_seconds(path), 2)
            ok += 1
    log(pid, "Voice", f"Recorded {ok} of {len(lines)} lines" + ("" if ok else " - the neural voice needs internet"), "done")
    log(pid, "Animator", "Timing each scene to its voice line")
    for s in project["scenes"]:
        if s.get("voice_len"):
            s["duration"] = round(max(float(s["duration"]), s["voice_len"] + 0.9), 2)
    log(pid, "Animator", f"Total length {sum(s['duration'] for s in project['scenes']) / project['speed']:.1f} s", "done")
    return project


# ---------------------------------------------------------------- Renderer + Mixer

def render(pid: str) -> str:
    """Draws every frame in a hidden browser and writes video.mp4. Returns its path."""
    project = load(pid)
    if not project:
        raise RuntimeError("no such project")
    ff = _ffmpeg()
    if not ff:
        raise RuntimeError("ffmpeg isn't installed - run install.bat once")
    start_server()
    st = status(pid)
    d = _dir(pid)
    fps = int(getattr(config, "MOTION_FPS", 30) or 30)
    w, h = SIZES[project["size"]]
    silent = os.path.join(d, "_frames.mp4")
    out = os.path.join(d, "video.mp4")
    with _lock:
        st["render"] = {"state": "rendering", "progress": 0.0}
    log(pid, "Reviewer", "Opening the frames to check the text fits")
    from playwright.sync_api import sync_playwright
    import webcap
    with sync_playwright() as pw:
        browser = webcap._launch(pw, headless=True)
        page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
        page.goto(f"http://127.0.0.1:{port()}/player.html?id={pid}", wait_until="load")
        page.wait_for_function("window.__ready === true", timeout=30000)
        page.evaluate("document.fonts && document.fonts.ready")
        duration = float(page.evaluate("window.__duration"))
        spill = page.evaluate("""() => [...document.querySelectorAll('.h1,.h2,.number,.sub')]
            .filter(n => n.scrollWidth > n.clientWidth + 2).length""")
        log(pid, "Reviewer", "All text fits" if not spill else f"{spill} text blocks were shrunk to fit", "done")
        frames = max(1, int(round(duration * fps)))
        log(pid, "Renderer", f"Drawing {frames} frames at {w}x{h}, {fps} fps")
        enc = subprocess.Popen([ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps),
                                "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                                "-pix_fmt", "yuv420p", "-movflags", "+faststart", silent],
                               stdin=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        t0 = time.time()
        try:
            for i in range(frames):
                page.evaluate(f"window.__seek({i / fps})")
                enc.stdin.write(page.screenshot(type="jpeg", quality=92))
                if i % 10 == 0:
                    with _lock:
                        st["render"]["progress"] = round(i / frames, 3)
        finally:
            enc.stdin.close()
            enc.wait()
            browser.close()
        log(pid, "Renderer", f"Frames done in {time.time() - t0:.0f} s", "done")
    log(pid, "Mixer", "Laying the voice and music under the picture")
    _mix(project, silent, out, duration, ff)
    try:
        os.remove(silent)
    except OSError:
        pass
    log(pid, "Mixer", "Video ready", "done")
    with _lock:
        st["render"] = {"state": "done", "progress": 1.0, "video": f"/files/{pid}/video.mp4?{int(time.time())}"}
    return out


def _mix(project: dict, silent: str, out: str, duration: float, ff: str):
    d = _dir(project["id"])
    inputs, filters, labels = ["-i", silent], [], []
    t = 0.0
    speed = float(project.get("speed") or 1)
    for s in project["scenes"]:
        vf = s.get("voice_file")
        if vf and os.path.exists(os.path.join(d, "audio", vf)):
            idx = len(inputs) // 2
            inputs += ["-i", os.path.join(d, "audio", vf)]
            ms = int((t / speed + 0.25) * 1000)
            filters.append(f"[{idx}:a]adelay={ms}|{ms},aformat=channel_layouts=stereo[v{idx}]")
            labels.append(f"[v{idx}]")
        t += float(s["duration"])
    music = project.get("music")
    if music and os.path.isfile(music):
        idx = len(inputs) // 2
        inputs += ["-stream_loop", "-1", "-i", music]
        fade = max(0.0, duration - 1.5)
        filters.append(f"[{idx}:a]volume=0.16,afade=t=out:st={fade:.2f}:d=1.5,aformat=channel_layouts=stereo[m]")
        labels.append("[m]")
    if not labels:
        shutil.copyfile(silent, out)
        return
    filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest[a]")
    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
           "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{duration:.2f}",
           "-movflags", "+faststart", out]
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        print(f"[motion] audio mix failed, keeping the silent video: {r.stderr[-300:]}")
        shutil.copyfile(silent, out)


# ---------------------------------------------------------------- Editor (voice/text edits)

EDITOR = ("You edit an animated video project given as JSON. Apply the user's change and return the WHOLE updated "
          "project as JSON only. Keep everything they didn't ask to change. Scene numbers start at 1. Allowed scene "
          "types: title, statement, big_number, list, phone, split, outro. Mascots: blob, bot, cloud, drop, box, none. "
          "Moods: happy, wow, wave, think. 'faster' = raise speed (max 2), 'slower' = lower it (min 0.5). "
          "Colours are #hex. Wrap highlighted words in [square brackets].")


def edit(pid: str, instruction: str) -> str:
    import brain
    project = load(pid)
    if not project:
        return "I couldn't find that video project."
    with _lock:
        status(pid)["busy"] = True
    try:
        log(pid, "Director", f"Editing: {instruction}")
        slim = {k: v for k, v in project.items() if k not in ("updated", "brief")}
        for s in slim.get("scenes", []):
            s.pop("voice_file", None)
            s.pop("voice_len", None)
        new = brain.ask_json(f"PROJECT:\n{json.dumps(slim, ensure_ascii=False)}\n\nCHANGE: {instruction}",
                             EDITOR, max_tokens=4000, timeout=180)
        if not isinstance(new, dict) or not new.get("scenes"):
            log(pid, "Director", "Couldn't apply that change", "done")
            return "I couldn't apply that change. Try saying it another way."
        new["id"] = pid
        new["brief"] = project.get("brief", "")
        new.setdefault("music", project.get("music", ""))
        voice_changed = [a.get("voice") for a in project["scenes"]] != [b.get("voice") for b in new["scenes"]]
        new = validate(new)
        if not voice_changed:                    # keep the recorded lines that are still valid
            for a, b in zip(project["scenes"], new["scenes"]):
                if a.get("voice_file") and a.get("voice") == b.get("voice"):
                    b["voice_file"], b["voice_len"] = a["voice_file"], a.get("voice_len")
        else:
            new = voice(new)
        save(new)
        log(pid, "Director", "Change applied", "done")
        return "Done. The studio shows the new version. Say 'render the video' when you're happy."
    finally:
        with _lock:
            status(pid)["busy"] = False


# ---------------------------------------------------------------- the whole pipeline

def make(brief: str, render_now: bool | None = None, open_studio: bool = True, speak=None) -> str:
    if render_now is None:
        render_now = bool(getattr(config, "MOTION_AUTO_SAVE", False))
    pid = _slug(brief[:40])
    start_server()
    _placeholder(pid, brief)
    if open_studio:
        open_in_browser(pid)
    err = _make_with_id(pid, brief, render_now, placeholder=False)
    if err:
        return f"The video agents hit a problem: {err}"
    project = load(pid) or {}
    if render_now:
        return (f"Your video is ready: {project.get('title', 'your video')}, {len(project.get('scenes', []))} scenes. "
                f"It's saved in {_dir(pid)}.")
    return (f"{project.get('title', 'Your video')} is ready to watch in the studio. "
            "I haven't saved the video file yet - say 'save the video' when you're happy with it.")


def make_async(brief: str, speak=None) -> str:
    threading.Thread(target=lambda: _announce(make(brief), speak), daemon=True, name="motion").start()
    return "On it. My video agents are working on it - you can watch them in the studio."


def _announce(reply: str, speak):
    if speak:
        try:
            speak(reply)
        except Exception:
            pass


def render_async(pid: str | None = None, speak=None) -> str:
    pid = pid or latest_id()
    if not pid:
        return "There's no video project yet. Say: make a motion video about something."
    st = status(pid)
    if st["render"].get("state") == "rendering":
        return "It's already rendering."

    def run():
        try:
            path = render(pid)
            _announce(f"The video is saved in {os.path.dirname(path)}.", speak)
        except Exception as e:
            log(pid, "Renderer", f"Stopped: {e}", "error")
            with _lock:
                st["render"] = {"state": "error", "progress": 0, "error": str(e)}
            _announce(f"Rendering failed: {e}", speak)
    threading.Thread(target=run, daemon=True, name="motion-render").start()
    return "Saving the video now. I'll tell you when it's done."


# ---------------------------------------------------------------- studio server

def port() -> int:
    return int(getattr(config, "STUDIO_PORT", 8740) or 8740)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path):
        if not os.path.isfile(path):
            return self._send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        size = os.path.getsize(path)
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng and (m := re.match(r"bytes=(\d*)-(\d*)", rng)):
            start = int(m.group(1) or 0)
            end = int(m.group(2)) if m.group(2) else size - 1
        with open(path, "rb") as f:
            f.seek(start)
            data = f.read(end - start + 1)
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Accept-Ranges", "bytes")
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def do_GET(self):
        u = urlparse(self.path)
        parts = [unquote(x) for x in u.path.strip("/").split("/") if x]
        if not parts or parts == ["studio"]:
            return self._file(os.path.join(STATIC, "studio.html"))
        if parts[0] == "player.html":
            return self._file(os.path.join(STATIC, "player.html"))
        if parts[0] == "static" and len(parts) == 2:
            return self._file(os.path.join(STATIC, os.path.basename(parts[1])))
        if parts[0] == "files" and len(parts) >= 3:
            base = os.path.realpath(_dir(parts[1]))
            path = os.path.realpath(os.path.join(base, *parts[2:]))
            if not path.startswith(base + os.sep):
                return self._send(403, {"error": "no"})
            return self._file(path)
        if parts[:2] == ["api", "projects"]:
            return self._send(200, projects())
        if parts[:2] == ["api", "project"] and len(parts) == 3:
            p = load(parts[2])
            return self._send(200 if p else 404, p or {"error": "not found"})
        if parts[:2] == ["api", "status"] and len(parts) == 3:
            st = status(parts[2])
            with _lock:
                return self._send(200, {"agents": st["agents"], "log": st["log"][-40:], "render": st["render"],
                                        "busy": st["busy"], "brain": _brain_name()})
        if parts[:2] == ["api", "info"]:
            return self._send(200, {"brain": _brain_name(), "types": TYPES, "mascots": MASCOTS, "moods": MOODS,
                                    "agents": AGENTS})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        parts = [unquote(x) for x in urlparse(self.path).path.strip("/").split("/") if x]
        body = self._body()
        if parts[:2] == ["api", "project"] and len(parts) == 3:
            body["id"] = parts[2]
            old = load(parts[2]) or {}
            body.setdefault("brief", old.get("brief", ""))
            return self._send(200, save(body))
        if parts[:2] == ["api", "new"]:
            brief = str(body.get("brief") or "").strip()
            if not brief:
                return self._send(400, {"error": "brief needed"})
            pid = _slug(brief[:40])
            threading.Thread(target=_make_with_id, args=(pid, brief, bool(getattr(config, "MOTION_AUTO_SAVE", False))),
                             daemon=True).start()
            return self._send(200, {"id": pid})
        if parts[:2] == ["api", "edit"] and len(parts) == 3:
            threading.Thread(target=edit, args=(parts[2], str(body.get("text") or "")), daemon=True).start()
            return self._send(200, {"ok": True})
        if parts[:2] == ["api", "render"] and len(parts) == 3:
            return self._send(200, {"message": render_async(parts[2])})
        if parts[:2] == ["api", "voice"] and len(parts) == 3:
            def run():
                p = load(parts[2])
                if p:
                    save(voice(p))
            threading.Thread(target=run, daemon=True).start()
            return self._send(200, {"ok": True})
        if parts[:2] == ["api", "reveal"] and len(parts) == 3:
            try:
                os.startfile(_dir(parts[2]))
            except (OSError, AttributeError):
                pass
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})


def _placeholder(pid, brief):
    save(validate({"id": pid, "title": "Planning...", "brief": brief, "scenes": [
        {"type": "statement", "headline": "Your agents are [working]", "mascot": "bot", "mood": "think", "duration": 3}]}))


def _make_with_id(pid, brief, render_now=False, placeholder=True):
    """Runs the whole agent team. Returns None when fine, else the error text."""
    st = status(pid)
    with _lock:
        st["busy"] = True
    if placeholder:
        _placeholder(pid, brief)
    try:
        project = direct(pid, brief)
        save(project)
        save(voice(project))
        if render_now:
            render(pid)
        return None
    except Exception as e:
        log(pid, "Renderer", f"Stopped: {e}", "error")
        with _lock:
            st["render"] = {"state": "error", "progress": 0, "error": str(e)}
        return str(e)
    finally:
        with _lock:
            st["busy"] = False


def _brain_name() -> str:
    try:
        import brain
        return brain.describe()
    except Exception:
        return "local"


def start_server() -> int:
    if _server["httpd"]:
        return port()
    os.makedirs(ROOT, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", port()), _Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True, name="motion-studio").start()
    _server["httpd"] = httpd
    print(f"[motion] studio on http://127.0.0.1:{port()}")
    return port()


def open_in_browser(pid: str | None = None) -> str:
    start_server()
    url = f"http://127.0.0.1:{port()}/" + (f"?id={pid}" if pid else "")
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass
    return "I've opened the motion studio."


def music_for(pid: str | None, path: str) -> str:
    pid = pid or latest_id()
    p = load(pid) if pid else None
    if not p:
        return "There's no video project yet."
    if not os.path.isfile(path):
        return "I couldn't find that music file."
    p["music"] = path
    save(p)
    return "Added the music. Say 'render the video' to hear it."


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(make(" ".join(sys.argv[1:]), open_studio=False))
    else:
        start_server()
        print(f"Studio: http://127.0.0.1:{port()}  (Ctrl+C to stop)")
        while True:
            time.sleep(3600)
