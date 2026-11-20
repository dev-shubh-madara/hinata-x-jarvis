"""
Plug-in tools over MCP (Model Context Protocol).

Any MCP server - the same ones Claude Desktop and VS Code use - becomes a
set of new Hinata tools without touching her code. Add servers to

    D:\\Hinata_Output\\mcp_servers.json

in the usual format:

    {
      "mcpServers": {
        "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "D:\\\\Projects"]},
        "github":     {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
                       "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "..."}},
        "my_tool":    {"command": "python", "args": ["D:\\\\tools\\\\server.py"], "trusted": true}
      }
    }

then say "reload my plugins". Each server's tools show up to the AI as
mcp__<server>__<tool>, and only when your request mentions them, so the
prompt stays small.

Safety: tools the server marks read-only run straight away. Anything that
could write, delete, send or run things asks for your "confirm", unless
you set "trusted": true for that server.
"""

import json
import os
import re
import subprocess
import threading
import time

import config
from pc_actions import Confirm

CONFIG_PATH = os.path.join(config.OUTPUT_DIR, "mcp_servers.json")
PROTOCOL = "2025-06-18"
WRITE_WORDS = re.compile(r"(write|create|delete|remove|update|edit|move|rename|send|post|push|commit|merge|exec|"
                         r"run|install|upload|publish|set|put|patch|drop|insert|kill|close|transfer|pay)", re.I)

_servers: dict[str, "Server"] = {}
_tools: dict[str, tuple[str, dict]] = {}          # hinata tool name -> (server name, MCP tool)


class Server:
    """One MCP server over stdio (newline-delimited JSON-RPC 2.0)."""

    def __init__(self, name: str, spec: dict):
        self.name = name
        self.spec = spec
        self.proc = None
        self.next_id = 0
        self.waiting: dict[int, dict] = {}
        self.lock = threading.Lock()
        self.tools: list[dict] = []
        self.error = ""

    def start(self, timeout: float = 30) -> bool:
        cmd = [self.spec["command"]] + [str(a) for a in self.spec.get("args", [])]
        env = dict(os.environ, **{k: str(v) for k, v in (self.spec.get("env") or {}).items()})
        flags = 0x08000000 if os.name == "nt" else 0
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         env=env, cwd=self.spec.get("cwd") or None, creationflags=flags,
                                         text=True, encoding="utf-8", errors="replace", bufsize=1,
                                         shell=(os.name == "nt" and cmd[0].lower() in ("npx", "npm", "uvx")))
        except Exception as e:
            self.error = f"couldn't start: {e}"
            return False
        threading.Thread(target=self._read, daemon=True, name=f"mcp-{self.name}").start()
        threading.Thread(target=self._drain_err, daemon=True, name=f"mcp-{self.name}-err").start()
        init = self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                           "clientInfo": {"name": "hinata-x-helper", "version": "2.0"}}, timeout)
        if init is None:
            self.error = self.error or "no answer to initialize"
            self.stop()
            return False
        self.notify("notifications/initialized")
        self.tools = self.list_tools(timeout)
        return True

    def _read(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue                                  # servers sometimes log to stdout - ignore it
            if "id" in msg and ("result" in msg or "error" in msg):
                slot = self.waiting.get(msg["id"])
                if slot is not None:
                    slot["msg"] = msg
                    slot["done"].set()
            elif "id" in msg and "method" in msg:         # server asks us something we don't support
                self._send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "not supported"}})
        for slot in list(self.waiting.values()):
            slot["done"].set()

    def _drain_err(self):
        for line in self.proc.stderr:
            if line.strip():
                print(f"[mcp:{self.name}] {line.rstrip()[:200]}")

    def _send(self, obj):
        with self.lock:
            self.proc.stdin.write(json.dumps(obj) + "\n")
            self.proc.stdin.flush()

    def notify(self, method, params=None):
        self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})})

    def request(self, method, params=None, timeout=60):
        if not self.alive():
            self.error = "server isn't running"
            return None
        with self.lock:
            self.next_id += 1
            rid = self.next_id
        slot = {"done": threading.Event(), "msg": None}
        self.waiting[rid] = slot
        try:
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, **({"params": params} if params else {})})
        except Exception as e:
            self.error = f"pipe closed: {e}"
            self.waiting.pop(rid, None)
            return None
        slot["done"].wait(timeout)
        self.waiting.pop(rid, None)
        msg = slot["msg"]
        if msg is None:
            self.error = f"{method} timed out" if self.alive() else "server stopped"
            return None
        if "error" in msg:
            self.error = str(msg["error"].get("message", msg["error"]))
            return None
        return msg.get("result") or {}

    def list_tools(self, timeout=30) -> list[dict]:
        tools, cursor = [], None
        for _ in range(20):
            res = self.request("tools/list", {"cursor": cursor} if cursor else None, timeout)
            if not res:
                break
            tools += res.get("tools", [])
            cursor = res.get("nextCursor")
            if not cursor:
                break
        return tools

    def call(self, tool: str, args: dict, timeout=120) -> str:
        res = self.request("tools/call", {"name": tool, "arguments": args or {}}, timeout)
        if res is None:
            return f"The {self.name} plug-in failed: {self.error}"
        parts = []
        for c in res.get("content", []):
            if c.get("type") == "text":
                parts.append(c.get("text", ""))
            elif c.get("type") == "resource":
                parts.append(str((c.get("resource") or {}).get("text", "")))
            else:
                parts.append(f"[{c.get('type')}]")
        if res.get("structuredContent") and not parts:
            parts.append(json.dumps(res["structuredContent"])[:3000])
        text = "\n".join(p for p in parts if p).strip() or "Done."
        if res.get("isError"):
            return f"The {self.name} plug-in reported an error: {text[:600]}"
        return text[:4000]

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(3)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass


