# [ZeliJudge #013] 256은 되고 257은 왜 안 돼?: 값(Equality)과 주소(Identity)의 배신 (is vs ==)

## 📌 문제 배경 스토리
핀테크 스타트업 '젤리페이'의 신입 백엔드 개발자 젤리는 결제 금액 검증 및 주문 상태 확인 모듈을 개발했습니다.
젤리는 파이썬 문법을 공부하던 중 `is` 연산자가 영어 문장처럼 읽혀서 가독성이 훨씬 좋다고 생각했습니다:

```python
# [젤리가 작성한 결제 검증 로직]
if user_amount is target_amount:
    approve_payment()

if order_status is "SUCCESS":
    send_receipt()
```

개발 서버에서 테스트할 때 젤리는 100원, 200원짜리 테스트 결제를 수없이 시도했고, 매번 100% 초록불로 결제가 깔끔하게 승인되었습니다!
자신감을 얻은 젤리는 코드를 프로덕션 운영 서버에 즉시 배포했습니다.

그러나 다음 날 아침, 젤리페이 본사는 고객들의 항의 전화로 마비되었습니다!
> **고객 A**: "250원짜리 사탕 결제는 잘 되는데, **300원** 결제하려고 하니까 '금액 불일치'라면서 계속 결제가 튕겨요!"
> **고객 B**: "10,000원 충전하려고 하는데 승인 거절 났습니다. 장난합니까?!"
> **가맹점 대표**: "주문 상태 코드가 `PAID`일 때는 영수증이 나가는데, 주문 코드가 `PAID-ONLINE`인 건 영수증이 단 하나도 안 나갔어요!"

긴급 투입된 시니어 아키텍트는 젤리의 코드를 보자마자 이마를 짚었습니다:
*"젤리 씨! `is`는 두 변수의 **값(Value)**이 같은지 비교하는 게 아니라, 두 변수가 **컴퓨터 메모리의 물리적 주소(Identity)**까지 동일한 단 하나의 객체인지 검사하는 포인터 비교 연산자입니다! CPython 인터프리터가 성능을 아끼려고 **`-5`부터 `256`까지의 정수**와 **기본 식별자 문자열**만 메모리에 미리 캐싱해 두기 때문에, 테스트할 때만 기적처럼 우연히 맞았던 거라고요!"*

CTO는 결제 엔진의 오판정 사고를 방지하기 위해,
1. `is`를 맹신하여 메모리 주소를 비교하는 **순진한 버그 검증기 (`NAIVE_IS`)**
2. `==`를 사용하여 데이터 내용물(값)을 비교하는 **정석 검증기 (`ACCURATE_EQ`)**
두 검증기의 판정 결과를 나란히 대조 분석하는 시뮬레이터를 구축하라고 명령했습니다.

---

## ⚙️ 시스템 동작 규칙

검증 시스템은 정수, 문자열, 리스트에 대해 다음과 같은 규칙으로 두 검증기의 결과를 도출합니다.

### 1. 정수 비교 (`INT <a> <b>`)
- **`ACCURATE_EQ` (값 비교, `a == b`)**:
  - 두 정수의 수치적 크기가 같으면 `YES`, 다르면 `NO`.
- **`NAIVE_IS` (메모리 주소 비교, `a is b`)**:
  - CPython의 **Small Integer Cache (-5 ~ 256)** 규칙을 엄격하게 따릅니다.
  - 두 정수의 값이 같고(`a == b`), 그 값이 **`-5` 이상 `256` 이하** (`-5 <= a <= 256`)라면 CPython 인터프리터가 미리 생성된 동일한 캐시 객체를 공유하므로 `YES`입니다.
  - 값이 다르거나, 값이 같더라도 **`-5` 미만이거나 `256`을 초과**하면 동적으로 별도의 힙 메모리 객체가 생성되어 주소가 다르므로 `NO`입니다.
- **출력 포맷**: `INT <a> <b> IS:<YES/NO> EQ:<YES/NO>`

### 2. 문자열 비교 (`STR <s> <t>`)
- **`ACCURATE_EQ` (값 비교, `s == t`)**:
  - 두 문자열의 글자 내용이 완벽히 일치하면 `YES`, 다르면 `NO`.
- **`NAIVE_IS` (메모리 주소 비교, `s is t`)**:
  - CPython의 **문자열 인터닝(String Interning)** 규칙을 엄격하게 따릅니다.
  - 두 문자열의 내용이 같고(`s == t`), 문자열이 **파이썬 식별자(Identifier) 규격**을 만족하는 경우(영문 알파벳, 숫자, 밑줄 `_`로만 구성됨, 예: `status.isidentifier() == True`) 인터닝 풀의 동일 객체를 공유하므로 `YES`입니다.
  - 글자 내용이 다르거나, 내용이 같더라도 하이픈(`-`), 골뱅이(`@`), 느낌표(`!`), 점(`.`), 슬래시(`/`) 등 **특수기호가 포함된 문자열**은 인터닝 대상이 아니므로 서로 다른 메모리 객체에 할당되어 `NO`입니다.
