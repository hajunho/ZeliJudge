# 카프카 컨슈머 리밸런싱 스톰(Rebalance Storm)과 Eager vs Cooperative Sticky Assignor (KIP-429)

## 1. 개요 및 실무 장애 시나리오: "파드 하나 재시작했을 뿐인데 왜 100대 컨슈머가 올스톱돼요?!"

글로벌 핀테크/이커머스 기업 '젤리페이'의 데이터 플랫폼 엔지니어 태호는 대규모 결제 및 주문 스트림 토픽(`order-events`, 총 64개 파티션)을 소비하기 위해 **Apache Kafka 컨슈머 그룹(64개 Pod)**을 쿠버네티스 클러스터에서 운용하고 있습니다.

어느 날 오후, 컨슈머 파드 중 1개(`pod-42`)가 긴 가비지 컬렉션(GC STW 8초)으로 인해 카프카 브로커에 하트비트를 제시간에 보내지 못해 일시적으로 컨슈머 그룹에서 퇴출(LeaveGroup)되었습니다.

그러자 믿을 수 없는 대참사가 벌어졌습니다:
1. `pod-42` 하나가 빠졌을 뿐인데, 정상 작동 중이던 **나머지 63개 컨슈머 파드의 모든 이벤트 소비가 일제히 정지(Stop-The-World)**되었습니다!
2. 모든 컨슈머가 자신이 읽고 있던 파티션을 강제로 반납(`REVOKE`)하고, 카프카 브로커의 그룹 코디네이터(Coordinator)에게 `JoinGroup` 요청을 보내며 재협상을 시작했습니다.
3. 리밸런싱이 진행되는 수 초 동안 초당 수만 건의 결제 이벤트가 소비되지 못하고 파티션에 쌓여 **컨슈머 렉(Lag)이 수천만 건으로 폭증**했습니다.
4. 더 끔찍한 것은, 리밸런싱이 끝난 직후 쌓여있던 렉을 한꺼번에 가져오느라 또 다른 파드의 CPU/메모리가 치솟아 `max.poll.interval.ms`를 초과했고, **연쇄적으로 또 다른 리밸런싱이 발동(Rebalance Storm / Cascade Failure)**된 것입니다!
5. 64대의 컨슈머 파드는 무려 30분 동안 일도 하지 못한 채 리밸런싱 무한 루프에 갇혔고, 결국 결제 알림톡 발송이 30분 지연되는 대형 프로덕션 장애가 터졌습니다.

태호는 머리를 감싸 쥐었습니다:
> *"문제없는 63개 파드는 자기가 읽던 파티션을 계속 읽으면 되는데, 도대체 왜 파드 1개 빠졌다고 전체 컨슈머가 파티션을 다 뱉어내고 멈추는 거지?!"*

---

## 2. 참사의 원인: 전통적인 Eager Rebalance 프로토콜의 한계

카프카의 기본 할당 전략(RangeAssignor, RoundRobinAssignor, 구형 StickyAssignor)은 모두 **Eager Rebalance 프로토콜**을 사용합니다.

```
[Eager Rebalance의 Stop-The-World 참사]

t=0:  C1:[P0, P1]   C2:[P2, P3]   C3:[P4, P5] (정상 소비 중)
                         │
t=1:  C3 파드 일시 퇴출 발생! (GC STW 또는 배포)
                         │
t=2:  [EAGER ALL-REVOKE 발동!]
      C1: [P0, P1] 강제 반납! ──> 소비 올스톱 (STW)
      C2: [P2, P3] 강제 반납! ──> 소비 올스톱 (STW)
                         │
      ==> 리밸런싱 협상 중 (전체 클러스터 처리량 = 0, 렉 폭증!)
                         │
t=7:  [새로운 할당표 전파 (SyncGroup 완료)]
      C1: [P0, P1, P2]   C2: [P3, P4, P5]
      (C2는 원래 P2, P3을 읽다가 엉뚱하게 P4, P5를 받아서 인메모리 캐시 무효화!)
```

### (1) 전체 파티션 강제 반납 (Revoke All) & Stop-The-World
Eager 프로토콜의 설계 철학은 *"파티션 소유권이 중복되어 두 컨슈머가 같은 파티션을 동시에 소비하는 참사를 막기 위해, 일단 모든 컨슈머가 모든 파티션을 내려놓고 처음부터 다시 협상하자"*는 것입니다.
* 결과: 그룹 멤버십에 단 1개의 변경만 발생해도, **전체 컨슈머 그룹의 소비가 전면 중단(Stop-The-World)**됩니다.
* 리밸런스 시간(수 초 ~ 수십 초) 동안 파티션의 렉은 걷잡을 수 없이 치솟습니다.

