"""Focus mode - silence everything for a deep-work block."""
import re
import threading

NAME = "focus mode"
DESCRIPTION = "mutes the PC, hides every window and starts a focus timer (25 minutes by default)"
TRIGGERS = [r"\bfocus mode\b", r"\bdeep work\b", r"\bpomodoro\b"]


def run(text, ctx):
    m = re.search(r"(\d+)\s*(?:min|minute)", text)
    minutes = int(m.group(1)) if m else 25
    ctx.execute("volume", {"action": "mute"})
    ctx.execute("window", {"action": "minimize_all"})

    def done():
        ctx.execute("volume", {"action": "unmute"})
        if ctx.speak:
            ctx.speak(f"Focus block done. {minutes} minutes - nice work. Take a short break.")
    threading.Timer(minutes * 60, done).start()
    return f"Focus mode on for {minutes} minutes. Sound is off and your windows are hidden."
