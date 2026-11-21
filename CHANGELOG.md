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

## 2.0.0
- Wake word: say "Hinata" (or "Jarvis"). "Hinata, open Chrome" works in one breath. Offline.
- One always-open microphone with voice detection: she acts ~0.4 s after your last word instead of 1.5 s.
- Speech-to-text on the GPU with faster-whisper by default, Google as the fallback.
- Streaming replies: each sentence is spoken as soon as the model writes it. Tool calls, JSON and `<think>` blocks are never read out.
- The voice makes the next sentence's audio while the current one plays. Offline Kokoro voice when the internet drops.
- Tool routing: each request gets only the tools it needs (1-2k tokens instead of 4.4k+, which overflowed the 4k context). Context raised to 8192.
- Long-term memory: remember, recall, forget. Relevant facts go into the AI's instructions automatically.
- All-drives file index in SQLite with trigram search; type and date aware ("physics ppt from last week").
- Browser control in Hinata's own Chrome profile: open, read, click, type, tabs, YouTube. Password boxes are never typed into; pay/send/delete buttons need "confirm".
- Screen OCR with the Windows OCR engine; error detection from screen text.
- Coding helper: run Python snippets, fix a file from its traceback with a diff in VS Code, "read this error and fix it".
- MCP plug-ins from `mcp_servers.json`; writes need "confirm" unless the server is trusted.

## 2.1.0
- Background mode is the default: the full-screen hologram only opens when you say "show hologram" (or set `HOLOGRAM_ON_WAKE`).
- Finished actions are silent with a soft tick; problems and questions are still spoken.
- Instant hands-free commands with no AI: type, enter, new line, select all, copy, paste, undo, delete that, tabs, zoom, and more.
- "Go to <app>" brings a running window to the front by title or program, or opens it.
- Long dictation is pasted in one go and your clipboard is put back.
- Spoken punctuation; the automatic full stop from speech-to-text isn't typed.
- Listen mode: commands without the wake word until "stop listening" or two quiet minutes; chatter that doesn't start like a command is ignored.
- Wake word survives common mishearings after a pause ("and not to type...") when a real command word follows.
- "Hinata, open Chrome" in one breath no longer plays the listening chime.
