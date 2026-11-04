"""
hud3d.py - the real-time 3D hologram for Hinata X Helper.

Everything is generated live, every frame, from real 3D geometry (no video):

  * a holographic globe of particles rotating in 3D with depth shading
  * three tilted orbit rings that spin and precess, with travelling light nodes
  * a HUD plane (tick ring, segmented arcs, radar sweep, voice bars) that
    unfolds from edge-on during the intro
  * a glowing core that ignites, pulses and collapses
  * a two-level bloom pass so everything glows like a hologram

Colours follow the Hinata theme: lavender while listening, rose-magenta while
thinking, moonlight blue while speaking.

Phases:
  build    0 -> 1   intro: particles fly in, rings unfold, core ignites
  loop               spins while Hinata listens / thinks / speaks
  dissolve 0 -> 1   outro: rings collapse, particles burst, core flashes out

Needs only NumPy + Pillow. Detail scales with the render size, so the
overlay can raise the resolution on fast PCs and lower it on slow ones.
"""

import math
import time

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

# accent colour per state: (main, bright)
PALETTES = {
    "idle":      ((170, 140, 255), (236, 228, 255)),
    "listening": ((160, 125, 255), (238, 230, 255)),
    "thinking":  ((255, 92, 190), (255, 214, 240)),
    "speaking":  ((110, 185, 255), (225, 240, 255)),
    "rejected":  ((255, 70, 90), (255, 200, 210)),
}
# base hologram colours (globe, core) - lavender
CYAN = np.array((175, 150, 255), dtype=float)
CYAN_HI = np.array((245, 240, 255), dtype=float)
CYAN_DIM = np.array((45, 25, 95), dtype=float)

CAM_DIST = 3.2


# ---------------------------------------------------------------- helpers

def _clamp01(x):
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def _sub(x, lo, hi):
    return _clamp01((x - lo) / (hi - lo))


def _ease_out(x):
    x = _clamp01(x)
    return 1 - (1 - x) ** 3


def _ease_in(x):
    x = _clamp01(x)
    return x * x * x


def _smooth(x):
    x = _clamp01(x)
    return x * x * (3 - 2 * x)


