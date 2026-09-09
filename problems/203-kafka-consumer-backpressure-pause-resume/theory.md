# 카프카 컨슈머 흐름 제어와 리액티브 백프레셔(Pause/Resume) 심층 분석

## 1. 개요: 카프카 컨슈머 생존 주기와 2대 타임아웃 메커니즘

Apache Kafka 클라이언트 아키텍처에서 컨슈머(Consumer)는 토픽의 파티션(Partition)을 할당받아 데이터를 지속적으로 가져오는 역할을 합니다.  
카프카 브로커의 **그룹 코디네이터(Group Coordinator)**는 컨슈머가 정상 동작 중인지 확인하기 위해 두 가지 독립된 생존 확인(Liveness) 메커니즘을 운영합니다:

```
+-------------------------------------------------------------------------+
|                        Kafka Consumer Process                           |
|                                                                         |
|  [Background Heartbeat Thread] -------- Heartbeat RPC -------> [Broker] |
|  - session.timeout.ms (예: 45초)                                        |
|  - heartbeat.interval.ms (예: 3초)                                      |
|                                                                         |
|  [Foreground Main Event Loop] --------- Fetch/Poll RPC ------> [Broker] |
|  - max.poll.interval.ms (예: 300초 / 5분)                               |
|  - max.poll.records (예: 500개)                                         |
+-------------------------------------------------------------------------+
```

### 1.1 KIP-62 이전과 이후: 하트비트 스레드의 분리
- **초기 카프카(KIP-62 이전)**: 하트비트 전송과 메시지 처리가 단일 스레드에서 함께 수행되었습니다. 메시지 처리가 10초만 지연되어도 하트비트가 끊겨 컨슈머가 퇴출당하는 문제가 심각했습니다.
- **KIP-62 개선**: 백그라운드 하트비트 스레드를 분리하여, 네트워크 단절이나 프로세스 완전 크래시(`SIGKILL`)는 `session.timeout.ms`로 빠르게 감지합니다.
- **`max.poll.interval.ms`의 도입 목적**:
  - 하트비트 스레드가 살아있더라도, 애플리케이션 메인 스레드가 무한 루프, DB 교착상태(Deadlock), 또는 극심한 병목에 빠져 메시지를 전혀 처리하지 못하는 **라이브락(Livelock)** 상태를 방지하기 위해 도입되었습니다.
  - 두 번의 `poll()` 호출 사이의 시간이 이 임계치를 초과하면, 코디네이터는 해당 컨슈머가 "작업 불능" 상태라고 판단하고 그룹에서 강제 제명합니다.

---

## 2. 다운스트림 병목 시의 2대 대참사

다운스트림 서비스(RDBMS, 외부 결제 PG사, 외부 API)의 일시적 장애나 락 경합으로 레코드당 처리 시간이 5ms에서 100ms~200ms로 급증할 때, 나이브한 컨슈머 아키텍처는 시스템을 붕괴시킵니다.

### 2.1 참사 1: 동기식 블로킹 컨슈머의 연쇄 리밸런스 폭풍 (Rebalance Storm)
나이브한 단일 루프 컨슈머:
```java
while (running) {
    ConsumerRecords<String, String> records = consumer.poll(Duration.ofMillis(100));
    for (ConsumerRecord<String, String> record : records) {
        processRecordSynchronously(record); // DB 지연 발생 시 60초 소요!
    }
    consumer.commitSync();
}
```
1. 500개 레코드를 가져왔는데 레코드당 DB 지연이 1초로 튀면 루프 순회에 500초가 소요됩니다.
2. `max.poll.interval.ms`(기본 300초)가 만료되어 코디네이터가 컨슈머를 강제 제명(`CommitFailedException` 발생).
3. **캐스케이딩 전이**: 제명된 파티션이 인접한 컨슈머 Pod 2에게 재할당됩니다. Pod 2 역시 동일한 대량 백로그와 느린 DB를 만나 5분 뒤 강제 퇴출됩니다.
4. 결국 컨슈머 그룹 내 모든 Pod가 도미노처럼 쓰러지며 메시지 처리가 완전히 정지하는 **리밸런스 지옥(Rebalance Storm)**에 빠집니다.

### 2.2 참사 2: 무제한 인메모리 큐 분리와 OOM 폭사 (Unbounded Buffer OOM)
리밸런스를 피하겠다고 `poll()` 스레드와 워커 스레드를 분리하고 사이에 큐를 두는 방식:
```
[Poll Thread] ---> LinkedBlockingQueue (Unbounded!) ---> [Worker Thread Pool]
```
- 다운스트림이 느려져 워커 풀은 초당 50건만 처리하는데, `poll()` 스레드는 초당 수만 건을 계속해서 인출하여 큐에 적재합니다.
- 수백만 건의 레코드가 힙 메모리에 쌓이며 JVM Full GC 스톨이 발생하고, 결국 운영체제 OOM-Killer에 의해 프로세스가 강제 사살(`SIGKILL`)됩니다.

---

## 3. 구원 아키텍처: `consumer.pause()` & `consumer.resume()` 리액티브 백프레셔

카프카 컨슈머 API에는 이 문제를 해결하기 위해 파티션 레벨의 정밀 흐름 제어 기능인 `pause()`와 `resume()`이 내장되어 있습니다.

