"""Browser control, the coding helper and screen error parsing."""
import os, sys, threading, types, tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
kb = types.ModuleType("keyboard"); kb.send = lambda k: None; kb.write = lambda t, delay=0: None
kb.add_hotkey = lambda *a, **k: None
sys.modules["keyboard"] = kb
import config, commands, coder, screen
from pc_actions import Confirm

fails = 0
def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("OK  " if ok else "FAIL") + f" {name:55} -> {got!r}")

# ---------------------------------------------------------------- coder: running snippets
config.OUTPUT_DIR = tempfile.mkdtemp()
coder.CODE_DIR = os.path.join(config.OUTPUT_DIR, "Code")
check("runs a snippet", coder.run_code("print(sum(range(101)))"), "5050")
check("strips ``` fences", coder.run_code("```python\nprint('hi')\n```"), "hi")
check("reports the error line", coder.run_code("1/0").startswith("It failed: ZeroDivisionError"), True)
check("writing inside Code folder is fine", coder.run_code("open('out.txt','w').write('x'); print('ok')"), "ok")
for risky in ["import os; os.remove('C:/x')", "import shutil; shutil.rmtree('D:/')", "import subprocess",
              "open('C:/Windows/x.txt','w')", "open('../../x','w')", "import requests; requests.post('http://x')"]:
    check(f"asks first: {risky[:34]}", isinstance(coder.run_code(risky), Confirm), True)
coder.RUN_TIMEOUT = 2
check("stops runaway code", coder.run_code("while True: pass").startswith("It ran longer than 2 seconds"), True)

# ---------------------------------------------------------------- coder: tracebacks + fixing
tb = '''Traceback (most recent call last):
  File "D:\\\\Projects\\\\bot\\\\main.py", line 12, in <module>
    run()
  File "C:\\\\Users\\\\SHUBH\\\\AppData\\\\Local\\\\Programs\\\\Python\\\\Python312\\\\Lib\\\\json\\\\__init__.py", line 346, in loads
  File "D:\\\\Projects\\\\bot\\\\utils.py", line 4, in run
    return 10 / count
ZeroDivisionError: division by zero'''
check("traceback files, innermost first, no stdlib", coder.files_in_traceback(tb),
      ["D:\\\\Projects\\\\bot\\\\utils.py", "D:\\\\Projects\\\\bot\\\\main.py"])

proj = tempfile.mkdtemp()
bug = os.path.join(proj, "avg.py")
open(bug, "w").write("nums = [3, 4, 5]\nprint(sum(nums) / len(num))\n")
asked = {}
def fake_ask(prompt, system):
    asked["prompt"] = prompt
    return "```python\nnums = [3, 4, 5]\nprint(sum(nums) / len(nums))\n```\nWHY: a typo, num instead of nums."
coder._code_cmd = lambda args: True                         # no VS Code here
res = coder.fix(bug, ask=fake_ask)
check("fix runs the file to get the error", "NameError" in asked["prompt"], True)
check("fix asks before saving", isinstance(res, Confirm) and "typo" in res.question, True)
check("original untouched until confirm", open(bug).read(), "nums = [3, 4, 5]\nprint(sum(nums) / len(num))\n")
commands._ask(res)
check("confirm saves + keeps .bak", commands.handle("confirm"), "Saved the fix. Your old version is avg.py.bak.")
check("file fixed", coder._run([sys.executable, bug])[0].strip(), "4.0")
check("backup kept", os.path.exists(bug + ".bak"), True)

open(bug, "w").write("print(1/0)\n")
commands._ask(coder.fix(bug, ask=lambda p, s: "```python\nprint(1)\n```\nWHY: no divide by zero."))
check("cancel discards the proposal", (commands.handle("cancel"), os.path.exists(bug + ".hinata-fix")), ("Cancelled.", False))
open(bug, "w").write("print('fine')\n")
check("working file: nothing to fix", coder.fix(bug, ask=fake_ask).startswith("avg.py runs without errors"), True)

