# 127. 브라우저에선 초록불인데 왜 모바일 앱에선 결제가 다 터져요?!: TLS X.509 인증서 체인(Certificate Chain)과 누락된 중간 CA(Intermediate CA) & AIA의 저주

## 문제 설명

이커머스 스타트업의 주니어 인프라 엔지니어 젤리(Zeli)는 자정 무렵 만료 예정이던 서비스 도메인(`checkout.zeli.shop`)의 SSL/TLS 인증서를 Let's Encrypt를 통해 성공적으로 갱신했습니다.  
Nginx 설정 파일(`/etc/nginx/sites-available/default`)을 수정한 뒤 `nginx -t && systemctl reload nginx` 명령어를 실행했고, 자신의 맥북(MacBook) 크롬 브라우저에서 결제 페이지로 접속해 보았습니다.

```
https://checkout.zeli.shop
🔒 연결이 안전합니다. (인증서 유효함: 2026-09-09 ~ 2026-12-08)
```

초록색 자물쇠가 완벽하게 뜨고 결제창 UI도 정상 렌더링되는 것을 확인한 젤리는 안도의 한숨을 쉬며 잠자리에 들었습니다. 😴  

하지만 새벽 2시, 슬랙 알람이 쉴 새 없이 울리기 시작했습니다! 🚨
- **CS팀 긴급 보고**: *"안드로이드 및 iOS 모바일 앱에서 결제하기 버튼을 누르면 전부 `네트워크 연결 오류`가 뜨면서 결제가 100% 실패하고 있습니다!"*
- **모바일 앱 로그**:
  ```
  javax.net.ssl.SSLHandshakeException: 
  java.security.cert.CertPathValidatorException: 
  Trust anchor for certification path not found.
  ```
- **외부 PG사(결제대행사) 웹훅 로그**:
  ```
  curl: (60) SSL certificate problem: unable to get local issuer certificate
  More details here: https://curl.se/docs/sslcerts.html
  ```

*"아니, 내 맥북 브라우저에서는 분명 초록색 자물쇠가 뜨고 결제도 잘 되는데, 왜 모바일 앱과 결제 서버(cURL, Java)에서만 인증서가 유효하지 않다며 결제가 전면 마비되는 거죠?!"* 😱

---

### 왜 이런 참사가 발생했을까? (신뢰의 사슬과 `cert.pem` vs `fullchain.pem`)

이 참사의 원인은 Nginx 설정 파일에 적힌 단 한 줄의 경로 때문이었습니다:

```nginx
# ❌ 젤리가 적은 잘못된 설정 (중간 CA 누락!)
ssl_certificate /etc/letsencrypt/live/zeli.shop/cert.pem;
ssl_certificate_key /etc/letsencrypt/live/zeli.shop/privkey.pem;

# ✅ 반드시 적어야 하는 올바른 설정 (전체 인증서 체인 포함!)
ssl_certificate /etc/letsencrypt/live/zeli.shop/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/zeli.shop/privkey.pem;
```

#### 1. X.509 신뢰의 사슬(Chain of Trust) 3계층
웹 브라우저나 모바일 앱은 서버를 무작정 믿지 않습니다. 오직 자신이 신뢰하는 기관이 발급한 인증서만 인정합니다:

```
[X.509 3계층 신뢰의 사슬]

┌─────────────────────────────────────────────────────────┐
│ 1. Root CA (최상위 인증기관, 예: ISRG Root X1)          │ <- 스마트폰/OS Trust Store에 내장
│    (Self-Signed: 자기 자신이 스스로 서명)               │
└────────────────────────────┬────────────────────────────┘
                             │ 서명(Sign)
                             ▼
┌─────────────────────────────────────────────────────────┐
│ 2. Intermediate CA (중간 인증기관, 예: R3)              │ <- ⚠️ 서버가 TLS 통신 시 건네줘야 함!
│    (Root CA가 서명한 위임 관리자)                       │
└────────────────────────────┬────────────────────────────┘
                             │ 서명(Sign)
                             ▼
┌─────────────────────────────────────────────────────────┐
│ 3. Leaf Certificate (서버 인증서, checkout.zeli.shop)   │ <- 내 도메인 인증서
│    (중간 CA가 최종 서명하여 발급)                       │
└─────────────────────────────────────────────────────────┘
```

