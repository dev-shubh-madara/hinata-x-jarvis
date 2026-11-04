"""
The router. Turns what you said into action, as fast as possible:

  1. confirmations ("confirm" / "cancel") for anything waiting on you
  2. instant patterns - common commands run with zero AI delay
  3. "on my phone ..." -> phone fast path, else the AI with phone tools
  4. everything else -> the local AI agent (nlu.py), which can chain tools
  5. AI offline -> free web answer, then a Google search (never a dead end)
"""

import json
import re
import time

import config
import nlu
import pc_actions as pc
import phone_control as phone
import phone_pair
import live_info
import vision
import web_answer
from pc_actions import Confirm

_overlay = None
_speak = None
_pending: dict | None = None        # {"kind", "payload", "at"}
_created_pending = False
_acted = False          # did this command do real work on the PC / phone?
_info_reply = False     # was it only a read-out (time, weather, battery...)?
INFO_TOOLS = {"get_info", "look_at_screen", "live_info"}

PHONE_PHRASES = [r"\b(?:do (?:this|it) )?(?:on|in|into|from|using) (?:my|the) (?:phone|mobile)\b[,:]?",
                 r"\bphone (?:pe|par|me|mein)\b[,:]?", r"^(?:phone|mobile)[,:]\s*"]
_MULTI = re.compile(r"\b(and|then|after that|also)\b|,|;", re.I)
CONFIRM_WORDS = {"confirm", "yes", "yes confirm", "do it", "yes do it", "go ahead", "confirmed", "haan",
                 "ok do it", "okay do it", "sure", "yes please", "proceed", "confirm it"}
_CANCEL_RE = re.compile(r"\b(cancel|never ?mind|don'?t|do not|abort|nahi|stop it)\b")
_AI_CALL = re.compile(r"^(?:(?:can|could|will) you |please |hey |okay |ok )*(?:call|phone|ring)(?: up)? (.+?)"
                      r"(?: (?:on|from) my phone)? (?:and|to) ((?:tell|inform|let|ask|say|remind|wish)\b.*)$")
_LOOK = re.compile(r"\b(what(?:'s| is| are) (?:this|that|these|on (?:my|the) screen)|what (?:is|'s) (?:this|that) (?:video|error|page|code)|"
                   r"how (?:do|can|should) i .*\b(?:this|here|it)\b|read (?:this|my screen|the screen)|"
                   r"what does (?:this|that|it)(?: \w+)? (?:say|mean)|look at (?:my|the) screen|what am i (?:looking at|watching)|"
                   r"(?:explain|summari[sz]e) (?:this|my screen|the screen)|(?:see|check) (?:my|the) screen)\b")
CANCEL_WORDS = {"cancel", "no", "stop", "don't", "do not", "nahi", "never mind", "nevermind", "cancel it", "abort"}


def set_overlay(overlay):
    global _overlay
    _overlay = overlay


def set_speaker(fn):
    global _speak
    _speak = fn


# ---------------------------------------------------------------- confirmations

def _ask(c: Confirm) -> str:
    global _pending, _created_pending
    _pending = {"kind": c.kind, "payload": c.payload, "at": time.time()}
    _created_pending = True
    return c.question


def _resolve_pending(t: str):
    global _pending, _acted
    if _pending is None:
        return None
    first = re.sub(r"[^a-z' ]", "", t).strip()
    if time.time() - _pending["at"] > config.CONFIRM_SECONDS:
        _pending = None
        return "That request timed out, so I didn't do it." if first.split(" ")[0] in ("confirm", "yes") else None
    if first in CANCEL_WORDS or _CANCEL_RE.search(first):
        _pending = None
        return "Cancelled."
    if _pending["kind"] == "phone_pay" and not re.search(r"\b(confirm|pay)\b", first) and \
            first in CONFIRM_WORDS:
        _pending["at"] = time.time()
        return "This spends money, so please say the word confirm to pay."
    if first in CONFIRM_WORDS or first.startswith("confirm") or \
            (_pending["kind"] == "phone_pay" and re.fullmatch(r"(yes )?(pay|pay it|pay now)", first)):
        p, _pending = _pending, None
        kind, payload = p["kind"], p["payload"]
        _acted = True
        if kind == "system":
            return pc.do_system(payload)
        if kind == "delete":
            return pc.do_delete(payload)
        if kind == "powershell":
            out = pc.execute_powershell(payload)
            return out if len(out) < 300 else "Done. " + out[:300]
        if kind == "phone_call":
            return phone.place_call(payload)
        if kind == "phone_sms":
            return phone.send_composed()
        if kind == "phone_pay":
            x, y, _label = payload
            phone.tap_point(x, y)
            return phone.after_payment()
        if kind == "ai_call":
            import call_agent
            return call_agent.start(payload, speak_status=_speak, overlay=_overlay)
        if kind == "phone_shell":
            out = phone.execute_shell(payload)
            return out if len(out) < 300 else "Done. " + out[:300]
    _pending = None        # she was told something else - the old request is dropped, so a
    return None            # later stray "yes" can never trigger it


