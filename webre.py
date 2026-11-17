"""
Website reverse engineering.

    "reverse engineer stripe.com"     -> how it's built: tech stack, fonts, colours,
                                         layout, API calls, plus an AI rebuild plan
    "clone the website example.com"   -> the same report + an offline study copy
                                         you can open and inspect

Everything is read from the public page (the same files your browser gets).
The offline copy is for studying or for rebuilding your own sites: its forms
are switched off and it carries a small "study copy" banner.
"""

import collections
import hashlib
import html
import os
import re
import time
import webbrowser
from urllib.parse import urljoin, urlparse

import requests

import config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
MAX_FILES = 160
MAX_BYTES = 45 * 1024 * 1024

# (name, pattern searched in the HTML + headers + script names)
TECH = [
    ("Next.js", r"/_next/|__NEXT_DATA__"), ("Nuxt", r"/_nuxt/|__NUXT__"), ("React", r"react(-dom)?[.\-@]|data-reactroot|__REACT"),
    ("Vue", r"vue(\.runtime)?(\.global)?(\.min)?\.js|data-v-[0-9a-f]{6,}"), ("Angular", r"ng-version=|angular(\.min)?\.js"),
    ("Svelte / SvelteKit", r"svelte-[a-z0-9]{5,}|/_app/immutable/"), ("Astro", r"astro-island|/_astro/"),
    ("Gatsby", r"___gatsby|/page-data/"), ("Remix", r"__remixContext"), ("Vite", r"/assets/index-[A-Za-z0-9_-]{8}\.js|/@vite/"),
    ("Tailwind CSS", r"tailwind|\b(?:sm|md|lg):[a-z-]+\b.*\bflex\b|--tw-"), ("Bootstrap", r"bootstrap(\.bundle)?(\.min)?\.(css|js)"),
    ("jQuery", r"jquery[.\-][\d.]*(min\.)?js|jquery\.min\.js"), ("GSAP", r"gsap|TweenMax|ScrollTrigger"),
    ("Three.js", r"three(\.module)?(\.min)?\.js|THREE\."), ("Framer Motion", r"framer-motion|data-framer"),
    ("Lenis smooth scroll", r"lenis"), ("Swiper", r"swiper"), ("Alpine.js", r"alpine(\.min)?\.js|x-data="),
    ("WordPress", r"wp-content|wp-includes"), ("Shopify", r"cdn\.shopify\.com|Shopify\.theme"), ("Wix", r"wixstatic\.com"),
    ("Webflow", r"webflow\.(js|css)|data-wf-"), ("Squarespace", r"squarespace"), ("Framer", r"framerusercontent\.com"),
    ("Google Fonts", r"fonts\.googleapis\.com"), ("Font Awesome", r"font-?awesome"), ("Google Analytics", r"gtag\(|googletagmanager"),
    ("Cloudflare", r"cf-ray|cdnjs\.cloudflare\.com|cloudflare"), ("Vercel", r"x-vercel|vercel"), ("Netlify", r"netlify"),
    ("Stripe", r"js\.stripe\.com"), ("Firebase", r"firebase(app|io)"), ("Supabase", r"supabase"),
]


# ---------------------------------------------------------------- small helpers

def normalise_url(text: str) -> str | None:
    """Pulls a web address out of what was said: 'clone stripe dot com' -> https://stripe.com"""
    t = (text or "").strip()
    t = re.sub(r"\s+dot\s+", ".", t, flags=re.I)
    t = re.sub(r"\s+slash\s+", "/", t, flags=re.I)
    m = re.search(r"(https?://[^\s\"'<>]+)", t, re.I) or \
        re.search(r"\b((?:[a-z0-9-]+\.)+(?:[a-z]{2,})(?:/[^\s\"'<>]*)?)", t, re.I)
    if not m:
        return None
    url = m.group(1).rstrip(".,)")
    return url if url.lower().startswith("http") else "https://" + url


