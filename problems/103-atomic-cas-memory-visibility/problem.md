# [CS-103] CPU 캐시 가시성(Memory Visibility)과 Atomic CAS (Lock-Free 동시성 제어)

> **"선생님! 변수에 `volatile` 키워드를 붙여서 멀티스레드 가시성을 확보했는데, 100만 번 카운터를 올렸더니 최종 숫자가 왜 73만인가요?!"**
> 
> 주니어 개발자 민우는 동시성 프로그래밍을 공부하다가 "스레드들이 CPU 코어 캐시(L1/L2)를 공유하지 않고 각자 캐시된 값을 읽어 변경사항이 안 보일 수 있으니 `volatile`을 쓰라"는 글을 보았습니다.
> 이에 자신 있게 전역 카운터 변수에 `volatile`을 붙이고 스레드 10개로 각 10만 번씩 총 100만 번 `count++`를 돌렸습니다.
> 하지만 결과는 처참했습니다. 1,000,000이 나와야 할 숫자가 734,219로 심각하게 깎여 누락된 것입니다!
> 
> "가시성을 확보했는데 왜 숫자가 유실되죠?!"  
> 시니어 아키텍트는 칠판에 분필로 숫자 하나를 쓰며 씩 웃었습니다.
> "민우 씨, `volatile`은 칠판 글씨를 아주 또렷하게 실시간으로 보여주는 안경일 뿐이에요. 두 사람이 동시에 칠판을 보고 '0이네? 1 더해서 1 적어야지' 하고 동시에 1을 적어버리면, 두 번 적었는데도 숫자는 1이 되잖아요?"

---

## 1. 문제 배경과 현실 비유: 교실 칠판과 분필

우리가 아무 생각 없이 작성하는 한 줄의 코드 `count++`는 CPU 입장에서는 결코 하나의 명령어가 아닙니다.
내부적으로는 무려 **3단계(Read-Modify-Write)** 로 나뉘어 실행됩니다.

1. **Read (읽기)**: 메모리/캐시에서 `count` 값을 CPU 레지스터로 읽어옵니다 (`MOV EAX, [count]`).
2. **Modify (연산)**: 레지스터의 값을 1 증가시킵니다 (`ADD EAX, 1`).
3. **Write (쓰기)**: 레지스터의 결과를 다시 메모리/캐시로 덮어씁니다 (`MOV [count], EAX`).

### 칠판과 두 학생의 참사 (Race Condition)
- 현재 칠판에 적힌 숫자: `0`
- 학생 A와 B가 동시에 칠판으로 달려옵니다.
- [동시 Read]: 학생 A도 `0`을 보고, 학생 B도 `0`을 봅니다.
- [동시 Modify]: 학생 A도 머릿속으로 `0 + 1 = 1`을 계산하고, 학생 B도 `0 + 1 = 1`을 계산합니다.
- [동시 Write]: 학생 A가 칠판을 지우고 `1`을 씁니다. 바로 뒤이어 학생 B도 칠판을 지우고 `1`을 씁니다.
- 결과: 분명 두 학생이 각각 한 번씩 더했으므로 `2`가 되어야 하지만, 칠판에는 여전히 `1`이 적혀 있습니다. 한 번의 연산이 영원히 사라져버린 **갱신 분실(Lost Update)** 참사가 일어난 것입니다!

### `volatile`의 한계와 착각
- `volatile`은 컴파일러 최적화로 인한 변수 레지스터 캐싱을 막고, 항상 L1/L2/메모리 계층의 최신 값을 직접 읽고 쓰게(가시성, Visibility) 강제합니다.
- 하지만 읽고(Read) 계산하고(Modify) 쓰는(Write) 3단계 자체를 하나의 묶음으로 쪼개지지 않게(원자성, Atomicity) 만들어주지는 못합니다!

### 하드웨어의 해결책: Compare-And-Swap (CAS)
- 무거운 뮤텍스 락(`synchronized`, `mutex`)을 걸어 스레드를 재우는(OS Context Switching 페널티 발생) 대신, CPU 레벨의 원자적 명령어인 `LOCK CMPXCHG`를 사용합니다.
- **"내가 아까 볼 때 칠판 숫자가 0이었는데, 지금도 여전히 0이니? 그렇다면 1로 바꾸고 성공(True)을 반환해! 만약 그 사이에 딴 놈이 바꿔서 0이 아니라면 아무것도 건드리지 말고 실패(False)를 반환해!"**
- 만약 실패했다면? 포기하지 않고 최신 칠판 숫자를 다시 읽어서 성공할 때까지 뺑뺑이를 돕니다(**스핀 루프, Spin-Retry Loop**). 이것이 바로 `AtomicInteger`, `AtomicLong`의 핵심 동작 원리입니다!

---

## 2. 요구사항 및 명령어 사양

당신은 멀티스레드 환경의 메모리 가시성과 원자성을 시뮬레이션하는 `MemorySimulator` 엔진을 구현해야 합니다.
표준 입력(`stdin`)으로 들어오는 명령어들을 한 줄씩 파싱하여 정확한 형식으로 표준 출력(`stdout`)에 출력하십시오.

### 지원 명령어 목록

1. `INIT_VAR <var_name> <initial_value>`
   - 메모리에 변수 `<var_name>`을 생성하고 `<initial_value>`로 초기화합니다.
   - 출력: `INIT_VAR <var_name>=<initial_value>`

