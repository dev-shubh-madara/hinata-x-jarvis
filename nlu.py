"""
The AI brain - a local agent powered by Ollama (no API key, no cloud).

commands.py answers common phrases instantly with patterns. Everything
else comes here: the model picks one or more tools, Hinata runs them,
feeds the results back, and the model continues until the job is done
(up to AGENT_MAX_STEPS actions) - so "open notepad and write a poem about
rain" or "on my phone open WhatsApp, tap Vishal and type hi" just work.

Speed tricks:
  * replies stream: each finished sentence goes to the voice straight away,
    so she starts talking while the model is still writing the rest
  * the model is pre-loaded at startup and kept in memory (keep_alive)
  * single-action requests skip the second model call entirely
  * small context window + capped output length
  * talks to Ollama's REST API directly on 127.0.0.1 (no proxy, no IPv6 surprises)

Self-test:  python nlu.py
"""

import json
import os
import re
import shutil
import subprocess
import threading
import time
from urllib.parse import urlparse

import requests

import config

_session = requests.Session()
_session.trust_env = False

_state = {"checked_at": 0.0, "ok": False, "reason": "not checked yet", "model": None,
          "tools": None, "start_tried_at": 0.0}
RECHECK_SECONDS = 15
KEEP_ALIVE = "60m"
OPTIONS = {"temperature": config.AI_TEMPERATURE, "num_ctx": int(getattr(config, "AI_CONTEXT", 8192)), "num_predict": 400}

EMBED_HINTS = ("embed", "bge", "minilm", "e5-", "rerank", "nomic", "mxbai", "snowflake-arctic-embed", "clip")
PREFERRED = ("qwen2.5", "qwen3", "llama3.2", "llama3.1", "llama3", "mistral-nemo", "mistral",
             "granite3", "command-r", "gemma3", "gemma2", "phi4", "phi3", "deepseek", "llava")


# ---------------------------------------------------------------- connection

def base_url() -> str:
    raw = (config.OLLAMA_HOST or os.environ.get("OLLAMA_HOST", "") or "127.0.0.1:11434").strip()
    if "://" not in raw:
        raw = "http://" + raw
    p = urlparse(raw)
    host = p.hostname or "127.0.0.1"
    if host in ("0.0.0.0", "::", "localhost", "[::]"):
        host = "127.0.0.1"
    return f"{p.scheme or 'http'}://{host}:{p.port or 11434}"


def _get(path, timeout=3):
    return _session.get(base_url() + path, timeout=timeout)


def _post(path, payload, timeout=(5, 180)):
    return _session.post(base_url() + path, json=payload, timeout=timeout)


def _is_up() -> bool:
    try:
        return _get("/api/version", timeout=2).ok
    except requests.RequestException:
        return False


def _find_ollama_exe():
    exe = shutil.which("ollama")
    if exe:
        return exe
    for p in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
              r"C:\Program Files\Ollama\ollama.exe"):
        if p and os.path.isfile(p):
            return p
    return None


def _try_start_ollama() -> bool:
    if time.time() - _state["start_tried_at"] < 60:
        return False
    _state["start_tried_at"] = time.time()
    exe = _find_ollama_exe()
    if not exe:
        print("[nlu] Ollama isn't installed - get it from https://ollama.com")
        return False
    print(f"[nlu] Starting Ollama: {exe} serve")
    try:
        env = dict(os.environ)
        env["OLLAMA_HOST"] = base_url().split("://", 1)[1]
        subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        print(f"[nlu] Couldn't start Ollama: {e}")
        return False
    for _ in range(30):
        time.sleep(0.5)
        if _is_up():
            return True
    return False


# ---------------------------------------------------------------- models

def installed_models() -> list[str]:
    data = _get("/api/tags", timeout=5).json()
    return [m.get("name") or m.get("model") for m in data.get("models", []) if (m.get("name") or m.get("model"))]


def _capabilities(name):
    try:
        caps = _post("/api/show", {"model": name}, timeout=(3, 10)).json().get("capabilities")
        return list(caps) if caps else None
    except Exception:
        return None


def _pick_model(names):
    wanted = (config.OLLAMA_MODEL or "").strip()
    if wanted:
        for n in names:
            if n == wanted or n.split(":")[0] == wanted or n.startswith(wanted):
                return n
        print(f"[nlu] OLLAMA_MODEL '{wanted}' isn't installed. Installed: {', '.join(names)}")
    chat = [n for n in names if not any(h in n.lower() for h in EMBED_HINTS)]
    if not chat:
        return None
    fast = (getattr(config, "FAST_MODEL", "") or "").strip()
    if fast:                                   # small + fast model = replies in about a second
        for n in chat:
            if n == fast or n.startswith(fast):
                return n
    caps = {n: _capabilities(n) for n in chat}
    for family in PREFERRED:
        for n in chat:
            if n.startswith(family) and caps[n] and "tools" in caps[n]:
                return n
    for n in chat:
        if caps[n] and "tools" in caps[n]:
            return n
    for family in PREFERRED:
        for n in chat:
            if n.startswith(family):
                return n
    return chat[0]


