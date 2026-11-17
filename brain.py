"""
The big brain - for big jobs (motion videos, the desktop agent, website rebuild plans).

Quick answers and normal commands stay on the local model in nlu.py (fast, free,
private). Big jobs use the strongest brain you have:

  1. a cloud model, if you added a key ("add my API key" - Hinata asks for it once)
       Claude  (sk-ant-...)   Gemini  (AIza...)   Groq  (gsk_...)
  2. otherwise the bigger local model BIG_LOCAL_MODEL, if it's downloaded
  3. otherwise the normal fast local model

Keys are saved in Hinata's data folder (keys.json), never in the project folder,
so they can't end up on GitHub. Environment variables work too:
ANTHROPIC_API_KEY, GEMINI_API_KEY, GROQ_API_KEY.
"""

import json
import os
import re
import threading

import requests

import config
import nlu

_FILE = os.path.join(config.DATA_DIR, "keys.json")
ENV = {"claude": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}
NAMES = {"claude": "Claude", "gemini": "Gemini", "groq": "Groq"}
ORDER = ("claude", "gemini", "groq")

_session = requests.Session()
_state = {"gemini_model": None, "pull_started": False, "last_error": ""}


# ---------------------------------------------------------------- keys

def _load() -> dict:
    try:
        with open(_FILE, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def keys() -> dict:
    d = {k: v for k, v in _load().items() if k in ENV and v}
    for p, var in ENV.items():
        if not d.get(p) and os.environ.get(var):
            d[p] = os.environ[var].strip()
    return d


def detect_provider(key: str):
    key = (key or "").strip()
    if key.startswith("sk-ant-"):
        return "claude"
    if key.startswith("AIza"):
        return "gemini"
    if key.startswith("gsk_"):
        return "groq"
    return None


def save_key(key: str, provider: str | None = None) -> str:
    key = (key or "").strip().strip('"').strip()
    provider = provider or detect_provider(key)
    if not key or provider not in ENV:
        return "That doesn't look like a Claude, Gemini or Groq key. Claude keys start with sk-ant, Gemini with AIza, Groq with gsk."
    d = _load()
    d[provider] = key
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f)
    ok = test(provider)
    if ok:
        return f"{NAMES[provider]} key saved and working. Big jobs will use {NAMES[provider]} now."
    return f"I saved the {NAMES[provider]} key, but a test call failed: {_state['last_error'] or 'no answer'}."


def remove_key(provider: str | None = None) -> str:
    d = _load()
    gone = [p for p in list(d) if provider in (None, p)]
    for p in gone:
        d.pop(p, None)
    with open(_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f)
    return "Removed the key." if gone else "There was no key to remove."


def provider():
    """The cloud provider big jobs will use, or None for local only."""
    want = str(getattr(config, "CLOUD_AI", "auto") or "auto").lower()
    if want == "off":
        return None
    k = keys()
    if want in ENV:
        return want if k.get(want) else None
    return next((p for p in ORDER if k.get(p)), None)


def describe() -> str:
    p = provider()
    if p:
        return f"{NAMES[p]} in the cloud"
    big = _big_local()
    return f"the local model {big or nlu.model_name() or 'Ollama'}"


# ---------------------------------------------------------------- public API

def ask(prompt: str, system: str = "", max_tokens: int = 4096, json_mode: bool = False,
        timeout: float = 150, local_only: bool = False):
    """One prompt in, text out. Cloud first (if a key is set), then local. None if nothing answers."""
    p = None if local_only else provider()
    if p:
        try:
            out = {"claude": _claude, "gemini": _gemini, "groq": _groq}[p](
                prompt, system, max_tokens, json_mode, timeout)
            if out:
                return out
        except Exception as e:
            _state["last_error"] = str(e)[:200]
            print(f"[brain] {p} failed, using the local model: {e}")
    return _local(prompt, system, max_tokens, json_mode, timeout)


def ask_json(prompt: str, system: str = "", max_tokens: int = 4096, **kw):
    """Like ask(), but returns a parsed dict/list (one retry with a stricter nudge)."""
    for attempt in range(2):
        text = ask(prompt if not attempt else prompt + "\n\nReturn ONLY valid JSON. No comments, no markdown.",
                   system, max_tokens, json_mode=True, **kw)
        obj = parse_json(text)
        if obj is not None:
            return obj
    return None


def parse_json(text):
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    try:
        return json.loads(text)
    except Exception:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = text.find(open_c)
        end = text.rfind(close_c)
        if start != -1 and end > start:
            chunk = text[start:end + 1]
            try:
                return json.loads(chunk)
            except Exception:
                try:                                    # trailing commas are the usual small-model slip
                    return json.loads(re.sub(r",\s*([}\]])", r"\1", chunk))
                except Exception:
                    continue
    return None


