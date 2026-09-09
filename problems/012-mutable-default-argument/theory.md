# [ZeliJudge CS 백서 #012] 남의 장바구니에 내 물건이 왜 있어?: 가변 기본 인자의 저주와 정의 시점(Definition Time)

> **"컴퓨터는 당신이 '의도'한 대로 움직이지 않는다. 당신이 '작성'한 대로, 그리고 '언어 런타임의 규칙'대로 움직일 뿐이다."**

---

## ☕ 1. 일상 비유: 낡은 머그컵 하나를 돌려 마시는 카페

어느 무인 카페의 사장님이 커피 자판기 소프트웨어를 만들었습니다.
사장님의 생각:
*"손님이 개인 텀블러를 가져오면 거기에 커피를 따라주고, 텀블러를 안 가져오면(`cup` 생략) 머신이 알아서 새 종이컵(`[]`)을 하나 꺼내서 따라주게 해야지!"*

```python
# 사장님이 짠 코드
def pour_coffee(flavor, cup=[]):
    cup.append(flavor)
    return cup
```

그런데 손님들이 몰려오자 끔찍한 일이 벌어졌습니다:
* 1번 손님이 와서 **"아메리카노"**를 뽑았습니다. (종이컵에 아메리카노 담김)
* 2번 손님이 와서 **"딸기 라떼"**를 뽑았습니다. 그런데 손님의 컵에 **"아메리카노 + 딸기 라떼"**가 섞여서 나왔습니다!
* 3번 손님이 와서 **"민트 초코"**를 뽑았습니다. 컵에는 **"아메리카노 + 딸기 라떼 + 민트 초코"**의 괴생명체 음료가 담겨 나왔습니다!

**왜 이런 일이 벌어졌을까요?**
자판기 제작업체가 사장님의 코드를 읽고 이렇게 기계를 만들었기 때문입니다:
> *"아, 기본 컵이 `[]`라고 적혀 있네? 그럼 **공장에서 자판기 만들 때 낡은 머그컵 하나를 출구에 딱 용접해 두고**, 손님이 개인 텀블러 안 가져오면 무조건 이 용접된 머그컵에 계속 부어버려야겠다!"*

이것이 바로 파이썬 역사상 가장 많은 초보자와 바이브 코더를 울린 **"가변 기본 인자의 함정 (Mutable Default Argument Trap)"**입니다.

---

## 🧠 2. 컴퓨터 과학의 핵심: 정의 시점(Definition Time) vs 호출 시점(Call Time)

인간의 뇌와 컴퓨터 인터프리터의 뇌는 코드를 읽는 방식이 완전히 다릅니다.

### 인간의 착각: "호출할 때마다 실행되겠지?"
초보 개발자는 함수 선언부를 보면서 이렇게 상상합니다:
> *"누군가 `pour_coffee('latte')`를 호출할 때마다, 파이썬이 `cup=[]`을 보고 '아, 빈 리스트를 새로 만들어야겠구나!' 하고 새 종이컵을 꺼내겠지?"*

### 파이썬 인터프리터의 진실: "def 문도 엄연한 1회성 실행문이다!"
파이썬에서 `def` 키워드는 컴파일러에게 주는 힌트가 아니라, **인터프리터가 그 줄을 읽는 순간 메모리에 객체를 만드는 실행문(Executable Statement)**입니다.

```text
[서버가 켜질 때 (Definition Time - 단 1회 실행)]
  1. 인터프리터가 `def pour_coffee(flavor, cup=[]):` 줄을 읽음
  2. 파이썬: "오, 기본값으로 `[]`가 있네? 힙(Heap) 메모리 0x1000 번지에 빈 리스트를 딱 1개 만들자!"
  3. 파이썬: "함수 객체를 만들고, `pour_coffee.__defaults__` 에 (0x1000,) 주소를 영구 박제하자!"

[손님이 100만 번 호출할 때 (Call / Runtime)]
  1. `pour_coffee('americano')` -> cup 인자가 없네? `__defaults__[0]` (0x1000) 가져와서 append!
  2. `pour_coffee('latte')`     -> cup 인자가 없네? `__defaults__[0]` (0x1000) 가져와서 append!
  3. `pour_coffee('mocha')`     -> cup 인자가 없네? `__defaults__[0]` (0x1000) 가져와서 append!
```

직접 파이썬 인터랙티브 셸에서 확인해 보면 충격적인 사실을 눈으로 볼 수 있습니다:

