# Changelog

## 1.0.0
- Voice assistant for Windows with a local AI brain (Ollama): no API keys, no cloud bills.
- Real-time 3D holographic HUD, rendered in its own process with adaptive resolution.
- Neural female voice (Edge TTS) with an offline fallback and barge-in.
- Conversation mode: stays open while you chat, closes after real work.
- Waits for a short pause (1.5 s, configurable) before acting, so long commands are heard in full.
- About 40 tools: apps, files, windows, volume, brightness, documents, PowerPoint, timers, PowerShell (with a safety gate).
- Android phone control over ADB: QR pairing, auto hotspot on college Wi-Fi, tap by text, type, call, SMS.
- FRIDAY-style powers: screen vision, AI phone calls with transcripts, food ordering with a payment lock, ISS, news and cricket.
- Headless test suite and CI.

## 1.1.0
- Right-clicking the hologram sends it back to the orb instead of quitting. Right-clicking the orb opens a small menu.
- Faster replies: small default model (`qwen2.5:3b`), shorter end-of-speech pause, quicker phone reconnect.
- Starts with Windows (`install_autostart.bat`), runs as a single instance.
- Pairing code is the default phone pairing method, with a firewall hint and retries.

## 1.2.0
- Motion studio: say "make a reel about ..." and a small team of agents plans the scenes, picks the characters, records the voice and times it. Preview in the studio, edit by hand or by voice, and the MP4 is saved only when you say "save the video".
- Desktop agent: "take over and ..." works the PC step by step with a visible gliding cursor. Esc stops it. Risky buttons need a spoken confirm and password boxes are never typed into.
- Video editing by voice: cut, speed, reel format, captions, compress, mute, music, GIF, join.
- Website study copy now records the live site in Edge and replays it offline, so JavaScript, 3D and smooth scroll still work. The report compares real vs copy.
- WhatsApp by name: finds the chat in WhatsApp Desktop, no number or country code needed.
- Skills folder for new jobs without touching the code, plus an optional cloud brain (Claude, Gemini or Groq key) for big jobs.
- start_quiet.bat starts Hinata with no console window. New-laptop guide in docs/SETUP.md.
