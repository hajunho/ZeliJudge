# 131. 크롬 업데이트 이후 왜 결제 승인/로그인만 하면 세션이 풀려요?!: 브라우저 쿠키 보안 3대 플래그(SameSite: Strict/Lax/None, HttpOnly, Secure)와 CSRF 방어 & 3rd-Party Callback 참사

## 문제 설명

이커머스 스타트업의 주니어 풀스택 엔지니어 젤리(Zeli)는 쇼핑몰 서비스에 국내 결제대행사(PG사)의 신용카드 결제 모듈을 연동했습니다.  
테스트베드에서 결제창 팝업을 띄우고 결제 승인을 진행했을 때 모든 것이 완벽하게 동작했습니다.

```
[사용자 브라우저]                  [쇼핑몰 서버 (shop.com)]         [결제사 PG (pg-pay.com)]
       |                                     |                                   |
       | 1. 장바구니 결제 요청               |                                   |
       |------------------------------------>| (세션 발급: SESSIONID)            |
       | 2. PG 결제창으로 이동                |                                   |
       |------------------------------------------------------------------------>|
       | 3. 카드 비밀번호 입력 및 승인 완료   |                                   |
       | 4. PG사가 쇼핑몰로 결제 결과 전송   |                                   |
       |    <form method="POST" action="https://shop.com/checkout/callback">     |
       |------------------------------------>|                                   |
       |                                     | 🚨 "SESSIONID 쿠키가 없는데요?!" |
       |                                     |    "누구 주문인지 알 수 없습니다"  |
```

그러나 구글이 **Chrome 80 업데이트**를 전 세계에 전면 배포한 다음 날 아침, 젤리의 회사 고객센터는 결제 실패를 호소하는 고객들의 전화로 마비되었습니다! 🚨

> **고객 항의**:  
> *"카드사 앱카드 비밀번호까지 다 치고 결제 완료를 눌렀는데, 쇼핑몰로 돌아오자마자 **'로그인이 필요합니다'**라면서 장바구니가 텅 비어버려요!"*  
> *"우리 회사 서버 코드는 어제 한 줄도 배포하지 않았는데 도대체 왜 갑자기 결제가 다 튕기는 거죠?!"* 😱

---

### 원인: 브라우저 쿠키의 SameSite 기본값 변경 (None $	o$ Lax)

과거(Chrome 79 이전)에는 웹 서버가 세션 쿠키를 발급할 때 `SameSite` 속성을 따로 지정하지 않아도(`Unspecified`), 브라우저가 이를 **`SameSite=None`**으로 취급하여 **다른 사이트(Cross-Site)에서 출발한 요청이라도 쿠키를 무조건 자동으로 전송**해 주었습니다.

하지만 이는 해커가 악성 사이트(`evil.com`)에서 사용자의 은행/쇼핑몰 계좌로 위조 요청을 몰래 날릴 수 있는 **CSRF(Cross-Site Request Forgery)** 공격에 취약했습니다!

이를 원천 차단하기 위해 Chrome 80부터 다음 두 가지 강력한 정책이 강제 적용되었습니다:

1. **Lax by Default**:
   - `SameSite`가 명시되지 않은 쿠키는 기본값이 **`SameSite=Lax`**로 강제 격상됩니다.
   - `Lax` 모드에서는 사용자가 링크를 클릭하여 페이지를 이동하는 **Top-level GET 요청**에는 쿠키가 전송되지만, **Cross-Site POST 요청이나 Subresource(이미지, iframe, 비동기 fetch) 요청에는 쿠키 전송이 원천 차단**됩니다!
   - PG사가 결제 완료 후 쇼핑몰의 `/checkout/callback`으로 쏜 요청은 `https://pg-pay.com`에서 `https://shop.com`으로 날아간 **Cross-Site Top-Level POST** 요청이었습니다.
   - 따라서 브라우저가 쇼핑몰의 `SESSIONID` 쿠키 전송을 가차없이 차단해 버렸고, 쇼핑몰 서버는 결제 승인 결과를 받고도 주문자가 누구인지 식별하지 못해 세션 유실 참사가 발생한 것입니다!

