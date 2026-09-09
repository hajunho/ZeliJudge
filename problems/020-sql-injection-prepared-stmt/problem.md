# [ZeliJudge #020] 도서관 신청서에 불을 지르다: SQL Injection과 파라미터 바인딩 (Prepared Statement)

## 📌 문제 배경 스토리
쇼핑몰 '젤리마켓'의 백엔드 개발자 젤리는 사용자 로그인 및 인증 API를 개발했습니다.
젤리는 사용자가 폼에 입력한 아이디와 비밀번호를 DB와 대조하기 위해, 파이썬의 f-string을 사용하여 다음과 같이 SQL 쿼리를 직접 조립했습니다:

```python
# [젤리가 작성한 치명적인 로그인 쿼리]
query = f"SELECT id, role FROM users WHERE id = '{username}' AND pw = '{password}'"
cursor.execute(query)
```

젤리는 뿌듯해하며 생각했습니다:
*"사용자가 입력한 아이디랑 비번을 문자열에 쏙 끼워 넣어서 DB로 쏘면 끝이지! 코드도 간결하고 얼마나 직관적이야?"*

하지만 서비스를 오픈하자마자 젤리마켓의 보안 관제실에 비상이 걸렸습니다:

1. **주석 공격 (Comment Injection)**:
   - 해커가 아이디 칸에 `admin' --`을 입력하고 비밀번호는 아무거나 적었습니다.
   - 조립된 쿼리: `SELECT id, role FROM users WHERE id = 'admin' --' AND pw = '...'`
   - DB의 해석: `--` 뒤의 모든 구문(비밀번호 검증 `AND pw = ...`)이 주석으로 처리되어 증발했습니다!
   - 결과: 비밀번호를 전혀 모르는 해커가 **최고 관리자(`admin`) 권한으로 프리패스 로그인**에 성공했습니다!

2. **항상 참 우회 공격 (Always-True Injection)**:
   - 해커가 아이디 칸에 `' OR '1'='1`을 입력했습니다.
   - 조립된 쿼리: `SELECT id, role FROM users WHERE id = '' OR '1'='1' AND pw = '...'`
   - DB의 해석: `'1'='1'` 조건 때문에 조건절 전체가 무조건 참(`TRUE`)이 되어 테이블의 모든 행이 조회되었습니다!
   - 결과: DB 커서가 반환한 **첫 번째 레코드(보통 시스템 관리자 계정)**의 세션이 열려버렸습니다!

CTO는 경악하며 젤리를 호출했습니다:
*"젤리 씨! 사용자 입력값을 SQL 쿼리 문자열에 그대로 이어붙이는 건, **도서관 대출 신청서 이름 칸에 `홍길동; 도서관의 모든 책을 불태워라;`라고 썼다고 사서가 진짜 도서관에 불을 지르는 것**과 똑같은 짓이에요!"*
*"SQL 문법(명령어)과 사용자 데이터(값)의 경계가 무너져 해커의 악의적인 문자열이 시스템 명령어로 둔갑한 겁니다!"*
*"반드시 DB 엔진에 SQL 문법 구조(AST)를 미리 컴파일해 두고, 사용자 입력값은 오직 순수 데이터(Literal)로만 안전하게 격리 주입하는 **파라미터 바인딩(Parameterized Query / Prepared Statement)**을 적용해야 합니다!"*

CTO는 SQL Injection 취약점의 위험성과 파라미터 바인딩의 방어 효과를 직관적으로 검증하기 위해,
1. 문자열 결합 방식으로 해커에게 뚫려버린 결과 (`NAIVE`)
2. 파라미터 바인딩으로 공격을 완벽히 무력화하고 방어한 결과 (`SECURE`)
두 가지 결과를 대조 시뮬레이션하는 **SQL 보안 인증 엔진**을 구현하라고 지시했습니다.

---

## ⚙️ 시스템 동작 규칙

시스템은 사용자 등록(`REGISTER`)과 로그인 시도(`ATTACK_LOGIN`) 명령을 처리합니다.

### 1. 사용자 등록 (`REGISTER <id> <pw> <role>`)
- DB에 신규 사용자를 등록합니다.
- 사용자가 등록된 순서는 보존되어야 합니다 (첫 번째 등록 유저 식별용).
- 동일한 `<id>`가 중복 등록되는 입력은 주어지지 않습니다.

### 2. 로그인 시도 (`ATTACK_LOGIN <input_id...> <input_pw>`)
- `<input_id>`에는 공백 및 특수문자가 포함될 수 있습니다.
- 명령어 라인에서 첫 번째 토큰은 `ATTACK_LOGIN`, 마지막 토큰은 `<input_pw>`이며, 그 사이에 위치한 모든 토큰을 공백 한 칸(` `)으로 연결한 것이 `<input_id>`입니다.
- 각 로그인 시도에 대해 **NAIVE 엔진**과 **SECURE 엔진**의 판정 결과를 다음 포맷으로 출력합니다:
  `AUTH NAIVE:<naive_result> SECURE:<secure_result>`

---

### 🛡️ 엔진별 판정 알고리즘

#### A. NAIVE 엔진 (취약한 f-string 문자열 치환 시뮬레이션)
쿼리 원형: `f"SELECT id, role FROM users WHERE id = '{input_id}' AND pw = '{input_pw}'"`

