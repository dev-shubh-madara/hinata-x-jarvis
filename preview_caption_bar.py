"""Shows the caption bar going through its states for ~12 seconds (to see how it looks)."""
import tkinter as tk

import caption_bar

root = tk.Tk()
root.withdraw()
bar = caption_bar.CaptionBar(root)


def report(tag):
    t = bar.top
    if t is None:
        print(tag, "no window yet", flush=True)
        return
    print(f"{tag}: visible={bar.visible} alpha={bar.alpha:.2f} state={bar.state} "
          f"geometry={t.winfo_width()}x{t.winfo_height()}+{t.winfo_x()}+{t.winfo_y()} "
          f"mapped={t.winfo_ismapped()} screen={t.winfo_screenwidth()}x{t.winfo_screenheight()} "
          f"2cm={t.winfo_fpixels('2c'):.0f}px", flush=True)


steps = [
    (0, lambda: bar.show("listening", line="")),
    (1000, lambda: report("listening")),
    (1500, lambda: bar.show("thinking", line="open whatsapp and send hi to Anik")),
    (3000, lambda: report("working")),
    (4500, lambda: (bar.set_state("speaking"), bar.set_line("Sent to Anik."))),
    (6000, lambda: report("done")),
    (7000, lambda: bar.show("awake", line="")),
    (8500, lambda: report("awake")),
    (10000, lambda: bar.hide(0.2)),
    (12000, root.destroy),
]
for ms, fn in steps:
    root.after(ms, fn)
root.mainloop()
print("preview finished", flush=True)
