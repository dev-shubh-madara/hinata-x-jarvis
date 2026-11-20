"""
Coding helper: Hinata runs Python, opens files in VS Code and fixes errors.

    "run this: print the first 20 primes"   -> she writes it, runs it, says the result
    "fix my bot.py"                           -> runs it, reads the traceback, writes a fix
    "read this error and fix it"              -> takes the error from your screen (screen.py),
                                                 finds the file in the traceback, fixes it

A fix is never written straight over your file. She shows the change in
VS Code's diff view first and waits for "confirm"; your old version is
kept next to it as <name>.bak.

Code she writes to answer a question runs in D:\\Hinata_Output\\Code with a
time limit. If it touches files outside that folder, deletes things, runs
programs or talks to the network, she asks first.
"""

import difflib
import os
import re
import shutil
import subprocess
import sys
import time

import config
from pc_actions import Confirm

CODE_DIR = os.path.join(config.OUTPUT_DIR, "Code")
RUN_TIMEOUT = 30

# anything that can change the PC or reach out -> ask first
RISKY_CODE = re.compile(
    r"\b(os\.(remove|unlink|rmdir|removedirs|rename|replace|system|popen|chmod|kill)|shutil\.(rmtree|move|copy\w*)|"
    r"subprocess|send2trash|winreg|ctypes|socket|requests\.(post|put|delete|patch)|urllib|httpx|smtplib|"
    r"pyautogui|keyboard|eval\(|exec\(|__import__|Path\([^)]*\)\.(unlink|rmdir|write_\w+|rename))", re.I)
_WRITE = re.compile(r"open\(\s*(['\"])(.+?)\1\s*,\s*['\"][wax+]", re.I)


def _safe_writes(code: str) -> bool:
    """Writing files is fine only inside the Code folder (relative paths land there)."""
    for m in _WRITE.finditer(code):
        path = m.group(2)
        absolute = os.path.isabs(path) or re.match(r"^(?:[a-z]:|[\\/]|~|%|\$)", path, re.I)
        if absolute or ".." in path.replace("\\", "/").split("/"):
            return False
    return True


def is_risky(code: str) -> bool:
    return bool(RISKY_CODE.search(code)) or not _safe_writes(code)


def _python() -> str:
    return sys.executable or "python"


def run_code(code: str, purpose: str = ""):
    """Runs a Python snippet. Returns its output, or a Confirm if it could change the PC."""
    code = strip_fences(code)
    if not code.strip():
        return "There's no code to run."
    if is_risky(code):
        return Confirm("run_code", code, f"This code {purpose or 'changes things on your PC'}. "
                                         "Say confirm to run it, or cancel.")
    return execute(code)


def execute(code: str) -> str:
    os.makedirs(CODE_DIR, exist_ok=True)
    path = os.path.join(CODE_DIR, f"snippet_{time.strftime('%Y%m%d_%H%M%S')}.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    out, err, code_ = _run([_python(), path], cwd=CODE_DIR)
    if code_ == "timeout":
        return f"It ran longer than {RUN_TIMEOUT} seconds, so I stopped it. The code is in {path}."
    if code_ != 0:
        return f"It failed: {_last_error(err)}"
    out = out.strip()
    return out[:1500] if out else "It ran fine with no output."


def _run(cmd, cwd=None, timeout=RUN_TIMEOUT):
    flags = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           creationflags=flags, env=env, encoding="utf-8", errors="replace")
        return r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired as e:
        return (e.stdout or ""), (e.stderr or ""), "timeout"


def _last_error(err: str) -> str:
    lines = [ln for ln in (err or "").strip().splitlines() if ln.strip()]
    return lines[-1][:300] if lines else "unknown error"


def strip_fences(text: str) -> str:
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", text or "", re.S)
    return (m.group(1) if m else (text or "")).strip("\n")


# ---------------------------------------------------------------- files

_TB_FILE = re.compile(r'File "([^"]+\.py)", line (\d+)')


def files_in_traceback(text: str) -> list[str]:
    """Files from a traceback, innermost first, skipping Python's own libraries."""
    seen, out = set(), []
    for path, _line in reversed(_TB_FILE.findall(text or "")):
        low = path.lower().replace("\\", "/")
        if any(s in low for s in ("/lib/python", "site-packages", "/python3", "\\lib\\", "<frozen")) or \
                re.search(r"/python\d+/lib/", low):
            continue
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def resolve(name: str) -> str | None:
    """A file path from a path or a spoken name ('my bot.py', 'the salon index file')."""
    name = (name or "").strip().strip('"')
    if not name:
        return None
    p = os.path.expandvars(os.path.expanduser(name))
    if os.path.isfile(p):
        return os.path.abspath(p)
    try:
        import file_index
        hits = [h for h in file_index.search(name) if not h["isdir"]]
        if hits:
            return hits[0]["path"]
    except Exception:
        pass
    try:
        import system_info
        return system_info.find_file(os.path.basename(name))
    except Exception:
        return None


def open_in_vscode(target: str) -> str:
    path = resolve(target) or (target if os.path.isdir(target) else None)
    if not path:
        return f"I couldn't find {target}."
    if not _code_cmd([path]):
        os.startfile(path) if os.name == "nt" else None
    return f"Opened {os.path.basename(path)} in VS Code."


