# [ZeliJudge #022] 로컬에선 되는데 왜 배포하니까 빨간 줄이 떠요?: CORS와 브라우저 Preflight (OPTIONS 정찰병)의 비극

## 📌 문제 배경 스토리
쇼핑몰 '젤리마켓'의 프론트엔드 개발자 젤리는 React로 멋진 쇼핑몰 웹앱을 개발하고, 백엔드는 FastAPI로 API 서버를 구축했습니다.
로컬 환경에서는 프론트와 백엔드가 한 컴퓨터에서 완벽하게 통신했습니다.
하지만 서비스를 실서버에 배포한 첫날, 대참사가 벌어졌습니다:

* 프론트엔드 주소: `https://jellymarket.com`
* 백엔드 API 주소: `https://api.jellymarket.com`

젤리가 배포된 사이트에 접속해 로그인 버튼을 누르는 순간, 브라우저 개발자 도구 콘솔창이 새빨간 에러 메시지로 도배되었습니다:
> 🔴 **`Access to fetch at 'https://api.jellymarket.com/login' from origin 'https://jellymarket.com' has been blocked by CORS policy: Response to preflight request doesn't pass access control check: No 'Access-Control-Allow-Origin' header is present on the requested resource.`**

젤리는 패닉에 빠졌습니다:
*"이상하다? Postman이나 터미널 `curl`로 API를 쏘면 데이터가 200 OK로 너무 잘 오는데, 왜 크롬 브라우저에서만 빨간 불이 뜨지?! 서버는 멀쩡한데 브라우저가 왜 내 데이터를 압수하는 거야?!"*

급하게 구글링을 한 젤리는 블로그를 보고 백엔드에 와일드카드 설정을 넣었습니다:
```python
# 블로그에서 본 엉터리 만병통치약 복사
allow_origins = ["*"]
allow_credentials = True
```
하지만 이번엔 더 끔찍한 에러가 터졌습니다:
> 🔴 **`The value of the 'Access-Control-Allow-Origin' header in the response must not be the wildcard '*' when the request's credentials mode is 'include'.`**

게다가 자신이 보내지도 않은 `OPTIONS` 요청이 백엔드로 날아가 `405 Method Not Allowed`를 뿜으며 본 요청(POST)은 시도조차 못 하고 브라우저 현관문에서 사살당했습니다!

CTO는 젤리를 진정시키며 말했습니다:
*"젤리 씨! CORS(Cross-Origin Resource Sharing)는 **서버를 지키는 기술이 아니라, 사용자 브라우저를 지키는 보안관**이에요!"*
*"사용자가 해커 사이트(`evil.com`)에 접속했을 때, 해커 사이트가 사용자의 브라우저 권한을 악용해 `bank.com`이나 `naver.com`의 개인정보를 몰래 fetch해가지 못하도록 브라우저가 출입국 심사를 하는 겁니다!"*
*"특히 `PUT`, `DELETE`나 `Authorization` 헤더 같은 위험한 요청은 브라우저가 본 요청을 쏘기 전에 **정찰병(`OPTIONS` Preflight 요청)**을 먼저 보내서 서버가 허락하는지 묻는데, 정찰병을 죽여버리니 통신이 될 리가 없죠!"*

CTO는 프론트엔드와 백엔드 간의 불필요한 CORS 삽질을 종식시키기 위해, 브라우저의 출입국 심사대 판정 엔진인 **CORS & Preflight 검증 시뮬레이터**를 개발하라고 지시했습니다.

---

## ⚙️ 시스템 동작 규칙

시스템은 백엔드 서버의 CORS 정책(`CONFIG`)을 입력받고, 클라이언트의 각 HTTP 요청(`REQ`)에 대해 브라우저의 출입국 심사 판정 결과를 시뮬레이션합니다.

### 1. 서버 CORS 정책 (`CONFIG`)
- `ORIGIN:<origins>`: 쉼표(`,`)로 구분된 허용 오리진 목록 또는 `*` (와일드카드)
  - 예: `https://jelly.com,https://admin.jelly.com` 또는 `*`
- `METHODS:<methods>`: 쉼표로 구분된 허용 HTTP 메서드 목록 또는 `*`
  - 예: `GET,POST,PUT,DELETE,OPTIONS` 또는 `*`
- `HEADERS:<headers>`: 쉼표로 구분된 허용 헤더 목록 (소문자) 또는 `*` 또는 `-` (없음)
  - 예: `authorization,content-type,x-api-key` 또는 `*` 또는 `-`
- `CREDENTIALS:<bool>`: `TRUE` 또는 `FALSE` (쿠키/인증정보 포함 허용 여부)

---

### 2. 요청 정보 (`REQ <origin> <method> <headers> <with_credentials>`)
- `<origin>`: 요청을 보낸 프론트엔드 웹사이트 출처 (예: `https://jelly.com`)
- `<method>`: 요청 HTTP 메서드 (대문자, 예: `GET`, `POST`, `PUT`, `DELETE` 등)
- `<headers>`: 요청에 포함된 헤더 목록 (소문자, 쉼표 구분, 없으면 `-`)
- `<with_credentials>`: 쿠키 및 인증 헤더 포함 여부 (`TRUE` 또는 `FALSE`)

---

### 3. 심사 1단계: 단순 요청 vs Preflight(정찰병) 판정
브라우저는 요청의 위험도를 평가하여 본 요청 전에 `OPTIONS` 정찰병을 보낼지 결정합니다:

