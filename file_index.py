"""
Instant file search across every drive - like the "Everything" app.

    "find my physics ppt from last week"
    "open the salon project folder"
    "where is my resume pdf"

The first time, Hinata walks all your fixed drives (C:, D:, ...) in the
background and stores file names in a small SQLite database
(%LOCALAPPDATA%\\HinataXHelper\\files.db). After that a search is a single
indexed query: a few milliseconds even with a million files. Your user
folders (Desktop, Downloads, Documents, D:\\) are re-scanned every few
minutes so new files show up fast; everything else every few hours.

Only names, sizes and dates are stored - never file contents.
"""

import os
import re
import sqlite3
import string
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta

import config

DB = os.path.join(config.DATA_DIR, "files.db")

SKIP = {"windows", "program files", "program files (x86)", "programdata", "$recycle.bin", "system volume information",
        "appdata", "node_modules", "__pycache__", ".git", ".svn", "site-packages", "venv", ".venv", "env",
        "$windows.~bt", "$windows.~ws", "windowsapps", "msocache", "recovery", "perflogs", "config.msi",
        ".cache", ".gradle", ".m2", ".nuget", ".cargo", ".rustup", "temp", "tmp", "dist-packages", ".npm",
        "go\\pkg", "anaconda3", "miniconda3", ".vscode-server", ".android", "intermediates", "build-cache"}

KINDS = {
    "ppt": ("ppt", "pptx", "key", "odp"), "presentation": ("ppt", "pptx", "key", "odp"), "slides": ("ppt", "pptx", "odp"),
    "pdf": ("pdf",), "word": ("doc", "docx", "odt"), "doc": ("doc", "docx", "odt"), "document": ("doc", "docx", "odt", "pdf", "txt"),
    "excel": ("xls", "xlsx", "csv"), "sheet": ("xls", "xlsx", "csv"), "spreadsheet": ("xls", "xlsx", "csv"),
    "photo": ("jpg", "jpeg", "png", "heic", "webp"), "image": ("jpg", "jpeg", "png", "gif", "webp", "heic", "svg"),
    "picture": ("jpg", "jpeg", "png", "heic", "webp"), "pic": ("jpg", "jpeg", "png", "heic", "webp"),
    "screenshot": ("png", "jpg"), "video": ("mp4", "mkv", "mov", "avi", "webm"), "recording": ("mp4", "mkv", "m4a", "wav", "mp3"),
    "song": ("mp3", "m4a", "flac", "wav"), "music": ("mp3", "m4a", "flac", "wav"), "audio": ("mp3", "m4a", "wav", "aac", "amr"),
    "python": ("py", "ipynb"), "notebook": ("ipynb",), "code": ("py", "js", "ts", "html", "css", "java", "c", "cpp", "ipynb"),
    "zip": ("zip", "rar", "7z"), "apk": ("apk",), "resume": (), "cv": (),
    "text": ("txt", "md"), "notes": ("txt", "md", "docx"), "html": ("html", "htm"),
}
_NOISE = set("""find open show search locate where's where is are my the a an file files folder folders from for of
in on at that which with called named last this please me get bring up can you hinata hey ok okay one some""".split())


def _conn():
    c = sqlite3.connect(DB, timeout=10, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, path TEXT UNIQUE, name TEXT, ext TEXT, "
              "isdir INT, size INT, mtime REAL, seen REAL)")
    c.execute("CREATE INDEX IF NOT EXISTS files_mtime ON files(mtime)")
    c.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    try:
        # trigram full-text index on names: substring search without scanning the table
        c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS names USING fts5(name, tokenize='trigram')")
        _state["fts"] = True
    except sqlite3.OperationalError:
        _state["fts"] = False                     # old SQLite: plain LIKE search (still fine)
    return c


_state = {"fts": False, "building": False, "lock": threading.Lock(), "thread": None}


# ---------------------------------------------------------------- where to look

