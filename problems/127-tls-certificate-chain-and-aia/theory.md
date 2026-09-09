# TLS X.509 인증서 체인(Certificate Chain)과 누락된 중간 CA & AIA의 저주

> **"맥북 크롬 브라우저에서는 초록색 자물쇠가 완벽하게 뜨는데, 왜 모바일 앱(안드로이드/iOS)과 결제 백엔드에서는 `Trust anchor for certification path not found` 에러가 터지며 전면 마비될까요?!"**  
> HTTPS 인증서를 갱신한 직후 백엔드 개발자와 데브옵스 엔지니어를 패닉에 빠뜨리는 대표적인 실무 참사가 바로 **"누락된 중간 CA(Missing Intermediate CA)"** 문제입니다.

---

## 1. 신뢰의 사슬(Chain of Trust)이란 무엇인가?

HTTPS(TLS/SSL)의 보안은 **"내가 믿는 기관(Trust Anchor)이 보증한 녀석인가?"**를 확인하는 **신뢰의 사슬(Chain of Trust)** 구조로 이루어져 있습니다.

인증서는 단 한 장으로 동작하지 않고, 보통 3단계 계층 구조를 갖습니다:

```
[X.509 3계층 인증서 체인 구조]

┌─────────────────────────────────────────────────────────┐
│ 1. Root CA (최상위 인증기관, 예: ISRG Root X1)          │ <- OS/브라우저에 하드코딩 (Trust Store)
│    (Self-Signed: 자기 자신이 서명)                      │
└────────────────────────────┬────────────────────────────┘
                             │ 서명(Sign)
                             ▼
┌─────────────────────────────────────────────────────────┐
│ 2. Intermediate CA (중간 인증기관, 예: R3)              │ <- 서버가 함께 보내줘야 함!
│    (Root CA가 서명하여 발급한 중간 관리자)              │
└────────────────────────────┬────────────────────────────┘
                             │ 서명(Sign)
                             ▼
┌─────────────────────────────────────────────────────────┐
│ 3. Leaf / Server Certificate (서버 인증서)              │ <- 내 도메인 (checkout.zeli.shop)
│    (중간 CA가 최종 검증하여 발급한 내 도메인 인증서)   │
└─────────────────────────────────────────────────────────┘
```

### 왜 굳이 Root CA와 중간 CA를 나눌까?
Root CA의 비공개키(Private Key)가 유출되면 전 세계 수십억 대의 컴퓨터가 해킹 위험에 처합니다.  
따라서 Root CA의 개인키는 인터넷이 완전히 차단된 지하 금고(HSM)에 보관하며, 일상적인 웹사이트 인증서 발급은 **중간 CA(Intermediate CA)**에게 위임합니다.

---

## 2. 주니어의 치명적 실수: `cert.pem` vs `fullchain.pem`