# ---------------------------------------------------------------- screen: error from OCR text
ocr_text = "VS Code  main.py  Terminal\nPS D:\\bot> python main.py\n" + tb + "\nPS D:\\bot>"
err = screen.find_error(ocr_text)
check("finds the traceback in screen text", "ZeroDivisionError" in err and "utils.py" in err, True)
check("no error -> ''", screen.find_error("Hello Shubh, all tests passed"), "")

# ---------------------------------------------------------------- spoken routes
real = (coder.fix_from_screen, coder.fix, coder.open_in_vscode)
coder.fix_from_screen = lambda: "<screen fix>"
coder.fix = lambda f, e="": f"<fix {f}>"
coder.open_in_vscode = lambda f: f"<vscode {f}>"
commands.vision.look = lambda q, hide_overlay=None: "<vision>"
for said, want in [("read this error and fix it", "<screen fix>"), ("fix this error", "<screen fix>"),
                   ("can you debug the crash", "<screen fix>"), ("fix my bot.py", "<fix bot.py>"),
                   ("open the salon project in vs code", "<vscode salon project>"),
                   ("what does this error mean", "<vision>")]:
    check(f"say: {said}", commands.handle(said), want)
coder.fix_from_screen, coder.fix, coder.open_in_vscode = real

# ---------------------------------------------------------------- browser (real headless Chromium)
site = tempfile.mkdtemp()
open(os.path.join(site, "index.html"), "w").write("""<!doctype html><title>Shop</title>
<main><h1>Hello Boss</h1><p>Your cart has 1 item.</p>
<label>Search <input id=q placeholder="Search products"></label>
<label>Password <input type=password id=pw></label>
<button onclick="document.title='clicked-more'">Show more</button>
<button onclick="document.title='ORDERED'">Place order</button>
<a href="page2.html">Next page</a></main>""")
open(os.path.join(site, "page2.html"), "w").write("<title>Page two</title><main>Second page text</main>")
class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=site, **k)
    def log_message(self, *a): pass
srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_port}/index.html"

try:
    import browser
    config.BROWSER_AGENT_CHANNEL = ""
    config.BROWSER_HEADLESS = True
    browser.register()
    check("open", browser.open_page(url), "Opened Shop.")
    check("read the page", "Your cart has 1 item." in browser.read(), True)
    check("type into a labelled box", browser.type_text("search", "headphones"), "Typed it.")
    check("value really typed", browser._w.call(lambda w: w.page.input_value("#q")), "headphones")
    check("never types passwords", browser.type_text("password", "hunter2"),
          "That's a password or payment box. I never type those - please type it yourself.")
    check("password box still empty", browser._w.call(lambda w: w.page.input_value("#pw")), "")
    check("normal click", browser.click("Show more"), "Clicked Show more.")
    check("click worked", browser._w.call(lambda w: w.page.title()), "clicked-more")
    q = commands.execute("browser_click", {"target": "Place order"})
    check("pay/order button asks first", "confirm" in q.lower(), True)
    check("not clicked yet", browser._w.call(lambda w: w.page.title()), "clicked-more")
    check("confirm clicks it", commands.handle("confirm"), "Clicked Place order.")
    check("order really clicked", browser._w.call(lambda w: w.page.title()), "ORDERED")
    check("follow a link", browser.click("Next page"), "Clicked Next page.")
    browser._w.call(lambda w: w.page.wait_for_load_state())
    check("now on page two", "Second page text" in browser.read(), True)
    check("back", browser.nav("back"), "Done.")
    check("tabs list", browser.tabs().startswith("Open tabs: 1."), True)
    check("missing element", browser.click("Unicorn button"), "I can't see 'Unicorn button' on the page.")
    check("url from site name", browser._url("github"), "https://github.com")
    check("url from search words", browser._url("lofi beats").startswith("https://www.google.com/search?q=lofi"), True)
except ImportError as e:
    print(f"SKIP browser tests: {e}")

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
