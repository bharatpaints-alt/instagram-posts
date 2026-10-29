"""Niche trend finder: recent high-view YouTube Shorts for the client's niche -> one angle + shot list.

Uses the YouTube Data API v3 (YOUTUBE_API_KEY, free quota: search = 100 units, ~100 searches/day).
Without a key it still works: Claude picks the angle from season/festival knowledge alone (marked source="no-youtube").
"""
import datetime as dt
import os
import urllib.parse

from .common import http_json
from .llm import ask_json

YT = "https://www.googleapis.com/youtube/v3/"


def youtube_trending(queries, region="IN", days=14, per_query=8):
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        return []
    after = (dt.datetime.utcnow() - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids, seen = [], set()
    for q in queries:
        params = {"part": "snippet", "q": q, "type": "video", "videoDuration": "short", "order": "viewCount",
                  "publishedAfter": after, "regionCode": region, "relevanceLanguage": "hi", "maxResults": per_query,
                  "key": key}
        for it in http_json(YT + "search?" + urllib.parse.urlencode(params)).get("items", []):
            vid = it["id"]["videoId"]
            if vid not in seen:
                seen.add(vid)
                ids.append((vid, q))
    if not ids:
        return []
    stats = {}
    for i in range(0, len(ids), 50):
        chunk = ",".join(v for v, _ in ids[i:i + 50])
        r = http_json(YT + "videos?" + urllib.parse.urlencode({"part": "snippet,statistics", "id": chunk, "key": key}))
        for it in r.get("items", []):
            stats[it["id"]] = it
    out = []
    for vid, q in ids:
        it = stats.get(vid)
        if not it:
            continue
        out.append({"query": q, "title": it["snippet"]["title"], "channel": it["snippet"]["channelTitle"],
                    "published": it["snippet"]["publishedAt"][:10],
                    "views": int(it["statistics"].get("viewCount", 0)), "url": f"https://youtube.com/shorts/{vid}"})
    return sorted(out, key=lambda x: -x["views"])[:25]


SYSTEM = """You plan one Instagram Reel a day for a small local business in India.
Pick ONE angle that is trending now (season, festival, weather, what the YouTube list shows) AND fits this business.
Then list 2-3 concrete shots the owner can take today on a phone (what, where, how long, from where), vertical 9:16.
Only use the business facts given. Write trend_line and shots in simple Hinglish (Roman script)."""


def todays_angle(client, today=None):
    today = today or dt.date.today()
    vids = youtube_trending(client["niche"]["youtube_queries"], client["niche"].get("region", "IN"))
    lines = [f"Today: {today:%d %B %Y}. Business: {client['name']}, {client.get('city', '')}.",
             "Facts:\n- " + "\n- ".join(client["facts"]),
             f"Niche: {client['niche']['description']}"]
    if vids:
        lines.append("Top recent YouTube Shorts in this niche (views, title):\n" +
                     "\n".join(f"{v['views']:>9,}  {v['title']}  [{v['query']}]" for v in vids))
    lines.append('Return {"trend_line": "...", "angle": "...", "why": "...", '
                 '"shots": ["...", "..."], "inspired_by": ["<youtube url>", ...]}')
    res = ask_json(SYSTEM, ["\n\n".join(lines)], max_tokens=1200)
    res["source"] = "youtube" if vids else "no-youtube"
    res["youtube"] = vids[:5]
    return res
