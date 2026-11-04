"""
Hologram render process.

The 3D hologram is drawn in its own Python process so it gets a full CPU core
and never fights the window / voice threads for Python's GIL (the reason a
thread-based renderer stalls near 30 FPS). Frames go back to the window through
shared memory - a triple buffer, so neither side ever waits.

    python hud_proc.py <shared-memory-name> <max-size>

Started and stopped automatically by overlay.py. When the parent quits, its
stdin pipe closes and this process exits.
"""

import math
import sys
import threading
import time

import numpy as np
from multiprocessing import shared_memory

# control block layout (int64 + float64 arrays at the start of the shared memory)
I_ACTIVE, I_LATEST, I_READING, I_FRAME, I_T, I_PX, I_STATE, I_QUIT, I_MAXPX = range(9)
F_BUILD, F_DISSOLVE, F_T0, F_MS, F_FPS = range(5)
N_INT, N_FLT = 16, 8
HEADER = N_INT * 8 + N_FLT * 8
STATES = ["listening", "thinking", "speaking", "rejected", "idle"]
MIN_PX = 480


def layout(shm, max_t):
    ints = np.ndarray((N_INT,), dtype=np.int64, buffer=shm.buf, offset=0)
    flts = np.ndarray((N_FLT,), dtype=np.float64, buffer=shm.buf, offset=N_INT * 8)
    frame = max_t * max_t * 3
    bufs = [np.ndarray((frame,), dtype=np.uint8, buffer=shm.buf, offset=HEADER + i * frame) for i in range(3)]
    return ints, flts, bufs


def total_size(max_t):
    return HEADER + 3 * max_t * max_t * 3


def _watch_parent():
    try:
        sys.stdin.read()
    except Exception:
        pass
    import os
    os._exit(0)


def no_throttle(priority: int = 0x8000):
    """Windows 11 'Efficiency mode' slows windowless background processes to a crawl.
    Opt out (full CPU speed + precise timers) and raise priority. No-op elsewhere."""
    try:
        import ctypes
        from ctypes import wintypes

        class PPT(ctypes.Structure):
            _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG),
                        ("StateMask", wintypes.ULONG)]
        k = ctypes.windll.kernel32
        h = k.GetCurrentProcess()
        st = PPT(1, 0x1 | 0x4, 0)            # EXECUTION_SPEED | IGNORE_TIMER_RESOLUTION -> off
        k.SetProcessInformation(h, 4, ctypes.byref(st), ctypes.sizeof(st))   # ProcessPowerThrottling
        k.SetPriorityClass(h, priority)      # ABOVE_NORMAL
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass


def main():
    name, max_t = sys.argv[1], int(sys.argv[2])
    no_throttle()
    threading.Thread(target=_watch_parent, daemon=True).start()
    from PIL import Image
    from hud3d import HoloRenderer

    shm = shared_memory.SharedMemory(name=name)
    ints, flts, bufs = layout(shm, max_t)
    renderer = None
    frame_ms = None
    last_adapt = 0.0
    n = 0
    try:
        while not ints[I_QUIT]:
            if not ints[I_ACTIVE] or not ints[I_T]:
                n = 0
                time.sleep(0.03)
                continue
            start = time.perf_counter()
            T = int(min(ints[I_T], max_t))
            px = int(max(MIN_PX, min(ints[I_PX] or 800, ints[I_MAXPX] or T, 1600)))
            if renderer is None or abs(renderer.size - px) >= 8:
                old = renderer
                renderer = HoloRenderer(px)
                if old is not None:   # carry the animation state over - no visual jump
                    for k in ("_acc", "_acc_hi", "_spin", "_speed", "_think", "_listen", "_talk", "_last_t"):
                        setattr(renderer, k, getattr(old, k))
            t = time.perf_counter() - flts[F_T0]
            state = STATES[int(ints[I_STATE]) % len(STATES)]
            if state == "idle":
                state = "listening"
            img = renderer.render(t, float(flts[F_BUILD]), float(flts[F_DISSOLVE]), state)
            if img.size[0] != T:
                img = img.resize((T, T), Image.BILINEAR)
            # write into the buffer the window is NOT showing / reading
            latest, reading = int(ints[I_LATEST]), int(ints[I_READING])
            w = next(i for i in range(3) if i != latest and i != reading)
            bufs[w][:T * T * 3] = np.frombuffer(img.tobytes(), dtype=np.uint8)
            ints[I_LATEST] = w
            ints[I_FRAME] += 1
            n += 1

            spent = (time.perf_counter() - start) * 1000
            frame_ms = spent if frame_ms is None else frame_ms * 0.85 + spent * 0.15
            flts[F_MS] = frame_ms
            fps = max(20.0, float(flts[F_FPS] or 50))
            budget = 1000 / fps
            now = time.perf_counter()
            if ints[I_MAXPX] and n > 10 and now - last_adapt > 1.0:   # adaptive resolution
                cap = int(min(ints[I_MAXPX], T))
                if frame_ms > budget * 0.9 and px > MIN_PX:
                    ints[I_PX] = max(MIN_PX, int(px * 0.88))
                    last_adapt = now
                elif frame_ms < budget * 0.6 and px < cap:
                    ints[I_PX] = min(cap, int(px * 1.08) + 1)
                    last_adapt = now
            time.sleep(max(0.001, (budget - spent) / 1000))
    finally:
        shm.close()


if __name__ == "__main__":
    main()
