#!/usr/bin/env python3
"""
게임 트렌드 대시보드 데이터 수집기
- YouTube 인기 게임 영상 (한국/미국/캐나다/일본)
- Bilibili 게임 구역 랭킹 (중국)
- 국내외 게임 뉴스 RSS
- Gemini API로 인사이트/한글요약 생성 (키 있을 때만)
결과를 data.json 으로 저장. 소스 하나가 실패해도 나머지는 계속 수집.
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
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")  # 없으면 요약 생략

YT_REGIONS = {
    "KR": "한국",
    "US": "미국",
    "CA": "캐나다",
    "JP": "일본",
}
YT_MAX_RESULTS = 20

NEWS_FEEDS = [
    {"source": "디스이즈게임", "lang": "ko", "url": "https://www.thisisgame.com/rss/rss.xml"},
    {"source": "게임메카", "lang": "ko", "url": "https://www.gamemeca.com/rss.php"},
    {"source": "인벤", "lang": "ko", "url": "https://www.inven.co.kr/rss/webzine/news/"},
    {"source": "IGN", "lang": "en", "url": "https://feeds.feedburner.com/ign/games-all"},
    {"source": "GameSpot", "lang": "en", "url": "https://www.gamespot.com/feeds/game-news/"},
    {"source": "Eurogamer", "lang": "en", "url": "https://www.eurogamer.net/feed"},
    {"source": "GamesIndustry.biz", "lang": "en", "url": "https://www.gamesindustry.biz/feed"},
    {"source": "PC Gamer", "lang": "en", "url": "https://www.pcgamer.com/rss/"},
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


def http_post_json(url, payload, timeout=60):
    req = Request(url, data=json.dumps(payload).encode("utf-8"),
                  headers={"Content-Type": "application/json",
                           "User-Agent": "GameTrendDashboard/1.0"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def collect_youtube():
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
                "https://www.googleapis.com/youtube/v3/videos?" + params))
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
                    "url": "https://www.youtube.com/watch?v=" + item.get("id", ""),
                })
            out[code] = {"name": name, "videos": videos}
            print("[youtube] " + code + " " + str(len(videos)) + "개")
        except Exception as e:
            print("[youtube] " + code + " 실패: " + str(e))
        time.sleep(0.3)
    return out


def collect_bilibili():
    headers = {
        "Referer": "https://www.bilibili.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    }
    endpoints = [
        "https://api.bilibili.com/x/web-interface/ranking/v2?rid=4&type=all",
        "https://api.bilibili.com/x/web-interface/popular?ps=50",
    ]
    for url in endpoints:
        try:
            data = json.loads(http_get(url, headers=headers))
            if data.get("code") != 0:
                print("[bilibili] 응답 코드 " + str(data.get("code")) + " - 다음 엔드포인트 시도")
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
                    "url": "https://www.bilibili.com/video/" + v.get("bvid", ""),
                })
            if videos:
                print("[bilibili] " + str(len(videos)) + "개")
                return videos
        except Exception as e:
            print("[bilibili] 실패: " + str(e))
    return []


def _text(el, *tags):
    for t in tags:
        for child in el.iter():
            tag = child.tag.split('}')[-1]
            if tag == t and child.text:
                return child.text.strip()
    return ""


def _parse_date(s):
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
            entries = [e for e in root.iter() if e.tag.split('}')[-1] in ("item", "entry")]
            count = 0
            for e in entries[:NEWS_PER_FEED]:
                title = _text(e, "title")
                link = _text(e, "link")
                if not link:
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
            print("[news] " + feed["source"] + " " + str(count) + "개")
        except Exception as e:
            print("[news] " + feed["source"] + " 실패: " + str(e))
        time.sleep(0.2)
    articles.sort(key=lambda a: a.get("publishedAt") or "", reverse=True)
    return articles


def generate_insights(data):
    """Gemini 무료 API로 인사이트/한글요약 생성. 키 없거나 실패 시 조용히 생략."""
    if not GEMINI_API_KEY:
        print("[insight] GEMINI_API_KEY 없음 - 건너뜀")
        return
    blocks = []
    for code, r in data.get("youtube", {}).items():
        titles = [v["title"] for v in r.get("videos", [])[:12]]
        if titles:
            blocks.append("### " + r["name"] + "(" + code + ") YouTube 인기 영상\n" + "\n".join(titles))
    if data.get("bilibili"):
        blocks.append("### 중국(CN) Bilibili 인기 영상\n" +
                      "\n".join(v["title"] for v in data["bilibili"][:12]))
    ko_titles = [a["title"] for a in data.get("news", []) if a["lang"] == "ko"][:25]
    if ko_titles:
        blocks.append("### 한국 게임 뉴스 제목\n" + "\n".join(ko_titles))
    foreign = [(i, a) for i, a in enumerate(data.get("news", [])) if a["lang"] != "ko"][:40]
    if foreign:
        blocks.append("### 해외 게임 뉴스 제목 (번호: 제목)\n" +
                      "\n".join(str(i) + ": (" + a["source"] + ") " + a["title"] for i, a in foreign))
    if not blocks:
        print("[insight] 요약할 데이터 없음 - 건너뜀")
        return

    prompt = (
        "너는 게임 업계 애널리스트다. 아래는 오늘 수집된 지역별 YouTube/Bilibili 인기 게임 영상 제목과 게임 뉴스 제목이다.\n\n"
        + "\n\n".join(blocks) +
        "\n\n다음 JSON 형식으로만 답하라(코드블록 없이):\n"
        "{\n"
        ' "highlights": ["오늘 게임 업계에서 주목할 핵심 포인트 3~5개, 각 한 문장, 한국어"],\n'
        ' "regional": {\n'
        '  "KR": "한국에서 지금 뜨는 게임/화제 한두 문장",\n'
        '  "NA": "북미(미국·캐나다)에서 뜨는 게임/화제 한두 문장",\n'
        '  "JP": "일본에서 뜨는 게임/화제 한두 문장",\n'
        '  "CN": "중국(Bilibili)에서 뜨는 게임/화제 한두 문장",\n'
        '  "common": "여러 지역에서 공통적으로 뜨는 게임이나 트렌드 한두 문장"\n'
        " },\n"
        ' "translations": {"뉴스번호": "해당 해외 기사 제목의 자연스러운 한국어 한줄 요약"}\n'
        "}\n"
        "translations는 위 해외 뉴스 번호 전부를 포함하라. 데이터가 부족한 지역은 \"데이터 부족\"이라고 써라."
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "response_mime_type": "application/json"},
    }
    from urllib.error import HTTPError
    # 사용 가능한 모델을 API에서 직접 조회해 최신 flash 모델 자동 선택
    candidates = []
    try:
        ml = json.loads(http_get(
            "https://generativelanguage.googleapis.com/v1beta/models?key=" + GEMINI_API_KEY,
            timeout=30))
        flashes = [m["name"].split("/")[-1] for m in ml.get("models", [])
                   if "generateContent" in m.get("supportedGenerationMethods", [])
                   and "flash" in m["name"]
                   and not any(x in m["name"] for x in ("image", "tts", "live", "audio", "preview", "exp"))]
        flashes.sort(reverse=True)  # 버전 높은 순
        lite = [m for m in flashes if "lite" in m]
        full = [m for m in flashes if "lite" not in m]
        candidates = lite[:2] + full[:2]  # lite 우선(무료 한도가 더 넉넉)
        print("[insight] 사용 가능 flash 모델: " + ", ".join(flashes[:8]))
    except Exception as e:
        print("[insight] 모델 목록 조회 실패: " + str(e))
    candidates += ["gemini-flash-latest", "gemini-flash-lite-latest"]  # 폴백
    for model in dict.fromkeys(candidates):
        try:
            url = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   + model + ":generateContent?key=" + GEMINI_API_KEY)
            try:
                resp = http_post_json(url, payload)
            except HTTPError as he:
                if he.code == 429:  # 무료 티어 순간 제한 - 30초 후 1회 재시도
                    print("[insight] " + model + " 429 - 30초 후 재시도")
                    time.sleep(30)
                    resp = http_post_json(url, payload)
                else:
                    detail = ""
                    try:
                        detail = he.read().decode("utf-8", "ignore")[:300]
                    except Exception:
                        pass
                    raise Exception("HTTP " + str(he.code) + " " + detail)
            text = resp["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
            result = json.loads(text)
            data["insights"] = {
                "highlights": result.get("highlights", []),
                "regional": result.get("regional", {}),
                "model": model,
            }
            n_tr = 0
            for idx, ko in (result.get("translations") or {}).items():
                try:
                    data["news"][int(idx)]["title_ko"] = ko
                    n_tr += 1
                except (ValueError, IndexError):
                    pass
            print("[insight] " + model + " - 하이라이트 " + str(len(data["insights"]["highlights"])) + "개, 번역 " + str(n_tr) + "개")
            return
        except Exception as e:
            print("[insight] " + model + " 실패: " + str(e))
    print("[insight] 모든 모델 실패 - 요약 없이 진행")


def main():
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "youtube": collect_youtube(),
        "bilibili": collect_bilibili(),
        "news": collect_news(),
    }
    generate_insights(data)
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    n_yt = sum(len(v["videos"]) for v in data["youtube"].values())
    print("완료: YouTube " + str(n_yt) + "개 / Bilibili " + str(len(data["bilibili"])) + "개 / 뉴스 " + str(len(data["news"])) + "개 -> data.json")
    if not (n_yt or data["bilibili"] or data["news"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
