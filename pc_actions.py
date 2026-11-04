"""
Everything Hinata can physically do on the Windows PC. Each function does
one job and returns a short sentence to speak.

Actions that can't be undone (shut down, delete, risky PowerShell) never run
straight away - they return a Confirm(...) and commands.py asks the user
to say "confirm" first.
"""

import os
import re
import shutil
import subprocess
import threading
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote_plus

import requests

import config
import system_info

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class Confirm:
    """Returned instead of doing something irreversible."""
    kind: str
    payload: object
    question: str


# ---------------------------------------------------------------- apps, sites, files

def open_target(target: str) -> str:
    target = target.strip().strip(".").strip('"')
    lower = target.lower()
    if not target:
        return "What should I open?"
    if lower in config.KNOWN_SITES:
        webbrowser.open(config.KNOWN_SITES[lower])
        return f"Opening {target}."
    if lower.startswith(("http://", "https://", "www.")):
        webbrowser.open(target if "://" in target else "https://" + target)
        return f"Opening {target}."
    expanded = os.path.expandvars(os.path.expanduser(target))
    if os.path.exists(expanded):
        os.startfile(expanded)
        return f"Opening {os.path.basename(expanded.rstrip(os.sep)) or target}."
    looks_like_file = bool(re.search(r"\.[a-z0-9]{2,5}$", lower))
    if looks_like_file:
        found = system_info.find_file(target)
        if found:
            os.startfile(found)
            return f"Opened {os.path.basename(found)}."
    exe = config.KNOWN_APPS.get(lower)
    if exe:
        try:
            os.startfile(exe)
        except Exception:
            subprocess.Popen(["cmd", "/c", "start", "", exe], creationflags=_NO_WINDOW)
        return f"Opening {target}."
    app = system_info.find_app(lower)
    if app:
        system_info.launch(app[1])
        return f"Opening {app[0]}."
    folder = system_info.find_folder(target)
    if folder:
        os.startfile(folder)
        return f"Opened the {os.path.basename(folder)} folder."
    found = system_info.find_file(target)
    if found:
        os.startfile(found)
        return f"Opened {os.path.basename(found)}."
    if "." in target and " " not in target:
        webbrowser.open("https://" + target)
        return f"Opening {target}."
    webbrowser.open(f"https://google.com/search?q={quote_plus(target)}")
    return f"I couldn't find an app or file called {target}, so I searched for it."


def close_app(name: str) -> str:
    exe = config.KNOWN_APPS.get(name.lower().strip())
    if exe and exe.endswith(".exe"):
        r = subprocess.run(["taskkill", "/IM", exe, "/F"], capture_output=True, creationflags=_NO_WINDOW)
        if r.returncode == 0:
            return f"Closed {name}."
    if system_info.kill_process(name) > 0:
        return f"Closed {name}."
    return f"I couldn't find {name} running."


# ---------------------------------------------------------------- media & web

