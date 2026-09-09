# #153 카프카 파티션은 1개인데 스레드 16개로 병렬 처리하고 싶어요!: 인-프로세스 키 기반 병렬 컨슈머(Parallel Consumer)와 오프셋 워터마크(Low Watermark Offset) 안전 커밋

## 문제 배경 및 장애 상황

글로벌 결제/이커머스 플랫폼 'ZeliPay'는 분산 이벤트 스트리밍 백본으로 **Apache Kafka**를 운용하고 있습니다.

주문 및 결제 트랜잭션 이벤트 토픽(`payment-events`)의 단일 파티션에는 다음과 같은 특성이 있습니다:
* 카프카의 근본 설계 원칙상 **1개 파티션은 오직 1개의 컨슈머 스레드**만 할당받아 순차적으로 소비(Consume)할 수 있습니다.
* 각 이벤트는 외부 카드사 결제 승인 API 호출, FDS(이상거래탐지) 실시간 스코어링, 알림톡 발송 등 무거운 네트워크 I/O를 수반하여 레코드당 **50ms ~ 300ms**의 처리 시간이 소요됩니다.
* 단일 스레드 순차 처리 시 초당 처리량은 기껏해야 3~5 req/sec에 불과합니다.

```
       Kafka Broker (Topic: payment-events)
       ┌───────────────────────────────────────────────┐
       │ Partition 0: [0] [1] [2] [3] [4] [5] [6] ...  │
       └───────────────────────┬───────────────────────┘
                               │ Poll Records
                               ▼
                   [ Parallel Consumer Engine ]
                Key-Ordered Concurrency & Dispatcher
            ┌──────────────┬──────────────┬──────────────┐
            ▼              ▼              ▼              ▼
       [Worker 0]     [Worker 1]     [Worker 2]     [Worker 3]
       Offset: 0      Offset: 1      Offset: 2      Offset: 4
       Key: A         Key: B         Key: C         Key: D
       Cost: 200ms    Cost: 20ms     Cost: 30ms     Cost: 40ms
            │              │              │              │
            │              ▼ t=20ms       ▼ t=30ms       ▼ t=40ms
            │          [COMPLETED]    [COMPLETED]    [COMPLETED]
            │          (Hole #1)      (Hole #2)      (Hole #3)
            │
            │◄── Safe Watermark held at 0 (Cannot commit!)
            │
            ▼ t=200ms
       [COMPLETED]
            │
            └──► Safe Watermark JUMPS to 3 (Safe to commit 3!)
```

블랙 프라이데이 타임세일 이벤트 당일, 초당 2,000건의 결제 트래픽이 쏟아지자 **Consumer Lag이 30분 만에 50만 건**을 돌파하며 전사 장애가 선포되었습니다!

### 비극적인 오답 1: 파티션을 무작정 1,000개로 늘린다?
인프라팀은 처리량을 늘리기 위해 파티션 수를 100개, 500개로 무작정 증설했습니다. 그러나 파티션이 증가할수록:
1. 브로커 파일 핸들(File Descriptor) 및 OS 페이지 캐시 경합 급증.
2. 파드 재배포 시 리밸런싱 지연(Rebalance Storm) 발생.
3. 엔터티 키 라우팅이 분산되어 단일 파티션 내 순서 보장의 의미가 퇴색됨.

### 비극적인 오답 2: 컨슈머 내부에서 일반 `ThreadPoolExecutor`에 던지고 최신 완료 오프셋을 커밋한다?
주니어 엔지니어가 컨슈머 루프 안에서 레코드들을 Java의 `ExecutorService` 스레드 풀에 던지고, 작업이 끝날 때마다 가장 큰 오프셋을 브로커에 `commitSync(offset)`했습니다.
* **100번 오프셋**(느린 PG사 승인, 200ms)과 **101번, 102번 오프셋**(빠른 캐시 조회, 20ms)을 동시에 스레드에 할당.
* 101번, 102번이 20ms 만에 먼저 완료되자, 컨슈머는 브로커에 `commitSync(103)`을 전송했습니다.
* 그런데 100번 작업이 실행 중이던 워커 파드가 메모리 부족(OOM)으로 불시에 강제 종료되었습니다!
* 재시작된 컨슈머는 브로커의 커밋 오프셋인 103번부터 메시지를 읽어오기 시작했고, 아직 끝나지 않았던 **100번 고객의 1억 원짜리 결제 이벤트는 영구 소실(Silent Data Loss)** 되는 초대형 금융 사고로 번졌습니다!

### 비극적인 오답 3: 동일 유저의 주문/취소가 뒤집혀 처리된다?
서로 다른 스레드가 동일 유저 `USER_123`의 "주문 결제(Offset 10)"와 "결제 취소(Offset 15)"를 병렬로 실행하면서, 네트워크 지연에 의해 "결제 취소"가 먼저 완료되고 나중에 "주문 결제"가 승인되어 고객 계좌에서 돈이 빠져나간 채 주문이 남아버렸습니다!

