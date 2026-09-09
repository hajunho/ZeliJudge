# #046 외부 API 5개 불렀을 뿐인데 응답이 15초나 걸려요?!: 직렬 동기 호출 vs 병렬 비동기 I/O (Async Fan-Out / Gather)

---

## 1. 현실 세계 비유: 해외여행 패키지 견적서와 5대의 전화기

고객이 여행사에 전화를 걸어 "호텔, 항공권, 렌터카, 여행자보험, 공연티켓 견적을 한 번에 뽑아주세요!"라고 요청했습니다.

```text
❌ 직렬 동기 호출 (Serial Sync):
   직원이 한 손에 전화기를 들고...
   1. 호텔에 전화 걸어 3초 통화 후 끊음
   2. 항공사에 전화 걸어 3초 통화 후 끊음
   3. 렌터카에 전화 걸어 3초 통화 후 끊음
   4. 보험사에 전화 걸어 3초 통화 후 끊음
   5. 공연기획사에 전화 걸어 3초 통화 후 끊음
   결과 -> 고객은 전화기를 붙잡고 무려 3 + 3 + 3 + 3 + 3 = 15초 동안 멍하니 기다리다 전화를 끊어버립니다!

✅ 병렬 비동기 I/O (Async Fan-Out / Gather):
   직원이 책상 위에 전화기 5대를 놓고 양손을 뻗어 5개 업체에 동시에 신호를 보냅니다(Fan-Out).
   각 업체가 회신해 오는 것을 논블로킹(Non-Blocking)으로 기다렸다가(Fan-In),
   가장 늦게 끝나는 업체의 응답 시간인 max(T_i) = 3초 만에 견적서를 완성해 고객에게 전달합니다!
```

마이크로서비스 아키텍처(MSA)나 백엔드 API 게이트웨이(BFF)를 처음 개발하는 초보 개발자나 AI 바이브 코더들이 가장 흔하게 저지르는 실수가 바로 **외부 API를 `for` 루프 돌려 순차적으로 호출하는 것**입니다.

각 서비스 응답이 500ms~1s씩만 걸려도, 5개만 엮이면 사용자 화면 로딩 시간이 5초~10초로 치솟아 이탈률이 폭증합니다.  
네트워크 I/O는 CPU를 쓰지 않고 대기하는 시간(Idle Waiting)이므로, **동시에 요청을 던져두고 한꺼번에 수거하는 비동기 병렬 I/O(Fan-Out / Fan-In)**가 필수적입니다!

---

## 2. 문제 개요

당신은 슈퍼앱(Super App)의 통합 대시보드 API를 최적화해야 하는 시니어 백엔드 엔지니어입니다.  
여러 외부 마이크로서비스(Subtask)를 호출하는 요청들이 주어질 때,  
기존의 **직렬 순차 호출 모델(SERIAL_SYNC)**과 `asyncio.gather` / `CompletableFuture.allOf` 스타일의 **병렬 비동기 모델(PARALLEL_ASYNC)**을 시뮬레이션하고,  
지연 시간 단축률(`AVG_SPEEDUP`)과 부분 실패 처리 정책(`FAIL_FAST`, `ALL_SETTLED`)에 따른 동작을 정밀 검증하세요.

### 시뮬레이션 상세 규칙

#### 1. 공통 환경
- `GLOBAL_TIMEOUT <timeout_ms>`: 메인 요청 전체에 허용된 최대 시간 한도 (ms, $1 \le timeout\_ms \le 60,000$).
- `PARTIAL_FAILURE_POLICY <FAIL_FAST | ALL_SETTLED>`: 부분 실패 처리 전략.
  - `FAIL_FAST`: 서브태스크 중 하나라도 실패(`ERROR` 또는 개별 타임아웃)하면 즉시 전체 작업을 중단하고 실패 처리.
  - `ALL_SETTLED`: 모든 서브태스크가 완료되거나 글로벌 타임아웃에 도달할 때까지 끝까지 기다린 후, 성공한 데이터는 최대한 살려 반환(우아한 성능 저하, Graceful Degradation).

