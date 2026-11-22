"""Shows the caption bar going through its states for ~12 seconds (to see how it looks)."""
import tkinter as tk

import caption_bar

root = tk.Tk()
root.withdraw()
bar = caption_bar.CaptionBar(root)
steps = [
    (0, lambda: bar.show("listening", line="")),
    (1500, lambda: bar.show("thinking", line="open whatsapp and send hi to Anik")),
    (4500, lambda: (bar.set_state("speaking"), bar.set_line("Sent to Anik."))),
    (7000, lambda: bar.show("awake", line="")),
    (10000, lambda: bar.hide(0.2)),
    (12000, root.destroy),
]
for ms, fn in steps:
    root.after(ms, fn)
root.mainloop()
