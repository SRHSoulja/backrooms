#!/usr/bin/env python3
"""Roots from what the public web is saying today, never from a human list.

Wikipedia's current-events portal is a public, dated, sourced list of things
that happened, written and cited by thousands of editors. Each item is a
specific claim that several independent outlets report, which is what a
corroboration world needs: the residents can find a second source, and a
different figure when one exists. The items are read through the broker's
guarded fetch, stripped of markup, and offered to the council as candidate
root questions; the council's own rules still decide which are asked.
"""

import json
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

API = "https://en.wikipedia.org/w/api.php"
MIN_CHARS = 60
MAX_CHARS = 280
MAX_ITEMS = 40


def day_page(day):
    return f"Portal:Current_events/{day.year}_{day.strftime('%B')}_{day.day}"


def page_url(day):
    return API + "?" + urllib.parse.urlencode({"action": "parse", "page": day_page(day), "prop": "wikitext", "format": "json", "formatversion": "2"})


def clean_wikitext(line):
    text = re.sub(r"<!--.*?-->", "", line)
    text = re.sub(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", "", text)
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    citations = [{"url": url, "label": re.sub(r"'{2,}", "", label).strip("() ")} for url, label in re.findall(r"\[(https?://\S+)\s+([^\]]+)\]", text)]
    sources = [item["label"] for item in citations]
    text = re.sub(r"\[https?://\S+(?:\s+[^\]]*)?\]", "", text)
    text = re.sub(r"\[\[([^\]|]*)\|([^\]]*)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"'{2,}", "", text)
    text = text.replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text).strip(" .;:")
    clean_wikitext.last_citations = citations
    return text, [re.sub(r"\s+", " ", item).strip("() ") for item in sources]


def items_from_wikitext(wikitext, day=None):
    """Sourced event sentences from a day page: the deepest bullets, not the topic headers."""
    out, seen = [], set()
    for raw in str(wikitext or "").splitlines():
        if not raw.startswith("*"):
            continue
        body = raw.lstrip("*").strip()
        text, sources = clean_wikitext(body)
        if not (MIN_CHARS <= len(text) <= MAX_CHARS) or not re.search(r"[a-z]", text):
            continue
        if not sources:
            continue  # a topic header or an unsourced fragment; only cited events are candidates
        key = text.lower()[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append({"text": text + ".", "sources": sources[:3], "citations": list(getattr(clean_wikitext, "last_citations", []))[:3],
                    "day": day.isoformat() if day else None})
        if len(out) >= MAX_ITEMS:
            break
    return out


def recent_items(fetch_json, now=None, days=3):
    """Items from the last ``days`` day pages, newest first; a missing page is skipped."""
    now = now or datetime.now(timezone.utc)
    items = []
    for offset in range(days):
        day = (now - timedelta(days=offset)).date()
        try:
            payload = fetch_json(page_url(day))
        except Exception:  # noqa: BLE001 - one bad day never blocks the rest
            continue
        wikitext = (payload.get("parse") or {}).get("wikitext") if isinstance(payload, dict) else ""
        items.extend(items_from_wikitext(wikitext, day))
    return items


def root_question(item):
    """The council's root for an item: check it, and look for a different figure or date.
    The outlet that first reported it is the line's seed source, not part of the question,
    so its name never steers the search."""
    text = str(item.get("text", "")).rstrip(".")
    return f"Do independent public sources confirm that {text}, and does any give a different figure, date, or account?"[:300]


def seed_for(item):
    """The claim and the outlet page the day's record cited for it: the line's first source, to be re-fetched and quoted."""
    citations = [c for c in (item.get("citations") or []) if str(c.get("url", "")).startswith("https://")]
    if not citations:
        return None
    return {"claim": str(item.get("text", "")).strip()[:300], "url": str(citations[0]["url"])[:500], "outlet": str(citations[0].get("label", ""))[:80]}


def stream_questions(items, cycle, limit=8):
    """A rotation of candidate roots keyed to the cycle, so every cycle sees a different slice."""
    if not items:
        return []
    start = int(cycle) % len(items)
    ordered = items[start:] + items[:start]
    return [(root_question(item), "stream:wikipedia-current-events" + (f"/{item.get('day')}" if item.get("day") else ""), seed_for(item))
            for item in ordered[:limit]]


if __name__ == "__main__":
    import sys
    try:
        from scripts.tool_broker import fetch, RESEARCH_MAX_BYTES
    except ImportError:
        from tool_broker import fetch, RESEARCH_MAX_BYTES
    found = recent_items(lambda url: json.loads(fetch(url, RESEARCH_MAX_BYTES)))
    print(json.dumps({"items": len(found), "sample": found[:5], "questions": stream_questions(found, int(sys.argv[1]) if len(sys.argv) > 1 else 0, 3)}, indent=1))
