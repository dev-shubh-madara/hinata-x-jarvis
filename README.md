<div align="center">

# 💜 Hinata X Helper

**A fast, voice-controlled AI assistant for your Windows PC *and* your Android phone, with a real-time 3D holographic HUD.**

Press a hotkey, say what you want, and it's done. Runs on a **local AI** (Ollama), so there's no API key, no cloud bill and no usage limits.

`Python` · `Ollama` · `ADB` · `NumPy 3D renderer` · `Neural female voice` · `MIT`

<img src="docs/hologram.png" width="420" alt="Hinata's 3D hologram">

</div>

---

## ✨ Features

- **Do anything on the PC.** Open any app, file, folder or site. Type, press shortcuts, control windows, volume, brightness and media. Take screenshots, write documents and code, build PowerPoints, set timers, manage files, and change settings.
- **A multi-step AI agent.** Ask *"open notepad and write a poem about rain"* or *"find my resume and move it to Downloads"*, and Hinata chains the steps herself.
- **PowerShell for everything else.** If no built-in tool covers a request, she writes and runs a PowerShell command. Risky commands always ask you to say **"confirm"** first.
- **Phone control with QR pairing.** Say *"pair to phone"* and scan the QR code. After that she can open apps, tap buttons by their on-screen text, type, swipe, call contacts by name, text, take screenshots, toggle Wi-Fi or Bluetooth, read the screen, and mirror it on your PC.
- **A natural female voice.** It uses Microsoft neural voices (free, no key). If you're offline, it falls back to the built-in Windows voice.
- **Fast.** Common commands skip the AI and run in under 0.3 seconds. The AI model is preloaded and kept warm, and apps and files are indexed in the background.
- **A cinematic 3D HUD.** The hologram is rendered live every frame: a particle globe, orbit rings, a radar sweep and bloom glow. It sets its own resolution to keep the animation smooth on your PC. Captions show what you said, her reply, and the response time.
- **Barge-in.** Press the hotkey while she's talking and she stops to listen.
- **Typed commands.** `Ctrl+Shift+J` opens a command bar, which is useful in a quiet room or when you need maximum speed.

## ⚡ Speed

| Request type | Typical time* |
|---|---|
| Instant commands (open, close, play, volume, timer...) | **0.05 – 0.4 s** |
| AI, single action (`qwen2.5:3b` on GPU) | **0.5 – 1.5 s** |
| AI, multi-step task | about 1 – 1.5 s per step |
| Speech recognition (Google) | about 0.6 – 1 s after you stop talking |

<sub>*These are measured from the end of your command to the start of the action. Actual speed depends on your GPU, the model and your internet connection. Use a small tool-calling model for the best speed.</sub>

## 🚀 Install

