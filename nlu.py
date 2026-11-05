"""
The AI brain - a local agent powered by Ollama (no API key, no cloud).

commands.py answers common phrases instantly with patterns. Everything
else comes here: the model picks one or more tools, Hinata runs them,
feeds the results back, and the model continues until the job is done
(up to AGENT_MAX_STEPS actions) - so "open notepad and write a poem about
rain" or "on my phone open WhatsApp, tap Vishal and type hi" just work.

Speed tricks:
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
OPTIONS = {"temperature": config.AI_TEMPERATURE, "num_ctx": 4096, "num_predict": 400}

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

# single-shot tools: when one of these alone answers the request, skip the
# follow-up model call and reply straight from the tool result (much faster)
FINAL_TOOLS = TOOL_NAMES - {"order_food", "phone_read_screen", "phone_shell", "file_action", "clipboard", "run_powershell", "get_info"}


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
    return p


def _json_prompt(phone_hint: bool) -> str:
    lines = []
    for t in TOOLS:
        f = t["function"]
        lines.append(f"- {f['name']}({', '.join(f['parameters']['properties'])}): {f['description']}")
    return (_system_prompt(phone_hint) + "\n\nTools:\n" + "\n".join(lines) +
            '\n\nAnswer with ONE JSON object only. To act: {"tool": "<name>", "args": {...}}. '
            'When finished or just talking: {"reply": "<short spoken answer>"}.')


# ---------------------------------------------------------------- chat plumbing

class _NoTools(Exception):
    pass


def _chat(messages, tools=None, json_format=False, num_predict=None):
    opts = dict(OPTIONS)
    if num_predict:
        opts["num_predict"] = num_predict
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
    if name in TOOL_NAMES:
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

def run_agent(text: str, execute, should_stop=lambda: False, phone_hint: bool = False) -> str:
    """Runs the request to completion. execute(name, args) -> result string."""
    if not available():
        return ""
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
        message = _chat(msgs, tools=TOOLS)
        content = _strip_think(message.get("content", ""))
        calls = []
        for c in message.get("tool_calls") or []:
            fn = c.get("function", {})
            if fn.get("name") in TOOL_NAMES:
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
        if step == 0 and not multi and all(n in FINAL_TOOLS for n, _ in calls):
            return " ".join(results)
    return " ".join(results[-2:])


def _agent_json(text, execute, should_stop, phone_hint, multi, results):
    msgs = [{"role": "system", "content": _json_prompt(phone_hint)}] + _history + \
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
        if step == 0 and not multi and name in FINAL_TOOLS:
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
