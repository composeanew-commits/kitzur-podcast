#!/usr/bin/env python3
"""
Builds a podcast RSS feed (feed.xml) from the shul's shiurim page.
Runs automatically every few hours on GitHub (see .github/workflows).
The feed points straight at the audio files already on zntshul.org,
so nothing is ever downloaded or uploaded by hand.
"""

import json
import os
import re
import sys
from datetime import date as Date, datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

# ============ EDIT THESE (only if you want to) ============
SHOW_TITLE = "Kitzur Shulchan Aruch with Rabbi Shmuel Weiner"
SHOW_DESCRIPTION = (
    "A short daily shiur on the Kitzur Shulchan Aruch with Rabbi Shmuel Weiner "
    "of Khal Zichron Nosson Tzvi in Jerusalem. Each episode takes a few simanim and "
    "explains the halachos clearly and practically, in about 5 to 20 minutes. "
    "The series starts at the beginning, with the halachos of waking up and getting "
    "dressed, and moves through the day: washing, tefilin, tzitzis, mezuzah, brachos, "
    "and tefillah."
)
AUTHOR = "Rabbi Shmuel Weiner"
OWNER_EMAIL = "composeanew@gmail.com"   # <-- put your real email here (Apple/Spotify use it to verify)
LANGUAGE = "en"
COVER_FILE = "cover.jpg"
EPISODE_DESCRIPTION = (
    "{title}\n\nDaily Kitzur Shulchan Aruch shiur by Rabbi Shmuel Weiner, "
    "Khal Zichron Nosson Tzvi, Jerusalem."
)
# ==========================================================

SOURCE_PAGE = "https://zntshul.org/shiurim-2/"
FEED_FILE = Path("feed.xml")
STATE_FILE = Path("episodes.json")

_repo = os.environ.get("GITHUB_REPOSITORY")  # e.g. "dovid/kitzur-podcast"
if _repo:
    _owner, _name = _repo.split("/", 1)
    BASE_URL = f"https://{_owner.lower()}.github.io/{_name}"
else:
    BASE_URL = "https://YOURNAME.github.io/YOURREPO"

AUDIO_EXT = (".mp3", ".m4a", ".wav", ".aac")
MIME = {".mp3": "audio/mpeg", ".m4a": "audio/x-m4a", ".wav": "audio/wav", ".aac": "audio/aac"}
TITLE_RE = re.compile(r"^\s*(\d{1,3})\s+Kitzur Shulchan Aruch\b.*", re.I)
DATE_RE = re.compile(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),\s+(\d{4})")
TIMES_START_RE = re.compile(r"^((?:\d{1,2}:\d{2}(?::\d{2})?\s*)+)")
TIME_TOKEN_RE = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?")
HEADERS = {"User-Agent": "Mozilla/5.0 (podcast feed builder)"}

ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ATOM = "http://www.w3.org/2005/Atom"
ET.register_namespace("itunes", ITUNES)
ET.register_namespace("atom", ATOM)


def parse_page(html, base_url=SOURCE_PAGE):
    """Walk the page in order: title line -> date -> duration -> audio link = one episode."""
    soup = BeautifulSoup(html, "html.parser")
    episodes = []
    title = number = date = duration = None
    for node in soup.descendants:
        if isinstance(node, NavigableString):
            text = " ".join(str(node).split())
            if not text:
                continue
            m = TITLE_RE.match(text)
            if m:
                title, number, date, duration = text, int(m.group(1)), None, None
                continue
            if title:
                if date is None:
                    d = DATE_RE.search(text)
                    if d:
                        try:
                            date = datetime.strptime(f"{d.group(1)} {d.group(2)} {d.group(3)}", "%b %d %Y").date()
                        except ValueError:
                            pass
                t = TIMES_START_RE.match(text)
                if t:
                    duration = TIME_TOKEN_RE.findall(t.group(1))[-1]  # last time shown = total length
        elif isinstance(node, Tag) and node.name == "a":
            href = node.get("href", "")
            if title and href.lower().split("?")[0].endswith(AUDIO_EXT):
                episodes.append({
                    "number": number,
                    "title": title,
                    "date": date.isoformat() if date else "",
                    "duration": duration or "",
                    "url": urljoin(base_url, href),
                })
                title = number = date = duration = None
    return episodes