def drives() -> list[str]:
    if os.name != "nt":
        return [os.path.expanduser("~")]
    import ctypes
    out = []
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if mask & (1 << i):
            root = f"{letter}:\\"
            if ctypes.windll.kernel32.GetDriveTypeW(root) == 3:      # DRIVE_FIXED - no USB sticks, no network
                out.append(root)
    return out


def hot_folders() -> list[str]:
    home = os.path.expanduser("~")
    cands = [config.DESKTOP_DIR] + [os.path.join(home, f) for f in ("Downloads", "Documents", "Pictures", "Videos", "Music")]
    if os.name == "nt" and os.path.isdir("D:\\"):
        cands.append("D:\\")
    cands.append(config.OUTPUT_DIR)
    seen, out = set(), []
    for p in cands:
        if p and os.path.isdir(p) and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


def _skip(name: str) -> bool:
    n = name.lower()
    return n in SKIP or (n.startswith(".") and n not in (".github",))


# ---------------------------------------------------------------- indexing

def scan(roots, max_depth=None, limit=3_000_000, now=None):
    """Yields (path, name, ext, isdir, size, mtime) for everything under roots."""
    count = 0
    for root in roots:
        stack = [(root, 0)]
        while stack:
            d, depth = stack.pop()
            try:
                with os.scandir(d) as it:
                    for e in it:
                        try:
                            if e.is_dir(follow_symlinks=False):
                                if _skip(e.name):
                                    continue
                                st = e.stat(follow_symlinks=False)
                                yield (e.path, e.name.lower(), "", 1, 0, st.st_mtime)
                                if max_depth is None or depth < max_depth:
                                    stack.append((e.path, depth + 1))
                            elif e.is_file(follow_symlinks=False):
                                st = e.stat(follow_symlinks=False)
                                ext = os.path.splitext(e.name)[1][1:].lower()
                                yield (e.path, e.name.lower(), ext, 0, st.st_size, st.st_mtime)
                            count += 1
                            if count >= limit:
                                return
                        except OSError:
                            continue
            except OSError:
                continue


def index(roots, max_depth=None, prune=True) -> int:
    """Indexes roots into the database. With prune, entries under roots that are gone are removed."""
    started = time.time()
    c = _conn()
    n = 0
    batch = []
    with _state["lock"]:
        for row in scan(roots, max_depth=max_depth):
            batch.append(row + (started,))
            if len(batch) >= 5000:
                n += _flush(c, batch)
                batch = []
        n += _flush(c, batch)
        if prune and max_depth is None:
            for r in roots:
                lo = r.rstrip("\\/") + os.sep
                hi = lo[:-1] + chr(ord(os.sep) + 1)              # every path that starts with lo
                gone = [i for (i,) in c.execute("SELECT id FROM files WHERE path >= ? AND path < ? AND seen < ?",
                                                (lo, hi, started))]
                for k in range(0, len(gone), 500):
                    chunk = gone[k:k + 500]
                    marks = ",".join("?" * len(chunk))
                    if _state["fts"]:
                        c.execute(f"DELETE FROM names WHERE rowid IN ({marks})", chunk)
                    c.execute(f"DELETE FROM files WHERE id IN ({marks})", chunk)
        c.commit()
    c.close()
    return n


def _flush(c, batch) -> int:
    if not batch:
        return 0
    top = c.execute("SELECT COALESCE(MAX(id), 0) FROM files").fetchone()[0]
    c.executemany("INSERT OR IGNORE INTO files(path,name,ext,isdir,size,mtime,seen) VALUES(?,?,?,?,?,?,?)", batch)
    c.executemany("UPDATE files SET size=?, mtime=?, seen=? WHERE path=?",
                  [(b[4], b[5], b[6], b[0]) for b in batch])
    if _state["fts"]:                                   # only brand-new rows need a name entry
        c.execute("INSERT INTO names(rowid, name) SELECT id, name FROM files WHERE id > ?", (top,))
    c.commit()
    return len(batch)