def _first_youtube_id(query: str):
    try:
        html = requests.get("https://www.youtube.com/results",
                            params={"search_query": query}, timeout=6,
                            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en"}).text
        m = re.search(r'"videoId":"([\w-]{11})"', html)
        return m.group(1) if m else None
    except requests.RequestException:
        return None


def play_media(query: str, platform: str = "youtube") -> str:
    query = query.strip()
    platform = (platform or "youtube").lower()
    if platform == "spotify":
        os.startfile(f"spotify:search:{quote_plus(query)}")
        return f"Searching Spotify for {query}."
    vid = _first_youtube_id(query)
    if vid:
        host = "music.youtube.com" if "music" in platform else "www.youtube.com"
        webbrowser.open(f"https://{host}/watch?v={vid}")
        return f"Playing {query}."
    webbrowser.open(f"https://www.youtube.com/results?search_query={quote_plus(query)}")
    return f"Searching YouTube for {query}."


def search_web(query: str) -> str:
    webbrowser.open(f"https://google.com/search?q={quote_plus(query)}")
    return f"Searching for {query}."


def media_control(action: str) -> str:
    import keyboard
    keys = {"play_pause": "play/pause media", "next": "next track", "previous": "previous track",
            "stop": "stop media"}
    if action not in keys:
        return "I'm not sure which media action you meant."
    keyboard.send(keys[action])
    return {"play_pause": "Done.", "next": "Next track.", "previous": "Previous track.", "stop": "Stopped."}[action]


# ---------------------------------------------------------------- keyboard & windows

KEY_ALIASES = {"control": "ctrl", "windows": "windows", "win": "windows", "cmd": "windows",
               "return": "enter", "escape": "esc", "del": "delete", "option": "alt"}


def type_text(text: str) -> str:
    import keyboard
    time.sleep(0.35)
    keyboard.write(text, delay=0.004)
    return "Typed it."


def press_keys(keys: str) -> str:
    import keyboard
    parts = [KEY_ALIASES.get(k.strip().lower(), k.strip().lower())
             for k in re.split(r"\s*\+\s*|\s+plus\s+", keys) if k.strip()]
    if not parts:
        return "Which keys should I press?"
    time.sleep(0.2)
    keyboard.send("+".join(parts))
    return f"Pressed {keys}."


def window(action: str) -> str:
    import keyboard
    shortcuts = {"minimize": "windows+down", "maximize": "windows+up", "close": "alt+f4",
                 "switch": "alt+tab", "show_desktop": "windows+d", "snap_left": "windows+left",
                 "snap_right": "windows+right", "minimize_all": "windows+m"}
    combo = shortcuts.get(action)
    if not combo:
        return "I'm not sure what to do with the window."
    time.sleep(0.2)
    keyboard.send(combo)
    if action == "minimize":
        time.sleep(0.05)
        keyboard.send(combo)
    return "Done."


# ---------------------------------------------------------------- volume & brightness

def _endpoint():
    from pycaw.pycaw import AudioUtilities
    dev = AudioUtilities.GetSpeakers()
    if hasattr(dev, "EndpointVolume"):             # pycaw >= 2025
        return dev.EndpointVolume
    from ctypes import POINTER, cast
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume
    iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(iface, POINTER(IAudioEndpointVolume))


def volume(action: str, level=None) -> str:
    try:
        ep = _endpoint()
        cur = ep.GetMasterVolumeLevelScalar()
        if action == "up":
            ep.SetMasterVolumeLevelScalar(min(1.0, cur + 0.1), None)
            ep.SetMute(0, None)
        elif action == "down":
            ep.SetMasterVolumeLevelScalar(max(0.0, cur - 0.1), None)
        elif action == "mute":
            ep.SetMute(1, None)
            return "Muted."
        elif action == "unmute":
            ep.SetMute(0, None)
            return "Unmuted."
        elif action == "set" and level is not None:
            ep.SetMasterVolumeLevelScalar(max(0, min(100, int(level))) / 100, None)
            ep.SetMute(0, None)
        else:
            return "How loud should it be?"
        return f"Volume {round(ep.GetMasterVolumeLevelScalar() * 100)} percent."
    except Exception:
        import keyboard   # fallback: media keys
        if action in ("mute", "unmute"):
            keyboard.send("volume mute")
            return "Done."
        for _ in range(5):
            keyboard.send("volume up" if action in ("up", "set") else "volume down")
        return f"Volume {action}."


def set_brightness(level) -> str:
    level = max(0, min(100, int(level)))
    try:
        import screen_brightness_control as sbc
        sbc.set_brightness(level)
    except Exception:
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
                        f".WmiSetBrightness(1,{level})"], capture_output=True, creationflags=_NO_WINDOW)
    return f"Brightness {level} percent."


# ---------------------------------------------------------------- system

