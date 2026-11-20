"""
Browser control: Hinata drives a real Chrome window for you.

    "open github and go to my repositories"
    "search YouTube for lofi and play the first one"
    "read this page"  /  "click Sign in"  /  "type hello in the search box"

She uses her own Chrome profile (%LOCALAPPDATA%\\HinataXHelper\\browser), so
the first time you sign in to sites there yourself and she stays signed in
after that. (Chrome doesn't let any program take over your main profile,
for your safety.) Set BROWSER_AGENT_CHANNEL = "msedge" in config.py for Edge.

Safety, enforced here:
  * she never types into password, card, CVV or OTP boxes - you do that
  * buttons that pay, buy, delete, send or post need your spoken "confirm"
"""

import queue
import re
import threading

import config
from pc_actions import Confirm

PROFILE = None
RISKY_BUTTON = re.compile(r"\b(pay|buy|purchase|place order|checkout|delete|remove|send|post|publish|submit|"
                          r"transfer|confirm order|subscribe|unsubscribe)\b", re.I)
SECRET_FIELD = re.compile(r"pass(word|code)?|pwd|otp|one.?time|cvv|cvc|card.?number|cc-|security code|pin\b", re.I)


class _Worker:
    """Playwright's sync API must stay on one thread, so every browser job runs here."""

    def __init__(self):
        self.q: queue.Queue = queue.Queue()
        self.t = None
        self.ctx = None
        self.page = None

    def call(self, fn, timeout=60):
        if self.t is None:
            self.t = threading.Thread(target=self._loop, daemon=True, name="browser")
            self.t.start()
        box = {}
        done = threading.Event()
        self.q.put((fn, box, done))
        if not done.wait(timeout):
            return "The browser is taking too long."
        if "err" in box:
            raise box["err"]
        return box.get("ok")

    def _loop(self):
        while True:
            fn, box, done = self.q.get()
            try:
                box["ok"] = fn(self)
            except Exception as e:
                box["err"] = e
            done.set()

    def ensure(self):
        if self.ctx is not None:
            try:
                if self.page and not self.page.is_closed():
                    return self.page
                pages = [p for p in self.ctx.pages if not p.is_closed()]
                self.page = pages[-1] if pages else self.ctx.new_page()
                return self.page
            except Exception:
                self.ctx = None                      # the window was closed - start again
        import os
        from playwright.sync_api import sync_playwright
        global PROFILE
        PROFILE = os.path.join(config.DATA_DIR, "browser")
        self.pw = getattr(self, "pw", None) or sync_playwright().start()
        self.ctx = self.pw.chromium.launch_persistent_context(
            PROFILE, channel=getattr(config, "BROWSER_AGENT_CHANNEL", "chrome") or None,
            headless=bool(getattr(config, "BROWSER_HEADLESS", False)),
            no_viewport=True, args=["--start-maximized", "--disable-blink-features=AutomationControlled"])
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        return self.page


_w = _Worker()


def _url(target: str) -> str:
    t = target.strip()
    if re.match(r"^https?://", t):
        return t
    sites = {k.lower(): v for k, v in getattr(config, "KNOWN_SITES", {}).items()}
    if t.lower() in sites:
        return sites[t.lower()]
    if re.fullmatch(r"[\w-]+(\.[\w-]+)+(/\S*)?", t):
        return "https://" + t
    from urllib.parse import quote_plus
    return "https://www.google.com/search?q=" + quote_plus(t)


def open_page(target: str) -> str:
    def job(w):
        page = w.ensure()
        page.goto(_url(target), wait_until="domcontentloaded", timeout=30000)
        page.bring_to_front()
        return f"Opened {page.title() or page.url}."
    return _w.call(job)


def youtube(query: str) -> str:
    from urllib.parse import quote_plus

    def job(w):
        page = w.ensure()
        page.goto("https://www.youtube.com/results?search_query=" + quote_plus(query), wait_until="domcontentloaded")
        first = page.locator("a#video-title").first
        first.wait_for(timeout=15000)
        title = first.get_attribute("title") or "the first video"
        first.click()
        page.bring_to_front()
        return f"Playing {title}."
    return _w.call(job)


def read() -> str:
    def job(w):
        page = w.ensure()
        text = page.evaluate("""() => {
            const pick = document.querySelector('main, article, [role=main]') || document.body;
            return pick.innerText;
        }""") or ""
        text = re.sub(r"\n\s*\n+", "\n", text).strip()
        return f"PAGE: {page.title()} ({page.url})\n{text[:4000]}"
    return _w.call(job)


def _find_clickable(page, target: str):
    t = target.strip()
    for loc in (page.get_by_role("button", name=t), page.get_by_role("link", name=t),
                page.get_by_role("button", name=re.compile(re.escape(t), re.I)),
                page.get_by_role("link", name=re.compile(re.escape(t), re.I)),
                page.get_by_text(t, exact=True), page.get_by_text(re.compile(re.escape(t), re.I))):
        try:
            if loc.count() and loc.first.is_visible():
                return loc.first
        except Exception:
            continue
    return None


