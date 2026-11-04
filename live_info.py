"""
Live info - things that change every minute. All free, no API keys.

    iss()            where the International Space Station is right now (+ opens a live map)
    news(topic)      top headlines (Google News RSS), optionally about a topic
    cricket()        live / recent cricket scores
"""

import re
import webbrowser
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import requests

_s = requests.Session()
_s.headers["User-Agent"] = "HinataXHelper/1.0"


def _get(url, timeout=6):
    r = _s.get(url, timeout=timeout)
    r.raise_for_status()
    return r


def iss(show_map: bool = True) -> str:
    try:
        d = _get("https://api.wheretheiss.at/v1/satellites/25544").json()
        lat, lon = float(d["latitude"]), float(d["longitude"])
        speed, alt = float(d.get("velocity", 27600)), float(d.get("altitude", 420))
    except Exception:
        try:
            p = _get("http://api.open-notify.org/iss-now.json").json()["iss_position"]
            lat, lon, speed, alt = float(p["latitude"]), float(p["longitude"]), 27600.0, 420.0
        except Exception as e:
            return f"I couldn't reach the space station tracker: {e}"
    where = _place(lat, lon)
    if show_map:
        webbrowser.open("https://wheretheiss.at/")
    ns, ew = ("north" if lat >= 0 else "south"), ("east" if lon >= 0 else "west")
    return (f"The International Space Station is over {where} right now, at {abs(lat):.1f} degrees {ns}, "
            f"{abs(lon):.1f} degrees {ew}, about {alt:.0f} kilometres up, moving at {speed:,.0f} kilometres an hour.")


def _place(lat, lon) -> str:
    try:
        d = _get(f"https://api.wheretheiss.at/v1/coordinates/{lat},{lon}", timeout=4).json()
        cc = (d.get("country_code") or "").upper()
        if cc and cc != "??":
            try:
                import pycountry  # optional
                return pycountry.countries.get(alpha_2=cc).name
            except Exception:
                return cc
    except Exception:
        pass
    return _ocean(lat, lon)


def _ocean(lat, lon) -> str:
    if lat > 66:
        return "the Arctic"
    if lat < -60:
        return "the Southern Ocean"
    if -70 <= lon <= 20 and lat > -60:
        return "the Atlantic Ocean"
    if 20 < lon <= 120 and lat < 25:
        return "the Indian Ocean"
    return "the Pacific Ocean"


def news(topic: str = "", count: int = 5) -> str:
    region = "hl=en-IN&gl=IN&ceid=IN:en"
    url = (f"https://news.google.com/rss/search?q={quote_plus(topic)}&{region}" if topic
           else f"https://news.google.com/rss?{region}")
    try:
        root = ET.fromstring(_get(url).content)
    except Exception as e:
        return f"I couldn't get the news: {e}"
    titles = []
    for item in root.iter("item"):
        t = (item.findtext("title") or "").strip()
        t = re.sub(r"\s+-\s+[^-]+$", "", t)          # drop " - Source"
        if t:
            titles.append(t)
        if len(titles) >= count:
            break
    if not titles:
        return "I didn't find any headlines" + (f" about {topic}." if topic else ".")
    head = f"Top news about {topic}" if topic else "Top headlines"
    return head + ": " + ". ".join(titles) + "."


def cricket() -> str:
    try:
        root = ET.fromstring(_get("https://static.cricinfo.com/rss/livescores.xml").content)
        games = [(i.findtext("title") or "").strip() for i in root.iter("item")]
        games = [g for g in games if g][:4]
        if games:
            return "Cricket right now: " + ". ".join(games) + "."
    except Exception:
        pass
    return news("cricket score live", 3)
