"""
The agent cursor window - runs in its own process so it stays smooth while
Hinata works (and can never freeze the hologram).

agent_cursor.py starts it and sends one JSON command per line on stdin:
    {"op": "move", "x": 800, "y": 400, "label": "Clicking Send", "ms": 450}
    {"op": "pulse"}        click ripple at the current spot
    {"op": "label", "text": "Typing..."}
    {"op": "hide"} / {"op": "show"} / {"op": "quit"}

The window is click-through and never takes focus, so it can't get in the way
of the real clicks.
"""

import json
import math
import queue
import sys
import threading
import time
import tkinter as tk

KEY = "#010203"                   # transparent colour
W, H = 340, 120                   # window size; the cursor tip sits at (TIP_X, TIP_Y)
TIP_X, TIP_Y = 34, 34
ACCENT = "#6fe3ff"
ACCENT_2 = "#b28cff"
FG = "#eaf6ff"
BG = "#10141c"


def _ease(t):                      # easeInOutCubic
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


class CursorWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass
        self.root.configure(bg=KEY)
        self.cv = tk.Canvas(self.root, width=W, height=H, bg=KEY, highlightthickness=0)
        self.cv.pack()
        self.x = self.root.winfo_screenwidth() / 2
        self.y = self.root.winfo_screenheight() / 2
        self.src = (self.x, self.y)
        self.dst = (self.x, self.y)
        self.t0 = 0.0
        self.dur = 0.0
        self.label = ""
        self.pulse_t = -1.0
        self.visible = True
        self.started = time.time()
        self.inbox: queue.Queue = queue.Queue()
        self._place()
        self.root.update_idletasks()
        self._click_through()
        self._tick()

    def _click_through(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes
            u = ctypes.windll.user32
            hwnd = u.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            GWL_EXSTYLE = -20
            style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
            # layered + transparent (click-through) + toolwindow (no taskbar) + noactivate
            u.SetWindowLongW(hwnd, GWL_EXSTYLE, style | 0x80000 | 0x20 | 0x80 | 0x08000000)
        except Exception:
            pass

    # ------------------------------------------------------------ commands

    def command(self, c: dict):
        op = c.get("op")
        if op == "move":
            self.src = (self.x, self.y)
            self.dst = (float(c["x"]), float(c["y"]))
            self.dur = max(0.05, float(c.get("ms", 450)) / 1000)
            self.t0 = time.time()
            if "label" in c:
                self.label = c.get("label") or ""
            self._show(True)
        elif op == "jump":
            self.x, self.y = float(c["x"]), float(c["y"])
            self.src = self.dst = (self.x, self.y)
            self.dur = 0
            self._show(True)
        elif op == "pulse":
            self.pulse_t = time.time()
        elif op == "label":
            self.label = c.get("text") or ""
        elif op == "hide":
            self._show(False)
        elif op == "show":
            self._show(True)
        elif op == "quit":
            self.root.destroy()

    def _show(self, on):
        if on and not self.visible:
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self._click_through()
        elif not on and self.visible:
            self.root.withdraw()
        self.visible = on

    # ------------------------------------------------------------ drawing

    def _place(self):
        self.root.geometry(f"{W}x{H}+{int(self.x - TIP_X)}+{int(self.y - TIP_Y)}")

    def _tick(self):
        while True:                                # commands from the reader thread
            try:
                c = self.inbox.get_nowait()
            except queue.Empty:
                break
            self.command(c)
            if c.get("op") == "quit":
                return
        now = time.time()
        if self.dur:
            p = min(1.0, (now - self.t0) / self.dur)
            e = _ease(p)
            # slight arc so the glide looks hand-made, not robotic
            sx, sy = self.src
            dx, dy = self.dst
            arc = math.sin(math.pi * e) * min(60, math.hypot(dx - sx, dy - sy) * 0.08)
            self.x = sx + (dx - sx) * e
            self.y = sy + (dy - sy) * e - arc
            if p >= 1:
                self.x, self.y = dx, dy
                self.dur = 0
        if self.visible:
            self._place()
            self._draw(now)
        self.root.after(8, self._tick)            # ~120 Hz loop, the screen shows what it can

    def _draw(self, now):
        cv = self.cv
        cv.delete("all")
        tx, ty = TIP_X, TIP_Y
        breathe = 0.5 + 0.5 * math.sin((now - self.started) * 3.2)

        # glow rings
        for i, col in enumerate(("#0f3443", "#145569", "#1c7d96")):
            r = 22 - i * 5 + breathe * 2
            cv.create_oval(tx - r, ty - r, tx + r, ty + r, outline=col, width=2)

        # click ripple
        if self.pulse_t > 0:
            age = now - self.pulse_t
            if age < 0.55:
                r = 8 + age * 70
                cv.create_oval(tx - r, ty - r, tx + r, ty + r, outline=ACCENT, width=max(1, int(4 - age * 6)))
            else:
                self.pulse_t = -1

        # arrow
        s = 1.15
        pts = [(0, 0), (0, 22), (6, 17), (10, 26), (14, 24), (10, 15), (18, 15)]
        poly = [(tx + px * s, ty + py * s) for px, py in pts]
        shadow = [(x + 2, y + 2) for x, y in poly]
        cv.create_polygon(shadow, fill="#05070a", outline="")
        cv.create_polygon(poly, fill=ACCENT, outline=FG, width=1.5)

        # label chip
        if self.label:
            text = self.label if len(self.label) <= 34 else self.label[:33] + "..."
            lx, ly = tx + 26, ty + 26
            tid = cv.create_text(lx + 12, ly + 13, text=text, anchor="w", fill=FG,
                                 font=("Segoe UI Semibold", 10))
            x1, y1, x2, y2 = cv.bbox(tid)
            cv.create_rectangle(lx, ly, x2 + 12, ly + 26, fill=BG, outline=ACCENT_2, width=1)
            cv.create_rectangle(lx, ly, lx + 3, ly + 26, fill=ACCENT, outline="")
            cv.tag_raise(tid)


def _reader(win: CursorWindow):
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            c = json.loads(line)
        except ValueError:
            continue
        win.inbox.put(c)
        if c.get("op") == "quit":
            return
    win.inbox.put({"op": "quit"})                  # parent went away


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
    win = CursorWindow()
    win.root.withdraw()
    win.visible = False
    threading.Thread(target=_reader, args=(win,), daemon=True).start()
    win.root.mainloop()


if __name__ == "__main__":
    main()