def _rx(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _ry(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rz(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _col(rgb, k):
    """Colour scaled by brightness k (0..1+) - on a black background this
    behaves like transparency."""
    return (int(min(255, rgb[0] * k)), int(min(255, rgb[1] * k)), int(min(255, rgb[2] * k)))


def _cols(rgb, k):
    """Vectorised _col: rgb (N,3) or (3,), k (N,) -> list of int tuples."""
    a = np.clip(np.asarray(rgb, dtype=float) * np.asarray(k, dtype=float)[:, None], 0, 255).astype(int)
    return [tuple(c) for c in a.tolist()]


def _circle(n, r=1.0, a0=0.0, a1=2 * math.pi):
    a = np.linspace(a0, a1, n)
    return np.stack([np.cos(a) * r, np.sin(a) * r, np.zeros(n)], axis=1)


# ---------------------------------------------------------------- renderer

class HoloRenderer:
    def __init__(self, size: int, mini: bool = False, seed: int = 7):
        self.size = int(size)
        self.mini = mini
        self.cx = self.cy = self.size / 2
        self.S = self.size * 0.5 * 0.90          # 1 world unit -> pixels
        self.px = max(1.0, self.size / 800)       # line-width unit
        rnd = np.random.default_rng(seed)

        detail = min(1.6, max(0.7, self.size / 900))   # more particles at high resolution
        # globe of particles (Fibonacci sphere)
        n = 70 if mini else int(460 * detail)
        i = np.arange(n) + 0.5
        phi = np.arccos(1 - 2 * i / n)
        theta = math.pi * (1 + 5 ** 0.5) * i
        self.globe_r = 0.30 if mini else 0.33
        self.globe = np.stack([np.cos(theta) * np.sin(phi),
                               np.cos(phi),
                               np.sin(theta) * np.sin(phi)], axis=1) * self.globe_r
        d = rnd.normal(size=(n, 3))
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        self.globe_start = d * rnd.uniform(1.4, 2.8, size=(n, 1))
        self.globe_delay = rnd.uniform(0, 0.32, size=n)
        v = rnd.normal(size=(n, 3))
        self.globe_vel = (v / np.linalg.norm(v, axis=1, keepdims=True)) * rnd.uniform(0.6, 1.8, size=(n, 1))

        # free-floating dust on random 3D orbits
        m = 0 if mini else int(90 * detail)
        self.dust_r = rnd.uniform(0.55, 0.98, size=m)
        self.dust_a = rnd.uniform(0, 2 * math.pi, size=m)
        self.dust_spd = rnd.uniform(0.15, 0.5, size=m) * rnd.choice([-1, 1], size=m)
        self.dust_tilt = rnd.uniform(-1.2, 1.2, size=(m, 2))

        # orbit rings: radius, tilt-x, phase, spin speed, precession speed, dashed
        if mini:
            self.rings = [(0.62, 1.15, 0.0, 1.0, 0.25, False),
                          (0.70, -1.0, 1.7, -0.7, -0.2, False)]
        else:
            self.rings = [(0.53, 1.05, 0.0, 0.9, 0.18, False),
                          (0.61, -0.92, 2.1, -0.6, -0.13, True),
                          (0.47, 1.32, 4.0, 1.3, 0.27, False)]
        self.ring_pts = 72 if mini else 150

        # HUD segmented arcs: (start deg, length deg, radius, width, speed)
        self.arcs = [(0, 70, 0.71, 3, -0.35), (95, 40, 0.71, 3, -0.35),
                     (160, 110, 0.71, 3, -0.35), (290, 50, 0.71, 3, -0.35),
                     (20, 140, 0.93, 2, 0.22), (200, 90, 0.93, 2, 0.22),
                     (300, 30, 0.93, 2, 0.22)]

        # smoothly blended state values
        self._acc = np.array(PALETTES["listening"][0], dtype=float)
        self._acc_hi = np.array(PALETTES["listening"][1], dtype=float)
        self._spin = 0.0
        self._speed = 1.0
        self._think = 0.0
        self._listen = 0.0
        self._talk = 0.0
        self._last_t = None

    # ------------------------------------------------------------ projection

    def _proj(self, P):
        k = CAM_DIST / np.maximum(CAM_DIST + P[:, 2], 0.4)
        return self.cx + P[:, 0] * k * self.S, self.cy - P[:, 1] * k * self.S, k

    # ------------------------------------------------------------ main entry

    def render(self, t: float, build: float = 1.0, dissolve: float = 0.0,
               state: str = "listening", level: float | None = None) -> Image.Image:
        dt = 0.033 if self._last_t is None else max(0.0, min(0.1, t - self._last_t))
        self._last_t = t
        self._blend_state(state, dt)

        W = self.size
        img = Image.new("RGB", (W, W))
        dh = db = ImageDraw.Draw(img)

        if level is None:   # synthetic voice level
            level = 0.55 + 0.45 * math.sin(t * 9.1) * math.sin(t * 3.7 + 1.0)
            level = abs(level) * (0.25 + 0.75 * self._listen) + 0.5 * self._talk * abs(math.sin(t * 11))

        # global wobble so the whole hologram feels like it floats in 3D
        wob = _rx(0.16 * math.sin(t * 0.37)) @ _ry(0.20 * math.sin(t * 0.29 + 0.6))

        if not self.mini:
            self._draw_hud(dh, t, build, dissolve, level, wob)
            self._draw_dust(db, t, build, dissolve, wob)
        self._draw_rings(dh, t, build, dissolve, wob)
        self._draw_globe(db, t, build, dissolve, level, wob)
        self._draw_core(db, t, build, dissolve, level)

        return self._bloom(img)

    # ------------------------------------------------------------ state blend

    def _blend_state(self, state, dt):
        main, hi = PALETTES.get(state, PALETTES["listening"])
        k = 1 - math.exp(-dt * 5)
        self._acc += (np.array(main) - self._acc) * k
        self._acc_hi += (np.array(hi) - self._acc_hi) * k
        target_speed = {"thinking": 2.6, "listening": 1.3, "speaking": 1.1}.get(state, 0.8)
        self._speed += (target_speed - self._speed) * k
        self._spin += dt * self._speed
        self._think += ((state == "thinking") - self._think) * k
        self._listen += ((state == "listening") - self._listen) * k
        self._talk += ((state == "speaking") - self._talk) * k

    # ------------------------------------------------------------ HUD plane

    def _hud_matrix(self, t, build, dissolve, wob):
        # intro: plane swings up from edge-on; outro: tips back over
        unfold = _ease_out(_sub(build, 0.30, 0.85))
        tip = _ease_in(_sub(dissolve, 0.0, 0.6))
        ang = (1 - unfold) * 1.45 + tip * 1.3
        return wob @ _rx(ang)

    def _poly(self, d, P, M, color, width, closed=False):
        Q = P @ M.T
        x, y, _ = self._proj(Q)
        pts = list(zip(x.tolist(), y.tolist()))
        if closed:
            pts.append(pts[0])
        if len(pts) > 1:
            d.line(pts, fill=color, width=max(1, int(round(width))))

    def _depth_poly(self, d, Q, rgb, alpha, k0, k1, r, chunk=6, width=None):
        """Polyline whose brightness follows depth, drawn in short chunks."""
        xs, ys, _ = self._proj(Q)
        zs = Q[:, 2]
        n = len(xs)
        w = max(1, int(width or self.px))
        for j in range(0, n - 1, chunk):
            e = min(n, j + chunk + 1)
            nz = 0.5 - zs[(j + e) // 2] / (2 * r)
            d.line(list(zip(xs[j:e].tolist(), ys[j:e].tolist())), fill=_col(rgb, alpha * (k0 + k1 * nz)), width=w)

    def _draw_hud(self, d, t, build, dissolve, level, wob):
        M = self._hud_matrix(t, build, dissolve, wob)
        vis = _ease_out(_sub(build, 0.30, 0.8)) * (1 - _ease_in(_sub(dissolve, 0.0, 0.55)))
        if vis <= 0.01:
            return
        acc, hi = self._acc, self._acc_hi
        grow = 0.75 + 0.25 * _ease_out(_sub(build, 0.3, 0.9)) + 0.25 * _ease_in(_sub(dissolve, 0, 0.6))
        px = self.px

        # thin guide circles
        for r, k in ((0.665, 0.35), (0.86, 0.30), (0.985, 0.18)):
            self._poly(d, _circle(160, r * grow), M, _col(acc, k * vis), px)

        # tick ring - draws itself around during the intro
        n = 120
        shown = int(n * _smooth(_sub(build, 0.42, 1.0)))
        if shown:
            a = np.linspace(0, 2 * math.pi, n, endpoint=False)[:shown] - self._spin * 0.12 + math.pi / 2
            long = (np.arange(shown) % 10 == 0)
            r0 = np.full(shown, 0.79) * grow
            r1 = np.where(long, 0.845, 0.815) * grow
            P0 = np.stack([np.cos(a) * r0, np.sin(a) * r0, np.zeros(shown)], 1) @ M.T
            P1 = np.stack([np.cos(a) * r1, np.sin(a) * r1, np.zeros(shown)], 1) @ M.T
            x0, y0, _ = self._proj(P0)
            x1, y1, _ = self._proj(P1)
            c_long, c_short = _col(hi, 0.9 * vis), _col(acc, 0.5 * vis)
            w_long, w_short = max(1, int(px * 2)), max(1, int(px))
            x0, y0, x1, y1 = x0.tolist(), y0.tolist(), x1.tolist(), y1.tolist()
            for j in range(shown):
                lg = long[j]
                d.line((x0[j], y0[j], x1[j], y1[j]), fill=c_long if lg else c_short, width=w_long if lg else w_short)

        # rotating segmented arcs
        for start, length, r, w, spd in self.arcs:
            a0 = math.radians(start) + self._spin * spd
            frac = _ease_out(_sub(build, 0.45, 0.95))
            a1 = a0 + math.radians(length) * frac
            if a1 - a0 > 0.01:
                self._poly(d, _circle(24, r * grow, a0, a1), M, _col(acc, 0.85 * vis), w * px)

        # "processing" chase arcs while thinking
        if self._think > 0.02:
            for k in range(3):
                a0 = self._spin * (2.2 + k * 0.5) + k * 2.1
                self._poly(d, _circle(30, 0.89 * grow, a0, a0 + 1.1),
                           M, _col(hi, self._think * vis * (0.9 - k * 0.2)), (4 - k) * px)

        # voice bars ring
        nb = 96
        a = np.linspace(0, 2 * math.pi, nb, endpoint=False) + self._spin * 0.05
        idx = np.arange(nb)
        wave = np.abs(np.sin(idx * 0.61 + t * 6.3) * np.sin(idx * 0.23 - t * 2.7)) * 0.8 \
            + 0.2 * np.abs(np.sin(idx * 1.7 + t * 13))
        length = (0.012 + 0.085 * level * wave) * _ease_out(_sub(build, 0.5, 1.0))
        r0 = 0.585 * grow
        P0 = np.stack([np.cos(a) * r0, np.sin(a) * r0, np.zeros(nb)], 1) @ M.T
        P1 = np.stack([np.cos(a) * (r0 + length), np.sin(a) * (r0 + length), np.zeros(nb)], 1) @ M.T
        x0, y0, _ = self._proj(P0)
        x1, y1, _ = self._proj(P1)
        cols = _cols(np.tile(acc, (nb, 1)), (0.45 + 0.6 * wave * level) * vis)
        wb = max(1, int(px * 2))
        x0, y0, x1, y1 = x0.tolist(), y0.tolist(), x1.tolist(), y1.tolist()
        for j in range(nb):
            d.line((x0[j], y0[j], x1[j], y1[j]), fill=cols[j], width=wb)

        # radar sweep with fading trail
        sweep = t * 1.6
        for k in range(14):
            ang = sweep - k * 0.045
            P = np.array([[math.cos(ang) * 0.2, math.sin(ang) * 0.2, 0],
                          [math.cos(ang) * 0.78 * grow, math.sin(ang) * 0.78 * grow, 0]])
            self._poly(d, P, M, _col(acc, (0.55 - k * 0.038) * vis * (0.4 + 0.6 * self._listen)), px * 1.5)

    # ------------------------------------------------------------ orbit rings

    def _draw_rings(self, d, t, build, dissolve, wob):
        acc, hi = self._acc, self._acc_hi
        n = self.ring_pts
        for i, (r, tilt, ph, spd, prec, dashed) in enumerate(self.rings):
            lo = 0.18 + 0.08 * i
            g = _ease_out(_sub(build, lo, lo + 0.45))
            out = _ease_in(_sub(dissolve, 0.0, 0.5 + 0.1 * i))
            if g <= 0.01 or out >= 0.99:
                continue
            scale = g * (1 + 0.7 * out)
            alpha = g * (1 - out)
            spin = self._spin * spd + ph
            M = wob @ _ry(t * prec + ph) @ _rx(tilt) @ _rz(spin)
            arc = 2 * math.pi * _smooth(_sub(build, lo, lo + 0.5))
            P = _circle(n, r * scale, 0, arc) @ M.T
            x, y, k = self._proj(P)
            z = P[:, 2]
            depth = np.clip(0.5 - z / (2 * r + 1e-6), 0, 1)       # 1 = nearest
            step = 4 if dashed else 5
            xl, yl, dl = x.tolist(), y.tolist(), depth.tolist()
            for j in range(0, n - 1, step):
                if dashed and (j // 4) % 2:
                    continue
                e = min(n, j + step + (0 if dashed else 1))
                dj = dl[(j + e) // 2 if (j + e) // 2 < n else j]
                c = _col(acc * (0.35 + 0.9 * dj), alpha)
                d.line(list(zip(xl[j:e], yl[j:e])), fill=c, width=max(1, int(self.px * (1 + 2.2 * dj))))
            # travelling light nodes
            for nk in range(2):
                a = spin * 1.8 + nk * math.pi
                if a % (2 * math.pi) > arc:
                    continue
                Q = (np.array([[math.cos(a) * r * scale, math.sin(a) * r * scale, 0]]) @ M.T)
                qx, qy, qk = self._proj(Q)
                rad = self.px * (3 + 3 * qk[0]) * (0.6 if self.mini else 1)
                d.ellipse((qx[0] - rad, qy[0] - rad, qx[0] + rad, qy[0] + rad), fill=_col(hi, alpha))

    # ------------------------------------------------------------ dust

    def _draw_dust(self, d, t, build, dissolve, wob):
        if not len(self.dust_r):
            return
        vis = _ease_out(_sub(build, 0.4, 1.0)) * (1 - _ease_in(_sub(dissolve, 0, 0.5)))
        if vis <= 0.01:
            return
        a = self.dust_a + t * self.dust_spd
        P = np.stack([np.cos(a) * self.dust_r, np.sin(a) * self.dust_r, np.zeros_like(a)], 1)
        # each mote has its own tilted orbit
        tx, ty = self.dust_tilt[:, 0], self.dust_tilt[:, 1]
        y1 = P[:, 1] * np.cos(tx)
        z1 = P[:, 1] * np.sin(tx)
        x2 = P[:, 0] * np.cos(ty) + z1 * np.sin(ty)
        z2 = -P[:, 0] * np.sin(ty) + z1 * np.cos(ty)
        Q = np.stack([x2, y1, z2], 1) @ wob.T
        x, y, k = self._proj(Q)
        cols = _cols(np.tile(self._acc, (len(x), 1)), 0.55 * vis * k)
        rad = self.px * 1.2 * k
        x0, y0, x1, y1 = (x - rad).tolist(), (y - rad).tolist(), (x + rad).tolist(), (y + rad).tolist()
        for j in range(len(cols)):
            d.ellipse((x0[j], y0[j], x1[j], y1[j]), fill=cols[j])

    # ------------------------------------------------------------ globe

    def _draw_globe(self, d, t, build, dissolve, level, wob):
        R = wob @ _ry(self._spin * 0.55) @ _rx(0.42)
        pulse = 1 + 0.06 * self._talk * level + 0.02 * math.sin(t * 2.2)

        # particles: fly in, then burst on the way out
        local = np.clip((build - 0.04 - self.globe_delay) / 0.55, 0, 1)
        local = 1 - (1 - local) ** 3
        swirl = (1 - local) * 2.4
        cs, sn = np.cos(swirl), np.sin(swirl)
        S0 = self.globe_start
        start = np.stack([S0[:, 0] * cs + S0[:, 2] * sn, S0[:, 1], -S0[:, 0] * sn + S0[:, 2] * cs], 1)
        P = start * (1 - local)[:, None] + self.globe * pulse * local[:, None]
        alpha = np.clip(local * 1.6, 0, 1)
        if dissolve > 0:
            dd = np.clip((dissolve - self.globe_delay * 0.6) / 0.6, 0, 1)
            P = P + self.globe_vel * (dd ** 2 * 2.2)[:, None]
            alpha = alpha * (1 - dd)

        Q = P @ R.T
        order = np.argsort(-Q[:, 2])          # far first
        x, y, k = self._proj(Q)
        z = Q[:, 2]
        near = np.clip(0.5 - z / (2 * self.globe_r * 1.2), 0, 1)
        base = CYAN * 0.6 + self._acc * 0.4
        sz = self.px * (0.6 if self.mini else 1.0)
        nj = near[:, None]
        rgb = CYAN_DIM * (1 - nj) + base * nj + CYAN_HI * (nj ** 4) * 0.5
        cols = _cols(rgb, alpha * (0.22 + 0.72 * near))
        rad = sz * (0.6 + 1.7 * near) * k
        x0, y0, x1, y1 = (x - rad).tolist(), (y - rad).tolist(), (x + rad).tolist(), (y + rad).tolist()
        al = alpha.tolist()
        for j in order.tolist():
            if al[j] > 0.02:
                d.ellipse((x0[j], y0[j], x1[j], y1[j]), fill=cols[j])

        # faint wire latitudes on the globe once it has formed
        wire = _ease_out(_sub(build, 0.5, 0.95)) * (1 - _ease_in(_sub(dissolve, 0, 0.4)))
        if wire > 0.02 and not self.mini:
            gr = self.globe_r * pulse
            for lat in (-0.55, 0.0, 0.55):
                rr = gr * math.cos(lat)
                C = _circle(60, rr) @ _rx(math.pi / 2).T
                C[:, 1] += gr * math.sin(lat)
                Q = C @ R.T
                self._depth_poly(d, Q, base, wire, 0.12, 0.35, gr)
            for lon in range(0, 180, 45):
                C = _circle(60, gr) @ _ry(math.radians(lon)).T
                Q = C @ R.T
                self._depth_poly(d, Q, base, wire, 0.08, 0.30, gr)

    # ------------------------------------------------------------ core

    def _draw_core(self, d, t, build, dissolve, level):
        ign = _sub(build, 0.0, 0.32)
        grow = _ease_out(ign)
        # little overshoot "ignition" pop
        pop = math.sin(math.pi * _sub(build, 0.18, 0.42)) * 0.35
        shrink = 1 - _ease_in(_sub(dissolve, 0.55, 1.0))
        scale = (grow + pop) * shrink
        if scale <= 0.01:
            return
        pulse = 1 + 0.10 * self._talk * level + 0.04 * math.sin(t * 3.1)
        rc = self.S * (0.11 if self.mini else 0.075) * scale * pulse
        cx, cy = self.cx, self.cy
        acc, hi = self._acc, self._acc_hi
        base = CYAN * 0.55 + acc * 0.45

        # soft halo -> hot white centre
        steps = 9
        for s in range(steps, 0, -1):
            f = s / steps
            r = rc * (0.25 + 1.6 * f)
            c = _col(base * (1 - f) * 1.4 + CYAN_HI * (1 - f) ** 3, 0.25 + 0.75 * (1 - f))
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=c)
        r = rc * 0.32
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(250, 246, 255))

        # arc-reactor segments around the core
        if not self.mini:
            nseg = 10
            r0, r1 = rc * 1.75, rc * 2.25
            rot = -self._spin * 0.9
            for s in range(nseg):
                a0 = rot + s * 2 * math.pi / nseg
                a1 = a0 + 2 * math.pi / nseg * 0.62
                pts = [(cx + math.cos(a0) * r0, cy + math.sin(a0) * r0),
                       (cx + math.cos(a0) * r1, cy + math.sin(a0) * r1),
                       (cx + math.cos(a1) * r1, cy + math.sin(a1) * r1),
                       (cx + math.cos(a1) * r0, cy + math.sin(a1) * r0)]
                d.polygon(pts, fill=_col(base, 0.55), outline=_col(hi, 0.8))
            r2 = rc * 2.55
            d.ellipse((cx - r2, cy - r2, cx + r2, cy + r2), outline=_col(acc, 0.6), width=max(1, int(self.px * 2)))

        # flash at ignition and at the very end of the dissolve
        flash = max(math.sin(math.pi * _sub(build, 0.12, 0.38)) * 0.9,
                    math.sin(math.pi * _sub(dissolve, 0.6, 0.95)) * 1.0)
        if flash > 0.02:
            rf = self.S * 0.22 * flash
            d.ellipse((cx - rf, cy - rf, cx + rf, cy + rf), fill=_col(CYAN_HI, flash))
            # horizontal lens streak
            hw = self.S * 0.9 * flash
            hh = max(1, self.px * 2.5 * flash)
            d.ellipse((cx - hw, cy - hh, cx + hw, cy + hh), fill=_col(CYAN_HI, 0.8 * flash))

    # ------------------------------------------------------------ glow

    def _bloom(self, img):
        W = self.size
        if self.mini:
            g = img.filter(ImageFilter.GaussianBlur(W / 18))
            out = ImageChops.add(img, g)
            return ImageChops.add(out, g)
        # glow is built at quarter resolution (cheap), then added once
        small = img.reduce(5)
        sw = small.size[0]
        g1 = small.filter(ImageFilter.BoxBlur(max(1, sw / 90)))      # tight glow
        g2 = small.filter(ImageFilter.GaussianBlur(sw / 22))          # wide halo
        g = ImageChops.add(g1, g2, scale=0.5)                          # (g1 + g2) * 2 in one pass
        return ImageChops.add(img, g.resize((W, W), Image.BILINEAR, reducing_gap=None))


JarvisRenderer = HoloRenderer   # backwards-compatible name


if __name__ == "__main__":
    # quick benchmark: python hud3d.py
    r = HoloRenderer(800)
    t0 = time.perf_counter()
    for i in range(30):
        r.render(i / 30, build=min(1, i / 20))
    print(f"{(time.perf_counter() - t0) / 30 * 1000:.1f} ms per frame at 800px")
