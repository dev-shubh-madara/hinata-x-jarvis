"""MCP plug-ins: a real stdio server becomes Hinata tools; writes need confirm."""
import json, os, sys, types, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
kb = types.ModuleType("keyboard"); kb.send = lambda k: None; kb.write = lambda t, delay=0: None
kb.add_hotkey = lambda *a, **k: None
sys.modules["keyboard"] = kb
import config, commands, nlu, mcp_client

fails = 0
def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("OK  " if ok else "FAIL") + f" {name:55} -> {got!r}")

fake = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "fake_mcp_server.py")
mcp_client.CONFIG_PATH = os.path.join(tempfile.mkdtemp(), "mcp_servers.json")
check("no config yet", commands.handle("reload my plugins").startswith("No plug-ins set up yet"), True)
json.dump({"mcpServers": {"chat": {"command": sys.executable, "args": [fake]},
                          "broken": {"command": "definitely-not-a-real-program-xyz"}}},
          open(mcp_client.CONFIG_PATH, "w"))
msg = commands.handle("reload my plugins")
check("loads the server, both pages of tools", "chat (2 tools)" in msg, True)
check("reports the broken one", "broken:" in msg, True)
check("tools registered for the AI", sorted(n for n in nlu._EXTRA_TOOLS if n.startswith("mcp__")),
      ["mcp__chat__get_weather", "mcp__chat__send_message"])
check("schema passed through", nlu._EXTRA_TOOLS["mcp__chat__get_weather"]["function"]["parameters"]["required"], ["city"])

check("read-only tool runs straight away", commands.execute("mcp__chat__get_weather", {"city": "Warangal"}),
      "Warangal: 26 C, clear")
check("server errors are reported", commands.execute("mcp__chat__get_weather", {"city": "Atlantis"}),
      "The chat plug-in reported an error: Unknown city")
q = commands.execute("mcp__chat__send_message", {"to": "Vishal", "text": "hi"})
check("a sending tool asks first", "Say confirm" in q, True)
check("confirm runs it once", commands.handle("confirm"), "sent to Vishal (total 1)")
commands.execute("mcp__chat__send_message", {"to": "Udit", "text": "yo"})
check("cancel never sends", (commands.handle("cancel"), commands.execute("mcp__chat__get_weather", {"city": "X"}))[0], "Cancelled.")

# the plug-in tools are offered only when the request mentions them
nlu._last_sel.clear()
names = [t["function"]["name"] for t in nlu.select_tools("what's the weather in Warangal")]
check("weather request gets the plug-in", "mcp__chat__get_weather" in names, True)
nlu._last_sel.clear()
names = [t["function"]["name"] for t in nlu.select_tools("open notepad")]
check("unrelated request doesn't", any(n.startswith("mcp__") for n in names), False)

check("summary", commands.handle("what plugins do you have"), "Plug-ins: chat (2 tools).")
# trusted servers skip the confirm
mcp_client._servers["chat"].spec["trusted"] = True
check("trusted server: no confirm", commands.execute("mcp__chat__send_message", {"to": "Aditya"}), "sent to Aditya (total 2)")
for s in mcp_client._servers.values():
    s.stop()
check("stopped server is reported", commands.execute("mcp__chat__get_weather", {"city": "X"}).startswith("The chat plug-in isn't running"), True)

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