2. `EXEC_UNSAFE_INCREMENT <var_name> <threads> <operations_per_thread>`
   - 비원자적(Unsafe, 동기화 없는 `volatile count++`) 동시성 증가를 시뮬레이션합니다.
   - 총 시도 횟수 `expected = threads * operations_per_thread`
   - $N$개의 스레드가 동시에 `count++`의 Read-Modify-Write 단계를 실행할 때 경합이 발생합니다.
     - 각 라운드($1 \dots operations\_per\_thread$)마다 $threads$개의 스레드가 동시에 변수의 동일한 현재 값을 읽습니다.
     - 모든 스레드가 `현재값 + 1`을 계산하여 차례로 쓰기를 시도하지만, 결과적으로 해당 라운드에서는 단 1번의 증가만 최종 반영됩니다.
     - 따라서 실제 반영된 증가량 `actual_increment = operations_per_thread * 1` (threads >= 1인 경우)이 되며, 유실된 업데이트는 `lost_updates = expected - actual_increment`가 됩니다.
   - 변수의 값은 `현재값 + actual_increment`로 갱신됩니다.
   - 성공률 `success_rate = (actual_increment / expected) * 100` (소수점 둘째 자리까지 반올림 포맷 `%.2f`).
   - 출력: `UNSAFE_RESULT var=<var_name> expected=<expected> actual=<actual_increment> lost_updates=<lost_updates> success_rate=<success_rate>%`

3. `EXEC_ATOMIC_INCREMENT <var_name> <threads> <operations_per_thread>`
   - 하드웨어 CAS 루프 기반의 완전 무결 원자적 증가(`AtomicInteger.incrementAndGet()`)를 시뮬레이션합니다.
   - 총 시도 횟수 `expected = threads * operations_per_thread`
   - 모든 연산은 CAS 스핀 루프를 통해 단 하나의 유실도 없이 $100\%$ 반영됩니다: `actual_increment = expected`.
   - 충돌(Collision) 및 재시도 횟수 모델링:
     - $threads$개의 스레드가 동시에 1회 증가를 시도할 때, 정확히 1개의 스레드만 첫 번째 시도에서 CAS 성공하고 나머지 $threads - 1$개의 스레드는 충돌하여 실패 후 재시도합니다.
     - 전체 라운드 동안 발생하는 총 CAS 성공 횟수는 정확히 `cas_successes = expected`입니다.
     - 발생하는 총 CAS 재시도(Retry) 횟수는 `cas_retries = (threads - 1) * operations_per_thread`입니다.
   - 변수의 값은 `현재값 + expected`로 갱신됩니다.
   - 출력: `ATOMIC_RESULT var=<var_name> expected=<expected> actual=<expected> cas_successes=<expected> cas_retries=<cas_retries> lost_updates=0`

4. `CAS <var_name> <expected_val> <new_val>`
   - 명시적인 단일 Compare-And-Swap 연산을 수행합니다.
   - 현재 `<var_name>`의 값이 `<expected_val>`과 일치하면:
     - 변수 값을 `<new_val>`로 즉시 변경하고 성공을 출력합니다.
     - 출력: `CAS_SUCCESS var=<var_name> old=<expected_val> new=<new_val>`
   - 일치하지 않으면:
     - 값을 변경하지 않고 현재 값을 함께 출력합니다.
     - 출력: `CAS_FAILED var=<var_name> expected=<expected_val> actual=<current_val>`

5. `STATS <var_name>`
   - 해당 변수의 현재 저장된 값을 출력합니다.
   - 출력: `STATS var=<var_name> current_val=<current_val>`

---

## 3. 입출력 예시

### 예시 입력 1
```text
INIT_VAR counter 0
EXEC_UNSAFE_INCREMENT counter 4 100
STATS counter
INIT_VAR atomic_counter 0
EXEC_ATOMIC_INCREMENT atomic_counter 4 100
STATS atomic_counter
CAS atomic_counter 400 999
CAS atomic_counter 400 1000
STATS atomic_counter
```

### 예시 출력 1
```text
INIT_VAR counter=0
UNSAFE_RESULT var=counter expected=400 actual=100 lost_updates=300 success_rate=25.00%
STATS var=counter current_val=100
INIT_VAR atomic_counter=0
ATOMIC_RESULT var=atomic_counter expected=400 actual=400 cas_successes=400 cas_retries=300 lost_updates=0
STATS var=atomic_counter current_val=400
CAS_SUCCESS var=atomic_counter old=400 new=999
CAS_FAILED var=atomic_counter expected=400 actual=999
STATS var=atomic_counter current_val=999
```

---

## 4. 실무 핵심 요약 (Architecture Takeaway)

1. **가시성(Visibility) vs 원자성(Atomicity)**
   - `volatile`은 CPU 코어의 로컬 캐시를 거치지 않고 메인 메모리와 직접 동기화하도록 강제하여 "다른 스레드가 쓴 최신 값을 즉시 보게(Visibility)" 합니다.
   - 그러나 `count++`와 같이 복합 연산(Read -> Modify -> Write)인 경우 원자성을 보장하지 못하므로 결코 스레드 안전(Thread-safe)하지 않습니다.
2. **Lock-Free와 CAS 루프**
   - OS 레벨의 뮤텍스(Mutex)나 모니터 락(`synchronized`)은 락을 획득하지 못한 스레드를 대기 상태(Blocked)로 전환시키며, 이때 스레드 스케줄링 및 컨텍스트 스위칭 오버헤드가 발생합니다.
   - 반면 CAS(`AtomicInteger`, `AtomicReference` 등)는 CPU 하드웨어 단일 명령어(`LOCK CMPXCHG`)를 사용하여 락 없이도 완벽한 동시성을 보장합니다.
   - 단, 스레드 간 경합(Contention)이 극도로 심한 환경에서는 수많은 스레드가 무한 재시도(Spin-Retry)를 반복하면서 CPU를 100% 소모할 수 있으므로, 이때는 `LongAdder`와 같이 여러 셀로 카운터를 분산시키는 전략을 취해야 합니다.
