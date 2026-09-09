# 카프카 메시지 1개 재시도했을 뿐인데 왜 뒤의 100만 개가 멈춰요?!: HOL 블로킹과 논블로킹 재시도 큐 (Kafka Non-Blocking Retry & DLT)

## 문제 설명

대규모 이벤트 기반 마이크로서비스 아키텍처(MSA)에서 아파치 카프카(Apache Kafka)를 사용할 때 가장 흔하게 발생하는 재앙 중 하나는 **"불량 메시지 1개의 재시도 때문에 뒤따라오던 수백만 건의 정상 메시지가 모조리 멈춰 서는 Head-of-Line (HOL) 블로킹"**입니다.

카프카의 파티션(Partition)은 엄격한 순서 보장(Ordering)을 원칙으로 합니다.  
만약 컨슈머가 특정 결제 메시지를 처리하다가 일시적인 외부 PG사 타임아웃을 만나 실패했을 때, 전통적인 방식처럼 그 자리에서 `Thread.sleep(5000)`으로 대기하며 재시도(In-place Retry)를 시도한다면:

1. 실패한 메시지가 톨게이트 1차로를 가로막고 서서 오프셋 커밋(`commitOffset`)을 하지 못합니다.
2. 파티션 뒤에 줄 서 있던 **수십만 건의 정상 결제 메시지들이 단 1건도 처리되지 못하고 대기열에 갇힙니다(HOL Blocking)**.
3. 재시도 대기 시간이 5분(`max.poll.interval.ms`)을 초과하면, 브로커는 컨슈머가 죽은 줄 알고 그룹에서 강제 퇴출시켜 전사 **컨슈머 리밸런스 폭풍(Rebalance Storm)**까지 일으킵니다.

### 🚀 우버(Uber)와 스프링 카프카의 해법: 다단계 논블로킹 재시도 토픽
우버(Uber) 엔지니어링 팀과 스프링 카프카(`@RetryableTopic`)는 이 문제를 해결하기 위해 **신속 갓길 이동(Off-ramp)** 아키텍처를 표준화했습니다:

- **메인 토픽 (`MAIN`)**:
  - 메시지가 실패하면 그 자리에서 버티지 않고, 즉시 1차 재시도 토픽(`RETRY_1`)으로 전달한 뒤 **메인 토픽의 오프셋을 즉시 커밋**합니다.
  - 뒤따라오던 정상 메시지들은 **단 1ms의 지체도 없이 0초 만에 정상 처리**됩니다.
- **다단계 지연 재시도 토픽 (`RETRY_1`, `RETRY_2`)**:
  - 실패한 메시지는 별도의 전용 재시도 토픽으로 격리되어 지정된 지연 시간(예: 5초, 30초) 후에 재시도됩니다.
- **데드 레터 토픽 (`DLT`)**:
  - 모든 재시도 횟수를 소진한 독약 메시지(Poison Pill)는 최종적으로 DLT로 이동하여 운영자 분석을 위해 격리됩니다.

당신은 전통적 블로킹 재시도 방식과 현대적 논블로킹 다단계 재시도 아키텍처를 시뮬레이션하는 엔진을 구현해야 합니다.

---

## 시뮬레이션 규칙

### 1. 두 가지 실행 모드 (`mode`)
- **`NON_BLOCKING` (기본값 / 우버 & 스프링 카프카 표준)**:
  - `MAIN` 토픽에서 메시지가 실패하면, 즉시 `execute_at = current_time + retry1_delay`로 1차 재시도 큐(`RETRY_1`)에 넣고 메인 토픽 오프셋을 즉시 커밋합니다.
  - 메인 큐의 다음 정상 메시지는 **블로킹 없이 즉시 처리**됩니다.
  - `RETRY_1` 큐의 메시지는 `current_time >= execute_at`가 되었을 때 재시도됩니다.
    - 성공 시: 정상 완료 (`total_success += 1`).
    - 실패 시: `execute_at = current_time + retry2_delay`로 2차 재시도 큐(`RETRY_2`)로 이동.
  - `RETRY_2` 큐의 메시지가 또 실패하면 최대 재시도 한도 초과로 즉시 사장 메시지 큐(`DLT`)로 격리됩니다.