SETTINGS_PAGES = {
    "wifi": "network-wifi", "wi-fi": "network-wifi", "network": "network-status",
    "bluetooth": "bluetooth", "display": "display", "sound": "sound", "battery": "batterysaver",
    "power": "powersleep", "updates": "windowsupdate", "update": "windowsupdate", "apps": "appsfeatures",
    "privacy": "privacy", "personalization": "personalization", "wallpaper": "personalization-background",
    "background": "personalization-background", "themes": "themes", "storage": "storagesense",
    "notifications": "notifications", "mouse": "mousetouchpad", "keyboard": "typing",
    "date": "dateandtime", "time": "dateandtime", "language": "regionlanguage", "vpn": "network-vpn",
    "hotspot": "network-mobilehotspot", "night light": "nightlight", "about": "about",
    "microphone": "privacy-microphone", "camera": "privacy-webcam", "default apps": "defaultapps",
    "startup": "startupapps", "accounts": "yourinfo", "focus": "quiethours",
}


def open_settings(page: str) -> str:
    key = page.lower().strip()
    uri = SETTINGS_PAGES.get(key) or next((v for k, v in SETTINGS_PAGES.items() if k in key), "")
    os.startfile(f"ms-settings:{uri}")
    return f"Opened {page} settings."


def system_control(action: str):
    if action == "lock":
        subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"])
        return "Locking the PC."
    if action == "sleep":
        subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        return "Going to sleep."
    questions = {"shutdown": "Shut down the PC?", "restart": "Restart the PC?",
                 "sign_out": "Sign out of Windows?", "empty_recycle_bin": "Empty the recycle bin for good?"}
    if action in questions:
        return Confirm("system", action, questions[action] + " Say confirm, or cancel.")
    return "Not sure what system action you meant."


def do_system(action: str) -> str:
    if action == "shutdown":
        subprocess.run(["shutdown", "/s", "/t", "5"])
        return "Shutting down in 5 seconds."
    if action == "restart":
        subprocess.run(["shutdown", "/r", "/t", "5"])
        return "Restarting in 5 seconds."
    if action == "sign_out":
        subprocess.run(["shutdown", "/l"])
        return "Signing out."
    if action == "empty_recycle_bin":
        subprocess.run(["powershell", "-NoProfile", "-Command", "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"],
                       creationflags=_NO_WINDOW)
        return "Recycle bin emptied."
    return "Done."


def take_screenshot() -> str:
    from PIL import ImageGrab
    path = os.path.join(config.OUTPUT_DIR, f"screenshot_{datetime.now():%Y%m%d_%H%M%S}.png")
    ImageGrab.grab(all_screens=True).save(path)
    return "Screenshot saved to your Hinata Output folder."


# ---------------------------------------------------------------- writing

def _safe_name(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9 _-]+", "", title).strip().replace(" ", "_")[:60] or "note"


def write_document(title: str, content: str, extension: str = "txt") -> str:
    ext = re.sub(r"[^a-z0-9]", "", (extension or "txt").lower()) or "txt"
    path = os.path.join(config.OUTPUT_DIR, f"{_safe_name(title)}_{datetime.now():%H%M%S}.{ext}")
    content = re.sub(r"^```[a-zA-Z0-9]*\n|\n```\s*$", "", content.strip())
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    try:
        os.startfile(path)
    except Exception:
        pass
    return f"I wrote {title} and opened it. It's saved in your Hinata Output folder."


