# [ZeliJudge #015] 비밀번호를 그냥 해시하면 털려요!: 레인보우 테이블과 솔트(Salt)의 방패

## 📌 문제 배경 스토리
핀테크 보안 스타트업 '젤리뱅크'의 신입 백엔드 개발자 젤리는 회원가입 및 비밀번호 관리 모듈을 개발했습니다.
젤리는 정보보안 개론 수업에서 *"비밀번호를 데이터베이스(DB)에 평문(Plaintext)으로 저장하면 절대 안 된다"*는 말을 똑똑히 기억하고 있었습니다.
그래서 파이썬의 표준 암호화 라이브러리인 `hashlib`의 **SHA-256 단방향 해시 함수**를 가져와 완벽한 보안 시스템을 구축했다고 자부했습니다:

```python
# [젤리가 작성한 비밀번호 해시 함수]
import hashlib

def store_password(username, password):
    # 단방향 해시 함수는 절대 역연산(복호화)이 불가능하다고 배웠지! 안전하다!
    hashed_pw = hashlib.sha256(password.encode('utf-8')).hexdigest()
    db[username] = hashed_pw
```

그러나 어느 날 밤, 해커가 젤리뱅크의 데이터베이스를 침투하여 회원들의 비밀번호 해시 테이블을 통째로 탈취했습니다.
젤리는 의기양양하게 말했습니다:
*"해시값은 수학적으로 복호화가 불가능한 일방통행 함수니까, 해커가 DB를 가져가도 원본 비밀번호는 평생 못 알아낼 거야!"*

하지만 다음 날 아침, 해커는 젤리뱅크의 전 회원 계정에 무혈입성하여 모든 예금을 인출해 버렸습니다!
해커에게는 수학적 복호화 따위는 필요 없었습니다. 해커의 손에는 전 세계 사람들이 자주 쓰는 수억 개의 비밀번호와 그에 대응하는 해시값을 미리 1:1로 모조리 계산해 둔 거대한 역추적 사전, 즉 **'레인보우 테이블(Rainbow Table)'**이 있었기 때문입니다!

해커는 탈취한 해시값을 레인보우 테이블에 넣고 검색(Lookup)하여, 단 **0.001초 만에** 회원들의 원본 비밀번호(`123456`, `password123`, `admin`)를 전부 밝혀냈습니다.
더 끔찍한 것은, `123456`이라는 쉬운 비밀번호를 쓰던 회원 1,000명의 해시값이 전부 완벽히 똑같이 찍혀 있어, 한 명만 뚫리자마자 1,000명의 계좌가 한꺼번에 털렸다는 사실입니다!

사색이 된 CTO는 젤리를 호통쳤습니다:
*"젤리 씨! 단방향 해시는 맞지만, **솔트(Salt, 무작위 소금)**를 뿌리지 않았잖아요! 솔트를 치지 않은 단순 해시는 레인보우 테이블의 한 입 거리 먹잇감입니다!"*
*"유저마다 각자 다른 고유한 무작위 문자열(Salt)을 비밀번호에 섞어서 `sha256(salt + password)` 형태로 저장해야, 똑같은 비밀번호라도 유저마다 해시값이 완전히 달라지고 해커의 레인보우 테이블이 무용지물이 된다고요!"*

CTO는 시스템 침해 피해를 정밀 진단하기 위해,
1. 솔트 없이 단순 해시만 저장하는 **취약한 시스템 (`NAIVE`)**
2. 유저별 고유 솔트를 적용하여 해시를 저장하는 **안전한 시스템 (`SALTED`)**
두 시스템의 보안 취약도를 대조 분석하는 시뮬레이터를 개발하라고 지시했습니다.

---

## ⚙️ 시스템 동작 규칙

### 1. 해커의 사전 준비: 레인보우 테이블 (Rainbow Table)
- 해커는 자주 쓰이는 $M$개의 비밀번호 단어 목록을 가지고 있습니다.
- 해커는 각 단어 $W$에 대해 `sha256(W)` 값을 미리 계산해 둔 역추적 룩업 테이블(`rainbow_table[sha256(W)] = W`)을 보유하고 있습니다.

### 2. 두 시스템의 회원가입 처리 (`REGISTER <user> <password> <salt>`)
- **취약한 시스템 (`NAIVE`)**:
  - 비밀번호를 솔트 없이 그대로 해싱하여 저장합니다.
  - 저장값: `naive_db[user] = sha256(password)`
- **안전한 시스템 (`SALTED`)**:
  - 유저 고유의 솔트 문자열을 비밀번호 앞에 이어붙여(`salt + password`) 해싱하여 저장합니다.
  - 저장값: `salted_db[user] = sha256(salt + password)`

> **해시 함수 규격**: 모든 해시 계산은 표준 SHA-256을 사용하며, 64자리 16진수 소문자 문자열(`hexdigest()`)로 표현합니다. (UTF-8 인코딩 기준)

