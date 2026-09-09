# #155 컨슈머 파드 하나 재시작했을 뿐인데 왜 100대 컨슈머가 일제히 멈추고 렉이 1억 개로 터져요?!: 카프카 컨슈머 리밸런싱 스톰(Rebalance Storm)과 Eager vs Cooperative Sticky Assignor (Kafka Consumer Rebalance Storm & Cooperative Sticky Assignor)

## 1. 실무 장애 시나리오: "파드 하나 재시작했을 뿐인데 왜 100대 컨슈머가 올스톱돼요?!"

글로벌 핀테크/이커머스 결제 플랫폼 '젤리페이'의 데이터 플랫폼 엔지니어 태호는 대규모 결제 및 주문 스트림 토픽(`order-events`, 총 64개 파티션)을 실시간으로 처리하기 위해 **Apache Kafka 컨슈머 그룹(64개 Pod)**을 쿠버네티스 클러스터에서 운용하고 있습니다.

어느 날 오후, 컨슈머 파드 중 1개(`pod-42`)가 긴 가비지 컬렉션(GC STW 8초)으로 인해 카프카 브로커에 하트비트를 제시간에 보내지 못해 일시적으로 컨슈머 그룹에서 퇴출(LeaveGroup)되었습니다.

그러자 믿을 수 없는 대참사가 벌어졌습니다:
1. `pod-42` 하나가 빠졌을 뿐인데, 정상 작동 중이던 **나머지 63개 컨슈머 파드의 모든 이벤트 소비가 일제히 정지(Stop-The-World)**되었습니다!
2. 모든 컨슈머가 자신이 읽고 있던 파티션을 강제로 반납(`REVOKE`)하고, 카프카 브로커의 그룹 코디네이터(Coordinator)에게 `JoinGroup` 요청을 보내며 재협상을 시작했습니다.
3. 리밸런싱이 진행되는 수 초 동안 초당 수만 건의 결제 이벤트가 소비되지 못하고 파티션에 쌓여 **컨슈머 렉(Lag)이 수천만 건으로 폭증**했습니다.
4. 더 끔찍한 것은, 리밸런싱이 끝난 직후 쌓여있던 렉을 한꺼번에 가져오느라 또 다른 파드의 CPU/메모리가 치솟아 `max.poll.interval.ms`를 초과했고, **연쇄적으로 또 다른 리밸런싱이 발동(Rebalance Storm / Cascade Failure)**된 것입니다!
5. 64대의 컨슈머 파드는 무려 30분 동안 일도 하지 못한 채 리밸런싱 무한 루프에 갇혔고, 결국 결제 알림톡 발송이 30분 지연되는 대형 프로덕션 장애가 터졌습니다.

태호는 머리를 감싸 쥐었습니다:
> *"문제없는 63개 파드는 자기가 읽던 파티션을 계속 읽으면 되는데, 도대체 왜 파드 1개 빠졌다고 전체 컨슈머가 파티션을 다 뱉어내고 멈추는 거지?!"*

긴급 소집된 분산 스트리밍 아키텍트 민우 님이 카프카 리밸런스 프로토콜을 화이트보드에 그리며 원인을 설명해주었습니다:

> "태호 님! 카프카의 기본 파티션 할당기(RangeAssignor, RoundRobinAssignor)는 구형 **Eager Rebalance 프로토콜**을 기반으로 동작합니다!  
> Eager 프로토콜은 '파티션 중복 소비를 원천 차단한다'는 명목으로, 그룹 멤버십이 1개라도 바뀌면 **모든 컨슈머가 자신이 쥐고 있던 모든 파티션을 강제로 내려놓고(Revoke All) 전체가 일제히 멈추는 Stop-The-World**를 강제합니다!  
> 심지어 리밸런스가 끝나면 파티션을 처음부터 새로 분배(Shuffle)하므로, 아무 잘못 없는 파드까지 파티션이 바뀌어 로컬 인메모리 캐시가 날아가고 오프셋을 새로 읽느라 과부하가 걸립니다!  
> 이 끔찍한 리밸런싱 스톰을 근본적으로 해결하려면, Kafka 2.4부터 도입된 **KIP-429 Cooperative Sticky Assignor (증분 협업 리밸런싱)**을 적용해야 합니다!  
> Cooperative Sticky는 소유권이 바뀌지 않는 파티션은 **1초도 멈추지 않고 계속 소비(STW = 0초)**하며, 오직 이전이 필요한 파티션만 핀포인트로 옮겨서 무중단 처리를 완벽하게 보장합니다!"

태호는 민우 님의 조언에 따라 카프카 컨슈머 리밸런싱 시뮬레이터를 구축하여, Eager와 Cooperative Sticky 프로토콜 간의 STW 정지 시간, 파티션 마이그레이션 횟수, 그리고 피크 렉(Peak Lag) 억제 성능을 정밀 검증하기로 했습니다.

---

## 2. 핵심 이론: Eager vs Cooperative Sticky Assignor (KIP-429)

```
[Eager Rebalance의 Stop-The-World 참사]
t=10:  C4 퇴출 발생!
       ==> C1, C2, C3의 ALL 파티션 강제 반납 (Revoke All)!
       ==> 전체 파티션 5초간 전면 정지 (Stop-The-World, 렉 폭증!)
t=15:  Round-Robin으로 처음부터 다시 할당 (불필요한 파티션 대규모 셔플링)

[Cooperative Sticky Assignor의 무중단 리밸런싱]
t=10:  C4 퇴출 발생!
       ==> C1, C2, C3은 자신의 기존 파티션을 계속 정상 소비! (STW = 0초!)
       ==> C4가 버린 고아 파티션만 대기
t=15:  고아 파티션만 C1, C2, C3에게 1개씩 증분 할당 (기존 소유권 100% 보존!)
```