def available(force: bool = False) -> bool:
    now = time.time()
    if not force and _state["ok"]:
        return True
    if not force and now - _state["checked_at"] < RECHECK_SECONDS:
        return False
    _state["checked_at"] = now
    if not _is_up() and not _try_start_ollama():
        _state.update(ok=False, reason="Ollama isn't running. Open the Ollama app, then try again.")
        return False
    try:
        names = installed_models()
    except Exception as e:
        _state.update(ok=False, reason=f"Ollama answered but listing models failed: {e}")
        return False
    if not names:
        _state.update(ok=False, reason="Ollama has no models. Run: ollama pull qwen2.5:3b")
        return False
    model = _pick_model(names)
    if not model:
        _state.update(ok=False, reason="Only embedding models are installed. Run: ollama pull qwen2.5:3b")
        return False
    if model != _state["model"]:
        caps = _capabilities(model)
        _state["tools"] = None if caps is None else ("tools" in caps)
    _state.update(ok=True, reason="", model=model)
    mode = {True: "tool calling", False: "JSON actions", None: "auto"}[_state["tools"]]
    print(f"[nlu] Ollama online - model: {model} ({mode})")
    return True


def _pull_fast_model():
    """Downloads FAST_MODEL once in the background, then switches to it live."""
    fast = (getattr(config, "FAST_MODEL", "") or "").strip()
    if not fast or (config.OLLAMA_MODEL or "").strip():
        return
    try:
        if any(n == fast or n.startswith(fast) for n in installed_models()):
            return
        print(f"[nlu] downloading the fast model {fast} (one time, ~2 GB) ...")
        _post("/api/pull", {"model": fast, "stream": False}, timeout=(5, 3600))
        print(f"[nlu] {fast} ready - switching to it")
        _state["model"] = None
        available(force=True)
        _post("/api/generate", {"model": _state["model"], "prompt": "", "keep_alive": KEEP_ALIVE},
              timeout=(5, 120))
    except Exception as e:
        print(f"[nlu] fast model download failed: {e}")


def warm_up():
    """Loads the model into GPU/RAM now, so the first command isn't slow."""
    def run():
        if available(force=True):
            try:
                _post("/api/generate", {"model": _state["model"], "prompt": "", "keep_alive": KEEP_ALIVE},
                      timeout=(5, 120))
                print(f"[nlu] {_state['model']} loaded and kept warm.")
            except Exception as e:
                print(f"[nlu] warm-up failed: {e}")
    threading.Thread(target=run, daemon=True, name="ollama-warmup").start()
    threading.Thread(target=_pull_fast_model, daemon=True, name="fast-model").start()


def status_reason() -> str:
    return _state["reason"]


def model_name():
    return _state["model"]


# ---------------------------------------------------------------- tools

def _tool(_name, _desc, _required=(), **params):
    props = {}
    for p, spec in params.items():
        typ, d = spec[0], spec[1]
        props[p] = {"type": typ, "description": d}
        if len(spec) > 2:
            props[p]["enum"] = list(spec[2])
    return {"type": "function", "function": {
        "name": _name, "description": _desc,
        "parameters": {"type": "object", "properties": props, "required": list(_required)}}}