def click(target: str, confirmed: bool = False):
    def job(w):
        page = w.ensure()
        el = _find_clickable(page, target)
        if el is None:
            return f"I can't see '{target}' on the page."
        label = (el.inner_text(timeout=2000) or target).strip()[:60]
        if not confirmed and RISKY_BUTTON.search(label + " " + target):
            return Confirm("browser_click", target, f"'{label}' may pay, send or delete something. "
                                                    "Say confirm to click it, or cancel.")
        el.click(timeout=8000)
        return f"Clicked {label}."
    return _w.call(job)


def type_text(field: str, text: str, submit: bool = False) -> str:
    def job(w):
        page = w.ensure()
        loc = None
        if field:
            for cand in (page.get_by_label(re.compile(re.escape(field), re.I)),
                         page.get_by_placeholder(re.compile(re.escape(field), re.I)),
                         page.get_by_role("searchbox"), page.get_by_role("textbox", name=re.compile(re.escape(field), re.I))):
                try:
                    if cand.count() and cand.first.is_visible():
                        loc = cand.first
                        break
                except Exception:
                    continue
        if loc is None:
            focused = page.evaluate("() => document.activeElement && ['INPUT','TEXTAREA'].includes(document.activeElement.tagName)")
            if not focused:
                return f"I can't find the {field or 'text'} box."
            loc = page.locator(":focus")
        attrs = loc.evaluate("e => [e.type||'', e.name||'', e.id||'', e.autocomplete||'', e.placeholder||'', "
                             "(e.labels && e.labels[0] ? e.labels[0].innerText : '')].join(' ')")
        if SECRET_FIELD.search(attrs or "") or SECRET_FIELD.search(field or ""):
            return "That's a password or payment box. I never type those - please type it yourself."
        loc.fill(text, timeout=8000)
        if submit:
            loc.press("Enter")
        return f"Typed it{' and pressed Enter' if submit else ''}."
    return _w.call(job)


def key(keys: str) -> str:
    def job(w):
        page = w.ensure()
        k = "+".join(p.capitalize() if len(p) > 1 else p for p in keys.replace(" ", "").split("+"))
        k = k.replace("Ctrl", "Control").replace("Esc", "Escape").replace("Pgdn", "PageDown").replace("Pgup", "PageUp")
        page.keyboard.press(k)
        return f"Pressed {keys}."
    return _w.call(job)


def nav(action: str) -> str:
    def job(w):
        page = w.ensure()
        if action == "back":
            page.go_back()
        elif action == "forward":
            page.go_forward()
        elif action == "reload":
            page.reload()
        elif action in ("scroll_down", "scroll_up"):
            page.mouse.wheel(0, 900 if action == "scroll_down" else -900)
        elif action == "new_tab":
            w.page = w.ctx.new_page()
        elif action == "close_tab":
            page.close()
            w.page = None
        return "Done."
    return _w.call(job)


def tabs(action: str = "list", index: int = 0) -> str:
    def job(w):
        w.ensure()
        pages = [p for p in w.ctx.pages if not p.is_closed()]
        if action == "switch" and 1 <= index <= len(pages):
            w.page = pages[index - 1]
            w.page.bring_to_front()
            return f"Switched to {w.page.title()}."
        return "Open tabs: " + "; ".join(f"{i}. {p.title() or p.url}" for i, p in enumerate(pages, 1))
    return _w.call(job)


# ---------------------------------------------------------------- AI tools

def register():
    import commands
    import nlu
    S = "string"
    nlu.register_tools([
        nlu._tool("browser_open", "Open a website or Google search in Hinata's Chrome window (she can then read, "
                  "click and type there).", ["target"], target=(S, "URL, site name or search terms")),
        nlu._tool("browser_youtube", "Search YouTube in the browser and play the first result.", ["query"],
                  query=(S, "what to play")),
        nlu._tool("browser_read", "Read the text of the page open in the browser."),
        nlu._tool("browser_click", "Click a button or link on the browser page by its visible text.", ["target"],
                  target=(S, "visible text of the button/link")),
        nlu._tool("browser_type", "Type into a box on the browser page (never passwords).", ["text"],
                  field=(S, "label or placeholder of the box, e.g. 'search'"), text=(S, "what to type"),
                  submit=("boolean", "press Enter after typing")),
        nlu._tool("browser_nav", "Browser navigation.", ["action"],
                  action=(S, "action", ("back", "forward", "reload", "scroll_down", "scroll_up", "new_tab", "close_tab"))),
        nlu._tool("browser_tabs", "List browser tabs or switch to one.", ["action"],
                  action=(S, "action", ("list", "switch")), index=("integer", "tab number for switch")),
    ], final={"browser_open", "browser_youtube"})
    h = commands.register_handler
    h("browser_open", lambda a: open_page(str(a.get("target") or "")))
    h("browser_youtube", lambda a: youtube(str(a.get("query") or "")))
    h("browser_read", lambda a: read(), info=True)
    h("browser_click", lambda a: click(str(a.get("target") or "")))
    h("browser_type", lambda a: type_text(str(a.get("field") or ""), str(a.get("text") or ""), bool(a.get("submit"))))
    h("browser_nav", lambda a: nav(str(a.get("action") or "")))
    h("browser_tabs", lambda a: tabs(str(a.get("action") or "list"), int(a.get("index") or 0)), info=True)
    commands.register_confirm("browser_click", lambda target: click(target, confirmed=True))