def _meta(k, v=None):
    c = _conn()
    try:
        if v is None:
            row = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
            return row[0] if row else None
        c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, str(v)))
        c.commit()
    finally:
        c.close()


def total() -> int:
    c = _conn()
    try:
        return c.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    finally:
        c.close()


def start_background():
    """Full index of every drive now and then; hot folders every few minutes."""
    if _state["thread"]:
        return

    def loop():
        full_every = float(getattr(config, "FILE_INDEX_FULL_HOURS", 6)) * 3600
        hot_every = float(getattr(config, "FILE_INDEX_HOT_MINUTES", 5)) * 60
        last_hot = 0.0
        while True:
            try:
                last_full = float(_meta("full_at") or 0)
                if time.time() - last_full > full_every:
                    _lower_priority()
                    t0 = time.time()
                    _state["building"] = True
                    n = index(drives())
                    _state["building"] = False
                    _meta("full_at", time.time())
                    print(f"[files] indexed {n:,} items on {', '.join(drives())} in {time.time() - t0:.0f}s")
                elif time.time() - last_hot > hot_every:
                    index(hot_folders(), max_depth=3, prune=False)   # new files show up; gone ones are skipped at search time
                    last_hot = time.time()
            except Exception as e:
                _state["building"] = False
                print(f"[files] index error: {e}")
            time.sleep(20)

    _state["thread"] = threading.Thread(target=loop, daemon=True, name="file-index")
    _state["thread"].start()


def _lower_priority():
    try:
        import psutil
        p = psutil.Process()
        if sys.platform == "win32":
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass


# ---------------------------------------------------------------- search

def parse(query: str):
    """'my physics ppt from last week' -> (['physics'], ('ppt','pptx',...), since, want_dir)"""
    q = (query or "").lower()
    since = None
    now = datetime.now()
    for pat, delta in ((r"\btoday\b", timedelta(days=1)), (r"\byesterday\b", timedelta(days=2)),
                       (r"\b(?:last|this|past) week\b", timedelta(days=8)), (r"\b(?:last|this|past) month\b", timedelta(days=32)),
                       (r"\b(?:recent|recently|latest|newest|new)\b", timedelta(days=14))):
        if re.search(pat, q):
            since = (now - delta).timestamp()
            q = re.sub(pat, " ", q)
    q = re.sub(r"\b(?:last|this|past)\b", " ", q)
    want_dir = bool(re.search(r"\b(?:folder|directory|project)\b", q))
    exts: tuple = ()
    words = []
    for w in re.findall(r"[a-z0-9._+-]+", q):
        w = w.strip(".")
        base = w[:-1] if w.endswith("s") and w[:-1] in KINDS else w
        if base in KINDS and KINDS[base]:
            exts += KINDS[base]
            if base in ("resume", "cv"):
                words.append(base)
            continue
        if base in ("resume", "cv"):
            words.append(base)
            continue
        if re.fullmatch(r"\.?[a-z0-9]{1,5}", w) and w.lstrip(".") in {e for v in KINDS.values() for e in v} and w.startswith("."):
            exts += (w.lstrip("."),)
            continue
        if w in _NOISE or w in ("folder", "directory", "project") or not w:
            continue
        words.append(w)
    return words, tuple(dict.fromkeys(exts)), since, want_dir


