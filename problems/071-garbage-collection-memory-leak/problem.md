# Problem 071: 가비지 컬렉션과 메모리 누수의 덫 (Garbage Collection & Memory Leak via GC Roots)

## 문제 설명

Java(JVM), Node.js, Python 등 관리형 언어(Managed Language)로 백엔드 서버를 운영하던 당신의 팀에서 매일 새벽마다 기괴한 장애가 발생했습니다:
> "분명히 우리 언어는 가비지 컬렉터(GC)가 알아서 쓰레기 객체를 치워주는데, 서버 메모리 사용량이 계단식으로 조금씩 계속 오르더니 결국 매일 새벽 3시마다 `java.lang.OutOfMemoryError: Java heap space`를 뿜으며 서버가 죽어버립니다!  
> 힙 덤프(Heap Dump)를 떠서 분석해보니, 이미 한 달 전에 탈퇴한 유저의 프로필 객체 수백만 개가 힙 메모리의 80%를 가득 채우고 있었습니다!"

원인은 가비지 컬렉터의 동작 원리를 오해하고 작성한 **메모리 누수(Memory Leak) 안티패턴**이었습니다:
- **무제한 정적 캐시 (Unbounded Static Cache)**: `public static final Map<Long, User> cache = new HashMap<>();`에 만료 정책(TTL)이나 최대 크기(LRU) 제한 없이 계속 객체를 `put`했습니다. 정적 변수(`static`)는 클래스가 언로드되지 않는 한 영구히 살아남는 **GC Root**이기 때문에, 여기에 매달린 모든 객체는 GC가 절대 치우지 못합니다.
- **미해제 이벤트 리스너 (Dangling Listener)**: 짧은 생명주기를 가진 요청 처리 객체가 싱글톤 이벤트 버스에 리스너를 등록해 두고, 작업이 끝난 뒤 `unsubscribe()`를 호출하지 않아 싱글톤 GC Root에 영구 고정되었습니다.

거실 기둥(GC Root)에 질긴 끈(강한 참조)으로 빈 피자 상자(객체)를 묶어두면, 최신형 로봇 청소기(GC)가 집을 백 번 청소해도 "주인이 아끼는 물건"으로 착각하여 절대 버리지 못하는 것과 같습니다.

현대 가비지 컬렉터는 **도달 가능성 분석(Reachability Analysis)**으로 동작합니다:
1. **GC Roots**: 정적 변수, 현재 활성 스택 프레임의 로컬 변수, 싱글톤 리스너 등.
2. **도달 가능 객체(Live Object)**: GC Roots로부터 참조 체인을 따라 도달할 수 있는 객체 $\to$ 절대 수거하지 않음.
3. **도달 불가능 객체(Garbage Object)**: 모든 GC Roots와의 연결이 끊어진 고립 객체 $\to$ GC가 100% 깔끔하게 메모리 회수(Reclaim).

당신은 동일한 객체 할당 및 수명 주기 스트림에 대해 무제한 누수를 방치하는 **Naive Leaky 엔진**과 LRU 캐시 및 명시적 리스너 해제를 갖춘 **Robust Managed GC 엔진**의 힙 사용량, 회수량(`RECLAIMED_MB`), OOM 발생 여부를 비교 시뮬레이션하는 메모리 엔지니어링 엔진을 작성해야 합니다.

---

## 시스템 요구사항 및 동작 규칙

### 1. 전역 설정
- `HEAP_MAX_MB <heap_max_mb>`: 힙 메모리의 최대 물리 한도 (예: 300MB).
  - 힙 사용량이 이 한도를 초과하면 `OOM_CRASH` 상태가 됩니다.
- `LRU_CACHE_CAPACITY <lru_cap>`: Robust 엔진의 정적 캐시가 보관할 수 있는 최대 객체 수.
  - 용량 초과 시 가장 오래 참조되지 않은 항목(LRU)이 자동 축출(Evict)되어 GC Root 연결이 해제됩니다.

---

### 2. 두 가지 메모리 관리 아키텍처

#### 1) Naive Leaky Engine (안티패턴)
- 정적 캐시(`STATIC_CACHE`): 크기 제한 없는 `HashSet`에 무제한 등록. 명시적 제거가 없어 영구 누수.
- 이벤트 리스너(`LISTENER`): 등록 해제 요청(`UNSUBSCRIBE_LISTENER`)을 무시(`IGNORED_LEAKING`)하여 영구 누수.
- 스택 변수(`STACK`): `POP_STACK_FRAME` 시 프레임이 제거되면서 GC Root 연결 해제.
- GC 실행(`TRIGGER_GC`): GC Root에 여전히 연결되어 있는 캐시와 리스너 객체를 단 1MB도 수거하지 못해 힙이 지속 증가하다가 결국 `OOM_CRASH` 폭사.

