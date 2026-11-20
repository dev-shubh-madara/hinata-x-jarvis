"""
Loads Hinata's extra powers and gives their tools to the AI agent.

Each power is one module with a register() function that calls
nlu.register_tools(...) and commands.register_handler(...). A power that
fails to load (missing package, no Windows) is skipped with a log line,
so Hinata always starts.
"""

POWERS = ["memory", "file_index", "screen", "browser", "coder", "mcp_client"]
loaded: list[str] = []
failed: dict[str, str] = {}


def load():
    import importlib
    for name in POWERS:
        if name in loaded:
            continue
        try:
            mod = importlib.import_module(name)
            mod.register()
            loaded.append(name)
        except Exception as e:
            failed[name] = str(e)
            print(f"[powers] {name} not loaded: {e}")
