# #055 CDN 캐시를 날렸는데 왜 유저 화면에 옛날 CSS/JS가 나와요?!: 정적 자산 캐싱과 Content Hashing (Cache Busting)

---

## 1. 현실 세계 비유: 같은 제목으로 표지만 갈아 끼운 책 vs 바코드(ISBN)가 찍힌 개정판

동네 도서관과 출판사의 단행본 배포를 상상해 보세요.

```text
❌ 고정 파일명의 비극 (도서관 사서의 디스크 캐싱):
   출판사가 오타를 고친 '개정 2판'을 냈는데, 책 표지와 제목이 1판과 똑같이 "ant.js"입니다.
   독자가 도서관(브라우저)에 가서 "ant.js 책 주세요!"라고 하자,
   사서는 "어? 그 책 우리 서가(로컬 디스크 캐시)에 1년 대여용으로 이미 꽂혀있는데?" 하고
   출판사에 전화조차 걸지 않고 서가에서 낡은 '1판'을 꺼내줍니다.
   출판사 사장님이 도서관 본부 전산망(CDN 캐시)을 $5 내고 초기화(Invalidation)해도,
   이미 전 세계 독자들의 방 책상(브라우저 로컬 디스크)에 꽂힌 낡은 책은 신(God)도 회수할 수 없습니다!
   독자는 옛날 코드를 실행하다가 신형 서버와 규격이 안 맞아 에러를 뿜습니다.

✅ Content-Based Hashing (바코드 번호가 박힌 신간):
   출판사가 책 내용이 1글자라도 바뀌면, 책 내용의 고유 해시(Hash)를 파일명에 바코드로 찍습니다:
   "ant.d8a7c2.js"
   독자가 가져가는 목차 종이(index.html)는 항상 최신(no-cache)이므로,
   목차에 적힌 "ant.d8a7c2.js 주세요!"라는 요청을 본 사서는
   "어? 이 바코드 번호는 우리 서가에 없네!" 하고 출판사에서 즉시 신간을 사 옵니다.
   한번 들여온 바코드 책은 내용이 영원히 안 바뀌므로(immutable) 안심하고 평생 보관(max-age 1년)할 수 있습니다!
```

프론트엔드와 웹 애플리케이션을 배포하는 수많은 주니어 개발자와 AI 바이브 코더들이  
"버그 고쳐서 Vercel/S3에 올렸는데, 왜 고객들 화면에는 여전히 옛날 버튼이 나오고 결제가 터지나요?!"라며  
사내 슬랙에 **"사용자 여러분, 강력 새로고침(Ctrl+Shift+R)을 눌러주세요"**라는 굴욕적인 공지를 띄웁니다.

브라우저의 HTTP 캐싱 메커니즘과 현대 웹 번들러(Vite, Webpack, Turbopack)의 핵심 무기인  
**Content-Based Hashing (Cache Busting)**을 시뮬레이션을 통해 완벽히 이해해 봅시다.

---

## 2. 문제 개요

당신은 초대형 글로벌 웹 포털의 프론트엔드 인프라 엔지니어입니다.  
신규 프론트엔드 번들 릴리즈 배포 시,  
기존의 **고정 파일명 캐싱 모델(NAIVE)**과 **Content Hash 기반 캐시 버스팅 모델(HASH)**을 시뮬레이션하고,  
클라이언트 브라우저 로컬 디스크 캐시에 따른 API 버전 불일치 에러율과 캐시 버스팅의 안정성 우위(`CACHE_BUSTING_ADVANTAGE`)를 정밀 계측하세요.

### 시뮬레이션 상세 규칙

#### 1. 공통 환경 및 해시 규칙
- 웹 애플리케이션의 핵심 자산:
  - 진입점: `index.html`
  - 스크립트 번들: 소스 코드 `code_content`
