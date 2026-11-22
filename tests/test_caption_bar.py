"""Caption bar placement and text fitting (no window needed)."""
import os, sys, types
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if "tkinter" not in sys.modules:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        sys.modules["tkinter"] = types.ModuleType("tkinter")
import caption_bar as cb

fails = 0
def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("OK  " if ok else "FAIL") + f" {name:55} -> {got!r}")

two_cm = 75.6                              # 2 cm at 96 dpi
# 1920x1080, taskbar 48 px tall (work area ends at 1032)
x, y = cb.place(1920, 1080, 1032, 600, 64, two_cm)
check("centred horizontally", x + 300, 960)
check("bottom edge 2 cm above the screen bottom", 1080 - (y + 64), round(two_cm))
check("above the taskbar", y + 64 <= 1032, True)
# a tall taskbar (100 px) - sit just above it instead
x, y = cb.place(1920, 1080, 980, 600, 64, two_cm)
check("tall taskbar: sits above it", y + 64, 970)
# 2560x1600 at 150% (2 cm = 113 px)
x, y = cb.place(2560, 1600, 1552, 500, 44, 113.4)
check("high-dpi screen: centred", x + 250, 1280)
check("high-dpi screen: 2 cm up", round(1600 - (y + 44)), 113)
check("short text untouched", cb.fit("open notepad"), "open notepad")
long = "open whatsapp and send a message to Anik that the meeting moved to six in the evening tomorrow"
check("long text trimmed with an ellipsis", (len(cb.fit(long)) <= 70, cb.fit(long).endswith("…")), (True, True))
check("glow colour mix", cb._mix("#000000", "#ffffff", 0.5), "#808080")
print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
