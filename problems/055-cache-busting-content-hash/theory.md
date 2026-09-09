# #055 정적 자산 캐싱과 Content Hashing (Cache Busting) 완벽 가이드

---

## 1. 개요: "배포했는데 왜 사용자들은 새로고침을 해야만 하나요?"

프론트엔드 개발자가 React나 Vue 코드를 빌드하여 AWS S3 + CloudFront, Vercel, 또는 Nginx 웹 서버에 배포한 직후  
CS 팀과 사내 슬랙에 불이 나는 대표적인 시나리오가 있습니다:

> "방금 긴급 핫픽스를 배포했습니다!  
> 그런데 고객들이 여전히 이전 화면을 보고 있고,  
> 신규 백엔드 API와 통신할 때 규격이 안 맞아 **화면이 하얗게 멈추는 에러(White Screen of Death)**가 뜹니다!  
> 고객들에게 브라우저 캐시를 지우거나 `Ctrl + Shift + R`을 누르라고 안내해야 하나요?!"

배포를 했는데 왜 고객의 브라우저는 이전 자바스크립트/CSS를 실행할까요?  
CloudFront 캐시 무효화(Invalidation)를 아무리 돌려도 왜 해결되지 않을까요?

그 이유는 **고객의 스마트폰과 PC 브라우저 로컬 디스크에 박혀있는 디스크 캐시(Disk Cache)** 때문입니다.  
브라우저 HTTP 캐싱의 원리와, 현대 웹 프론트엔드 빌드 도구들이 이를 극복하기 위해 사용하는  
**Content-Based Hashing (Cache Busting)** 전략을 완전히 파헤쳐 봅시다.

---

## 2. HTTP 캐시 제어의 2가지 핵심 질문

브라우저가 리소스(HTML, JS, CSS, 이미지)를 요청할 때 거치는 결정 트리는 크게 2단계입니다:

```text
[요청 발생: /static/bundle.js]
        │
   (1) "서버에 물어봐야 하는가?"
        │
   ├─ YES (만료됨 / no-cache) ──> (2) "서버에 가서: 내용이 바뀌었는가?"
   │                                   │
   │                                   ├─ NO  (ETag 동일) ──> 304 Not Modified (기존 캐시 사용)
   │                                   └─ YES (ETag 변경) ──> 200 OK (새 파일 다운로드)
   │
   └─ NO  (max-age 유효) ────────> [디스크 캐시에서 즉시 실행! (from disk cache, 0ms)]
                                    🚨 서버에는 HTTP 패킷조차 날아가지 않습니다!
```

### 1) `no-cache` vs `no-store`의 결정적 차이
- **`Cache-Control: no-store`**:
  - "어떤 캐시도 하지 마라!"
  - 브라우저나 프록시가 로컬 디스크나 메모리에 파일 내용을 1바이트도 저장하지 않습니다.
  - 개인정보, 금융 계좌 내역, 일회용 보안 토큰에 사용합니다.
- **`Cache-Control: no-cache`**:
  - **"캐시는 하되, 쓸 때마다 항상 서버에 물어보고 써라!" (Always Revalidate)**
  - 브라우저 디스크에 저장해 두지만, 매번 서버에 `ETag`를 보내 "이거 바뀌었어?" 하고 물어봅니다.
  - 바뀌지 않았으면 서버가 본문 없이 `304 Not Modified`만 내려주므로 0.01초 만에 로컬 캐시를 재사용합니다.
  - **`index.html`에 적용해야 하는 가장 완벽한 헤더**입니다!

---

## 3. 고정 파일명의 비극과 캐시 버스팅(Cache Busting)

### 1) 왜 파일명이 고정되어 있으면 망하는가?
서버가 `/static/bundle.js`에 대해 `max-age=86400` (24시간)을 설정해 두었다면:
- 브라우저는 24시간 동안 서버에 접속조차 하지 않고 로컬 디스크의 `bundle.js`를 실행합니다.
- 개발자가 서버의 `bundle.js` 내용을 100번 수정해도, 클라이언트는 URL(`/static/bundle.js`)이 같기 때문에 옛날 코드를 실행합니다.
- 클라우드 CDN 캐시를 지워도(Invalidate), **이미 사용자의 브라우저 디스크 캐시에 들어간 파일은 서버 관리자가 절대 지울 수 없습니다.**

