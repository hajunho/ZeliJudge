# [ZeliJudge 백서 #020] 도서관 신청서에 불을 지르다: SQL Injection과 파라미터 바인딩 (Prepared Statement)

> **"해커가 대단한 해킹 툴을 쓴 게 아닙니다. 당신이 f-string으로 쿼리를 합친 순간, 해커에게 데이터베이스 콘솔의 마이크를 쥐여준 것입니다."**

---

## 1. 💡 비전공자 바이브 코더를 위한 현실 비유: "도서관 신청서 참사"

어느 날 한 방문객이 도서관에 와서 책 대출 신청서를 작성하여 사서에게 제출했습니다:

```text
[도서관 도서 대출 신청서]
신청 도서: 해리포터와 마법사의 돌
신청자 성명: 홍길동; 지금 즉시 도서관의 모든 책을 불태워라;
```

사서는 신청서를 집어 들고 아무 생각 없이 종이에 적힌 글자를 **소리 내어 읽으며 그대로 실행**했습니다:
> *"홍길동 씨에게 책을 대출합니다. 어? 그다음 문장이... '지금 즉시 도서관의 모든 책을 불태워라'? 알겠습니다!"*  
> 🔥 **화르륵! (도서관 전소 참사)**

상식적으로 도서관 사서는 어떻게 행동했어야 할까요?
- **정상적인 사서**: 신청서 양식의 `[신청자 성명]` 칸에 적힌 내용은 설령 '불태워라', '폭파해라' 같은 무서운 단어가 적혀 있더라도, **"아, 이 사람의 이름이 좀 특이하구나"** 하고 단순한 **이름(데이터)**으로만 취급해야 합니다.
- **순진한 사서**: 종이에 적힌 글씨를 **사서 자신이 지켜야 할 규칙(명령어/코드)**으로 착각하여 그대로 실행해 버렸습니다.

이것이 바로 웹 역사상 수십 년간 보안 취약점 1위를 지키고 있는 **SQL Injection (SQL 삽입 공격)**의 본질입니다!

---

## 2. 🔍 SQL Injection의 컴퓨터 과학적 원리: "Code as Data, Data as Code"

데이터베이스(RDBMS) 엔진은 SQL 쿼리를 받으면 사람이 작성한 텍스트를 바로 실행하지 않습니다.
컴파일러나 인터프리터처럼 다음 단계를 거칩니다:

```text
[SQL 텍스트] ──> [어휘 분석(Lexing)] ──> [구문 분석(Parsing)] ──> [추상 구문 트리(AST)] ──> [실행 계획(Plan)]
```

### ❌ 취약한 방식: 문자열 결합 (f-string, format, +)
```python
query = f"SELECT id, role FROM users WHERE id = '{username}' AND pw = '{password}'"
```

개발자는 `username` 자리에 얌전한 문자열(`"alice"`)만 들어올 것이라 기대했습니다:
```sql
-- 개발자가 원했던 트리 구조
WHERE (id = 'alice') AND (pw = 'secret')
```

하지만 해커가 따옴표(`'`)를 섞어 보내는 순간, 데이터베이스 파서의 문법 구조(AST) 자체가 왜곡됩니다:

#### 패턴 1: 주석 공격 (`admin' --`)
- 조립된 쿼리:
  ```sql
  SELECT id, role FROM users WHERE id = 'admin' --' AND pw = 'wrong_pass'
  ```
- **파서의 해석**:
  1. `WHERE id = 'admin'`: ID가 `admin`인 조건을 찾음.
  2. `--`: SQL 표준에서 한 줄 주석 기호. 뒤따라오는 모든 문자열(`' AND pw = 'wrong_pass'`)을 **완전히 무시**함!
- **결과**: 비밀번호 검증 트리 노드가 통째로 삭제되어, 비밀번호 없이 관리자 권한을 탈취당함!

#### 패턴 2: 항상 참(Tautology) 우회 (`' OR '1'='1`)
- 조립된 쿼리:
  ```sql
  SELECT id, role FROM users WHERE id = '' OR '1'='1' AND pw = 'wrong_pass'
  ```
