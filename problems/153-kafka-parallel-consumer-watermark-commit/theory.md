# [CS Deep Dive] 카프카 인-프로세스 병렬 소비와 오프셋 워터마크 안전 커밋 (Parallel Consumer Architecture)

## 1. Apache Kafka의 파티션 확장성 한계 (The Partition Concurrency Ceiling)

Apache Kafka는 대규모 분산 로그(Distributed Commit Log) 모델을 채택하고 있으며, 파티션(Partition)은 확장성과 동시성의 기본 단위입니다.

### 카프카 기본 컨슈머의 제약
* **파티션 대 컨슈머 스레드 1:1 매핑**:
  동일한 컨슈머 그룹(Consumer Group) 내에서 하나의 파티션은 오직 하나의 컨슈머 스레드에 의해서만 소비될 수 있습니다.
  $$\text{Maximum Concurrent Consumers} = \text{Number of Partitions}$$
* **I/O 바운드 작업의 치명적 병목**:
  이벤트 처리가 순수 CPU 연산이 아니라 외부 결제 API, 데이터베이스 쿼리, 이메일/푸시 발송 등 네트워크 I/O를 포함하는 경우 (소요 시간 100ms~300ms), 1개 스레드의 최대 처리량은 다음과 같이 극도로 제한됩니다:
  $$\text{Throughput}_{single} = \frac{1}{0.2\text{s}} = 5 \text{ records/sec}$$
  만약 파티션이 8개라면 서버의 CPU 코어가 64개라도 전체 클러스터 처리량은 40 req/sec에 묶이게 되며, 트래픽 급증 시 Consumer Lag이 수십만 건으로 폭증합니다.

---

## 2. 왜 파티션을 무한정 늘리면 안 되는가? (Why More Partitions Is Not the Answer)

파티션을 1,000개, 10,000개로 무작정 늘리는 것은 카프카 브로커에 치명적인 부작용을 초래합니다:

1. **파일 디스크립터(File Descriptor) 및 OS 리소스 고갈**:
   각 파티션은 로그 세그먼트(`.log`), 인덱스(`.index`), 타임인덱스(`.timeindex`) 등 최소 3개 이상의 열린 파일 핸들을 소비합니다. 파티션이 많아질수록 OS 파일 테이블과 메모리 매핑(`mmap`) 오버헤드가 급증합니다.
2. **리밸런싱 폭풍(Rebalance Storm) 및 가용성 저하**:
   컨슈머 파드가 재시작되거나 오토스케일링될 때 수천 개의 파티션을 재할당(Reassignment)하는 데 수십 초에서 수분의 다운타임이 발생합니다.
3. **종단 간 복제 지연(End-to-End Latency) 증가**:
   브로커 리더-팔로워 간 복제 패킷이 파티션 단위로 쪼개져 네트워크 오버헤드가 증가합니다.
4. **키 도메인 분산의 부작용**:
   카프카 파티셔너(`murmur2(key) % num_partitions`)에 의해 파티션 수가 변경되면 기존 키들의 해시 라우팅 대상 파티션이 달라져 이전 메시지와의 순서가 뒤틀립니다.

---

## 3. Confluent Parallel Consumer 아키텍처

Confluent는 2021년 단일 파티션 내에서 수십~수백 개의 스레드로 병렬 처리를 수행하면서도 순서와 안전성을 100% 보장하는 **Parallel Consumer** 오픈소스를 발표했습니다.

```
                  Kafka Partition 0
               [0] [1] [2] [3] [4] [5] ...
                         │
                         ▼
        ┌──────────────────────────────────┐
        │     Parallel Consumer Engine     │
        │  1. In-Flight Buffer Queue       │
        │  2. Key-Ordered Sharding Router  │
        │  3. Low Watermark Tracker        │
        └────────────────┬─────────────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   [Thread 1]       [Thread 2]       [Thread 3]
   Key: USER_A      Key: USER_B      Key: USER_C
```

### 3대 핵심 서브시스템

