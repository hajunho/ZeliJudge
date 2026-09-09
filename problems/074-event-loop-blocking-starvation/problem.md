# Problem 074: 싱글 스레드 이벤트 루프 블로킹과 기아 현상 (Single-Threaded Event Loop Blocking & Task Starvation)

## 문제 설명

수만 명의 동시 접속자를 처리하는 Node.js(Express/NestJS) 및 Python(FastAPI) 백엔드 마이크로서비스를 운영하던 팀에 기괴한 장애가 발생했습니다:
> "평소에는 수천 건의 요청도 1~2ms 만에 번개처럼 처리되던 서버가, 어떤 사용자가 회원가입/로그인 API를 호출하는 순간 서버 전체가 10초 동안 완전히 먹통이 됩니다!  
> 그 10초 동안 단순한 `GET /health` 헬스체크 핑조차 타임아웃(504 Gateway Timeout)이 나고, 쿠버네티스(K8s)는 파드가 사망했다고 판단하여 인스턴스를 강제로 연쇄 재부팅시켜 사이트 전체가 다운되었습니다!"

장애의 근본 원인은 **싱글 스레드 이벤트 기반 아키텍처(Single-Threaded Event Loop)**의 동작 원리를 무시하고 작성한 **이벤트 루프 블로킹(Event Loop Blocking)과 태스크 기아(Task Starvation)** 때문이었습니다:
- **싱글 스레드의 강점과 신뢰**: Node.js(libuv)와 Python(asyncio)은 단일 메인 스레드에서 이벤트 루프(Event Loop) 무한 반복을 돌며, 태스크 큐에 쌓인 작업들을 하나씩 꺼내 초고속으로 처리합니다. 멀티스레드의 락(Lock) 경합이나 컨텍스트 스위칭 오버헤드가 없어 I/O 바운드 작업에서 엄청난 처리량을 발휘합니다.
- **"Don't Block the Event Loop!"**: 이 구조는 모든 개별 태스크가 아주 짧은 시간(수 마이크로초~수 밀리초) 안에 CPU 제어권을 반환한다는 전제하에 동작합니다. 만약 어떤 개발자가 메인 스레드에서 `bcrypt.hashSync(cost=14)`, 대용량 JSON 파싱, 복잡한 정규식(ReDoS) 같은 **동기 CPU 연산**이나 `fs.readFileSync`, `requests.get()` 같은 **동기 블로킹 I/O**를 실행하면, 메인 스레드 콜 스택이 독점되어 이벤트 루프가 멈춰 섭니다 (Event Loop Lag 폭증).
- **태스크 기아 현상 (Task Starvation)**: 블로킹 작업이 메인 스레드를 쥐고 있는 동안, 뒤따라 큐에 인입된 수천 건의 경량 웹 요청(`LIGHT`)들은 실행 기회를 전혀 얻지 못하고 큐에 갇히게 됩니다. 결국 최대 대기 허용 시간(`MAX_WAIT_TICKS`)을 초과하여 대량 타임아웃 드롭(`TIMED_OUT`)이 발생합니다.

초스피드로 물건을 찍어주는 편의점 단 하나의 계산대에서, 앞 손님이 "A4 용지 5,000장 복사해서 스탬프 찍고 코팅해 주세요"라고 요구하자 점원이 계산대를 막아두고 10분 동안 복사기만 돌리는 바람에, 뒤에 껌 한 통 사려던 손님 100명이 줄줄이 물건을 던져두고 편의점을 나가버린 것과 같습니다!

이를 해결하려면:
1. **무거운 CPU 연산**: 메인 루프에서 즉시 백그라운드 **워커 스레드 풀(Worker Thread Pool)**로 작업을 오프로딩(`loop.run_in_executor()`, `worker_threads`)하여 병렬 처리합니다.
2. **동기 블로킹 I/O**: 비동기 논블로킹 I/O(OS 커널 epoll/kqueue)로 전환하여 메인 스레드가 멈추지 않고 즉시 다음 태스크를 처리하도록 합니다.

당신은 동일한 요청 스트림에 대해 메인 스레드를 그대로 블로킹하는 **Naive Event Loop 엔진**과 워커 풀 및 비동기 커널 오프로딩을 적용한 **Tuned Event Loop 엔진**의 동작을 시뮬레이션하고, 타임아웃 절감 효과를 검증하는 이벤트 루프 시뮬레이터를 작성해야 합니다.

---

## 시스템 요구사항 및 동작 규칙

