"""
Desktop agent - Hinata works your PC herself, step by step, like a person.

"take over and turn on dark mode in settings"
"do it yourself: open notepad, write a leave letter and save it on the desktop"

Each step she reads the window in front of her through Windows UI Automation
(every button, box, menu and list item with its name and position), the big
brain picks ONE action, and the agent cursor glides there and does it. Then
she looks again. Esc stops her at any time.

Safety:
  * buttons like Send / Pay / Buy / Delete / Uninstall / Post are only pressed
    when your request said so - otherwise she stops and asks "say confirm"
  * she never types into password boxes
"""

import re
import time

import config
import agent_cursor as ac
import brain

INTERACTIVE = {"ButtonControl", "EditControl", "ComboBoxControl", "ListItemControl", "MenuItemControl",
               "TabItemControl", "HyperlinkControl", "CheckBoxControl", "RadioButtonControl", "TreeItemControl",
               "DataItemControl", "SplitButtonControl", "DocumentControl", "MenuBarControl", "SliderControl",
               "SpinnerControl", "ToggleButtonControl"}
SHORT = {"ButtonControl": "button", "EditControl": "textbox", "ComboBoxControl": "dropdown",
         "ListItemControl": "item", "MenuItemControl": "menu", "TabItemControl": "tab", "HyperlinkControl": "link",
         "CheckBoxControl": "checkbox", "RadioButtonControl": "radio", "TreeItemControl": "tree-item",
         "DataItemControl": "row", "SplitButtonControl": "button", "DocumentControl": "document",
         "MenuBarControl": "menubar", "SliderControl": "slider", "SpinnerControl": "spinner",
         "ToggleButtonControl": "toggle", "TextControl": "text"}
RISKY = re.compile(r"\b(send|pay|payment|buy|purchase|place order|order now|checkout|delete|remove|erase|uninstall|"
                   r"format|submit|post|publish|share|sign out|log ?out|transfer|reset|factory|wipe|discard)\b", re.I)
MAX_ELEMENTS = 70
WALK_SECONDS = 2.5

SYSTEM = (
    "You operate a Windows PC for the user by choosing ONE action at a time. You see the active window's "
    "controls as numbered lines: id, type, name, and value. Reply with ONE JSON object and nothing else:\n"
    '{"do":"click","id":N,"why":"..."}\n'
    '{"do":"double_click","id":N,"why":"..."}\n'
    '{"do":"type","id":N,"text":"...","enter":false,"replace":true,"why":"..."}   (clicks the box, then types)\n'
    '{"do":"key","keys":"ctrl+s","why":"..."}\n'
    '{"do":"open","app":"notepad","why":"..."}   (app, website or file)\n'
    '{"do":"switch","window":"part of a window title","why":"..."}\n'
    '{"do":"scroll","direction":"down","why":"..."}\n'
    '{"do":"wait","seconds":2,"why":"..."}\n'
    '{"do":"done","say":"one short sentence for the user"}\n'
    '{"do":"ask","say":"a short question when you truly need the user"}\n'
    "Rules: use ids exactly as listed. Prefer keyboard shortcuts when they are obvious. If the needed app "
    "isn't open, use open. When the goal is reached, answer done right away. Never invent ids. "
    "Never type passwords or card numbers."
)


def _auto():
    import uiautomation as auto
    auto.SetGlobalSearchTimeout(1.5)
    return auto


# ---------------------------------------------------------------- reading the screen

def _rect(c):
    r = c.BoundingRectangle
    return (r.left, r.top, r.right, r.bottom)


def _value(c):
    try:
        if c.ControlTypeName in ("EditControl", "ComboBoxControl", "DocumentControl"):
            v = c.GetValuePattern().Value
            return (v or "")[:60]
    except Exception:
        pass
    try:
        if c.ControlTypeName in ("CheckBoxControl", "ToggleButtonControl"):
            return "on" if c.GetTogglePattern().ToggleState == 1 else "off"
    except Exception:
        pass
    return ""


