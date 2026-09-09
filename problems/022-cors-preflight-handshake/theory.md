# [ZeliJudge 백서 #022] 로컬에선 되는데 왜 배포하니까 빨간 줄이 떠요?: CORS와 브라우저 Preflight (OPTIONS 정찰병)의 비극

> **"Postman에서는 200 OK로 잘만 오는데 브라우저에서만 빨간 에러가 뜬다면, 서버가 고장 난 게 아니라 브라우저라는 보안관이 당신의 데이터를 압수한 것입니다."**

---

## 1. 💡 비전공자 바이브 코더를 위한 현실 비유: "출입국 심사대와 정찰병"

많은 초보 개발자가 착각합니다:  
*"CORS 에러가 떴으니 백엔드 서버가 내 요청을 거절한 건가 봐!"*

아닙니다! 백엔드 서버 로그를 보면 사실 **200 OK로 정상 응답을 보낸 상태**입니다!  
데이터를 중간에서 가로채 압수하고 콘솔에 빨간 불을 켠 범인은 바로 **당신의 웹 브라우저(크롬, 사파리)**입니다.

```text
[상황 비유]
당신이 사기꾼 사이트(evil.com)에 실수로 접속했습니다.
사기꾼 사이트의 자바스크립트가 당신 몰래 백그라운드에서 네이버 메일(mail.naver.com)의 편지함을 조회하려고 합니다!

1. 사기꾼 사이트: "네이버 서버야, 이 사용자의 받은 편지함 내용 좀 줘!"
2. 네이버 서버: "어? 쿠키도 정상이고 정당한 회원이네? 여기 편지함 데이터 200 OK!" (데이터를 브라우저로 쏴줌)
3. 브라우저 보안관(출입국 심사관) 출동!:
   "잠깐! 네이버 서버가 보낸 도장을 확인해 볼까? 'Access-Control-Allow-Origin: https://evil.com' 도장이 없잖아!"
   "사기꾼 사이트 놈아! 너한테는 이 소중한 편지함 데이터를 절대 넘겨줄 수 없다! 압수!!" ──> 🔴 CORS Error 발생!
```

즉, **CORS(Cross-Origin Resource Sharing)는 서버를 지키는 게 아니라, 사용자 브라우저의 개인정보를 지키는 보호막**입니다!

---

## 2. 🔍 출처(Origin)란 무엇인가?: 삼위일체 원칙

웹 브라우저는 다음 세 가지가 **토씨 하나 틀리지 않고 100% 일치**해야만 "동일 출처(Same Origin)"로 인정합니다:

```text
https://api.jellymarket.com:443/login
└──┬──┘  └────────┬───────┘  └─┬─┘
 프로토콜       도메인(Host)      포트(Port)
 (Scheme)
```

| 프론트엔드 출처 | 백엔드 API 출처 | 판정 | 이유 |
|---|---|---|---|
| `http://localhost:3000` | `http://localhost:8000` | ❌ **Cross-Origin** | 포트 번호 다름 (3000 vs 8000) |
| `https://jelly.com` | `http://jelly.com` | ❌ **Cross-Origin** | 프로토콜 다름 (HTTPS vs HTTP) |
| `https://jelly.com` | `https://api.jelly.com` | ❌ **Cross-Origin** | 서브 도메인 다름 |
| `https://jelly.com` | `https://jelly.com/api` | ✅ **Same-Origin** | 경로(Path)만 다를 뿐 삼위일체 일치! |

---

## 3. 🕵️‍♂️ 정찰병 (Preflight Request - HTTP OPTIONS)의 비밀

단순한 `GET` 요청은 데이터만 가져오므로 안전하지만, `PUT`, `DELETE`나 `Authorization` 토큰이 들어간 요청은 **서버의 DB를 삭제하거나 변경할 수 있는 치명적인 요청**입니다.

따라서 브라우저는 위험한 본 요청을 보내기 전에, 먼저 가벼운 **정찰병(Preflight Request)**을 보내 서버의 허락을 구합니다:

```text
[1단계: 정찰병 출격 (OPTIONS)]
브라우저 ─── OPTIONS /users/1 (저기... DELETE 메서드랑 Authorization 헤더 써도 되나요?) ───> 백엔드

[2단계: 백엔드의 승인 도장]
백엔드  ─── 200 OK (Allow-Origin: jelly.com, Allow-Methods: DELETE, Allow-Headers: Authorization) ───> 브라우저

[3단계: 안심하고 본 요청 전송]
브라우저 ─── DELETE /users/1 ───────────────────────────────────────────────────────────> 백엔드
```

### 💥 정찰병 암살 참사 (405 Method Not Allowed)
백엔드 개발자가 `OPTIONS` 메서드에 대한 응답 처리를 하지 않거나 CORS 미들웨어를 빼먹으면:
- 백엔드는 정찰병에게 `404 Not Found` 또는 `405 Method Not Allowed`를 던져버립니다!
- 정찰병이 사살당했으므로, 브라우저는 본 요청(`DELETE`)을 **아예 전송조차 하지 않고 취소**합니다!

---

## 4. ⚠️ 실무 1위 함정: 와일드카드(`*`)와 `credentials`의 모순

개발자들이 가장 많이 하는 실수:
```python
# ❌ 절대 불가능한 모순 설정!
allow_origins = ["*"]
allow_credentials = True  # 쿠키, 세션, Authorization 헤더 동반
```

- `allow_origins = ["*"]`: "전 세계 모든 사이트에게 문을 활짝 열어주겠다!"
- `allow_credentials = True`: "사용자의 신분증(쿠키, 로그인 세션)도 같이 동봉하겠다!"

만약 이 모순된 설정이 통과된다면, 악성 해커 사이트가 사용자의 로그인 쿠키를 실어서 사용자 모르게 송금이나 결제를 실행할 수 있게 됩니다.
따라서 W3C 보안 규격은 **`credentials: true`일 때 `allow_origins`에 `*`를 적으면 브라우저가 무조건 통신을 거부**하도록 못 박아 두었습니다!

✅ **해결책**:
`allow_origins`에 `*` 대신 **정확한 프론트엔드 도메인(`https://jellymarket.com`)**을 명시해야 합니다!

---

## 5. 🎯 요약 및 핵심 한 줄
> **"CORS 에러는 서버 에러가 아니라 브라우저의 보호 조치다. 정확한 출처를 명시하고, 정찰병(OPTIONS)에게 친절한 허가 도장을 찍어주어라!"**