1. **Python 3.10+.** Install it from [python.org](https://python.org) and tick *"Add to PATH"*.
2. **Ollama** (the local AI brain). Install it from [ollama.com](https://ollama.com), then run:
   ```bash
   ollama pull qwen2.5:3b
   ```
   On a stronger GPU, `qwen2.5:7b` is smarter.
3. **Install the dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
   If PyAudio fails to install: `pip install pipwin && pipwin install pyaudio`
4. **Run it:**
   ```bash
   python main.py
   ```
   You can also double-click `run.bat`.

The `keyboard` library needs global hotkeys. If the hotkeys don't respond, run the terminal as administrator.

## 🎙️ Use it

| Hotkey | Action |
|---|---|
| `Ctrl + Shift + H` | Speak a command |
| `Ctrl + Shift + J` | Type a command |
| Right-click the orb | Quit |

**Things to say:**

| Say | What happens |
|---|---|
| "open vs code" / "open resume.pdf" / "open downloads" | Opens any app, file or folder (found automatically) |
| "play believer by imagine dragons" | Starts playing it on YouTube |
| "volume 30" / "brightness 70" / "mute" | Sets the volume, brightness or mute |
| "open notepad and type hello world" | Multi-step: opens Notepad, then types |
| "write an essay about AI" | Writes it, saves it and opens it |
| "make a presentation about black holes" | Builds a styled .pptx with AI-written slides |
| "remind me in 10 minutes to drink water" | Sets a spoken reminder with a toast |
| "how's my laptop doing" | Reads out CPU, RAM, disk and the heaviest apps |
| "what's my IP address" | Runs PowerShell through the agent |
| "create a folder called projects on desktop" | Creates the folder |
| "shut down" → "confirm" | Power actions always ask first |
| **"pair to phone"** | Shows the QR code for phone pairing |
| "on my phone open whatsapp" | Opens WhatsApp on the phone |
| "on my phone tap Vishal" / "type hi" / "tap send" | Taps by on-screen text and types |
| "call mom on my phone" → "confirm" | Calls the contact by name |
| "on my phone text Mom saying I'm on my way" | Prepares the SMS; say "confirm" to send |
| "show my phone screen" | Mirrors the phone on your PC (needs scrcpy) |

## 👂 Listening

Speak naturally. Hinata waits until you've been quiet for about **2 seconds** before she acts, so long sentences and short pauses are fine. Change this with `END_OF_SPEECH_PAUSE` in `config.py` (lower means snappier).

## 💬 Conversation mode

Hinata adapts to what you ask:

- **Just talking** (questions, chat, "what time is it", weather) - the hologram **stays open** and she keeps listening for your next sentence. No hotkey between sentences.
- **Real work** ("open Chrome", "make a presentation", "play a song", "show the phone QR", "type this") - she does it, answers in a few words, and the hologram **closes** so you can see the result. Press the hotkey to bring her back.
- **Asking you to confirm** (shut down, delete, call...) - stays open and waits for "confirm" or "cancel".
- **To end a chat:** say *"Okay Hinata, let's continue with our work"* (or "that's all" / "bye Hinata"). She also closes by herself after 30 seconds of silence.

Turn it off with `CONVERSATION_MODE = False` in `config.py` (she then closes after every command). Tune the waiting time with `CONVO_IDLE_SECONDS`. If she ever hears her own voice, use headphones.

## 🧠 FRIDAY-style powers

| Say | What happens |
|---|---|
| "What is this video about?" / "How do I export this?" / "What does this error mean?" | She **looks at your screen** with a local vision model and answers. On first use she downloads `qwen2.5vl:3b` (~3 GB) automatically. |
| "Where is the ISS right now?" | Live International Space Station position, spoken, with the live map opened |
| "Latest news" / "News about ISRO" / "Cricket score" | Live headlines and scores |
| "Order chicken biryani on Swiggy" | Opens Swiggy (or Zomato) on your phone, searches, picks a restaurant, adds it and goes to the cart. **She stops at the Pay / Place order button and tells you the total.** Only the word **"confirm"** pays; UPI PINs are always yours to type. |
| "Call mom and tell her I'll be late today" | After you say "confirm", **she makes the call and does the talking**: *"Hello Mom, I'm Hinata, Shubh's AI assistant…"*. She listens, replies, hangs up, then pops up the transcript (saved in `Hinata_Output/Calls`). |

She calls you **"Boss"**. Change `USER_TITLE` and `USER_NAME` in `config.py`.

### 📞 AI phone calls
**Default: speakerphone mode (no setup, no Phone Link, no cable).** Hinata dials from your phone, turns on the phone's loudspeaker when they answer, listens with the laptop mic, and talks through the laptop speakers. Keep the phone next to the laptop in a quiet room.

**Optional, cleaner audio: Phone Link mode.** Set `CALL_AUDIO = "phonelink"` in `config.py`, then do this one-time setup:
1. Install **Phone Link** on the laptop (it's built into Windows 11) and **Link to Windows** on the phone. Pair them and turn on **Calls** (it uses Bluetooth).
2. Install the free **VB-Audio Virtual Cable** from vb-audio.com/Cable.
3. In **Windows Sound settings → Recording**, right-click **CABLE Output** and choose **Set as Default Communication Device**. Phone Link uses this as its microphone, so Hinata's voice goes into the call.
4. Run `pip install pyaudiowpatch miniaudio`.

The call is placed from your own phone, so your number shows. Without the cable it still works: she speaks through the laptop speakers and the mic picks her up, just less cleanly. For Hindi calls, set `CALL_LANGUAGE = "hi-IN"`.

## 📱 Phone pairing (QR)

This uses Android's official **Wireless debugging**, the same QR pairing Android Studio uses.

1. Connect the phone and the PC to the **same Wi-Fi**.
2. On the phone, go to **Settings → About phone** and tap **Build number** 7 times to enable Developer options.
3. Go to **Settings → Developer options → Wireless debugging** and switch it on.
4. Say **"pair to phone"**. A QR code appears on the PC.
5. On the phone, tap **"Pair device with QR code"** and scan it. Done ✅

From then on, Hinata reconnects automatically whenever Wireless debugging is on. Requirements: Android 11+, plus Google's `adb` tool, which is **downloaded automatically** if it's missing. For screen mirroring, install scrcpy with `winget install Genymobile.scrcpy`.

> If the QR scan isn't found (some routers block discovery), click **"Use pairing code instead"** on the QR panel.
>
> Some phones (Xiaomi, Realme, Oppo) also need **"USB debugging (Security settings)"** turned on in Developer options before taps and typing will work.

## ⚙️ Configuration

Everything is in **`config.py`**:

- `ASSISTANT_NAME`, `USER_NAME`
- `HOTKEY`, `TYPE_HOTKEY`
- `NEURAL_VOICE`: try `en-US-AriaNeural`, `en-GB-SoniaNeural` or `hi-IN-SwaraNeural`
- `STT_ENGINE`: `"google"` (default) or `"whisper"` for fully offline speech recognition on your GPU (`pip install faster-whisper`)
- `OLLAMA_MODEL`: a specific model, or leave it blank to pick one automatically
- `HUD_QUALITY`: `auto` / `ultra` / `high` / `medium` / `low`, plus `HUD_TARGET_FPS`
- `AUTO_RUN_SAFE_COMMANDS`: set it to `False` to confirm **every** PowerShell command

## 🛡️ Safety

- Hinata only acts after you press the hotkey. She never listens in the background.
- Shut down, restart, sign out, deleting files (they go to the Recycle Bin), calls, SMS, and any PowerShell that deletes, installs, downloads or changes system settings all need a spoken **"confirm"** within 25 seconds.
- Everything runs locally. The only internet use is Google speech recognition, the neural voice, weather, and YouTube search.

## 🗂️ Project structure

```
main.py             app loop: hotkeys → listen → act → speak
config.py           every setting
commands.py         router: confirmations, instant patterns, phone routing, AI fallback
nlu.py              local AI agent (Ollama tool calling, multi-step)
pc_actions.py       everything it can do on Windows (+ PowerShell safety gate)
phone_pair.py       QR pairing + auto-reconnect (ADB Wireless debugging, mDNS)
phone_control.py    phone actions over ADB (tap-by-text, type, call, SMS...)
tts_engine.py       female neural voice + cache + barge-in
hotkey_listener.py  global hotkeys + speech-to-text (Google / faster-whisper)
overlay.py          orb, full-screen HUD, captions, command bar, QR panel
hud3d.py            real-time 3D hologram renderer (NumPy + Pillow)
system_info.py      app/file index, battery, stats, weather
web_answer.py       keyless answers when the AI is offline
```

## 🧪 Tests

```bash
python tests/run_all.py
```

The tests run headless, with a fake phone, PC and AI, so they work without Windows or Ollama. They cover the command router, conversation mode, the AI agent loop, QR pairing, AI calls and the payment lock. CI runs them on every push. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the pieces fit together.

## 🧰 Troubleshooting

| Problem | Fix |
|---|---|
| "AI brain offline" | Open the Ollama app, then check with `ollama list` and `python nlu.py` |
| Hotkey does nothing | Run the terminal as administrator, or change `HOTKEY` |
| Robotic voice | The neural voice needs internet; the robotic voice is the offline fallback |
| Phone not found after scanning | Check that both devices are on the same Wi-Fi, scan from Wireless debugging (not the camera), or use the pairing code |
| Taps or typing on the phone do nothing | Turn on "USB debugging (Security settings)" (Xiaomi/Realme/Oppo) |
| HUD is laggy | Set `HUD_QUALITY = "medium"` or lower `HUD_TARGET_FPS` |

## 🤝 Contributing

PRs are welcome: new tools (add them in `nlu.py` → `TOOLS` and `commands.py` → `_execute`), new HUD themes, Linux/macOS support, and translations.

## 📄 License

MIT © 2026 **Shubh** ([@dev-shubh-madara](https://github.com/dev-shubh-madara)). If you like it, give it a ⭐!