- Content Hash 계산 (결정론적 6자리 헥스):
  ```python
  h = 0
  for c in code_content:
    h = (h * 31 + ord(c)) & 0xFFFFFFFF
  hash_str = f'{h:08x}'[:6]
```
- 백엔드 API 호환성 원칙:
  - 서버의 현재 배포된 최신 버전이 $V_{server}$일 때,
  - 클라이언트가 브라우저에서 실행한 JS 번들의 버전이 $V_{client} < V_{server}$라면,
  - 신규 백엔드 API와 통신할 수 없어 **`API_MISMATCH_ERROR`** (500 런타임 에러)가 발생합니다.

#### 2. 모델 A: 고정 파일명 캐싱 (NAIVE)
- 번들 파일명: 항상 `/static/bundle.js` (고정).
- 캐시 헤더 설정:
  - `index.html`: `Cache-Control: max-age=<naive_html_ttl>`
  - `bundle.js`: `Cache-Control: max-age=<naive_bundle_ttl>`
- 클라이언트 브라우저 동작:
  - $t < html\_exp$이면 캐시된 HTML을 사용, 만료되었으면 서버에서 새 HTML 다운로드 및 $html\_exp = t + naive\_html\_ttl$ 갱신.
  - 고정 URL `/static/bundle.js`에 대해:
    - $t < bundle\_exp$이면 **서버에 요청하지 않고 디스크 캐시의 번들을 그대로 실행**!
    - 만료되었으면 서버에서 현재 최신 번들을 다운로드하고 $bundle\_exp = t + naive\_bundle\_ttl$ 갱신.
  - 실행된 번들 버전이 $V_{server}$보다 낮으면 $\to$ `API_MISMATCH_ERROR`. 일치하면 $\to$ `SUCCESS`.

#### 3. 모델 B: Content Hash 기반 캐시 버스팅 (HASH)
- 번들 파일명: `/static/bundle.<hash_str>.js` (내용물이 바뀔 때마다 파일명이 완전히 달라짐).
- 캐시 헤더 설정:
  - `index.html`: `Cache-Control: no-cache` (항상 서버에 변경 여부를 확인하여 100% 최신 HTML 보장).
  - `bundle.<hash>.js`: `Cache-Control: max-age=31536000, immutable` (영구 캐시).
- 클라이언트 브라우저 동작:
  - 방문 시 `index.html`은 항상 최신 버전을 수신. 최신 HTML은 최신 해시 번들 URL을 가리킴.
  - 해당 번들 URL이 클라이언트의 로컬 디스크 캐시에 이미 존재하면:
    - `DISK_HIT` (네트워크 대역폭 0바이트).
  - 해당 번들 URL이 로컬 디스크 캐시에 없으면:
    - 서버에서 다운로드하여 로컬에 영구 캐시 $\to$ `NETWORK_FETCH`.
  - 실행되는 번들은 항상 100% 최신 $V_{server}$이므로 $\to$ `SUCCESS` (버전 불일치 0건!).

---

## 3. 입력 형식

```text
NAIVE_HTML_TTL_SEC <naive_html_ttl>
NAIVE_BUNDLE_TTL_SEC <naive_bundle_ttl>
EVENTS <E>
... (총 E개의 이벤트 줄)
```

이벤트 줄의 종류:
1. `DEPLOY <timestamp> <version> <code_content>`:
   - 시각 `timestamp`에 서버에 새 버전 `version`과 코드 `code_content`가 배포됨.
2. `VISIT <client_id> <timestamp>`:
   - 시각 `timestamp`에 클라이언트 `client_id`가 웹사이트를 방문함.

---

## 4. 출력 형식

각 `VISIT`마다 한 줄씩 두 모델의 처리 상태를 출력합니다:
```text
VISIT <client_id> AT:<t> NAIVE:<status>,EXEC_V:<ver> HASH:<status>,EXEC_V:<ver>,ASSET:<DISK_HIT|NETWORK_FETCH>
```

