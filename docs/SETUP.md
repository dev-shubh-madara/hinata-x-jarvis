# Setting up Hinata on a new laptop

Start to end, about 20–30 minutes (most of it is downloads).

## What you need

- Windows 10 or 11
- Internet for the first setup
- About 10 GB free space (the AI models take most of it)
- A mic for voice. Typing works without one.

## 1. Install Python

1. Download Python 3.12 from <https://www.python.org/downloads/>.
2. Run the installer and **tick "Add python.exe to PATH"** at the bottom of the first screen.
3. Click **Install Now**.

Check it: open Command Prompt and type `py --version`. You should see `Python 3.12.x`.

## 2. Install Ollama (the local AI)

1. Download it from <https://ollama.com/download> and install it.
2. Open Command Prompt and pull the models:

```bat
ollama pull qwen2.5:3b
ollama pull gemma3:4b
ollama pull qwen2.5-coder:7b
```

- `qwen2.5:3b` is the main brain (needed).
- `gemma3:4b` lets her look at your screen (optional).
- `qwen2.5-coder:7b` gives better motion videos and a smarter desktop agent. It needs a 6 GB+ GPU. Skip it on a slow laptop and Hinata uses the small model instead.

## 3. Get Hinata

**With Git:**

```bat
cd %USERPROFILE%\Desktop
git clone https://github.com/dev-shubh-madara/hinata-x-jarvis.git Hinata-X-Helper
```

**Without Git:** open the repo page on GitHub, click **Code → Download ZIP**, and extract it to `Desktop\Hinata-X-Helper`.

## 4. Install everything

Open the `Hinata-X-Helper` folder and double-click **`install.bat`**. (From PowerShell, type `.\install.bat` - PowerShell needs the `.\` in front.)
It installs all the Python packages, including the parts for the agents, the motion studio and video editing. It takes 3–5 minutes.

If PyAudio fails to install, open Command Prompt in the folder and run:

```bat
py -3 -m pip install pipwin
py -3 -m pipwin install pyaudio
```

## 5. Start her

Double-click **`start_quiet.bat`**. After about 20–30 seconds the small orb shows up in the top-left corner.

| Do this | What happens |
|---|---|
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>H</kbd> | talk to her |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>J</kbd> | type a command |
| right-click the orb | menu (Quit is here) |

If the hotkeys don't work, start `run.bat` once with right-click → **Run as administrator**.

## 6. Quick test

Press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>J</kbd> and try these:

- `what are your skills`
- `open notepad`
- `make a reel about a chai shop called Chai Adda` (opens the studio, then say `save the video` to keep it)
- `take over and turn on dark mode in settings`
- `clone example.com`

## 7. Optional extras

- **Start with Windows:** double-click `install_autostart.bat`. Undo it with `uninstall_autostart.bat`. On someone else's laptop you'll probably want to skip this.
- **WhatsApp by name:** install WhatsApp Desktop from the Microsoft Store and log in.
- **Phone control:** follow the *Phone control* part of the README (Hinata Link with Termux + Shizuku).
- **Cloud brain for big jobs:** say `add my API key` and paste a Claude, Gemini or Groq key. It's saved on that laptop only.

## Where things go

- Videos, edits, website copies and your own skills go to `D:\Hinata_Output`, or `Desktop\Hinata_Output` if there's no D drive.
- Settings and saved contacts live in `%LOCALAPPDATA%\HinataXHelper`. Delete that folder to wipe her memory from the laptop.
- `hinata.log` in the Hinata folder shows what she did. Send it along when something breaks.

## Removing her

1. Right-click the orb and choose **Quit Hinata**.
2. Run `uninstall_autostart.bat` if you turned autostart on.
3. Delete the `Hinata-X-Helper` folder and `%LOCALAPPDATA%\HinataXHelper`.
4. Optional: uninstall Ollama and Python.