#### 2. 직렬 동기 모델 (SERIAL_SYNC)
서브태스크들을 입력 순서대로 하나씩 차례대로 동기 블로킹 방식으로 실행합니다.
- 누적 소요 시간 `elapsed = 0`.
- 각 서브태스크마다:
  - 만약 $elapsed + task.duration > timeout\_ms$ 라면:
    - 글로벌 타임아웃 발생! 즉시 중단: `TIMEOUT (timeout_ms ms)`.
  - $elapsed += task.duration$.
  - 만약 $task.status == "ERROR"$ 라면:
    - `FAIL_FAST` 정책인 경우: 즉시 전체 중단하고 종료: `FAILED (elapsed ms)`.
    - `ALL_SETTLED` 정책인 경우: 실패를 기록하고 다음 서브태스크를 계속 실행.
- 모든 서브태스크를 순회 완료했을 때:
  - `ALL_SETTLED` 정책이고 실패한 태스크가 1개 이상 존재할 때:
    - 만약 모든 태스크가 `ERROR`라면: `FAILED (elapsed ms)`.
    - 성공한 태스크가 1개라도 있다면: `DEGRADED_SUCCESS (elapsed ms)`.
  - 에러가 없었다면: `SUCCESS (elapsed ms)`.

#### 3. 병렬 비동기 모델 (PARALLEL_ASYNC)
모든 서브태스크가 $t=0$ 시점에 동시에 시작됩니다 (Fan-Out).
- 각 태스크의 완료 시점은 $task.duration$입니다. 만약 $task.duration > timeout\_ms$이면 해당 태스크는 타임아웃 실패입니다.
- **`FAIL_FAST` 정책**:
  - 서브태스크 중 가장 먼저 발생한 실패(완료 시점의 `ERROR` 또는 `timeout_ms` 시점의 타임아웃)를 찾습니다.
  - 만약 실패가 존재한다면:
    - 가장 빠른 실패 시점 $T = \min(first\_error\_time, timeout\_ms)$.
    - 만약 $first\_error\_time \le timeout\_ms$이면: `FAILED (T ms)`.
    - 만약 타임아웃이 더 빠르거나 타임아웃만 있다면: `TIMEOUT (timeout_ms ms)`.
  - 모든 태스크가 정상(`OK`)이고 타임아웃 이내라면:
    - 소요 시간 $T = \max_{task}(task.duration)$ (태스크가 없으면 0ms).
    - 상태: `SUCCESS (T ms)`.
- **`ALL_SETTLED` 정책**:
  - 모든 태스크가 완료되거나 글로벌 타임아웃에 도달할 때까지 대기합니다.
  - 소요 시간 $T = \min(timeout\_ms, \max_{task}(task.duration))$ (태스크가 없으면 0ms).
  - 정상 완료 태스크 수 $ok\_cnt$, 에러 태스크 수 $err\_cnt$, 타임아웃 태스크 수 $to\_cnt$ 집계:
    - 만약 $ok\_cnt == len(tasks)$ (모두 정상): `SUCCESS (T ms)`.
    - 만약 $ok\_cnt > 0$ (일부 성공): `DEGRADED_SUCCESS (T ms)`.
    - 만약 $ok\_cnt == 0$ (전원 실패):
      - $err\_cnt > 0$이면 `FAILED (T ms)`, 전원 타임아웃이면 `TIMEOUT (timeout_ms ms)`.

---

## 3. 입력 형식

```text
GLOBAL_TIMEOUT <timeout_ms>
PARTIAL_FAILURE_POLICY <FAIL_FAST | ALL_SETTLED>
REQUESTS <R>
REQ <req_id> SUBTASKS <K>
SUBTASK <task_name> DURATION <duration_ms> STATUS <OK | ERROR>
... (총 K개의 SUBTASK)
... (총 R개의 REQ)
```

- `timeout_ms`: 글로벌 타임아웃 (ms, 정수)
- `PARTIAL_FAILURE_POLICY`: `FAIL_FAST` 또는 `ALL_SETTLED`
- `R`: 요청 총 개수 ($1 \le R \le 30,000$)
- `K`: 서브태스크 개수 ($0 \le K \le 20$)
- `duration_ms`: 서브태스크 실행 소요 시간 (ms, 정수)
- `STATUS`: `OK` 또는 `ERROR`