S = "string"
TOOLS = [
    # ---- PC
    _tool("open_target", "Open an installed app (WhatsApp, Chrome, VS Code, Spotify...), a website, a URL, or a file/folder by name or path.",
          ["target"], target=(S, "app name, site, URL, file name or full path")),
    _tool("close_app", "Close a running app.", ["name"], name=(S, "app name")),
    _tool("play_media", "Play a song or video so it starts playing.", ["query"],
          query=(S, "song / video to play"), platform=(S, "where", ("youtube", "youtube music", "spotify"))),
    _tool("search_web", "Google search in the browser.", ["query"], query=(S, "search terms")),
    _tool("type_text", "Type text into the focused window.", ["text"], text=(S, "exact text to type")),
    _tool("press_keys", "Press a keyboard shortcut, e.g. 'ctrl+s', 'alt+f4', 'win+e', 'enter'.", ["keys"],
          keys=(S, "keys joined with +")),
    _tool("window", "Control windows.", ["action"],
          action=(S, "what to do", ("minimize", "maximize", "close", "switch", "show_desktop", "snap_left", "snap_right", "minimize_all"))),
    _tool("volume", "PC volume.", ["action"], action=(S, "action", ("up", "down", "mute", "unmute", "set")),
          level=("integer", "0-100, only for set")),
    _tool("set_brightness", "Set screen brightness.", ["level"], level=("integer", "0-100")),
    _tool("media_control", "Media playback.", ["action"], action=(S, "action", ("play_pause", "next", "previous", "stop"))),
    _tool("system_control", "Lock, sleep, sign out, shut down or restart the PC (power actions ask for confirmation).", ["action"],
          action=(S, "action", ("lock", "sleep", "sign_out", "shutdown", "restart", "empty_recycle_bin"))),
    _tool("open_settings", "Open a Windows Settings page.", ["page"],
          page=(S, "e.g. wifi, bluetooth, display, sound, battery, updates, apps, privacy, network, personalization")),
    _tool("write_document", "Write something (essay, notes, code, letter, list) and save + open it. Put the FULL text in content.",
          ["title", "content"], title=(S, "short title"), content=(S, "the full written content"),
          extension=(S, "file type: txt, md, py, html, js, csv...")),
    _tool("make_presentation", "Create a PowerPoint presentation on a topic.", ["topic"],
          topic=(S, "topic"), slides=("integer", "number of slides, default 6")),
    _tool("take_screenshot", "Screenshot the PC screen."),
    _tool("file_action", "Work with files and folders.", ["action", "path"],
          action=(S, "action", ("create_folder", "search", "open_folder", "move", "copy", "rename", "delete")),
          path=(S, "file/folder name or full path (folder name for create_folder)"),
          destination=(S, "target folder or new name for move/copy/rename")),
    _tool("clipboard", "Read or set the clipboard.", ["action"], action=(S, "action", ("read", "copy")),
          text=(S, "text to copy")),
    _tool("set_timer", "Set a timer / reminder that speaks when it's done.", ["minutes"],
          minutes=("number", "minutes from now"), label=(S, "what to remind about")),
    _tool("get_info", "Get live info.", ["kind"],
          kind=(S, "what", ("time", "battery", "cpu_temp", "weather", "system_stats")), city=(S, "city for weather")),
    _tool("run_powershell", "Run a PowerShell command for anything no other tool covers (system info, network, processes, "
          "files, installing apps with winget...). Output is returned to you. Risky commands are confirmed by the user.",
          ["command"], command=(S, "PowerShell command"), purpose=(S, "one short line: what it does")),
    # ---- phone
    _tool("pair_phone", "Show the QR code to pair/connect the user's Android phone for the first time."),
    _tool("phone_open_app", "Open an app on the phone.", ["name"], name=(S, "app name")),
    _tool("phone_tap", "Tap a button / item on the phone screen by its visible text.", ["target"], target=(S, "visible text")),
    _tool("phone_type", "Type text into the focused field on the phone.", ["text"], text=(S, "text")),
    _tool("phone_swipe", "Swipe / scroll on the phone.", ["direction"],
          direction=(S, "direction", ("up", "down", "left", "right", "scroll down", "scroll up"))),
    _tool("phone_key", "Press a phone key.", ["key"],
          key=(S, "key", ("home", "back", "recents", "power", "volume up", "volume down", "mute", "enter", "play pause", "next", "previous", "wake", "end call"))),
    _tool("phone_call", "Call a contact name or number from the phone (user confirms).", ["who"], who=(S, "contact name or number")),
    _tool("phone_message", "Send an SMS from the phone (user confirms).", ["who", "text"],
          who=(S, "contact name or number"), text=(S, "message")),
    _tool("phone_open_url", "Open a website or search on the phone.", ["query"], query=(S, "URL or search terms")),
    _tool("phone_read_screen", "Read all visible text on the phone screen (use it to see what's there before tapping)."),
    _tool("phone_screenshot", "Screenshot the phone and show it on the PC."),
    _tool("phone_toggle", "Turn a phone feature on/off.", ["feature", "on"],
          feature=(S, "feature", ("wifi", "bluetooth", "mobile data", "airplane mode", "auto rotation")), on=("boolean", "true = on")),
    _tool("phone_status", "Phone battery level."),
    _tool("phone_mirror", "Show and control the phone screen on the PC."),
    _tool("look_at_screen", "LOOK at the user's PC screen and answer about it: 'what is this video about', "
          "'how do I export this', 'what does this error say', 'read this'. Use whenever they say this/that/here "
          "about something on screen.", ["question"], question=(S, "the user's question, as asked")),
    _tool("whatsapp_message", "Send a WhatsApp message from the PC to a person. Opens the chat with the text typed; "
          "the user confirms before it is sent.", ["who", "message"],
          who=(S, "contact name or phone number"), message=(S, "the message, in the user's words")),
    _tool("website_reverse_engineer", "Reverse engineer a website: tech stack, design, structure, API calls and a "
          "rebuild plan. With clone=true also saves an offline study copy.", ["url"],
          url=(S, "website address"), clone=("boolean", "true to also save an offline copy")),
    _tool("make_motion_video", "Make an animated motion video / reel / ad / explainer with mascots and voice-over "
          "(a team of video agents plans, voices and renders it).", ["brief"],
          brief=(S, "what the video is about, who it's for, length or format if said")),
    _tool("edit_video", "Edit a video file: cut, trim, speed up, slow motion, reel format, captions, compress, mute, "
          "music, GIF, rotate, join.", ["request"], request=(S, "the user's edit request in their words")),
    _tool("pc_agent", "Work the PC like a person for multi-step jobs inside apps and windows (clicking buttons, menus, "
          "settings, filling boxes) when no other tool does it directly.", ["goal"],
          goal=(S, "the full goal in the user's words")),
    _tool("team_task", "The user's task list.", ["action"],
          action=(S, "what to do", ("add", "list", "done")), text=(S, "task text, or task number for done")),
    _tool("team_note", "Save or read quick notes.", ["action"],
          action=(S, "what to do", ("add", "read")), text=(S, "the note")),
    _tool("draft_email", "Write an email with AI and open it in the mail app (the user sends it).", ["about"],
          to=(S, "person or email address"), about=(S, "what the email should say")),
    _tool("live_info", "Live info that changes all the time.", ["kind"],
          kind=(S, "what", ("iss", "news", "cricket")), topic=(S, "news topic (optional)")),
    _tool("order_food", "Order food on the user's phone (Swiggy/Zomato): opens the app and searches the dish. "
          "Then continue with phone_tap / phone_read_screen to pick a restaurant, ADD, View Cart, and tap the pay "
          "button (the user confirms the amount).", ["item"],
          item=(S, "dish, e.g. 'chicken biryani'"), app=(S, "app", ("swiggy", "zomato")),
          restaurant=(S, "restaurant name if given")),
    _tool("call_and_talk", "Phone someone and let HINATA do the talking - deliver a message or ask something "
          "for the user (e.g. 'call mom and tell her I'll be late'). The user confirms first.", ["who", "message"],
          who=(S, "contact name or number"), message=(S, "what to tell or ask them, in the user's words")),
    _tool("phone_shell", "Run ANY Android adb shell command on the phone for anything the other phone tools don't cover: "
          "am start -a/-n (open screens, intents, deep links), settings put/get, cmd, input, dumpsys, pm list, "
          "media, alarms, camera, flashlight, ringer mode... Output is returned to you. Destructive commands are "
          "confirmed by the user.", ["command"], command=(S, "adb shell command (without 'adb shell')")),
]
TOOL_NAMES = {t["function"]["name"] for t in TOOLS}

