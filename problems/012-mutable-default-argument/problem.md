# [ZeliJudge #012] 남의 장바구니에 내 물건이 왜 있어?: 가변 기본 인자(Mutable Default Argument)의 저주

## 📌 문제 배경 스토리
스타트업 '젤리마켓'의 신입 백엔드 개발자 젤리는 장바구니(Cart) 생성 및 상품 추가 API를 작성했습니다.
젤리는 코드를 깔끔하게 줄이기 위해 파이썬의 **함수 기본 인자(Default Argument)** 기능을 사용하여 다음과 같이 구현했습니다:

```python
# [젤리가 작성한 장바구니 추가 함수]
def add_to_cart(item, cart=[]):
    cart.append(item)
    return cart
```

젤리는 생각했습니다.
*"손님이 기존 장바구니를 넘겨주면 거기에 담고, 아무것도 안 넘겨주면(`cart` 생략) 파이썬이 알아서 빈 새 장바구니(`[]`)를 딱 만들어주겠지? 파이썬 짱이다!"*

하지만 프로덕션 서버에 배포된 직후, 고객센터는 발칵 뒤집혔습니다!
> **고객 A**: "오늘 처음 앱 켜서 장바구니 열었는데... 모르는 사람이 담은 기저귀 3팩이랑 삼겹살이 들어있어요!"
> **고객 B**: "제가 아이스크림 하나 담았는데, 결제창 누르니까 54명이 담은 상품 120개가 한꺼번에 결제됐어요! 사기꾼들아 내 돈 돌려내!"

CTO는 이 참사를 보고 즉시 젤리를 불러 호통을 쳤습니다:
*"젤리 씨! 파이썬에서 가변 객체(List, Dict, Set)를 함수의 기본 인자로 쓰면 무슨 일이 일어나는지 모릅니까?! 그 기본값 빈 리스트는 함수가 호출될 때 생기는 게 아니라, **서버가 켜지고 함수가 '정의(Define)'될 때 메모리에 딱 1개 생겨서 모든 손님이 영구히 공유하는 '공용 텀블러'**가 된다고요!"*

CTO는 시스템을 긴급 점검하기 위해, **버그가 있는 초기 시스템(`BUGGY`)**과 **올바르게 수정한 시스템(`FIXED`)**을 동일한 유저 요청 스트림에 대해 나란히 시뮬레이션하여 두 시스템 간의 상태 차이를 정밀하게 비교 분석하는 모니터링 엔진을 작성하라고 지시했습니다.

---

## ⚙️ 시스템 동작 규칙

각 손님(User)은 쇼핑을 시작할 때 장바구니를 개설하고, 물건을 담습니다.

### 1. 두 시스템의 함수 구현 차이
* **버그 시스템 (`BUGGY`)**:
  - 함수가 `def add_to_cart(item, cart=DEFAULT_OBJ):` 형태로 동작합니다.
  - `DEFAULT_OBJ`는 **최초에 단 한 번 생성된 공용 빈 리스트(`[]`)**입니다.
  - 손님이 `DEFAULT` 모드로 장바구니를 열면, 이 `DEFAULT_OBJ`의 참조를 그대로 할당받습니다.
  - 손님이 `PRIVATE` 모드로 장바구니를 열면, 손님만을 위한 `새로운 독립 리스트([])`를 생성하여 할당받습니다.
* **수정된 시스템 (`FIXED`)**:
  - 파이썬 관용구(Idiomatic Python)인 `cart=None` 센티넬 패턴으로 동작합니다.
  - 손님이 `DEFAULT` 모드로 열든, `PRIVATE` 모드로 열든, 각 손님은 **항상 자신만의 새로운 독립 리스트(`[]`)**를 개별적으로 할당받아 사용합니다.

### 2. 처리해야 할 5가지 명령
1. `OPEN <user_id> DEFAULT`
   - 해당 유저가 기본 장바구니를 사용하여 쇼핑을 시작합니다.
   - `BUGGY`: 유저의 장바구니는 공용 `DEFAULT_OBJ`를 가리킵니다.
   - `FIXED`: 유저의 장바구니는 독립된 새 리스트 `[]`를 가리킵니다.
2. `OPEN <user_id> PRIVATE`
   - 해당 유저가 전용 개인 장바구니를 명시적으로 생성하여 쇼핑을 시작합니다.
   - `BUGGY` 및 `FIXED` 모두: 유저만을 위한 새로운 독립 리스트 `[]`를 가리킵니다.
