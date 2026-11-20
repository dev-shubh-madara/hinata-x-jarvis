# How Hinata X Helper works

```
 wake word "Hinata" (wake.py)  /  hotkey (Ctrl+Shift+H / Ctrl+Shift+J)
        │
        ▼
 hotkey_listener ──► fast_stt: always-on mic, VAD endpoint (~0.4 s), faster-whisper on the GPU
        │                 (Google as the fallback)
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
        │                               only the tools that fit the request (select_tools)
        │                               + memory, files, browser, coder, MCP plug-ins (powers.py)
        ▼
 tts_engine  (streamed sentence by sentence, synthesized ahead)  +  overlay / hud3d (3D hologram)
```

## Modules

| File | Job |
|---|---|
| `main.py` | Starts everything: log, hologram, background warm-up, voice loop |
| `config.py` | Every setting in one place |
| `hotkey_listener.py` | Global hotkeys and triggers |
| `fast_stt.py` | Always-on mic, voice activity detection, faster-whisper |
| `wake.py` | The "Hinata" wake word |
| `memory.py` | Long-term memory, injected into prompts when relevant |
| `file_index.py` | All-drives file index (SQLite + trigram full-text) |
| `browser.py` | Playwright-driven Chrome with its own profile |
| `screen.py` | Windows OCR of the screen, error detection |
| `coder.py` | Run Python, fix files with a confirmed diff, VS Code |
| `mcp_client.py` | MCP servers over stdio as extra tools |
| `kokoro_tts.py` | Offline voice |
| `powers.py` | Registers the modules above with the agent |
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
- The browser never types into password, card, CVV or OTP boxes; pay/buy/send/delete buttons need "confirm".
- Code that leaves the Code folder, runs programs or uses the network needs "confirm"; fixes are saved only after "confirm", with a .bak.
- MCP tools that aren't read-only need "confirm" unless the server is marked trusted.
- Wake word audio stays on the laptop; only phrases that start with her name are acted on.

## Tests
`python tests/run_all.py` runs headless tests with fake phone, PC and AI. No Windows or Ollama needed.