# tools added by other modules (memory, files, browser, coder, MCP plug-ins)
_EXTRA_TOOLS: dict[str, dict] = {}
_EXTRA_FINAL: set[str] = set()


def register_tools(tools: list, final=()):
    """Adds tools the agent can call. final = names whose result can be spoken as the answer."""
    for t in tools:
        _EXTRA_TOOLS[t["function"]["name"]] = t
    _EXTRA_FINAL.update(final)


def unregister_tools(prefix: str):
    for name in [n for n in _EXTRA_TOOLS if n.startswith(prefix)]:
        _EXTRA_TOOLS.pop(name, None)
        _EXTRA_FINAL.discard(name)


def all_tools() -> list:
    return TOOLS + list(_EXTRA_TOOLS.values())


# ---------------------------------------------------------------- tool routing
# All ~60 tool descriptions together are ~6,000 tokens - bigger than a small
# model's context, so the start of the prompt got cut off and the model got
# slower and confused. Each request now gets only the tools that fit it.

CORE_TOOLS = ["open_target", "search_web", "type_text", "press_keys", "write_document", "get_info",
              "run_powershell", "pc_agent", "open_file", "find_files", "recall_memory", "remember_fact"]
TOOL_GROUPS = [
    (r"\b(play|song|music|video|youtube|spotify|pause|resume|next|previous|skip|lofi|playlist)\b",
     ["play_media", "media_control", "volume", "browser_youtube"]),
    (r"\b(volume|brightness|mute|unmute|lock|sleep|shut ?down|restart|sign out|settings?|wifi|wi-fi|bluetooth|"
     r"window|minimi[sz]e|maximi[sz]e|snap|desktop|recycle|battery|cpu|temperature|weather|time)\b",
     ["volume", "set_brightness", "system_control", "open_settings", "window", "get_info"]),
    (r"\b(file|files|folder|move|copy|rename|delete|create|zip|downloads?|documents?|clipboard|paste|ppt|pdf|"
     r"photo|screenshot)\b", ["file_action", "clipboard", "take_screenshot"]),
    (r"\b(website|site|page|browser|chrome|edge|tab|tabs|click|sign ?in|log ?in|github|gmail|google|amazon|"
     r"flipkart|form|scroll|link|url|\.com|\.in)\b",
     ["browser_open", "browser_read", "browser_click", "browser_type", "browser_nav", "browser_tabs"]),
    (r"\b(code|coding|python|script|program|error|bug|fix|debug|traceback|vs ?code|run|calculate|compute|"
     r"convert|how many|prime|factorial|sum|power of|to the power|square root|percent(?:age)?)\b",
     ["run_python", "fix_code", "open_in_vscode", "read_screen_text"]),
    (r"\b(screen|this|that|here|read|showing|see)\b", ["look_at_screen", "read_screen_text"]),
    (r"\b(whats ?app|message|text|email|e-?mail|mail|send|call|tell)\b",
     ["whatsapp_message", "draft_email", "call_and_talk"]),
    (r"\b(task|tasks|to ?do|note|notes|remind|reminder|timer|alarm|minutes|plan)\b",
     ["team_task", "team_note", "set_timer"]),
    (r"\b(ppt|presentation|slides|reel|motion|animat\w*|explainer|ad|edit|trim|cut|caption)\b",
     ["make_presentation", "make_motion_video", "edit_video"]),
    (r"\b(reverse|clone|tech stack|rebuild|inspect)\b", ["website_reverse_engineer"]),
    (r"\b(news|cricket|score|iss|space station)\b", ["live_info"]),
    (r"\b(remember|forget|know about|told you)\b", ["remember_fact", "recall_memory"]),
    (r"\b(order|food|swiggy|zomato|biryani|pizza)\b", ["order_food"]),
]
PHONE_TOOLS = ["pair_phone", "phone_open_app", "phone_tap", "phone_type", "phone_swipe", "phone_key", "phone_call",
               "phone_message", "phone_open_url", "phone_read_screen", "phone_screenshot", "phone_toggle",
               "phone_status", "phone_mirror", "phone_shell", "order_food", "call_and_talk"]