def _hide_hologram():
    """Close the full-screen hologram so whatever she opens (QR panel, apps) is visible."""
    if _overlay:
        _overlay.collapse()
        time.sleep(0.5)


def _ghost_for_capture():
    if _overlay:
        _overlay.ghost(True)
        import threading
        threading.Timer(0.8, lambda: _overlay.ghost(False)).start()


def _info(reply):
    """Mark a reply as a read-out only - the hologram can stay open for those."""
    global _info_reply
    _info_reply = True
    return reply


def last_outcome() -> str:
    """'confirm' = waiting for your yes/no, 'action' = she did real work, 'chat' = just talking."""
    if _created_pending:
        return "confirm"
    return "action" if _acted else "chat"


_END_PATTERNS = [
    r"(lets|let us) (continue|carry on|get back|go back)( with| to)?( our| the| my)?( work)?",
    r"(continue|back)( with| to)?( our| the| my)? work",
    r"(thats|that is|were|we are) (all|done)( for now)?",
    r"(bye|goodbye|good night|see you|see you later|thanks|thank you|thank you so much|thanks a lot)",
    r"(go to sleep|you can go|dismiss|close yourself|stand by|standby|go back to sleep)",
    r"(close|exit|stop|quit|shut up|hide|minimi[sz]e)( it| yourself| this| the hologram| hologram| now)?",
    r"(band karo|bas|bas karo|chalo bye|ruk jao|close karo)",
]
_FILLER = {"ok", "okay", "hey", "hinata", "alright", "so", "now", "well", "please", "x", "helper"}


def is_end_phrase(text: str) -> bool:
    """'okay Hinata, let's continue with our work' / 'that's all' / 'bye' - ends the chat."""
    words = [w for w in re.sub(r"[^a-z' ]", " ", text.lower()).replace("'", "").split() if w not in _FILLER]
    flat = " ".join(words)
    return bool(flat) and any(re.fullmatch(p, flat) for p in _END_PATTERNS)


def _should_stop() -> bool:
    return _created_pending


# ---------------------------------------------------------------- tool executor (shared by AI + fast path)

def execute(name: str, a: dict):
    global _acted
    a = a or {}
    g = lambda k, d="": a.get(k, d) if a.get(k) is not None else d   # noqa: E731
    if name == "pair_phone":
        _hide_hologram()
    res = _execute(name, a, g)
    if name not in INFO_TOOLS:
        _acted = True
    return _ask(res) if isinstance(res, Confirm) else res


