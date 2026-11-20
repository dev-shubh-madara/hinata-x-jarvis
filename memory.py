"""
Long-term memory: things you tell Hinata stay with her across restarts.

    "Remember that my exam starts on 24 November"
    "Remember my mentor's name is Rasmita"
    "What do you remember about my exam?"
    "Forget the exam thing"

Facts are kept in %LOCALAPPDATA%\\HinataXHelper\\memory.json on this laptop
only. Before every AI answer, the few facts that match what you said are
added to her instructions, so she uses them without being asked
("when's my exam?" just works).

Matching is keyword overlap with light stemming - no embedding model, so it
costs nothing and takes under a millisecond.
"""

import difflib
import json
import os
import re
import threading
import time

import config

PATH = os.path.join(config.DATA_DIR, "memory.json")
_lock = threading.Lock()
_STOP = set("""a an the and or but if of to in on at for with from by about as is are was were be been am i me my
mine you your it its this that these those do does did have has had will would can could should please remember
forget that what when where who whom how why which tell know there their they them he she his her we our us
okay ok hinata hey just also really very some any all""".split())


def _load() -> list[dict]:
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(items):
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PATH)


def _stem(w: str) -> str:
    for suf in ("ing", "ies", "es", "ed", "'s", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def keywords(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9']+", (text or "").lower()) if w not in _STOP and len(w) > 1}


def _tidy(fact: str) -> str:
    """'that my exam is on monday' -> 'My exam is on monday.' (first person stays the user's)"""
    f = re.sub(r"^\s*(?:that|about)\s+", "", fact.strip(), flags=re.I).strip(" .")
    if not f:
        return ""
    return f[0].upper() + f[1:] + "."


def remember(fact: str) -> str:
    fact = _tidy(fact)
    if len(keywords(fact)) == 0:
        return "What should I remember?"
    with _lock:
        items = _load()
        for it in items:                                   # same fact again -> update it, don't duplicate
            if difflib.SequenceMatcher(None, it["text"].lower(), fact.lower()).ratio() > 0.85:
                it.update(text=fact, at=time.time())
                _save(items)
                return "Updated. I'll remember that."
        items.append({"id": int(time.time() * 1000), "text": fact, "at": time.time()})
        _save(items)
    return "Got it, I'll remember that."


def recall(query: str, k: int = 5, min_score: float = 0.34) -> list[str]:
    """Facts that match the query, best first."""
    q = keywords(query)
    if not q:
        return []
    scored = []
    for it in _load():
        kw = keywords(it["text"])
        hit = len(q & kw)
        if not hit:
            continue
        score = hit / len(q)
        score += 0.05 * min(1.0, 30 * 86400 / max(1.0, time.time() - it.get("at", 0)))   # newer wins ties
        if score >= min_score:
            scored.append((score, it["text"]))
    scored.sort(key=lambda x: -x[0])
    return [t for _, t in scored[:k]]


def recent(n: int = 5) -> list[str]:
    return [it["text"] for it in sorted(_load(), key=lambda x: -x.get("at", 0))[:n]]


def count() -> int:
    return len(_load())


def forget(query: str) -> str:
    q = keywords(query)
    if not q:
        return "What should I forget?"
    with _lock:
        items = _load()
        best, best_score = None, 0.0
        for it in items:
            s = len(q & keywords(it["text"])) / len(q)
            if s > best_score:
                best, best_score = it, s
        if not best or best_score < 0.5:
            return "I don't have anything like that saved."
        items.remove(best)
        _save(items)
    return f"Forgotten: {best['text']}"


def forget_all() -> str:
    with _lock:
        n = len(_load())
        _save([])
    return f"Done. I've forgotten all {n} things you told me."


def answer(query: str) -> str:
    """Spoken answer to 'what do you remember about X'."""
    hits = recall(query, k=3, min_score=0.2) if keywords(query) else recent(3)
    if not hits:
        return "I don't have anything saved about that." if keywords(query) else "You haven't told me anything to remember yet."
    return " ".join(hits)


def context_for(text: str) -> str:
    """A line for the AI's instructions with the facts relevant to this request ('' if none)."""
    hits = recall(text, k=4)
    if not hits:
        return ""
    who = config.USER_NAME or "the user"
    return f"Things {who} told you earlier (use them if relevant, don't recite them): " + " ".join(hits)


# ---------------------------------------------------------------- AI tools

def tools():
    import nlu
    S = "string"
    return [
        nlu._tool("remember_fact", "Save a lasting fact the user tells you about themselves, their people, plans or "
                  "preferences ('remember that...', 'my sister's name is...'). Not for one-off chat.",
                  ["fact"], fact=(S, "the fact, in the user's words")),
        nlu._tool("recall_memory", "Look up what the user told you earlier.", ["query"], query=(S, "what to look up")),
    ]


def register():
    import commands
    import nlu
    nlu.register_tools(tools(), final={"remember_fact", "recall_memory"})
    commands.register_handler("remember_fact", lambda a: remember(str(a.get("fact") or "")), info=True)
    commands.register_handler("recall_memory", lambda a: answer(str(a.get("query") or "")), info=True)