MAX_TOOLS = 22
_last_sel: list[str] = []


def select_tools(text: str, phone_hint: bool = False) -> list:
    """The tools that fit this request: a core set, matching groups, phone tools, matching plug-ins."""
    t = (text or "").lower()
    names: list[str] = []
    if phone_hint or re.search(r"\b(phone|mobile|android)\b", t):
        names += PHONE_TOOLS
    for pattern, group in TOOL_GROUPS:
        if re.search(pattern, t):
            names += group
    if re.search(r"\b(pair|qr)\b", t):
        names.append("pair_phone")
    names += CORE_TOOLS
    names += _last_sel                              # follow-ups ("now pause it") keep last turn's tools
    words = set(re.findall(r"[a-z0-9]{3,}", t))
    for name in _EXTRA_TOOLS:                       # MCP plug-ins: offered when the request mentions them
        if name.startswith("mcp__"):
            parts = set(re.findall(r"[a-z0-9]{3,}", name.lower().replace("mcp__", "")))
            desc = _EXTRA_TOOLS[name]["function"].get("description", "").lower()
            if parts & words or any(w in desc for w in words if len(w) > 4):
                names.append(name)
    by_name = {tool["function"]["name"]: tool for tool in all_tools()}
    out, seen = [], set()
    for n in names:
        if n in by_name and n not in seen:
            seen.add(n)
            out.append(by_name[n])
        if len(out) >= MAX_TOOLS:
            break
    _last_sel[:] = [n for n in seen if n not in CORE_TOOLS][:8]
    return out


def is_tool(name) -> bool:
    return name in TOOL_NAMES or name in _EXTRA_TOOLS


def _is_final(name) -> bool:
    return name in FINAL_TOOLS or name in _EXTRA_FINAL

# single-shot tools: when one of these alone answers the request, skip the
# follow-up model call and reply straight from the tool result (much faster)
FINAL_TOOLS = TOOL_NAMES - {"order_food", "phone_read_screen", "phone_shell", "file_action", "clipboard", "run_powershell", "get_info"}


_extra = {"text": ""}     # instructions from a matched skill (skills.py), for this request only
_ctx = {"text": ""}       # remembered facts that matter for this request (memory.py)


def _set_context(text: str):
    try:
        import memory
        _ctx["text"] = memory.context_for(text)
    except Exception as e:
        print(f"[nlu] memory unavailable: {e}")
        _ctx["text"] = ""