2. **SameSite=None Requires Secure**:
   - 외부 사이트 콜백이나 위젯을 위해 `SameSite=None`을 명시하더라도, 반드시 **`Secure` (HTTPS 필수)** 플래그가 함께 붙어있지 않으면 브라우저가 쿠키 자체를 거부합니다(`REJECTED_SAMESITE_NONE_REQUIRES_SECURE`).

---

### 쿠키의 3대 핵심 보안 플래그와 Site 판정 (eTLD+1)

젤리는 이번 장애를 수습하면서 쿠키 보안 플래그의 상호작용과 브라우저의 동작 원리를 완벽하게 시뮬레이션하는 **"브라우저 쿠키 보안 엔진"**을 개발하기로 결심했습니다.

#### 1. Site vs Origin (eTLD+1)
- **Origin**: `Scheme + Host + Port` (완전 일치해야 Same-Origin)
- **Site**: `eTLD + 1` (유효 최상위 도메인 + 직전 도메인 1단계)
  - `https://api.shop.com` $	o$ `https://shop.com`: Origin은 다르지만 Site는 `shop.com`으로 동일 (**Same-Site**!)
  - `https://a.co.kr` $	o$ `https://b.co.kr`: `co.kr`은 2단 TLD이므로 `a.co.kr`과 `b.co.kr`은 서로 다른 사이트 (**Cross-Site**!)
  - 직접 주소창 입력이나 북마크 이동: Initiator가 없으므로 Same-Site로 간주.

#### 2. 쿠키 보안 플래그 동작
- **`HttpOnly`**:
  - `action_type == "JS_COOKIE_ACCESS"` 시 자바스크립트 엔진(`document.cookie`)에 노출되지 않음.
  - `http_only: true`인 쿠키는 보호되고, `false`인 쿠키만 JS에 읽힙니다. 읽을 수 있는 쿠키가 1개라도 있으면 `XSS_COOKIE_THEFT_POSSIBLE`, 없으면 `XSS_MITIGATED_BY_HTTPONLY`.
- **`Secure`**:
  - `secure: true`인 쿠키는 오직 `https://` 요청에서만 전송됩니다. 평문 `http://` 요청 시 `REJECTED_INSECURE_PROTOCOL` 사유로 차단됩니다.
- **`SameSite` (Strict / Lax / None)**:
  - `Same-Site` 요청: 쿠키 종류에 관계없이 정상 첨부.
  - `Cross-Site` 요청:
    - `Strict`: 무조건 차단 (`BLOCKED_BY_SAMESITE_STRICT`). 외부 링크를 클릭해서 들어와도 전송 안 됨.
    - `Lax`: Top-Level 탐색이면서 안전한 메서드(`GET`, `HEAD`)일 때만 전송 허용. Cross-Site POST나 Subresource 요청 시 차단 (`BLOCKED_BY_SAMESITE_LAX`).
    - `None`: 모든 Cross-Site 전송 허용. 단, Chrome 80+에서는 `secure: true`가 필수. 누락 시 `REJECTED_SAMESITE_NONE_REQUIRES_SECURE`.

