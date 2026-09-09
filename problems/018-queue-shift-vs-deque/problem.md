# [ZeliJudge #018] 롤러코스터 대기열과 50억 번의 발걸음: list.pop(0) vs collections.deque

## 📌 문제 배경 스토리
핀테크 스타트업 '젤리페이'의 신입 백엔드 개발자 젤리는 대형 테마파크의 롤러코스터 실시간 탑승 대기열(FIFO Queue) 관리 서버를 구축했습니다.
젤리는 파이썬 기초 문법책에서 리스트 자료형에 `append()`와 `pop(0)`이 있다는 것을 보고, 다음과 같이 아주 심플하게 대기열을 구현했습니다:

```python
# [젤리가 작성한 초간단 큐 모듈]
queue = []

def enqueue(user_id):
    queue.append(user_id)  # 대기열 맨 뒤에 줄 서기

def dequeue():
    return queue.pop(0)    # 맨 앞 0번 손님 탑승!
```

젤리는 생각했습니다:
*"파이썬 기본 리스트는 만능이니까 `pop(0)`을 쓰면 완벽한 선입선출(FIFO) 큐가 되겠지? 단 4줄 만에 큐 구현 끝!"*

로컬 개발 컴퓨터에서 10명, 20명으로 테스트할 때는 눈 깜짝할 사이에 0.001초 만에 동작했습니다.
그러나 테마파크 개장 첫날, 무려 **10만 명의 인파**가 몰려 대기열 등록과 탑승 요청이 쏟아지자마자, 서버의 CPU 점유율이 100%로 치솟으며 전산망이 완전히 얼어붙었습니다! 10만 명의 탑승 처리를 완료하는 데 수분이 넘게 걸리며 손님들의 거센 항의가 빗발쳤습니다.

긴급 투입된 시니어 시스템 엔지니어가 코드를 보자마자 이마를 짚었습니다:
*"젤리 씨! 파이썬의 `list`는 메모리에 물리적으로 따닥따닥 붙어 있는 **동적 배열(Dynamic Array)**입니다! 맨 앞 `0`번 원소를 빼내는 순간, 컴퓨터는 그 뒤에 서 있는 수만 명의 원소를 **전부 왼쪽 메모리 주소로 한 칸씩 낑낑대며 복사 이동(Memory Shift)**시킨다고요! 10만 명 대기열에서 `pop(0)`을 돌리면 내부적으로 **약 50억 번의 메모리 시프트($O(N^2)$)**가 발생해 CPU가 타버리는 겁니다!"*
*"큐를 만들 때는 양방향 연결 리스트(청크 블록)로 구현되어 포인터만 한 칸 슥 넘기는 **`collections.deque` ($O(1)$)**를 써야 합니다!"*

CTO는 이 성능 재앙의 심각성을 가시화하기 위해,
1. `list.pop(0)`을 사용할 때 매 Dequeue마다 발생하는 **내부 메모리 원소 시프트 횟수**를 누적 계산하는 **비효율적 시스템 (`NAIVE_LIST`)**
2. `collections.deque`를 사용하여 시프트 없이 $O(1)$로 즉시 처리하는 **최적화 시스템 (`OPTIMIZED_DEQUE`)**
두 시스템의 상태를 모니터링하고 낭비된 총 시프트 횟수를 실시간 계측하는 벤치마크 엔진을 구현하라고 지시했습니다.

---

## ⚙️ 시스템 동작 규칙

대기열은 선입선출(FIFO) 방식으로 동작합니다.

### 1. 처리해야 할 3가지 명령
1. `ENQUEUE <user_id>`
   - 대기열 맨 뒤에 새로운 손님 `<user_id>`를 추가합니다.
   - 원소 추가는 맨 뒤에서 이루어지므로 시프트가 발생하지 않습니다 (시프트 0회).
