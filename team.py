"""
Founder tools - a small team helper.

    "add task call the printer by Friday"      "what are my tasks"
    "task 2 done"                              "note: investor wants a demo video"
    "read my notes"                            "draft an email to Rahul about the pricing"

Tasks and notes live in plain JSON in Hinata's data folder. Emails are only
drafted: they open in your mail app for you to read and send.
"""

import datetime as dt
import json
import os
import re
from urllib.parse import quote

import config

_FILE = os.path.join(config.DATA_DIR, "team.json")


def _load() -> dict:
    try:
        with open(_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    d.setdefault("tasks", [])
    d.setdefault("notes", [])
    return d


def _save(d: dict):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)


# ---------------------------------------------------------------- tasks

def add_task(text: str) -> str:
    text = (text or "").strip(" .")
    if not text:
        return "What's the task?"
    d = _load()
    d["tasks"].append({"text": text[:1].upper() + text[1:], "done": False,
                       "added": dt.date.today().isoformat()})
    _save(d)
    left = sum(not t["done"] for t in d["tasks"])
    return f"Added. You have {left} open task{'s' if left != 1 else ''}."


def open_tasks() -> list[dict]:
    return [t for t in _load()["tasks"] if not t["done"]]


def list_tasks() -> str:
    tasks = open_tasks()
    if not tasks:
        return "Your task list is clear."
    said = ". ".join(f"{i}, {t['text']}" for i, t in enumerate(tasks[:8], 1))
    more = f" And {len(tasks) - 8} more." if len(tasks) > 8 else ""
    return f"You have {len(tasks)} open task{'s' if len(tasks) != 1 else ''}. {said}.{more}"


def done_task(ref: str) -> str:
    d = _load()
    tasks = [t for t in d["tasks"] if not t["done"]]
    if not tasks:
        return "There are no open tasks."
    ref = (ref or "").strip().lower()
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
             "first": 1, "second": 2, "third": 3, "last": len(tasks)}
    m = re.search(r"\d+", ref)
    n = int(m.group()) if m else words.get(ref.split()[0] if ref else "", 0)
    target = tasks[n - 1] if 1 <= n <= len(tasks) else next((t for t in tasks if ref and ref in t["text"].lower()), None)
    if not target:
        return "I couldn't find that task. Say the task number, like: task 2 done."
    target["done"] = True
    _save(d)
    return f"Done: {target['text']}. {sum(not t['done'] for t in d['tasks'])} left."


def clear_done() -> str:
    d = _load()
    d["tasks"] = [t for t in d["tasks"] if not t["done"]]
    _save(d)
    return "Cleared the finished tasks."


# ---------------------------------------------------------------- notes

def add_note(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return "What should I note down?"
    d = _load()
    d["notes"].append({"text": text[:1].upper() + text[1:], "at": dt.datetime.now().strftime("%d %b %H:%M")})
    _save(d)
    return "Noted."


def read_notes(count: int = 5) -> str:
    notes = _load()["notes"][-count:]
    if not notes:
        return "You have no notes yet."
    return "Your latest notes: " + ". ".join(n["text"] for n in notes) + "."


# ---------------------------------------------------------------- email drafts

def draft_email(to: str, about: str, generate=None) -> str:
    """Writes the email with the local AI and opens it in the mail app - never sends it."""
    about = (about or "").strip()
    if not about:
        return "What should the email be about?"
    user = getattr(config, "USER_NAME", "") or ""
    body, subject = "", about[:1].upper() + about[1:70]
    if generate:
        text = generate(
            f"Write a short, polite business email to {to or 'the recipient'} about: {about}.\n"
            f"Sign it as {user or 'me'}. First line must be 'Subject: <subject>'. Then a blank line, "
            "then the email body. Plain text, under 130 words, no placeholders in brackets.")
        if text:
            m = re.match(r"\s*subject:\s*(.+)", text, re.I)
            if m:
                subject = m.group(1).strip()
                text = text[m.end():]
            body = text.strip()
    if not body:
        body = f"Hi {to.title() if to else ''},\n\n{about[:1].upper() + about[1:]}.\n\nRegards,\n{user}"
    addr = to if "@" in (to or "") else ""
    url = f"mailto:{addr}?subject={quote(subject)}&body={quote(body)}"
    try:
        os.startfile(url)
    except (OSError, AttributeError):
        import webbrowser
        webbrowser.open(url)
    return f"I've drafted the email{' to ' + to if to else ''} and opened it. Read it and press send when you're happy."


def brief() -> str:
    """Quick founder brief: the date and what's open."""
    today = dt.datetime.now().strftime("%A, %d %B")
    return f"It's {today}. " + list_tasks()