- **Root CA**: 전 세계 OS/기기의 공인 신뢰 목록(Trust Store)에 이미 설치되어 있습니다.
- **Leaf Certificate**: 내 도메인 전용 인증서입니다.
- **Intermediate CA**: Root CA와 Leaf 사이를 잇는 중간 다리입니다. **클라이언트의 기기에는 이 중간 CA가 저장되어 있지 않으므로, 서버가 TLS 핸드셰이크 시 반드시 함께 전달(Server Hello)해야 합니다!**

#### 2. 데스크톱 브라우저가 사기(AIA Fetching)를 치는 이유
`cert.pem`에는 Leaf 인증서 1장만 들어 있고 중간 CA가 누락되어 있습니다. 그런데 왜 맥북 브라우저에선 정상 작동했을까요?

1. **AIA (Authority Information Access) 백그라운드 페칭**:
   - X.509 인증서 내부에는 상위 발급자(CA) 인증서를 다운로드할 수 있는 HTTP URL(`CA Issuers`)이 기록되어 있습니다.
   - **Chrome, Safari 등 데스크톱 웹 브라우저**는 중간 CA가 누락되면, **사용자 몰래 백그라운드로 AIA URL에 접속하여 누락된 중간 CA를 다운로드**한 뒤 체인을 완성합니다!
   - 또한 이전에 다른 웹사이트를 방문하면서 로컬 디스크에 캐시해 둔 중간 CA를 자동으로 끌어와 재사용하기도 합니다.
2. **모바일 앱(Android OkHttp, iOS)과 백엔드(Java, cURL)의 엄격한 거부**:
   - 모바일 네이티브 네트워크 라이브러리(OkHttp 등)와 백엔드 서버(Java, Python, cURL)는 **성능 및 보안상의 이유로 AIA Fetching을 지원하지 않습니다**!
     - *지연 시간(Latency)*: HTTPS 핸드셰이크 도중에 추가 HTTP 통신을 하면 수백 ms의 네트워크 지연이 발생함.
     - *중간자 공격(MITM)*: 중간 인증서를 평문 HTTP로 받아오는 과정에서 보안 취약점이 발생할 수 있음.
   - 따라서 서버가 중간 CA를 직접 건네주지 않으면, 모바일 앱은 즉시 `Trust anchor for certification path not found` 에러를 던지고 연결을 끊어버립니다!

`fullchain.pem`(`cert.pem` + `chain.pem`)을 설정하면 서버가 Leaf와 Intermediate CA를 한 번에 클라이언트에게 건네주므로, AIA 다운로드 없이 모든 모바일 기기와 백엔드에서 0.1초 만에 안전하게 통과됩니다.

---

## 과제

당신은 TLS 클라이언트의 인증서 체인 검증 엔진을 시뮬레이션하는 **"TLS Certificate Chain Validator"**를 구현해야 합니다.

클라이언트 기기의 신뢰 저장소(Trust Store), 외부 AIA 다운로드 저장소, 그리고 서버가 전송한 인증서 목록과 클라이언트 환경이 주어질 때, 각 연결 시나리오의 체인 유효성을 검증하고 그 결과를 리포트하십시오.

---

### 입력 형식 (JSON)

표준 입력(stdin)으로 다음 구조의 JSON 객체가 주어집니다:

```json
{
  "client_trust_stores": {
    "<client_type>": [
      {
        "subject": "CN=ISRG Root X1",
        "valid_from": 1433376000,
        "valid_to": 1748995200
      }
    ]
  },
  "intermediate_ca_repository": {
    "http://r3.i.lencr.org/": {
      "subject": "CN=R3",
      "issuer": "CN=ISRG Root X1",
      "valid_from": 1600000000,
      "valid_to": 1750000000
    }
  },
  "scenarios": [
    {
      "scenario_id": "desktop_browser_aia_success",
      "client_type": "modern_browser",
      "allow_aia_fetching": true,
      "current_time": 1650000000,
      "server_sent_chain": [
        {
          "cert_id": "leaf",
          "subject": "CN=checkout.zeli.shop",
          "issuer": "CN=R3",
          "valid_from": 1640000000,
          "valid_to": 1670000000,
          "aia_ca_issuers_url": "http://r3.i.lencr.org/"
        }
      ]
    }
  ]
}
```

