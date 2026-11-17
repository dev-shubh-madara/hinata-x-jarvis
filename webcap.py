"""
Live website capture and replay - for sites built with JavaScript, 3D (Three.js /
WebGL), smooth scroll (Lenis, Locomotive), GSAP scroll animations and cursor effects.

A plain download only gets the HTML shell. Here Hinata opens the site in a real
browser (Microsoft Edge, hidden), scrolls it top to bottom, moves the mouse
around and hovers the buttons, and records EVERY file the page loads: code
chunks, 3D models, textures, shaders, fonts, videos. That recording is replayed
later in a real browser window with the original JavaScript running - so the
3D, smooth scroll and cursor effects work, fully offline.

The replay never reaches the internet: anything that wasn't recorded (form
posts, logins, live data) simply fails. Forms are switched off and a small
"study copy" banner is shown.

    python webcap.py capture https://example.com D:\\out\\example.com
    python webcap.py replay  D:\\out\\example.com
"""

import json
import os
import random
import sys
import threading
import time

import config

VIEW_W, VIEW_H = 1440, 900
MAX_SCREENS = 40               # stop scrolling after this many screen heights (endless feeds)
SHOT_POINTS = (0.0, 0.25, 0.5, 0.75, 1.0)

_BANNER_JS = r"""
(() => {
  const add = () => {
    if (!document.body || document.getElementById('__hx_banner')) return;
    const b = document.createElement('div');
    b.id = '__hx_banner';
    b.textContent = 'Offline study copy of ' + %HOST% + ' - recorded by Hinata X Helper. Forms are switched off.';
    b.style.cssText = 'position:fixed;z-index:2147483647;left:0;right:0;bottom:0;background:#150d2e;color:#e9e2ff;' +
      'font:12px Segoe UI,sans-serif;padding:5px 12px;text-align:center;opacity:.9;pointer-events:none';
    document.body.appendChild(b);
  };
  document.addEventListener('submit', e => { e.preventDefault(); e.stopPropagation(); }, true);
  document.addEventListener('DOMContentLoaded', add);
  setInterval(add, 2000);
})();
"""


def _launch(pw, headless: bool, extra_args=()):
    """Edge first (always on Windows 11), then Chrome, then Playwright's own Chromium."""
    want = (getattr(config, "BROWSER_CHANNEL", "msedge") or "").strip()
    order = [c for c in (want, "msedge", "chrome") if c] + [None]
    last = None
    for ch in dict.fromkeys(order):
        try:
            kw = {"headless": headless, "args": ["--autoplay-policy=no-user-gesture-required", *extra_args]}
            if ch:
                kw["channel"] = ch
            return pw.chromium.launch(**kw)
        except Exception as e:
            last = e
    raise RuntimeError(f"no browser could be started: {last}")


def _har(folder: str) -> str:
    return os.path.join(folder, "recording.zip")


# ---------------------------------------------------------------- capture

def _settle(page, ms=6000):
    try:
        page.wait_for_load_state("networkidle", timeout=ms)
    except Exception:
        pass


def _doc_height(page) -> int:
    try:
        return int(page.evaluate("Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0)"))
    except Exception:
        return VIEW_H


def _wiggle(page, n=6):
    """Moves the mouse like a person - wakes up cursor followers and hover effects."""
    for _ in range(n):
        page.mouse.move(random.randint(80, VIEW_W - 80), random.randint(80, VIEW_H - 80), steps=8)
        page.wait_for_timeout(60)


def _scroll_to(page, frac: float):
    page.evaluate("""f => {
        const h = Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0);
        const y = Math.max(0, (h - innerHeight) * f);
        if (window.lenis && window.lenis.scrollTo) { try { window.lenis.scrollTo(y, {immediate: true}); } catch (e) {} }
        window.scrollTo(0, y);
    }""", frac)


def _shots(page, folder: str, prefix: str) -> list[str]:
    paths = []
    for i, f in enumerate(SHOT_POINTS):
        try:
            _scroll_to(page, f)
            page.wait_for_timeout(900)
            p = os.path.join(folder, f"{prefix}_{i}.png")
            page.screenshot(path=p)
            paths.append(p)
        except Exception as e:
            print(f"[webcap] screenshot {prefix} {i} failed: {e}")
    return paths