def _system_prompt(phone_hint: bool) -> str:
    who = f" The user's name is {config.USER_NAME}." if config.USER_NAME else ""
    title = getattr(config, "USER_TITLE", "")
    if title:
        who += f" Address the user as '{title}' now and then (e.g. 'Done, {title}.'), like a loyal assistant."
    p = (f"You are {config.ASSISTANT_NAME}, a fast, friendly female voice assistant that fully controls "
         f"the user's Windows PC and their paired Android phone.{who} "
         "When asked to do something, DO it with tools - never explain how. Chain several tools for "
         "multi-step tasks, in order. Use run_powershell for anything no other tool covers. "
         "If unsure what's on the phone screen, call phone_read_screen first. "
         "Replies are spoken aloud: plain English, no markdown, 1-2 short sentences. "
         "If the user is just chatting or asking a question, answer naturally and warmly, "
         "like a friend (up to 3 sentences), and do NOT call a tool. "
         "For long writing use write_document with the full content. "
         "NEVER say you did, opened, showed or started something unless a tool actually did it in this turn - "
         "if the user wants an action, call the tool. Phone pairing / QR code = call pair_phone.")
    if phone_hint:
        p += " This request is about the user's PHONE - use the phone_ tools."
    if _ctx["text"]:
        p += "\n\n" + _ctx["text"]
    if _extra["text"]:
        p += "\n\nFollow this skill for the request:\n" + _extra["text"]
    return p


def _json_prompt(phone_hint: bool, text: str = "") -> str:
    lines = []
    for t in select_tools(text, phone_hint):
        f = t["function"]
        lines.append(f"- {f['name']}({', '.join(f['parameters']['properties'])}): {f['description']}")
    return (_system_prompt(phone_hint) + "\n\nTools:\n" + "\n".join(lines) +
            '\n\nAnswer with ONE JSON object only. To act: {"tool": "<name>", "args": {...}}. '
            'When finished or just talking: {"reply": "<short spoken answer>"}.')


# ---------------------------------------------------------------- chat plumbing

class _NoTools(Exception):
    pass


class Sentences:
    """Collects streamed text and hands out whole sentences as soon as they end."""

    _END = re.compile(r"(?<=[.!?])[\"')\]]*\s+|\n+")

    def __init__(self, emit):
        self.emit = emit
        self.buf = ""
        self.sent: list[str] = []
        self.blocked = False                 # a tool call / JSON started: say nothing

    def add(self, text: str):
        if self.blocked or not text:
            return
        self.buf += text
        if not self.sent and self.buf.lstrip().startswith(("{", "[", "<tool", "```")):
            self.blocked = True
            return
        while True:
            m = self._END.search(self.buf)
            # a comma break keeps a very long first sentence from making her wait
            if not m and not self.sent and len(self.buf) > 140:
                cut = self.buf.rfind(", ", 60)
                if cut > 0:
                    self._out(self.buf[:cut + 1])
                    self.buf = self.buf[cut + 2:]
                    continue
            if not m:
                return
            self._out(self.buf[:m.end()])
            self.buf = self.buf[m.end():]

    def _out(self, piece: str):
        piece = _strip_think(piece).strip()
        if piece and re.search(r"[A-Za-z0-9]", piece):
            self.sent.append(piece)
            self.emit(piece)

    def finish(self) -> str:
        if not self.blocked and self.buf.strip():
            self._out(self.buf)
        self.buf = ""
        return " ".join(self.sent)


def _chat(messages, tools=None, json_format=False, num_predict=None, on_sentence=None):
    opts = dict(OPTIONS)
    if num_predict:
        opts["num_predict"] = num_predict
    if on_sentence and not json_format:
        return _chat_stream(messages, tools, opts, on_sentence)
    payload = {"model": _state["model"], "messages": messages, "stream": False,
               "keep_alive": KEEP_ALIVE, "options": opts}
    if tools:
        payload["tools"] = tools
    if json_format:
        payload["format"] = "json"
    r = _post("/api/chat", payload)
    if r.status_code == 400 and tools and "tool" in r.text.lower():
        raise _NoTools()
    if r.status_code == 404:
        raise RuntimeError(f"model '{_state['model']}' not found - run: ollama pull {_state['model']}")
    if not r.ok:
        raise RuntimeError(f"Ollama error {r.status_code}: {r.text[:200]}")
    return r.json().get("message", {})