인증기관(Let's Encrypt, DigiCert, Sectigo 등)에서 인증서를 발급받으면 보통 다음 파일들이 생성됩니다:

- `cert.pem`: 내 도메인용 **Leaf 인증서 1장**만 들어 있음.
- `chain.pem`: 상위 **중간 CA 인증서 1~2장**이 들어 있음.
- `fullchain.pem`: **`cert.pem` + `chain.pem`**을 위에서 아래로 이어 붙인 파일.

이때 Nginx 설정에서 다음과 같이 지정하면 대참사가 시작됩니다:

```nginx
# ❌ 절대 하지 말아야 할 설정 (중간 CA 누락!)
ssl_certificate /etc/letsencrypt/live/zeli.shop/cert.pem;

# ✅ 올바른 설정 (전체 체인 포함!)
ssl_certificate /etc/letsencrypt/live/zeli.shop/fullchain.pem;
```

---

## 3. 왜 PC 크롬에선 되고 모바일 앱에선 터질까?! (AIA Fetching의 비밀)

`cert.pem`만 설정해서 중간 CA가 누락되었는데도, 배포 전 개발자가 맥북 크롬으로 테스트하면 **초록색 자물쇠가 완벽하게 뜨며 정상 접속**됩니다!  
그러나 운영 배포 직후 모바일 앱에서는 다음과 같은 치명적인 에러가 터집니다:

```
javax.net.ssl.SSLHandshakeException: 
java.security.cert.CertPathValidatorException: 
Trust anchor for certification path not found.
```

### PC 브라우저가 사기(AIA Fetching)를 치는 이유
1. **AIA (Authority Information Access) 자동 다운로드**:
   - Leaf 인증서 내부에는 상위 발급기관의 인증서를 다운로드할 수 있는 HTTP URL(`CA Issuers`)이 적혀 있습니다.
   - 데스크톱 브라우저(Chrome, Safari, Edge)는 중간 CA가 누락되면, **사용자 몰래 백그라운드에서 AIA URL로 접속하여 누락된 중간 CA를 다운로드**하여 사슬을 완성합니다!
   - 또한 이전에 다른 사이트를 방문하면서 다운로드했던 중간 CA를 로컬 디스크에 캐시해 두고 재사용하기도 합니다.
2. **모바일 앱 & 백엔드 라이브러리(OkHttp, cURL, Java, Python)의 동작**:
   - 모바일 네이티브 네트워크 스택과 서버용 라이브러리는 **AIA Fetching을 일체 수행하지 않습니다**!
   - 이유 1: HTTPS 핸드셰이크 도중에 추가 HTTP 통신을 하면 지연 시간(Latency)이 수백 ms 증가함.
   - 이유 2: 중간 인증서를 평문 HTTP로 다운로드하는 과정에서 중간자 공격(MITM) 위험이 있음.
   - 따라서 서버가 중간 CA를 직접 건네주지 않으면 **즉시 핸드셰이크를 실패(Drop)** 처리합니다!

---

## 4. 트러스트 스토어(Trust Store)와 인증서 체인 검증 규칙

클라이언트는 서버가 건넨 인증서 체인을 다음 순서로 검증합니다:

1. **Leaf 인증서 확인**: 서버가 보낸 첫 번째 인증서가 내가 요청한 도메인과 일치하는가?
2. **유효 기간(Validity Period) 확인**: `valid_from <= current_time <= valid_to`
3. **서명 사슬 역추적 (Leaf $	o$ Intermediate $	o$ Root)**:
   - `curr.issuer == next.subject`가 성립하는 상위 인증서를 서버 체인에서 탐색.
   - 서버 체인에 없다면, 클라이언트의 `allow_aia_fetching`이 켜져 있을 때만 AIA URL을 통해 다운로드 시도.
4. **트러스트 앵커(Trust Anchor / Root CA) 도달 검증**:
   - 최종 상위 인증서가 클라이언트 기기의 **Trust Store(신뢰하는 루트 인증서 목록)**에 존재하는가?
   - 기기 Trust Store에 있다면 검증 성공 (`VERIFICATION_SUCCESS`)!
   - 어디에도 없다면 `MISSING_INTERMEDIATE_CA` 또는 `UNTRUSTED_ROOT_CA` 에러로 연결 차단!

---

## 5. 실무 엔지니어의 체크리스트

1. **Nginx / Apache / Traefik 설정 점검**:
   - 파일 이름이 `cert.pem`인지 `fullchain.pem`(또는 `bundle.crt`)인지 반드시 확인하라.
2. **터미널에서 체인 완성도 직접 검증하기**:
   ```bash
   openssl s_client -connect checkout.zeli.shop:443 -showcerts
   ```
   - 출력 결과에 Certificate chain이 최소 2개 이상(`0: s:... i:...`, `1: s:... i:...`) 떠야 정상입니다.
3. **SSL Labs 온라인 진단 도구 활용**:
   - `https://www.ssllabs.com/ssltest/`에서 진단하여 **"Chain issues: Incomplete"** 경고가 뜨는지 반드시 확인하라.