#### 2) Robust Managed GC Engine (모범 설계)
- 정적 캐시(`STATIC_CACHE`): LRU 순서를 유지하는 `OrderedDict` 기반 캐시. 용량(`LRU_CACHE_CAPACITY`) 초과 시 가장 오래된 객체를 자동 축출(`[EVICTED:<id>]`)하여 GC Root 참조 단절.
- 이벤트 리스너(`LISTENER`): `UNSUBSCRIBE_LISTENER` 호출 시 이벤트 버스에서 즉시 제거하여 GC Root 참조 단절.
- 스택 변수(`STACK`): `POP_STACK_FRAME` 시 로컬 프레임 제거로 GC Root 참조 단절.
- GC 실행(`TRIGGER_GC`): 모든 GC Roots로부터 고립된 객체들을 완벽하게 수거하여 힙 메모리를 안전하게 확보.

---

### 3. 6대 액션 명세

#### 1) `PUSH_STACK_FRAME`
- 새로운 스택 프레임 생성 (메서드 호출).
- 출력 (3줄):
  ```text
  ACT <idx> PUSH_STACK_FRAME
    NAIVE: FRAME_DEPTH:<depth>
    ROBUST: FRAME_DEPTH:<depth>
  ```

#### 2) `POP_STACK_FRAME`
- 최상위 스택 프레임 제거 (메서드 리턴 및 로컬 변수 참조 해제).
- 출력 (3줄):
  ```text
  ACT <idx> POP_STACK_FRAME
    NAIVE: FRAME_DEPTH:<depth>
    ROBUST: FRAME_DEPTH:<depth>
  ```

#### 3) `ALLOC_OBJECT <obj_id> <size_mb> <target_type>`
- 객체 힙 할당 (`target_type`: `STACK`, `STATIC_CACHE`, `LISTENER`).
- 출력 (3줄):
  ```text
  ACT <idx> ALLOC_OBJECT <obj_id> SIZE:<size_mb>MB TARGET:<target_type>
    NAIVE: ALLOCATED HEAP_USED:<used>MB/<max>MB STATUS:<OK|OOM_CRASH>
    ROBUST: ALLOCATED HEAP_USED:<used>MB/<max>MB STATUS:<OK|OOM_CRASH> [EVICTED:<evicted_id>]
  ```
  - 단, Robust 엔진에서 캐시 축출이 발생한 경우에만 `[EVICTED:<evicted_id>]`를 끝에 덧붙입니다.

#### 4) `UNSUBSCRIBE_LISTENER <obj_id>`
- 리스너 등록 해제 요청.
- 출력 (3줄):
  ```text
  ACT <idx> UNSUBSCRIBE_LISTENER <obj_id>
    NAIVE: IGNORED_LEAKING
    ROBUST: UNLINKED_FROM_ROOT
  ```

#### 5) `TRIGGER_GC`
- 가비지 컬렉터 강제 구동.
- 출력 (3줄):
  ```text
  ACT <idx> TRIGGER_GC
    NAIVE: RECLAIMED:<reclaimed>MB REMAINING_HEAP:<rem>MB/<max>MB LIVE_OBJS:<live_cnt>
    ROBUST: RECLAIMED:<reclaimed>MB REMAINING_HEAP:<rem>MB/<max>MB LIVE_OBJS:<live_cnt>
  ```

#### 6) `CHECK_MEMORY`
- 현재 메모리 상태 및 누수 객체(Leaked Objects) 수 점검.
- 출력 (3줄):
  ```text
  ACT <idx> CHECK_MEMORY
    NAIVE: HEAP:<used>MB LEAKED_OBJECTS:<cnt> HEALTH:<HEALTHY|CRITICAL_LEAK|OOM_CRASH>
    ROBUST: HEAP:<used>MB LEAKED_OBJECTS:0 HEALTH:<HEALTHY|OOM_CRASH>
  ```
  - Naive 엔진은 `OOM_CRASH`가 아니고 누수 객체가 1개 이상이면 `CRITICAL_LEAK`, 0개이면 `HEALTHY`.

---

## 입력 형식

```text
SYSTEM_CONFIG
HEAP_MAX_MB <heap_max_mb>
LRU_CACHE_CAPACITY <lru_cap>
ACTIONS
<action_cmd> <args...>
...
```

---

## 출력 형식

1. 각 액션별 출력 (위 명세 참조)
2. 모든 액션 종료 후 최종 통계 요약 (5줄):
```text
SUMMARY TOTAL_ALLOCATIONS:<alloc_cnt> (TOTAL_REQUESTED:<tot_mb>MB)
SUMMARY NAIVE PEAK_HEAP:<peak>MB FINAL_HEAP:<final>MB OOM_CRASH:<YES|NO> LEAKED_OBJS:<cnt>
SUMMARY ROBUST PEAK_HEAP:<peak>MB FINAL_HEAP:<final>MB OOM_CRASH:NO LEAKED_OBJS:0
SUMMARY MEMORY_SAVED:<saved_mb>MB (EFFICIENCY:<pct:.2f>%)
SUMMARY GC_MANAGEMENT_VERDICT: ROBUST_PREVENTS_OOM
```

