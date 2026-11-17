"""
Video editing by voice.

    "edit my last video: cut from 0:10 to 0:45"     "speed up my last video 2x"
    "make my last video a reel with captions"       "compress this video for WhatsApp"
    "remove the first 5 seconds"                    "mute my last video"
    "turn my last video into a gif"                 "extract the audio from my last video"
    "add captions to my last video"                 "join my last 2 videos"
    "edit a video: ..."  -> a file picker opens so you can choose it

Which video: a path you say, else "pick/choose" opens a file picker, else the
newest video in your Videos, Downloads, Desktop or D:\\Hinata_Output folders.
Anything the patterns don't cover goes to the AI, which turns your words into
the same edit steps. The original is never changed: results go to
D:\\Hinata_Output\\Edits.
"""

import glob
import os
import re
import shutil
import subprocess
import sys
import threading
import time

import config

VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")
OUT = os.path.join(config.OUTPUT_DIR, "Edits")
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def _run(args, cwd=None) -> tuple[bool, str]:
    ff = ffmpeg()
    if not ff:
        return False, "ffmpeg isn't installed - run install.bat once."
    r = subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", *args], capture_output=True, text=True,
                       cwd=cwd, creationflags=NOWIN)
    return r.returncode == 0, (r.stderr or "")[-400:]


def duration(path: str) -> float:
    ff = ffmpeg()
    if not ff:
        return 0.0
    r = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True, creationflags=NOWIN)
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", r.stderr or "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def has_audio(path: str) -> bool:
    ff = ffmpeg()
    if not ff:
        return False
    r = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True, creationflags=NOWIN)
    return "Audio:" in (r.stderr or "")


# ---------------------------------------------------------------- finding the video

def _search_dirs():
    home = os.path.expanduser("~")
    dirs = [os.path.join(home, "Videos"), os.path.join(home, "Videos", "Captures"), os.path.join(home, "Downloads"),
            config.DESKTOP_DIR, os.path.join(config.OUTPUT_DIR, "Motion"), OUT]
    if os.name == "nt" and os.path.isdir("D:\\"):
        dirs.append("D:\\")
    return dirs


def recent_videos(n: int = 5) -> list[str]:
    found = []
    for d in _search_dirs():
        for pat in ("*", os.path.join("*", "*")):
            for p in glob.glob(os.path.join(d, pat)):
                if p.lower().endswith(VIDEO_EXT) and os.path.isfile(p):
                    found.append(p)
    found = sorted(set(found), key=lambda p: os.path.getmtime(p), reverse=True)
    return found[:n]


def pick_file(title="Choose a video", video=True) -> str | None:
    """A native file picker in its own process (safe next to the hologram)."""
    kinds = "[('Videos', '*.mp4 *.mov *.mkv *.webm *.avi *.m4v'), ('All files', '*.*')]" if video else \
        "[('Audio', '*.mp3 *.wav *.m4a *.aac *.ogg'), ('All files', '*.*')]"
    code = ("import tkinter as t, tkinter.filedialog as f; r=t.Tk(); r.withdraw(); r.attributes('-topmost',1); "
            f"print(f.askopenfilename(title={title!r}, filetypes={kinds}))")
    try:
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=600)
        p = (r.stdout or "").strip()
        return p if p and os.path.isfile(p) else None
    except Exception:
        return None


def find_video(text: str) -> str | None:
    m = re.search(r"([A-Za-z]:[\\/][^\"<>|*?]+?\.(?:mp4|mov|mkv|webm|avi|m4v))", text or "", re.I)
    if m and os.path.isfile(m.group(1)):
        return m.group(1)
    if re.search(r"\b(pick|choose|select|browse)\b|\ba video\b", (text or "").lower()) and \
            not re.search(r"\b(last|latest|recent|newest)\b", (text or "").lower()):
        return pick_file()
    vids = recent_videos(1)
    return vids[0] if vids else None


# ---------------------------------------------------------------- understanding the request

