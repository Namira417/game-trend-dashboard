#!/usr/bin/env python3
"""
행사 일정 주간 자동 갱신
- 뉴스 제목들을 수집해 Gemini에게 전달
- 일정 발표/변경 근거가 명확한 경우에만 events.json 갱신
- 결과 검증 실패 시 기존 파일 유지
"""
import json
import os
import re
import sys

from collector import collect_news, http_post_json, GEMINI_API_KEY

EVENTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "events.json")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REQUIRED = ("name", "region", "location", "start", "end", "url")


def valid(events):
    if not isinstance(events, list) or not events:
        return False
    for e in events:
        if not isinstance(e, dict):
            return False
        if not all(k in e and isinstance(e[k], str) and e[k] for k in REQUIRED):
            return False
        if not (DATE_RE.match(e["start"]) and DATE_RE.match(e["end"])):
            return False
        if e["end"] < e["start"]:
            return False
    return True


def main():
    if not GEMINI_API_KEY:
        print("[events] GEMINI_API_KEY 없음 - 종료")
        return

    current = json.load(open(EVENTS_PATH, encoding="utf-8"))
    news = collect_news()
    titles = "\n".join(a["source"] + ": " + a["title"] for a in news[:120])
    if not titles:
        print("[events] 뉴스 없음 - 종료")
        return

    prompt = (
        "너는 게임 행사 일정 데이터베이스 관리자다.\n\n"
        "## 현재 행사 목록(JSON)\n" + json.dumps(current["events"], ensure_ascii=False, indent=1) +
        "\n\n## 이번 주 게임 뉴스 제목\n" + titles +
        "\n\n위 뉴스에서 행사 일정의 신규 발표, 날짜 확정/변경, 취소 근거가 '명확히' 있는 경우에만 목록을 수정하라.\n"
        "규칙:\n"
        "- 근거 없는 항목은 절대 수정/삭제하지 말고 그대로 유지\n"
        "- note에 '미확정' 표시된 행사가 뉴스로 확정되면 날짜 갱신하고 note에서 미확정 문구 제거\n"
        "- 뉴스에 새 대형 행사(국제 게임쇼, 한국 행사) 일정 발표가 있으면 같은 형식으로 추가\n"
        "- 종료된 지 6개월 넘은 행사는 삭제 가능\n"
        "- 변경 사항이 하나도 없으면 {\"changed\": false} 만 반환\n"
        "- 변경했으면 {\"changed\": true, \"reason\": \"한줄 사유\", \"events\": [전체 목록]} 반환\n"
        "날짜 형식 YYYY-MM-DD. JSON만 출력하고 코드블록 금지."
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "response_mime_type": "application/json"},
    }
    for model in ("gemini-flash-lite-latest", "gemini-flash-latest"):
        try:
            resp = http_post_json(
                "https://generativelanguage.googleapis.com/v1beta/models/" + model
                + ":generateContent?key=" + GEMINI_API_KEY, payload)
            text = resp["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
            result = json.loads(text)
            if not result.get("changed"):
                print("[events] 변경 없음")
                return
            events = result.get("events", [])
            # 안전장치: 형식 검증 + 기존 대비 급감 방지
            if not valid(events) or len(events) < len(current["events"]) - 2:
                print("[events] 검증 실패 - 갱신 취소")
                return
            current["events"] = events
            json.dump(current, open(EVENTS_PATH, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
            print("[events] 갱신 완료: " + result.get("reason", ""))
            return
        except Exception as e:
            print("[events] " + model + " 실패: " + str(e))
    print("[events] 실패 - 기존 유지")


if __name__ == "__main__":
    main()