---

## 입출력 예시

### 예시 1

**입력:**
```text
SYSTEM_CONFIG
HEAP_MAX_MB 300
LRU_CACHE_CAPACITY 2
ACTIONS
ALLOC_OBJECT C-1 100 STATIC_CACHE
ALLOC_OBJECT C-2 100 STATIC_CACHE
ALLOC_OBJECT C-3 100 STATIC_CACHE
TRIGGER_GC
PUSH_STACK_FRAME
ALLOC_OBJECT S-1 50 STACK
POP_STACK_FRAME
TRIGGER_GC
ALLOC_OBJECT L-1 50 LISTENER
UNSUBSCRIBE_LISTENER L-1
TRIGGER_GC
CHECK_MEMORY
```

**출력:**
```text
ACT 1 ALLOC_OBJECT C-1 SIZE:100MB TARGET:STATIC_CACHE
  NAIVE: ALLOCATED HEAP_USED:100MB/300MB STATUS:OK
  ROBUST: ALLOCATED HEAP_USED:100MB/300MB STATUS:OK
ACT 2 ALLOC_OBJECT C-2 SIZE:100MB TARGET:STATIC_CACHE
  NAIVE: ALLOCATED HEAP_USED:200MB/300MB STATUS:OK
  ROBUST: ALLOCATED HEAP_USED:200MB/300MB STATUS:OK
ACT 3 ALLOC_OBJECT C-3 SIZE:100MB TARGET:STATIC_CACHE
  NAIVE: ALLOCATED HEAP_USED:300MB/300MB STATUS:OK
  ROBUST: ALLOCATED HEAP_USED:300MB/300MB STATUS:OK [EVICTED:C-1]
ACT 4 TRIGGER_GC
  NAIVE: RECLAIMED:0MB REMAINING_HEAP:300MB/300MB LIVE_OBJS:3
  ROBUST: RECLAIMED:100MB REMAINING_HEAP:200MB/300MB LIVE_OBJS:2
ACT 5 PUSH_STACK_FRAME
  NAIVE: FRAME_DEPTH:1
  ROBUST: FRAME_DEPTH:1
ACT 6 ALLOC_OBJECT S-1 SIZE:50MB TARGET:STACK
  NAIVE: ALLOCATED HEAP_USED:350MB/300MB STATUS:OOM_CRASH
  ROBUST: ALLOCATED HEAP_USED:250MB/300MB STATUS:OK
ACT 7 POP_STACK_FRAME
  NAIVE: FRAME_DEPTH:0
  ROBUST: FRAME_DEPTH:0
ACT 8 TRIGGER_GC
  NAIVE: RECLAIMED:50MB REMAINING_HEAP:300MB/300MB LIVE_OBJS:3
  ROBUST: RECLAIMED:50MB REMAINING_HEAP:200MB/300MB LIVE_OBJS:2
ACT 9 ALLOC_OBJECT L-1 SIZE:50MB TARGET:LISTENER
  NAIVE: ALLOCATED HEAP_USED:350MB/300MB STATUS:OOM_CRASH
  ROBUST: ALLOCATED HEAP_USED:250MB/300MB STATUS:OK
ACT 10 UNSUBSCRIBE_LISTENER L-1
  NAIVE: IGNORED_LEAKING
  ROBUST: UNLINKED_FROM_ROOT
ACT 11 TRIGGER_GC
  NAIVE: RECLAIMED:0MB REMAINING_HEAP:350MB/300MB LIVE_OBJS:4
  ROBUST: RECLAIMED:50MB REMAINING_HEAP:200MB/300MB LIVE_OBJS:2
ACT 12 CHECK_MEMORY
  NAIVE: HEAP:350MB LEAKED_OBJECTS:2 HEALTH:OOM_CRASH
  ROBUST: HEAP:200MB LEAKED_OBJECTS:0 HEALTH:HEALTHY
SUMMARY TOTAL_ALLOCATIONS:5 (TOTAL_REQUESTED:400MB)
SUMMARY NAIVE PEAK_HEAP:350MB FINAL_HEAP:350MB OOM_CRASH:YES LEAKED_OBJS:2
SUMMARY ROBUST PEAK_HEAP:300MB FINAL_HEAP:200MB OOM_CRASH:NO LEAKED_OBJS:0
SUMMARY MEMORY_SAVED:150MB (EFFICIENCY:42.86%)
SUMMARY GC_MANAGEMENT_VERDICT: ROBUST_PREVENTS_OOM
```
