# [ZeliJudge #019] C++을 검색했는데 왜 C가 나와?: URL 인코딩(Percent-Encoding)과 예약어의 배신

## 📌 문제 배경 스토리
테크 블로그 플랫폼 '젤리로그'의 신입 백엔드 개발자 젤리는 기술 태그 및 키워드 검색 API를 개발했습니다.
젤리는 검색 요청 URL을 조립할 때 파이썬의 f-string을 사용하여 다음과 같이 아주 단순하게 파라미터를 이어붙였습니다:

```python
# [젤리가 작성한 단순 URL 조립 코드]
def create_search_url(key, raw_value):
    return f"https://api.jellylog.io/search?{key}={raw_value}"
```

젤리는 생각했습니다:
*"파라미터 키 뒤에 등호(`=`) 붙이고 검색어를 그냥 붙이면 끝이지! 뭐 별거 있나?"*

하지만 사용자들이 다양한 프로그래밍 언어와 특수문자를 검색하기 시작하자마자 검색 엔진은 완전히 마비되었습니다:

1. **사용자가 `C++`를 검색했을 때**:
   - 젤리가 만든 URL: `https://api.jellylog.io/search?tag=C++`
   - 서버의 해석: 웹 표준에서 URL 쿼리의 `+` 기호는 **공백(Space)**을 의미합니다!
   - 결과: 서버는 태그를 `"C  "`(C 뒤에 공백 2개)로 읽어들여, `C++` 관련 글이 **단 한 개도 검색되지 않는 참사**가 터졌습니다!
2. **사용자가 `Tom & Jerry`를 검색했을 때**:
   - 젤리가 만든 URL: `https://api.jellylog.io/search?keyword=Tom & Jerry`
   - 서버의 해석: `&`는 쿼리 파라미터와 파라미터를 가르는 **구분자(Delimiter)**입니다!
   - 결과: 서버는 `keyword`를 `"Tom "`까지만 읽고, 뒤의 `" Jerry"`는 존재하지도 않는 엉뚱한 파라미터로 인식하여 버려버렸습니다!
3. **사용자가 `discount#1`을 검색했을 때**:
   - 젤리가 만든 URL: `https://api.jellylog.io/search?title=discount#1`
   - 브라우저의 해석: `#`은 웹페이지 내부의 스크롤 위치를 가리키는 **프래그먼트(Fragment)**입니다!
   - 결과: 브라우저는 `#` 뒤의 모든 문자열(`1`)을 **서버로 아예 전송조차 하지 않았습니다!**

CTO는 이 사태를 보고 젤리를 호출했습니다:
*"젤리 씨! URL은 전송 규약(RFC 3986)에 따라 특수 예약 문자(`+`, `&`, `#`, `=`, `/`, `?`, `%`, 공백 등)를 반드시 **`%` 뒤에 2자리 16진수 아스키 코드로 감싸는 퍼센트 인코딩(Percent-Encoding)**을 거쳐야 한다고요!"*
*"파이썬의 `urllib.parse.quote(val, safe='')`나 자바스크립트의 `encodeURIComponent()`를 쓰지 않고 날것 그대로 보내면, 데이터가 잘려나가고 엉뚱한 공백으로 왜곡됩니다!"*

CTO는 URL 전송 안전성을 검증하기 위해,
1. 표준 퍼센트 인코딩을 거쳐 안전하게 조립된 쿼리 문자열 (`ENCODED`)
2. 인코딩 없이 보냈을 때 서버와 브라우저가 오인식하여 훼손된 파라미터 값 (`NAIVE_CORRUPTED`)
3. 인코딩된 URL을 서버가 안전하게 디코딩하여 100% 온전히 복원한 파라미터 값 (`DECODED`)
세 가지 결과를 대조 분석하는 URL 검증 엔진을 구현하라고 지시했습니다.

---

## ⚙️ 시스템 동작 규칙

입력으로 파라미터 키 `<key>`와 원본 값 `<raw_value>`가 주어집니다.

