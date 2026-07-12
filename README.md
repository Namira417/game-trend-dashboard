# 🎮 게임 트렌드 대시보드 — 설정 가이드

매일 아침 7시(KST)에 자동으로 데이터를 수집해서 폰/PC 어디서든 볼 수 있는 대시보드입니다.

## 파일 구성

| 파일 | 역할 |
|---|---|
| `index.html` | 대시보드 (트렌드 / 뉴스 / 행사 탭) |
| `collector.py` | 데이터 수집 스크립트 → `data.json` 생성 |
| `events.json` | 행사 일정 (직접 편집해서 추가/수정) |
| `data.json` | 수집된 데이터 (자동 생성, 현재는 샘플) |
| `.github/workflows/update.yml` | 매일 07:00 KST 자동 수집 |

## 1단계 — YouTube API 키 발급 (5분, 무료)

1. https://console.cloud.google.com 접속 → Google 계정 로그인
2. 상단에서 **프로젝트 만들기** (이름 아무거나, 예: `game-dashboard`)
3. 왼쪽 메뉴 **API 및 서비스 → 라이브러리** → `YouTube Data API v3` 검색 → **사용 설정**
4. **API 및 서비스 → 사용자 인증 정보 → 사용자 인증 정보 만들기 → API 키**
5. 생성된 키 복사 (신용카드 등록 불필요, 일 10,000유닛 무료 — 이 대시보드는 하루 10유닛도 안 씀)

## 2단계 — GitHub 저장소 만들기

1. https://github.com 가입/로그인
2. 우측 상단 **+ → New repository**
   - 이름: `game-trend-dashboard`
   - **Public** 선택 (Private도 가능하지만 Pages가 유료 플랜 필요)
   - Create repository
3. **uploading an existing file** 링크 클릭 → 이 폴더의 파일 전체를 드래그해서 업로드 → Commit
   - ⚠️ `.github/workflows/update.yml`은 웹 업로드로 폴더 구조가 유지 안 될 수 있음.
     이 경우: 저장소에서 **Add file → Create new file** → 파일명에 `.github/workflows/update.yml` 입력 → 내용 붙여넣기

## 3단계 — API 키 등록 (Secrets)

1. 저장소 → **Settings → Secrets and variables → Actions**
2. **New repository secret**
   - Name: `YOUTUBE_API_KEY`
   - Secret: 1단계에서 복사한 키
3. Add secret

## 4단계 — GitHub Pages 켜기

1. 저장소 → **Settings → Pages**
2. Source: **Deploy from a branch** / Branch: `main`, 폴더 `/ (root)` → Save
3. 1~2분 후 `https://<아이디>.github.io/game-trend-dashboard/` 에서 접속 가능
4. 폰에서 이 주소를 홈 화면에 추가하면 앱처럼 사용 가능

## 5단계 — 첫 수집 실행

1. 저장소 → **Actions** 탭 → 처음이면 "I understand... enable them" 클릭
2. 왼쪽 **데이터 수집** → **Run workflow** 버튼 → 실행
3. 완료되면 `data.json`이 실제 데이터로 갱신되고, 이후 매일 아침 7시 자동 실행

## 커스터마이징

- **행사 추가/수정**: `events.json` 편집 (GitHub 웹에서 연필 아이콘으로 바로 가능)
- **뉴스 매체 추가**: `collector.py`의 `NEWS_FEEDS`에 RSS 주소 추가
- **지역 추가**: `collector.py`의 `YT_REGIONS`에 국가 코드 추가 (예: `"GB": "영국"`)
- **수집 시간 변경**: `update.yml`의 cron 수정 (UTC 기준, KST-9시간)

## 문제 해결

- 트렌드 탭이 비어 있음 → Secrets에 `YOUTUBE_API_KEY` 등록됐는지, Actions 로그에서 `[youtube]` 줄 확인
- Bilibili가 비어 있음 → Bilibili가 가끔 봇 요청을 차단함. 다음 수집 때 자동 재시도되므로 대부분 하루 안에 복구
- 특정 뉴스 매체 누락 → 해당 매체 RSS가 일시 장애일 수 있음. Actions 로그의 `[news]` 줄에서 원인 확인

## (추가) Gemini 무료 API로 인사이트/한글요약 켜기

1. https://aistudio.google.com 접속 → Google 계정 로그인
2. 좌측 상단 **Get API key** → **Create API key** → 키 복사 (무료, 카드 불필요)
3. GitHub 저장소 → **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `GEMINI_API_KEY` / Secret: 복사한 키 → Add secret
4. Actions에서 "데이터 수집" 다시 실행하면:
   - 트렌드 탭 상단에 💡 **오늘의 인사이트** 카드 (핵심 3~5줄 + 지역별 트렌드 비교)
   - 뉴스 탭의 해외 기사 아래에 🇰🇷 한글 한줄 요약

키를 등록하지 않으면 이 기능만 빠지고 나머지는 그대로 동작합니다.
