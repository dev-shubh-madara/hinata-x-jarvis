"""
The on-screen side of Hinata X Helper.

At rest: a small live 3D orb you can drag anywhere (right-click to quit).
On the hotkey: the full-screen real-time 3D hologram (hud3d.py)
    intro  - particles fly in, rings unfold, the core ignites
    loop   - reacts live: lavender = listening, rose = thinking, blue = speaking
    outro  - rings collapse, the globe bursts into sparks

Extras: live captions (what you said, her reply, response time), a typed
command bar, the phone-pairing QR panel, and reminder toasts.

Adaptive quality: the hologram is rendered as large as your PC can keep
smooth. It measures every frame and raises or lowers the resolution to hold
HUD_TARGET_FPS, and remembers the best size for next launch.

Tk runs on the main thread; the voice thread only calls the thread-safe
methods: set_state, set_info, set_caption, expand, collapse, ask_text,
ask_command, show_qr, flash.
"""

import ctypes
import json
import math
import os
import random
import threading
import time
import tkinter as tk
from datetime import datetime

import config

try:
    import psutil
except Exception:
    psutil = None

try:
    import numpy as np
    from PIL import Image, ImageTk
    from hud3d import HoloRenderer
    _HAS_3D = True
except Exception as _e:
    print(f"[overlay] 3D renderer unavailable ({_e}) - simple animation. Run: pip install numpy pillow")
    _HAS_3D = False

# ---- tuning -------------------------------------------------------------
TARGET_FPS = max(20, int(config.HUD_TARGET_FPS))
INTRO_SECONDS = 1.6
OUTRO_SECONDS = 1.0
QUALITY_MAX = {"ultra": 1500, "high": 1150, "medium": 850, "low": 620, "auto": 1150}
QUALITY_MIN = 480
SMALL_SIZE = 88
MINI_FPS = 24
_QUALITY_FILE = os.path.join(config.DATA_DIR, "hud_quality_v2.json")

STATE_LABELS = {"idle": "STANDBY", "listening": "LISTENING", "thinking": "PROCESSING",
                "speaking": "RESPONDING", "rejected": "IGNORED"}

# Hinata theme
LAV = "#a98cff"
LAV_HI = "#efe9ff"
LAV_DIM = "#3b2a6e"
ROSE = "#ff5cbe"
MOON = "#6eb9ff"
STATE_COLORS = {"listening": LAV, "thinking": ROSE, "speaking": MOON, "idle": LAV, "rejected": "#ff4664"}

BG = "#0b0716"
PANEL = "#130d24"
FIELD = "#1b1333"
FG = LAV_HI
MUTED = "#9d93c4"
ACCENT = "#7b5cff"
BTN = "#241a42"

TITLE_FONT = ("Segoe UI Semibold", 11)
MONO = "Consolas"


def _spaced(s: str) -> str:
    return " ".join(s.upper())


class _QRPanel:
    def __init__(self, overlay):
        self._ov = overlay
        self.cancelled = threading.Event()
        self.use_code = threading.Event()
        self.top = None
        self.status_lbl = None

    def status(self, text):
        self._ov.root.after(0, lambda: self.status_lbl and self.status_lbl.config(text=text))

    def close(self):
        def run():
            if self.top is not None:
                try:
                    self.top.destroy()
                except tk.TclError:
                    pass
                self.top = None
        self._ov.root.after(0, run)