---

## 구원 아키텍처: Confluent Parallel Consumer 패턴

시니어 아키텍처팀은 Confluent의 공식 병렬 컨슈머(`parallel-consumer`) 패턴을 도입하여 단일 파티션에서도 완벽한 안전성을 보장하는 고성능 병렬 소비 엔진을 구축하기로 결정했습니다:

1. **키 단위 순서 보장 (Key-Ordered Concurrency)**:
   - 동일한 `key`를 가진 레코드들은 무조건 **엄격한 FIFO 순서**로 순차 처리됩니다 (선행 레코드가 완료되기 전까지 후행 레코드는 워커에 할당되지 않고 큐에서 대기).
   - 서로 다른 `key`를 가진 레코드들은 상호 독립적이므로 가용 워커 스레드 풀에서 **완전 병렬(Parallel)** 로 동시 실행됩니다.
2. **연속 최소 오프셋 안전 워터마크 커밋 (Low Watermark Offset Commit)**:
   - 카프카의 단일 누적 오프셋 커밋 모델을 준수하기 위해, **완료되지 않은 가장 작은 오프셋($O_{min\_uncompleted}$)** 을 연속적으로 추적합니다.
   - 안전 커밋 오프셋(Watermark)은 $0$번부터 $O_{watermark}-1$까지의 모든 레코드가 단 하나의 구멍(Hole) 없이 연속적으로 완료되었을 때만 전진합니다!
   - 101번, 102번이 먼저 끝나도 100번이 실행 중이면 워터마크는 0에 머물러 조기 커밋에 의한 유실을 원천 차단합니다.
   - 100번이 마침내 완료되는 순간, 이미 완료된 101번, 102번까지 한 번에 포섭하여 워터마크가 103으로 시원하게 점프합니다!
3. **인플라이트 백프레셔 제어 (`MAX_IN_FLIGHT`)**:
   - 워커 풀이 감당할 수 있는 최대 동시 실행 작업 수(`MAX_IN_FLIGHT`)를 제한하여 OOM을 방지합니다.

당신은 이산 사건 시뮬레이션(Discrete-Event Simulation) 기법을 기반으로, Kafka Key-Ordered Parallel Consumer 엔진을 구현하고 벤치마크 및 안전성을 검증해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 다음 형식의 설정과 레코드 목록이 주어집니다:

1. **첫 번째 줄**: 워커 스레드 수와 최대 인플라이트 제한
   ```text
   WORKERS <num_workers> MAX_IN_FLIGHT <max_in_flight>
   ```
2. **두 번째 줄**: 레코드 총 개수 $N$
   ```text
   RECORDS <N>
   ```
3. **다음 $N$개 줄**: 각 레코드의 상세 정보 (오프셋 오름차순)
   ```text
   <offset> <key> <cost_ms> <arrival_time_ms>
   ```
   * `offset`: 파티션 내 고유 오프셋 ($0$부터 시작하는 정수)
   * `key`: 비즈니스 엔터티 키 (문자열, 예: `USER_1`, `ORDER_A`)
   * `cost_ms`: 처리 소요 시간 (밀리초 정수, $\ge 1$)
   * `arrival_time_ms`: 카프카 파티션에서 컨슈머 버퍼로 인입된 절대 물리 시간 (밀리초 정수, $\ge 0$)
4. **마지막 줄**: `END`

---

## 디스패치 및 스케줄링 규칙

1. **시간 진행**: 이산 사건 시뮬레이션(DES)으로 진행하며, 이벤트는 레코드 인입(`arrival_time`)과 작업 완료(`finish_time`)입니다.
2. **동일 완료 시간 결정론적 정렬**: 복수의 작업이 동일한 밀리초에 완료될 경우, `offset` 오름차순으로 처리 순서를 확정합니다.
3. **디스패치 우선순위**:
   * 버퍼에 대기 중인 레코드 중,
   * 유휴 워커(`idle_workers`)가 존재하고,
   * 현재 실행 중인 작업 수 < `MAX_IN_FLIGHT`이며,
   * 해당 레코드의 `key`가 현재 다른 워커에서 실행 중이지 않을 때(Key Lock 미보유),
   * 가장 낮은 오프셋을 가진 레코드부터 유휴 워커(워커 번호가 가장 작은 워커)에 즉시 할당합니다.
   * 작업 시작 시각: $T_{start} = \max(T_{current}, record.arrival\_time)$
   * 작업 종료 시각: $T_{finish} = T_{start} + record.cost\_ms$
