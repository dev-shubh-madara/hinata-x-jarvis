# How Hinata X Helper works

```
 hotkey (Ctrl+Shift+H / Ctrl+Shift+J)
        │
        ▼
 hotkey_listener ──► speech-to-text (Google / faster-whisper)
        │                 waits for ~2 s of silence, so long sentences are heard in full
        ▼
 session.run_session ── chat?  keep the hologram open and listen again
        │               work?  do it, then close the hologram
        ▼
 commands.handle  (the router)
   1. pending "confirm" / "cancel"   (shut down, delete, calls, payments)
   2. phone pairing                   phone_pair + hotspot
   3. AI phone calls                  call_agent
   4. screen vision / live info       vision, live_info
   5. phone commands                  phone_control  (ADB)
   6. instant patterns                pc_actions     (< 0.3 s, no AI)
   7. local AI agent                  nlu  (Ollama tool calling, multi-step)
        │
        ▼
 tts_engine  (neural female voice, cached)  +  overlay / hud3d (3D hologram)
```

## Modules

| File | Job |
|---|---|
| `main.py` | Starts everything: log, hologram, background warm-up, voice loop |
| `config.py` | Every setting in one place |
| `hotkey_listener.py` | Global hotkeys, microphone, speech-to-text |
| `session.py` | One open-to-close conversation (chat mode vs work mode) |
| `commands.py` | Router: confirmations, fast patterns, phone routing, AI fallback |
| `nlu.py` | Local AI agent on Ollama: about 40 tools, multi-step, JSON fallback |
| `pc_actions.py` | Everything on Windows, plus the PowerShell safety gate |
| `phone_control.py` | Android over ADB: tap by text, type, call, SMS, food ordering, payment lock |
| `phone_pair.py` / `hotspot.py` | QR pairing (Android Wireless debugging), auto hotspot on college Wi-Fi |
| `call_agent.py` | AI phone calls: dial, talk, listen, hang up, transcript |
| `vision.py` | Screenshot plus local vision model, to answer "what's on my screen" |
| `live_info.py` | ISS tracker, news, cricket |
| `overlay.py` | Orb, full-screen HUD, captions, command bar, QR panel |
| `hud3d.py` / `hud_proc.py` | Real-time 3D hologram renderer, running in its own process |
| `tts_engine.py` | Edge neural voice, cache, barge-in |
| `system_info.py` / `web_answer.py` | App and file index, system stats, keyless web answers |

## Safety rules (enforced in code)
- Power actions, deletes, risky PowerShell, calls, SMS and **payments** need a spoken "confirm".
- Payment buttons ("Pay", "Place order"…) are detected on the phone screen and blocked until you say "confirm". "Yes" is not enough.
- AI calls always start with "I'm Hinata, <name>'s AI assistant".
- UPI PINs and lock-screen PINs are never typed.

## Tests
`python tests/run_all.py` runs headless tests with fake phone, PC and AI. No Windows or Ollama needed.