def capture(url: str, folder: str, status=print) -> dict:
    """Records the site into folder/recording.zip. Returns facts about the capture."""
    from playwright.sync_api import sync_playwright
    os.makedirs(folder, exist_ok=True)
    har = _har(folder)
    t0 = time.time()
    counts = {"requests": 0, "bytes": 0, "types": {}}

    def on_response(resp):
        try:
            counts["requests"] += 1
            kind = resp.request.resource_type
            counts["types"][kind] = counts["types"].get(kind, 0) + 1
            n = resp.headers.get("content-length")
            if n and n.isdigit():
                counts["bytes"] += int(n)
        except Exception:
            pass

    with sync_playwright() as pw:
        browser = _launch(pw, headless=True)
        ctx = browser.new_context(viewport={"width": VIEW_W, "height": VIEW_H}, record_har_path=har,
                                  record_har_content="attach", record_har_mode="full", service_workers="block",
                                  locale="en-US")
        page = ctx.new_page()
        page.on("response", on_response)
        status("Opening the site")
        page.goto(url, wait_until="load", timeout=60000)
        _settle(page)
        page.wait_for_timeout(1500)
        _wiggle(page)

        status("Scrolling through every section")
        y, screens = 0, 0
        while screens < MAX_SCREENS:
            page.mouse.wheel(0, VIEW_H * 0.6)
            page.wait_for_timeout(280)
            if screens % 2 == 0:
                _wiggle(page, 2)
            y += VIEW_H * 0.6
            screens += 0.6
            if y + VIEW_H >= _doc_height(page) + 50:
                page.wait_for_timeout(1200)                 # lazy content may grow the page
                if y + VIEW_H >= _doc_height(page) + 50:
                    break
        _settle(page, 4000)

        status("Hovering buttons and links")
        try:
            handles = page.query_selector_all("a, button, [role=button], [class*=card], [class*=btn]")[:40]
            for h in handles:
                try:
                    if h.is_visible():
                        h.hover(timeout=600)
                        page.wait_for_timeout(40)
                except Exception:
                    continue
        except Exception:
            pass
        _scroll_to(page, 0)
        page.wait_for_timeout(1000)
        _settle(page, 3000)

        status("Taking reference screenshots")
        live = _shots(page, folder, "live")
        title = page.title()
        final_url = page.url
        ctx.close()                        # writes the recording
        browser.close()

    meta = {"url": final_url, "start": url, "title": title, "captured": time.strftime("%Y-%m-%d %H:%M"),
            "requests": counts["requests"], "types": counts["types"], "seconds": round(time.time() - t0, 1),
            "mb": round(os.path.getsize(har) / 1048576, 1) if os.path.exists(har) else 0}
    with open(os.path.join(folder, "capture.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    meta["live_shots"] = live
    return meta


# ---------------------------------------------------------------- replay

def _replay_context(pw, folder: str, headless: bool):
    meta = _meta(folder)
    host = (meta.get("url") or "").split("//")[-1].split("/")[0]
    browser = _launch(pw, headless=headless, extra_args=() if headless else ("--start-maximized",))
    kw = {"service_workers": "block"}
    if headless:
        kw["viewport"] = {"width": VIEW_W, "height": VIEW_H}
    else:
        kw["no_viewport"] = True
    ctx = browser.new_context(**kw)
    ctx.route_from_har(_har(folder), not_found="abort")
    ctx.add_init_script(_BANNER_JS.replace("%HOST%", json.dumps(host)))
    return browser, ctx, meta


def _meta(folder: str) -> dict:
    try:
        with open(os.path.join(folder, "capture.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def check(folder: str) -> dict:
    """Replays the recording headless and compares it with the live screenshots."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, ctx, meta = _replay_context(pw, folder, headless=True)
        page = ctx.new_page()
        failed = []
        page.on("requestfailed", lambda r: failed.append(r.url))
        page.goto(meta.get("url") or meta.get("start"), wait_until="load", timeout=60000)
        _settle(page, 4000)
        page.wait_for_timeout(1500)
        page.evaluate("document.getElementById('__hx_banner') && document.getElementById('__hx_banner').remove()")
        page.add_style_tag(content="#__hx_banner{display:none!important}")
        copy = _shots(page, folder, "copy")
        browser.close()
    live = [os.path.join(folder, f"live_{i}.png") for i in range(len(SHOT_POINTS))]
    scores = [similarity(a, b) for a, b in zip(live, copy) if os.path.exists(a) and os.path.exists(b)]
    score = round(sum(scores) / len(scores)) if scores else 0
    res = {"score": score, "scores": scores, "missing": len(failed), "missing_examples": failed[:8]}
    meta.update(check=res)
    with open(os.path.join(folder, "capture.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    return res


def similarity(a: str, b: str) -> int:
    """0-100: how alike two screenshots look (small, blurred, greyscale compare)."""
    from PIL import Image, ImageChops, ImageFilter
    try:
        ia = Image.open(a).convert("L").resize((240, 150)).filter(ImageFilter.GaussianBlur(1.5))
        ib = Image.open(b).convert("L").resize((240, 150)).filter(ImageFilter.GaussianBlur(1.5))
    except Exception:
        return 0
    diff = ImageChops.difference(ia, ib)
    hist = diff.histogram()
    close = sum(hist[:26])                            # pixels within ~10% brightness
    return round(100 * close / (240 * 150))


_open = {"threads": []}


def open_copy(folder: str, wait: bool = False) -> str:
    """Opens the recorded site in a real browser window (runs until you close it)."""
    if not os.path.exists(_har(folder)):
        return "There's no recording in that folder yet."

    def run():
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as pw:
                browser, ctx, meta = _replay_context(pw, folder, headless=False)
                page = ctx.new_page()
                page.goto(meta.get("url") or meta.get("start"), wait_until="load", timeout=60000)
                while not page.is_closed() and browser.is_connected():
                    try:
                        page.wait_for_timeout(1000)
                    except Exception:
                        break
                try:
                    browser.close()
                except Exception:
                    pass
        except Exception as e:
            print(f"[webcap] replay failed: {e}")

    if wait:
        run()
    else:
        t = threading.Thread(target=run, daemon=True, name="webcap-replay")
        t.start()
        _open["threads"].append(t)
    return "Opened the offline copy."


def write_launcher(folder: str):
    """open copy.bat - double-click it later to open the recording again."""
    if os.name != "nt":
        return
    here = os.path.abspath(__file__)
    bat = os.path.join(folder, "open copy.bat")
    with open(bat, "w", encoding="utf-8") as f:
        f.write(f'@echo off\r\n"{sys.executable}" "{here}" replay "{folder}"\r\n')


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "capture":
        m = capture(sys.argv[2], sys.argv[3])
        print(json.dumps({k: v for k, v in m.items() if k != "live_shots"}, indent=1))
        print(check(sys.argv[3]))
    elif len(sys.argv) >= 3 and sys.argv[1] == "replay":
        open_copy(sys.argv[2], wait=True)
    else:
        print(__doc__)