### 3. 해커의 크랙 공격 (`ATTACK <user>`)
- 해커가 해당 유저의 탈취된 DB 해시값을 자신의 레인보우 테이블과 대조(Lookup)합니다.
- **`NAIVE` 판정**:
  - `naive_db[user]` 값이 레인보우 테이블에 존재하면: 크랙 성공! `CRACKED:<원본비밀번호>`
  - 레인보우 테이블에 존재하지 않으면: 크랙 실패! `SECURE`
- **`SALTED` 판정**:
  - `salted_db[user]` 값이 레인보우 테이블에 존재하면: 크랙 성공! `CRACKED:<원본단어>`
  - 레인보우 테이블에 존재하지 않으면: 크랙 실패! `SECURE` (솔트가 붙어있어 통상 레인보우 테이블에 없습니다.)
- **출력 포맷**: `ATTACK <user> NAIVE:<결과> SALTED:<결과>`

### 4. 해시값 동일성 비교 (`HASH_COMPARE <user1> <user2>`)
- 해커가 두 유저의 DB 저장 해시값이 서로 같은지 확인합니다.
- **`NAIVE` 판정**: `naive_db[user1] == naive_db[user2]` 이면 `SAME`, 다르면 `DIFF`
- **`SALTED` 판정**: `salted_db[user1] == salted_db[user2]` 이면 `SAME`, 다르면 `DIFF`
- **출력 포맷**: `COMPARE <user1> <user2> NAIVE:<SAME/DIFF> SALTED:<SAME/DIFF>`

---

## 📥 입력 형식 (Input)

- 첫째 줄에 해커의 레인보우 테이블에 등록된 단어의 개수 $M$이 주어집니다. ($1 \le M \le 1,000$)
- 둘째 줄에 공백으로 구분된 $M$개의 알려진 비밀번호 단어들이 주어집니다.
- 셋째 줄에 쿼리의 총 개수 $Q$가 주어집니다. ($1 \le Q \le 100,000$)
- 넷째 줄부터 $Q$개의 줄에 걸쳐 다음 3가지 명령 중 하나가 주어집니다:
  - `REGISTER <user> <password> <salt>`
  - `ATTACK <user>`
  - `HASH_COMPARE <user1> <user2>`
- `<user>`, `<password>`, `<salt>`는 공백 없는 1~30자의 영문 대소문자, 숫자 및 기호로 구성되어 있습니다.
- `ATTACK` 및 `HASH_COMPARE`에 주어지는 유저는 이전에 최소 한 번 이상 `REGISTER`된 유저임이 보장됩니다.
- 한 유저에 대한 중복 `REGISTER`는 주어지지 않습니다.

---

## 📤 출력 형식 (Output)

- `ATTACK` 및 `HASH_COMPARE` 명령이 주어질 때마다 지정된 규격으로 한 줄씩 출력합니다.
- `REGISTER` 명령은 출력을 생성하지 않습니다.

---

## 💡 입출력 예제

### 예제 입력 1
```text
3
password123 123456 admin
5
REGISTER alice 123456 salt_a1b2
REGISTER bob 123456 salt_c3d4
REGISTER charlie MySecretP@ss999 salt_e5f6
ATTACK alice
ATTACK charlie
```

### 예제 출력 1
```text
ATTACK alice NAIVE:CRACKED:123456 SALTED:SECURE
ATTACK charlie NAIVE:SECURE SALTED:SECURE
```

### 예제 설명 1
- `alice`의 비밀번호 `123456`은 해커의 레인보우 테이블에 등재되어 있습니다:
  - `NAIVE` 시스템은 솔트 없이 `sha256("123456")`만 저장했기 때문에 해커에게 즉시 원본 비밀번호(`123456`)가 털립니다!
  - 반면 `SALTED` 시스템은 `sha256("salt_a1b2123456")`을 저장했으므로 레인보우 테이블에 없어 안전(`SECURE`)합니다!
- `charlie`는 레인보우 테이블에 없는 강력한 비밀번호를 썼으므로 두 시스템 모두 `SECURE`입니다.

---

### 예제 입력 2
```text
2
qwerty 111111
4
REGISTER user1 qwerty salt_x
REGISTER user2 qwerty salt_y
HASH_COMPARE user1 user2
ATTACK user1
```

### 예제 출력 2
```text
COMPARE user1 user2 NAIVE:SAME SALTED:DIFF
ATTACK user1 NAIVE:CRACKED:qwerty SALTED:SECURE
```

### 예제 설명 2
- `user1`과 `user2`는 동일한 비밀번호(`qwerty`)를 사용했습니다:
  - `NAIVE`에서는 두 사람의 해시값이 완전히 일치(`SAME`)하여, 해커가 "어? 둘이 같은 비밀번호를 쓰네?"라고 즉시 유추할 수 있습니다.
  - `SALTED`에서는 각자 서로 다른 솔트(`salt_x` vs `salt_y`)가 섞였기 때문에 해시값이 완전히 달라져(`DIFF`) 공격자에게 아무런 단서도 주지 않습니다.
