#!/usr/bin/env python3
"""
게임 트렌드 대시보드 데이터 수집기
- YouTube 인기 게임 영상 (한국/미국/캐나다/일본)
- Bilibili 게임 구역 랭킹 (중국)
- 국내외 게임 뉴스 RSS
결과를 data.json 으로 저장. 소스 하나가 실패해도 나머지는 계속 수집.
사용법: YOUTUBE_API_KEY 환경변수 설정 후  python collector.py
"""
import json
import os
import sys
import time
import html
import re
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

# 수집 대상 YouTube 지역 (ISO 3166-1 alpha-2)
YT_REGIONS = {
    "KR": "한국",
    "US": "미국",
    "CA": "캐나다",
    "JP": "일본",
}
YT_MAX_RESULTS = 20  # 지역당 영상 수

# 뉴스 RSS 피드 (실패해도 건너뜀)
NEWS_FEEDS = [
    # 국내
    {"source": "디스이즈게임", "lang": "ko", "url": "https://www.thisisgame.com/rss/rss.xml"},
    {"source": "게임메카", "lang": "ko", "url": "https://www.gamemeca.com/rss.php"},
    {"source": "인벤", "lang": "ko", "url": "https://www.inven.co.kr/rss/webzine/news/"},
    # 해외
    {"source": "IGN", "lang": "en", "url": "https://feeds.feedburner.com/ign/games-all"},
    {"source": "GameSpot", "lang": "en", "url": "https://www.gamespot.com/feeds/game-news/"},
    {"source": "Eurogamer", "lang": "en", "url": "https://www.eurogamer.net/feed"},
    {"source": "GamesIndustry.biz", "lang": "en", "url": "https://www.gamesindustry.biz/feed"},
    {"source": "PC Gamer", "lang": "en", "url": "https://www.pcgamer.com/rss/"},
    # 일본
    {"source": "4Gamer", "lang": "ja", "url": "https://www.4gamer.net/rss/index.xml"},
]
NEWS_PER_FEED = 15


def http_get(url, headers=None, timeout=15):
    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GameTrendDashboard/1.0"}
    if headers:
        h.update(headers)
    req = Request(url, headers=h)
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def collect_youtube():
    """지역별 게임 카테고리(20) 인기 영상"""
    if not YOUTUBE_API_KEY:
        print("[youtube] YOUTUBE_API_KEY 없음 - 건너뜀")
        return {}
    out = {}
    for code, name in YT_REGIONS.items():
        try:
            params = urlencode({
                "part": "snippet,statistics",
                "chart": "mostPopular",
                "videoCategoryId": "20",
                "regionCode": code,
                "maxResults": YT_MAX_RESULTS,
                "key": YOUTUBE_API_KEY,
            })
            data = json.loads(http_get(
                f"https://www.googleapis.com/youtube/v3/videos?{params}"))
            videos = []
            for item in data.get("items", []):
                sn = item.get("snippet", {})
                st = item.get("statistics", {})
                thumbs = sn.get("thumbnails", {})
                thumb = (thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
                videos.append({
                    "id": item.get("id", ""),
                    "title": sn.get("title", ""),
                    "channel": sn.get("channelTitle", ""),
                    "publishedAt": sn.get("publishedAt", ""),
                    "views": int(st.get("viewCount", 0)),
                    "thumbnail": thumb,
                    "url": f"https://www.youtube.com/watch?v={item.get('id','')}",
                })
            out[code] = {"name": name, "videos": videos}
            print(f"[youtube] {code} {len(videos)}개")
        except Exception as e:
            print(f"[youtube] {code} 실패: {e}")
        time.sleep(0.3)
    return out


def collect_bilibili():
    """Bilibili 게임 구역 인기 랭킹 (중국 트렌드 대용)"""
    headers = {
        "Referer": "https://www.bilibili.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    }
    endpoints = [
        # 게임 구역(rid=4) 랭킹
        "https://api.bilibili.com/x/web-interface/ranking/v2?rid=4&type=all",
        # 폴백: 전체 인기
        "https://api.bilibili.com/x/web-interface/popular?ps=50",
    ]
    for url in endpoints:
        try:
            data = json.loads(http_get(url, headers=headers))
            if data.get("code") != 0:
                print(f"[bilibili] 응답 코드 {data.get('code')} - 다음 엔드포인트 시도")
                continue
            items = data.get("data", {}).get("list", [])[:20]
            videos = []
            for v in items:
                stat = v.get("stat", {})
                videos.append({
                    "id": v.get("bvid", ""),
                    "title": v.get("title", ""),
                    "channel": (v.get("owner") or {}).get("name", ""),
                    "views": int(stat.get("view", 0)),
                    "thumbnail": (v.get("pic") or "").replace("http://", "https://"),
                    "url": f"https://www.bilibili.com/video/{v.get('bvid','')}",
                })
            if videos:
                print(f"[bilibili] {len(videos)}개")
                return videos
        except Exception as e:
            print(f"[bilibili] 실패: {e}")
    return []


def _text(el, *tags):
    for t in tags:
        for child in el.iter():
            tag = child.tag.split('}')[-1]
            if tag == t and child.text:
                return child.text.strip()
    return ""


def _parse_date(s):
    """RFC822 / ISO8601 파싱해서 ISO 문자열 반환"""
    from email.utils import parsedate_to_datetime
    if not s:
        return ""
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except Exception:
        return ""


def collect_news():
    articles = []
    for feed in NEWS_FEEDS:
        try:
            raw = http_get(feed["url"])
            root = ET.fromstring(raw)
            # RSS <item> 또는 Atom <entry>
            entries = [e for e in root.iter() if e.tag.split('}')[-1] in ("item", "entry")]
            count = 0
            for e in entries[:NEWS_PER_FEED]:
                title = _text(e, "title")
                link = _text(e, "link")
                if not link:  # Atom: <link href="...">
                    for child in e.iter():
                        if child.tag.split('}')[-1] == "link" and child.get("href"):
                            link = child.get("href")
                            break
                date = _parse_date(_text(e, "pubDate", "published", "updated", "date"))
                if title and link:
                    articles.append({
                        "source": feed["source"],
                        "lang": feed["lang"],
                        "title": html.unescape(re.sub(r"<[^>]+>", "", title)),
                        "url": link,
                        "publishedAt": date,
                    })
                    count += 1
            print(f"[news] {feed['source']} {count}개")
        except Exception as e:
            print(f"[news] {feed['source']} 실패: {e}")
        time.sleep(0.2)
    articles.sort(key=lambda a: a.get("publishedAt") or "", reverse=True)
    return articles


def main():
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "youtube": collect_youtube(),
        "bilibili": collect_bilibili(),
        "news": collect_news(),
    }
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    n_yt = sum(len(v["videos"]) for v in data["youtube"].values())
    print(f"완료: YouTube {n_yt}개 / Bilibili {len(data['bilibili'])}개 / 뉴스 {len(data['news'])}개 -> data.json")
    # 전부 비어있으면 실패 처리 (Actions 알림용)
    if not (n_yt or data["bilibili"] or data["news"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