def _secs(s: str) -> float:
    s = s.strip()
    if ":" in s:
        parts = [float(x) for x in s.split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    m = re.match(r"([\d.]+)\s*(m|min|minute|minutes)?", s)
    v = float(m.group(1)) if m else 0
    return v * 60 if m and m.group(2) else v


_T = r"(\d+(?::\d{1,2}){0,2}(?:\.\d+)?\s*(?:s|sec|secs|seconds|m|min|minutes)?)"


def plan(text: str) -> list[dict]:
    """Turns words into edit steps. Unknown phrasing -> [] (the AI handles it)."""
    t = (text or "").lower()
    ops = []
    if (m := re.search(rf"\b(?:cut|trim|keep|clip)\b[a-z' ]{{0,30}}? {_T} ?(?:to|till|until|-) ?{_T}", t)):
        ops.append({"op": "trim", "start": _secs(m.group(1)), "end": _secs(m.group(2))})
    elif (m := re.search(rf"(?:remove|delete|cut|skip) (?:the )?first {_T}", t)):
        ops.append({"op": "trim", "start": _secs(m.group(1)), "end": None})
    elif (m := re.search(rf"(?:remove|delete|cut) (?:the )?last {_T}", t)):
        ops.append({"op": "trim_end", "seconds": _secs(m.group(1))})
    elif (m := re.search(rf"(?:keep|only|just) (?:the )?first {_T}", t)):
        ops.append({"op": "trim", "start": 0, "end": _secs(m.group(1))})
    elif (m := re.search(rf"(?:keep|only|just) (?:the )?last {_T}", t)):
        ops.append({"op": "keep_last", "seconds": _secs(m.group(1))})
    if (m := re.search(r"(\d(?:\.\d+)?)\s*x\b", t)) and re.search(r"\b(speed|fast|faster|slow|x)\b", t):
        ops.append({"op": "speed", "factor": float(m.group(1))})
    elif re.search(r"\bslow ?mo(?:tion)?\b|\bslow (?:it )?down\b", t):
        ops.append({"op": "speed", "factor": 0.5})
    elif re.search(r"\bspeed (?:it )?up\b|\bfaster\b", t):
        ops.append({"op": "speed", "factor": 1.5})
    if re.search(r"\b(reel|short|shorts|vertical|tiktok|9 ?: ?16|story)\b", t):
        ops.append({"op": "vertical"})
    if re.search(r"\b(caption|captions|subtitle|subtitles|subs)\b", t):
        ops.append({"op": "captions"})
    if re.search(r"\b(mute|remove (?:the )?(?:audio|sound)|no sound|silent)\b", t):
        ops.append({"op": "mute"})
    if re.search(r"\brotate\b", t):
        ops.append({"op": "rotate", "degrees": 180 if "180" in t else (270 if re.search(r"\bleft|anti|counter", t) else 90)})
    if re.search(r"\b(compress|smaller|reduce (?:the )?size|for whatsapp|whatsapp)\b", t):
        ops.append({"op": "compress"})
    if re.search(r"\b(add|put) (?:some |background )?music\b", t):
        ops.append({"op": "music"})
    if re.search(r"\bgif\b", t):
        ops.append({"op": "gif"})
    if re.search(r"\b(extract|get|save|take out) (?:the )?(?:audio|sound|music|mp3)\b|\bto mp3\b", t):
        ops.append({"op": "audio"})
    if (m := re.search(r"\b(?:join|merge|combine) (?:my )?(?:last |latest )?(\d+|two|three|four) videos\b", t)):
        n = {"two": 2, "three": 3, "four": 4}.get(m.group(1), None) or int(m.group(1))
        ops = [{"op": "join", "count": n}]
    return ops


AI_PROMPT = (
    "Turn the user's video edit request into JSON steps, in order. Allowed steps:\n"
    '{"op":"trim","start":seconds,"end":seconds or null}, {"op":"trim_end","seconds":n}, {"op":"keep_last","seconds":n}, '
    '{"op":"speed","factor":0.25-4}, {"op":"vertical"}, {"op":"captions"}, {"op":"mute"}, '
    '{"op":"rotate","degrees":90|180|270}, {"op":"compress"}, {"op":"music"}, {"op":"gif"}, {"op":"audio"}, '
    '{"op":"brightness","value":-0.3..0.3}, {"op":"fade"}\n'
    'Reply as {"steps":[...]} only. The video is DURATION seconds long.')


def ai_plan(text: str, dur: float) -> list[dict]:
    try:
        import brain
        obj = brain.ask_json(f"Request: {text}", AI_PROMPT.replace("DURATION", f"{dur:.1f}"), max_tokens=400, timeout=60)
        steps = obj.get("steps") if isinstance(obj, dict) else obj
        return [s for s in steps or [] if isinstance(s, dict) and s.get("op")]
    except Exception:
        return []


# ---------------------------------------------------------------- steps

def _out(src: str, tag: str, ext: str = ".mp4") -> str:
    os.makedirs(OUT, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src))[0]
    stem = re.sub(r"(_(trim|fast|slow|reel|captions|muted|rot|small|music|edited|faded|bright|joined)(_\d{6})?)+$", "", stem)
    return os.path.join(OUT, f"{stem}_{tag}{ext}")