def _chat_stream(messages, tools, opts, on_sentence):
    """Same as _chat, but sentences reach on_sentence while the model is still writing.
    Returns the message dict; message['_spoken'] = True if all of it was already sent."""
    payload = {"model": _state["model"], "messages": messages, "stream": True,
               "keep_alive": KEEP_ALIVE, "options": opts}
    if tools:
        payload["tools"] = tools
    r = _session.post(base_url() + "/api/chat", json=payload, timeout=(5, 180), stream=True)
    if r.status_code == 400 and tools and "tool" in r.text.lower():
        raise _NoTools()
    if r.status_code == 404:
        raise RuntimeError(f"model '{_state['model']}' not found - run: ollama pull {_state['model']}")
    if not r.ok:
        raise RuntimeError(f"Ollama error {r.status_code}: {r.text[:200]}")
    sp = Sentences(on_sentence)
    content, calls = "", []
    in_think = False
    for line in r.iter_lines():
        if not line:
            continue
        try:
            chunk = json.loads(line)
        except ValueError:
            continue
        msg = chunk.get("message") or {}
        if msg.get("tool_calls"):
            calls.extend(msg["tool_calls"])
            sp.blocked = True
        piece = msg.get("content") or ""
        content += piece
        # reasoning models think out loud between <think> tags - never speak that
        if "<think>" in piece:
            in_think = True
        if not in_think:
            sp.add(piece)
        if "</think>" in piece:
            in_think = False
            sp.add(piece.split("</think>", 1)[1])
        if chunk.get("done"):
            break
    spoken = sp.finish() if not calls else ""
    out = {"role": "assistant", "content": content}
    if calls:
        out["tool_calls"] = calls
    out["_spoken"] = bool(spoken) and not calls and not sp.blocked
    return out


def _strip_think(text):
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


def _parse_args(args):
    if isinstance(args, str):
        try:
            return json.loads(args)
        except Exception:
            return {}
    return args if isinstance(args, dict) else {}


