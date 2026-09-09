# 카프카 컨슈머 흐름 제어: max.poll.interval.ms 타임아웃 리밸런스 폭풍 vs Pause/Resume 리액티브 백프레셔

## 문제 배경 및 개요
글로벌 핀테크 및 이커머스 이벤트 스트리밍 파이프라인(주문 체결, 결제 승인, 정산 이벤트)에서 Apache Kafka는 대규모 비동기 메시지 전달의 핵심 허브입니다.
컨슈머 애플리케이션(Java Spring Kafka, Go Sarama, Python Kafka)은 브로커의 토픽 파티션으로부터 레코드 배치를 폴링(`poll()`)하여 다운스트림 데이터베이스(PostgreSQL, MongoDB)나 외부 결제대행사(PG) API로 전달합니다.

그러나 트래픽 피크 타임에 다운스트림 데이터베이스의 락 경합이나 네트워크 스톨로 인해 레코드당 처리 지연시간이 5ms에서 120ms로 급증했을 때, 전통적인 컨슈머 구현 방식에서 파괴적인 연쇄 재앙이 발생했습니다:

1. **동기식 블로킹 컨슈머의 리밸런스 지옥 (`CONSUMER_REBALANCE_STORM_COLLAPSE`)**:
   - 나이브한 단일 스레드 컨슈머는 `poll()`로 50개 배치를 가져온 후, 해당 루프 내에서 동기식으로 비즈니스 로직을 처리합니다.
   - 평소에는 250ms(50 * 5ms) 만에 끝나 다음 `poll()`을 즉시 호출하지만, DB 지연이 120ms로 튀면 배치 처리에 6000ms(50 * 120ms)가 소요됩니다.
   - 이때 카프카 컨슈머의 안전장치인 `max.poll.interval.ms`(기본 또는 설정값 5000ms)를 초과하게 됩니다.
   - 카프카 그룹 코디네이터(Group Coordinator)는 해당 컨슈머가 죽었다고(Dead/Hung) 판단하여 **컨슈머 그룹에서 강제 제명(Revoke)하고 리밸런스(Rebalance)를 발동**합니다.
   - 제명당한 파티션은 다른 정상 컨슈머에게 재할당되지만, 그 컨슈머 역시 동일한 DB 병목을 만나 연쇄 퇴출당하며 클러스터 전체가 멈추는 **캐스케이딩 리밸런스 폭풍(Cascading Rebalance Storm)**으로 번집니다.
2. **무제한 비동기 버퍼링의 OOM 폭사 (`CONSUMER_UNBOUNDED_BUFFER_OOM_CRASH`)**:
   - `max.poll.interval.ms` 초과를 막겠다고 `poll()` 전용 스레드와 워커 스레드 풀을 분리하고 그 사이에 인메모리 큐를 두었으나, 백프레셔(Backpressure)가 없는 무제한 큐를 사용했습니다.
   - 다운스트림 처리는 초당 수십 건으로 느려졌는데 `poll()` 스레드는 초당 수만 건을 무차별적으로 큐에 밀어 넣으면서 큐가 수 기가바이트로 폭증하여 JVM Full GC 스톨 및 OOM-Killer 강제 피살이 발생했습니다.

현대 카프카 아키텍처는 이를 해결하기 위해 **`consumer.pause()` / `consumer.resume()` 기반 리액티브 백프레셔(Reactive Backpressure)**를 사용합니다:
- 컨슈머는 워커 풀과의 사이에 유계 큐(Bounded Queue, `buffer_capacity`)를 유지합니다.
- 큐 적재량이 상한 임계치(High Watermark)에 도달하면 `consumer.pause(partitions)`를 호출하여 브로커로부터의 추가 레코드 유입을 일시 차단합니다.
- **핵심 구원 원리**: 파티션이 일시정지(Paused)된 상태에서도 컨슈머 이벤트 루프는 주기적으로 `consumer.poll(0)`을 계속 호출합니다! 브로커로부터 레코드는 0건 가져오지만, **그룹 코디네이터에게 하트비트와 생존 신호를 끊임없이 전달하여 `max.poll.interval.ms` 타임아웃을 원천 방어**합니다.
- 워커 풀이 버퍼를 비워 하한 임계치(Low Watermark) 이하로 내려가면 `consumer.resume(partitions)`를 호출하여 정상 레코드 인출을 재개합니다 (`OPTIMAL_KAFKA_PAUSE_RESUME_BACKPRESSURE`).

당신은 카프카 컨슈머 이벤트 루프 시뮬레이터를 구현하여, 다운스트림 병목 상황에서 동기식 블로킹의 리밸런스 폭풍과 무제한 큐의 OOM 참사를 재현하고, Pause/Resume 기반 리액티브 백프레셔의 무손실 무중단 완벽 동작을 검증해야 합니다.

---

## 시스템 동작 규칙 및 상태 머신

### 1. 컨슈머 모드별 동작 정의

#### A. 동기식 블로킹 모드 (`mode == "naive_blocking"`)
- 단일 스레드가 `poll()`을 호출하여 최대 `poll_batch_size`개의 레코드를 가져옵니다.
- 가져온 레코드 수만큼 동기식으로 다운스트림 처리를 수행합니다 (`processing_time = fetch_count * delay_per_record`).
- 동기 처리 도중에는 `poll()`이 호출되지 않으므로, 소요 시간이 `max_poll_interval_ms`를 초과하면 즉시 `rebalances_count += 1`이 발생합니다.