class MicOverlay:
    def __init__(self, assistant_name: str = "HINATA X HELPER"):
        self.assistant_name = assistant_name
        try:   # Windows timers default to 15.6 ms steps -> animation capped near 30 FPS. Use 1 ms.
            ctypes.windll.winmm.timeBeginPeriod(1)
        except Exception:
            pass
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self._set_attr("-transparentcolor", "black")

        self.width = self.height = SMALL_SIZE
        self._orb_pos = (60, 60)
        self.root.geometry(f"{SMALL_SIZE}x{SMALL_SIZE}+{self._orb_pos[0]}+{self._orb_pos[1]}")
        self.canvas = tk.Canvas(self.root, width=self.width, height=self.height,
                                highlightthickness=0, bg="black")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonPress-3>", self._on_right_click)
        self.sleep_requested = threading.Event()      # right-click on the HUD = go back to the orb
        self.on_quit = None
        self._drag_offset = (0, 0)

        self._current_state = "idle"
        self._hud_mode = False
        self._tick_angle = 0
        self._info = {"AI": "CHECKING", "MIC": "...", "PHONE": "NOT PAIRED"}
        self._caption = {"you": "", "reply": "", "ms": None}

        # 3D state
        self._renderer = None
        self._mini = HoloRenderer(SMALL_SIZE * 2, mini=True) if _HAS_3D else None
        self._phase = None
        self._phase_start = 0.0
        self._build = 0.0
        self._dissolve = 0.0
        self._job = None
        self._img_item = None
        self._photo = None
        self._photo_mini = None
        self._T = 0
        self._frame_no = 0
        self._t0 = time.perf_counter()
        self._render_px = self._load_quality()
        self._frame_ms = None
        self._last_adapt = 0.0
        # frames are rendered on a background thread; the Tk thread only shows them
        self._rlock = threading.Lock()
        self._latest = None            # (frame_id, PIL image) - newest finished frame
        self._shown_id = -1
        self._render_wake = threading.Event()
        self._hp = None                # separate render process (best), else a thread
        if _HAS_3D and not self._start_render_process():
            threading.Thread(target=self._render_worker, daemon=True, name="hud-render").start()

        self.root.deiconify()
        self.root.update_idletasks()
        self._no_activate(self.root)
        self._animate_idle()

    # ---- render process -------------------------------------------------------

    def _start_render_process(self) -> bool:
        """Runs the 3D renderer in its own process (own CPU core, no GIL fights)."""
        if not getattr(config, "HUD_RENDER_PROCESS", True):
            return False
        try:
            import subprocess
            import sys
            from multiprocessing import shared_memory
            import hud_proc as hp
            max_t = int(getattr(config, "HUD_MAX_PX", 1000))
            shm = shared_memory.SharedMemory(create=True, size=hp.total_size(max_t))
            ints, flts, bufs = hp.layout(shm, max_t)
            ints[:] = 0
            flts[:] = 0
            ints[hp.I_READING] = 2
            flts[hp.F_T0] = self._t0
            flts[hp.F_FPS] = TARGET_FPS
            exe = sys.executable
            if exe.lower().endswith("pythonw.exe"):
                exe = exe[:-5] + ".exe"
            here = os.path.dirname(os.path.abspath(__file__))
            proc = subprocess.Popen([exe, os.path.join(here, "hud_proc.py"), shm.name, str(max_t)],
                                    stdin=subprocess.PIPE, cwd=here,
                                    creationflags=0x08000000 if os.name == "nt" else 0)
            self._hp = {"shm": shm, "ints": ints, "flts": flts, "bufs": bufs, "proc": proc, "mod": hp,
                        "max_t": max_t}
            self.root.bind("<Destroy>", lambda e: self._stop_render_process() if e.widget is self.root else None)
            print(f"[hud] render process started (pid {proc.pid})")
            return True
        except Exception as e:
            print(f"[hud] render process unavailable ({e}) - using a thread")
            self._hp = None
            return False

    def _stop_render_process(self):
        hp = self._hp
        if not hp:
            return
        self._hp = None
        try:
            hp["ints"][hp["mod"].I_QUIT] = 1
            hp["proc"].stdin.close()
        except Exception:
            pass
        try:
            hp["shm"].close()
            hp["shm"].unlink()
        except Exception:
            pass

    def _px_now(self) -> int:
        if self._hp:
            return int(self._hp["ints"][self._hp["mod"].I_PX])
        return getattr(self._renderer, "size", 0)

    def _proc_frame(self):
        """Newest frame from the render process, or None if nothing new."""
        hp = self._hp
        m, ints = hp["mod"], hp["ints"]
        fid = int(ints[m.I_FRAME])
        if fid == self._shown_id:
            return None
        L = int(ints[m.I_LATEST])
        ints[m.I_READING] = L
        if int(ints[m.I_LATEST]) != L:          # it just flipped - take the newer one
            L = int(ints[m.I_LATEST])
            ints[m.I_READING] = L
        T = self._T
        mv = memoryview(hp["bufs"][L])[:T * T * 3]
        self._frame_ms = float(hp["flts"][m.F_MS]) or None
        return fid, Image.frombuffer("RGB", (T, T), mv, "raw", "RGB", 0, 1)

    # ---- helpers ------------------------------------------------------------

    def _set_attr(self, name, value):
        try:
            self.root.wm_attributes(name, value)
        except tk.TclError:
            pass

    def _now(self):
        return time.perf_counter() - self._t0

    @staticmethod
    def _hwnd(win):
        try:
            return ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        except Exception:
            return None

    def _no_activate(self, win):
        """The hologram never steals keyboard focus - so 'type hello' types into
        your app, not into Hinata. Also hides it from the taskbar / Alt+Tab."""
        hwnd = self._hwnd(win)
        if not hwnd:
            return
        try:
            u32 = ctypes.windll.user32
            GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = -20, 0x08000000, 0x00000080
            style = u32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            u32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        except Exception:
            pass

    def _force_focus(self, win, widget=None):
        """Bring a dialog to the front with keyboard focus (Windows otherwise
        blocks background apps from taking focus)."""
        win.lift()
        hwnd = self._hwnd(win)
        try:
            u32 = ctypes.windll.user32
            u32.keybd_event(0x12, 0, 0, 0)        # tap Alt - lets us take the foreground
            u32.SetForegroundWindow(hwnd)
            u32.keybd_event(0x12, 0, 2, 0)
        except Exception:
            pass
        win.focus_force()
        if widget is not None:
            widget.focus_set()

    def _load_quality(self) -> int:
        q = str(config.HUD_QUALITY).lower()
        cap = QUALITY_MAX.get(q, QUALITY_MAX["auto"])
        if q != "auto":
            return cap
        try:
            with open(_QUALITY_FILE) as f:
                return max(QUALITY_MIN, min(cap, int(json.load(f)["px"])))
        except Exception:
            return 820

    def _save_quality(self):
        try:
            with open(_QUALITY_FILE, "w") as f:
                json.dump({"px": int(self._render_px)}, f)
        except Exception:
            pass

    # ---- dragging ---------------------------------------------------------------

    def _start_drag(self, event):
        if not self._hud_mode:
            self._drag_offset = (event.x, event.y)

    def _on_drag(self, event):
        if self._hud_mode:
            return
        x = self.root.winfo_pointerx() - self._drag_offset[0]
        y = self.root.winfo_pointery() - self._drag_offset[1]
        self.root.geometry(f"+{x}+{y}")
        self._orb_pos = (x, y)

    # ---- public, thread-safe API ---------------------------------------------------

    def set_state(self, state: str):
        self.root.after(0, self._apply_state, state)

    def set_info(self, key: str, value: str):
        self.root.after(0, self._info.__setitem__, key, value)

    def set_caption(self, you=None, reply=None, ms=None):
        def run():
            if you is not None:
                self._caption["you"] = you
            if reply is not None:
                self._caption["reply"] = reply
            if ms is not None:
                self._caption["ms"] = ms
            elif you is not None:          # a new command clears the old timing
                self._caption["ms"] = None
            self._draw_captions()
        self.root.after(0, run)

    def expand(self):
        self.root.after(0, self._do_expand)

    def collapse(self):
        self.root.after(0, self._do_collapse)

    # ---- right-click: sleep, never quit by accident -------------------------------

    def _on_right_click(self, event):
        if self._hud_mode:
            # big hologram -> back to the small orb; Hinata keeps running in the background
            self.sleep_requested.set()
            self._do_collapse()
            close = getattr(self, "_close_bar", None)
            if close:
                self._close_bar = None
                try:
                    close()
                except Exception:
                    pass
            try:
                import tts_engine
                tts_engine.stop()
            except Exception:
                pass
            return
        menu = tk.Menu(self.root, tearoff=0, bg=PANEL, fg=FG, activebackground=LAV,
                       activeforeground="#000000", font=("Segoe UI", 10), bd=0)
        menu.add_command(label="  Talk to Hinata   (Ctrl+Shift+H)", command=lambda: self._fire("voice"))
        menu.add_command(label="  Type a command   (Ctrl+Shift+J)", command=lambda: self._fire("type"))
        menu.add_separator()
        menu.add_command(label="  Quit Hinata", command=self._confirm_quit)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _fire(self, kind):
        try:
            import hotkey_listener
            hotkey_listener._fire(kind)
        except Exception as e:
            print(f"[overlay] menu action failed: {e}")

    def _confirm_quit(self):
        from tkinter import messagebox
        if messagebox.askyesno("Hinata X Helper", "Quit Hinata completely?\n\n"
                               "(She'll start again next time you log in.)", parent=self.root):
            if self.on_quit:
                self.on_quit()
            self.root.destroy()

    def consume_sleep(self) -> bool:
        if self.sleep_requested.is_set():
            self.sleep_requested.clear()
            return True
        return False

    def ghost(self, on: bool):
        """Makes Hinata invisible for a moment (so screenshots show YOUR screen, not her)."""
        alpha = 0.0 if on else (config.HUD_OPACITY if self._hud_mode else 1.0)
        done = threading.Event()
        self.root.after(0, lambda: (self._set_attr("-alpha", alpha), done.set()))
        done.wait(1.0)
        time.sleep(0.12 if on else 0)

    def ask_fields(self, prompt, fields, title="Hinata X Helper"):
        """Themed form with several labelled boxes. BLOCKS the calling thread.
        fields: [(label, default, hint)] -> list of strings, or None if cancelled."""
        done, out = threading.Event(), {"v": None}

        def build():
            top = self._dialog(title)
            tk.Label(top, text=prompt, bg=BG, fg=FG, font=("Segoe UI", 11), wraplength=460,
                     justify="left").pack(padx=20, pady=(16, 8), anchor="w")
            entries = []
            for label, default, hint in fields:
                row = tk.Frame(top, bg=BG)
                row.pack(padx=20, pady=4, fill="x")
                tk.Label(row, text=label, bg=BG, fg=LAV, font=("Segoe UI", 10, "bold"), width=14,
                         anchor="w").pack(side="left")
                e = tk.Entry(row, width=24, bg=FIELD, fg=FG, insertbackground=LAV_HI, relief="flat",
                             font=(MONO, 15), highlightthickness=1, highlightbackground=LAV_DIM,
                             highlightcolor=LAV)
                e.pack(side="left", ipady=5, fill="x", expand=True)
                if default:
                    e.insert(0, default)
                if hint:
                    tk.Label(row, text=hint, bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side="left", padx=8)
                entries.append(e)

            def finish(value):
                out["v"] = value
                try:
                    top.destroy()
                finally:
                    done.set()

            def submit(_e=None):
                finish([e.get().strip() for e in entries])

            btns = tk.Frame(top, bg=BG)
            btns.pack(padx=20, pady=(12, 16), anchor="e")
            self._button(btns, "Cancel", lambda: finish(None)).pack(side="right", padx=(8, 0))
            self._button(btns, "Pair", submit, primary=True).pack(side="right")
            for i, e in enumerate(entries):     # Enter jumps to the next box, then pairs
                e.bind("<Return>", (lambda ev, j=i: entries[j + 1].focus_set()) if i < len(entries) - 1 else submit)
            top.bind("<Escape>", lambda e: finish(None))
            top.protocol("WM_DELETE_WINDOW", lambda: finish(None))
            self._center(top)
            first_empty = next((e for e in entries if not e.get()), entries[0])
            top.after(30, lambda: self._force_focus(top, first_empty))

        self.root.after(0, build)
        done.wait(timeout=600)
        return out["v"]

    def ask_text(self, prompt, title="Hinata X Helper"):
        """Themed text prompt. BLOCKS the calling thread. Returns text or None."""
        done, out = threading.Event(), {"v": None}

        def build():
            top = self._dialog(title)
            tk.Label(top, text=prompt, bg=BG, fg=FG, font=("Segoe UI", 11), wraplength=420,
                     justify="left").pack(padx=20, pady=(16, 10), anchor="w")
            entry = tk.Entry(top, width=32, bg=FIELD, fg=FG, insertbackground=LAV_HI, relief="flat",
                             font=(MONO, 15), highlightthickness=1, highlightbackground=LAV_DIM,
                             highlightcolor=LAV)
            entry.pack(padx=20, pady=4, ipady=6, fill="x")

            def finish(value):
                out["v"] = value
                try:
                    top.destroy()
                finally:
                    done.set()

            row = tk.Frame(top, bg=BG)
            row.pack(padx=20, pady=(12, 16), anchor="e")
            self._button(row, "Cancel", lambda: finish(None)).pack(side="right", padx=(8, 0))
            self._button(row, "OK", lambda: finish(entry.get().strip() or None), primary=True).pack(side="right")
            entry.bind("<Return>", lambda e: finish(entry.get().strip() or None))
            top.bind("<Escape>", lambda e: finish(None))
            top.protocol("WM_DELETE_WINDOW", lambda: finish(None))
            self._center(top)
            top.after(30, lambda: self._force_focus(top, entry))

        self.root.after(0, build)
        done.wait(timeout=300)
        return out["v"]

    def ask_command(self):
        """Spotlight-style command bar. BLOCKS the calling thread."""
        done, out = threading.Event(), {"v": None}

        def build():
            top = tk.Toplevel(self.root)
            top.overrideredirect(True)
            top.attributes("-topmost", True)
            top.configure(bg=LAV, padx=2, pady=2)
            inner = tk.Frame(top, bg=PANEL)
            inner.pack(fill="both", expand=True)
            tk.Label(inner, text=_spaced("Hinata"), bg=PANEL, fg=LAV, font=(MONO, 9, "bold")
                     ).pack(anchor="w", padx=18, pady=(12, 0))
            entry = tk.Entry(inner, width=46, bg=PANEL, fg=FG, insertbackground=LAV_HI, relief="flat",
                             font=("Segoe UI", 19), highlightthickness=0)
            entry.pack(padx=18, pady=(2, 4), fill="x")
            tk.Label(inner, text="Enter to run  ·  Esc to close  ·  try: \"open vs code and make a new file\"",
                     bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=18, pady=(0, 12))

            def finish(value):
                out["v"] = value
                try:
                    top.destroy()
                finally:
                    done.set()

            entry.bind("<Return>", lambda e: finish(entry.get().strip() or None))
            entry.bind("<Escape>", lambda e: finish(None))
            self._close_bar = lambda: finish(None)        # right-click on the hologram closes it too
            top.update_idletasks()
            w = top.winfo_reqwidth()
            top.geometry(f"+{(top.winfo_screenwidth() - w) // 2}+{int(top.winfo_screenheight() * 0.22)}")
            top.after(30, lambda: self._force_focus(top, entry))

        self.root.after(0, build)
        done.wait(timeout=600)
        return out["v"]

    def show_qr(self, title, pil_image, steps, footer="",
                subtitle="Scan with your phone to give Hinata control", code_button=True):
        """Non-blocking phone-pairing panel. Returns a handle with .status(),
        .close(), .cancelled and .use_code events."""
        panel = _QRPanel(self)
        ready = threading.Event()

        def build():
            top = self._dialog(title)
            panel.top = top
            tk.Label(top, text=_spaced(title), bg=BG, fg=LAV, font=(MONO, 13, "bold")
                     ).pack(pady=(18, 4))
            tk.Label(top, text=subtitle, bg=BG, fg=MUTED,
                     font=("Segoe UI", 10)).pack(pady=(0, 12))
            frame = tk.Frame(top, bg=LAV, padx=3, pady=3)
            frame.pack()
            from PIL import Image as _Img, ImageTk as _ImgTk
            panel._photo = _ImgTk.PhotoImage(pil_image.resize((300, 300), _Img.NEAREST))
            tk.Label(frame, image=panel._photo, bg="white", bd=0).pack()
            box = tk.Frame(top, bg=PANEL, padx=16, pady=12)
            box.pack(padx=22, pady=14, fill="x")
            for s in steps:
                tk.Label(box, text=s, bg=PANEL, fg=FG, font=("Segoe UI", 10), anchor="w",
                         justify="left").pack(fill="x", pady=1)
            panel.status_lbl = tk.Label(top, text=footer, bg=BG, fg=ROSE, font=(MONO, 10))
            panel.status_lbl.pack(pady=(0, 8))
            row = tk.Frame(top, bg=BG)
            row.pack(pady=(2, 18))
            if code_button:
                self._button(row, "Use pairing code instead", panel.use_code.set).pack(side="left", padx=6)
            else:
                self._button(row, "Phone joined - next", panel.use_code.set).pack(side="left", padx=6)
            self._button(row, "Cancel", lambda: (panel.cancelled.set(), panel.close())).pack(side="left", padx=6)
            top.protocol("WM_DELETE_WINDOW", lambda: (panel.cancelled.set(), panel.close()))
            self._center(top)
            top.lift()
            ready.set()

        self.root.after(0, build)
        ready.wait(timeout=5)
        return panel

    def flash(self, message: str, seconds: float = 7):
        """Small toast in the corner (reminders)."""
        def build():
            top = tk.Toplevel(self.root)
            top.overrideredirect(True)
            top.attributes("-topmost", True)
            top.configure(bg=ROSE, padx=2, pady=2)
            tk.Label(top, text="⏰  " + message, bg=PANEL, fg=FG, font=("Segoe UI", 12),
                     padx=18, pady=12).pack()
            top.update_idletasks()
            sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
            top.geometry(f"+{sw - top.winfo_reqwidth() - 28}+{sh - top.winfo_reqheight() - 70}")
            self._no_activate(top)
            top.after(int(seconds * 1000), top.destroy)
        self.root.after(0, build)

    # ---- dialog helpers -------------------------------------------------------------------

    def _dialog(self, title):
        top = tk.Toplevel(self.root)
        top.title(title)
        top.configure(bg=BG)
        top.attributes("-topmost", True)
        top.resizable(False, False)
        return top

    def _button(self, parent, text, cmd, primary=False):
        return tk.Button(parent, text=text, command=cmd, bg=ACCENT if primary else BTN,
                         fg="#ffffff" if primary else FG, activebackground=LAV,
                         activeforeground="#0b0716", relief="flat", bd=0, padx=16, pady=6,
                         font=("Segoe UI", 10), cursor="hand2")

    def _center(self, top):
        top.update_idletasks()
        w, h = top.winfo_width(), top.winfo_height()
        top.geometry(f"+{(top.winfo_screenwidth() - w) // 2}+{(top.winfo_screenheight() - h) // 2}")

    # ---- expand / collapse ------------------------------------------------------------------

    def _apply_state(self, state: str):
        self._current_state = state

    def _do_expand(self):
        self.sleep_requested.clear()
        now = self._now()
        if self._hud_mode:
            if self._phase == "outro":
                self._phase = "intro"
                self._phase_start = now - (1 - self._dissolve) * INTRO_SECONDS * 0.6
                self._dissolve = 0.0
            return

        self._hud_mode = True
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.width, self.height = sw, sh
        self._set_attr("-transparentcolor", "")
        self._set_attr("-alpha", config.HUD_OPACITY)
        self.root.geometry(f"{sw}x{sh}+0+0")
        self.canvas.config(width=sw, height=sh, bg="#000000")
        self.canvas.delete("all")
        if not _HAS_3D:
            return
        # copying huge frames into the window is the slow part on 2K/4K screens, so cap it
        self._T = int(min(min(sw, sh) * config.HUD_SCALE, getattr(config, "HUD_MAX_PX", 1000)))
        self._shown_times = []
        with self._rlock:
            self._latest = None
        if self._hp:
            m, ints = self._hp["mod"], self._hp["ints"]
            self._T = min(self._T, self._hp["max_t"])
            auto = str(config.HUD_QUALITY).lower() == "auto"
            cap = QUALITY_MAX.get(str(config.HUD_QUALITY).lower(), QUALITY_MAX["auto"])
            ints[m.I_T] = self._T
            ints[m.I_MAXPX] = min(cap, self._T) if auto else 0
            ints[m.I_PX] = min(self._render_px, self._T) if auto else min(cap, self._T)
            self._shown_id = int(ints[m.I_FRAME])
        self._build_backdrop(sw, sh)
        self._img_item = self.canvas.create_image(sw // 2, sh // 2, anchor="center")
        self.canvas.tag_lower(self._img_item)
        self._draw_captions()
        self._phase, self._phase_start = "intro", now
        self._build, self._dissolve = 0.0, 0.0
        self._frame_no = 0
        if self._hp:
            self._push_params()
            self._hp["ints"][self._hp["mod"].I_ACTIVE] = 1
        self._render_wake.set()
        if self._job is None:
            self._tick()

    def _render_worker(self):
        """Background thread: renders + scales frames so the window never stutters."""
        while True:
            if not self._hud_mode or self._phase is None or not self._T:
                self._render_wake.wait(0.25)
                self._render_wake.clear()
                continue
            start = time.perf_counter()
            try:
                self._ensure_renderer()
                state = self._current_state if self._current_state != "idle" else "listening"
                img = self._renderer.render(self._now(), self._build, self._dissolve, state)
                T = self._T
                if T and img.size[0] != T:
                    img = img.resize((T, T), Image.BILINEAR)
                with self._rlock:
                    fid = (self._latest[0] + 1) if self._latest else 0
                    self._latest = (fid, img)
            except Exception as e:
                print(f"[overlay] render error: {e}")
                time.sleep(0.1)
            spent = (time.perf_counter() - start) * 1000
            self._adapt_quality(spent)
            time.sleep(max(0.002, (1000 / TARGET_FPS - spent) / 1000))

    def _ensure_renderer(self):
        px = int(min(self._T, self._render_px))
        if self._renderer is not None and abs(self._renderer.size - px) < 8:
            return
        old = self._renderer
        self._renderer = HoloRenderer(px)
        if old is not None:      # carry the animation state over - no visual jump
            for k in ("_acc", "_acc_hi", "_spin", "_speed", "_think", "_listen", "_talk", "_last_t"):
                setattr(self._renderer, k, getattr(old, k))

    def _adapt_quality(self, frame_ms):
        self._frame_ms = frame_ms if self._frame_ms is None else self._frame_ms * 0.85 + frame_ms * 0.15
        if str(config.HUD_QUALITY).lower() != "auto" or self._frame_no < 12:
            return
        now = self._now()
        if now - self._last_adapt < 1.2:
            return
        budget = 1000 / TARGET_FPS
        cap = min(QUALITY_MAX["auto"], self._T)
        if self._frame_ms > budget * 0.95 and self._render_px > QUALITY_MIN:
            self._render_px = max(QUALITY_MIN, int(self._render_px * 0.87))
        elif self._frame_ms < budget * 0.55 and self._render_px < cap:
            self._render_px = min(cap, int(self._render_px * 1.08))
        else:
            return
        self._last_adapt = now        # the render thread rebuilds at the new size

    def _do_collapse(self):
        if not self._hud_mode:
            return
        if not _HAS_3D:
            self._finish_collapse()
            return
        if self._phase in ("intro", "loop"):
            self._phase, self._phase_start = "outro", self._now()

    def _push_params(self):
        m, ints, flts = self._hp["mod"], self._hp["ints"], self._hp["flts"]
        flts[m.F_BUILD] = self._build
        flts[m.F_DISSOLVE] = self._dissolve
        st = self._current_state if self._current_state in m.STATES else "listening"
        ints[m.I_STATE] = m.STATES.index(st)

    def _finish_collapse(self):
        if self._hp:
            self._hp["ints"][self._hp["mod"].I_ACTIVE] = 0
            self._render_px = max(QUALITY_MIN, self._px_now() or self._render_px)
        st = getattr(self, "_shown_times", [])
        if len(st) > 5 and self._frame_ms:
            print(f"[hud] last {(len(st) - 1) / max(1e-3, st[-1] - st[0]):.0f} FPS, render {self._frame_ms:.0f} ms "
                  f"at {self._px_now()}px -> {self._T}px")
        self._hud_mode = False
        self._phase = None
        if self._job is not None:
            try:
                self.root.after_cancel(self._job)
            except Exception:
                pass
        self._job = None
        self._photo = None
        self._img_item = None
        with self._rlock:
            self._latest = None
        self._shown_id = -1
        self.width = self.height = SMALL_SIZE
        x, y = self._orb_pos
        self._set_attr("-alpha", 1.0)
        self._set_attr("-transparentcolor", "black")
        self.root.geometry(f"{SMALL_SIZE}x{SMALL_SIZE}+{x}+{y}")
        self.canvas.config(width=SMALL_SIZE, height=SMALL_SIZE, bg="black")
        self.canvas.delete("all")
        self._current_state = "idle"
        self._save_quality()

    # ---- backdrop: frame, title, panels, captions ------------------------------------------

    def _build_backdrop(self, sw, sh):
        c = self.canvas
        m = int(min(sw, sh) * 0.035)
        L = int(min(sw, sh) * 0.09)
        for (x, y, dx, dy) in ((m, m, 1, 1), (sw - m, m, -1, 1), (m, sh - m, 1, -1), (sw - m, sh - m, -1, -1)):
            c.create_line(x, y, x + dx * L, y, fill=LAV, width=2, tags=("backdrop", "frame"))
            c.create_line(x, y, x, y + dy * L, fill=LAV, width=2, tags=("backdrop", "frame"))
            c.create_line(x + dx * 8, y + dy * 8, x + dx * (L // 2), y + dy * 8, fill=LAV_DIM,
                          tags=("backdrop", "frame"))

        f_big = max(15, int(sh * 0.025))
        f_small = max(9, int(sh * 0.0135))
        c.create_text(sw // 2, int(sh * 0.05), text=_spaced(self.assistant_name), fill=LAV_HI,
                      font=(MONO, f_big, "bold"), tags=("backdrop", "title"))
        c.create_line(sw // 2 - sw * 0.17, int(sh * 0.078), sw // 2 + sw * 0.17, int(sh * 0.078),
                      fill=LAV_DIM, tags=("backdrop", "frame"))
        c.create_text(sw // 2, int(sh * 0.905), text="", fill=LAV,
                      font=(MONO, max(16, int(sh * 0.028)), "bold"), tags="lbl_state")
        c.create_text(sw // 2, int(sh * 0.872), text="", fill=MUTED,
                      font=("Segoe UI", max(10, int(sh * 0.0135))), tags="lbl_hint")
        c.create_text(sw // 2, int(sh * 0.94), text="", fill=MUTED,
                      font=("Segoe UI", max(11, int(sh * 0.016))), tags="cap_you", width=int(sw * 0.6))
        c.create_text(sw // 2, int(sh * 0.968), text="", fill=LAV_HI,
                      font=("Segoe UI", max(11, int(sh * 0.016))), tags="cap_reply", width=int(sw * 0.7))
        c.create_text(int(sw * 0.955), int(sh * 0.905), text="", fill=ROSE, anchor="e",
                      font=(MONO, max(11, int(sh * 0.017)), "bold"), tags="cap_ms")

        px_l, px_r = int(sw * 0.045), int(sw * 0.955)
        py = int(sh * 0.30)
        c.create_text(px_l, py, text="", fill=LAV, anchor="nw", font=(MONO, f_small), tags="panel_l")
        c.create_text(px_r, py, text="", fill=LAV, anchor="ne", font=(MONO, f_small),
                      tags="panel_r", justify="right")
        c.create_text(px_l, int(sh * 0.955), text="", fill=LAV_DIM, anchor="w", font=(MONO, f_small),
                      tags="perf")
        c.create_line(0, 0, sw, 0, fill=LAV_DIM, tags=("backdrop", "scan"))

    def _draw_captions(self):
        if not (self._hud_mode and config.SHOW_CAPTIONS):
            return
        c = self.canvas
        you, reply, ms = self._caption["you"], self._caption["reply"], self._caption["ms"]
        c.itemconfig("cap_you", text=f"YOU  ›  {you}" if you else "")
        short = reply if len(reply) < 180 else reply[:177] + "..."
        c.itemconfig("cap_reply", text=f"HINATA  ›  {short}" if reply else "")
        c.itemconfig("cap_ms", text=f"⚡ {ms / 1000:.2f}s" if ms is not None else "")

    def _panel_text(self):
        lines_l = ["// SYSTEM"]
        st = self._stats()
        if st:
            cpu, ram, batt = st
            lines_l += [f"CPU    {cpu:5.1f} %", f"RAM    {ram:5.1f} %"]
            if batt is not None:
                lines_l.append(f"POWER  {batt:5d} %")
        lines_l += ["", "// LINK"] + [f"{k:<6} {v}" for k, v in self._info.items()]
        now = datetime.now()
        lines_r = ["// " + now.strftime("%A").upper(), now.strftime("%H:%M:%S"),
                   now.strftime("%d %b %Y").upper(), "", "// MODE",
                   STATE_LABELS.get(self._current_state, "STANDBY")]
        return "\n".join(lines_l), "\n".join(lines_r)

    def _update_backdrop(self, t):
        c = self.canvas
        vis = min(self._build, 1 - self._dissolve)
        state_col = STATE_COLORS.get(self._current_state, LAV)
        label = STATE_LABELS.get(self._current_state, "STANDBY")
        dots = "." * (int(t * 3) % 4) if self._current_state in ("listening", "thinking") else ""
        c.itemconfig("lbl_state", text=_spaced(label) + dots if vis > 0.4 else "", fill=state_col)
        chatting = self._info.get("MODE") == "CONVERSATION" and vis > 0.6
        c.itemconfig("lbl_hint", text="say  \u201cokay Hinata, let's continue with our work\u201d  to close" if chatting else "")
        if self._frame_no % 8 == 0:
            left, right = self._panel_text()
            reveal = max(0.0, min(1.0, (self._build - 0.45) / 0.5)) * (1 - min(1, self._dissolve * 2.5))
            c.itemconfig("panel_l", text=left[:int(len(left) * reveal)], fill=state_col)
            c.itemconfig("panel_r", text=right[:int(len(right) * reveal)], fill=state_col)
            st = getattr(self, "_shown_times", [])
            if self._frame_ms and len(st) > 5:
                fps = (len(st) - 1) / max(1e-3, st[-1] - st[0])      # real frames on screen
                if self._frame_no % 120 == 0:
                    print(f"[hud] {fps:.0f} FPS  render {self._frame_ms:.0f} ms  at {self._px_now()}px -> {self._T}px")
                c.itemconfig("perf", text=f"RENDER {self._px_now()}px  ·  {fps:.0f} FPS" if vis > 0.6 else "")
        state = "normal" if vis > 0.15 else "hidden"
        for tag in ("frame", "title", "scan", "cap_you", "cap_reply", "cap_ms"):
            c.itemconfig(tag, state=state)
        y = (t * 0.18 % 1.0) * self.height
        c.coords("scan", 0, y, self.width, y)

    # ---- render loop --------------------------------------------------------------------------

    def _tick(self):
        self._job = None
        if not (self._hud_mode and _HAS_3D):
            return
        start = time.perf_counter()
        now = self._now()
        elapsed = now - self._phase_start
        if self._phase == "intro":
            self._build = min(1.0, elapsed / INTRO_SECONDS)
            if self._build >= 1.0:
                self._phase = "loop"
        elif self._phase == "loop":
            self._build = 1.0
        elif self._phase == "outro":
            self._dissolve = min(1.0, elapsed / OUTRO_SECONDS)
            if self._dissolve >= 1.0:
                self._finish_collapse()
                return

        try:
            if self._hp:
                self._push_params()
                latest = self._proc_frame()
            else:
                with self._rlock:
                    latest = self._latest
            if latest and latest[0] != self._shown_id:
                fid, img = latest
                if self._photo is not None and (self._photo.width(), self._photo.height()) == img.size:
                    self._photo.paste(img)            # reuse the buffer - much faster than a new image
                else:
                    self._photo = ImageTk.PhotoImage(img)
                    self.canvas.itemconfig(self._img_item, image=self._photo)
                self._shown_id = fid
                self._frame_no += 1
                self._shown_times = (getattr(self, "_shown_times", []) + [now])[-30:]
            self._update_backdrop(now)
        except Exception as e:
            print(f"[overlay] display error: {e}")

        spent_ms = (time.perf_counter() - start) * 1000
        self._job = self.root.after(max(1, int(1000 / TARGET_FPS - spent_ms)), self._tick)

    def _stats(self):
        if psutil is None:
            return None
        try:
            battery = psutil.sensors_battery()
            return (psutil.cpu_percent(interval=None), psutil.virtual_memory().percent,
                    round(battery.percent) if battery else None)
        except Exception:
            return None

    # ---- idle orb ---------------------------------------------------------------------------------

    def _animate_idle(self):
        self._tick_angle = (self._tick_angle + 1) % 3600
        if not self._hud_mode:
            if self._mini is not None:
                self._draw_mini()
            else:
                self._draw_fallback()
        elif not _HAS_3D:
            self._draw_fallback()
        self.root.after(int(1000 / MINI_FPS), self._animate_idle)

    def _draw_mini(self):
        try:
            img = self._mini.render(self._now(), 1.0, 0.0, "idle")
            img = img.resize((SMALL_SIZE, SMALL_SIZE), Image.LANCZOS)
            arr = np.asarray(img).copy()
            arr[arr.max(axis=2) < 30] = 0
            self._photo_mini = ImageTk.PhotoImage(Image.fromarray(arr))
            if not self.canvas.find_withtag("mini"):
                self.canvas.delete("all")
                self.canvas.create_image(SMALL_SIZE // 2, SMALL_SIZE // 2, image=self._photo_mini, tags="mini")
            else:
                self.canvas.itemconfig("mini", image=self._photo_mini)
        except Exception as e:
            print(f"[overlay] mini render error: {e}")
            self._mini = None

    def _draw_fallback(self):
        self.canvas.delete("all")
        cx, cy = self.width // 2, self.height // 2
        scale = min(self.width, self.height)
        big = self._hud_mode
        angle = self._tick_angle * (2.5 if self._current_state == "listening" else 1.0)
        core_r = scale * (0.08 if big else 0.2)
        for i in range(6, 0, -1):
            r = core_r + i * scale * (0.015 if big else 0.03)
            shade = int(30 + 20 * (6 - i))
            self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                    fill=f"#{shade // 2:02x}{shade // 3:02x}{shade:02x}", outline="")
        for ring, (rf, spd) in enumerate(((0.30, 1.0), (0.36, -0.7), (0.42, 0.5))):
            if not big and ring:
                break
            r = scale * (rf if big else 0.42)
            a0 = (angle * spd) % 360
            for k in range(3):
                self.canvas.create_arc(cx - r, cy - r, cx + r, cy + r, start=a0 + k * 120, extent=70,
                                       style="arc", outline=LAV, width=2)
        if big:
            rnd = random.Random(7)
            for _ in range(60):
                pa = rnd.uniform(0, 2 * math.pi) + math.radians(angle * 0.3)
                pd = rnd.uniform(scale * 0.12, scale * 0.45)
                px, py = cx + pd * math.cos(pa), cy + pd * math.sin(pa)
                self.canvas.create_oval(px - 2, py - 2, px + 2, py + 2, fill=LAV_HI, outline="")
            self.canvas.create_text(cx, cy - scale * 0.46, text=_spaced(self.assistant_name), fill=LAV_HI,
                                    font=(MONO, max(14, int(scale * 0.03)), "bold"))
            self.canvas.create_text(cx, cy + scale * 0.46, text=STATE_LABELS.get(self._current_state, ""),
                                    fill=STATE_COLORS.get(self._current_state, LAV),
                                    font=(MONO, max(18, int(scale * 0.04)), "bold"))
        self.canvas.create_oval(cx - core_r * 0.5, cy - core_r * 0.5, cx + core_r * 0.5, cy + core_r * 0.5,
                                fill=LAV_HI, outline="")

    def start(self):
        self.root.mainloop()