### 2) 구식 해결책: 쿼리 스트링 (`bundle.js?v=2`)의 한계
옛날에는 파일 뒤에 쿼리 스트링을 붙였습니다: `<script src="/bundle.js?v=2">`
- 하지만 수많은 기업 사내 프록시, 통신사 게이트웨이, 구형 CDN은 **URL에 쿼리 스트링이 붙어있으면 캐시를 아예 꺼버리거나, 반대로 쿼리 스트링을 무시하고 캐시**해 버리는 심각한 호환성 문제가 있습니다 (RFC 7234 권고사항).

### 3) 현대적 표준: Content-Based Hashing (`bundle.[contenthash].js`)
Vite, Webpack, Turbopack 등 최신 번들러는 **파일 내용물의 암호학적 해시(SHA-256)를 파일명 자체에 박아 넣습니다**:

```text
빌드 1: bundle.a8f19c.js  (내용: v1 코드)
빌드 2: bundle.d4e2b0.js  (내용: v2 코드 - 코드 1글자만 바뀌어도 해시가 완전히 달라짐!)
```

---

## 4. 실무 완벽 프론트엔드 배포 아키텍처 (2-Tier Cache Strategy)

현대 웹 배포의 모범 규격은 **"HTML 진입점"**과 **"정적 번들 자산"**의 캐시 정책을 철저히 이원화하는 것입니다.

```text
[웹 애플리케이션 리소스]
       │
       ├─ [1] index.html
       │      - 절대 영구 캐시 금지!
       │      - Cache-Control: no-cache, no-store, must-revalidate
       │      - 항상 최신 HTML을 서버에서 가져와 최신 번들 해시 URL을 읽음.
       │
       └─ [2] /assets/bundle.[contenthash].js, style.[contenthash].css
              - 절대 만료될 일 없음 (내용이 바뀌면 파일명이 바뀌므로!)
              - Cache-Control: public, max-age=31536000, immutable
              - 1년(31,536,000초) 동안 브라우저에 영구 캐시!
              - immutable: 유저가 F5 새로고침을 연타해도 서버에 304 재검증조차 안 날림!
```

### AWS S3 + CloudFront 배포 스크립트 모범 예시 (CI/CD)

```bash
# 1단계: 정적 자산(assets)을 1년 영구 캐시로 업로드
aws s3 sync dist/assets s3://my-web-bucket/assets \
  --cache-control "public, max-age=31536000, immutable"

# 2단계: index.html을 no-cache로 업로드
aws s3 cp dist/index.html s3://my-web-bucket/index.html \
  --cache-control "no-cache, no-store, must-revalidate"

# 3단계: CloudFront 캐시 무효화 (비용 절감)
# 전체(/*)를 날릴 필요 없이, 오직 index.html 딱 1개만 무효화하면 0.1초 만에 전 세계 배포 완료!
aws cloudfront create-invalidation --distribution-id E12345 --paths "/index.html"
```

---

## 5. 결론: Content Hashing이 가져다주는 3대 기적

1. **배포 즉시 100% 반영**: 사용자가 새로고침이나 캐시 삭제를 할 필요 없이, 사이트에 접속하는 순간 즉시 최신 번들이 실행됩니다.
2. **네트워크 대역폭 90% 절감**: 변경되지 않은 자산(예: 로고 이미지, 써드파티 라이브러리 `vendor.[hash].js`)은 사용자의 브라우저 디스크에 영구 보관되어 트래픽 비용이 0원이 됩니다.
3. **구버전-신버전 동시 무장애 공존**: 이전 탭을 열어둔 사용자는 여전히 이전 해시 파일을 읽고, 새 탭을 연 사용자는 새 해시 파일을 읽으므로 스크립트 충돌이 완전히 방지됩니다.