def _vcodec(crf=20):
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart"]


def step(src: str, s: dict, status=print) -> tuple[str | None, str]:
    """Runs one step. Returns (new file or None, message)."""
    op = s["op"]
    dur = duration(src)
    if op in ("trim", "trim_end", "keep_last"):
        if op == "trim":
            a, b = float(s.get("start") or 0), s.get("end")
            b = float(b) if b not in (None, "") else dur
        elif op == "trim_end":
            a, b = 0.0, max(0.1, dur - float(s.get("seconds") or 0))
        else:
            a, b = max(0.0, dur - float(s.get("seconds") or 0)), dur
        if dur and (a >= dur or b <= a):
            return None, f"That cut is outside the video - it's only {dur:.0f} seconds long."
        out = _out(src, "trim")
        ok, err = _run(["-ss", f"{a:.3f}", "-i", src, "-t", f"{b - a:.3f}", *_vcodec(), "-c:a", "aac", out])
        return (out, f"cut it to {a:.0f}-{b:.0f} seconds") if ok else (None, f"cutting failed: {err}")
    if op == "speed":
        f = max(0.25, min(4.0, float(s.get("factor") or 1.5)))
        out = _out(src, "fast" if f > 1 else "slow")
        atempo, rest = [], f
        while rest > 2.0:
            atempo.append("atempo=2.0")
            rest /= 2.0
        while rest < 0.5:
            atempo.append("atempo=0.5")
            rest /= 0.5
        atempo.append(f"atempo={rest:.4f}")
        args = ["-i", src, "-filter:v", f"setpts={1 / f:.5f}*PTS"]
        args += ["-filter:a", ",".join(atempo)] if has_audio(src) else ["-an"]
        ok, err = _run(args + _vcodec() + [out])
        return (out, f"sped it up {f:g} times" if f > 1 else f"slowed it to {f:g} speed") if ok else (None, f"speed change failed: {err}")
    if op == "vertical":
        out = _out(src, "reel")
        vf = ("[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:2[bg];"
              "[b]scale=1080:1920:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]")
        args = ["-i", src, "-filter_complex", vf, "-map", "[v]"]
        args += ["-map", "0:a?", "-c:a", "aac"]
        ok, err = _run(args + _vcodec() + [out])
        return (out, "made it a 9 by 16 reel") if ok else (None, f"reel format failed: {err}")
    if op == "mute":
        out = _out(src, "muted")
        ok, err = _run(["-i", src, "-c:v", "copy", "-an", out])
        return (out, "removed the sound") if ok else (None, f"mute failed: {err}")
    if op == "rotate":
        deg = int(s.get("degrees") or 90)
        vf = {90: "transpose=1", 270: "transpose=2", 180: "transpose=1,transpose=1"}.get(deg, "transpose=1")
        out = _out(src, "rot")
        ok, err = _run(["-i", src, "-vf", vf, *_vcodec(), "-c:a", "copy", out])
        return (out, f"rotated {deg} degrees") if ok else (None, f"rotate failed: {err}")
    if op == "compress":
        out = _out(src, "small")
        ok, err = _run(["-i", src, "-vf", "scale='min(1280,iw)':-2", *_vcodec(28), "-c:a", "aac", "-b:a", "96k", out])
        if ok:
            mb_a, mb_b = os.path.getsize(src) / 1048576, os.path.getsize(out) / 1048576
            return out, f"compressed from {mb_a:.1f} to {mb_b:.1f} MB"
        return None, f"compressing failed: {err}"
    if op == "brightness":
        v = max(-0.4, min(0.4, float(s.get("value") or 0.1)))
        out = _out(src, "bright")
        ok, err = _run(["-i", src, "-vf", f"eq=brightness={v:.2f}", *_vcodec(), "-c:a", "copy", out])
        return (out, "changed the brightness") if ok else (None, f"brightness failed: {err}")
    if op == "fade":
        out = _out(src, "faded")
        st = max(0.0, dur - 0.8)
        args = ["-i", src, "-vf", f"fade=t=in:st=0:d=0.6,fade=t=out:st={st:.2f}:d=0.8"]
        args += ["-af", f"afade=t=in:st=0:d=0.6,afade=t=out:st={st:.2f}:d=0.8"] if has_audio(src) else []
        ok, err = _run(args + _vcodec() + [out])
        return (out, "added fades") if ok else (None, f"fade failed: {err}")
    if op == "gif":
        out = _out(src, "edited", ".gif")
        vf = "fps=12,scale=540:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse"
        ok, err = _run(["-i", src, "-t", "15", "-vf", vf, out])
        return (out, "made a GIF of the first 15 seconds") if ok else (None, f"GIF failed: {err}")
    if op == "audio":
        out = _out(src, "edited", ".mp3")
        ok, err = _run(["-i", src, "-vn", "-c:a", "libmp3lame", "-q:a", "2", out])
        return (out, "saved the audio as MP3") if ok else (None, f"audio extract failed: {err}")
    if op == "music":
        song = s.get("file") or pick_file("Choose the music", video=False)
        if not song:
            return None, "no music picked"
        out = _out(src, "music")
        if has_audio(src):
            fc = f"[1:a]volume=0.22,afade=t=out:st={max(0, dur - 2):.2f}:d=2[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]"
        else:
            fc = f"[1:a]afade=t=out:st={max(0, dur - 2):.2f}:d=2[a]"
        ok, err = _run(["-i", src, "-stream_loop", "-1", "-i", song, "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
                        "-c:v", "copy", "-c:a", "aac", "-t", f"{dur:.2f}", out])
        return (out, f"added {os.path.basename(song)} as music") if ok else (None, f"adding music failed: {err}")
    if op == "captions":
        return captions(src, status)
    return None, f"I don't know the step {op}"


