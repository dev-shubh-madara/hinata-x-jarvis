"""
Screen reading (OCR): Hinata reads every word on your screen exactly.

The vision model (vision.py) is good at "what is this?", but it guesses at
long text. For errors, code, terminal output and documents she needs the
exact characters, so this uses the OCR engine built into Windows 10/11
(Windows.Media.Ocr): offline, no download, ~0.3 s for a full screen.

    "read my screen"            -> she reads it out (short) / gives the text to the AI
    "read this error and fix it" -> the coder (coder.py) gets the exact traceback

Fallbacks: Tesseract if installed, then the local vision model.
"""

import asyncio
import re

_hide = {"fn": None}


def set_hider(fn):
    """fn() hides the hologram for a moment so it isn't in the screenshot."""
    _hide["fn"] = fn


def grab(region=None):
    from PIL import ImageGrab
    if _hide["fn"]:
        try:
            _hide["fn"]()
            import time
            time.sleep(0.12)
        except Exception:
            pass
    return ImageGrab.grab(bbox=region, all_screens=False)


async def _windows_ocr(img) -> str:
    from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError("no OCR language installed in Windows")
    limit = int(OcrEngine.max_image_dimension or 10000)
    if max(img.size) > limit:
        img.thumbnail((limit, limit))
    rgba = img.convert("RGBA")
    w, h = rgba.size
    writer = DataWriter()
    writer.write_bytes(rgba.tobytes("raw", "BGRA"))
    bmp = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.BGRA8, w, h,
                                                BitmapAlphaMode.PREMULTIPLIED)
    result = await engine.recognize_async(bmp)
    return "\n".join(line.text for line in result.lines)


def ocr(img) -> str:
    """Image -> text. Windows OCR, then Tesseract."""
    errors = []
    try:
        return asyncio.run(_windows_ocr(img))
    except Exception as e:
        errors.append(f"windows ocr: {e}")
    try:
        import pytesseract
        return pytesseract.image_to_string(img)
    except Exception as e:
        errors.append(f"tesseract: {e}")
    raise RuntimeError("; ".join(errors))


def read_text(region=None) -> str:
    """Every word on the screen right now ('' if OCR isn't available)."""
    try:
        return tidy(ocr(grab(region)))
    except Exception as e:
        print(f"[screen] OCR unavailable: {e}")
        return ""


def tidy(text: str) -> str:
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    out, blank = [], 0
    for ln in lines:
        blank = blank + 1 if not ln.strip() else 0
        if blank <= 1:
            out.append(ln)
    return "\n".join(out).strip()


_ERR = re.compile(r"(Traceback \(most recent call last\):.*?(?:\n\S[^\n]*(?:Error|Exception)[^\n]*))|"
                  r"((?:\w+\.)*\w*(?:Error|Exception): .+)|(error(?: \w+)?: .+)|(npm ERR!.+)|(SyntaxError.+)",
                  re.S | re.I)


def find_error(text: str) -> str:
    """The most useful error block in a screen's text ('' if none)."""
    m = list(_ERR.finditer(text or ""))
    if not m:
        return ""
    best = max(m, key=lambda x: len(x.group(0)))
    start = max(0, best.start() - 400)
    return text[start:best.end() + 200].strip()


def summary(text: str, limit: int = 3000) -> str:
    return text if len(text) <= limit else text[:limit] + " ...(cut)"


# ---------------------------------------------------------------- AI tools

def register():
    import commands
    import nlu
    set_hider(commands._ghost_for_capture)
    nlu.register_tools([
        nlu._tool("read_screen_text", "Read the EXACT text on the user's screen (OCR): errors, code, terminal output, "
                  "documents, chat messages. Use before fixing an error shown on screen or when exact words matter."),
    ])

    def tool(_a):
        text = read_text()
        if not text:
            import vision
            return vision.look("Read out all the text you can see, exactly.", hide_overlay=commands._ghost_for_capture)
        err = find_error(text)
        return ("ERROR ON SCREEN:\n" + err + "\n\nFULL SCREEN TEXT:\n" if err else "") + summary(text)

    commands.register_handler("read_screen_text", tool, info=True)