def _execute(name, a, g):
    if name == "open_target":
        return pc.open_target(str(g("target")))
    if name == "close_app":
        return pc.close_app(str(g("name")))
    if name == "play_media":
        return pc.play_media(str(g("query")), str(g("platform", "youtube")))
    if name == "search_web":
        return pc.search_web(str(g("query")))
    if name == "type_text":
        return pc.type_text(str(g("text")))
    if name == "press_keys":
        return pc.press_keys(str(g("keys")))
    if name == "window":
        return pc.window(str(g("action")))
    if name == "volume":
        return pc.volume(str(g("action")), a.get("level"))
    if name == "set_brightness":
        return pc.set_brightness(g("level", 70))
    if name == "media_control":
        return pc.media_control(str(g("action")))
    if name == "system_control":
        return pc.system_control(str(g("action")))
    if name == "open_settings":
        return pc.open_settings(str(g("page")))
    if name == "write_document":
        content = str(g("content")).strip() or (nlu.generate(f"Write: {g('title')}") or "")
        if not content:
            return "I couldn't write that right now."
        return pc.write_document(str(g("title", "note")), content, str(g("extension", "txt")))
    if name == "make_presentation":
        return _presentation(str(g("topic", "presentation")), int(g("slides", 6) or 6))
    if name == "take_screenshot":
        return pc.take_screenshot()
    if name == "file_action":
        return pc.file_action(str(g("action")), str(g("path")), str(g("destination")))
    if name == "clipboard":
        return pc.clipboard(str(g("action", "read")), str(g("text")))
    if name == "set_timer":
        return pc.set_timer(g("minutes", 1), str(g("label")), _timer_done)
    if name == "get_info":
        return pc.get_info(str(g("kind", "time")), str(g("city")))
    if name == "run_powershell":
        return pc.run_powershell(str(g("command")), str(g("purpose")))
    # ---- phone
    if name == "pair_phone":
        return phone_pair.pair_with_qr(_overlay)
    if name == "phone_open_app":
        return phone.open_app(str(g("name")))
    if name == "phone_tap":
        r = phone.tap_text(str(g("target")))
        return Confirm("phone_pay", r[1], phone.pay_question(r)) if isinstance(r, tuple) else r
    if name == "order_food":
        return phone.order_food(str(g("item")), str(g("app", "swiggy")), str(g("restaurant")))
    if name == "look_at_screen":
        return vision.look(str(g("question")), hide_overlay=_ghost_for_capture)
    if name == "live_info":
        kind = str(g("kind", "news")).lower()
        if kind == "iss":
            _hide_hologram()                           # the live map opens - let him see it
            return live_info.iss()
        if kind == "cricket":
            return live_info.cricket()
        return live_info.news(str(g("topic")))
    if name == "call_and_talk":
        import call_agent
        return call_agent.prepare(str(g("who")), str(g("message")))
    if name == "phone_type":
        return phone.type_text(str(g("text")))
    if name == "phone_swipe":
        return phone.swipe(str(g("direction", "up")))
    if name == "phone_key":
        return phone.press_key(str(g("key", "home")))
    if name == "phone_call":
        reply, number = phone.dial(str(g("who")))
        return Confirm("phone_call", number, reply) if number else reply
    if name == "phone_message":
        reply, ok = phone.compose_sms(str(g("who")), str(g("text")))
        return Confirm("phone_sms", None, reply) if ok else reply
    if name == "phone_open_url":
        return phone.open_url(str(g("query")))
    if name == "phone_read_screen":
        return phone.read_screen()
    if name == "phone_screenshot":
        return phone.screenshot()
    if name == "phone_toggle":
        on = a.get("on", True)
        return phone.toggle(str(g("feature")), on if isinstance(on, bool) else str(on).lower() in ("true", "on", "1"))
    if name == "phone_status":
        return phone.battery()
    if name == "phone_shell":
        res = phone.run_shell(a.get("command", ""))
        if isinstance(res, tuple):
            return Confirm("phone_shell", res[1], "That changes your phone a lot. Say confirm to run it, or cancel.")
        return res
    if name == "phone_mirror":
        return phone.mirror()
    return f"I don't have a tool called {name}."


def _timer_done(msg):
    if _overlay:
        _overlay.flash(msg)
    if _speak:
        _speak(msg)


def _presentation(topic: str, slides: int = 6) -> str:
    slides = max(3, min(12, slides))
    raw = nlu.generate(
        f"Create a {slides}-slide presentation outline about: {topic}. "
        'Return JSON: {"slides": [{"title": "...", "bullets": ["...", "..."]}]} '
        "with 3-5 short informative bullets (max 14 words) per slide. No intro/title slide.",
        json_format=True)
    outline = []
    try:
        outline = json.loads(re.search(r"\{.*\}", raw or "", re.S).group(0)).get("slides", [])
    except Exception:
        pass
    if not outline:
        outline = [{"title": f"Overview of {topic}", "bullets": [f"What {topic} is", f"Why {topic} matters",
                                                                 "Key ideas", "Summary"]}]
    return pc.make_presentation(topic, outline)


# ---------------------------------------------------------------- instant patterns

