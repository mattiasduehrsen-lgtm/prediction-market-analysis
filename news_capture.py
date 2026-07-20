"""Esports news-event capture — forward data for the news-lag edge (2026-07-20).

The retrospective wiki study returned n=0: July roster edits land days from
matches (transfer window) and match-day STAND-IN news rarely hits the wiki in
time. Verdict: the lag question needs FORWARD capture from fast channels,
timestamped at observation, running alongside the book capture that already
logs every CS2/LoL market. After 2-4 weeks: join news events x books and
measure the market's reaction lag with real timestamps.

Channels (all free, polite):
  - HLTV news RSS (~2 min poll)              fast channel for CS2 roster news
  - Liquipedia recentchanges, CS2+LoL wikis  (~5 min poll, 1 req/2s etiquette)
Each item logged once (dedup by id/url) with BOTH its own timestamp and our
observation timestamp — the pair is the whole point (channel latency is part
of what we're measuring).

Run: .venv\\Scripts\\python.exe -u news_capture.py   (via watch_news_capture.bat)
Output: output/news_capture/news_YYYYMMDD.jsonl (tiny; text only)
"""
from __future__ import annotations
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "output" / "news_capture"
OUT_DIR.mkdir(parents=True, exist_ok=True)

HLTV_RSS = "https://www.hltv.org/rss/news"
WIKIS = {"cs2": "https://liquipedia.net/counterstrike/api.php",
         "lol": "https://liquipedia.net/leagueoflegends/api.php"}
HLTV_EVERY = 120.0
WIKI_EVERY = 300.0
ROSTER_RE = re.compile(
    r"roster|stand-?in|substitut|benched|inactive|loan|transfer|join|leav|sign"
    r"|part ways|removed|added|coach|lineup|miss|absen|illness|sick|visa|forfeit"
    r"|withdraw|replace", re.I)

S = requests.Session()
S.headers["User-Agent"] = "prediction-market-analysis news-capture (read-only research)"
seen: set[str] = set()


def write(rows):
    if not rows:
        return
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    with (OUT_DIR / f"news_{day}.jsonl").open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def poll_hltv(now):
    rows = []
    try:
        r = S.get(HLTV_RSS, timeout=15)
        if r.status_code != 200:
            return rows
        root = ET.fromstring(r.content)
        for item in root.iter("item"):
            g = lambda tag: (item.findtext(tag) or "").strip()
            key = g("guid") or g("link")
            if not key or key in seen:
                continue
            seen.add(key)
            try:
                pub = parsedate_to_datetime(g("pubDate")).timestamp()
            except Exception:
                pub = None
            title = g("title")
            rows.append({"obs_ts": round(now, 1), "src": "hltv", "id": key,
                         "item_ts": pub, "title": title,
                         "rosterish": bool(ROSTER_RE.search(title))})
    except Exception as e:
        print(f"[news] hltv poll error: {e}")
    return rows


def poll_wiki(game, api, now, since_iso):
    rows = []
    try:
        r = S.get(api, timeout=20, params={
            "action": "query", "list": "recentchanges", "format": "json",
            "rcend": since_iso, "rcprop": "title|timestamp|comment|ids",
            "rcnamespace": 0, "rclimit": 200})
        if r.status_code != 200:
            return rows
        for c in r.json().get("query", {}).get("recentchanges", []):
            key = f"{game}:{c.get('rcid')}"
            if key in seen:
                continue
            seen.add(key)
            txt = f"{c.get('title', '')} {c.get('comment', '')}"
            try:
                its = datetime.fromisoformat(
                    c.get("timestamp", "").replace("Z", "+00:00")).timestamp()
            except Exception:
                its = None
            rows.append({"obs_ts": round(now, 1), "src": f"liqui_{game}",
                         "id": key, "item_ts": its,
                         "title": c.get("title", ""),
                         "comment": (c.get("comment") or "")[:120],
                         "rosterish": bool(ROSTER_RE.search(txt))})
    except Exception as e:
        print(f"[news] {game} wiki poll error: {e}")
    return rows


def main():
    print("[news-capture] start; hltv every 2min, wikis every 5min")
    last_hltv = last_wiki = 0.0
    n_total = 0
    while True:
        now = time.time()
        rows = []
        if now - last_hltv >= HLTV_EVERY:
            rows += poll_hltv(now)
            last_hltv = now
        if now - last_wiki >= WIKI_EVERY:
            since = datetime.fromtimestamp(now - 7200, timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            for game, api in WIKIS.items():
                rows += poll_wiki(game, api, time.time(), since)
                time.sleep(2.0)
            last_wiki = now
        write(rows)
        n_total += len(rows)
        if rows:
            hot = [r["title"][:60] for r in rows if r["rosterish"]]
            if hot:
                print(f"[news-capture] rosterish: {hot}")
        if len(seen) > 20000:
            seen.clear()
        time.sleep(15.0)


if __name__ == "__main__":
    main()