def test(p: str) -> bool:
    try:
        out = {"claude": _claude, "gemini": _gemini, "groq": _groq}[p]("Reply with the word ok.", "", 20, False, 30)
        return bool(out)
    except Exception as e:
        _state["last_error"] = str(e)[:200]
        return False


# ---------------------------------------------------------------- cloud providers

def _models():
    return dict({"claude": "claude-sonnet-5-5", "gemini": "gemini-flash-latest",
                 "groq": "llama-3.3-70b-versatile"}, **(getattr(config, "CLOUD_MODELS", {}) or {}))


def _claude(prompt, system, max_tokens, json_mode, timeout):
    body = {"model": _models()["claude"], "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]}
    if system:
        body["system"] = system
    r = _session.post("https://api.anthropic.com/v1/messages", json=body, timeout=timeout,
                      headers={"x-api-key": keys()["claude"], "anthropic-version": "2023-06-01"})
    if not r.ok:
        raise RuntimeError(f"Claude {r.status_code}: {r.text[:160]}")
    return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text").strip()


def _gemini_pick(key):
    """Finds a working 'flash' model when the configured name doesn't exist any more."""
    r = _session.get("https://generativelanguage.googleapis.com/v1beta/models", timeout=20,
                     headers={"x-goog-api-key": key})
    names = [m["name"].split("/", 1)[-1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    flash = [n for n in names if "flash" in n and "lite" not in n and "image" not in n and "tts" not in n]
    pick = (sorted(flash, reverse=True) or names or [None])[0]
    _state["gemini_model"] = pick
    return pick


def _gemini(prompt, system, max_tokens, json_mode, timeout):
    key = keys()["gemini"]
    model = _state["gemini_model"] or _models()["gemini"]
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.5}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    for attempt in range(2):
        r = _session.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                          json=body, timeout=timeout, headers={"x-goog-api-key": key})
        if r.status_code == 404 and not attempt:
            model = _gemini_pick(key)
            if model:
                continue
        if not r.ok:
            raise RuntimeError(f"Gemini {r.status_code}: {r.text[:160]}")
        break
    parts = (r.json().get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts).strip()


def _groq(prompt, system, max_tokens, json_mode, timeout):
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    body = {"model": _models()["groq"], "messages": msgs, "max_tokens": min(max_tokens, 8000), "temperature": 0.5}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = _session.post("https://api.groq.com/openai/v1/chat/completions", json=body, timeout=timeout,
                      headers={"Authorization": f"Bearer {keys()['groq']}"})
    if not r.ok:
        raise RuntimeError(f"Groq {r.status_code}: {r.text[:160]}")
    return (r.json()["choices"][0]["message"].get("content") or "").strip()


# ---------------------------------------------------------------- local

def _big_local():
    want = (getattr(config, "BIG_LOCAL_MODEL", "") or "").strip()
    if not want or not nlu.available():
        return None
    try:
        for n in nlu.installed_models():
            if n == want or n.startswith(want):
                return n
    except Exception:
        pass
    return None


def download_big_model() -> str:
    """Pulls BIG_LOCAL_MODEL in the background (one time, a few GB)."""
    want = (getattr(config, "BIG_LOCAL_MODEL", "") or "").strip()
    if not want:
        return "No big local model is set in config."
    if _big_local():
        return f"{want} is already downloaded."
    if _state["pull_started"]:
        return f"{want} is already downloading."
    if not nlu.available():
        return "Ollama isn't running, so I can't download the model yet."
    _state["pull_started"] = True

    def run():
        try:
            print(f"[brain] downloading {want} (one time) ...")
            nlu._post("/api/pull", {"model": want, "stream": False}, timeout=(5, 7200))
            print(f"[brain] {want} ready")
        except Exception as e:
            print(f"[brain] download failed: {e}")
        _state["pull_started"] = False
    threading.Thread(target=run, daemon=True, name="big-model").start()
    return f"Downloading {want} in the background. Big jobs get smarter once it's done."


def _local(prompt, system, max_tokens, json_mode, timeout):
    if not nlu.available():
        return None
    model = _big_local() or nlu.model_name()
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    payload = {"model": model, "messages": msgs, "stream": False, "keep_alive": nlu.KEEP_ALIVE,
               "options": {"temperature": 0.4, "num_ctx": 8192, "num_predict": max_tokens}}
    if json_mode:
        payload["format"] = "json"
    try:
        r = nlu._post("/api/chat", payload, timeout=(5, timeout))
        if not r.ok:
            print(f"[brain] local model error {r.status_code}: {r.text[:120]}")
            return None
        return nlu._strip_think(r.json().get("message", {}).get("content", ""))
    except Exception as e:
        print(f"[brain] local model failed: {e}")
        return None