- `client_trust_stores`: 클라이언트 환경별 신뢰하는 최상위 루트 인증서(Root CA) 목록
  - `subject`: 인증서 식별자 (예: `"CN=ISRG Root X1"`)
  - `valid_from`, `valid_to`: 유효 기간 (초 단위 Unix Timestamp)
- `intermediate_ca_repository`: AIA URL별 중간 CA 인증서 정보 딕셔너리
  - `subject`, `issuer`, `valid_from`, `valid_to`
- `scenarios`: 검증할 접속 시나리오 목록
  - `scenario_id`: 시나리오 고유 ID
  - `client_type`: 클라이언트 환경 (신뢰 저장소 조회 키)
  - `allow_aia_fetching`: AIA 백그라운드 다운로드 활성화 여부 (데스크톱 브라우저는 `true`, 모바일 앱/서버는 `false`)
  - `current_time`: 접속 시점의 현재 시각 (Unix Timestamp)
  - `server_sent_chain`: 서버가 TLS 핸드셰이크 시 전송한 인증서 목록 (첫 번째 원소가 Leaf 인증서)
    - `cert_id`, `subject`, `issuer`, `valid_from`, `valid_to`
    - `aia_ca_issuers_url`: (선택) 상위 발급자 AIA 다운로드 URL

---

### 체인 검증 규칙

각 시나리오별로 다음 절차에 따라 인증서 체인을 검증합니다:

1. **서버 인증서 부재 (`EMPTY_SERVER_CHAIN`)**:
   - `server_sent_chain`이 비어 있으면 즉시 실패합니다:
     - `status`: `"VERIFICATION_FAILED"`
     - `error`: `"EMPTY_SERVER_CHAIN"`
     - `error_detail`: `"Server did not send any certificates in TLS handshake"`
     - `resolved_chain`: `[]`, `aia_downloads`: `[]`

2. **인증서 체인 순회 (Leaf부터 시작)**:
   - 서버가 보낸 첫 번째 인증서(`server_sent_chain[0]`)를 현재 인증서(`curr`)로 설정합니다.
   - 체인을 한 단계씩 올라가며 다음을 확인합니다:
     1. **현재 인증서 유효 기간 검증**:
        - `current_time < curr.valid_from`:
          - `error`: `"CERTIFICATE_NOT_YET_VALID"`
          - `error_detail`: `"Certificate <subject> is not valid until <valid_from>"`
          - `resolved_chain`에 `curr.subject`를 추가하고 검증 중단 (실패).
        - `current_time > curr.valid_to`:
          - `error`: `"CERTIFICATE_EXPIRED"`
          - `error_detail`: `"Certificate <subject> expired at <valid_to>"`
          - `resolved_chain`에 `curr.subject`를 추가하고 검증 중단 (실패).
     2. 유효 기간이 정상이면 `resolved_chain`에 `curr.subject`를 추가합니다.
     3. **클라이언트 Trust Store 확인**:
        - 현재 인증서의 `subject`가 해당 클라이언트의 `client_trust_stores[client_type]`에 존재하는지 확인합니다.
        - 만약 Trust Store에 존재한다면 (트러스트 앵커 도달):
          - Trust Store에 등록된 루트 인증서의 `valid_to`가 `current_time`보다 이전이면:
            - `error`: `"ROOT_CA_EXPIRED"`
            - `error_detail`: `"Root CA <subject> expired at <valid_to>"`
            - 검증 중단 (실패).
          - 만료되지 않았다면 체인 검증 **성공**! 루프를 종료합니다.
     4. **자체 서명(Self-Signed) 루트 불일치 확인**:
        - `curr.issuer == curr.subject`인데 클라이언트 Trust Store에 없다면:
          - `error`: `"UNTRUSTED_ROOT_CA"`
          - `error_detail`: `"Self-signed root <subject> is not in client trust store"`
          - 검증 중단 (실패).
     5. **상위 발급자(Issuer) 탐색**:
        - `server_sent_chain`에서 `subject == curr.issuer`인 인증서를 찾습니다 (`next_cert`).
        - **서버 체인에 없을 경우**:
          - 먼저 클라이언트의 Trust Store에 `curr.issuer`와 일치하는 Root CA가 있는지 확인합니다.
            - 존재한다면: `resolved_chain`에 해당 Root CA의 `subject`를 추가합니다.
            - 만약 Root CA의 `current_time > valid_to`라면:
              - `error`: `"ROOT_CA_EXPIRED"`
              - `error_detail`: `"Trust anchor <subject> expired at <valid_to>"`
              - 검증 중단 (실패).
            - 만료되지 않았다면 체인 검증 **성공**! 루프를 종료합니다.
          - Trust Store에도 없다면, **AIA Fetching**을 시도합니다:
            - `allow_aia_fetching == true`이고, `curr.aia_ca_issuers_url`이 존재하며 `intermediate_ca_repository`에 등록되어 있다면:
              - AIA 저장소에서 해당 인증서를 가져옵니다 (`next_cert`).
              - `aia_downloads`에 `{"url": aia_url, "downloaded_subject": next_cert.subject}`를 기록합니다.
            - 그렇지 않다면 (AIA 불가 또는 URL 없음):
              - `error`: `"MISSING_INTERMEDIATE_CA"`
              - `error_detail`: `"Unable to find intermediate CA for <issuer> (AIA fetching: <allow_aia_fetching>)"`
              - 검증 중단 (실패).
     6. **순환 참조(Loop) 감지**:
        - `next_cert.subject`가 이미 이번 검증에서 방문한 적이 있다면:
          - `error`: `"CERTIFICATE_LOOP_DETECTED"`
          - `error_detail`: `"Loop detected at <next_cert.subject>"`
          - 검증 중단 (실패).
     7. `curr = next_cert`로 갱신하고 다음 단계로 진행합니다.