### (1) Eager Assignor (Round-Robin)
* 이벤트 발생 시 그룹 전체 컨슈머의 모든 파티션 소비를 일제히 중단(`total_stw_pause_sec += rebalance_duration_sec`).
* 리밸런스 종료 시 파티션 번호 $i$를 활성 컨슈머 정렬 목록의 $i \pmod k$ 번째 컨슈머에게 일괄 재할당.
* 기존 소유자와 무관하게 파티션이 대규모로 셔플링되어 불필요한 마이그레이션이 다수 발생.

### (2) Cooperative Sticky Assignor (KIP-429)
* 이벤트 발생 시에도 기존 소유자가 활성 상태를 유지하고 목표 할당량 이내인 파티션은 **절대 중단 없이 소비 계속 (Global STW = 0초)**.
* 목표 할당량: 최소 $\lfloor N_p / k \rfloor$, 최대 $\lceil N_p / k \rceil$.
* 기존 할당을 최우선적으로 보존(Sticky)하며, 고아 파티션 또는 초과분만 보유 파티션 수가 적은 컨슈머에게 증분 이전하여 마이그레이션 횟수를 최소화.

---

## 3. 문제 요구사항

입력으로 주어지는 프로토콜(`rebalance_protocol`), 파티션 수(`num_partitions`), 초기 컨슈머(`initial_consumers`), 시뮬레이션 기간, 트래픽 유입률(`incoming_rate_per_partition`), 소진율(`drain_rate_per_partition`), 리밸런스 소요 시간(`rebalance_duration_sec`), 이벤트 목록(`events`)을 바탕으로 초 단위($t = 0 \dots T-1$) 시뮬레이션을 수행하고, 최종 메트릭 및 최종 할당표를 JSON 형식으로 출력하는 프로그램을 작성하세요.

### 상세 규칙
1. **초기 상태 ($t=0$)**:
   * 활성 컨슈머 목록 정렬 후 파티션 $0 \dots N_p - 1$을 Round-Robin으로 초기 분배.
   * 각 파티션의 초기 렉은 0.0.
2. **이벤트 처리 ($t$ 시점)**:
   * `CONSUMER_LEAVE`: 활성 컨슈머 목록에서 해당 컨슈머 제거.
   * `CONSUMER_JOIN`: 활성 컨슈머 목록에 새 컨슈머 추가.
   * **Eager**:
     - 즉시 모든 파티션의 처리를 중단(STW = False for all partitions).
     - `total_stw_pause_sec += rebalance_duration_sec`.
     - $t + \text{rebalance\_duration}$ 시점에 Round-Robin으로 재할당.
   * **Cooperative Sticky**:
     - 목표 할당표를 계산하고, 기존 소유자가 활성 상태이면서 새 할당표에서도 해당 파티션을 유지하는 파티션은 **중단 없이 계속 처리(can_drain = True)**.
     - 오직 주인이 바뀌는 파티션만 리밸런스 동안 대기 후 $t + \text{rebalance\_duration}$ 시점에 인계.
3. **트래픽 및 렉 계산 ($t \to t+1$ 구간)**:
   * 각 파티션에 `incoming_rate_per_partition`만큼 렉 누적.
   * 해당 파티션이 처리 가능한 상태(`can_drain == True`)라면 $\min(\text{lag}, \text{drain\_rate})$만큼 소비하여 렉 차감 및 `total_processed_records` 누적.
   * 매 초 전체 파티션 렉 합의 최댓값을 `peak_lag`로 기록.
4. **리밸런스 완료 ($t+1 == \text{end\_time}$)**:
   * 새 할당표 적용 및 이전 할당표 대비 소유자가 변경된 파티션 수를 `total_migrations`에 누적.

---

## 4. 입력 및 출력 형식

### 입력 형식 (Standard Input - JSON)
```json
{
  "rebalance_protocol": "COOPERATIVE_STICKY",
  "num_partitions": 12,
  "initial_consumers": ["C1", "C2", "C3", "C4"],
  "simulation_duration_sec": 40,
  "incoming_rate_per_partition": 100.0,
  "drain_rate_per_partition": 150.0,
  "rebalance_duration_sec": 5,
  "events": [
    {
      "time_sec": 10,
      "type": "CONSUMER_LEAVE",
      "consumer_id": "C4"
    }
  ]
}
```

### 출력 형식 (Standard Output - JSON)
```json
{
  "protocol": "COOPERATIVE_STICKY",
  "metrics": {
    "total_rebalances": 1,
    "total_stw_pause_sec": 0.0,
    "total_migrations": 3,
    "peak_lag": 1500.0,
    "final_lag": 0.0,
    "total_processed_records": 48000.0
  },
  "final_assignment": {
    "0": "C1",
    "1": "C2",
    "2": "C3",
    "3": "C1",
    "4": "C1",
    "5": "C2",
    "6": "C3",
    "7": "C2",
    "8": "C1",
    "9": "C2",
    "10": "C3",
    "11": "C3"
  },
  "diagnosis": "OPTIMAL: Cooperative Sticky assignor eliminated global STW pause (0.0s). Preserved locality with only 3 necessary migrations, keeping peak lag at 1,500."
}
```
