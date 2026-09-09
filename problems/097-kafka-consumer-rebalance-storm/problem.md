# 097. 배치 작업 5분 돌렸을 뿐인데 왜 전사 메시지 처리가 멈추고 파티션이 핑퐁을 쳐요?!: Apache Kafka 컨슈머 리밸런스 폭풍(Consumer Rebalance Storm)과 `max.poll.interval.ms`의 배신

---

## 1. 비극의 시작 (Real-World Disaster)

스타트업 백엔드 엔지니어 진우는 월말 결제 정산 시스템을 위해 **Apache Kafka** 기반의 비동기 메시지 파이프라인을 구축했습니다.  
주문 토픽(`orders`)에 쌓인 대용량 정산 요청을 처리하기 위해 Spring Boot 컨슈머 인스턴스 3대(`c1, c2, c3`)를 띄웠습니다:

```java
@KafkaListener(topics = "orders", groupId = "settlement-group")
public void listen(List<ConsumerRecord<String, String>> records, Acknowledgment ack) {
    for (ConsumerRecord<String, String> record : records) {
        // 건당 수초~수십 초 걸리는 무거운 외부 PG사 대사 및 정산 API 호출
        settlementService.processHeavySettlement(record.value());
    }
    ack.acknowledge(); // 모든 배치 처리가 끝난 뒤 수동 오프셋 커밋!
}
```

월말 정산 당일, 1건당 외부 API 응답이 1초씩 걸리는 정산 메시지 500건(`max.poll.records=500`)이 한꺼번에 들어왔습니다.  
`c1` 컨슈머는 성실하게 루프를 돌며 정산 작업을 수행했고, 총 **5분 10초(310초)**가 걸렸습니다.

작업을 무사히 마치고 `ack.acknowledge()`가 호출되는 순간, 서버 콘솔에 시뻘건 에러 폭탄이 터졌습니다:

```text
org.apache.kafka.clients.consumer.CommitFailedException: Commit cannot be completed since the group has already rebalanced and assigned the partitions to another member. This means that the time between subsequent calls to poll() was longer than the configured max.poll.interval.ms, which typically implies that the poll loop is spending too much time processing messages. You can address this either by increasing max.poll.interval.ms or by decreasing the maximum size of batches returned in poll() with max.poll.records.
```

**"분명히 JVM 프로세스도 살아있고 서버 CPU도 여유로운데 왜 커밋이 거부당하지?!"**  
비극은 여기서 끝나지 않았습니다:
1. 카프카 브로커는 `c1`이 5분 동안 다음 `poll()`을 부르지 않자 죽은 것으로 판단하고 강제 퇴출(`EVICTION`)시켰습니다.
2. 남아있던 `c2, c3`에게 파티션을 재분배하기 위해 **전체 컨슈머가 메시지 소비를 멈추는 전면 정지(Stop-The-World Rebalance)**가 발생했습니다!
3. `c1`이 처리했던 그 무거운 메시지는 커밋되지 못했기 때문에, 파티션을 넘겨받은 `c2`가 **똑같은 메시지를 가져와 또 5분 동안 처리**하다가 또 퇴출당했습니다!
4. 퇴출당했던 `c1`은 다시 살아나서 그룹에 재가입(`JoinGroup`)하려 들고, 그러자 **또다시 2차 리밸런스**가 터졌습니다!
5. 파티션이 컨슈머들 사이에서 무한 핑퐁을 치며 정산 처리는 완전히 멈췄고, DB에는 동일한 정산 내역이 **2번, 3번씩 중복 결제되는 초대형 금융 사고**가 발생했습니다!

---

## 2. 도서관 사서와 5분 반납 타이머 비유

이 참사를 대학교 중앙도서관에 비유해 봅시다:
- 서가(카프카 파티션)에 책 꾸러미(메시지)가 꽂혀 있고, 학생 3명(`c1, c2, c3`)이 팀을 이뤄 책을 나눠 읽습니다.
- 사서 선생님(카프카 그룹 코디네이터, Group Coordinator)의 엄격한 규칙:
  > **"책 꾸러미를 빌려 가면(`poll()`), 반드시 5분(`max.poll.interval.ms=300초`) 안에 데스크에 와서 '다 읽었습니다!' 하고 확인 도장(`commit`)을 찍어야 합니다. 5분이 지나도록 안 오면 학생이 실종된 것으로 간주하고 도서관 문을 닫고(`Rebalance`) 책을 다른 학생에게 뺏어서 넘깁니다!"**