3. `ADD <user_id> <item>`
   - 해당 유저의 장바구니에 `<item>`을 추가합니다 (`cart.append(item)`).
   - 만약 유저가 다른 유저와 동일한 장바구니(메모리 객체)를 공유하고 있다면, 그 장바구니를 공유하는 모든 유저에게 추가된 아이템이 즉시 반영됩니다.
4. `COUNT <user_id>`
   - 해당 유저의 현재 장바구니에 담긴 아이템 총 개수를 출력합니다.
   - 출력 형식: `<user_id> BUGGY:<cnt_buggy> FIXED:<cnt_fixed>`
5. `CHECK_SAME <user1> <user2>`
   - 두 유저의 장바구니가 **물리적으로 동일한 메모리 객체(Same Object, Python의 `is` 연산자)**를 공유하고 있는지 확인합니다.
   - 동일 객체를 공유하고 있다면 `YES`, 서로 다른 독립 객체라면 `NO`를 출력합니다.
   - 출력 형식: `SAME_REF BUGGY:<YES/NO> FIXED:<YES/NO>`

---

## 📥 입력 형식 (Input)

- 첫째 줄에 쿼리의 총 개수 $Q$가 주어집니다. ($1 \le Q \le 100,000$)
- 둘째 줄부터 $Q$개의 줄에 걸쳐 위의 5가지 명령 중 하나가 주어집니다:
  - `OPEN <user_id> DEFAULT`
  - `OPEN <user_id> PRIVATE`
  - `ADD <user_id> <item>`
  - `COUNT <user_id>`
  - `CHECK_SAME <user1> <user2>`
- `<user_id>`와 `<item>`은 공백 없는 1~20자의 영문 대소문자 및 숫자로 이루어져 있습니다.
- `ADD`, `COUNT`, `CHECK_SAME`에 등장하는 유저는 이전에 최소 한 번 이상 `OPEN` 명령을 수행했음이 보장됩니다.
- 각 유저에 대한 `OPEN` 명령은 세션 동안 최초 1회만 주어집니다.

---

## 📤 출력 형식 (Output)

- `COUNT` 및 `CHECK_SAME` 명령이 주어질 때마다 지정된 형식으로 한 줄씩 출력합니다.
- `OPEN` 및 `ADD` 명령은 출력을 생성하지 않습니다.

---

## 💡 입출력 예제

### 예제 입력 1
```text
8
OPEN alice DEFAULT
ADD alice apple
OPEN bob DEFAULT
ADD bob banana
COUNT alice
COUNT bob
CHECK_SAME alice bob
OPEN charlie PRIVATE
```

### 예제 출력 1
```text
alice BUGGY:2 FIXED:1
bob BUGGY:2 FIXED:1
SAME_REF BUGGY:YES FIXED:NO
```

### 예제 설명 1
- `alice`가 `DEFAULT`로 열고 `apple`을 담았습니다.
- `bob`이 `DEFAULT`로 열고 `banana`를 담았습니다.
- **BUGGY 시스템**:
  - `alice`와 `bob`은 함수 정의 시점에 생성된 단 하나의 공용 리스트를 공유합니다!
  - 따라서 `bob`이 바나나를 담자 `alice`의 장바구니에도 바나나가 함께 들어가 총 **2개(`apple`, `banana`)**가 됩니다.
  - 두 사람의 장바구니는 물리적으로 완벽히 동일하므로 `CHECK_SAME` 결과 `YES`입니다.
- **FIXED 시스템**:
  - 두 사람 모두 `cart=None` 패턴을 통해 독립된 새 리스트를 받았으므로 각자 담은 **1개**만 존재하며, 동일 객체가 아니므로 `NO`입니다.

---

### 예제 입력 2
```text
9
OPEN userA DEFAULT
OPEN userB PRIVATE
ADD userA snack
ADD userB drink
CHECK_SAME userA userB
COUNT userA
COUNT userB
ADD userA ramen
COUNT userB
```

### 예제 출력 2
```text
SAME_REF BUGGY:NO FIXED:NO
userA BUGGY:1 FIXED:1
userB BUGGY:1 FIXED:1
userB BUGGY:1 FIXED:1
```

### 예제 설명 2
- `userB`는 `PRIVATE` 모드로 열었기 때문에 `BUGGY` 시스템에서도 독립된 리스트를 받았습니다.
- 따라서 `userA`와 `userB`는 `BUGGY`에서도 서로 다른 리스트를 참조하며, `userA`가 라면을 추가해도 `userB`의 카트에는 아무 영향이 없습니다.
