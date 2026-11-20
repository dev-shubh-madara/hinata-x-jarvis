"""Long-term memory and the all-drives file index."""
import os, sys, time, types, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
kb = types.ModuleType("keyboard"); kb.send = lambda k: None; kb.write = lambda t, delay=0: None
kb.add_hotkey = lambda *a, **k: None
sys.modules["keyboard"] = kb
import config, memory, file_index, commands, nlu

fails = 0
def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("OK  " if ok else "FAIL") + f" {name:55} -> {got!r}")

# ---------------------------------------------------------------- memory
check("remember", memory.remember("that my maths exam starts on 24 November"), "Got it, I'll remember that.")
memory.remember("my mentor's name is Rasmita")
memory.remember("I like lofi music while coding")
check("no duplicates", memory.remember("My maths exam starts on 24 November."), "Updated. I'll remember that.")
check("count", memory.count(), 3)
check("recall by topic", memory.recall("when is my exam"), ["My maths exam starts on 24 November."])
check("recall mentor", memory.recall("who is my mentor"), ["My mentor's name is Rasmita."])
check("no false recall", memory.recall("open chrome"), [])
check("context line for the AI", "Rasmita" in memory.context_for("what is my mentor's name"), True)
check("no context when irrelevant", memory.context_for("set volume to 40"), "")
check("forget", memory.forget("the exam"), "Forgotten: My maths exam starts on 24 November.")
check("forgotten for good", memory.recall("exam"), [])
check("forget unknown", memory.forget("my bike"), "I don't have anything like that saved.")
check("survives a restart (on disk)", len(memory._load()), 2)

# router: spoken patterns
check("say: remember that ...", commands.handle("remember that my college is SR University"),
      "Got it, I'll remember that.")
check("say: what do you remember about ...", commands.handle("what do you remember about my college"),
      "My college is SR University.")
check("say: forget ...", commands.handle("forget that my college is SR University"),
      "Forgotten: My college is SR University.")
check("memory is not 'work' (hologram stays)", commands.last_outcome(), "chat")
check("forget everything asks first", "confirm" in commands.handle("forget everything you know about me").lower(), True)
check("cancel keeps memory", (commands.handle("cancel"), memory.count())[1], 2)

# the AI sees relevant facts in its instructions
memory.remember("my sister's name is Riya")
nlu._set_context("what's my sister's name")
check("fact injected into system prompt", "Riya" in nlu._system_prompt(False), True)
nlu._set_context("open chrome")
check("not injected when irrelevant", "Riya" in nlu._system_prompt(False), False)

# ---------------------------------------------------------------- file index
root = tempfile.mkdtemp()
now = time.time()
files = {
    "College/Sem1/Physics/physics_unit2_semiconductors.pptx": now - 3 * 86400,
    "College/Sem1/Physics/physics_old_notes.pptx": now - 90 * 86400,
    "College/Sem1/Physics/physics lab report.docx": now - 2 * 86400,
    "College/Sem1/Maths/tangent_plane.pdf": now - 5 * 86400,
    "Downloads/Shubh_Resume_2026.pdf": now - 20 * 86400,
    "Downloads/resume_template.docx": now - 200 * 86400,
    "Projects/salon/index.html": now - 1 * 86400,
    "Projects/salon/README.md": now - 1 * 86400,
    "Projects/node_modules/physics/index.js": now,                 # must be skipped
    "Videos/reel_api_key.mp4": now - 3600,
    "Pictures/Screenshots/Screenshot 2026-11-20.png": now - 7200,
}
for rel, mt in files.items():
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write("x")
    os.utime(p, (mt, mt))

n = file_index.index([root])
check("indexed (node_modules skipped)", n, len(files) - 1 + 10)     # 10 folders
file_index._meta("full_at", time.time())
name = lambda q: (file_index.search(q) or [{"name": None}])[0]["name"]   # noqa: E731
check("physics ppt from last week", name("open my physics ppt from last week"), "physics_unit2_semiconductors.pptx")
check("physics ppt (any time, newest first)", name("physics ppt"), "physics_unit2_semiconductors.pptx")
check("lab report doc", name("find the physics lab report doc"), "physics lab report.docx")
check("resume pdf", name("where is my resume pdf"), "Shubh_Resume_2026.pdf")
check("salon project folder", name("open the salon project folder"), "salon")
check("latest video", name("my latest video"), "reel_api_key.mp4")
check("screenshot from today", name("screenshot from today"), "Screenshot 2026-11-20.png")
check("tangent pdf (2-letter-safe)", name("tangent plane pdf"), "tangent_plane.pdf")
check("nothing for nonsense", file_index.search("zebra quantum invoice"), [])
check("node_modules never shows", any("node_modules" in h["path"] for h in file_index.search("physics")), False)

# deleted files disappear after the next scan
os.remove(os.path.join(root, "Videos", "reel_api_key.mp4"))
file_index.index([root])
check("deleted file pruned", name("my latest video"), None)

# spoken summary
check("describe", file_index.describe(file_index.search("tangent plane pdf")).startswith("tangent_plane.pdf in Maths, changed"), True)

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