def _get(url: str, timeout=12, binary=False):
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en"}, timeout=timeout)
    r.raise_for_status()
    return r if binary else r


def _attrs(tag: str) -> dict:
    return {k.lower(): html.unescape(v1 or v2 or v3 or "") for k, v1, v2, v3 in
            re.findall(r"([\w:-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", tag)}


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _out_dir(url: str) -> str:
    host = urlparse(url).netloc.replace("www.", "") or "site"
    d = os.path.join(config.OUTPUT_DIR, "WebRE", re.sub(r"[^A-Za-z0-9.-]+", "_", host))
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------- analysis

def analyse(url: str, deep: bool = True) -> dict:
    t0 = time.time()
    r = _get(url)
    r.encoding = r.encoding or "utf-8"
    page, final = r.text, r.url
    head_blob = " ".join(f"{k}: {v}" for k, v in r.headers.items())
    info = {"url": final, "host": urlparse(final).netloc, "status": r.status_code,
            "size_kb": round(len(r.content) / 1024, 1), "server": r.headers.get("server", ""),
            "powered": r.headers.get("x-powered-by", "")}

    m = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    info["title"] = _text(m.group(1)) if m else ""
    metas = [_attrs(x) for x in re.findall(r"<meta\b[^>]*>", page, re.I)]
    info["description"] = next((a.get("content", "") for a in metas
                                if a.get("name", "").lower() == "description"), "")
    info["generator"] = next((a.get("content", "") for a in metas
                              if a.get("name", "").lower() == "generator"), "")

    scripts = [urljoin(final, a["src"]) for a in (_attrs(x) for x in re.findall(r"<script\b[^>]*>", page, re.I))
               if a.get("src")]
    styles = [urljoin(final, a["href"]) for a in (_attrs(x) for x in re.findall(r"<link\b[^>]*>", page, re.I))
              if "stylesheet" in a.get("rel", "").lower() and a.get("href")]
    inline_css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", page, re.S | re.I))
    info["scripts"], info["styles"] = scripts, styles

    blob = page + " " + head_blob + " " + " ".join(scripts + styles)
    info["tech"] = [name for name, pat in TECH if re.search(pat, blob, re.I)]
    if info["generator"]:
        info["tech"].insert(0, info["generator"])

    # structure
    info["headings"] = [(lvl, _text(txt)[:90]) for lvl, txt in
                        re.findall(r"<h([1-3])\b[^>]*>(.*?)</h\1>", page, re.S | re.I) if _text(txt)][:30]
    nav = re.search(r"<nav\b.*?</nav>", page, re.S | re.I)
    info["nav"] = [t for t in (_text(x) for x in re.findall(r"<a\b[^>]*>(.*?)</a>", nav.group(0) if nav else "",
                                                            re.S | re.I)) if t and len(t) < 30][:14]
    info["counts"] = {k: len(re.findall(rf"<{k}\b", page, re.I)) for k in
                      ("section", "img", "video", "canvas", "svg", "form", "button", "a", "iframe")}
    info["forms"] = [[a.get("name") or a.get("type") or "?" for a in
                      (_attrs(i) for i in re.findall(r"<input\b[^>]*>", f, re.I))][:10]
                     for f in re.findall(r"<form\b.*?</form>", page, re.S | re.I)][:5]

    # styles: colours, fonts, breakpoints
    css = inline_css
    if deep:
        for s in styles[:6]:
            try:
                css += "\n" + _get(s, timeout=8).text[:700_000]
            except Exception:
                pass
    cols = collections.Counter(c.lower() for c in re.findall(r"#[0-9a-fA-F]{6}\b", css))
    info["colours"] = [c for c, _ in cols.most_common(10)]
    fonts = collections.Counter()
    for fam in re.findall(r"font-family\s*:\s*([^;}{]+)", css, re.I):
        first = fam.split(",")[0].strip().strip("'\"")
        if first and not first.startswith("var(") and first.lower() not in ("inherit", "initial", "unset"):
            fonts[first] += 1
    info["fonts"] = [f for f, _ in fonts.most_common(6)]
    info["breakpoints"] = sorted({int(x) for x in re.findall(r"@media[^{]*?(?:max|min)-width\s*:\s*(\d{3,4})px", css)})[:8]
    info["css_vars"] = len(set(re.findall(r"(--[\w-]+)\s*:", css)))
    info["animations"] = len(set(re.findall(r"@keyframes\s+([\w-]+)", css)))

    # API calls hinted at in the scripts
    apis = set(re.findall(r"[\"'`]((?:https?://[^\"'`\s]+)?/(?:api|graphql|v\d)/[^\"'`\s]{0,80})[\"'`]", page))
    if deep:
        host = urlparse(final).netloc
        for s in [s for s in scripts if urlparse(s).netloc == host][:5]:
            try:
                js = _get(s, timeout=8).text[:900_000]
                apis |= set(re.findall(r"[\"'`]((?:https?://[^\"'`\s]+)?/(?:api|graphql|v\d)/[^\"'`\s]{0,80})[\"'`]", js))
                blob_js = js[:200_000]
                info["tech"] += [n for n, pat in TECH if n not in info["tech"] and re.search(pat, blob_js, re.I)
                                 and n in ("React", "Vue", "GSAP", "Three.js", "Framer Motion", "Lenis smooth scroll",
                                           "Firebase", "Supabase", "Stripe")]
            except Exception:
                pass
    info["apis"] = sorted(apis)[:20]
    info["seconds"] = round(time.time() - t0, 1)
    info["_html"] = page
    return info