모든 이벤트 종료 후 최종 종합 통계를 출력합니다:
```text
SUMMARY TOTAL_VISITS:<total>
NAIVE SUCCESS:<n_succ> ERRORS:<n_err> SUCCESS_RATE:<n_rate>%
HASH SUCCESS:<h_succ> ERRORS:<h_err> SUCCESS_RATE:<h_rate>% NETWORK_FETCHES:<fetches> DISK_HITS:<hits>
SUMMARY CACHE_BUSTING_ADVANTAGE:<adv>%
```

- `CACHE_BUSTING_ADVANTAGE = HASH_SUCCESS_RATE - NAIVE_SUCCESS_RATE` (소수점 둘째 자리까지 반올림, 예: `33.33%`)

---

## 5. 입출력 예시

### 입력
```text
NAIVE_HTML_TTL_SEC 100
NAIVE_BUNDLE_TTL_SEC 500
EVENTS 7
DEPLOY 10 1 const_v1_button_blue
VISIT C1 20
VISIT C1 30
DEPLOY 50 2 const_v2_button_red_new_api
VISIT C1 60
VISIT C2 60
VISIT C1 80
```

### 출력
```text
VISIT C1 AT:20 NAIVE:SUCCESS,EXEC_V:1 HASH:SUCCESS,EXEC_V:1,ASSET:NETWORK_FETCH
VISIT C1 AT:30 NAIVE:SUCCESS,EXEC_V:1 HASH:SUCCESS,EXEC_V:1,ASSET:DISK_HIT
VISIT C1 AT:60 NAIVE:API_MISMATCH_ERROR,EXEC_V:1 HASH:SUCCESS,EXEC_V:2,ASSET:NETWORK_FETCH
VISIT C2 AT:60 NAIVE:SUCCESS,EXEC_V:2 HASH:SUCCESS,EXEC_V:2,ASSET:NETWORK_FETCH
VISIT C1 AT:80 NAIVE:API_MISMATCH_ERROR,EXEC_V:1 HASH:SUCCESS,EXEC_V:2,ASSET:DISK_HIT
SUMMARY TOTAL_VISITS:5
NAIVE SUCCESS:3 ERRORS:2 SUCCESS_RATE:60.00%
HASH SUCCESS:5 ERRORS:0 SUCCESS_RATE:100.00% NETWORK_FETCHES:3 DISK_HITS:2
SUMMARY CACHE_BUSTING_ADVANTAGE:40.00%
```

#### 해설
- $t=10$: 버전 1 배포.
- $t=20$: C1의 첫 방문. 두 모델 모두 버전 1을 다운로드하여 `SUCCESS`.
- $t=30$: C1의 재방문. 두 모델 모두 로컬 캐시에서 버전 1을 실행하여 `SUCCESS`. (HASH는 `DISK_HIT`).
- $t=50$: 신규 기능과 새 API를 요구하는 버전 2가 릴리즈 배포됨.
- $t=60$: C1의 방문!
  - **NAIVE**: 번들 캐시 유효기간이 $20+500 = 520$초까지이므로, 브라우저는 서버에 묻지도 않고 로컬 디스크 캐시에서 옛날 버전 1을 실행합니다! 백엔드는 버전 2 API를 요구하므로 $\to$ **`API_MISMATCH_ERROR`** 발생!
  - **HASH**: 최신 HTML이 `/static/bundle.<hash2>.js`를 가리키므로, 브라우저는 새 번들을 즉시 다운로드(`NETWORK_FETCH`)하여 100% 정상 작동 (`SUCCESS`).
  - 신규 방문자 C2는 캐시가 없으므로 두 모델 모두 버전 2를 받아 성공.
- $t=80$: C1의 재방문.
  - NAIVE는 여전히 옛날 번들을 실행하며 500 에러를 뿜지만, HASH는 방금 다운받았던 버전 2를 `DISK_HIT`로 0바이트 대역폭으로 초고속 실행합니다!
- Content Hashing 모델은 500 에러 0건과 40.00%의 신뢰성 우위를 증명했습니다.
