"""
Central configuration for Hinata X Helper.
Everything you'd want to tweak lives here - no other file needs editing.
"""

import os

# ---- Identity -------------------------------------------------------------
ASSISTANT_NAME = "Hinata X Helper"
USER_NAME = "Shubh"            # your name (used on calls: "I'm Shubh's assistant")
USER_TITLE = "Boss"            # what Hinata calls you - "Okay, Boss"
VISION_MODEL = "qwen2.5vl:3b"  # local vision model for "look at my screen" (auto-downloaded)
CALL_AI_ENABLED = True         # Hinata can talk on phone calls for you
CALL_AUDIO = "phonelink"       # "phonelink" = call audio comes through Phone Link (Bluetooth) - cleanest
                               # "speakerphone" = no setup (phone on loudspeaker next to the laptop)
                               # Optional: VB-Audio Cable + CALL_PLAYBACK_DEVICE for studio-clean audio
CALL_PLAYBACK_DEVICE = "CABLE Input"   # where Hinata speaks into the call ("" = default speakers)
CALL_MAX_MINUTES = 4
CALL_LANGUAGE = "en-IN"         # speech recognition language on calls ("hi-IN" for Hindi)
USER_PRONOUN = "he"            # used on calls: "he asked me to tell you..."

# ---- Activation -------------------------------------------------------------
# Avoid F1-F12: many laptops grab them in firmware (mic mute, brightness...).
HOTKEY = "ctrl+shift+h"       # press, then SPEAK a command (avoid Alt+Space: Windows opens a window menu)
TYPE_HOTKEY = "ctrl+shift+j"  # press, then TYPE a command (fastest - no speech step)
LISTEN_TIMEOUT = 7             # seconds to wait for you to start speaking
PHRASE_TIME_LIMIT = 30         # max seconds for one spoken command (long sentences are fine)
END_OF_SPEECH_PAUSE = 2.2      # she waits this long after you stop talking before acting (2-3 s)
SPEECH_LANGUAGE = "en-IN"      # "en-IN" Indian English, "hi-IN" Hindi, "en-US"...

# Speech-to-text engine:
#   "google"  - free, no setup, needs internet (~0.6-1s)
#   "whisper" - fully offline on your GPU via faster-whisper (pip install faster-whisper)
STT_ENGINE = "google"
WHISPER_MODEL = "small"        # tiny / base / small / medium - bigger = more accurate, slower

# ---- Conversation mode ---------------------------------------------------------
# While you're just talking (questions, chat - anything that needs no work on the
# PC) the hologram stays open and keeps listening, so you don't press the hotkey
# between sentences. It closes by itself the moment she does real work (open, make,
# play, pair phone...) or when you say "okay Hinata, let's continue with our work".
CONVERSATION_MODE = True
CONVO_LISTEN_TIMEOUT = 8       # seconds she waits for your next sentence
CONVO_IDLE_SECONDS = 30        # total silence before she closes on her own

# ---- Voice (female) -----------------------------------------------------------
# "neural" = Microsoft Edge neural voice (natural, needs internet, free, no key)
# "system" = built-in Windows voice (Zira) - offline, more robotic
TTS_ENGINE = "neural"
NEURAL_VOICE = "en-IN-NeerjaNeural"   # try: en-US-AriaNeural, en-US-JennyNeural,
                                      #      en-GB-SoniaNeural, hi-IN-SwaraNeural
VOICE_RATE = "+8%"                    # neural speed, e.g. "+0%", "+15%"
VOICE_PITCH = "+0Hz"                  # neural pitch, e.g. "+20Hz" for brighter
SYSTEM_VOICE_RATE = 1                 # SAPI fallback speed: -10 .. 10
CHIME = True                          # short sound the moment the hotkey fires

# ---- Local AI brain (Ollama) ----------------------------------------------------
OLLAMA_HOST = ""               # blank = 127.0.0.1:11434
OLLAMA_MODEL = ""              # exact name from "ollama list", or "" to auto-pick
                               # fast + smart picks: qwen2.5:3b, qwen2.5:7b, llama3.2:3b
AGENT_MAX_STEPS = 6            # how many actions the AI may chain for one request
AI_TEMPERATURE = 0.2

# ---- Safety ------------------------------------------------------------------------
# The AI can run PowerShell to do things no built-in tool covers.
# Read-only / harmless commands run instantly; anything that deletes, formats,
# changes system settings or downloads+executes code asks "say confirm" first.
AUTO_RUN_SAFE_COMMANDS = True
CONFIRM_SECONDS = 25

# ---- 3D HUD -------------------------------------------------------------------------
HUD_QUALITY = "auto"           # "auto" (adapts to your PC), "ultra", "high", "medium", "low"
HUD_TARGET_FPS = 50
HUD_SCALE = 0.84               # hologram height as a fraction of screen height
HUD_MAX_PX = 1000              # cap on the shown hologram size (bigger = sharper but slower on 2K screens)
HUD_RENDER_PROCESS = True      # draw the hologram in its own process (smoothest); False = thread
HUD_OPACITY = 0.94
SHOW_CAPTIONS = True           # show what you said + the reply + response time

# ---- Known apps (Windows) ------------------------------------------------------------
# Anything not listed is found automatically from your Start menu
# (WhatsApp, VS Code, Spotify, Discord, Store apps...).
KNOWN_APPS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",
    "word": "winword.exe",
    "powerpoint": "powerpnt.exe",
    "excel": "excel.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",
    "powershell": "powershell.exe",
    "terminal": "wt.exe",
    "task manager": "taskmgr.exe",
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "settings": "ms-settings:",
    "control panel": "control.exe",
    "snipping tool": "snippingtool.exe",
}

KNOWN_SITES = {
    "youtube": "https://youtube.com",
    "youtube music": "https://music.youtube.com",
    "gmail": "https://mail.google.com",
    "google": "https://google.com",
    "github": "https://github.com",
    "chatgpt": "https://chat.openai.com",
    "claude": "https://claude.ai",
    "instagram": "https://instagram.com",
    "linkedin": "https://linkedin.com",
    "whatsapp web": "https://web.whatsapp.com",
}

# ---- Weather ---------------------------------------------------------------------------
DEFAULT_CITY = ""              # blank = auto-detect from your internet connection

# ---- Phone -----------------------------------------------------------------------------
PHONE_AUTO_RECONNECT = True    # reconnect a paired phone at startup if Wireless debugging is on
SCRCPY_PATH = "scrcpy"         # for "show my phone screen" (optional, see README)


# ---- Paths -----------------------------------------------------------------------------
def _desktop() -> str:
    """Real Desktop folder - on OneDrive PCs it lives in OneDrive\\Desktop."""
    home = os.path.expanduser("~")
    for root in (os.environ.get("OneDrive"), os.environ.get("OneDriveConsumer")):
        if root and os.path.isdir(os.path.join(root, "Desktop")):
            return os.path.join(root, "Desktop")
    return os.path.join(home, "Desktop")


DESKTOP_DIR = _desktop()
OUTPUT_DIR = os.path.join(DESKTOP_DIR, "Hinata_Output")
DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "HinataXHelper")
for _d in (OUTPUT_DIR, DATA_DIR):
    try:
        os.makedirs(_d, exist_ok=True)
    except OSError:
        pass
