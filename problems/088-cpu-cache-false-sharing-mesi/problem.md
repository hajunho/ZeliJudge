# Problem #088: 멀티스레드로 바꿨더니 왜 10배나 느려져요?!: CPU 캐시 라인(64바이트)과 거짓 공유(False Sharing)의 덫

## 1. 문제 설명
대규모 실시간 데이터 스트리밍 처리 시스템을 개발하던 당신은 성능을 4배 끌어올리기 위해 단일 스레드 카운터를 4개의 독립된 작업자 스레드(`Thread 0 ~ 3`)가 각자의 카운터 변수(`count[0] ~ count[3]`)에 숫자를 더하는 병렬 구조로 리팩토링했습니다.  
코드에는 어떠한 락(Mutex)도 쓰지 않았으므로 완벽한 $4\times$ 선형 가속을 기대했으나, 벤치마크 결과는 놀랍게도 **싱글 스레드보다 10배 이상 느려졌습니다!**

하드웨어 성능 프로파일러(`perf`)로 CPU를 분석한 결과, 원인은 **거짓 공유(False Sharing)** 였습니다.  
서로 다른 스레드가 완전히 독립된 변수를 수정하고 있었지만, 메모리상에서 4개의 8바이트 정수가 인접해 있어 **동일한 64바이트 CPU 캐시 라인**에 묶여 있었던 것입니다!  
한 코어가 자신의 카운터를 수정할 때마다 **MESI 캐시 일관성 프로토콜**에 의해 다른 코어들의 L1 캐시 라인이 강제 무효화(`Invalid`)되어, 모든 코어가 L1 캐시 라인을 뺏고 빼앗기며 메모리 버스에서 100사이클씩 멈춰 서는(Stall) 비극이 벌어졌습니다.

당신은 멀티코어 CPU의 L1 데이터 캐시와 **MESI 프로토콜**을 정밀하게 시뮬레이션하여 거짓 공유를 감지하고, **64바이트 캐시 라인 패딩(Padding)** 을 통한 성능 최적화를 검증하는 시뮬레이터를 구축해야 합니다.

---

## 2. 시스템 동작 규칙

### (1) 캐시 모델 및 메모리 배치
- 캐시 라인 크기는 **64 바이트(Bytes)** 로 고정됩니다.
- 각 변수는 고유한 메모리 바이트 오프셋(Offset)을 가지며, 속한 캐시 라인 번호는 $\text{line\_id} = \lfloor \text{offset} / 64 \rfloor$ 로 결정됩니다.
- CPU는 `CORES`개의 독립 코어(`C0, C1, ...`)를 가지며, 각 코어는 전용 L1 데이터 캐시를 보유합니다.
- 각 코어의 캐시 라인은 **MESI 프로토콜**의 4가지 상태 중 하나를 갖습니다:
  - **M (Modified)**: 해당 코어가 독점 수정함 (더티 상태).
  - **E (Exclusive)**: 해당 코어만 독점 보유 중 (클린 상태).
  - **S (Shared)**: 여러 코어가 동시에 읽기 전용으로 공유 중.
  - **I (Invalid)**: 캐시 라인이 무효화됨 (초기 상태).

---

### (2) MESI 상태 전이 및 비용 규칙

1. **READ 연산 (`READ <core> <var>`)**:
   - **Cache Hit (상태가 `M`, `E`, `S` 중 하나)**:
     - 상태 변화 없음.
     - 소요 사이클: **1 cycle**.
     - 결과: `HIT`, 무효화: `0`.
   - **Cache Miss (상태가 `I`)**:
     - 소요 사이클: **100 cycles**.
     - 해당 라인을 보유한 다른 코어들을 스누핑(Bus Snooping)합니다:
       - 다른 코어 중 `M` 상태가 있다면 $\to$ 해당 코어는 `S`로 전이 (메모리 플러시).
       - 다른 코어 중 `E` 상태가 있다면 $\to$ 해당 코어는 `S`로 전이.
     - 다른 코어 중 한 곳이라도 이 라인을 보유하고 있었다면 $\to$ 요청 코어는 **`S`** 로 전이.
     - 아무 코어도 보유하고 있지 않았다면 $\to$ 요청 코어는 **`E`** 로 전이.
     - 결과: `MISS`, 무효화: `0`.

2. **WRITE 연산 (`WRITE <core> <var>`)**:
   - **Cache Hit (`M` 또는 `E`)**:
     - 이미 `M` 상태인 경우 $\to$ 상태 유지 (`M`).
     - `E` 상태인 경우 $\to$ 독점이므로 다른 코어 버스 통신 없이 즉시 **`M`** 으로 전이.
     - 소요 사이클: **1 cycle**.
     - 결과: `HIT`, 무효화: `0`.
   - **Write Upgrade (`S`)**:
     - 현재 `S` 상태이므로 다른 코어들도 이 라인을 들고 있습니다.
     - 다른 모든 코어의 해당 캐시 라인을 강제로 **`I (Invalid)` 로 강등(무효화)** 시킵니다!
     - 요청 코어는 **`M`** 으로 전이합니다.
     - 소요 사이클: **100 cycles** (버스 업그레이드 전파 비용).
     - 결과: `UPGRADE`, 무효화: 무효화된 다른 코어 수.
   - **Write Miss (`I`)**:
     - 현재 해당 라인이 유효하지 않습니다.
     - 라인을 메모리/다른 코어로부터 가져오며(`BusRdX`), 다른 모든 코어의 해당 캐시 라인을 **`I (Invalid)` 로 강등(무효화)** 시킵니다!
     - 요청 코어는 **`M`** 으로 전이합니다.
     - 소요 사이클: **100 cycles** (캐시 미스 + 버스 무효화 브로드캐스트).
     - 결과: `MISS`, 무효화: 무효화된 다른 코어 수.