- **출력 포맷**: `STR <s> <t> IS:<YES/NO> EQ:<YES/NO>`

### 3. 리스트 비교 (`LIST <item1> <item2>`)
- 각 원소를 담은 독립된 단일 원소 리스트 객체 `list1 = [item1]`, `list2 = [item2]`를 생성하여 비교합니다.
- **`ACCURATE_EQ` (값 비교, `list1 == list2`)**:
  - 두 리스트 내부의 원소 값이 같으면(`item1 == item2`) `YES`, 다르면 `NO`.
- **`NAIVE_IS` (메모리 주소 비교, `list1 is list2`)**:
  - 파이썬에서 대괄호 리터럴(`[]`)로 생성된 가변 객체는 내용물이 무엇이든 **항상 독립된 새로운 힙 메모리 주소**를 가집니다.
  - 따라서 `item1`과 `item2`의 일치 여부와 무관하게 **항상 `NO`**입니다.
- **출력 포맷**: `LIST <item1> <item2> IS:NO EQ:<YES/NO>`

---

## 📥 입력 형식 (Input)

- 첫째 줄에 쿼리의 총 개수 $Q$가 주어집니다. ($1 \le Q \le 100,000$)
- 둘째 줄부터 $Q$개의 줄에 걸쳐 다음 3가지 명령 중 하나가 주어집니다:
  - `INT <a> <b>` ($-10^9 \le a, b \le 10^9$)
  - `STR <s> <t>` (공백 없는 1~50자의 문자열)
  - `LIST <item1> <item2>` (공백 없는 1~50자의 문자열 원소)

---

## 📤 출력 형식 (Output)

- 각 쿼리마다 명시된 규격에 맞추어 판정 결과를 한 줄씩 출력합니다:
  - `INT <a> <b> IS:<YES/NO> EQ:<YES/NO>`
  - `STR <s> <t> IS:<YES/NO> EQ:<YES/NO>`
  - `LIST <item1> <item2> IS:NO EQ:<YES/NO>`

---

## 💡 입출력 예제

### 예제 입력 1
```text
7
INT 100 100
INT 256 256
INT 257 257
INT -5 -5
INT -6 -6
INT 50 60
STR user_admin user_admin
```

### 예제 출력 1
```text
INT 100 100 IS:YES EQ:YES
INT 256 256 IS:YES EQ:YES
INT 257 257 IS:NO EQ:YES
INT -5 -5 IS:YES EQ:YES
INT -6 -6 IS:NO EQ:YES
INT 50 60 IS:NO EQ:NO
STR user_admin user_admin IS:YES EQ:YES
```

### 예제 설명 1
- `100`, `256`, `-5`는 CPython의 Small Integer Cache 범위(`-5 <= n <= 256`)에 포함되므로 `is`로 비교해도 우연히 `YES`가 나옵니다.
- 하지만 **`257`**과 **`-6`**은 범위 밖이므로, 값은 같지만(`EQ:YES`), 물리적 주소가 달라 `IS:NO`가 됩니다!
- `user_admin`은 영문자와 밑줄로만 이루어진 유효한 파이썬 식별자이므로 인터닝되어 `IS:YES EQ:YES`입니다.

---

### 예제 입력 2
```text
5
STR PAID PAID
STR PAID-ONLINE PAID-ONLINE
STR order@shop order@shop
LIST apple apple
LIST apple banana
```

### 예제 출력 2
```text
STR PAID PAID IS:YES EQ:YES
STR PAID-ONLINE PAID-ONLINE IS:NO EQ:YES
STR order@shop order@shop IS:NO EQ:YES
LIST apple apple IS:NO EQ:YES
LIST apple banana IS:NO EQ:NO
```

### 예제 설명 2
- `PAID`는 식별자 규격을 만족하므로 `IS:YES`입니다.
- 하지만 `PAID-ONLINE`과 `order@shop`은 하이픈(`-`)과 골뱅이(`@`)라는 특수문자가 섞여 있어 식별자가 아닙니다. 따라서 인터닝 대상이 아니며, 둘의 내용은 같지만 서로 다른 메모리 객체이므로 `IS:NO EQ:YES`가 됩니다!
- `LIST apple apple`은 내용물은 똑같은 사과이지만, 서로 다른 괄호(`[]`)로 생성된 독립 리스트이므로 물리적 주소가 달라 `IS:NO EQ:YES`가 됩니다.