def _fast_path(t: str, raw: str):
    """Common commands with zero AI delay. Returns a reply or None."""
    if t in ("stop", "quiet", "shut up", "be quiet", "stop talking", "chup"):
        return _info("")
    if re.search(r"\b(what(?:'s| is) the (?:time|date)|what time is it|today'?s date|time now|kya time)\b", t):
        return _info(pc.time_reply())
    if t in ("pause", "resume", "play", "play music", "pause music", "resume music", "stop music"):
        return pc.media_control("play_pause")
    if re.search(r"\b(next|skip) (song|track)\b", t):
        return pc.media_control("next")
    if re.search(r"\bprevious (song|track)\b", t):
        return pc.media_control("previous")

    if (m := re.fullmatch(r"play (.+?)(?: on (youtube music|youtube|spotify))?", t)):
        return pc.play_media(m.group(1), m.group(2) or "youtube")
    if (m := re.fullmatch(r"(?:open|launch|start) (.+?)(?: settings)?", t)) and "settings" in t and \
            m.group(1).replace(" settings", "") in pc.SETTINGS_PAGES:
        return pc.open_settings(m.group(1).replace(" settings", ""))
    if (m := re.fullmatch(r"(?:open|launch|start|kholo) (.+)", t)):
        return pc.open_target(m.group(1))
    if (m := re.fullmatch(r"(?:close|quit|exit|band karo) (.+)", t)):
        return pc.close_app(m.group(1))
    if (m := re.fullmatch(r"(?:search|google)(?: for)? (.+)", t)):
        return pc.search_web(m.group(1))
    if (m := re.fullmatch(r"type (.+)", t)):
        return pc.type_text(raw.strip()[5:] if raw.strip().lower().startswith("type ") else m.group(1))
    if (m := re.fullmatch(r"(?:press|hit) ((?:ctrl|control|alt|shift|win|windows|enter|esc|escape|tab|f\d+)"
                          r"(?:\s*(?:\+|plus)\s*\w+)*)", t)):
        return pc.press_keys(m.group(1))
    if re.fullmatch(r"(?:take a )?screenshot|capture (?:the )?screen", t):
        return pc.take_screenshot()

    if (m := re.search(r"volume (?:to )?(\d{1,3})", t)):
        return pc.volume("set", int(m.group(1)))
    if re.search(r"\b(volume up|louder|increase (?:the )?volume)\b", t):
        return pc.volume("up")
    if re.search(r"\b(volume down|quieter|decrease (?:the )?volume|lower (?:the )?volume)\b", t):
        return pc.volume("down")
    if re.fullmatch(r"unmute", t):
        return pc.volume("unmute")
    if re.fullmatch(r"mute", t):
        return pc.volume("mute")
    if (m := re.search(r"brightness (?:to )?(\d{1,3})", t)):
        return pc.set_brightness(int(m.group(1)))

    if re.fullmatch(r"(?:show (?:the )?desktop|minimi[sz]e (?:all|everything))", t):
        return pc.window("show_desktop")
    if re.fullmatch(r"minimi[sz]e(?: (?:this|it|the window))?", t):
        return pc.window("minimize")
    if re.fullmatch(r"maximi[sz]e(?: (?:this|it|the window))?", t):
        return pc.window("maximize")
    if re.fullmatch(r"(?:switch|change) (?:the )?window", t):
        return pc.window("switch")

    if "battery" in t:
        return _info(phone.battery() if re.search(r"\b(phone|mobile)\b", t) else pc.get_info("battery"))
    if re.search(r"cpu temp|processor temp", t):
        return _info(pc.get_info("cpu_temp"))
    if re.search(r"system (?:status|stats|info)|how(?:'s| is) (?:my )?(?:pc|laptop|computer) doing", t):
        return _info(pc.get_info("system_stats"))
    if (m := re.fullmatch(r"(?:what'?s the )?weather(?: like)?(?: in (.+))?(?: today)?", t)):
        return _info(pc.get_info("weather", m.group(1) or ""))

    if (m := re.search(r"(?:set (?:a )?timer|remind me) (?:for |in )?(\d+(?:\.\d+)?) ?(second|sec|minute|min|hour)s?"
                       r"(?: (?:to|that|about) (.+))?", t)):
        n, unit = float(m.group(1)), m.group(2)
        minutes = n / 60 if unit.startswith("sec") else n * 60 if unit == "hour" else n
        return pc.set_timer(minutes, m.group(3) or "", _timer_done)

    if re.fullmatch(r"lock(?: (?:the|my) (?:pc|laptop|computer|screen))?|lock (?:pc|laptop|screen)", t):
        return pc.system_control("lock")
    if re.fullmatch(r"(?:put (?:the )?(?:pc|laptop|computer) to )?sleep(?: mode)?", t):
        return pc.system_control("sleep")
    if re.search(r"\bshut ?down\b", t):
        return pc.system_control("shutdown")
    if re.search(r"\brestart\b", t) and re.search(r"\b(pc|computer|laptop|system)\b", t):
        return pc.system_control("restart")
    if re.search(r"empty (?:the )?recycle bin", t):
        return pc.system_control("empty_recycle_bin")

    if (m := re.fullmatch(r"(?:make|create|generate) (?:a |an )?(?:ppt|powerpoint|presentation|slides?)"
                          r"(?: (?:about|on|for))? (.+)", t)):
        return _presentation(m.group(1))
    if (m := re.fullmatch(r"(?:write|create|make) (?:me )?(?:a |an )?(essay|poem|story|letter|note|notes|article|"
                          r"email|speech|summary|report|application)(?: (?:about|on|for|to))? (.+)", t)):
        kind, topic = m.groups()
        text = nlu.generate(f"Write a {kind} about {topic}. Plain text, no markdown.")
        if not text:
            return None
        return pc.write_document(f"{kind} {topic}", text)
    if re.fullmatch(r"run .+", t):
        m = re.search(r"\brun\s+(.+)", raw, re.I)
        return pc.run_powershell(m.group(1).strip(" .") if m else t[4:])
    return None


