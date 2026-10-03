#!/usr/bin/env python3
"""Build one RSS feed of CrimeRadar incidents near home.

Pulls the Provo and Orem city pages, keeps incidents whose address has one of
the ZIP codes below, merges them with what was seen before (so an incident
never disappears and reappears), and writes feed.xml.
"""
import html
import json
import os
import re
import sys
import time
import urllib.request
from email.utils import format_datetime
from datetime import datetime, timezone
from xml.sax.saxutils import escape

PAGES = ["provo-ut", "orem-ut"]
ZIPS = {"84604", "84601", "84602", "84606", "84097", "84057", "84058"}
BASE = "https://www.crimeradar.us"
STATE_FILE = "state.json"
FEED_FILE = "feed.xml"
KEEP = 40                 # newest incidents kept in the feed
MAX_AGE = 3 * 24 * 3600   # drop incidents older than 3 days

ANCHOR = re.compile(r'<a\s[^>]*?href="(/(?:%s)/[^"]+)"[^>]*>(.*?)</a>' % "|".join(PAGES), re.S)
H2 = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S)
ADDR = re.compile(r'<div class="mt-3[^"]*">(.*?)</div>', re.S)
CAT = re.compile(r'<span class="inline-flex[^"]*">.*?<span>(.*?)</span>', re.S)
ZIP = re.compile(r"\b(\d{5})\b")


def text(fragment):
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def fetch(page):
    req = urllib.request.Request(
        f"{BASE}/{page}?_={int(time.time())}",
        headers={
            "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse(page_html):
    items = []
    for href, body in ANCHOR.findall(page_html):
        slug = href.rsplit("/", 1)[-1]
        parts = slug.split("_")
        if len(parts) < 3 or not parts[1].isdigit():
            continue
        title = H2.search(body)
        addr = ADDR.search(body)
        cat = CAT.search(body)
        if not title or not addr:
            continue
        address = text(addr.group(1))
        zips = ZIP.findall(address)
        if not zips or zips[-1] not in ZIPS:
            continue
        items.append({
            "id": slug,
            "ts": int(parts[1]),
            "title": text(title.group(1)),
            "address": address,
            "category": text(cat.group(1)) if cat else "",
            "link": BASE + href,
        })
    return items


def build_rss(items):
    now = format_datetime(datetime.now(timezone.utc))
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0"><channel>',
        "<title>CrimeRadar near home</title>",
        f"<link>{BASE}/provo-ut</link>",
        "<description>Provo/Orem incidents filtered by ZIP</description>",
        f"<lastBuildDate>{now}</lastBuildDate>",
    ]
    for it in items:
        when = format_datetime(datetime.fromtimestamp(it["ts"], timezone.utc))
        out.append(
            "<item>"
            f"<title>{escape(it['title'])}</title>"
            f"<link>{escape(it['link'])}</link>"
            f'<guid isPermaLink="false">{escape(it["id"])}</guid>'
            f"<pubDate>{when}</pubDate>"
            f"<category>{escape(it['category'])}</category>"
            f"<description>{escape(it['address'])}</description>"
            "</item>"
        )
    out.append("</channel></rss>")
    return "\n".join(out) + "\n"


def main():
    seen = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            seen = {it["id"]: it for it in json.load(f)}

    fetched = 0
    for page in PAGES:
        try:
            for it in parse(fetch(page)):
                seen[it["id"]] = it
            fetched += 1
        except Exception as e:  # one bad page shouldn't wipe the feed
            print(f"warning: {page}: {e}", file=sys.stderr)
    if fetched == 0:
        sys.exit("could not fetch any page")

    cutoff = time.time() - MAX_AGE
    items = sorted((it for it in seen.values() if it["ts"] >= cutoff),
                   key=lambda it: it["ts"], reverse=True)[:KEEP]

    with open(STATE_FILE, "w") as f:
        json.dump(items, f, indent=1)
    with open(FEED_FILE, "w") as f:
        f.write(build_rss(items))
    print(f"{len(items)} incidents in feed")


if __name__ == "__main__":
    main()
