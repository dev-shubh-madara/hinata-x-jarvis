"""
WhatsApp from the laptop - "WhatsApp Vishal saying I'll be there at 5".

Hinata opens WhatsApp Desktop, searches the name you said, opens that chat,
types your message and sends it - no number, no country code. The agent
cursor shows each step.

She only sends when the chat she found matches the name: an exact match, or
the only chat with that name in it. If two chats fit ("Rahul" and "Rahul
College") she tells you both and waits for the full name.

Fallback when the app can't be driven: the phone number from Hinata's contact
book ("save contact Vishal 98765 43210") or your phone's contacts.
Set WHATSAPP_AUTO_SEND = False in config.py to hear it read back first.
"""

import json
import os
import re
import time
from urllib.parse import quote

import config

_FILE = os.path.join(config.DATA_DIR, "contacts.json")


def _load() -> dict:
    try:
        with open(_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(d: dict):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)


def clean_number(text: str) -> str:
    """'98765 43210' -> '919876543210' (country code from config when missing)."""
    digits = re.sub(r"\D", "", text or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 10:
        digits = str(getattr(config, "DEFAULT_COUNTRY_CODE", "91")) + digits
    return digits if 11 <= len(digits) <= 15 else ""


def clean_name(name: str) -> str:
    n = re.sub(r"^(my |to )+", "", (name or "").strip().lower())
    return re.sub(r"\s+", " ", n).strip(" .,")


def save_contact(name: str, number: str) -> str:
    num = clean_number(number)
    name = clean_name(name)
    if not name or not num:
        return "I need a name and a full phone number, like: save contact Vishal 98765 43210."
    d = _load()
    d[name] = num
    _save(d)
    return f"Saved {name.title()}."


def find_number(name: str) -> tuple[str, str] | None:
    """(display name, number) from the contact book, then the phone's contacts."""
    key = clean_name(name)
    if clean_number(key):
        return key, clean_number(key)
    d = _load()
    if key in d:
        return key.title(), d[key]
    close = [k for k in d if key and (key in k or k in key)]
    if len(close) == 1:
        return close[0].title(), d[close[0]]
    try:
        import phone_control
        if phone_control.is_connected():
            hit = phone_control.resolve_number(key)
            if hit and clean_number(hit[1]):
                d[clean_name(hit[0])] = clean_number(hit[1])
                _save(d)
                return hit[0], clean_number(hit[1])
    except Exception as e:
        print(f"[whatsapp] phone contact lookup failed: {e}")
    return None


def _open_chat(number: str, message: str = ""):
    url = f"whatsapp://send?phone={number}"
    if message:
        url += "&text=" + quote(message)
    try:
        os.startfile(url)                                   # WhatsApp desktop app
    except OSError:
        import webbrowser
        webbrowser.open(f"https://wa.me/{number}" + (f"?text={quote(message)}" if message else ""))


def tidy(message: str) -> str:
    m = (message or "").strip().strip('"').strip()
    return m[:1].upper() + m[1:] if m else m


# ---------------------------------------------------------------- by name, inside the WhatsApp app

def _uia():
    import uiautomation as auto
    auto.SetGlobalSearchTimeout(1.0)
    return auto


def _rect(c):
    r = c.BoundingRectangle
    return r.left, r.top, r.right, r.bottom


def _whatsapp_window(timeout: float = 9.0):
    """Opens WhatsApp Desktop and returns its window once it's in front."""
    auto = _uia()
    try:
        os.startfile("whatsapp:")
    except OSError:
        pass
    end = time.time() + timeout
    while time.time() < end:
        try:
            fg = auto.GetForegroundControl()
            top = fg.GetTopLevelControl() if fg else None
            if top and "whatsapp" in (top.Name or "").lower():
                return top
            w = auto.WindowControl(searchDepth=1, SubName="WhatsApp")
            if w.Exists(0.2):
                w.SetActive()
                w.SetFocus()
        except Exception:
            pass
        time.sleep(0.4)
    return None


def _controls(win, types, max_depth=30):
    auto = _uia()
    out = []
    for c, _d in auto.WalkControl(win, maxDepth=max_depth):
        try:
            if c.ControlTypeName in types and not c.IsOffscreen:
                l, t, r, b = _rect(c)
                if r - l > 4 and b - t > 4:
                    out.append(c)
        except Exception:
            continue
    return out


def _boxes(win):
    """(search box, message box) found by name first, then by where they sit."""
    wl, wt, wr, wb = _rect(win)
    mid = wl + (wr - wl) * 0.45
    edits = _controls(win, {"EditControl", "DocumentControl"})
    edits = [e for e in edits if e.ControlTypeName == "EditControl" or "message" in (e.Name or "").lower()]
    search = next((e for e in edits if "search" in (e.Name or "").lower()), None)
    if search is None:
        left = [e for e in edits if _rect(e)[2] <= mid + 40]
        search = min(left, key=lambda e: _rect(e)[1], default=None)
    message = next((e for e in edits if re.search(r"type a message|message", (e.Name or "").lower())
                    and "search" not in (e.Name or "").lower()), None)
    if message is None:
        right = [e for e in edits if _rect(e)[0] >= mid - 40 and e is not search]
        message = max(right, key=lambda e: _rect(e)[3], default=None)
    return search, message


def _title(c) -> str:
    """The chat's name: its first text line (WhatsApp puts time and last message after it)."""
    try:
        for t in c.GetChildren():
            if t.ControlTypeName == "TextControl" and (t.Name or "").strip():
                return t.Name.strip()
    except Exception:
        pass
    name = (c.Name or "").strip()
    return re.split(r"\s{2,}|\n|, |\d{1,2}:\d{2}", name)[0].strip() if name else ""


def pick_chat(query: str, items: list[tuple[str, object]]):
    """Chooses the chat for a spoken name. Returns (title, item), ("?", [titles]) when unclear, or None."""
    q = clean_name(query)
    if not q:
        return None
    word = re.compile(r"(?<![a-z0-9])" + re.escape(q) + r"(?![a-z0-9])")
    cands, seen = [], set()
    for title, item in items:
        tl = title.lower().strip()
        if tl and tl not in seen and word.search(tl):
            seen.add(tl)
            cands.append((title, item))
    if not cands:
        return None
    exact = [c for c in cands if c[0].lower().strip() == q]
    if exact:
        return exact[0]
    if len(cands) == 1:
        return cands[0]
    return "?", [c[0] for c in cands[:4]]


def send_by_name(who: str, message: str, auto_send: bool = True):
    """Searches the chat in WhatsApp Desktop, opens it, types and (optionally) sends.
    Returns a reply string, a Confirm, or None when the app couldn't be driven."""
    from pc_actions import Confirm
    import keyboard
    import agent_cursor as ac
    try:
        _uia()
    except Exception:
        return None
    ac.begin()
    win = _whatsapp_window()
    if win is None:
        ac.done()
        return None
    name = clean_name(who)
    try:
        keyboard.send("esc")
        time.sleep(0.25)
        search, _ = _boxes(win)
        if search is None:
            ac.done()
            print("[whatsapp] couldn't find the search box")
            return None
        ac.click(*ac.center(_rect(search)), f"Searching {name.title()}")
        ac.key("ctrl+a")
        ac.type_text(name, show=f"Searching {name.title()}")
        time.sleep(1.6)
        wl, wt, wr, wb = _rect(win)
        mid = wl + (wr - wl) * 0.45
        st = _rect(search)[3]
        items = []
        for c in _controls(win, {"ListItemControl", "DataItemControl", "ButtonControl", "GroupControl"}):
            l, t, r, b = _rect(c)
            if r <= mid + 40 and t >= st - 2:
                title = _title(c)
                if title:
                    items.append((title, c))
        pick = pick_chat(name, items)
        if pick is None:
            keyboard.send("esc")
            ac.done()
            return f"I couldn't find {name.title()} in your WhatsApp chats. Check the name, or say: save contact {name} and the number."
        if pick[0] == "?":
            keyboard.send("esc")
            ac.done()
            return f"I found {', '.join(pick[1])}. Say the full name and I'll send it."
        title, item = pick
        ac.click(*ac.center(_rect(item)), f"Opening {title}")
        time.sleep(1.0)
        _, box = _boxes(win)
        if box is None:
            ac.done()
            return f"I opened {title}'s chat but couldn't find the message box."
        ac.click(*ac.center(_rect(box)), "Writing the message")
        ac.type_text(message, show=f"Writing to {title}")
        time.sleep(0.3)
        if not auto_send:
            ac.done()
            return Confirm("whatsapp_send", {"mode": "ui", "name": title, "message": message},
                           f"I've typed this to {title}: {message}. Say confirm to send, or cancel.")
        ac.key("enter", f"Sending to {title}")
        ac.done("Sent")
        return f"Sent to {title} on WhatsApp."
    except Exception as e:
        print(f"[whatsapp] by-name failed: {e}")
        ac.done()
        return None


def prepare(who: str, message: str, overlay=None):
    """Sends a WhatsApp message to a contact by name (or number). Returns text or a Confirm."""
    from pc_actions import Confirm
    message = tidy(message)
    if not message:
        return f"What should I write to {who}?"
    auto_send = bool(getattr(config, "WHATSAPP_AUTO_SEND", True))
    digits_only = clean_number(clean_name(who))
    if not digits_only:
        res = send_by_name(who, message, auto_send)
        if res is not None:
            return res
    found = find_number(who)
    if not found:
        return (f"I couldn't open {clean_name(who).title()}'s chat in the WhatsApp app. "
                "Make sure WhatsApp Desktop is installed and logged in.")
    name, number = found
    _open_chat(number, message)
    payload = {"mode": "link", "name": name, "number": number, "message": message}
    if auto_send:
        return send(dict(payload, _opened=True))
    print(f"[whatsapp] chat opened for {name} - waiting for confirm")
    return Confirm("whatsapp_send", payload,
                   f"I've typed this to {name} on WhatsApp: {message}. Say confirm to send, or cancel.")


def send(payload: dict) -> str:
    """Presses Enter in the open chat (after 'confirm', or straight away with auto-send)."""
    import keyboard
    if payload.get("mode") == "ui":
        win = _whatsapp_window(5)
        if win is None:
            return "WhatsApp isn't open any more, so I didn't send it."
        _, box = _boxes(win)
        if box is not None:
            import agent_cursor as ac
            ac.click(*ac.center(_rect(box)), f"Sending to {payload['name']}")
            ac.done()
        keyboard.send("enter")
        return f"Sent to {payload['name']}."
    if not payload.get("_opened"):                 # after "confirm" the chat may be behind other windows
        _open_chat(payload["number"], payload["message"])
    time.sleep(float(getattr(config, "WHATSAPP_OPEN_WAIT", 2.2)))
    keyboard.send("enter")
    return f"Sent to {payload['name']}."
