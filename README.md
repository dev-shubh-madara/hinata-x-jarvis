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