def parse_json_answer(content):
    """{'tool','args'} | {'chat'} | None from a model's text answer."""
    m = re.search(r"\{.*\}", content or "", flags=re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    name = obj.get("tool") or obj.get("name") or obj.get("action")
    if is_tool(name):
        return {"tool": name, "args": _parse_args(obj.get("args") or obj.get("arguments") or obj.get("parameters") or {})}
    reply = obj.get("reply") or obj.get("response") or obj.get("answer")
    if isinstance(reply, str):
        return {"chat": reply}
    return None


_history: list[dict] = []


def _remember(user, reply):
    _history.extend([{"role": "user", "content": user}, {"role": "assistant", "content": reply}])
    del _history[:-12]


_MULTI = re.compile(r"\b(and|then|after that|also|aur|phir|uske baad)\b|,|;", re.I)


# ---------------------------------------------------------------- agent

_stream = {"fn": None, "spoken": False}


def last_reply_spoken() -> bool:
    """True if the last reply was already said sentence by sentence while streaming."""
    return _stream["spoken"]


def run_agent(text: str, execute, should_stop=lambda: False, phone_hint: bool = False,
              extra: str = "", on_sentence=None) -> str:
    """Runs the request to completion. execute(name, args) -> result string.
    extra = skill instructions added to the system prompt for this request.
    on_sentence = speak each sentence of a chat reply as soon as it's written."""
    _stream.update(fn=on_sentence, spoken=False)
    if not available():
        return ""
    _extra["text"] = extra or ""
    _set_context(text)
    try:
        return _run_agent(text, execute, should_stop, phone_hint)
    finally:
        _extra["text"] = ""
        _stream["fn"] = None


def _run_agent(text, execute, should_stop, phone_hint) -> str:
    multi = bool(_MULTI.search(text))
    results: list[str] = []
    try:
        if _state["tools"] is not False:
            try:
                reply = _agent_tools(text, execute, should_stop, phone_hint, multi, results)
                _state["tools"] = True
            except _NoTools:
                print(f"[nlu] {_state['model']} has no tool calling - using JSON actions.")
                _state["tools"] = False
                reply = _agent_json(text, execute, should_stop, phone_hint, multi, results)
        else:
            reply = _agent_json(text, execute, should_stop, phone_hint, multi, results)
    except requests.Timeout:
        reply = "My brain is taking too long - the model may still be loading. Try again in a moment."
    except requests.ConnectionError:
        _state.update(ok=False, checked_at=0.0)
        reply = "I lost the connection to Ollama. Make sure the Ollama app is running."
    except Exception as e:
        print(f"[nlu] error: {e}")
        reply = " ".join(results) or f"My brain hit an error: {e}"
    reply = reply or " ".join(results[-2:]) or "Done."
    _remember(text, reply)
    return reply


def _agent_tools(text, execute, should_stop, phone_hint, multi, results):
    msgs = [{"role": "system", "content": _system_prompt(phone_hint)}] + _history + \
           [{"role": "user", "content": text}]
    for step in range(_max_steps(text)):
        message = _chat(msgs, tools=select_tools(text, phone_hint), on_sentence=_stream["fn"])
        content = _strip_think(message.get("content", ""))
        if message.get("_spoken"):
            _stream["spoken"] = True
            return content
        calls = []
        for c in message.get("tool_calls") or []:
            fn = c.get("function", {})
            if is_tool(fn.get("name")):
                calls.append((fn["name"], _parse_args(fn.get("arguments", {}))))
        if not calls:
            parsed = parse_json_answer(content) if content.startswith("{") else None
            if parsed and "tool" in parsed:
                calls = [(parsed["tool"], parsed["args"])]
            else:
                return (parsed or {}).get("chat") or content
        msgs.append({"role": "assistant", "content": content, "tool_calls": message.get("tool_calls") or []})
        for name, args in calls:
            res = _run(execute, name, args)
            results.append(res)
            msgs.append({"role": "tool", "content": res, "tool_name": name})
            if should_stop():
                return res
        if step == 0 and not multi and all(_is_final(n) for n, _ in calls):
            return " ".join(results)
    return " ".join(results[-2:])


def _agent_json(text, execute, should_stop, phone_hint, multi, results):
    msgs = [{"role": "system", "content": _json_prompt(phone_hint, text)}] + _history + \
           [{"role": "user", "content": text}]
    for step in range(_max_steps(text)):
        message = _chat(msgs, json_format=True)
        content = _strip_think(message.get("content", ""))
        parsed = parse_json_answer(content)
        if not parsed or "chat" in parsed:
            return (parsed or {}).get("chat") or content
        name, args = parsed["tool"], parsed["args"]
        res = _run(execute, name, args)
        results.append(res)
        if should_stop():
            return res
        if step == 0 and not multi and _is_final(name):
            return res
        msgs += [{"role": "assistant", "content": content},
                 {"role": "user", "content": f"RESULT of {name}: {res}\nContinue, or reply if finished."}]
    return " ".join(results[-2:])


_LONG_TASK = re.compile(r"\b(order|swiggy|zomato|biryani|pizza|food|book|checkout)\b", re.I)


def _max_steps(text: str) -> int:
    """Ordering food etc. needs many taps - give the agent more room."""
    return max(config.AGENT_MAX_STEPS, 16) if _LONG_TASK.search(text or "") else config.AGENT_MAX_STEPS


def _run(execute, name, args) -> str:
    t0 = time.perf_counter()
    try:
        res = str(execute(name, args) or "Done.")
    except Exception as e:
        res = f"{name} failed: {e}"
    print(f"[agent] {name}({json.dumps(args)[:120]}) -> {res[:120]}  ({time.perf_counter() - t0:.2f}s)")
    return res


def quick_answer(text: str, on_sentence=None):
    """Fast path for plain questions: no tool list, short answer. None if it fails.
    With on_sentence the answer streams out sentence by sentence."""
    _stream["spoken"] = False
    if not available():
        return None
    title = getattr(config, "USER_TITLE", "")
    sys = (f"You are {config.ASSISTANT_NAME}, a warm, sharp female voice assistant"
           + (f" for {config.USER_NAME}" if config.USER_NAME else "")
           + (f" (call them '{title}' now and then)" if title else "")
           + ". Answer in one or two short spoken sentences, plain English, no markdown. "
             "If you don't know, say so.")
    _set_context(text)
    if _ctx["text"]:
        sys += " " + _ctx["text"]
    try:
        msg = _chat([{"role": "system", "content": sys}] + _history[-6:] + [{"role": "user", "content": text}],
                    num_predict=110, on_sentence=on_sentence)
        reply = _strip_think(msg.get("content", ""))
        _stream["spoken"] = bool(msg.get("_spoken"))
        if reply:
            _remember(text, reply)
        return reply or None
    except Exception as e:
        print(f"[nlu] quick answer failed: {e}")
        return None


def generate(prompt: str, max_chars: int = 12000, json_format: bool = False):
    """Plain text generation (documents, slide content). None if offline."""
    if not available():
        return None
    try:
        msg = _chat([{"role": "user", "content": prompt}], json_format=json_format, num_predict=2048)
        return _strip_think(msg.get("content", ""))[:max_chars]
    except Exception as e:
        print(f"[nlu] generate failed: {e}")
        return None


if __name__ == "__main__":
    print(f"Connecting to Ollama at {base_url()}")
    if available(force=True):
        print("  models:", ", ".join(installed_models()))
        print("  using:", model_name())
        fake = lambda n, a: f"(pretend ran {n} {a})"   # noqa: E731
        for q in ("open notepad", "open notepad and type hello", "what is the capital of japan"):
            t0 = time.time()
            print(f"\n> {q}\n  -> {run_agent(q, fake)}  ({time.time() - t0:.1f}s)")
    else:
        print("  PROBLEM:", status_reason())