- **`BLOCKING` (전통적 In-place 재시도)**:
  - 단일 파티션 큐에서 메시지가 실패하면, 해당 메시지가 성공하거나 최대 재시도(2회 재시도, 총 3회 시도) 후 DLT로 이동할 때까지 **다음 메시지로 넘어가지 못하고 파티션 전체가 동결(`HOL_BLOCKED = true`)**됩니다.
  - 1차 실패 시: `next_attempt_time = current_time + retry1_delay`
  - 2차 실패 시: `next_attempt_time = current_time + retry2_delay`
  - 3차 실패 시: DLT로 이동 후 비로소 다음 메시지 처리 가능.

### 2. 메시지 실패 시뮬레이션
- 각 메시지는 `fail_count` 속성을 가집니다.
- 메시지를 처리할 때:
  - `fail_count == 0`이면 처리에 성공합니다.
  - `fail_count > 0`이면 처리에 실패하고 `fail_count -= 1`, `attempts += 1`이 됩니다.

---

## 명령어 명세

모든 명령어는 표준 입력(stdin)으로 한 줄씩 주어지며, 인자는 `key=value` 형태 또는 공백 구분 위치 인자를 지원합니다.

1. **`CONFIG mode=<BLOCKING|NON_BLOCKING> retry1_delay=<sec> retry2_delay=<sec>`**
   - 시스템 동작 모드와 단계별 지연 시간을 설정합니다. (기본값: `mode=NON_BLOCKING, retry1_delay=5, retry2_delay=30`)
   - 출력: `CONFIG_OK mode=<mode> retry1_delay=<r1> retry2_delay=<r2>`

2. **`PRODUCE id=<msg_id> fail_count=<int>`**
   - 메인 토픽에 새 메시지를 발행합니다.
   - 출력: `PRODUCE_OK id=<id> fail_count=<fail_count>`

3. **`TICK <seconds>`**
   - 시뮬레이션 시간을 `<seconds>`초만큼 전진시킵니다.
   - 출력: `TICK_OK time=<current_time>`

4. **`PROCESS`**
   - 현재 시각(`current_time`) 기준으로 컨슈머 폴링 및 메시지 처리를 1회 실행합니다.
   - 출력: `PROCESS_OK mode=<mode> time=<current_time>`

5. **`STATUS`**
   - 현재 큐 및 처리 현황을 덤프합니다.
   - 출력 형식:
     ```
     --- KAFKA_RETRY_STATUS ---
     TIME: <current_time>s
     MODE: <BLOCKING|NON_BLOCKING>
     MAIN_PROCESSED: <int>
     MAIN_PENDING: <int>
     RETRY_1_PENDING: <int>
     RETRY_2_PENDING: <int>
     DLT_COUNT: <int>
     TOTAL_SUCCESS: <int>
     HOL_BLOCKED: <true|false>
     --- END_STATUS ---
     ```

6. **`RESET`**
   - 모든 큐, 지표, 시간을 초기 상태로 리셋합니다.
   - 출력: `RESET_OK`

---

## 입출력 예시

### 예시 입력
```
CONFIG mode=NON_BLOCKING retry1_delay=5 retry2_delay=30
PRODUCE id=order1 fail_count=1
PRODUCE id=order2 fail_count=0
PRODUCE id=order3 fail_count=0
PROCESS
STATUS
```

### 예시 출력
```
CONFIG_OK mode=NON_BLOCKING retry1_delay=5 retry2_delay=30
PRODUCE_OK id=order1 fail_count=1
PRODUCE_OK id=order2 fail_count=0
PRODUCE_OK id=order3 fail_count=0
PROCESS_OK mode=NON_BLOCKING time=0
--- KAFKA_RETRY_STATUS ---
TIME: 0s
MODE: NON_BLOCKING
MAIN_PROCESSED: 3
MAIN_PENDING: 0
RETRY_1_PENDING: 1
RETRY_2_PENDING: 0
DLT_COUNT: 0
TOTAL_SUCCESS: 2
HOL_BLOCKED: false
--- END_STATUS ---
```
