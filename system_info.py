"""
System helpers: battery, CPU temperature, live stats, weather, and fast
lookups for installed apps and files.

Speed: the Start-menu app list and an index of your user folders are built
in the background at startup (and the app list is cached on disk), so
"open whatsapp" / "open resume.pdf" answer instantly instead of scanning
the disk on every command.
"""

import json
import os
import re
import subprocess
import threading
import time

import requests

import config

WEATHER_CODES = {
    0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 71: "light snow", 73: "snow",
    75: "heavy snow", 80: "rain showers", 81: "rain showers", 82: "violent rain showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}

SEARCH_FOLDERS = ["Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music"]
SKIP_DIRS = {"node_modules", "__pycache__", "venv", ".venv", ".git", "site-packages", "AppData"}
FILE_INDEX_LIMIT = 200_000
FILE_INDEX_REFRESH = 600          # seconds
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------- battery / temp / stats

def get_battery() -> str:
    try:
        import psutil
        battery = psutil.sensors_battery()
    except Exception:
        return "I can't read battery info on this device."
    if battery is None:
        return "This PC doesn't seem to have a battery."
    status = "plugged in and charging" if battery.power_plugged else "on battery"
    left = ""
    if not battery.power_plugged and battery.secsleft and battery.secsleft > 0:
        h, m = divmod(int(battery.secsleft) // 60, 60)
        left = f", about {h} hours {m} minutes left" if h else f", about {m} minutes left"
    return f"Battery is at {round(battery.percent)} percent, {status}{left}."


def get_cpu_temp() -> str:
    try:
        import wmi
        zones = wmi.WMI(namespace="root\\WMI").MSAcpi_ThermalZoneTemperature()
        if not zones:
            raise ValueError("no thermal zones")
        celsius = (zones[0].CurrentTemperature / 10.0) - 273.15
        return f"CPU temperature is about {celsius:.0f} degrees Celsius."
    except Exception:
        return ("I can't read the CPU temperature on this laptop - most laptops block it. "
                "Running LibreHardwareMonitor as administrator usually unlocks it.")


def get_stats() -> str:
    try:
        import psutil
    except Exception:
        return "I can't read system stats right now."
    cpu = psutil.cpu_percent(interval=0.3)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
    procs = []
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            procs.append((p.info["memory_info"].rss, p.info["name"]))
        except Exception:
            pass
    procs.sort(reverse=True)
    top = ", ".join(sorted({n.replace(".exe", "") for _, n in procs[:6] if n})[:3])
    return (f"CPU at {cpu:.0f} percent, memory {mem.percent:.0f} percent used, "
            f"{disk.free / 2**30:.0f} gigabytes free on the main drive. "
            f"Biggest memory users: {top}.")


# ---------------------------------------------------------------- weather

def get_weather(city: str = "") -> str:
    city = (city or config.DEFAULT_CITY).strip()
    try:
        if not city:
            city = requests.get("https://ipapi.co/json/", timeout=5).json().get("city", "")
            if not city:
                return "I couldn't figure out your location - try saying a city name."
        geo = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                           params={"name": city, "count": 1}, timeout=5).json()
        results = geo.get("results")
        if not results:
            return f"I couldn't find a place called {city}."
        lat, lon = results[0]["latitude"], results[0]["longitude"]
        name = results[0].get("name", city)
        cur = requests.get("https://api.open-meteo.com/v1/forecast",
                           params={"latitude": lat, "longitude": lon, "current_weather": True},
                           timeout=5).json().get("current_weather")
        if not cur:
            return f"I couldn't get the weather for {name}."
        desc = WEATHER_CODES.get(cur["weathercode"], "unclear conditions")
        return (f"It's {cur['temperature']:.0f} degrees and {desc} in {name}, "
                f"wind {cur['windspeed']:.0f} kilometers per hour.")
    except requests.RequestException:
        return "I couldn't reach the weather service - check your internet."
    except Exception:
        return "Something went wrong getting the weather."


# ---------------------------------------------------------------- file index

def _search_roots() -> list[str]:
    home = os.path.expanduser("~")
    roots = [os.path.join(home, f) for f in SEARCH_FOLDERS]
    for od in (os.environ.get("OneDrive"), os.environ.get("OneDriveConsumer")):
        if od:
            roots += [os.path.join(od, f) for f in ("Desktop", "Documents", "Pictures")]
    seen, out = set(), []
    for r in roots:
        if os.path.isdir(r) and r.lower() not in seen:
            seen.add(r.lower())
            out.append(r)
    return out


_files: list[tuple[str, str]] = []      # (lowercase filename, full path)
_dirs: list[tuple[str, str]] = []
_files_built_at = 0.0
_files_lock = threading.Lock()


def _build_file_index():
    global _files, _dirs, _files_built_at
    files, dirs = [], []
    for base in _search_roots():
        for root, ds, fs in os.walk(base):
            ds[:] = [d for d in ds if not d.startswith(".") and d not in SKIP_DIRS]
            for d in ds:
                dirs.append((d.lower(), os.path.join(root, d)))
            for f in fs:
                files.append((f.lower(), os.path.join(root, f)))
            if len(files) > FILE_INDEX_LIMIT:
                break
    with _files_lock:
        _files, _dirs, _files_built_at = files, dirs, time.time()
    print(f"[files] indexed {len(files)} files, {len(dirs)} folders.")


def _match(entries, q):
    exact = partial = None
    for name, path in entries:
        if name == q or os.path.splitext(name)[0] == q:
            exact = path
            break
        if partial is None and q in name:
            partial = path
    return exact or partial


def find_file(name: str) -> str | None:
    q = name.lower().strip()
    if not q:
        return None
    if not _files_built_at:
        _build_file_index()
    elif time.time() - _files_built_at > FILE_INDEX_REFRESH:
        threading.Thread(target=_build_file_index, daemon=True).start()
    with _files_lock:
        found = _match(_files, q)
    if found and os.path.exists(found):
        return found
    return None


def find_folder(name: str) -> str | None:
    q = name.lower().strip()
    if not q:
        return None
    if not _files_built_at:
        _build_file_index()
    with _files_lock:
        found = _match(_dirs, q)
    return found if found and os.path.isdir(found) else None


def search_files(query: str, limit: int = 8) -> list[str]:
    q = query.lower().strip()
    if not _files_built_at:
        _build_file_index()
    with _files_lock:
        return [p for n, p in _files if q in n][:limit]


# ---------------------------------------------------------------- installed apps

_apps_cache: list[tuple[str, str]] | None = None
_APPS_FILE = os.path.join(config.DATA_DIR, "apps_cache.json")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _scan_apps() -> list[tuple[str, str]]:
    apps = []
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=25, creationflags=_NO_WINDOW).stdout
        data = json.loads(out) if out.strip() else []
        if isinstance(data, dict):
            data = [data]
        for a in data:
            if a.get("Name") and a.get("AppID"):
                apps.append((a["Name"], "shell:AppsFolder\\" + a["AppID"]))
    except Exception as e:
        print(f"[apps] Get-StartApps failed: {e}")
    for base in (os.path.join(os.environ.get("ProgramData", ""), r"Microsoft\Windows\Start Menu\Programs"),
                 os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs")):
        if os.path.isdir(base):
            for root, _d, files in os.walk(base):
                for f in files:
                    if f.lower().endswith((".lnk", ".url")):
                        apps.append((os.path.splitext(f)[0], os.path.join(root, f)))
    return apps


def _refresh_apps():
    global _apps_cache
    apps = _scan_apps()
    if apps:
        _apps_cache = apps
        try:
            with open(_APPS_FILE, "w", encoding="utf-8") as f:
                json.dump(apps, f)
        except OSError:
            pass
        print(f"[apps] {len(apps)} Start-menu apps indexed.")


def _load_apps() -> list[tuple[str, str]]:
    global _apps_cache
    if _apps_cache is not None:
        return _apps_cache
    try:
        with open(_APPS_FILE, encoding="utf-8") as f:
            _apps_cache = [tuple(x) for x in json.load(f)]
            return _apps_cache
    except Exception:
        pass
    _refresh_apps()
    return _apps_cache or []


def find_app(name: str) -> tuple[str, str] | None:
    q = _norm(name)
    if not q:
        return None
    best, best_score = None, 0
    for disp, target in _load_apps():
        n = _norm(disp)
        if "uninstall" in n:
            continue
        if n == q:
            score = 100
        elif q.replace(" ", "") == n.replace(" ", ""):
            score = 90
        elif n.startswith(q):
            score = 80 - len(n) * 0.1
        elif f" {q} " in f" {n} ":
            score = 60 - len(n) * 0.1
        elif q in n:
            score = 40 - len(n) * 0.1
        else:
            continue
        if score > best_score:
            best, best_score = (disp, target), score
    return best


def launch(target: str):
    if target.startswith("shell:AppsFolder"):
        subprocess.Popen(["explorer.exe", target])
    else:
        os.startfile(target)


def kill_process(name: str) -> int:
    q = _norm(name).replace(" ", "")
    if len(q) < 3:
        return 0
    try:
        import psutil
    except Exception:
        return 0
    me = os.getpid()
    protected = {"explorer.exe", "python.exe", "pythonw.exe", "svchost.exe", "csrss.exe",
                 "winlogon.exe", "dwm.exe", "system", "lsass.exe", "services.exe", "ollama.exe"}
    count = 0
    for p in psutil.process_iter(["pid", "name"]):
        try:
            pname = (p.info["name"] or "").lower()
            if p.info["pid"] == me or pname in protected:
                continue
            if q in pname.replace(" ", ""):
                p.terminate()
                count += 1
        except Exception:
            continue
    return count


# ---------------------------------------------------------------- warm-up

def preload():
    """Called once at startup: loads the cached app list instantly, refreshes it
    and builds the file index in the background."""
    global _apps_cache
    try:
        with open(_APPS_FILE, encoding="utf-8") as f:
            _apps_cache = [tuple(x) for x in json.load(f)]
    except Exception:
        pass
    threading.Thread(target=_refresh_apps, daemon=True, name="apps-index").start()
    threading.Thread(target=_build_file_index, daemon=True, name="file-index").start()