def make_presentation(topic: str, outline: list[dict]) -> str:
    """outline = [{'title': str, 'bullets': [str, ...]}, ...]"""
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    BG, ACC, FG = RGBColor(0x0E, 0x0A, 0x1F), RGBColor(0xB4, 0x9C, 0xFF), RGBColor(0xF2, 0xEE, 0xFF)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]

    def base():
        s = prs.slides.add_slide(blank)
        s.background.fill.solid()
        s.background.fill.fore_color.rgb = BG
        bar = s.shapes.add_shape(1, 0, Inches(7.3), prs.slide_width, Inches(0.2))
        bar.fill.solid()
        bar.fill.fore_color.rgb = ACC
        bar.line.fill.background()
        return s

    def text(s, x, y, w, h, value, size, color, bold=False):
        tf = s.shapes.add_textbox(x, y, w, h).text_frame
        tf.word_wrap = True
        tf.text = value
        p = tf.paragraphs[0]
        p.font.size, p.font.bold, p.font.color.rgb = Pt(size), bold, color
        return tf

    s = base()
    text(s, Inches(0.9), Inches(2.4), Inches(11.5), Inches(1.6), topic.title(), 48, FG, True)
    text(s, Inches(0.9), Inches(4.0), Inches(11.5), Inches(0.6),
         f"Made with {config.ASSISTANT_NAME}  |  {datetime.now():%d %B %Y}", 18, ACC)

    for slide in outline:
        s = base()
        text(s, Inches(0.8), Inches(0.5), Inches(11.7), Inches(1.0), str(slide.get("title", topic)), 34, ACC, True)
        tf = None
        for i, b in enumerate(slide.get("bullets", [])[:6]):
            if tf is None:
                tf = text(s, Inches(0.9), Inches(1.8), Inches(11.5), Inches(5.2), "•  " + str(b), 22, FG)
            else:
                p = tf.add_paragraph()
                p.text = "•  " + str(b)
                p.font.size, p.font.color.rgb = Pt(22), FG
                p.space_before = Pt(10)
        if tf is not None:
            tf.paragraphs[0].space_before = Pt(0)
    path = os.path.join(config.OUTPUT_DIR, f"{_safe_name(topic)}_{datetime.now():%H%M%S}.pptx")
    prs.save(path)
    try:
        os.startfile(path)
    except Exception:
        pass
    return f"Your presentation on {topic} is ready and open - {len(outline) + 1} slides."


# ---------------------------------------------------------------- files

def _resolve(path: str, must_exist=True) -> str | None:
    p = os.path.expandvars(os.path.expanduser(path.strip().strip('"')))
    if os.path.isabs(p):
        return p if (os.path.exists(p) or not must_exist) else None
    if not must_exist:
        return os.path.join(config.DESKTOP_DIR, p)
    return system_info.find_file(p) or system_info.find_folder(p)


def file_action(action: str, path: str, destination: str = ""):
    if action == "create_folder":
        target = _resolve(path, must_exist=False)
        os.makedirs(target, exist_ok=True)
        os.startfile(target)
        return f"Created the folder {os.path.basename(target)}."
    if action == "search":
        hits = system_info.search_files(path)
        if not hits:
            return f"No files matching {path}."
        names = ", ".join(os.path.basename(h) for h in hits[:5])
        return f"Found {len(hits)}: {names}. The first is in {os.path.dirname(hits[0])}."
    src = _resolve(path)
    if not src:
        return f"I couldn't find {path}."
    if action == "open_folder":
        target = src if os.path.isdir(src) else os.path.dirname(src)
        subprocess.Popen(["explorer", "/select,", src] if os.path.isfile(src) else ["explorer", target])
        return f"Opened {os.path.basename(target)}."
    if action == "delete":
        return Confirm("delete", src, f"Move {os.path.basename(src)} to the recycle bin? Say confirm, or cancel.")
    if action in ("move", "copy"):
        if not destination.strip():
            return "Where should it go?"
        d = os.path.expandvars(os.path.expanduser(destination.strip().strip('"')))
        if not os.path.isabs(d):
            known = {"desktop": config.DESKTOP_DIR,
                     "downloads": os.path.join(os.path.expanduser("~"), "Downloads"),
                     "documents": os.path.join(os.path.expanduser("~"), "Documents")}
            d = known.get(d.lower()) or system_info.find_folder(d) or os.path.join(config.DESKTOP_DIR, d)
        os.makedirs(d, exist_ok=True)
        final = os.path.join(d, os.path.basename(src.rstrip(os.sep)))
        if os.path.exists(final):
            return f"There's already a {os.path.basename(final)} in {os.path.basename(d)}."
        if action == "move":
            shutil.move(src, final)
        elif os.path.isdir(src):
            shutil.copytree(src, final)
        else:
            shutil.copy2(src, final)
        return f"{'Moved' if action == 'move' else 'Copied'} {os.path.basename(src)} to {os.path.basename(d)}."
    if action == "rename":
        if not destination:
            return "What should the new name be?"
        new = os.path.join(os.path.dirname(src), destination.strip())
        if not os.path.splitext(new)[1] and os.path.isfile(src):
            new += os.path.splitext(src)[1]
        os.rename(src, new)
        return f"Renamed to {os.path.basename(new)}."
    return "I'm not sure what to do with that file."