2. `DEQUEUE`
   - 대기열 맨 앞의 손님을 1명 탑승(제거)시킵니다.
   - 만약 대기열이 비어 있다면 아무 일도 일어나지 않습니다 (시프트 0회).
   - 대기열에 손님이 $K$명 있는 상태에서 맨 앞 손님이 제거되면:
     - **`NAIVE_LIST`**: 맨 앞 0번 원소가 빠져나가면서, **뒤에 서 있던 $K - 1$명의 손님이 전부 앞으로 한 칸씩 이동(Memory Shift)**합니다!
       따라서 이 작업 1회당 발생하는 원소 시프트 횟수는 **$K - 1$**회이며, 이를 누적 시프트 카운터(`total_shifts`)에 가산합니다.
     - **`OPTIMIZED_DEQUE`**: 포인터만 한 칸 이동하므로 물리적 원소 이동이 전혀 발생하지 않습니다 (시프트 0회).
3. `STATUS`
   - 현재 시점에서 대기열 상태를 다음 포맷으로 한 줄에 출력합니다:
     `STATUS QUEUE_LEN:<len> TOTAL_SHIFTS:<total_shifts>`
     - `<len>`: 현재 대기열에 남아있는 총 손님 수
     - `<total_shifts>`: 지금까지 수행된 모든 `DEQUEUE` 작업으로 인해 `NAIVE_LIST`에서 발생한 총 누적 원소 이동 횟수

---

## 📥 입력 형식 (Input)

- 첫째 줄에 쿼리의 총 개수 $Q$가 주어집니다. ($1 \le Q \le 100,000$)
- 둘째 줄부터 $Q$개의 줄에 걸쳐 다음 3가지 명령 중 하나가 주어집니다:
  - `ENQUEUE <user_id>`
  - `DEQUEUE`
  - `STATUS`
- `<user_id>`는 공백 없는 1~20자의 영문 대소문자 및 숫자로 이루어져 있습니다.

---

## 📤 출력 형식 (Output)

- `STATUS` 명령이 주어질 때마다 지정된 규격으로 한 줄씩 출력합니다.

---

## 💡 입출력 예제

### 예제 입력 1
```text
7
ENQUEUE userA
ENQUEUE userB
ENQUEUE userC
DEQUEUE
STATUS
DEQUEUE
STATUS
```

### 예제 출력 1
```text
STATUS QUEUE_LEN:2 TOTAL_SHIFTS:2
STATUS QUEUE_LEN:1 TOTAL_SHIFTS:3
```

### 예제 설명 1
- `userA`, `userB`, `userC` 3명이 줄을 섭니다 (대기열 길이: 3).
- 1번째 `DEQUEUE`:
  - `userA`가 빠지면서 뒤에 있던 `userB`, `userC` 2명이 한 칸씩 앞으로 이동합니다.
  - 시프트 횟수: $3 - 1 = 2$회 발생 (누적 시프트: 2, 남은 대기열: 2).
  - `STATUS` -> `STATUS QUEUE_LEN:2 TOTAL_SHIFTS:2`
- 2번째 `DEQUEUE`:
  - `userB`가 빠지면서 뒤에 있던 `userC` 1명이 한 칸 앞으로 이동합니다.
  - 시프트 횟수: $2 - 1 = 1$회 발생 (누적 시프트: $2 + 1 = 3$, 남은 대기열: 1).
  - `STATUS` -> `STATUS QUEUE_LEN:1 TOTAL_SHIFTS:3`

---

### 예제 입력 2
```text
6
DEQUEUE
STATUS
ENQUEUE solo
STATUS
DEQUEUE
STATUS
```

### 예제 출력 2
```text
STATUS QUEUE_LEN:0 TOTAL_SHIFTS:0
STATUS QUEUE_LEN:1 TOTAL_SHIFTS:0
STATUS QUEUE_LEN:0 TOTAL_SHIFTS:0
```

### 예제 설명 2
- 빈 대기열에서의 `DEQUEUE`는 시프트를 발생시키지 않습니다.
- 손님이 1명만 있을 때 `DEQUEUE`를 하면 뒤에 따라올 손님이 없으므로 시프트는 $1 - 1 = 0$회입니다.