def _plan(info: dict, generate) -> str:
    """Asks the local AI for a short rebuild plan from the facts found."""
    if not generate:
        return ""
    facts = (f"Site: {info['host']}\nTitle: {info['title']}\nTech found: {', '.join(info['tech']) or 'plain HTML/CSS/JS'}\n"
             f"Fonts: {', '.join(info['fonts'])}\nMain colours: {', '.join(info['colours'][:6])}\n"
             f"Navigation: {', '.join(info['nav'])}\nHeadings: {'; '.join(h for _, h in info['headings'][:12])}\n"
             f"Counts: {info['counts']}\nAPI paths: {', '.join(info['apis'][:8]) or 'none found'}")
    try:
        return generate("You are a senior front-end engineer. From these facts about a website, write a short, "
                        "practical plan to build a site with the same structure from scratch: the stack to use, "
                        "the page sections in order, the components, the animations, and the data it needs. "
                        "6 to 9 short bullet lines starting with '- '. Plain text.\n\n" + facts) or ""
    except Exception:
        return ""


def _report(info: dict, plan: str, clone_path: str = "", live: dict | None = None) -> str:
    e = html.escape
    chips = lambda items: "".join(f"<span class=chip>{e(str(i))}</span>" for i in items) or "<i>none found</i>"
    sw = "".join(f"<div class=sw><b style='background:{c}'></b>{c}</div>" for c in info["colours"])
    heads = "".join(f"<div class='h h{l}'>H{l} &nbsp; {e(t)}</div>" for l, t in info["headings"]) or "<i>none</i>"
    counts = "".join(f"<div class=stat><b>{v}</b>{k}</div>" for k, v in info["counts"].items())
    forms = "".join(f"<li>{e(', '.join(f))}</li>" for f in info["forms"]) or "<li>none</li>"
    apis = "".join(f"<li><code>{e(a)}</code></li>" for a in info["apis"]) or "<li>none found in the page scripts</li>"
    plan_html = "".join(f"<li>{e(l.lstrip('-• ').strip())}</li>" for l in plan.splitlines() if l.strip()) \
        or "<li>(AI brain offline - no plan written)</li>"
    files = "".join(f"<li><code>{e(s)}</code></li>" for s in (info["styles"] + info["scripts"])[:40])
    clone = f"<p class=ok>Plain offline copy (no JavaScript effects): <a href='{e(clone_path)}'>open index.html</a></p>" if clone_path else ""
    if live:
        ck = live.get("check", {})
        types = ", ".join(f"{v} {k}" for k, v in sorted(live.get("types", {}).items(), key=lambda kv: -kv[1]))
        shots = "".join(f"<div class=pair><img src='live copy/live_{i}.png'><img src='live copy/copy_{i}.png'>"
                        f"<span>{sc}% match</span></div>" for i, sc in enumerate(ck.get("scores", [])))
        clone = (f"<p class=ok><b>Live copy recorded</b> - {live.get('requests', 0)} files ({e(types)}), "
                 f"{live.get('mb', 0)} MB, overall match <b>{ck.get('score', 0)}%</b>. JavaScript, 3D, smooth scroll "
                 f"and cursor effects run in it. Open it again any time with <code>open copy.bat</code> in "
                 f"<code>{e(live.get('folder', ''))}</code>, or say \"open the copy of {e(info['host'])}\".</p>"
                 f"<h2>Real site vs copy</h2><div class=pairs>{shots}</div>") + clone
    doc = f"""<!doctype html><meta charset=utf-8><title>{e(info['host'])} - how it's built</title>
<style>body{{background:#0b0716;color:#e9e2ff;font:15px/1.6 Segoe UI,system-ui,sans-serif;margin:0;padding:32px;max-width:980px;margin:auto}}
h1{{font-size:30px;margin:0;color:#fff}}h2{{color:#b79cff;font-size:15px;letter-spacing:2px;text-transform:uppercase;margin:30px 0 10px}}
a{{color:#ff9ad5}}.sub{{color:#9f93c9}}.chip{{display:inline-block;background:#1d1240;border:1px solid #6a4bff;border-radius:14px;padding:3px 12px;margin:3px}}
.sw{{display:inline-block;margin:4px 10px 4px 0;font:12px Consolas,monospace}}.sw b{{display:inline-block;width:26px;height:26px;border-radius:6px;vertical-align:middle;margin-right:6px;border:1px solid #fff3}}
.stat{{display:inline-block;background:#150d2e;border-radius:10px;padding:8px 16px;margin:4px;text-align:center;color:#9f93c9}}.stat b{{display:block;font-size:22px;color:#fff}}
.h{{padding:2px 0}}.h2{{padding-left:22px;color:#cbbcff}}.h3{{padding-left:44px;color:#9f93c9}}code{{font:13px Consolas,monospace;color:#bfe8ff;word-break:break-all}}
.pairs{{display:grid;gap:14px}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:8px;position:relative}}.pair img{{width:100%;border-radius:8px;border:1px solid #fff2}}.pair span{{position:absolute;right:8px;top:8px;background:#0b0716cc;padding:2px 10px;border-radius:6px}}
.ok{{background:#12301f;border:1px solid #3ddc84;border-radius:10px;padding:10px 16px}}li{{margin:3px 0}}</style>
<h1>{e(info['title'] or info['host'])}</h1>
<div class=sub>{e(info['url'])} · {info['size_kb']} KB HTML · analysed in {info['seconds']} s · server: {e(info['server'] or '?')}</div>
{clone}
<h2>Tech stack</h2>{chips(info['tech'] or ['Plain HTML / CSS / JS'])}
<h2>Rebuild plan</h2><ul>{plan_html}</ul>
<h2>Design</h2><p><b>Fonts:</b> {chips(info['fonts'])}</p><p><b>Colours:</b><br>{sw or '<i>none found</i>'}</p>
<p><b>Breakpoints:</b> {chips(str(b) + 'px' for b in info['breakpoints'])} &nbsp; <b>CSS variables:</b> {info['css_vars']} &nbsp; <b>Keyframe animations:</b> {info['animations']}</p>
<h2>Page structure</h2><p><b>Navigation:</b> {chips(info['nav'])}</p>{counts}<div style="margin-top:12px">{heads}</div>
<h2>Forms</h2><ul>{forms}</ul>
<h2>API paths seen in the code</h2><ul>{apis}</ul>
<h2>Stylesheets and scripts</h2><ul>{files}</ul>
<p class=sub>Made by Hinata X Helper from the public page. Use it to learn from, or to rebuild sites you own.</p>"""
    path = os.path.join(_out_dir(info["url"]), "report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path


# ---------------------------------------------------------------- offline study copy

def _local_name(url: str, used: dict) -> str:
    if url in used:
        return used[url]
    p = urlparse(url)
    base = os.path.basename(p.path) or "file"
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)[-60:]
    stem, ext = os.path.splitext(base)
    name = f"{stem}_{hashlib.md5(url.encode()).hexdigest()[:6]}{ext or '.bin'}"
    used[url] = "assets/" + name
    return used[url]


