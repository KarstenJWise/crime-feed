"""Live RSS feed of CrimeRadar incidents near home, built fresh on every request."""
import html
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler
from xml.sax.saxutils import escape

PAGES = ["provo-ut", "orem-ut"]
ZIPS = {"84604", "84601", "84602", "84606", "84097", "84057", "84058"}
BASE = "https://www.crimeradar.us"
UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"

ANCHOR = re.compile(r'<a\s[^>]*?href="(/(?:%s)/[^"]+)"[^>]*>(.*?)</a>' % "|".join(PAGES), re.S)
H2 = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S)
ADDR = re.compile(r'<div class="mt-3[^"]*">(.*?)</div>', re.S)
CAT = re.compile(r'<span class="inline-flex[^"]*">.*?<span>(.*?)</span>', re.S)
ZIP = re.compile(r"\b(\d{5})\b")


def text(fragment):
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def fetch(page):
    req = urllib.request.Request(f"{BASE}/{page}?_={int(time.time())}",
                                 headers={"User-Agent": UA, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return r.read().decode("utf-8", "replace")


def parse(page_html):
    items = []
    for href, body in ANCHOR.findall(page_html):
        slug = href.rsplit("/", 1)[-1]
        parts = slug.split("_")
        title, addr, cat = H2.search(body), ADDR.search(body), CAT.search(body)
        if len(parts) < 3 or not parts[1].isdigit() or not title:
            continue
        address = text(addr.group(1)) if addr else ""
        zips = ZIP.findall(address)
        if zips and zips[-1] not in ZIPS:   # has a ZIP and it's not ours: skip
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


def build_feed():
    with ThreadPoolExecutor(len(PAGES)) as pool:
        pages = list(pool.map(lambda p: _safe(fetch, p), PAGES))
    if not any(pages):
        raise RuntimeError("could not reach crimeradar.us")
    seen = {}
    for page_html in pages:
        for it in parse(page_html or ""):
            seen[it["id"]] = it
    items = sorted(seen.values(), key=lambda it: it["ts"], reverse=True)

    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0"><channel>',
           "<title>CrimeRadar near home</title>", f"<link>{BASE}/provo-ut</link>",
           "<description>Provo/Orem incidents filtered by ZIP</description>",
           f"<lastBuildDate>{format_datetime(datetime.now(timezone.utc))}</lastBuildDate>"]
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
            "</item>")
    out.append("</channel></rss>")
    return "\n".join(out) + "\n"


def _safe(fn, arg):
    try:
        return fn(arg)
    except Exception:
        return None


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            body, status = build_feed().encode(), 200
        except Exception as e:
            body, status = f"error: {e}".encode(), 502
        self.send_response(status)
        self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
        self.send_header("Cache-Control", "public, s-maxage=60")
        self.end_headers()
        self.wfile.write(body)