def do_delete(path: str) -> str:
    try:
        from send2trash import send2trash
        send2trash(path)
        return f"Moved {os.path.basename(path)} to the recycle bin."
    except ImportError:
        return "Deleting needs the send2trash package: pip install send2trash"


# ---------------------------------------------------------------- clipboard, timers, info

def clipboard(action: str, text: str = "") -> str:
    import pyperclip
    if action == "copy":
        pyperclip.copy(text)
        return "Copied to your clipboard."
    data = pyperclip.paste() or ""
    return f"Clipboard says: {data[:1500]}" if data.strip() else "Your clipboard is empty."


_timers: list[threading.Timer] = []


def set_timer(minutes: float, label: str, on_done) -> str:
    secs = max(1, float(minutes) * 60)
    msg = f"Reminder: {label}." if label else "Your timer is done."
    t = threading.Timer(secs, on_done, args=(msg,))
    t.daemon = True
    t.start()
    _timers.append(t)
    when = f"{int(secs)} seconds" if secs < 90 else f"{secs / 60:g} minutes"
    return f"Timer set for {when}" + (f" - {label}." if label else ".")


def time_reply() -> str:
    now = datetime.now()
    return f"It's {now.strftime('%I:%M %p').lstrip('0')}, {now.strftime('%A %d %B')}."


def get_info(kind: str, city: str = "") -> str:
    return {"time": time_reply, "battery": system_info.get_battery, "cpu_temp": system_info.get_cpu_temp,
            "system_stats": system_info.get_stats,
            "weather": lambda: system_info.get_weather(city)}.get(kind, time_reply)()


# ---------------------------------------------------------------- PowerShell (with safety gate)

RISKY = re.compile(
    r"remove-item|\brm\b|\bdel\b|\berase\b|\brd\b|\brmdir\b|format-volume|\bformat\b|clear-disk|"
    r"initialize-disk|diskpart|stop-computer|restart-computer|shutdown|set-executionpolicy|"
    r"\breg(\.exe)?\s+(delete|add|import)|remove-itemproperty|set-itemproperty|new-itemproperty|"
    r"bcdedit|cipher|vssadmin|invoke-expression|\biex\b|invoke-webrequest|\biwr\b|invoke-restmethod|\birm\b|"
    r"downloadstring|downloadfile|start-bitstransfer|\bcurl\b|\bwget\b|net\s+user|net\s+localgroup|"
    r"localuser|localgroup|uninstall|winget\s+(install|uninstall|upgrade)|\bchoco\b|stop-process|taskkill|"
    r"mppreference|advfirewall|move-item|rename-item|\bmove\b|set-content|add-content|out-file|"
    r"(?<![<>=-])>(?![=])|schtasks|new-service|\bsc(\.exe)?\s+(delete|create|config)|takeown|icacls|attrib|"
    r"-verb\s+runas|clear-recyclebin|disable-|enable-|set-service|stop-service|restart-service|"
    r"set-date|set-timezone|new-item.*-force|copy-item.*-force|encodedcommand|-enc\b|frombase64",
    re.I)


def is_risky(command: str) -> bool:
    return bool(RISKY.search(command))


def run_powershell(command: str, purpose: str = ""):
    command = command.strip()
    if not command:
        return "No command given."
    if is_risky(command) or not config.AUTO_RUN_SAFE_COMMANDS:
        what = purpose or command[:80]
        print(f"[powershell] needs confirmation: {command}")
        return Confirm("powershell", command, f"This changes your system: {what}. Say confirm to run it, or cancel.")
    return execute_powershell(command)


def execute_powershell(command: str) -> str:
    print(f"[powershell] {command}")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                           capture_output=True, text=True, timeout=45, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return "The command took too long and was stopped."
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if r.returncode != 0 and err:
        return f"Command error: {err[:600]}"
    out = re.sub(r"\n\s*\n+", "\n", out)
    return out[:1800] if out else "Done."