def snapshot(info: dict) -> str:
    """Saves the page with its CSS, scripts, images and fonts for offline study."""
    out = _out_dir(info["url"])
    os.makedirs(os.path.join(out, "assets"), exist_ok=True)
    base, page = info["url"], info["_html"]
    used, budget = {}, {"files": 0, "bytes": 0}

    def fetch(u: str):
        if budget["files"] >= MAX_FILES or budget["bytes"] >= MAX_BYTES:
            return None
        try:
            r = _get(u, timeout=10)
        except Exception:
            return None
        budget["files"] += 1
        budget["bytes"] += len(r.content)
        return r

    def save(u: str, css_depth=0):
        if not u or u.startswith(("data:", "javascript:", "#", "mailto:", "tel:", "blob:")):
            return None
        full = urljoin(base, u)
        if full in used:
            return used[full]
        r = fetch(full)
        if r is None:
            return None
        local = _local_name(full, used)
        data = r.content
        if (local.endswith(".css") or "text/css" in r.headers.get("content-type", "")) and css_depth < 2:
            text = r.text

            def sub(m):
                inner = m.group(2).strip()
                got = None if inner.startswith("data:") else _save_from(full, inner, css_depth + 1)
                return f"url({m.group(1)}{os.path.basename(got) if got else inner}{m.group(1)})"
            text = re.sub(r"url\(\s*(['\"]?)([^)'\"]+)\1\s*\)", sub, text)
            data = text.encode("utf-8", "replace")
        with open(os.path.join(out, local), "wb") as f:
            f.write(data)
        return local

    def _save_from(css_url: str, ref: str, depth: int):
        return save(urljoin(css_url, ref), depth)

    def swap(tag_re, attr):
        nonlocal page

        def rep(m):
            tag = m.group(0)
            am = re.search(rf"\b{attr}\s*=\s*(\"[^\"]*\"|'[^']*')", tag, re.I)
            if not am:
                return tag
            val = html.unescape(am.group(1)[1:-1])
            local = save(val)
            return tag if not local else tag[:am.start(1)] + f'"{local}"' + tag[am.end(1):]
        page = re.sub(tag_re, rep, page, flags=re.I)

    swap(r"<link\b[^>]*rel\s*=\s*[\"']?[^>]*(?:stylesheet|icon)[^>]*>", "href")
    swap(r"<script\b[^>]*\bsrc\s*=[^>]*>", "src")
    swap(r"<img\b[^>]*>", "src")
    swap(r"<source\b[^>]*>", "src")
    page = re.sub(r"\s(?:srcset|integrity|crossorigin)\s*=\s*(\"[^\"]*\"|'[^']*')", "", page, flags=re.I)
    page = re.sub(r"<base\b[^>]*>", "", page, flags=re.I)
    # study copy: forms go nowhere
    page = re.sub(r"(<form\b[^>]*?)\saction\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", r"\1", page, flags=re.I)
    page = re.sub(r"<form\b", '<form action="#" onsubmit="return false"', page, flags=re.I)
    banner = (f'<div style="position:fixed;z-index:2147483647;left:0;right:0;bottom:0;background:#150d2e;color:#e9e2ff;'
              f'font:13px Segoe UI,sans-serif;padding:6px 14px;text-align:center;opacity:.92">Offline study copy of '
              f'{html.escape(info["host"])} - saved by Hinata X Helper. Forms are switched off.</div>')
    page = re.sub(r"</body>", banner + "</body>", page, count=1, flags=re.I) if re.search(r"</body>", page, re.I) \
        else page + banner
    path = os.path.join(out, "index.html")
    with open(path, "w", encoding="utf-8", errors="replace") as f:
        f.write(page)
    info["snapshot_files"] = budget["files"]
    info["snapshot_mb"] = round(budget["bytes"] / 1048576, 1)
    return path


