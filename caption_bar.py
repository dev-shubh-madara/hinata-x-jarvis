"""
Caption bar: a small glowing strip, centred about 2 cm above the bottom of
the screen, that shows what you said and what Hinata is doing.

    LISTENING   ...
    WORKING     open whatsapp and send hi to anik
    DONE        Sent to Anik.

It appears as soon as she starts listening, stays while she works and fades
out when she's done. In awake mode ("Hey Hinata") it stays on as a slim
"AWAKE" strip until you say "get back to rest".

It never takes keyboard focus and mouse clicks go straight through it, so
"type hello" still types into your app.
"""

import ctypes
import math
import time
import tkinter as tk

BG = "#0d0a1a"
TEXT = "#f1ecff"
MUTED = "#a99fce"
STATE = {
    "listening": ("LISTENING", "#a98cff"),
    "thinking": ("WORKING", "#ff5cbe"),
    "speaking": ("DONE", "#6eb9ff"),
    "idle": ("READY", "#a98cff"),
    "awake": ("AWAKE", "#4fe3b0"),
    "rejected": ("NOT YOU", "#ff4664"),
}
FONT = ("Segoe UI", 13)
FONT_SMALL = ("Segoe UI Semibold", 9)
FPS = 30


def _mix(hex_a: str, hex_b: str, t: float) -> str:
    """Colour between a and b (t=0 -> a, t=1 -> b). Tk has no alpha, so glow is faked by mixing into the background."""
    a = [int(hex_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(hex_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def _round_rect(c, x0, y0, x1, y1, r, **kw):
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
           x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return c.create_polygon(pts, smooth=True, **kw)


def work_area_bottom(screen_h: int) -> int:
    """Top of the taskbar (the bottom of the usable screen)."""
    try:
        class RECT(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]
        r = RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)    # SPI_GETWORKAREA
        return r.b or screen_h
    except Exception:
        return screen_h


def place(screen_w: int, screen_h: int, work_bottom: int, width: int, height: int, two_cm: float):
    """x, y so the bar is centred and its bottom edge is 2 cm above the screen's bottom -
    or just above the taskbar if the taskbar is taller than that."""
    bottom = min(screen_h - two_cm, work_bottom - 10)
    return round((screen_w - width) / 2), round(bottom - height)


def fit(text: str, limit: int = 70) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


class CaptionBar:
    def __init__(self, root, no_activate=None):
        self.root = root
        self.no_activate = no_activate
        self.top = None
        self.canvas = None
        self.state = "listening"
        self.line = ""
        self.visible = False
        self.alpha = 0.0
        self.target_alpha = 0.0
        self.hide_at = None
        self.t0 = time.time()
        self.w, self.h = 560, 64

    # ---- public (call from the Tk thread) ----------------------------------------

    def show(self, state="listening", line=None):
        self._ensure()
        self.hide_at = None
        self.state = state
        if line is not None:
            self.line = line
        self.target_alpha = 0.95
        if not self.visible:
            self.visible = True
            self.top.deiconify()
            self._make_click_through()
            self._tick()
        self._layout()

    def set_state(self, state):
        if state in STATE:
            self.state = state
            if self.visible:
                self._layout()

    def set_line(self, text):
        self.line = fit(text)
        if self.visible:
            self._layout()

    def hide(self, after: float = 1.2):
        """Fade out after a moment, so the last reply can still be read."""
        if self.visible:
            self.hide_at = time.time() + after

    # ---- drawing ---------------------------------------------------------------------

    def _ensure(self):
        if self.top is not None:
            return
        top = tk.Toplevel(self.root)
        top.withdraw()
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        try:
            top.attributes("-alpha", 0.0)
            top.attributes("-transparentcolor", "#010101")
        except tk.TclError:
            pass
        top.configure(bg="#010101")
        self.canvas = tk.Canvas(top, width=self.w, height=self.h, bg="#010101", highlightthickness=0)
        self.canvas.pack()
        self.top = top
        if self.no_activate:
            top.update_idletasks()
            self.no_activate(top)

    def _make_click_through(self):
        """Mouse clicks pass through the bar to whatever is under it."""
        try:
            hwnd = ctypes.windll.user32.GetParent(self.top.winfo_id()) or self.top.winfo_id()
            GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT = -20, 0x00080000, 0x00000020
            WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = 0x08000000, 0x00000080
            u32 = ctypes.windll.user32
            style = u32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            u32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                               style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        except Exception:
            pass

    def _layout(self):
        try:
            import tkinter.font as tkfont
            text_w = tkfont.Font(font=FONT).measure(self.line or "")
        except Exception:
            text_w = 9 * len(self.line or "")
        self.w = max(300, min(820, text_w + 170))
        self.h = 64 if self.line else 44
        self.canvas.config(width=self.w, height=self.h)
        sw, sh = self.top.winfo_screenwidth(), self.top.winfo_screenheight()
        x, y = place(sw, sh, work_area_bottom(sh), self.w, self.h, self.top.winfo_fpixels("2c"))
        self.top.geometry(f"{self.w}x{self.h}+{x}+{y}")
        self._draw(0.0)

    def _draw(self, t):
        c = self.canvas
        c.delete("all")
        label, color = STATE.get(self.state, STATE["idle"])
        pulse = 0.5 + 0.5 * math.sin(t * (5.0 if self.state in ("listening", "thinking") else 2.0))
        w, h, r = self.w, self.h, min(18, self.h // 2 - 2)
        # glow: three soft outlines that breathe with the pulse
        for inset, k, width in ((0, 0.18, 3), (1, 0.38, 2), (3, 0.7, 1)):     # faint outside -> bright inside
            _round_rect(c, inset, inset, w - inset, h - inset, r,
                        fill="", outline=_mix(BG, color, k * (0.55 + 0.45 * pulse)), width=width)
        _round_rect(c, 4, 4, w - 4, h - 4, r - 2, fill=BG, outline="")
        # state dot + label
        cx, cy = 26, h // 2
        rad = 5 + 2 * pulse
        c.create_oval(cx - rad - 4, cy - rad - 4, cx + rad + 4, cy + rad + 4, fill=_mix(BG, color, 0.25), outline="")
        c.create_oval(cx - rad, cy - rad, cx + rad, cy + rad, fill=color, outline="")
        if self.line:
            c.create_text(46, cy - 11, text=label, anchor="w", fill=color, font=FONT_SMALL)
            c.create_text(46, cy + 9, text=self.line, anchor="w", fill=TEXT, font=FONT)
        else:
            hint = "say 'get back to rest' when done" if self.state == "awake" else ""
            c.create_text(46, cy, text=label + ("   " + hint if hint else ""), anchor="w",
                          fill=color if not hint else MUTED, font=FONT_SMALL)
        if self.state == "thinking":                       # a little moving bar while she works
            span = w - 60
            pos = 30 + (t * 260) % span
            c.create_line(max(30, pos - 60), h - 7, pos, h - 7, fill=color, width=2, capstyle="round")

    def _tick(self):
        if not self.visible:
            return
        now = time.time()
        if self.hide_at and now >= self.hide_at:
            self.target_alpha = 0.0
        step = 0.12
        self.alpha += max(-step, min(step, self.target_alpha - self.alpha))
        try:
            self.top.attributes("-alpha", max(0.0, min(1.0, self.alpha)))
        except tk.TclError:
            pass
        if self.alpha <= 0.01 and self.target_alpha == 0.0:
            self.visible = False
            self.hide_at = None
            self.top.withdraw()
            return
        self._draw(now - self.t0)
        self.root.after(int(1000 / FPS), self._tick)