3. **결과 생성 및 집계**:
   - 에러 없이 루트 CA 도달 시: `status: "VERIFICATION_SUCCESS"`, `error: null`, `error_detail: null`
   - 에러 발생 시: `status: "VERIFICATION_FAILED"`
   - 전체 시나리오에 대한 요약(`summary`) 통계를 계산합니다.

---

### 출력 형식 (JSON)

표준 출력(stdout)으로 다음 형식의 JSON 객체를 출력합니다 (인덴트 2칸):

```json
{
  "summary": {
    "total_scenarios": 2,
    "successful_verifications": 1,
    "failed_verifications": 1,
    "missing_intermediate_ca_errors": 1,
    "expired_certificate_errors": 0
  },
  "results": [
    {
      "scenario_id": "desktop_browser_aia_success",
      "client_type": "modern_browser",
      "status": "VERIFICATION_SUCCESS",
      "error": null,
      "error_detail": null,
      "resolved_chain": [
        "CN=checkout.zeli.shop",
        "CN=R3",
        "CN=ISRG Root X1"
      ],
      "aia_downloads": [
        {
          "url": "http://r3.i.lencr.org/",
          "downloaded_subject": "CN=R3"
        }
      ]
    },
    {
      "scenario_id": "mobile_app_no_aia_failure",
      "client_type": "modern_browser",
      "status": "VERIFICATION_FAILED",
      "error": "MISSING_INTERMEDIATE_CA",
      "error_detail": "Unable to find intermediate CA for CN=R3 (AIA fetching: False)",
      "resolved_chain": [
        "CN=checkout.zeli.shop"
      ],
      "aia_downloads": []
    }
  ]
}
```

- `summary` 통계 필드:
  - `total_scenarios`: 총 시나리오 수
  - `successful_verifications`: `status == "VERIFICATION_SUCCESS"`인 시나리오 수
  - `failed_verifications`: `status == "VERIFICATION_FAILED"`인 시나리오 수
  - `missing_intermediate_ca_errors`: `error == "MISSING_INTERMEDIATE_CA"`인 수
  - `expired_certificate_errors`: `error`가 `"CERTIFICATE_EXPIRED"` 또는 `"ROOT_CA_EXPIRED"`인 수

---

## 입출력 예시

### 예시 1