# ---------------------------------------------------------------- captions (offline, on your GPU/CPU)

def _ts(x: float) -> str:
    ms = int(round(x * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _pip_install(pkg: str):
    def run():
        print(f"[edit] installing {pkg} ...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", pkg], creationflags=NOWIN)
        print(f"[edit] {pkg} installed")
    threading.Thread(target=run, daemon=True).start()


def captions(src: str, status=print) -> tuple[str | None, str]:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        _pip_install("faster-whisper")
        return None, "Captions need the offline speech model. I'm installing it now - ask again in two minutes."
    if not has_audio(src):
        return None, "That video has no sound to caption."
    status("Listening to the video for captions")
    wav = os.path.join(OUT, "_captions.wav")
    os.makedirs(OUT, exist_ok=True)
    ok, err = _run(["-i", src, "-vn", "-ac", "1", "-ar", "16000", wav])
    if not ok:
        return None, f"couldn't read the sound: {err}"
    try:
        try:
            model = WhisperModel(getattr(config, "WHISPER_MODEL", "small"), device="cuda", compute_type="float16")
        except Exception:
            model = WhisperModel(getattr(config, "WHISPER_MODEL", "small"), device="cpu", compute_type="int8")
        segs, _info = model.transcribe(wav, word_timestamps=True, vad_filter=True)
        words = [w for seg in segs for w in (seg.words or [])]
    finally:
        try:
            os.remove(wav)
        except OSError:
            pass
    if not words:
        return None, "I couldn't hear any speech in it."
    lines, chunk = [], []
    for w in words:                                   # short 3-4 word chunks, reel style
        chunk.append(w)
        if len(chunk) >= 4 or w.word.strip().endswith((".", "?", "!", ",")):
            lines.append(chunk)
            chunk = []
    if chunk:
        lines.append(chunk)
    srt_name = "_captions.srt"
    with open(os.path.join(OUT, srt_name), "w", encoding="utf-8") as f:
        for i, c in enumerate(lines, 1):
            text = " ".join(w.word.strip() for w in c).upper()
            f.write(f"{i}\n{_ts(c[0].start)} --> {_ts(c[-1].end)}\n{text}\n\n")
    out = _out(src, "captions")
    style = ("Fontname=Segoe UI Black,Fontsize=15,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
             "BorderStyle=1,Outline=3,Shadow=0,Alignment=2,MarginV=70")
    # run inside the output folder so the subtitle path needs no Windows escaping
    ok, err = _run(["-i", os.path.abspath(src), "-vf", f"subtitles={srt_name}:force_style='{style}'", *_vcodec(),
                    "-c:a", "copy", os.path.basename(out)], cwd=OUT)
    shutil.copyfile(os.path.join(OUT, srt_name), os.path.splitext(out)[0] + ".srt")
    return (out, f"added captions, {len(lines)} lines") if ok else (None, f"captions failed: {err}")


# ---------------------------------------------------------------- entry points

def join(paths: list[str]) -> tuple[str | None, str]:
    if len(paths) < 2:
        return None, "I need at least two videos to join."
    out = _out(paths[0], "joined")
    n = len(paths)
    parts = "".join(f"[{i}:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
                    f"setsar=1,fps=30[v{i}];" for i in range(n))
    audio_ok = all(has_audio(p) for p in paths)
    concat = "".join(f"[v{i}]" + (f"[{i}:a]" if audio_ok else "") for i in range(n))
    fc = parts + f"{concat}concat=n={n}:v=1:a={1 if audio_ok else 0}[v]" + ("[a]" if audio_ok else "")
    args = []
    for p in paths:
        args += ["-i", p]
    args += ["-filter_complex", fc, "-map", "[v]"] + (["-map", "[a]", "-c:a", "aac"] if audio_ok else [])
    ok, err = _run(args + _vcodec() + [out])
    return (out, f"joined {n} videos") if ok else (None, f"joining failed: {err}")


def reveal(path: str):
    try:
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    except Exception:
        pass


def edit(text: str, speak=None) -> str:
    """The whole job: find the video, work out the steps, run them, show the result."""
    ops = plan(text)
    if ops and ops[0]["op"] == "join":
        paths = list(reversed(recent_videos(ops[0]["count"])))
        out, msg = join(paths)
        if out:
            reveal(out)
            return f"Done - {msg}. It's in {OUT}."
        return msg
    src = find_video(text)
    if not src:
        return "I couldn't find a video. Say 'edit a video' and pick one, or say its full path."
    dur = duration(src)
    if not ops:
        ops = ai_plan(text, dur)
    if not ops:
        return ("Tell me what to do with it: cut from one time to another, speed up, make it a reel, add captions, "
                "compress for WhatsApp, mute, add music or make a GIF.")
    print(f"[edit] {os.path.basename(src)} ({dur:.0f}s) -> {ops}")
    done, cur, t0 = [], src, time.time()
    for s in ops:
        out, msg = step(cur, s, status=lambda m: print(f"[edit] {m}"))
        if not out:
            if done:
                break
            return msg[:1].upper() + msg[1:] + "."
        if cur != src and os.path.dirname(cur) == OUT and not cur.lower().endswith((".gif", ".mp3")):
            try:
                os.remove(cur)                       # keep only the final file
            except OSError:
                pass
        cur = out
        done.append(msg)
    final = cur
    if final != src and not final.lower().endswith((".gif", ".mp3")):
        nice = _out(src, "edited", os.path.splitext(final)[1])
        if os.path.exists(nice):
            nice = nice.replace("_edited", f"_edited_{time.strftime('%H%M%S')}")
        try:
            os.replace(final, nice)
            final = nice
        except OSError:
            pass
    reveal(final)
    return (f"Done in {time.time() - t0:.0f} seconds. I took {os.path.basename(src)}, {', then '.join(done)}. "
            f"Saved as {os.path.basename(final)} in your Edits folder.")