4. **워터마크 전진**:
   * 작업 완료 시 해당 오프셋을 완료 집합에 추가합니다.
   * `safe_commit_watermark`는 $0$부터 시작하여, 완료 집합에 연속적으로 존재하는 한 계속 $+1$씩 증가합니다.
   * 워터마크가 이전 값에서 전진할 때마다 그 시점의 `(finish_time, safe_commit_watermark)`를 기록합니다.
5. **구멍 방어 카운트 (`HOLES_PREVENTED`)**:
   * 어떤 작업이 완료되었을 때, 해당 오프셋이 당시의 `safe_commit_watermark`보다 크다면(즉, 앞선 오프셋 중 아직 미완료된 구멍이 존재하여 성급한 커밋을 방어했다면), `HOLES_PREVENTED` 카운터를 $+1$ 증가시킵니다.

---

## 출력 형식

총 5줄로 구성된 분석 보고서를 출력합니다:

```text
EXECUTION_ORDER: <off1>@<t1>,<off2>@<t2>,...
KEY_ORDER_STATUS: VALID (0 violations) | VIOLATION (<n> violations)
HOLES_PREVENTED: <holes_count>
WATERMARK_PROGRESSION: (<t1>,<off1>)->(<t2>,<off2>)->...
BENCHMARK: SEQ=<seq_ms>ms PAR=<par_ms>ms SPEEDUP=<speedup>x
```

* `EXECUTION_ORDER`: 실제 작업이 완료된 순서대로 `오프셋@완료시간`을 쉼표로 연결하여 출력합니다.
* `KEY_ORDER_STATUS`: 동일 키 내에서 후행 레코드가 선행 레코드의 완료 시간보다 일찍 시작된 적이 없다면 `VALID (0 violations)`, 있다면 위반 건수 출력.
* `HOLES_PREVENTED`: 성급하게 커밋했을 경우 데이터 유실 구멍(Hole)이 되었을 오프셋 완료 횟수.
* `WATERMARK_PROGRESSION`: 안전 커밋 오프셋이 갱신된 이력 `(시각,워터마크)`를 `->`로 연결하여 출력.
* `BENCHMARK`:
  * `SEQ`: 단일 스레드 순차 처리 시 총 소요 시간 (모든 레코드 `cost_ms`의 합).
  * `PAR`: 병렬 컨슈머로 전체 작업이 완료된 최종 시각.
  * `SPEEDUP`: `SEQ / PAR` 비율을 소수점 둘째 자리까지 반올림 포맷 (`0.00x`).

---

## 입출력 예시

### 예제 입력 1
```text
WORKERS 4 MAX_IN_FLIGHT 8
RECORDS 5
0 A 200 0
1 B 20 0
2 C 30 0
3 A 50 0
4 D 40 0
END
```

### 예제 출력 1
```text
EXECUTION_ORDER: 1@20,2@30,4@40,0@200,3@250
KEY_ORDER_STATUS: VALID (0 violations)
HOLES_PREVENTED: 3
WATERMARK_PROGRESSION: (200,3)->(250,5)
BENCHMARK: SEQ=340ms PAR=250ms SPEEDUP=1.36x
```

### 예제 1 상세 해설
1. $t=0$:
   * 오프셋 0 (Key `A`, 200ms) $\to$ Worker 0 할당 (종료 예정 200ms)
   * 오프셋 1 (Key `B`, 20ms) $\to$ Worker 1 할당 (종료 예정 20ms)
   * 오프셋 2 (Key `C`, 30ms) $\to$ Worker 2 할당 (종료 예정 30ms)
   * 오프셋 3 (Key `A`, 50ms) $\to$ Key `A`가 Worker 0에서 실행 중이므로 **할당 불가, 큐 대기!**
   * 오프셋 4 (Key `D`, 40ms) $\to$ Worker 3 할당 (종료 예정 40ms)
2. $t=20$: 오프셋 1 완료. 하지만 오프셋 0이 미완료이므로 워터마크는 0 유지! (구멍 #1 방어)
3. $t=30$: 오프셋 2 완료. 워터마크 0 유지 (구멍 #2 방어)
4. $t=40$: 오프셋 4 완료. 워터마크 0 유지 (구멍 #3 방어)
5. $t=200$: 오프셋 0 완료!
   * $0, 1, 2$번 오프셋이 모두 완료되었으므로 **워터마크가 즉시 3으로 점프!** `(200,3)`
   * Key `A`의 락이 해제되어 대기 중이던 오프셋 3 (Key `A`, 50ms)이 즉시 할당되어 $t=250$에 완료 예정.
6. $t=250$: 오프셋 3 완료!
   * $3, 4$번까지 모두 완료되었으므로 워터마크가 5로 최종 점프! `(250,5)`
7. 단일 스레드 대비 $340\text{ms} \to 250\text{ms}$로 $1.36\times$ 단축, 키 순서 위반 $0$건, 데이터 유실 위험 구멍 $3$건을 안전하게 방어했습니다!