#### B. 무제한 인메모리 큐 모드 (`mode == "naive_unbounded_buffer"`)
- `poll()` 스레드는 브로커에 데이터가 있는 한 백프레셔 없이 무조건 최대 배치씩 인출하여 인메모리 큐(`current_buffer`)에 적재합니다.
- 워커 스레드는 다운스트림 지연에 비례한 처리량(`drain_capacity = 1000 / delay_per_record`)만큼 큐를 비웁니다.
- `current_buffer`가 시스템 메모리 한도(`buffer_capacity`)를 초과하면 OOM 크래시(`oom_crashes_count += 1`)가 발생합니다.

#### C. 리액티브 Pause/Resume 모드 (`mode == "reactive_pause_resume"`)
- **수신 단계**:
  - `is_paused == False`인 경우:
    - 버퍼 여유 공간(`buffer_capacity - current_buffer`)과 브로커 잔여량 중 작은 값(최대 `poll_batch_size`)만큼 레코드를 인출하여 버퍼에 적재합니다.
    - 적재 직후 `current_buffer >= high_watermark`이면 즉시 `consumer.pause()`를 발동(`is_paused = True`, `pause_events_count += 1`)합니다.
  - `is_paused == True`인 경우:
    - 브로커로부터 레코드를 전혀 가져오지 않지만, `poll(0)`을 호출하여 코디네이터와의 하트비트를 유지하므로 `max.poll.interval.ms` 위반이 발생하지 않습니다.
- **워커 처리 단계**:
  - 워커 풀이 다운스트림 속도에 맞춰 버퍼의 레코드를 드레인합니다.
- **재개 단계**:
  - `is_paused == True`인 상태에서 버퍼 잔여량이 `current_buffer <= low_watermark`로 내려가면 즉시 `consumer.resume()`을 발동(`is_paused = False`, `resume_events_count += 1`)하여 다음 틱부터 레코드 인출을 재개합니다.

---

## 판정 기준 (System Status)

1. `CONSUMER_UNBOUNDED_BUFFER_OOM_CRASH`:
   - `oom_crashes_count > 0`: 무제한 버퍼링으로 인해 인메모리 적재량이 `buffer_capacity`를 초과하여 OOM으로 강제 종료된 상태.
2. `CONSUMER_REBALANCE_STORM_COLLAPSE`:
   - `rebalances_count > 0`: 동기식 처리 지연으로 `max.poll.interval.ms`를 초과하여 코디네이터에 의해 컨슈머가 퇴출되고 연쇄 리밸런스가 발생한 상태.
3. `OPTIMAL_KAFKA_PAUSE_RESUME_BACKPRESSURE`:
   - 리밸런스 0건, OOM 크래시 0건으로 High/Low Watermark 기반 Pause/Resume이 정상 작동하여 버퍼 안정성과 하트비트 생존성을 완벽히 양립한 상태.

---

## 입력 형식
표준 입력(`sys.stdin`)으로 다음 필드를 갖는 단일 JSON 객체가 주어집니다:
- `consumer_config`: 컨슈머 환경 설정
  - `mode`: `"naive_blocking"`, `"naive_unbounded_buffer"`, 또는 `"reactive_pause_resume"`
  - `max_poll_interval_ms`: 카프카 컨슈머 최대 폴링 간격 허용치 (밀리초, 실수)
  - `poll_batch_size`: 1회 poll당 최대 레코드 인출 수 (`max.poll.records`, 정수)
  - `buffer_capacity`: 인메모리 버퍼 최대 수용 한도 (정수)
  - `high_watermark`: `consumer.pause()`를 발동할 큐 상한 임계치 (정수)
  - `low_watermark`: `consumer.resume()`을 발동할 큐 하한 임계치 (정수)
- `steps`: 시간 흐름에 따른 트래픽 및 다운스트림 상태 단계 목록
  - `timestamp_ms`: 현재 단계 시작 타임스탬프 (밀리초, 실수)
  - `broker_records`: 브로커 토픽에 새로 유입/대기 중인 레코드 건수 (정수)
  - `downstream_delay_per_record_ms`: 해당 구간 다운스트림 처리 소요 시간 (밀리초, 실수)

---

## 출력 형식
표준 출력(`sys.stdout`)으로 다음 필드를 갖는 단일 JSON 객체를 인덴트 2칸(`indent=2`)으로 출력해야 합니다:
- `status`: 판정 결과 문자열 (`CONSUMER_REBALANCE_STORM_COLLAPSE` | `CONSUMER_UNBOUNDED_BUFFER_OOM_CRASH` | `OPTIMAL_KAFKA_PAUSE_RESUME_BACKPRESSURE`)
- `metrics`:
  - `total_records_fetched`: 브로커에서 인출된 총 레코드 수
  - `total_records_processed`: 다운스트림 처리가 완료된 총 레코드 수
  - `rebalances_count`: 발생한 리밸런스 횟수
  - `pause_events_count`: `consumer.pause()` 호출 횟수
  - `resume_events_count`: `consumer.resume()` 호출 횟수
  - `oom_crashes_count`: OOM 크래시 발생 횟수
  - `peak_buffer_size`: 인메모리 큐에 동시 적재된 최대 레코드 수
  - `max_poll_lag_ms`: `poll()` 호출 간 최대 경과 지연 시간 (밀리초, 소수점 1자리)
  - `unprocessed_backlog`: 미처리 잔여 레코드 수 (브로커 잔여량 + 버퍼 잔여량)
- `root_cause_analysis`: 한국어 원인 분석 및 아키텍처 진단 메시지
