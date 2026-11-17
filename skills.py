"""
Skills - teach Hinata new jobs without touching her code.

A skill is one file in a skills folder:

  skills/                       (comes with Hinata)
  D:\\Hinata_Output\\Skills\\      (yours - say "open my skills folder")

Markdown skill (no code) - instructions the AI follows when you say a trigger:

    ---
    name: study notes
    description: makes exam notes on a topic
    triggers: make notes on, study notes, revision notes
    ---
    1. Write clear notes with headings, key formulas and 5 practice questions.
    2. Save them with write_document as a .md file.

Python skill - full control, for things the AI shouldn't improvise:

    NAME = "focus mode"
    DESCRIPTION = "mutes, hides everything and starts a 25 minute timer"
    TRIGGERS = [r"\\bfocus mode\\b"]
    def run(text, ctx):          # ctx: speak, overlay, pc, brain, cursor, execute
        ...
        return "Focus mode on."

Files are re-read when they change, so a new skill works straight away.
"""

import importlib.util
import os
import re

import config

BUILTIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
USER_DIR = os.path.join(config.OUTPUT_DIR, "Skills")

_cache: dict[str, tuple[float, object]] = {}


class Skill:
    def __init__(self, name, description, path, kind, triggers=(), body="", module=None):
        self.name = name
        self.description = description
        self.path = path
        self.kind = kind                      # "md" | "py"
        self.triggers = list(triggers)
        self.body = body
        self.module = module

    def matches(self, text: str) -> bool:
        if self.kind == "py":
            return any(re.search(p, text, re.I) for p in self.triggers)
        return any(re.search(r"(?<![a-z])" + re.escape(t.lower()) + r"(?![a-z])", text.lower())
                   for t in self.triggers if t)

    def __repr__(self):
        return f"<Skill {self.name} ({self.kind})>"


def _parse_md(path: str):
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    meta, body = {}, raw
    m = re.match(r"\s*---\s*\n(.*?)\n---\s*\n?(.*)", raw, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip()
        body = m.group(2)
    name = meta.get("name") or os.path.splitext(os.path.basename(path))[0].replace("-", " ")
    triggers = [t.strip() for t in re.split(r"[,|]", meta.get("triggers", "")) if t.strip()] or [name]
    return Skill(name, meta.get("description", ""), path, "md", triggers, body.strip())


def _parse_py(path: str):
    spec = importlib.util.spec_from_file_location("hinata_skill_" + re.sub(r"\W", "_", path), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not callable(getattr(mod, "run", None)):
        raise ValueError("a Python skill needs a run(text, ctx) function")
    name = getattr(mod, "NAME", os.path.splitext(os.path.basename(path))[0].replace("_", " "))
    trig = getattr(mod, "TRIGGERS", None) or [r"\b" + re.escape(name) + r"\b"]
    return Skill(name, getattr(mod, "DESCRIPTION", ""), path, "py", trig, module=mod)


def _ensure_user_dir():
    try:
        os.makedirs(USER_DIR, exist_ok=True)
        readme = os.path.join(USER_DIR, "HOW TO ADD A SKILL.txt")
        if not os.path.exists(readme):
            with open(readme, "w", encoding="utf-8") as f:
                f.write(__doc__.strip() + "\n")
    except OSError:
        pass


def load() -> list[Skill]:
    """All skills; yours override built-in ones with the same name."""
    _ensure_user_dir()
    found: dict[str, Skill] = {}
    for folder in (BUILTIN_DIR, USER_DIR):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for fn in names:
            if fn.startswith(("_", ".")) or not fn.endswith((".md", ".py")):
                continue
            path = os.path.join(folder, fn)
            try:
                mtime = os.path.getmtime(path)
                hit = _cache.get(path)
                if hit and hit[0] == mtime:
                    sk = hit[1]
                else:
                    sk = _parse_md(path) if fn.endswith(".md") else _parse_py(path)
                    _cache[path] = (mtime, sk)
                found[sk.name.lower()] = sk
            except Exception as e:
                print(f"[skills] skipped {fn}: {e}")
    return list(found.values())


def match(text: str):
    """The skill for this request, or None. Python skills win over markdown ones."""
    skills = load()
    for kind in ("py", "md"):
        for sk in skills:
            if sk.kind == kind and sk.matches(text):
                return sk
    return None


def summary() -> str:
    skills = load()
    if not skills:
        return "I don't have any skills yet. Say: open my skills folder."
    names = ", ".join(s.name for s in skills)
    return f"I have {len(skills)} skills: {names}. Say 'open my skills folder' to add your own."


def open_folder() -> str:
    _ensure_user_dir()
    try:
        os.startfile(USER_DIR)
    except (OSError, AttributeError):
        pass
    return "I've opened your skills folder. Drop a .md or .py skill in it and I can use it right away."