# ---------------------------------------------------------------- entry point

def _live_copy(url: str, info: dict) -> dict | None:
    """Records the running site (JS, 3D, smooth scroll, cursor effects) and checks the replay."""
    try:
        import webcap
    except Exception as e:
        print(f"[webre] live capture unavailable: {e}")
        return None
    folder = os.path.join(_out_dir(url), "live copy")
    try:
        meta = webcap.capture(url, folder, status=lambda m: print(f"[webre] {m}"))
        meta["check"] = webcap.check(folder)
        webcap.write_launcher(folder)
        meta["folder"] = folder
        print(f"[webre] live copy: {meta['requests']} files, {meta['mb']} MB, match {meta['check']['score']}%")
        return meta
    except Exception as e:
        print(f"[webre] live capture failed: {e}")
        return None


def open_copy(text_or_url: str) -> str:
    """'open the copy of example.com' - replays a recorded site."""
    url = normalise_url(text_or_url)
    if not url:
        return "Which site's copy? Say its address."
    folder = os.path.join(_out_dir(url), "live copy")
    import webcap
    if not os.path.exists(os.path.join(folder, "recording.zip")):
        return f"I don't have a copy of {urlparse(url).netloc} yet. Say: clone {urlparse(url).netloc}."
    return webcap.open_copy(folder)