def read_window():
    """(window title, [elements], [visible texts], [other window titles])."""
    auto = _auto()
    fg = auto.GetForegroundControl()
    win = fg.GetTopLevelControl() if fg else None
    if not win:
        return "", [], [], []
    wl, wt, wr, wb = _rect(win)
    elems, texts = [], []
    deadline = time.time() + WALK_SECONDS
    for c, depth in auto.WalkControl(win, maxDepth=22):
        if time.time() > deadline or len(elems) >= MAX_ELEMENTS * 2:
            break
        try:
            typ = c.ControlTypeName
            if typ not in INTERACTIVE and typ != "TextControl":
                continue
            if c.IsOffscreen:
                continue
            l, t, r, b = _rect(c)
            if r - l < 3 or b - t < 3 or r < wl or l > wr or b < wt or t > wb:
                continue
            name = (c.Name or "").strip().replace("\n", " ")
            if typ == "TextControl":
                if name and len(texts) < 25 and name not in texts:
                    texts.append(name[:80])
                continue
            if not c.IsEnabled:
                continue
            pw = bool(getattr(c, "IsPassword", False))
            elems.append({"type": typ, "name": name[:70], "value": "" if pw else _value(c),
                          "rect": (l, t, r, b), "password": pw})
        except Exception:
            continue
    # named controls first, then by screen position; keep the list short for the model
    elems.sort(key=lambda e: (not e["name"] and e["type"] != "EditControl", e["rect"][1], e["rect"][0]))
    elems = elems[:MAX_ELEMENTS]
    others = []
    try:
        for w in auto.GetRootControl().GetChildren():
            n = (w.Name or "").strip()
            if n and n != win.Name and w.ControlTypeName in ("WindowControl", "PaneControl") and len(others) < 12:
                others.append(n[:60])
    except Exception:
        pass
    return (win.Name or "").strip(), elems, texts, others


def describe(elems) -> str:
    lines = []
    for i, e in enumerate(elems, 1):
        bit = f'{i} {SHORT.get(e["type"], e["type"])} "{e["name"]}"'
        if e["value"]:
            bit += f' value="{e["value"]}"'
        if e["password"]:
            bit += " (password)"
        lines.append(bit)
    return "\n".join(lines)


def _prompt(goal, title, elems, texts, others, history) -> str:
    return (f"GOAL: {goal}\n\nACTIVE WINDOW: {title or '(desktop)'}\n"
            f"CONTROLS:\n{describe(elems) or '(none readable)'}\n\n"
            f"TEXT ON SCREEN: {' | '.join(texts[:20]) or '-'}\n"
            f"OTHER WINDOWS: {', '.join(others) or '-'}\n\n"
            f"DONE SO FAR:\n" + ("\n".join(f"- {h}" for h in history[-8:]) or "- nothing yet") +
            "\n\nNext action (one JSON object):")


# ---------------------------------------------------------------- acting

def is_risky(name: str, goal: str) -> bool:
    """A risky button is fine only when the user's own words asked for that action."""
    m = RISKY.search(name or "")
    if not m:
        return False
    word = m.group(1).lower().split()[0]
    return not re.search(r"\b" + re.escape(word), goal.lower())


def _switch(part: str) -> bool:
    auto = _auto()
    part = (part or "").lower()
    for w in auto.GetRootControl().GetChildren():
        if part and part in (w.Name or "").lower():
            try:
                w.SetActive()
                w.SetFocus()
                return True
            except Exception:
                return False
    return False


