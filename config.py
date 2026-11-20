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
END_OF_SPEECH_PAUSE = 1.5      # she waits this long after you stop talking before acting (raise to 2-3 if she cuts you off)
SPEECH_LANGUAGE = "en-IN"      # "en-IN" Indian English, "hi-IN" Hindi, "en-US"...

# Speech-to-text engine:
#   "fast"    - always-on mic + voice detection + faster-whisper on your GPU (offline, ~0.2s).
#               Falls back to Google by itself if faster-whisper isn't installed.
#   "google"  - free, no setup, needs internet (~0.6-1s), opens the mic per command
#   "whisper" - old offline path (opens the mic per command)
STT_ENGINE = "fast"
WHISPER_MODEL = "small"        # tiny / base / small / medium / large-v3-turbo - bigger = more accurate, slower
END_SILENCE_MS = 450           # "fast" engine: silence after your last word before she acts (raise if she cuts you off)
VAD_AGGRESSIVENESS = 2         # 0-3, higher ignores more background noise (needs webrtcvad)
MIC_DEVICE_INDEX = None        # None = Windows default microphone

# ---- Wake word -------------------------------------------------------------------
# Say her name instead of pressing the hotkey. "Hinata" opens her; "Hinata, open
# Chrome" does it in one breath. Runs offline on the same always-on mic.
WAKE_WORD = True
WAKE_WORDS = ["hinata", "jarvis"]   # any of these at the start of a sentence wakes her

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
FAST_MODEL = "qwen2.5:3b"      # preferred when OLLAMA_MODEL is blank - downloaded once automatically; "" = off
                               # fast + smart picks: qwen2.5:3b, qwen2.5:7b, llama3.2:3b
AGENT_MAX_STEPS = 6            # how many actions the AI may chain for one request
AI_TEMPERATURE = 0.2

# ---- Big jobs: motion videos, the desktop agent, website rebuild plans ---------------
# Say "add my API key" once and Hinata uses that cloud brain for big jobs only.
# Quick answers and normal commands always stay on the fast local model.
CLOUD_AI = "auto"              # "auto" = whichever key you added | "claude" | "gemini" | "groq" | "off"
CLOUD_MODELS = {}              # override model names, e.g. {"gemini": "gemini-flash-latest"}
BIG_LOCAL_MODEL = "qwen2.5-coder:7b"   # stronger local model for big jobs (say "download the big model")
BROWSER_CHANNEL = "msedge"     # browser used for website capture and video rendering ("msedge" / "chrome")

# ---- Agent cursor -------------------------------------------------------------------
# When Hinata works your PC herself, a glowing cursor glides to each thing she clicks
# and shows what she's doing. Press Esc any time to stop her.
AGENT_CURSOR = True
AGENT_CURSOR_SPEED = 1.0       # 1 = normal, 2 = twice as fast
DESK_AGENT_MAX_STEPS = 20

# ---- Motion studio ------------------------------------------------------------------
STUDIO_PORT = 8740             # the studio runs on http://127.0.0.1:8740
MOTION_SIZE = "vertical"       # "vertical" (1080x1920 reels) | "wide" (1920x1080) | "square"
MOTION_FPS = 30
MOTION_AUTO_SAVE = False       # False = preview in the studio only; the MP4 is saved when you say "save the video"

# ---- Safety ------------------------------------------------------------------------
# The AI can run PowerShell to do things no built-in tool covers.
# Read-only / harmless commands run instantly; anything that deletes, formats,
# changes system settings or downloads+executes code asks "say confirm" first.
AUTO_RUN_SAFE_COMMANDS = True
CONFIRM_SECONDS = 25

# ---- 3D HUD -------------------------------------------------------------------------
HUD_QUALITY = "auto"           # "auto" (adapts to your PC), "ultra", "high", "medium", "low"
HUD_TARGET_FPS = 90            # she lowers the render size by herself to hold this
HUD_ORBIT = True               # the 3D core turns a full 360 degrees on every axis
HUD_SCALE = 0.84               # hologram height as a fraction of screen height
HUD_MAX_PX = 760               # cap on the shown hologram size (bigger = sharper but slower on 2K screens)
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
QUICK_ANSWERS = True           # plain questions skip the tool-calling step (answers in about a second)
DEFAULT_COUNTRY_CODE = "91"    # added to 10-digit numbers for WhatsApp
WHATSAPP_OPEN_WAIT = 2.2       # seconds to wait for WhatsApp to open before pressing Enter
WHATSAPP_AUTO_SEND = True      # find the contact by name and send straight away (False = ask "confirm" first)
PAIR_METHOD = "link"           # "link" = Hinata Link (Termux + Shizuku, no adb pairing) | "code" | "qr"
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


def _output_dir() -> str:
    """Everything Hinata makes goes to the D drive when there is one."""
    if os.name == "nt" and os.path.isdir("D:\\"):
        return "D:\\Hinata_Output"
    return os.path.join(DESKTOP_DIR, "Hinata_Output")


DESKTOP_DIR = _desktop()
OUTPUT_DIR = _output_dir()
DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "HinataXHelper")
for _d in (OUTPUT_DIR, DATA_DIR):
    try:
        os.makedirs(_d, exist_ok=True)
    except OSError:
        pass