#### 입력
```json
{
  "client_trust_stores": {
    "modern_browser": [
      {
        "subject": "CN=ISRG Root X1",
        "valid_from": 1433376000,
        "valid_to": 1748995200
      },
      {
        "subject": "CN=DigiCert Global Root CA",
        "valid_from": 1163116800,
        "valid_to": 1952035200
      }
    ]
  },
  "intermediate_ca_repository": {
    "http://r3.i.lencr.org/": {
      "subject": "CN=R3",
      "issuer": "CN=ISRG Root X1",
      "valid_from": 1600000000,
      "valid_to": 1750000000
    }
  },
  "scenarios": [
    {
      "scenario_id": "desktop_browser_aia_success",
      "client_type": "modern_browser",
      "allow_aia_fetching": true,
      "current_time": 1650000000,
      "server_sent_chain": [
        {
          "cert_id": "leaf",
          "subject": "CN=checkout.zeli.shop",
          "issuer": "CN=R3",
          "valid_from": 1640000000,
          "valid_to": 1670000000,
          "aia_ca_issuers_url": "http://r3.i.lencr.org/"
        }
      ]
    },
    {
      "scenario_id": "mobile_app_no_aia_failure",
      "client_type": "modern_browser",
      "allow_aia_fetching": false,
      "current_time": 1650000000,
      "server_sent_chain": [
        {
          "cert_id": "leaf",
          "subject": "CN=checkout.zeli.shop",
          "issuer": "CN=R3",
          "valid_from": 1640000000,
          "valid_to": 1670000000,
          "aia_ca_issuers_url": "http://r3.i.lencr.org/"
        }
      ]
    }
  ]
}
```

#### 출력
```json
{
  "summary": {
    "total_scenarios": 2,
    "successful_verifications": 1,
    "failed_verifications": 1,
    "missing_intermediate_ca_errors": 1,
    "expired_certificate_errors": 0
  },
  "results": [
    {
      "scenario_id": "desktop_browser_aia_success",
      "client_type": "modern_browser",
      "status": "VERIFICATION_SUCCESS",
      "error": null,
      "error_detail": null,
      "resolved_chain": [
        "CN=checkout.zeli.shop",
        "CN=R3",
        "CN=ISRG Root X1"
      ],
      "aia_downloads": [
        {
          "url": "http://r3.i.lencr.org/",
          "downloaded_subject": "CN=R3"
        }
      ]
    },
    {
      "scenario_id": "mobile_app_no_aia_failure",
      "client_type": "modern_browser",
      "status": "VERIFICATION_FAILED",
      "error": "MISSING_INTERMEDIATE_CA",
      "error_detail": "Unable to find intermediate CA for CN=R3 (AIA fetching: False)",
      "resolved_chain": [
        "CN=checkout.zeli.shop"
      ],
      "aia_downloads": []
    }
  ]
}
```

---

### 예시 2

#### 입력
```json
{
  "client_trust_stores": {
    "modern_browser": [
      {
        "subject": "CN=ISRG Root X1",
        "valid_from": 1433376000,
        "valid_to": 1748995200
      }
    ]
  },
  "intermediate_ca_repository": {},
  "scenarios": [
    {
      "scenario_id": "mobile_with_fullchain",
      "client_type": "modern_browser",
      "allow_aia_fetching": false,
      "current_time": 1650000000,
      "server_sent_chain": [
        {
          "cert_id": "leaf",
          "subject": "CN=checkout.zeli.shop",
          "issuer": "CN=R3",
          "valid_from": 1640000000,
          "valid_to": 1670000000
        },
        {
          "cert_id": "intermediate",
          "subject": "CN=R3",
          "issuer": "CN=ISRG Root X1",
          "valid_from": 1600000000,
          "valid_to": 1750000000
        }
      ]
    }
  ]
}
```

#### 출력
```json
{
  "summary": {
    "total_scenarios": 1,
    "successful_verifications": 1,
    "failed_verifications": 0,
    "missing_intermediate_ca_errors": 0,
    "expired_certificate_errors": 0
  },
  "results": [
    {
      "scenario_id": "mobile_with_fullchain",
      "client_type": "modern_browser",
      "status": "VERIFICATION_SUCCESS",
      "error": null,
      "error_detail": null,
      "resolved_chain": [
        "CN=checkout.zeli.shop",
        "CN=R3",
        "CN=ISRG Root X1"
      ],
      "aia_downloads": []
    }
  ]
}
```