- 학생 `c1`이 빌려간 책 속에 10,000쪽짜리 두꺼운 전공책(무거운 정산 데이터)이 들어 있어 다 읽는 데 **5분 10초**가 걸렸습니다.
- 5분이 지난 순간, 사서는 `c1`을 실종 처리하고 즉시 도서관 문을 닫아걸었습니다(Eager Rebalance 전면 중단).
- 5분 10초에 `c1`이 땀을 뻘뻘 흘리며 독후감을 들고 오자, 사서는 **"너 이미 제명됐어!"**라며 독후감을 찢어버립니다(`CommitFailedException`).
- 사서는 그 두꺼운 책을 `c2`에게 넘겼고, `c2`도 5분 안에 다 못 읽어 또 쫓겨납니다.
- 쫓겨난 `c1`은 "저 살아있어요!"라며 재입실 신청을 하고 도서관은 또 폐쇄됩니다.
- 학생들은 공부는커녕 **하루 종일 '문 닫고 책 뺏기 핑퐁'만 치는 리밸런스 폭풍(Rebalance Storm)**에 갇히게 된 것입니다!

---

## 3. 핵심 아키텍처 및 요구사항

당신은 Apache Kafka의 Group Coordinator, 토픽 파티션 큐, 컨슈머 그룹 라이프사이클(`JOIN`, `LEAVE`), `POLL` 지연 감지 및 강제 퇴출(`TIMEOUT_EVICTED`), `CommitFailedException` 방어, 그리고 파티션 재할당(Rebalance) 엔진을 시뮬레이션해야 합니다.

### 1) 토픽 설정 (`CONFIG_TOPIC`)
- `CONFIG_TOPIC <topic> <num_partitions>`
  - `<topic>` 이름과 `<num_partitions>`(0부터 N-1까지)개의 파티션을 생성합니다.
  - 모든 파티션의 초기 커밋 오프셋(`committed_offset`)은 0입니다.
  - 출력: `CONFIG_TOPIC_OK topic=<topic> partitions=<num_partitions>`

### 2) 컨슈머 그룹 가입 (`JOIN_GROUP`)
- `JOIN_GROUP <consumer_id> <max_poll_interval_ms> <max_poll_records>`
  - 컨슈머를 그룹에 등록하고 활성(`ACTIVE`) 상태로 만듭니다.
  - 이미 활성 상태인 멤버가 다시 조인하면: `ERROR:ALREADY_MEMBER consumer=<consumer_id>`
  - 신규 가입 또는 퇴출/이탈했던 멤버의 재가입 시:
    - 그룹의 세대 번호(`generation_id`)가 1 증가하고, 리밸런스 카운트(`rebalance_count`)가 1 증가합니다.
    - 정렬된 모든 활성 멤버들에게 0번부터 N-1번 파티션을 라운드 로빈 방식으로 분배합니다:
      - `partition p` -> `active_members[p % len(active_members)]`
    - 모든 활성 멤버의 `generation_id`는 최신 세대로 갱신됩니다.
    - 출력:
      ```text
      REBALANCE_TRIGGERED generation=<gen> reason=CONSUMER_JOIN member=<consumer_id>
      JOIN_OK consumer=<consumer_id> generation=<gen> partitions=[<assigned_partitions>]
      ```

### 3) 메시지 발행 (`PRODUCE`)
- `PRODUCE <topic> <partition_id> <msg_id> <processing_time_ms>`
  - 토픽의 지정된 파티션에 메시지를 인큐합니다.
  - 출력: `PRODUCE_OK topic=<topic> partition=<partition_id> msg=<msg_id> offset=<offset>`

### 4) 메시지 수신 및 처리 (`POLL`)
- `POLL <consumer_id>`
  - 컨슈머가 자신에게 할당된 파티션들(오름차순)에서 미처리된 메시지(`offset >= committed_offset`)를 최대 `max_poll_records` 건까지 가져와 순차 처리합니다.
  - 가져온 레코드들의 총 처리 시간: `total_duration = sum(msg.processing_time_ms)`.
  - **타임아웃 감지 (`total_duration > max_poll_interval_ms`)**:
    - 비즈니스 로직 처리 시간이 한도를 초과했습니다!
    - 해당 컨슈머는 즉시 **강제 퇴출(`EVICTED`)**되며 할당된 파티션을 모두 상실합니다.
    - **레코드 커밋 실패**: 오프셋은 전혀 전진하지 않고 그대로 유지됩니다.
    - 그룹 코디네이터는 즉시 세대를 올리고 남은 활성 멤버들에게 파티션을 재분배(리밸런스)합니다.
    - 출력:
      ```text
      TIMEOUT_EVICTED consumer=<consumer_id> duration=<total_duration>ms limit=<limit>ms
      REBALANCE_TRIGGERED generation=<gen> reason=CONSUMER_TIMEOUT evicted=<consumer_id>
      ```
  - **정상 처리 (`total_duration <= max_poll_interval_ms`)**:
    - 가져온 레코드 수만큼 파티션별 커밋 오프셋이 전진합니다.
    - 레코드가 0건이면 `duration=0ms`, `committed_offsets={}`.
    - 출력: `POLL_OK consumer=<consumer_id> processed_records=<count> duration=<total_duration>ms committed_offsets={<p_id>:<offset>, ...}`
  - 미등록 또는 비활성 멤버인 경우: `ERROR:NOT_MEMBER consumer=<consumer_id>`