```python
def add(item, box=[]):
    box.append(item)
    return box

print(add.__defaults__)  # ([],) -> 함수의 숨겨진 속성에 기본 리스트가 박제되어 있음!

add("사과")
print(add.__defaults__)  # (['사과'],) -> 헉! 함수 자체의 기본 인자 속성이 오염됨!

add("바나나")
print(add.__defaults__)  # (['사과', '바나나'],) -> 전역 변수처럼 계속 누적됨!
```

---

## 🔒 3. 가변 객체(Mutable) vs 불변 객체(Immutable)

그렇다면 왜 `def calculate_discount(price, rate=0.1):` 같은 기본 인자는 아무 문제가 없을까요?

| 구분 | 자료형 (Data Types) | 기본 인자로 사용 시 동작 |
| :--- | :--- | :--- |
| **불변 객체 (Immutable)** | `int`, `float`, `str`, `bool`, `tuple`, `None` | **안전함**. 값을 변경하려 하면 새로운 객체가 메모리에 생성되어 변수에 재할당되므로, 기존 기본 객체는 오염되지 않음. |
| **가변 객체 (Mutable)** | `list`, `dict`, `set`, 클래스 인스턴스 | **치명적 위험!** `.append()`, `[key] = val` 같은 메서드가 기존 메모리 공간(In-place)을 직접 수정하므로 모든 호출자가 영구히 오염됨. |

```python
# [안전한 예시: 정수는 불변 객체]
def increment(count=0):
    count += 1  # count = count + 1 -> 기존 0을 바꾸는 게 아니라 새로운 정수 1을 만들어 가리킴!
    return count

increment() # 1
increment() # 1 (기본값 0은 오염되지 않고 그대로 유지됨!)
```

하지만 리스트나 딕셔너리는 **내부 내용물만 바꾸는 가변 객체(In-place Mutation)**이기 때문에, 기본값으로 사용하는 순간 보이지 않는 전역 싱글톤(Global Singleton) 변수가 되어버립니다.

---

## 💥 4. 실제 실무에서 터지는 보안 및 비즈니스 대참사

### 1) 관리자 권한 유출 참사
```python
def create_account(username, permissions=[]):
    if username == "admin":
        permissions.append("SUPER_ADMIN")
    return {"user": username, "perms": permissions}

admin = create_account("admin") # SUPER_ADMIN 획득!
hacker = create_account("hacker") # permissions 생략!
# 결과: hacker['perms'] 에 ['SUPER_ADMIN']이 그대로 들어있음!! 회원가입만으로 최고관리자 탈취!
```

### 2) 데이터 누수 및 결제 중복 사고
쇼핑몰 주문 시 장바구니를 `cart=[]`로 두었다가, 다른 사람의 카드 정보나 배송 주소가 다음 손님 화면에 노출되어 수억 원의 개인정보보호법 과징금을 두들겨 맞은 실제 사례들이 존재합니다.

---

## ✅ 5. 올바른 해결책: None Sentinel (센티넬 패턴)

파이썬 창시자 귀도 반 로섬(Guido van Rossum)과 파이썬 커뮤니티가 정립한 공식 표준 해결책은 **`None` 센티넬 패턴**입니다:

```python
# [정석: 불변 객체인 None을 기본값으로 두고, 함수 내부에서 동적 할당]
def add_to_cart(item, cart=None):
    if cart is None:
        cart = []  # ★ 함수가 호출될 때마다(Call Time) 독립된 새 리스트 생성!
    cart.append(item)
    return cart
```

### 왜 이 방식이 완벽할까요?
1. `None`은 **불변 객체(Immutable Singleton)**이므로 메모리 주소가 영구히 고정되어도 내용물이 오염될 수 없습니다.
2. `if cart is None:` 조건문은 함수가 **실제로 호출되는 순간(Call Time)** 실행되므로, 손님이 장바구니를 안 넘겨줬을 때만 그 자리에서 따끈따끈한 새 리스트 `[]`를 메모리에 생성합니다.
3. 만약 손님이 자신의 개인 바구니를 넘겨줬다면 `cart is None`이 거짓이 되므로 전달받은 개인 바구니를 그대로 사용합니다.

---

## 🎯 6. 요약: 바이브 코더가 꼭 기억해야 할 3원칙

1. **파이썬의 기본 인자(`arg=[]`)는 함수를 정의할 때 딱 한 번만 만들어진다.**
2. **함수 인자의 기본값으로 절대 `[]`, `{}`, `set()` 같은 가변(Mutable) 객체를 쓰지 마라.**
3. **가변 인자의 기본값은 무조건 `=None`으로 두고, 함수 본문 첫 줄에서 `if arg is None: arg = []` 로 생성하라.**
