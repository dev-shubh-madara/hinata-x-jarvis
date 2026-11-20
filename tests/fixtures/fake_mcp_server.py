"""A tiny MCP server for tests: one read-only tool, one that sends, paginated tool list."""
import json, sys

TOOLS = [
    {"name": "get_weather", "description": "Current weather for a city.",
     "inputSchema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "send_message", "description": "Send a chat message to a friend.",
     "inputSchema": {"type": "object", "properties": {"to": {"type": "string"}, "text": {"type": "string"}}}},
]
sent = []
print("server log line that is not JSON", flush=True)          # real servers do this
for line in sys.stdin:
    msg = json.loads(line)
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:
        continue
    if method == "initialize":
        res = {"protocolVersion": params["protocolVersion"], "capabilities": {"tools": {}},
               "serverInfo": {"name": "fake", "version": "1"}}
    elif method == "tools/list":
        page = 1 if params.get("cursor") == "p2" else 0
        res = {"tools": [TOOLS[page]]}
        if page == 0:
            res["nextCursor"] = "p2"
    elif method == "tools/call":
        a = params.get("arguments") or {}
        if params["name"] == "get_weather":
            if a.get("city") == "Atlantis":
                res = {"content": [{"type": "text", "text": "Unknown city"}], "isError": True}
            else:
                res = {"content": [{"type": "text", "text": f"{a.get('city')}: 26 C, clear"}]}
        else:
            sent.append(a)
            res = {"content": [{"type": "text", "text": f"sent to {a.get('to')} (total {len(sent)})"}]}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "nope"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": res}), flush=True)