### 5) 수동 오프셋 커밋 (`COMMIT`)
- `COMMIT <consumer_id>`
  - 컨슈머가 현재 활성 상태이고, 자신이 기억하는 세대 번호가 그룹의 현재 `generation_id`와 일치할 때만 커밋이 성공합니다.
  - 컨슈머가 퇴출되었거나, 도중에 리밸런스가 발생하여 세대가 변경되었다면 커밋이 거부됩니다.
  - 성공 출력: `COMMIT_OK consumer=<consumer_id> generation=<generation_id>`
  - 실패 출력: `ERROR:COMMIT_FAILED consumer=<consumer_id> reason=REBALANCED_OR_EVICTED generation=<current_generation_id>`

### 6) 컨슈머 정상 이탈 (`LEAVE_GROUP`)
- `LEAVE_GROUP <consumer_id>`
  - 컨슈머가 정상 종료(Graceful Shutdown)할 때 호출합니다.
  - 상태가 `LEFT`로 전환되고 파티션이 회수되며, 남은 활성 멤버들에게 즉시 리밸런스가 일어납니다.
  - 출력:
    ```text
    LEAVE_OK consumer=<consumer_id>
    REBALANCE_TRIGGERED generation=<gen> reason=CONSUMER_LEAVE member=<consumer_id>
    ```

### 7) 컨슈머 설정 튜닝 (`TUNE_CONSUMER`)
- `TUNE_CONSUMER <consumer_id> <new_max_poll_interval_ms> <new_max_poll_records>`
  - 활성 컨슈머의 타임아웃 제한 시간과 1회 poll 배치 크기를 동적으로 변경합니다.
  - 출력: `TUNE_OK consumer=<consumer_id> max_poll_interval=<ms> max_poll_records=<n>`

### 8) 상태 요약 (`STATS`)
- `STATS`
  - 현재 세대 번호, 총 리밸런스 횟수, 활성 멤버 목록, 퇴출된 멤버 목록, 파티션별 잔여 Lag을 출력합니다.
  - 출력: `STATS generation=<gen> rebalances=<count> active_members=[<active_list>] evicted_members=[<evicted_list>] lag=[<p0_lag>, <p1_lag>, ...]`

---

## 4. 실무 권장 아키텍처 및 교훈

1. **`max.poll.records`와 `max.poll.interval.ms`의 상관관계**:
   - 배치 1건당 최악의 지연시간($T_{max}$)을 측정하고, $N_{records} 	imes T_{max} < T_{interval}$ 공식을 반드시 만족하도록 설정해야 합니다.
   - 외부 네트워크 호출이 있다면 `max.poll.records`를 기본 500개에서 10~50개 수준으로 대폭 낮추는 것이 안전합니다.
2. **워커 스레드 풀(Worker Thread Pool) 비동기 오프로딩**:
   - 카프카 `poll()` 루프는 오직 메시지를 인메모리 큐에 넘기는 역할만 하고 즉시 다음 `poll()`을 호출해야 카프카 브로커와의 커넥션 및 파티션 소유권을 안정적으로 유지할 수 있습니다.
3. **협력적 스티키 어사이너 (`CooperativeStickyAssignor`) 활용**:
   - 카프카 2.4+ 이상에서는 `partition.assignment.strategy`로 협력적 스티키 방식을 사용하여, 리밸런스 시 모든 컨슈머가 멈추는 Stop-The-World 없이 문제없는 파티션은 지속적으로 처리하도록 만듭니다.
4. **멱등성(Idempotency) 필수 설계**:
   - 리밸런스로 인한 `CommitFailedException`이 발생하면 이미 처리된 메시지가 다른 컨슈머에 의해 무조건 재처리됩니다. 비즈니스 로직에 멱등 키(Unique Key, Redis 처리 이력) 검증을 반드시 갖추어야 합니다.