### 1. 표준 퍼센트 인코딩 (`ENCODED`)
- RFC 3986 표준 비예약 문자(Unreserved Characters: 영문 대소문자 `a-z, A-Z`, 숫자 `0-9`, 밑줄 `_`, 하이픈 `-`, 마침표 `.`, 물결 `~`)를 제외한 모든 문자를 2자리 16진수 대문자 형태인 `%XX`로 인코딩합니다.
- 파이썬의 표준 라이브러리 `urllib.parse.quote(raw_value, safe='')`와 완벽히 동일합니다.
- 출력 형식: `ENCODED:<key>=<encoded_value>`

### 2. 순진한 전송 시의 데이터 왜곡 (`NAIVE_CORRUPTED`)
날것 그대로의 문자열을 URL 뒤에 붙여 전송했을 때, 웹 서버와 브라우저가 거치는 실제 파싱 규칙을 순차적으로 적용합니다:
1. **프래그먼트(`#`) 절단**: 문자열에 `#`이 포함되어 있다면, 첫 번째 `#`부터 그 뒤의 모든 문자는 브라우저에서 서버로 전송되지 않고 잘려나갑니다 (`raw_value.split('#')[0]`).
2. **파라미터 구분자(`&`) 절단**: 남아있는 문자열에 `&`가 포함되어 있다면, 쿼리 파라미터 구분자로 인식되므로 첫 번째 `&` 이전까지만 해당 키의 값으로 인정되고 뒤는 잘려나갑니다 (`.split('&')[0]`).
3. **더하기 기호(`+`)의 공백화**: 남아있는 문자열의 모든 `+` 기호는 URL 쿼리 스펙에 따라 공백(` `)으로 치환되어 디코딩됩니다 (`.replace('+', ' ')`).
- 출력 형식: `NAIVE_CORRUPTED:<key>=<corrupted_value>`

### 3. 정상 복원 디코딩 (`DECODED`)
- 퍼센트 인코딩된 문자열을 서버가 표준 디코딩하여 원본 데이터를 100% 온전하게 복원합니다 (`urllib.parse.unquote(encoded_value)`).
- 출력 형식: `DECODED:<key>=<decoded_value>`

---

## 📥 입력 형식 (Input)

- 첫째 줄에 쿼리의 총 개수 $Q$가 주어집니다. ($1 \le Q \le 10,000$)
- 둘째 줄부터 $Q$개의 줄에 걸쳐 각 파라미터가 다음 형식으로 주어집니다:
  `<key> <raw_value>`
- `<key>`는 공백 없는 1~20자의 영문 알파벳과 숫자로 구성되어 있습니다.
- `<key>`와 `<raw_value>` 사이는 단 하나의 공백으로 구분되며, `<raw_value>`는 공백, 특수문자 등을 포함할 수 있는 1~500자의 문자열입니다.

---

## 📤 출력 형식 (Output)

- 각 입력마다 다음 규격에 맞추어 정확히 3줄씩 출력합니다:
  `ENCODED:<key>=<encoded_value>`
  `NAIVE_CORRUPTED:<key>=<corrupted_value>`
  `DECODED:<key>=<decoded_value>`

---

## 💡 입출력 예제

### 예제 입력 1
```text
3
tag C++
keyword Tom & Jerry
title discount#1
```

### 예제 출력 1
```text
ENCODED:tag=C%2B%2B
NAIVE_CORRUPTED:tag=C  
DECODED:tag=C++
ENCODED:keyword=Tom%20%26%20Jerry
NAIVE_CORRUPTED:keyword=Tom 
DECODED:keyword=Tom & Jerry
ENCODED:title=discount%231
NAIVE_CORRUPTED:title=discount
DECODED:title=discount#1
```

### 예제 설명 1
- `tag C++`:
  - `ENCODED`: `+`가 `%2B`로 안전하게 인코딩되어 `C%2B%2B`가 됩니다.
  - `NAIVE_CORRUPTED`: `+`가 쿼리 공백으로 해석되어 `"C  "`(공백 2개)로 훼손됩니다.
  - `DECODED`: 인코딩 덕분에 원본 `"C++"`로 100% 복원됩니다.
- `keyword Tom & Jerry`:
  - `NAIVE_CORRUPTED`: `&`가 파라미터 구분자로 쪼개져 뒤쪽 `" Jerry"`가 통째로 증발하고 `"Tom "`만 남습니다.
- `title discount#1`:
  - `NAIVE_CORRUPTED`: `#`이 프래그먼트로 인식되어 `#1`이 서버로 전송조차 되지 않고 `"discount"`만 남습니다.