- **안전 헤더(Safe Headers)**: `accept`, `accept-language`, `content-language`, `-`
- **단순 메서드(Simple Methods)**: `GET`, `HEAD`, `POST`
- **Preflight 발생 조건**:
  - `<method>`가 단순 메서드가 아니거나 (예: `PUT`, `DELETE`, `PATCH` 등),
  - 요청 헤더에 안전 헤더 이외의 헤더(예: `authorization`, `content-type`, `x-*` 등)가 1개라도 포함되어 있다면:
  - ──> **`PREFLIGHT_REQUIRED`**
- 위 두 조건에 모두 해당하지 않는 얌전한 요청인 경우:
  - ──> **`SIMPLE_REQUEST`**

---

### 4. 심사 2단계: 브라우저 보안 심사 (우선순위 순서대로 판정)
브라우저는 다음 순서대로 위반 사항을 검사하며, 가장 먼저 적발된 사유를 반환합니다:

1. **와일드카드 크레덴셜 금지 위반 (`BLOCKED_CREDENTIALS_WILDCARD`)**:
   - 요청의 `<with_credentials>`가 `TRUE`인데, 서버의 `ORIGIN` 설정이 `*`(와일드카드)인 경우.
   - (W3C 보안 표준: 인증정보를 포함할 때는 절대 와일드카드 `*` 출처를 허용할 수 없음!)
2. **출처(Origin) 미승인 위반 (`BLOCKED_ORIGIN_NOT_ALLOWED`)**:
   - 서버의 `ORIGIN`이 `*`가 아니면서, 요청의 `<origin>`이 서버의 허용 오리진 목록에 포함되어 있지 않은 경우.
3. **메서드(Method) 미승인 위반 (`BLOCKED_METHOD_NOT_ALLOWED`)**:
   - 서버의 `METHODS`가 `*`가 아니면서, 요청의 `<method>`가 서버의 허용 메서드 목록에 포함되어 있지 않은 경우.
4. **헤더(Header) 미승인 위반 (`BLOCKED_HEADER_NOT_ALLOWED`)**:
   - 요청에 포함된 헤더 중 안전 헤더(`accept`, `accept-language`, `content-language`, `-`)를 제외한 커스텀 헤더들에 대해:
   - 서버의 `HEADERS`가 `*`가 아니면서, 해당 헤더가 서버의 허용 헤더 목록에 없는 경우.
5. **승인 통과 (`ALLOWED`)**:
   - 위 모든 보안 검사를 무사히 통과한 경우.

---

## 📥 입력 형식 (Input)

- 첫째 줄에 서버의 CORS 설정이 주어집니다:
  `CONFIG ORIGIN:<origins> METHODS:<methods> HEADERS:<headers> CREDENTIALS:<bool>`
- 둘째 줄에 검증할 클라이언트 요청의 개수 $Q$가 주어집니다. ($1 \le Q \le 100,000$)
- 셋째 줄부터 $Q$개의 줄에 걸쳐 각 요청 정보가 주어집니다:
  `REQ <origin> <method> <headers> <with_credentials>`

---

## 📤 출력 형식 (Output)

- 각 요청에 대해 브라우저의 심사 결과를 한 줄씩 출력합니다:
  `CORS <TYPE> <RESULT>`
  - `<TYPE>`: `SIMPLE_REQUEST` 또는 `PREFLIGHT_REQUIRED`
  - `<RESULT>`: `ALLOWED` 또는 `BLOCKED_...` 에러 코드

---

## 💡 입출력 예시 (Example)

### 예시 입력 1
```text
CONFIG ORIGIN:https://jelly.com,https://admin.jelly.com METHODS:GET,POST,OPTIONS HEADERS:authorization,content-type CREDENTIALS:TRUE
5
REQ https://jelly.com GET - FALSE
REQ https://jelly.com POST authorization,content-type TRUE
REQ https://jelly.com DELETE - FALSE
REQ https://hacker.com GET - FALSE
REQ https://jelly.com POST x-custom-token FALSE
```

### 예시 출력 1
```text
CORS SIMPLE_REQUEST ALLOWED
CORS PREFLIGHT_REQUIRED ALLOWED
CORS PREFLIGHT_REQUIRED BLOCKED_METHOD_NOT_ALLOWED
CORS SIMPLE_REQUEST BLOCKED_ORIGIN_NOT_ALLOWED
CORS PREFLIGHT_REQUIRED BLOCKED_HEADER_NOT_ALLOWED
```

### 예시 설명 1
- 1번: `GET`, 헤더 없음, 출처 일치 -> 안전한 단순 요청 통과 (`SIMPLE_REQUEST ALLOWED`)
- 2번: `authorization` 헤더가 포함되어 Preflight 발동, 서버가 해당 헤더와 메서드를 승인하므로 통과 (`PREFLIGHT_REQUIRED ALLOWED`)
- 3번: `DELETE` 메서드는 단순 메서드가 아니므로 Preflight 발동, 하지만 서버의 허용 메서드에 `DELETE`가 없으므로 차단 (`PREFLIGHT_REQUIRED BLOCKED_METHOD_NOT_ALLOWED`)
- 4번: `https://hacker.com`은 허용 오리진이 아니므로 차단 (`SIMPLE_REQUEST BLOCKED_ORIGIN_NOT_ALLOWED`)
- 5번: `x-custom-token` 헤더는 서버 허용 헤더 목록에 없으므로 차단 (`PREFLIGHT_REQUIRED BLOCKED_HEADER_NOT_ALLOWED`)