#### 3. 보안 판정 (Security Verdict)
- **Same-Site 요청**: `NORMAL_SAME_SITE_REQUEST`
- **Cross-Site 요청**:
  - 쿠키가 첨부된 경우:
    - POST/PUT/DELETE 등 상태 변경 요청:
      - CSRF 토큰 있음 (`csrf_token_present: true`): `CSRF_PREVENTED_BY_TOKEN`
      - CSRF 토큰 없음:
        - `is_callback: true`인 경우: `CALLBACK_PROCESSED_WITH_COOKIES`
        - 일반 공격 요청: `CSRF_VULNERABILITY_EXPLOITED` (공격 성공)
    - GET/HEAD 요청:
      - Top-Level 탐색: `SAFE_CROSS_SITE_NAVIGATION`
      - Subresource(이미지 등) 탐색: `GET_SUBRESOURCE_CSRF_EXPLOITED`
  - 쿠키가 차단된 경우:
    - 결제/OAuth 콜백 (`is_callback: true` 또는 URL 경로에 `callback`, `checkout`, `oauth` 포함):
      - `SESSION_COOKIE_BLOCKED_CALLBACK_FAILURE` (결제/인증 세션 유실 참사)
    - 일반 요청:
      - `CSRF_BLOCKED_BY_SAMESITE` (CSRF 공격 차단 성공)

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "browser_mode": "CHROME_80_PLUS",  // "CHROME_80_PLUS" 또는 "PRE_CHROME_80"
  "stored_cookies": [
    {
      "name": "SESSIONID",
      "domain": "shop.com",
      "path": "/",
      "secure": true,
      "http_only": true,
      "same_site": "Unspecified"  // "Strict", "Lax", "None", "Unspecified"
    }
  ],
  "scenarios": [
    {
      "scenario_id": "pg_callback_post",
      "action_type": "HTTP_REQUEST",  // "HTTP_REQUEST" 또는 "JS_COOKIE_ACCESS"
      "initiator_origin": "https://pg-pay.com",
      "target_url": "https://shop.com/checkout/callback",
      "method": "POST",
      "is_top_level_navigation": true,
      "csrf_token_present": false,
      "is_callback": true
    },
    {
      "scenario_id": "js_xss_attempt",
      "action_type": "JS_COOKIE_ACCESS",
      "page_origin": "https://shop.com"
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 출력합니다:

```json
{
  "summary": {
    "browser_mode": "CHROME_80_PLUS",
    "total_scenarios": 2,
    "csrf_vulnerabilities_exploited": 0,
    "csrf_attacks_blocked": 0,
    "session_lost_callback_failures": 1,
    "xss_exposed_cookies": 0,
    "xss_protected_cookies": 1
  },
  "scenarios": [
    {
      "scenario_id": "pg_callback_post",
      "action_type": "HTTP_REQUEST",
      "is_same_site": false,
      "attached_cookies": [],
      "blocked_cookies": [
        {
          "name": "SESSIONID",
          "reason": "BLOCKED_BY_SAMESITE_LAX"
        }
      ],
      "security_verdict": "SESSION_COOKIE_BLOCKED_CALLBACK_FAILURE"
    },
    {
      "scenario_id": "js_xss_attempt",
      "action_type": "JS_COOKIE_ACCESS",
      "status": "PROTECTED_BY_HTTPONLY",
      "readable_cookies": [],
      "protected_cookies": [
        "SESSIONID"
      ],
      "attached_cookies": [],
      "security_verdict": "XSS_MITIGATED_BY_HTTPONLY"
    }
  ]
}
```

---

## 제약 사항

- `browser_mode`는 `"CHROME_80_PLUS"` 또는 `"PRE_CHROME_80"` 중 하나입니다.
- 쿠키의 `domain` 매칭 시 `target_url`의 호스트가 `domain`과 정확히 일치하거나 하위 도메인(`.domain`으로 끝남)이어야 합니다.
- 쿠키의 `path` 매칭 시 `target_url`의 경로가 `path`로 시작해야 합니다.
- 2단 국가 코드 TLD(`co.kr`, `ne.kr`, `or.kr`, `re.kr`, `pe.kr`, `go.kr`, `co.uk`, `org.uk`, `ac.uk`, `gov.uk`, `me.uk`, `com.au`, `net.au`, `org.au`, `edu.au`, `co.jp`, `ne.jp`, `or.jp`, `ac.jp`, `go.jp`)의 경우 마지막 3개 세그먼트가 eTLD+1이 됩니다.
- IPv4 주소의 경우 4개 옥텟 전체가 Site로 취급됩니다.