def run(text_or_url: str, clone: bool = False, generate=None, open_report: bool = True) -> str:
    url = normalise_url(text_or_url)
    if not url:
        return "Which website? Say the address, like: reverse engineer example dot com."
    try:
        info = analyse(url)
    except requests.RequestException as e:
        return f"I couldn't open {urlparse(url).netloc}: {str(e)[:90]}"
    clone_path, live = "", None
    if clone:
        live = _live_copy(url, info)
        try:
            clone_path = snapshot(info)            # static fallback copy (plain HTML + assets)
        except Exception as e:
            print(f"[webre] snapshot failed: {e}")
    report = _report(info, _plan(info, generate), clone_path, live)
    print(f"[webre] {info['host']}: {', '.join(info['tech']) or 'plain'}  ({info['seconds']}s)  -> {report}")
    if open_report:
        try:
            webbrowser.open("file:///" + report.replace("\\", "/"))
        except Exception:
            pass
        if live:
            import webcap
            webcap.open_copy(live["folder"])
        elif clone_path:
            try:
                webbrowser.open("file:///" + clone_path.replace("\\", "/"))
            except Exception:
                pass
    tech = ", ".join(info["tech"][:5]) or "plain HTML, CSS and JavaScript"
    said = (f"{info['host']} is built with {tech}. It uses {len(info['fonts'])} fonts and "
            f"{info['counts']['section']} sections. ")
    if live:
        score = live["check"]["score"]
        said += (f"I recorded the live site, {live['requests']} files, and opened the offline copy. "
                 f"It matches the real site about {score} percent. ")
        if score < 80:
            said += "Some parts load live data, so they can't work offline. "
    elif clone_path:
        said += (f"The live recording didn't work, so I saved a plain copy with {info.get('snapshot_files', 0)} files "
                 "and opened it with the report.")
    else:
        said += "I've opened the full report with the rebuild plan."
    return said.strip()