```
+-------------------------------------------------------------------------+
|                  Reactive Pause/Resume Architecture                     |
|                                                                         |
|  [Kafka Broker]                                                         |
|       |                                                                 |
|       | poll() (Fetch Records)                                          |
|       v                                                                 |
|  [Consumer Thread]                                                      |
|       |                                                                 |
|       | Push Records                                                    |
|       v                                                                 |
|  [Bounded Buffer] <--- High Watermark (80%) 도달 시: consumer.pause()    |
|  [ (Cap: 200)   ]                                                       |
|  [              ] <--- Low Watermark  (20%) 복구 시: consumer.resume()   |
|       |                                                                 |
|       | Drain Records                                                   |
|       v                                                                 |
|  [Worker Pool] ----> [Slow Downstream DB]                               |
|                                                                         |
|  ★ 핵심: Paused 상태에서도 Consumer는 poll(0)을 계속 호출하여          |
|    max.poll.interval.ms를 무한히 리셋하고 하트비트를 유지함!           |
+-------------------------------------------------------------------------+
```

### 3.1 `consumer.pause()`의 내부 작동 원리
- `consumer.pause(consumer.assignment())`를 호출하면, 카프카 클라이언트 내부의 `SubscriptionState`에서 해당 파티션들의 상태가 `PAUSED`로 플래그 처리됩니다.
- 컨슈머 내부의 `Fetcher`는 다음 브로커 네트워크 요청(`sendFetches()`)을 구성할 때 일시정지된 파티션을 요청 대상 목록에서 완전히 제외합니다.
- 따라서 브로커로부터 데이터가 네트워크를 통해 전송되지 않으며, 네트워크 대역폭과 메모리가 0으로 유지됩니다.

### 3.2 핵심 불변식: 일시정지 중에도 `poll(0)` 지속 호출
- **가장 중요한 점**: 파티션을 pause했다고 해서 `poll()` 루프를 멈추거나 `sleep()`해서는 안 됩니다!
- 컨슈머 메인 스레드는 여전히 주기적으로(예: 100ms마다) `consumer.poll(Duration.ZERO)`를 호출해야 합니다.
- **효과**:
  1. 일시정지 상태이므로 가져오는 레코드 수는 **0개**입니다.
  2. 그러나 `poll()` 내부 로직이 실행되면서 **`max.poll.interval.ms` 타이머가 0으로 리셋**됩니다.
  3. 코디네이터와의 TCP 연결 킵얼라이브 및 하트비트가 정상 유지되므로 **리밸런스가 절대로 발동하지 않습니다**.

### 3.3 히스테리시스 워터마크 (High/Low Watermarks)
- 큐 크기 상한 단 하나만 두고 일시정지/재개를 반복하면 파티션이 1개 들어올 때마다 pause-resume이 초당 수백 번씩 요동치는 쓰래싱(Thrashing)이 발생합니다.
- 이를 방지하기 위해 슈미트 트리거(Schmitt Trigger)와 동일한 **히스테리시스 워터마크**를 적용합니다:
  - **High Watermark (예: 75~80%)**: 큐 적재량이 임계치를 넘으면 `pause()` 발동.
  - **Low Watermark (예: 20~25%)**: 워커 풀이 버퍼를 충분히 비워 하한선 이하로 내려갔을 때만 `resume()` 발동.

---

## 4. 3대 컨슈머 아키텍처 패턴 종합 비교

| 비교 항목 | 나이브 동기식 블로킹 | 무제한 큐 비동기 버퍼링 | **Pause/Resume 리액티브 백프레셔** |
|---|---|---|---|
| **구현 난이도** | 매우 단순 | 보통 | 정교한 상태 제어 필요 |
| **다운스트림 지연 시** | **max.poll.interval.ms 초과** | **메모리 폭발 (OOM Crash)** | **큐 상한선에서 안전 일시정지** |
| **리밸런스 폭풍 위험** | **매우 높음 (연쇄 퇴출)** | 없음 | **0건 (완전 회피)** |
| **메모리 안정성** | 안정 (단일 배치 크기) | **파멸적 (무제한 팽창)** | **완벽 보장 (유계 큐 통제)** |
| **하트비트 생존성** | 스톨 시 단절 | 유지 | **poll(0) 호출로 100% 생존** |
| **프로덕션 적용처** | 초소형 토이 프로젝트 | 절대 금기 안티패턴 | **넷플릭스, 우버, 쿠팡 엔터프라이즈 표준** |

---

## 5. 실무 Spring Kafka 및 프레임워크 설정 가이드

Spring Kafka를 비롯한 현대 프레임워크에서는 다음과 같은 설정과 리스너 구조를 통해 Pause/Resume 백프레셔를 손쉽게 통합할 수 있습니다:

```yaml
# application.yml
spring:
  kafka:
    consumer:
      max-poll-records: 50
      properties:
        max.poll.interval.ms: 300000 # 5분
        session.timeout.ms: 45000     # 45초
        heartbeat.interval.ms: 3000   # 3초
    listener:
      type: batch
      ack-mode: manual_immediate
```
- Spring Kafka의 `AbstractMessageListenerContainer`는 내부적으로 컨테이너 레벨의 `pause()` / `resume()` 메서드를 제공하여 다운스트림 큐가 가득 찼을 때 파티션 소비를 자동으로 멈추고 안전하게 복구합니다.