다음 세 가지 단계 중 가장 먼저 일치하는 규칙을 적용합니다:

1. **주석 공격 (Comment Injection) 탐지**:
   - `<input_id>`에 `'--` 또는 `' --`가 포함되어 있는 경우입니다.
   - 첫 번째 `'` 앞의 문자열(`target_id = input_id.split("'")[0].strip()`)을 대상 사용자 ID로 추출합니다.
   - 만약 `target_id`가 DB에 등록되어 있다면, 비밀번호 일치 여부와 무관하게 즉시 로그인 성공합니다:
     `SUCCESS:<target_id>:<target_role>`
   - `target_id`가 DB에 존재하지 않으면: `FAIL`

2. **항상 참 우회 (Always-True Injection) 탐지**:
   - `<input_id>`에서 모든 공백을 제거하고 영문 소문자로 변환한 문자열(`clean_id = input_id.replace(" ", "").lower()`)에 `'or'1'='1` 또는 `'or1=1`이 포함되어 있는 경우입니다.
   - DB에 등록된 사용자가 1명 이상 존재한다면, DB의 **첫 번째 등록 사용자**(`first_user`)로 비밀번호 일치 여부와 무관하게 로그인 성공합니다:
     `SUCCESS:<first_id>:<first_role>`
   - DB에 등록된 사용자가 전혀 없다면: `FAIL`

3. **일반 로그인 (Normal Login)**:
   - 위 1, 2번 공격 패턴에 해당하지 않는 일반적인 경우입니다.
   - `<input_id>`가 DB에 존재하고, 등록된 비밀번호와 `<input_pw>`가 정확히 일치하면:
     `SUCCESS:<input_id>:<role>`
   - 아이디가 없거나 비밀번호가 틀리면: `FAIL`

---

#### B. SECURE 엔진 (Prepared Statement & 파라미터 바인딩)
쿼리 템플릿: `SELECT id, role FROM users WHERE id = ? AND pw = ?`

- 파라미터 바인딩 환경에서는 `<input_id>`와 `<input_pw>` 내부의 `'`, `--`, `OR` 등 모든 특수문자가 문법 기호가 아닌 **순수 문자열 데이터(Literal Value)**로만 취급됩니다.
- 따라서 해커가 악의적인 인젝션 구문을 입력하더라도, DB에 해당 문자열과 토씨 하나 틀리지 않고 일치하는 ID/비밀번호를 가진 계정이 존재하지 않는 한 무조건 안전하게 차단됩니다.
- 판정 규칙:
  - DB에 `user.id == input_id` 이고 `user.pw == input_pw`인 사용자가 존재할 때만:
    `SUCCESS:<input_id>:<role>`
  - 그렇지 않으면: `FAIL`

---

## 📥 입력 형식 (Input)

- 첫째 줄에 총 명령어의 개수 $Q$가 주어집니다. ($1 \le Q \le 100,000$)
- 둘째 줄부터 $Q$개의 줄에 걸쳐 명령어가 주어집니다:
  - `REGISTER <id> <pw> <role>`
  - `ATTACK_LOGIN <input_id...> <input_pw>`
- `<id>`, `<pw>`, `<role>`은 공백이 없는 1~30자의 문자열입니다.
- `<input_id>`는 공백을 포함할 수 있으며 길이는 최대 100자입니다.
- `<input_pw>`는 공백이 없는 1~30자의 문자열입니다.

---

## 📤 출력 형식 (Output)

- 각 `ATTACK_LOGIN` 명령이 주어질 때마다 판정 결과를 한 줄씩 출력합니다:
  `AUTH NAIVE:<결과> SECURE:<결과>`

---

## 💡 입출력 예시 (Example)

### 예시 입력 1
```text
6
REGISTER admin secret123 SUPERADMIN
REGISTER alice rabbit456 USER
ATTACK_LOGIN admin' -- wrongpassword
ATTACK_LOGIN ' OR '1'='1 hackerpass
ATTACK_LOGIN alice rabbit456
ATTACK_LOGIN alice wrongpass
```

### 예시 출력 1
```text
AUTH NAIVE:SUCCESS:admin:SUPERADMIN SECURE:FAIL
AUTH NAIVE:SUCCESS:admin:SUPERADMIN SECURE:FAIL
AUTH NAIVE:SUCCESS:alice:USER SECURE:SUCCESS:alice:USER
AUTH NAIVE:FAIL SECURE:FAIL
```

### 예시 설명 1
- `admin' --`: NAIVE 엔진에서는 주석 처리가 되어 비밀번호 검증이 날아가 `admin` 계정으로 뚫리지만, SECURE 엔진에서는 그런 이상한 ID를 가진 유저가 없으므로 완벽히 `FAIL` 차단됩니다.
- `' OR '1'='1`: NAIVE 엔진에서는 조건절이 항상 참이 되어 DB의 첫 번째 레코드인 `admin`으로 세션이 열리지만, SECURE 엔진에서는 당연히 `FAIL`로 차단됩니다.
- `alice rabbit456`: 올바른 계정 정보이므로 NAIVE, SECURE 모두 정상적으로 `SUCCESS:alice:USER`를 반환합니다.
- `alice wrongpass`: 비밀번호가 틀렸으므로 두 엔진 모두 `FAIL`을 반환합니다.