#### 1. Key-Ordered Concurrency (키 기반 동시성 제어)
* **공리**: "비즈니스 엔터티가 동일한 이벤트(동일 `key`)는 순서가 보장되어야 하지만, 서로 다른 엔터티(서로 다른 `key`)는 처리 순서가 뒤바뀌어도 아무런 상관이 없다."
* 예: 고객 A의 '주문' $\to$ '취소'는 순차 실행되어야 하지만, 고객 A의 주문과 고객 B의 주문은 서로 다른 스레드에서 병렬로 실행되어도 무방합니다.
* **구현 기법**:
  - `ActiveKeys` 집합을 유지.
  - 레코드를 디스패치할 때 해당 레코드의 `key`가 이미 실행 중이면, 해당 키의 작업이 끝날 때까지 큐에 대기(Lock per Key).

#### 2. Low Watermark Offset Commit (안전 오프셋 워터마크)
카프카 브로커의 오프셋 커밋 API(`OffsetCommitRequest`)는 특정 단일 오프셋 번호만을 기록하며, 그 의미는 다음과 같습니다:
> "커밋된 오프셋 $K$ 이전의 모든 레코드($0, 1, \dots, K-1$)는 완벽히 처리 완료되었다."

* **순서 역전 완료(Out-of-Order Completion)의 딜레마**:
  - 오프셋 0 (200ms 소요)
  - 오프셋 1 (20ms 소요)
  - 오프셋 1이 먼저 끝났다고 해서 $2$를 커밋해버리면, 오프셋 0이 실행 중인 상태에서 파드가 재부팅되었을 때 **오프셋 0은 영원히 건너뛰어지는 데이터 유실(Silent Lost Record)** 이 발생합니다.
* **Low Watermark 공식**:
  $$O_{watermark} = \min \{ o \mid o \notin \text{CompletedOffsets} \}$$
  즉, $0$부터 시작하여 **단 하나의 빈틈(Hole)도 없이 연속적으로 완료된 가장 높은 오프셋의 다음 번호**만을 브로커에 안전 커밋 오프셋으로 전송합니다.
* **워터마크 점프 (Watermark Jump)**:
  선행하는 무거운 작업(예: 오프셋 0)이 마침내 완료되는 순간, 이미 사전에 완료되었던 후행 작업들($1, 2, 4$ 등)이 한 번에 포섭되면서 워터마크가 계단식으로 급격히 점프합니다.

#### 3. Max In-Flight & Backpressure (메모리 보호)
* 워커 스레드가 처리하는 속도보다 브로커에서 `poll()`해오는 속도가 훨씬 빠르면 컨슈머 메모리에 수십만 건의 미완료 레코드가 쌓여 OOM(Out of Memory)이 발생합니다.
* `MAX_IN_FLIGHT` 상한선을 설정하여, 현재 시스템 내에서 처리 중이거나 대기 중인 레코드 수가 임계치에 도달하면 `poll()`을 일시 중단(Pause)하는 백프레셔를 가동합니다.

---

## 4. 실무 아키텍처 체크리스트 & Best Practices

1. **멱등성(Idempotency)과 At-Least-Once 보장**:
   - 워터마크 커밋은 최악의 크래시 상황에서도 데이터 유실(Data Loss)은 0건으로 보장하지만, 비연속적으로 완료되었던 후행 오프셋들이 재시작 후 다시 전달될 수 있습니다(At-Least-Once Delivery).
   - 따라서 다운스트림 처리 로직은 반드시 DB Unique Key나 Redis 원자적 멱등성 토큰을 기반으로 **멱등적(Idempotent)** 으로 설계되어야 합니다.
2. **포이즌 필(Poison Pill) 및 데드 레터 큐(DLQ) 연동**:
   - 특정 오프셋 하나가 영구히 에러를 뿜으며 끝나지 않으면(무한 재시도), 워터마크가 해당 오프셋에 영구히 묶여 전체 파티션의 오프셋 커밋이 중단됩니다.
   - 최대 재시도 횟수(Max Retries)를 초과한 레코드는 즉시 Dead Letter Topic(DLQ)으로 라우팅하고 해당 오프셋을 완료 처리하여 워터마크가 전진할 수 있도록 퇴로를 열어주어야 합니다.
3. **Confluent Parallel Consumer 도입 고려**:
   - 직접 멀티스레드 컨슈머를 구현하기보다 `io.confluent.parallelconsumer:parallel-consumer-core` 프로덕션 검증 라이브러리를 적용하여 안정성을 확보하십시오.