# ---------------------------------------------------------------- main entry

def _phone_split(text: str):
    """'On my phone, text Mom saying Hi' -> 'text Mom saying Hi' (case kept)."""
    for p in PHONE_PHRASES:
        if re.search(p, text, re.I):
            return re.sub(r"\s+", " ", re.sub(p, " ", text, flags=re.I)).strip(" ,.")
    return None


def handle(text: str) -> str:
    """Executes a command and returns the reply to speak."""
    global _created_pending, _acted, _info_reply
    _created_pending = False
    _acted = False
    _info_reply = False
    raw = text.strip()
    t = re.sub(r"\s+", " ", raw.lower()).strip(" .!?")
    if config.ASSISTANT_NAME and t.startswith(("hinata ", "hey hinata ")):
        t = t.split(" ", 2 if t.startswith("hey") else 1)[-1]

    r = _resolve_pending(t)
    if r is not None:
        return r

    # ---- phone pairing / connecting
    if re.search(r"\b(pair|pairing|re-?pair)\b|\bqr\b|\b(connect|link|attach|jod)\b.*\b(phone|mobile|android)\b", t) \
            and not re.search(r"\b(earphone|headphone|airpods|buds|bluetooth speaker)\b", t):
        _acted = True
        if "pair" in t or "qr" in t or not phone_pair._load():
            _hide_hologram()
            return phone_pair.pair_with_qr(_overlay)
        return phone_pair.connect_existing()

    # ---- "call mom and tell her I'll be late" -> Hinata does the talking
    if (m := _AI_CALL.match(t)):
        _acted = True
        import call_agent
        res = call_agent.prepare(m.group(1).removeprefix("my ").strip(), m.group(2))
        return _ask(res) if isinstance(res, Confirm) else res

    # ---- screen vision / live info (instant routes)
    if _LOOK.search(t) and not _phone_split(raw):
        return _info(vision.look(raw, hide_overlay=_ghost_for_capture))
    if re.search(r"\b(iss|space station)\b", t):
        _acted = True                                  # opens the live map
        _hide_hologram()
        return live_info.iss()
    if (m := re.search(r"\b(?:news|headlines)\b(?: (?:about|on|of) (.+))?", t)) and len(t.split()) <= 9:
        return _info(live_info.news(m.group(1) or ""))
    if re.search(r"\bcricket\b.*\b(score|match|live)\b|\b(score|match)\b.*\bcricket\b", t):
        return _info(live_info.cricket())

    # ---- phone commands
    phone_cmd = _phone_split(raw)
    if phone_cmd is not None:
        _acted = bool(phone_cmd)
        if not _MULTI.search(phone_cmd):
            res = phone.handle(phone_cmd)
            if isinstance(res, tuple):
                return _ask(Confirm(res[1], res[2], res[3]))
            if res is not None:
                return res
        if not phone.ensure_connected():
            return phone.NOT_CONNECTED
        if nlu.available():
            return nlu.run_agent(raw, execute, _should_stop, phone_hint=True)
        return "I didn't understand that phone command, and my AI brain is offline."

    # ---- instant patterns (single-step requests only)
    multi = bool(_MULTI.search(t)) and nlu.available()
    if not multi:
        try:
            res = _fast_path(t, raw)
        except Exception as e:
            print(f"[commands] fast path error: {e}")
            res = None
        if isinstance(res, Confirm):
            return _ask(res)
        if res is not None:
            _acted = _acted or not _info_reply
            return res

    # ---- the AI agent
    if nlu.available():
        return nlu.run_agent(raw, execute, _should_stop)

    print(f"[commands] AI brain offline: {nlu.status_reason()}")
    found = web_answer.answer(raw)
    if found:
        return found
    _acted = True
    pc.search_web(raw)
    return f"My AI brain is offline, so I searched the web for that. {nlu.status_reason()}"