### 1. 전역 설정 (`SYSTEM_CONFIG`)
- `MAX_WAIT_TICKS <int>`: 클라이언트/로드밸런서가 대기할 수 있는 최대 대기 틱 수. 큐에 진입한 후 실행을 시작하기까지 대기한 시간(`current_tick - arrival_tick`)이 이 값을 초과하면 해당 요청은 즉시 **타임아웃 드롭(`TIMED_OUT`)** 처리됩니다.
- `WORKER_POOL_SIZE <int>`: Tuned 엔진의 백그라운드 워커 스레드 풀 크기.

---

### 2. 태스크 유형 (Task Type)
- `LIGHT`: 초경량 웹 요청 (예: `GET /health`, 캐시 조회). 비용 1 틱.
- `HEAVY_CPU <cost>`: 동기 무거운 CPU 연산 (예: `bcrypt.hashSync`, 대용량 JSON 파싱). 소요 비용 `cost` 틱.
- `SYNC_IO <cost>`: 동기 블로킹 I/O (예: `fs.readFileSync`, `requests.get`). 소요 비용 `cost` 틱.

---

### 3. 두 가지 이벤트 루프 아키텍처

#### 1) Naive Event Loop Engine (블로킹 메인 루프)
- 모든 태스크(`LIGHT`, `HEAVY_CPU`, `SYNC_IO`)를 단일 메인 스레드에서 직접 순차 실행합니다.
- 매 틱마다:
  - 현재 실행 중인 태스크가 있다면 잔여 틱(`remaining_ticks`)을 1 감소시킵니다. 잔여 틱이 0이 되면 완료(`completed_count += 1`).
  - 실행 중인 태스크가 없다면 큐에서 다음 태스크를 꺼냅니다:
    - 대기 시간(`current_tick - arrival_tick > MAX_WAIT_TICKS`) 초과 시 `timed_out_count += 1` 처리 후 계속 다음 태스크 탐색.
    - 유효한 태스크를 꺼내면 실행을 시작하며, 이번 틱에 즉시 1 틱을 소비합니다 (`remaining_ticks = cost - 1`). 잔여 틱이 0이면 즉시 완료.
  - `HEAVY_CPU`나 `SYNC_IO`가 실행되는 동안 메인 스레드가 `cost` 틱 동안 독점되므로 뒤의 태스크들은 대기 시간이 계속 증가합니다.

#### 2) Tuned Event Loop Engine (논블로킹 + 워커 풀 오프로딩)
- 메인 이벤트 루프는 블로킹 작업을 직접 수행하지 않고 즉시 위임합니다.
- 매 틱마다:
  1. **백그라운드 워커 풀**: 실행 중인 워커들의 잔여 틱 1 감소. 완료 시 슬롯 반환 및 `completed_count += 1`. 빈 슬롯이 있으면 워커 대기 큐의 작업을 즉시 시작.
  2. **비동기 커널 I/O**: 비동기 I/O 타이머들의 잔여 틱 1 감소. 완료 시 `completed_count += 1`.
  3. **메인 스레드 실행/디스패치**:
     - 메인 스레드에서 실행 중인 태스크의 잔여 틱 1 감소. 잔여 틱 0 도달 시:
       - `LIGHT`: 완료 처리 (`completed_count += 1`).
       - `HEAVY_CPU`: 워커 풀에 빈 슬롯이 있으면 워커 할당, 꽉 찼으면 워커 대기 큐 등록.
       - `SYNC_IO`: 논블로킹 비동기 I/O 타이머로 등록.
     - 메인 스레드가 유휴 상태이면 메인 큐에서 다음 태스크를 꺼냄 (타임아웃 검사 동일).
     - 유효한 태스크를 꺼내면 메인 스레드에서 1 틱 동안 실행 또는 디스패치 시작.

---

### 4. 액션 명세

#### 1) `ENQUEUE_REQ <req_id> <type> [cost]`
- 신규 요청 큐 인입. (`arrival_tick = current_tick`)
- 출력 (1줄):
  - `LIGHT`: `ACT <idx> ENQUEUE_REQ ID:<req_id> TYPE:LIGHT`
  - `HEAVY_CPU` / `SYNC_IO`: `ACT <idx> ENQUEUE_REQ ID:<req_id> TYPE:<type> COST:<cost>`

#### 2) `RUN_TICKS <ticks>`
- 두 엔진의 가상 시간을 `<ticks>`만큼 시뮬레이션 진행.
- 출력 (3줄):
  ```text
  ACT <idx> RUN_TICKS <ticks>
    NAIVE: TICK:<cur_tick> BUSY:<busy_str> QUEUE_WAITING:<queue_len> COMPLETED:<completed_cnt> TIMED_OUT:<timed_out_cnt>
    TUNED: TICK:<cur_tick> BUSY:<busy_str> WORKERS_ACTIVE:<active_workers>/<worker_pool_size> QUEUE_WAITING:<queue_len> COMPLETED:<completed_cnt> TIMED_OUT:<timed_out_cnt>
  ```
  *(단, `busy_str`은 실행 중인 경우 `<id>(<type>,REM:<rem>)`, 유휴 시 `IDLE`)*