### (2) 불필요한 파티션 대이동 (Partition Reshuffling)
기존 Eager Round-Robin 등은 파티션을 처음부터 다시 분배하므로, 아무 문제 없던 컨슈머가 들고 있던 파티션까지 다른 컨슈머로 무작위 이전됩니다.
* 이로 인해 컨슈머의 로컬 인메모리 캐시(RocksDB, 로컬 상태)가 무효화되고, 오프셋을 새로 읽어들이는 무거운 I/O가 발생합니다.

---

## 3. 구원자: KIP-429 증분 협업 리밸런싱 (Incremental Cooperative Rebalancing)

Apache Kafka 2.4부터 도입된 **KIP-429 (Cooperative Sticky Assignor)**는 이 끔찍한 Stop-The-World를 제거하기 위해 **"증분 협업(Incremental Cooperative)"** 방식을 도입했습니다.

```
[Cooperative Sticky Assignor의 무중단 리밸런싱]

t=0:  C1:[P0, P1]   C2:[P2, P3]   C3:[P4, P5] (정상 소비 중)
                         │
t=1:  C3 파드 퇴출 발생!
                         │
t=2:  [COOPERATIVE STICKY 발동!]
      C1: [P0, P1] "나는 내 파티션 계속 읽을게!" (STW = 0초, 무중단 소비!)
      C2: [P2, P3] "나도 내 파티션 계속 읽을게!" (STW = 0초, 무중단 소비!)
      미할당 파티션: [P4, P5] (C3의 유산만 대기)
                         │
t=7:  [증분 할당 (Incremental Assignment)]
      C1: [P0, P1, P4] (기존 P0, P1 유지 + P4 추가)
      C2: [P2, P3, P5] (기존 P2, P3 유지 + P5 추가)
      ==> 불필요한 파티션 이동 0건! 전체 클러스터 정지 0초!
```

### (1) 무중단 소비 (No Global Stop-The-World)
* 컨슈머가 그룹을 나가거나 새로 들어와도, **소유권이 변하지 않는 기존 파티션은 1초도 멈추지 않고 데이터를 계속 소비**합니다!
* 오직 위치가 변경되어야 하는 소수의 파티션만 핀포인트로 이전됩니다.
* 결과적으로 전체 컨슈머 그룹의 다운타임(STW)은 **0초**가 되며, 렉 폭증과 연쇄 리밸런싱 스톰이 원천 차단됩니다.

### (2) 스티키(Sticky) 할당: 최소 이동 원칙
* 기존 컨슈머가 이미 보유하고 있던 파티션은 최우선적으로 그대로 유지(Sticky)합니다.
* 컨슈머 간 파티션 개수 편차가 최대 1개가 되도록 보장하면서, **반드시 이동해야 하는 파티션만 최소한으로 이전**합니다.
* 로컬 캐시 히트율이 99% 이상 유지되며 오프셋 탐색 비용이 극소화됩니다.

---

## 4. 프로토콜 비교 매트릭스

| 비교 항목 | Eager Assignor (Range, RoundRobin) | Cooperative Sticky Assignor (KIP-429) |
|:---|:---:|:---:|
| **리밸런스 방식** | Eager (전체 일괄 반납) | **Incremental Cooperative (점진적 인계)** |
| **전체 컨슈머 STW 정지** | **발생 (수 초 ~ 수십 초 올스톱)** | **없음 (0초! 소유 파티션 계속 소비)** |
| **파티션 이동률** | 대규모 셔플링 (불필요한 이동 다수) | **최소 이동 (반드시 필요한 파티션만 이전)** |
| **컨슈머 렉(Lag) 영향** | 리밸런스 동안 전체 파티션 렉 폭증 | **이동 대상 파티션 외 렉 증가 없음** |
| **연쇄 리밸런스 위험** | 매우 높음 (Rebalance Storm) | **원천 방어** |
| **도입 버전** | Kafka 초기 ~ 2.3 | **Kafka 2.4+ (권장)** |

---

## 5. 실무 적용 및 프로덕션 설정 가이드

Spring Boot 및 Kafka Java 클라이언트에서 Cooperative Sticky Assignor를 활성화하는 것은 매우 간단합니다:

### (1) Java Consumer 설정
```java
Properties props = new Properties();
props.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, "kafka-broker:9092");
props.put(ConsumerConfig.GROUP_ID_CONFIG, "order-consumer-group");

// KIP-429 Cooperative Sticky Assignor 적용!
props.put(ConsumerConfig.PARTITION_ASSIGNMENT_STRATEGY_CONFIG, 
    org.apache.kafka.clients.consumer.CooperativeStickyAssignor.class.getName());
```

### (2) Spring Boot `application.yml`
```yaml
spring:
  kafka:
    consumer:
      group-id: order-consumer-group
      properties:
        partition.assignment.strategy: org.apache.kafka.clients.consumer.CooperativeStickyAssignor
```
* 무중단 롤링 배포, 파드 오토스케일링(HPA), 일시적 GC 튐 현상에서도 컨슈머 그룹이 결코 멈추지 않는 강력한 내구성을 얻을 수 있습니다.