def search(query: str, limit: int = 8) -> list[dict]:
    words, exts, since, want_dir = parse(query)
    if not words and not exts:
        return []
    where, args = [], []
    use_fts = bool(words) and _state["fts"] and all(len(w) >= 3 for w in words)
    if use_fts:
        where.append("names MATCH ?")
        args.append(" AND ".join('"' + w.replace('"', "") + '"' for w in words))
    else:
        for w in words:
            where.append("f.name LIKE ?")
            args.append(f"%{w}%")
    if exts:
        where.append(f"f.ext IN ({','.join('?' * len(exts))})")
        args += list(exts)
    if since:
        where.append("f.mtime >= ?")
        args.append(since)
    if want_dir and not exts:
        where.append("f.isdir = 1")
    src = "names JOIN files f ON f.id = names.rowid" if use_fts else "files f"
    c = _conn()
    try:
        rows = c.execute(f"SELECT f.path, f.name, f.ext, f.isdir, f.size, f.mtime FROM {src} "
                         f"WHERE {' AND '.join(where)} ORDER BY f.mtime DESC LIMIT 400", args).fetchall()
    finally:
        c.close()
    hits = []
    for path, name, ext, isdir, size, mtime in rows:
        stem = os.path.splitext(name)[0]
        score = 0.0
        for w in words:
            if stem == w:
                score += 3
            elif re.search(rf"(?:^|[^a-z0-9]){re.escape(w)}", stem):
                score += 2                                   # word starts a token: physics_unit2.pptx
            else:
                score += 1
        score += 0.6 * min(1.0, 30 * 86400 / max(3600.0, time.time() - mtime))   # newer first
        score -= 0.02 * path.count(os.sep)                                       # shallower first
        if any(s in path.lower() for s in ("\\temp\\", "/tmp/", "cache")):
            score -= 1
        hits.append({"path": path, "name": os.path.basename(path), "isdir": bool(isdir), "size": size,
                     "mtime": mtime, "score": score})
    hits.sort(key=lambda h: -h["score"])
    alive = []
    for h in hits:
        if os.path.exists(h["path"]):
            alive.append(h)
        if len(alive) >= limit:
            break
    return alive


def _when(ts: float) -> str:
    days = (time.time() - ts) / 86400
    if days < 1:
        return "today"
    if days < 2:
        return "yesterday"
    if days < 14:
        return f"{int(days)} days ago"
    return datetime.fromtimestamp(ts).strftime("%d %B")


def describe(hits) -> str:
    if not hits:
        return ""
    h = hits[0]
    where = os.path.basename(os.path.dirname(h["path"])) or h["path"][:3]
    more = f" I found {len(hits) - 1} more too." if len(hits) > 1 else ""
    return f"{h['name']} in {where}, changed {_when(h['mtime'])}.{more}"


def find(query: str) -> str:
    hits = search(query)
    if not hits:
        return _nothing(query)
    lines = "; ".join(f"{h['name']} ({os.path.dirname(h['path'])})" for h in hits[:5])
    return f"Best match: {describe(hits)} Top results: {lines}"


def open_best(query: str) -> str:
    hits = search(query)
    if not hits:
        return _nothing(query)
    h = hits[0]
    _open(h["path"])
    return f"Opening {h['name']}."


def show_in_folder(query: str) -> str:
    hits = search(query)
    if not hits:
        return _nothing(query)
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", hits[0]["path"]])
    return f"Here's {hits[0]['name']}."


def _open(path):
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", path])


def _nothing(query) -> str:
    if _state["building"] or not _meta("full_at"):
        return "I'm still indexing your drives for the first time. I couldn't find it yet - try again in a few minutes."
    return f"I couldn't find anything like {query}."


# ---------------------------------------------------------------- AI tools

def register():
    import commands
    import nlu
    S = "string"
    nlu.register_tools([
        nlu._tool("find_files", "Search every drive for files or folders by name, type and date "
                  "('my physics ppt from last week', 'resume pdf', 'salon project folder'). Returns paths.",
                  ["query"], query=(S, "what to find, in the user's words")),
        nlu._tool("open_file", "Find a file or folder anywhere on the PC and open it.", ["query"],
                  query=(S, "what to open, in the user's words")),
    ], final={"open_file"})
    commands.register_handler("find_files", lambda a: find(str(a.get("query") or "")), info=True)
    commands.register_handler("open_file", lambda a: open_best(str(a.get("query") or "")))