#### 3) `CHECK_HEALTH`
- 헬스체크 프로브 실행.
- Naive 엔진에서 현재 실행 중인 작업이 `HEAVY_CPU` 또는 `SYNC_IO`이면 `PROBE_FAILED (BLOCKED_BY_<type>)`, 그 외에는 `PROBE_OK`.
- Tuned 엔진은 항상 `PROBE_OK`.
- 출력 (3줄):
  ```text
  ACT <idx> CHECK_HEALTH
    NAIVE: PROBE:<probe_status> QUEUE_WAITING:<queue_len> TIMED_OUT:<timed_out_cnt>
    TUNED: PROBE:PROBE_OK QUEUE_WAITING:<queue_len> TIMED_OUT:<timed_out_cnt>
  ```

---

## 입력 형식

```text
SYSTEM_CONFIG
MAX_WAIT_TICKS <max_wait_ticks>
WORKER_POOL_SIZE <worker_pool_size>
ACTIONS
<action_cmd> <args...>
...
```

---

## 출력 형식

1. 각 액션별 실행 결과 (위 명세 참조)
2. 모든 액션 종료 후 최종 통계 요약 (5줄):
```text
SUMMARY TOTAL_REQUESTS:<total>
SUMMARY NAIVE COMPLETED:<completed_cnt> TIMED_OUT:<timed_out_cnt> TIMEOUT_RATE:<n_rate:.2f>%
SUMMARY TUNED COMPLETED:<completed_cnt> TIMED_OUT:<timed_out_cnt> TIMEOUT_RATE:<t_rate:.2f>%
SUMMARY TIMEOUT_REDUCTION:<reduction:.2f>%
SUMMARY EVENT_LOOP_VERDICT: TUNED_OFFLOADING_PREVENTS_STARVATION
```

---

## 입출력 예시

### 예시 1

**입력:**
```text
SYSTEM_CONFIG
MAX_WAIT_TICKS 5
WORKER_POOL_SIZE 2
ACTIONS
ENQUEUE_REQ H1 HEAVY_CPU 10
ENQUEUE_REQ L1 LIGHT
ENQUEUE_REQ L2 LIGHT
RUN_TICKS 3
CHECK_HEALTH
RUN_TICKS 8
CHECK_HEALTH
```

**출력:**
```text
ACT 1 ENQUEUE_REQ ID:H1 TYPE:HEAVY_CPU COST:10
ACT 2 ENQUEUE_REQ ID:L1 TYPE:LIGHT
ACT 3 ENQUEUE_REQ ID:L2 TYPE:LIGHT
ACT 4 RUN_TICKS 3
  NAIVE: TICK:3 BUSY:H1(HEAVY_CPU,REM:7) QUEUE_WAITING:2 COMPLETED:0 TIMED_OUT:0
  TUNED: TICK:3 BUSY:IDLE WORKERS_ACTIVE:1/2 QUEUE_WAITING:0 COMPLETED:2 TIMED_OUT:0
ACT 5 CHECK_HEALTH
  NAIVE: PROBE:PROBE_FAILED (BLOCKED_BY_HEAVY_CPU) QUEUE_WAITING:2 TIMED_OUT:0
  TUNED: PROBE:PROBE_OK QUEUE_WAITING:0 TIMED_OUT:0
ACT 6 RUN_TICKS 8
  NAIVE: TICK:11 BUSY:IDLE QUEUE_WAITING:0 COMPLETED:1 TIMED_OUT:2
  TUNED: TICK:11 BUSY:IDLE WORKERS_ACTIVE:0/2 QUEUE_WAITING:0 COMPLETED:3 TIMED_OUT:0
ACT 7 CHECK_HEALTH
  NAIVE: PROBE:PROBE_OK QUEUE_WAITING:0 TIMED_OUT:2
  TUNED: PROBE:PROBE_OK QUEUE_WAITING:0 TIMED_OUT:0
SUMMARY TOTAL_REQUESTS:3
SUMMARY NAIVE COMPLETED:1 TIMED_OUT:2 TIMEOUT_RATE:66.67%
SUMMARY TUNED COMPLETED:3 TIMED_OUT:0 TIMEOUT_RATE:0.00%
SUMMARY TIMEOUT_REDUCTION:100.00%
SUMMARY EVENT_LOOP_VERDICT: TUNED_OFFLOADING_PREVENTS_STARVATION
```