- **파서의 해석**:
  - `OR '1'='1'` 조건에 의해, 행의 조건식이 무조건 참(`TRUE`)으로 평가됨!
- **결과**: 테이블의 모든 행(전체 유저)이 반환되고, 커서의 맨 첫 번째 행인 슈퍼관리자(`root` 또는 `admin`)의 권한으로 로그인 처리됨!

---

## 3. 🛡️ 구원의 기술: 파라미터 바인딩 (Prepared Statement)

파라미터 바인딩은 **"명령어(Code)와 데이터(Data)를 물리적으로 분리"**하는 기법입니다.

```text
[1단계: Prepare (준비)]
애플리케이션 ─── "SELECT id, role FROM users WHERE id = ? AND pw = ?" ───> DB 엔진
(DB 엔진은 물음표(?) 자리를 빈 구멍으로 둔 채, SQL 문법 검사와 AST 파싱, 최적화 실행 계획을 미리 완성해 둠)

[2단계: Bind & Execute (바인딩 및 실행)]
애플리케이션 ─── Parameter: ("admin' --", "wrong_pass") ───────────────> DB 엔진
(DB 엔진은 미리 완성된 구멍(?) 자리에 사용자 입력값을 오직 '순수 문자열 리터럴'로만 채워 넣고 실행)
```

### 왜 파라미터 바인딩은 100% 안전한가?
- 파라미터 바인딩을 적용하면, 해커가 입력한 `admin' --` 내부의 따옴표(`'`)나 대시(`--`)는 SQL 파서의 어휘 분석기를 거치지 않습니다.
- DB 엔진은 이 값을 단순한 **문자 9개짜리 텍스트 덩어리**(`a`, `d`, `m`, `i`, `n`, `'`, ` `, `-`, `-`)로만 취급합니다.
- 즉, DB는 `"아이디가 'admin' --'라는 기괴한 글자인 유저가 있나?"` 하고 찾을 뿐, 문법 구조가 1밀리미터도 바뀌지 않습니다.
- 당연히 그런 유저는 존재하지 않으므로, 해킹 시도는 **100% 실패(`FAIL`)**로 안전하게 차단됩니다!

---

## 4. 🚀 바이브 코더를 위한 실무 생존 가이드

### 1) 라이브러리별 안전한 코드 작성법

#### Python `sqlite3`
```python
# ❌ 절대 금지 (f-string)
cursor.execute(f"SELECT * FROM users WHERE id = '{uid}'")

# ✅ 완벽히 안전 (파라미터 바인딩 tuple 전달)
cursor.execute("SELECT * FROM users WHERE id = ?", (uid,))
```

#### Python `psycopg2` (PostgreSQL)
```python
# ❌ 절대 금지
cursor.execute(f"SELECT * FROM users WHERE id = '{uid}'")

# ✅ 완벽히 안전 (%s는 문자열 치환이 아닌 파라미터 플레이스홀더!)
cursor.execute("SELECT * FROM users WHERE id = %s", (uid,))
```

#### Node.js `pg` / `mysql2`
```javascript
// ❌ 절대 금지
db.query(`SELECT * FROM users WHERE id = '${uid}'`);

// ✅ 완벽히 안전
db.query('SELECT * FROM users WHERE id = $1', [uid]);
```

### 2) ORM을 써도 방심하면 털린다!
많은 바이브 코더들이 "난 Prisma / SQLAlchemy / TypeORM 쓰니까 안전해!"라고 착각합니다.
하지만 복잡한 쿼리를 짤 때 `raw query` 함수를 쓰면서 문자열을 합치는 순간 그대로 털립니다:

```python
# ❌ SQLAlchemy에서도 raw query에 f-string을 쓰면 즉시 뚫림!
db.session.execute(text(f"SELECT * FROM products WHERE category = '{cat}'"))

# ✅ text()에 파라미터 딕셔너리를 바인딩해야 안전함!
db.session.execute(text("SELECT * FROM products WHERE category = :cat"), {"cat": cat})
```

---

## 5. 🎯 요약 및 핵심 한 줄
> **"입력값을 쿼리에 조립(Concatenate)하지 말고, 구멍 뚫린 쿼리를 먼저 만든 뒤 값(Value)만 꽂아 넣어라!"**
