#!/usr/bin/env python3
"""
게임 트렌드 대시보드 데이터 수집기
- YouTube 인기 게임 영상 (한국/미국/캐나다/일본)
- Steam 동접 Top 100
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

WARNINGS = []  # 한도 초과 등 이상 상황 - 대시보드에 표시됨

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
    # 중국
    {"source": "GameLook", "lang": "zh", "url": "http://www.gamelook.com.cn/feed"},
]
NEWS_PER_FEED = 15
STEAM_TOP_N = 100


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
            if "403" in str(e):
                WARNINGS.append("YouTube API 무료 한도 초과 또는 키 문제 (" + code + " 수집 실패)")
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


def collect_steam_top():
    try:
        raw = json.loads(http_get(
            "https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/?format=json"))
        ranks = raw.get("response", {}).get("ranks", [])[:STEAM_TOP_N]
        prev = {}
        hp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "steam_history.json")
        try:
            hist = json.load(open(hp, encoding="utf-8"))
            for g in (hist[-1].get("games", []) if hist else []):
                prev[str(g.get("appid"))] = g
        except Exception:
            pass

        games = []
        for i, g in enumerate(ranks, 1):
            appid = str(g.get("appid", ""))
            try:
                cur = int(json.loads(http_get(
                    "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?"
                    + urlencode({"appid": appid}),
                    timeout=10)).get("response", {}).get("player_count", 0))
            except Exception:
                cur = 0
            old = prev.get(appid, {})
            old_cur = old.get("current")
            old_rank = old.get("rank")
            delta = cur - int(old_cur) if old_cur is not None else None
            name = g.get("name") or old.get("name")
            if not name:
                try:
                    detail = json.loads(http_get(
                        "https://store.steampowered.com/api/appdetails?"
                        + urlencode({"appids": appid, "filters": "basic"}),
                        timeout=10)).get(appid, {})
                    info = detail.get("data", {})
                    name = name or info.get("name")
                except Exception:
                    pass
            is_new_top100 = appid not in prev
            games.append({
                "rank": i,
                "appid": appid,
                "name": name or ("App " + appid),
                "image": "https://cdn.akamai.steamstatic.com/steam/apps/" + appid + "/header.jpg",
                "current": cur,
                "peak_today": int(g.get("peak_in_game", 0)),
                "last_week_rank": int(g.get("last_week_rank", 0)) or None,
                "weekly_rank_change": int(g.get("last_week_rank", 0)) - i if g.get("last_week_rank") else None,
                "delta_current": delta,
                "delta_percent": round(delta / old_cur * 100, 1) if old_cur else None,
                "delta_rank": int(old_rank) - i if old_rank else None,
                "is_new_top100": is_new_top100,
                "url": "https://store.steampowered.com/app/" + appid,
            })
        print("[steam] " + str(len(games)) + "개")
        return {"games": games}
    except Exception as e:
        print("[steam] 실패: " + str(e))
        WARNINGS.append("Steam Top 100 수집 실패")
        return {"games": []}


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
    news_list = data.get("news", [])[:80]
    if news_list:
        blocks.append("### 오늘 게임 뉴스 제목 (번호: [언어] (매체) 제목)\n" +
                      "\n".join(str(i) + ": [" + a["lang"] + "] (" + a["source"] + ") " + a["title"]
                                for i, a in enumerate(news_list)))
    foreign_idx = [str(i) for i, a in enumerate(news_list) if a["lang"] != "ko"][:40]
    if foreign_idx:
        blocks.append("### 한국어 번역 필요한 뉴스 번호\n" + ", ".join(foreign_idx))
    # 지난 며칠 히스토리 (지속 트렌드 판단용)
    try:
        hp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.json")
        hist = json.load(open(hp, encoding="utf-8"))
        today = data.get("generated_at", "")[:10]
        prev = [h for h in hist if h.get("date") != today][-6:]
        if prev:
            lines = []
            for day in prev:
                for code, ts in day.get("regions", {}).items():
                    lines.append(day["date"] + " " + code + ": " + " | ".join(ts))
            blocks.append("### 지난 며칠간 지역별 인기 영상 TOP5 히스토리\n" + "\n".join(lines))
    except Exception:
        pass
    if not blocks:
        print("[insight] 요약할 데이터 없음 - 건너뜀")
        return

    # 워치리스트 (있으면 프롬프트에 포함)
    watch = {"context": "", "keywords": []}
    try:
        wp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.json")
        w = json.load(open(wp, encoding="utf-8"))
        watch["context"] = w.get("context", "")
        watch["keywords"] = [k for k in w.get("keywords", []) if k]
    except Exception:
        pass
    if watch["keywords"]:
        blocks.append("### 사용자 정보\n직군/관심: " + watch["context"] +
                      "\n워치리스트 키워드: " + ", ".join(watch["keywords"]))

    # prompt.txt가 있으면 분석 지침으로 사용 (자유롭게 편집 가능)
    intro = "너는 게임 업계 애널리스트다. 아래는 오늘 수집된 지역별 YouTube/Bilibili 인기 게임 영상 제목과 게임 뉴스 제목이다."
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt.txt")
        custom = open(p, encoding="utf-8").read().strip()
        if custom:
            intro = custom
    except Exception:
        pass
    prompt = (
        intro + "\n\n"
        + "\n\n".join(blocks) +
        "\n\n다음 JSON 형식으로만 답하라(코드블록 없이):\n"
        "{\n"
        ' "highlights": [{"text": "오늘 주목할 핵심 포인트 한 문장", "news_refs": [근거가 된 뉴스 번호들, 없으면 빈 배열]}],\n'
        ' "regional": {\n'
        '  "KR": {"summary": "한국에서 지금 뜨는 게임/화제 한두 문장", "tags": ["핵심 게임명/키워드 태그 2~5개"]},\n'
        '  "NA": {"summary": "북미(미국·캐나다)에서 뜨는 게임/화제 한두 문장", "tags": ["..."]},\n'
        '  "JP": {"summary": "일본에서 뜨는 게임/화제 한두 문장", "tags": ["..."]},\n'
        '  "CN": {"summary": "중국(Bilibili)에서 뜨는 게임/화제 한두 문장", "tags": ["..."]},\n'
        '  "common": {"summary": "여러 지역 공통 트렌드 한두 문장", "tags": ["..."]}\n'
        " },\n"
        ' "news_brief": {\n'
        '  "KR": {"summary": ["국내 게임 뉴스 핵심 1~3개, 각 한 문장"], "tags": ["핵심 태그 2~5개"]},\n'
        '  "NA": {"summary": ["북미/서구권 게임 뉴스 핵심 1~3개, 각 한 문장, 한국어"], "tags": ["..."]},\n'
        '  "JP": {"summary": ["일본 게임 뉴스 핵심 1~3개, 각 한 문장, 한국어"], "tags": ["..."]},\n'
        '  "CN": {"summary": ["중국 게임 뉴스 핵심 1~3개, 각 한 문장, 한국어"], "tags": ["..."]}\n'
        " },\n"
        ' "for_me": ["사용자 관점에서 주목할 만한, 데이터에서 직접 관찰된 사실과 그 맥락 2~3개, 각 한 문장"],\n'
        ' "watchlist": [{"keyword": "워치리스트 키워드", "note": "오늘 데이터에 근거한 관련 동향 1~2문장"}],\n'
        ' "translations": {"뉴스번호": "해당 해외 기사 제목의 자연스러운 한국어 한줄 요약"}\n'
        "}\n"
        "translations는 위 해외 뉴스 번호 전부를 포함하라. 태그는 # 없이 짧게(게임명, 행사명, 키워드). "
        "데이터가 부족한 지역은 summary를 \"데이터 부족\"으로 써라. "
        "watchlist는 오늘 데이터에 실제 근거가 있는 키워드만 포함하고 없으면 빈 배열로 둬라. 추측 금지. "
        "highlights는 3~5개. translations는 '번역 필요한 뉴스 번호' 전부 포함. "
        "중요: 조언·제안 표현(~해야 함, ~고려하라, ~필요함)은 전면 금지다. 관찰된 사실과 근거, 맥락만 써라. "
        "히스토리와 비교해 여러 날 지속되는 트렌드인지 오늘 새로 등장한 것인지 구분해서 언급하라."
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
    last_err = ""
    for model in list(dict.fromkeys(candidates))[:4]:  # 최대 4개 모델까지만 시도
        try:
            url = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   + model + ":generateContent?key=" + GEMINI_API_KEY)
            try:
                resp = http_post_json(url, payload)
            except HTTPError as he:
                detail = ""
                try:
                    detail = he.read().decode("utf-8", "ignore")[:500]
                except Exception:
                    pass
                if he.code == 429:  # 순간 제한이면 재시도, 할당량 0이면 즉시 포기
                    print("[insight] " + model + " 429 상세: " + detail)
                    if '"quotaValue": "0"' in detail or "limit: 0" in detail:
                        raise Exception("할당량 0 - 프로젝트 설정 문제")
                    print("[insight] " + model + " 30초 후 재시도")
                    time.sleep(30)
                    resp = http_post_json(url, payload)
                else:
                    raise Exception("HTTP " + str(he.code) + " " + detail)
            text = resp["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
            result = json.loads(text)
            data["insights"] = {
                "highlights": result.get("highlights", []),
                "regional": result.get("regional", {}),
                "news_brief": result.get("news_brief", {}),
                "for_me": result.get("for_me", []),
                "watchlist": result.get("watchlist", []),
                "model": model,
            }
            n_tr = 0
            for idx, ko in (result.get("translations") or {}).items():
                try:
                    data["news"][int(idx)]["title_ko"] = ko
                    n_tr += 1
                except (ValueError, IndexError):
                    pass
            print("[insight] " + model + " - 하이라이트 " + str(len(data["insights"].get("highlights", []))) + "개, 번역 " + str(n_tr) + "개")
            return
        except Exception as e:
            last_err = str(e)
            print("[insight] " + model + " 실패: " + str(e))
    print("[insight] 모든 모델 실패 - 요약 없이 진행")
    if "429" in last_err or "할당량" in last_err:
        WARNINGS.append("Gemini 무료 한도 초과 - 오늘 인사이트/한글요약이 생략됨 (내일 자동 복구)")
    elif last_err:
        WARNINGS.append("Gemini 호출 실패 - 인사이트 생략됨")


def main():
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "youtube": collect_youtube(),
        "steam": collect_steam_top(),
        "bilibili": collect_bilibili(),
        "news": collect_news(),
    }
    try:
        hp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "steam_history.json")
        hist = []
        try:
            hist = json.load(open(hp, encoding="utf-8"))
        except Exception:
            pass
        today = data["generated_at"][:10]
        entry = {"date": today, "games": [
            {k: g[k] for k in ("rank", "appid", "name", "current", "peak_today")}
            for g in data["steam"].get("games", [])
        ]}
        if entry["games"]:
            hist = [h for h in hist if h.get("date") != today] + [entry]
            json.dump(hist[-7:], open(hp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print("[steam_history] " + str(len(hist[-7:])) + "일치 보관")
    except Exception as e:
        print("[steam_history] 스킵: " + str(e))
    # 히스토리 갱신 (최근 7일 유지)
    try:
        hp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.json")
        hist = []
        try:
            hist = json.load(open(hp, encoding="utf-8"))
        except Exception:
            pass
        today = data["generated_at"][:10]
        entry = {"date": today, "regions": {}}
        for code, r in data["youtube"].items():
            entry["regions"][code] = [v["title"] for v in r["videos"][:5]]
        if data["bilibili"]:
            entry["regions"]["CN"] = [v["title"] for v in data["bilibili"][:5]]
        hist = [h for h in hist if h.get("date") != today] + [entry]
        json.dump(hist[-7:], open(hp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("[history] " + str(len(hist[-7:])) + "일치 보관")
    except Exception as e:
        print("[history] 스킵: " + str(e))
    generate_insights(data)
    # 워치리스트 키워드가 제목에 실제 포함된 뉴스/영상 (링크용)
    try:
        wp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.json")
        kws = [k for k in json.load(open(wp, encoding="utf-8")).get("keywords", []) if k]
        hits = []
        for a in data["news"]:
            t = a["title"].lower()
            for k in kws:
                if k.lower() in t:
                    hits.append({"keyword": k, "type": "news", "title": a["title"],
                                 "url": a["url"], "source": a["source"]})
                    break
        for code, r in data["youtube"].items():
            for v in r["videos"]:
                t = v["title"].lower()
                for k in kws:
                    if k.lower() in t:
                        hits.append({"keyword": k, "type": "video", "title": v["title"],
                                     "url": v["url"], "source": r["name"] + " YouTube"})
                        break
        data["watchlist_hits"] = hits[:30]
        print("[watchlist] 매칭 " + str(len(hits)) + "건")
    except Exception as e:
        print("[watchlist] 스킵: " + str(e))
        data["watchlist_hits"] = []
    data["warnings"] = WARNINGS
    if WARNINGS:
        print("경고: " + " / ".join(WARNINGS))
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    n_yt = sum(len(v["videos"]) for v in data["youtube"].values())
    n_steam = len(data["steam"].get("games", []))
    print("완료: YouTube " + str(n_yt) + "개 / Steam " + str(n_steam) + "개 / Bilibili " + str(len(data["bilibili"])) + "개 / 뉴스 " + str(len(data["news"])) + "개 -> data.json")
    if not (n_yt or n_steam or data["bilibili"] or data["news"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
