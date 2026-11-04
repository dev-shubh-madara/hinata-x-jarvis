"""
Free, keyless general-question answering using DuckDuckGo's public
Instant Answer API - no signup, no API key, no cost. Works for a lot
of factual questions ("who is...", "what is...", "how tall is...").

Used only when the local AI brain (Ollama) is offline, so general
questions still get an answer.
"""

import requests


def answer(query: str) -> str:
    """Returns a short factual answer, or '' if nothing useful was found."""
    try:
        r = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=6,
        )
        data = r.json()
    except Exception:
        return ""

    abstract = (data.get("AbstractText") or "").strip()
    if abstract:
        return abstract

    answer_field = (data.get("Answer") or "").strip()
    if answer_field:
        return answer_field

    definition = (data.get("Definition") or "").strip()
    if definition:
        return definition

    for item in data.get("RelatedTopics", []):
        if isinstance(item, dict) and item.get("Text"):
            return item["Text"]

    return ""