def _code_cmd(args) -> bool:
    exe = shutil.which("code") or shutil.which("code.cmd")
    if not exe and os.name == "nt":
        guess = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd")
        exe = guess if os.path.isfile(guess) else None
    if not exe:
        return False
    subprocess.Popen([exe] + list(args), shell=False)
    return True


# ---------------------------------------------------------------- fixing

def fix(target: str = "", error: str = "", ask=None):
    """Proposes a fix for a file. Returns a Confirm (with a diff shown in VS Code) or a reply.

    target: file path or spoken name; if empty, taken from the error's traceback
    error:  the error text (from the screen); if empty and it's a .py file, she runs it to get one
    ask:    fn(prompt, system) -> text; defaults to brain.ask (cloud key if you added one, else local)
    """
    path = resolve(target) if target else None
    if not path:
        for f in files_in_traceback(error):
            if os.path.isfile(f):
                path = f
                break
    if not path:
        return "Which file should I fix? Say its name, or open the error on screen."
    with open(path, encoding="utf-8", errors="replace") as f:
        original = f.read()
    if len(original) > 60000:
        return f"{os.path.basename(path)} is too big for me to fix in one go."
    if not error and path.endswith(".py"):
        out, err, rc = _run([_python(), path], cwd=os.path.dirname(path), timeout=20)
        if rc == 0:
            return f"{os.path.basename(path)} runs without errors. Tell me what's wrong with it."
        error = err if rc != "timeout" else "It runs forever (timed out after 20 s)."
    ask = ask or _default_ask
    prompt = (f"File: {os.path.basename(path)}\n\nERROR:\n{error[-4000:] or '(none given)'}\n\n"
              f"CODE:\n```\n{original}\n```\n\n"
              "Fix the error with the smallest change. Keep everything else exactly the same "
              "(names, comments, formatting). Reply with the COMPLETE fixed file in one code block, "
              "then one line starting with 'WHY:' that says what was wrong.")
    reply = ask(prompt, "You are a careful senior engineer. You fix bugs with minimal edits.")
    if not reply:
        return "My brain didn't answer. Is Ollama running?"
    fixed = strip_fences(reply)
    why = (re.search(r"WHY:\s*(.+)", reply) or [None, "I fixed the error."])[1].strip()
    if fixed.strip() == original.strip() or len(fixed) < 0.5 * len(original.strip()):
        return f"I couldn't find a safe fix for {os.path.basename(path)}. {why}"
    proposal = path + ".hinata-fix"
    with open(proposal, "w", encoding="utf-8") as f:
        f.write(fixed if fixed.endswith("\n") else fixed + "\n")
    changed = sum(1 for ln in difflib.unified_diff(original.splitlines(), fixed.splitlines(), lineterm="")
                  if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---")))
    _code_cmd(["--diff", path, proposal])
    return Confirm("code_fix", (path, proposal),
                   f"{why} I changed {changed} lines - the diff is open in VS Code. "
                   "Say confirm to save it, or cancel.")


def apply_fix(payload) -> str:
    path, proposal = payload
    shutil.copy2(path, path + ".bak")
    os.replace(proposal, path)
    if path.endswith(".py"):
        out, err, rc = _run([_python(), path], cwd=os.path.dirname(path), timeout=20)
        if rc not in (0, "timeout"):
            return f"Saved, with a backup as .bak. It still fails though: {_last_error(err)}"
    return f"Saved the fix. Your old version is {os.path.basename(path)}.bak."


def discard_fix(payload):
    try:
        os.remove(payload[1])
    except OSError:
        pass


def _default_ask(prompt, system):
    import brain
    return brain.ask(prompt, system, max_tokens=8192)


def fix_from_screen() -> object:
    import screen
    text = screen.read_text()
    err = screen.find_error(text)
    if not err:
        return "I don't see an error on your screen."
    return fix("", err)


# ---------------------------------------------------------------- AI tools

def register():
    import commands
    import nlu
    S = "string"
    nlu.register_tools([
        nlu._tool("run_python", "Write and run Python to compute or check something (maths, dates, data, "
                  "conversions, quick scripts). Put the full code in code; the output comes back.", ["code"],
                  code=(S, "complete Python code that prints the answer"), purpose=(S, "one short line: what it does")),
        nlu._tool("fix_code", "Fix a bug in one of the user's code files. Shows the change and waits for confirm.",
                  [], file=(S, "file name or path (optional if the error shows it)"),
                  error=(S, "the error text, if known (e.g. from read_screen_text)")),
        nlu._tool("open_in_vscode", "Open a file or project folder in VS Code.", ["target"],
                  target=(S, "file/folder name or path")),
    ], final={"fix_code", "open_in_vscode"})
    commands.register_handler("run_python", lambda a: run_code(str(a.get("code") or ""), str(a.get("purpose") or "")))
    commands.register_handler("fix_code", lambda a: fix(str(a.get("file") or ""), str(a.get("error") or "")))
    commands.register_handler("open_in_vscode", lambda a: open_in_vscode(str(a.get("target") or "")))
    commands.register_confirm("run_code", execute)
    commands.register_confirm("code_fix", apply_fix, on_cancel=discard_fix)