---

### (3) 액션 명세

- `READ <core_id> <var_name>`
- `WRITE <core_id> <var_name>`

존재하지 않는 변수나 유효하지 않은 코어 요청 시:
- `ACT <idx> <CMD> <core> <var> ERROR:VARIABLE_NOT_FOUND`
- `ACT <idx> <CMD> <core> <var> ERROR:INVALID_CORE`

정상 연산 시 한 줄 출력:
`ACT <idx> <CMD> <core> <var> LINE:<line_id> BEFORE:<before_state> AFTER:<after_state> RESULT:<HIT|MISS|UPGRADE> INVALS:<num_invals> CYCLES:<cycles>`

---

## 3. 입력 형식

```text
SYSTEM_CONFIG
CORES <int>
VARIABLES
<var_name_1> <byte_offset_1>
<var_name_2> <byte_offset_2>
...
ACTIONS
<ACTION_1>
<ACTION_2>
...
```

- `CORES`: 코어 수 (예: 2, 4). 코어 이름은 `C0, C1, ...`
- `VARIABLES`: 변수명과 바이트 오프셋(정수).
- `ACTIONS` 아래 한 줄에 하나씩 `READ` 또는 `WRITE` 액션이 주어집니다.

---

## 4. 출력 형식

각 액션마다 `ACT <act_idx> ...` 한 줄을 출력합니다 (`act_idx`는 1부터 시작).  
모든 액션 실행 후 `SUMMARY`를 출력합니다:

```text
SUMMARY TOTAL_ACTIONS:<cnt>
SUMMARY TOTAL_CYCLES:<total_cycles>
SUMMARY TOTAL_HITS:<hit_cnt>
SUMMARY TOTAL_MISSES:<miss_cnt>
SUMMARY TOTAL_UPGRADES:<upgrade_cnt>
SUMMARY TOTAL_INVALIDATIONS:<total_invals>
SUMMARY FALSE_SHARING_DETECTED: <TRUE (INVALIDATIONS:<cnt>)|FALSE>
```

- `TOTAL_MISSES`: `RESULT:MISS` 횟수
- `TOTAL_UPGRADES`: `RESULT:UPGRADE` 횟수
- `TOTAL_HITS`: `RESULT:HIT` 횟수
- `FALSE_SHARING_DETECTED`: `TOTAL_INVALIDATIONS > 0` 이면 `TRUE (INVALIDATIONS:<cnt>)`, 0이면 `FALSE`.

---

## 5. 입출력 예시

### 예시 입력 1 (거짓 공유 발생: 동일 캐시 라인 Line 0)
```text
SYSTEM_CONFIG
CORES 2
VARIABLES
count0 0
count1 8
ACTIONS
WRITE C0 count0
WRITE C1 count1
WRITE C0 count0
WRITE C1 count1
```

### 예시 출력 1
```text
ACT 1 WRITE C0 count0 LINE:0 BEFORE:I AFTER:M RESULT:MISS INVALS:0 CYCLES:100
ACT 2 WRITE C1 count1 LINE:0 BEFORE:I AFTER:M RESULT:MISS INVALS:1 CYCLES:100
ACT 3 WRITE C0 count0 LINE:0 BEFORE:I AFTER:M RESULT:MISS INVALS:1 CYCLES:100
ACT 4 WRITE C1 count1 LINE:0 BEFORE:I AFTER:M RESULT:MISS INVALS:1 CYCLES:100
SUMMARY TOTAL_ACTIONS:4
SUMMARY TOTAL_CYCLES:400
SUMMARY TOTAL_HITS:0
SUMMARY TOTAL_MISSES:4
SUMMARY TOTAL_UPGRADES:0
SUMMARY TOTAL_INVALIDATIONS:3
SUMMARY FALSE_SHARING_DETECTED: TRUE (INVALIDATIONS:3)
```

---

### 예시 입력 2 (64바이트 패딩 적용: Line 0과 Line 1로 분리 격리)
```text
SYSTEM_CONFIG
CORES 2
VARIABLES
count0 0
count1 64
ACTIONS
WRITE C0 count0
WRITE C1 count1
WRITE C0 count0
WRITE C1 count1
```

### 예시 출력 2
```text
ACT 1 WRITE C0 count0 LINE:0 BEFORE:I AFTER:M RESULT:MISS INVALS:0 CYCLES:100
ACT 2 WRITE C1 count1 LINE:1 BEFORE:I AFTER:M RESULT:MISS INVALS:0 CYCLES:100
ACT 3 WRITE C0 count0 LINE:0 BEFORE:M AFTER:M RESULT:HIT INVALS:0 CYCLES:1
ACT 4 WRITE C1 count1 LINE:1 BEFORE:M AFTER:M RESULT:HIT INVALS:0 CYCLES:1
SUMMARY TOTAL_ACTIONS:4
SUMMARY TOTAL_CYCLES:202
SUMMARY TOTAL_HITS:2
SUMMARY TOTAL_MISSES:2
SUMMARY TOTAL_UPGRADES:0
SUMMARY TOTAL_INVALIDATIONS:0
SUMMARY FALSE_SHARING_DETECTED: FALSE
```