---

## 4. 출력 형식

각 요청마다 한 줄씩 출력합니다:
```text
REQ <req_id> SERIAL:<serial_status>(<serial_time>ms) PARALLEL:<parallel_status>(<parallel_time>ms) LATENCY_IMPROVEMENT:<latency_diff>ms
```
- `<serial_status>`, `<parallel_status>`: `SUCCESS`, `DEGRADED_SUCCESS`, `FAILED`, `TIMEOUT`
- `<latency_diff>`: $\max(0, serial\_time - parallel\_time)$ (단축된 지연시간)

모든 요청 처리 후 마지막 줄에 요약 통계를 출력합니다:
```text
SUMMARY TOTAL_REQS:<R> SERIAL_TOTAL_TIME:<sum_s>ms PARALLEL_TOTAL_TIME:<sum_p>ms TOTAL_LATENCY_SAVED:<sum_saved>ms AVG_SPEEDUP:<speedup>x
```
- `<speedup>`: 직렬 총 소요 시간 대비 병렬 소요 시간 단축 배율 $\frac{sum\_s}{sum\_p}$ (소수점 첫째 자리까지 반올림 표기, 예: `3.3x`, `1.0x`).

---

## 5. 입출력 예시

### 예시 입력 1
```text
GLOBAL_TIMEOUT 5000
PARTIAL_FAILURE_POLICY ALL_SETTLED
REQUESTS 3
REQ req_01 SUBTASKS 5
SUBTASK hotel DURATION 800 STATUS OK
SUBTASK flight DURATION 1200 STATUS OK
SUBTASK car DURATION 600 STATUS OK
SUBTASK insurance DURATION 400 STATUS OK
SUBTASK ticket DURATION 1000 STATUS OK
REQ req_02 SUBTASKS 4
SUBTASK hotel DURATION 900 STATUS OK
SUBTASK flight DURATION 1500 STATUS OK
SUBTASK tour DURATION 500 STATUS ERROR
SUBTASK car DURATION 700 STATUS OK
REQ req_03 SUBTASKS 3
SUBTASK api_a DURATION 2000 STATUS OK
SUBTASK api_b DURATION 2500 STATUS OK
SUBTASK api_c DURATION 1500 STATUS OK
```

### 예시 출력 1
```text
REQ req_01 SERIAL:SUCCESS(4000ms) PARALLEL:SUCCESS(1200ms) LATENCY_IMPROVEMENT:2800ms
REQ req_02 SERIAL:DEGRADED_SUCCESS(3600ms) PARALLEL:DEGRADED_SUCCESS(1500ms) LATENCY_IMPROVEMENT:2100ms
REQ req_03 SERIAL:TIMEOUT(5000ms) PARALLEL:SUCCESS(2500ms) LATENCY_IMPROVEMENT:2500ms
SUMMARY TOTAL_REQS:3 SERIAL_TOTAL_TIME:12600ms PARALLEL_TOTAL_TIME:5200ms TOTAL_LATENCY_SAVED:7400ms AVG_SPEEDUP:2.4x
```

### 설명
- **`req_01`**: 5개 API가 모두 성공했습니다.
  - SERIAL: $800 + 1200 + 600 + 400 + 1000 = 4000$ms 소요.
  - PARALLEL: 가장 오래 걸린 `flight`(1200ms) 시간에 5개 전원 완료! **2.8초나 지연시간을 단축**했습니다.
- **`req_02`**: `tour` 서브태스크가 에러를 냈지만, `ALL_SETTLED` 정책 덕분에 둘 다 `DEGRADED_SUCCESS`로 나머지 3개 정상 데이터를 보존했습니다. PARALLEL은 1500ms 만에 신속 완료되었습니다.
- **`req_03`**: SERIAL은 합산이 6000ms가 되어 `GLOBAL_TIMEOUT`(5000ms)에 걸려 타임아웃 폭사했지만, PARALLEL은 2500ms 만에 여유롭게 `SUCCESS`를 거두었습니다.
- **최종 요약**: 병렬 비동기 처리를 통해 전체 응답 속도가 **2.4배(`2.4x`) 빨라졌습니다.**