def probe_size(url):
    """File size in bytes (podcast apps like to know it). 0 if unknown."""
    try:
        r = requests.head(url, headers=HEADERS, allow_redirects=True, timeout=30)
        size = int(r.headers.get("Content-Length", 0))
        if size:
            return size
    except Exception:
        pass
    try:
        with requests.get(url, headers=HEADERS, stream=True, timeout=30) as r:
            return int(r.headers.get("Content-Length", 0))
    except Exception:
        return 0


def clean_title(title):
    return re.sub(r"^\s*\d{1,3}\s+", "", title).strip()


def sub(parent, tag, text=None, **attrs):
    el = ET.SubElement(parent, tag, attrs)
    if text is not None:
        el.text = text
    return el


def build_feed(episodes):
    rss = ET.Element("rss", version="2.0")
    ch = ET.SubElement(rss, "channel")
    sub(ch, "title", SHOW_TITLE)
    sub(ch, "link", SOURCE_PAGE)
    sub(ch, "description", SHOW_DESCRIPTION)
    sub(ch, "language", LANGUAGE)
    sub(ch, "lastBuildDate", format_datetime(datetime.now(timezone.utc)))
    sub(ch, f"{{{ATOM}}}link", href=f"{BASE_URL}/feed.xml", rel="self", type="application/rss+xml")
    sub(ch, f"{{{ITUNES}}}author", AUTHOR)
    sub(ch, f"{{{ITUNES}}}summary", SHOW_DESCRIPTION)
    owner = sub(ch, f"{{{ITUNES}}}owner")
    sub(owner, f"{{{ITUNES}}}name", AUTHOR)
    sub(owner, f"{{{ITUNES}}}email", OWNER_EMAIL)
    sub(ch, f"{{{ITUNES}}}image", href=f"{BASE_URL}/{COVER_FILE}")
    cat = ET.SubElement(ch, f"{{{ITUNES}}}category", {"text": "Religion & Spirituality"})
    ET.SubElement(cat, f"{{{ITUNES}}}category", {"text": "Judaism"})
    sub(ch, f"{{{ITUNES}}}explicit", "false")
    sub(ch, f"{{{ITUNES}}}type", "episodic")

    for e in sorted(episodes, key=lambda e: (e["date"], e["number"]), reverse=True):
        title = clean_title(e["title"])
        item = ET.SubElement(ch, "item")
        sub(item, "title", title)
        sub(item, "description", EPISODE_DESCRIPTION.format(title=title))
        ext = Path(e["url"].split("?")[0]).suffix.lower()
        sub(item, "enclosure", url=e["url"], length=str(e.get("size", 0)), type=MIME.get(ext, "audio/mpeg"))
        sub(item, "guid", e["url"], isPermaLink="false")
        if e["date"]:
            d = Date.fromisoformat(e["date"])
        else:
            d = Date.fromisoformat(e["first_seen"])
        sub(item, "pubDate", format_datetime(datetime(d.year, d.month, d.day, 8, 0, tzinfo=timezone.utc)))
        if e.get("duration"):
            sub(item, f"{{{ITUNES}}}duration", e["duration"])
        sub(item, f"{{{ITUNES}}}episode", str(e["number"]))
        sub(item, f"{{{ITUNES}}}explicit", "false")

    ET.indent(rss)
    ET.ElementTree(rss).write(FEED_FILE, encoding="utf-8", xml_declaration=True)


def main():
    r = requests.get(SOURCE_PAGE, headers=HEADERS, timeout=30)
    r.raise_for_status()
    found = parse_page(r.text)
    if not found:
        sys.exit("No shiurim found on the page - leaving the feed unchanged. "
                 "The site layout may have changed.")

    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    today = datetime.now(timezone.utc).date().isoformat()
    added = 0
    for e in found:
        if e["url"] not in state:
            e["size"] = probe_size(e["url"])
            e["first_seen"] = today
            state[e["url"]] = e
            added += 1
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    build_feed(list(state.values()))
    print(f"{added} new episode(s) added. {len(state)} total in the feed.")


if __name__ == "__main__":
    main()