# ---------------------------------------------------------------- tool mapping

def tool_name(server: str, tool: str) -> str:
    raw = f"mcp__{server}__{tool}"
    return re.sub(r"[^a-zA-Z0-9_]", "_", raw)[:64]


def _schema(tool: dict) -> dict:
    sch = dict(tool.get("inputSchema") or {})
    sch.setdefault("type", "object")
    sch.setdefault("properties", {})
    sch.pop("$schema", None)
    return sch


def needs_confirm(server: "Server", tool: dict) -> bool:
    if server.spec.get("trusted"):
        return False
    ann = tool.get("annotations") or {}
    if ann.get("readOnlyHint") is True:
        return False
    if ann.get("destructiveHint") is True:
        return True
    return bool(WRITE_WORDS.search(tool.get("name", "")))


def _load_config() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except ValueError as e:
        print(f"[mcp] {CONFIG_PATH} isn't valid JSON: {e}")
        return {}
    servers = data.get("mcpServers") or data.get("servers") or {}
    return {k: v for k, v in servers.items() if isinstance(v, dict) and v.get("command") and not v.get("disabled")}


def write_example():
    if os.path.exists(CONFIG_PATH):
        return
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {}, "_example": {
                "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "D:\\Projects"]},
                "my_tool": {"command": "python", "args": ["D:\\tools\\server.py"], "trusted": True}}}, f, indent=2)
    except OSError:
        pass


def start_all(timeout=40) -> str:
    """(Re)starts every server in the config and registers its tools."""
    import commands
    import nlu
    for s in _servers.values():
        s.stop()
    _servers.clear()
    _tools.clear()
    nlu.unregister_tools("mcp__")
    specs = _load_config()
    ok, bad = [], []
    for name, spec in specs.items():
        s = Server(name, spec)
        if s.start(timeout):
            _servers[name] = s
            defs = []
            for tool in s.tools:
                hname = tool_name(name, tool["name"])
                _tools[hname] = (name, tool)
                desc = (tool.get("description") or tool.get("title") or tool["name"]).strip()
                defs.append({"type": "function", "function": {
                    "name": hname, "description": f"[{name} plug-in] {desc[:300]}", "parameters": _schema(tool)}})
                commands.register_handler(hname, lambda a, _h=hname: call(_h, a),
                                          info=bool((tool.get("annotations") or {}).get("readOnlyHint")))
            nlu.register_tools(defs)
            ok.append(f"{name} ({len(s.tools)} tools)")
        else:
            bad.append(f"{name}: {s.error}")
            print(f"[mcp] {name} failed: {s.error}")
    if not specs:
        return f"No plug-ins set up yet. Add MCP servers to {CONFIG_PATH}, then say 'reload my plugins'."
    msg = ("Loaded " + ", ".join(ok) + ".") if ok else "No plug-ins loaded."
    return msg + (" Failed: " + "; ".join(bad) + "." if bad else "")


def call(hname: str, args: dict, confirmed: bool = False):
    if hname not in _tools:
        return "That plug-in isn't loaded."
    server_name, tool = _tools[hname]
    s = _servers.get(server_name)
    if s is None or not s.alive():
        return f"The {server_name} plug-in isn't running. Say 'reload my plugins'."
    if not confirmed and needs_confirm(s, tool):
        short = json.dumps(args, ensure_ascii=False)[:120]
        return Confirm("mcp_call", (hname, args), f"The {server_name} plug-in wants to {tool['name'].replace('_', ' ')} "
                                                  f"with {short}. Say confirm to allow it, or cancel.")
    t0 = time.perf_counter()
    out = s.call(tool["name"], args)
    print(f"[mcp] {hname} ({time.perf_counter() - t0:.2f}s) -> {out[:120]}")
    return out


def summary() -> str:
    if not _servers:
        return f"No plug-ins loaded. Add MCP servers to {CONFIG_PATH}."
    return "Plug-ins: " + ", ".join(f"{n} ({len(s.tools)} tools{'' if s.alive() else ', stopped'})"
                                    for n, s in _servers.items()) + "."


def register():
    import commands
    write_example()
    commands.register_confirm("mcp_call", lambda p: call(p[0], p[1], confirmed=True))
    if _load_config():
        threading.Thread(target=start_all, daemon=True, name="mcp-start").start()