def act(a: dict, elems, goal: str):
    """Runs one action. Returns (history line, finished?, reply or Confirm)."""
    from pc_actions import Confirm
    do = (a.get("do") or "").lower()
    why = a.get("why") or ""

    def el():
        try:
            i = int(a.get("id"))
        except (TypeError, ValueError):
            return None
        return elems[i - 1] if 1 <= i <= len(elems) else None

    if do in ("done", "ask"):
        return f"{do}: {a.get('say', '')}", True, a.get("say") or "Done."
    if do in ("click", "double_click"):
        e = el()
        if not e:
            return f"bad id {a.get('id')} - pick an id from the list", False, None
        if is_risky(e["name"], goal):
            x, y = ac.center(e["rect"])
            ac.move(x, y, f"Waiting for you: {e['name']}")
            return ("stopped at a risky button", True,
                    Confirm("desk_click", {"goal": goal, "x": x, "y": y, "name": e["name"]},
                            f"I'm on the {e['name']} button. Say confirm and I'll press it, or cancel."))
        x, y = ac.center(e["rect"])
        ac.click(x, y, why or f"Clicking {e['name'] or SHORT.get(e['type'], '')}", double=do == "double_click")
        return f"clicked {SHORT.get(e['type'], '')} '{e['name']}'", False, None
    if do == "type":
        e = el()
        text = str(a.get("text") or "")
        if e is not None:
            if e["password"]:
                return "refused: that's a password box - the user types passwords", True, \
                    "That's a password box, so I'll leave it to you."
            ac.click(*ac.center(e["rect"]), why or f"Typing in {e['name'] or 'the box'}")
            if a.get("replace", True) and e["type"] in ("EditControl", "ComboBoxControl"):
                ac.key("ctrl+a")
        ac.type_text(text)
        if a.get("enter"):
            ac.key("enter")
        return f"typed '{text[:40]}'" + (" and pressed Enter" if a.get("enter") else ""), False, None
    if do == "key":
        keys = str(a.get("keys") or "").lower().replace(" ", "")
        if keys in ("alt+f4",) and not re.search(r"\b(close|quit|exit)\b", goal.lower()):
            return "skipped alt+f4 - the goal didn't ask to close anything", False, None
        ac.key(keys, why or f"Pressing {keys}")
        return f"pressed {keys}", False, None
    if do == "open":
        import pc_actions as pc
        ac.label(f"Opening {a.get('app')}")
        res = pc.open_target(str(a.get("app") or ""))
        time.sleep(2.0)
        return f"open {a.get('app')}: {res}", False, None
    if do == "switch":
        ok = _switch(str(a.get("window") or ""))
        time.sleep(0.6)
        return f"switch to '{a.get('window')}': {'ok' if ok else 'no such window'}", False, None
    if do == "scroll":
        down = str(a.get("direction", "down")).lower() != "up"
        ac.scroll(-5 if down else 5, "Scrolling " + ("down" if down else "up"))
        return f"scrolled {'down' if down else 'up'}", False, None
    if do == "wait":
        s = min(8.0, float(a.get("seconds") or 1.5))
        ac.label("Waiting...")
        time.sleep(s)
        return f"waited {s:.0f}s", False, None
    return f"unknown action {do!r}", False, None


# ---------------------------------------------------------------- the loop

def run(goal: str, history: list | None = None) -> object:
    """Works until the goal is done, Esc is pressed, or the step limit. Returns text or a Confirm."""
    try:
        _auto()
    except Exception:
        return "The desktop agent needs uiautomation. Run install.bat once and try again."
    history = list(history or [])
    ac.begin()
    ac.label("Looking at the screen...")
    steps = int(getattr(config, "DESK_AGENT_MAX_STEPS", 20))
    fails = 0
    try:
        for _ in range(steps):
            if ac.stopped():
                ac.done("Stopped")
                return "Stopped. You pressed Escape."
            title, elems, texts, others = read_window()
            a = brain.ask_json(_prompt(goal, title, elems, texts, others, history), SYSTEM, max_tokens=300,
                               timeout=60)
            if not isinstance(a, dict) or not a.get("do"):
                fails += 1
                history.append("(the last answer wasn't a valid action)")
                if fails >= 3:
                    ac.done()
                    return "My brain couldn't work out the next step. Try saying it more simply."
                continue
            print(f"[desk] {a}")
            line, finished, reply = act(a, elems, goal)
            history.append(line)
            if finished:
                if not isinstance(reply, str):          # a Confirm - keep the cursor parked on the button
                    reply.payload["history"] = history
                    return reply
                ac.done("Done")
                return reply
            time.sleep(0.35)
        ac.done()
        return "I ran out of steps before finishing. Tell me what's left and I'll continue."
    except Exception as e:
        ac.done()
        print(f"[desk] error: {e}")
        return f"The desktop agent hit a problem: {e}"


def confirm_click(payload: dict):
    """After 'confirm' on a risky button: press it, then keep going."""
    ac.click(payload["x"], payload["y"], f"Pressing {payload['name']}")
    hist = list(payload.get("history") or []) + [f"user confirmed and I pressed '{payload['name']}'"]
    return run(payload["goal"], hist)
