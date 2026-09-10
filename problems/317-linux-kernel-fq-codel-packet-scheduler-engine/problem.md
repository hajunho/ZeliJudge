# 리눅스 커널 FQ-CoDel(Fair Queueing with Controlled Delay, RFC 8290) 패킷 스케줄러 및 버퍼블로트 방어 엔진 (Linux Kernel FQ-CoDel Packet Scheduler Engine)

## 문제 설명

인터넷 라우터와 호스트 운영체제의 네트워크 스택에서 버퍼 메모리가 과도하게 커짐에 따라, 패킷이 적시에 처리되지 못하고 큐에 수백 밀리초에서 수 초 동안 갇혀 왕복 지연시간(RTT)이 폭증하는 현상을 **버퍼블로트(Bufferbloat)**라고 합니다.

특히 단일 FIFO 테일 드롭(Tail-Drop) 큐에서는 대용량 파일 다운로드나 동영상 스트리밍과 같은 벌크 플로우(Elephant Flow)가 전체 버퍼를 가득 채움으로써, 웹 브라우징, DNS 쿼리, 온라인 게임, VoIP 음성 통화와 같은 대화형 소량 트래픽(Mice Flow)이 극심한 지연과 지터를 겪게 됩니다.

이 문제를 해결하기 위해 제안된 **FQ-CoDel(Fair Queueing with Controlled Delay, IETF RFC 8290, `net/sched/sch_fq_codel.c`)**은 현대 리눅스 커널(systemd, Ubuntu, Fedora, OpenWrt 등)의 기본 큐잉 디시플린(Default Qdisc)으로 채택된 혁신적인 네트워크 스케줄링 알고리즘입니다.

```
+---------------------------------------------------------------------------------+
|                       Linux Kernel FQ-CoDel Architecture                        |
+---------------------------------------------------------------------------------+
| Incoming Packets (IPv4 / IPv6 5-Tuple Hash)                                     |
+---------------------------------------------------------------------------------+
                                         |
                                         v
   +---------------------------------------------------------------------------+
   |                     Fair Queueing (Flow Classification)                   |
   |                     Hash(5-tuple) % flows_cnt (e.g., 1024)                 |
   +---------------------------------------------------------------------------+
          |                             |                             |
          v                             v                             v
   [ Flow Bucket 0 ]             [ Flow Bucket 1 ]             [ Flow Bucket N ]
   +---------------+             +---------------+             +---------------+
   | Packet 1 (1KB)|             | Packet 3(60B) |             | Packet 5 (1KB)|
   | Packet 2 (1KB)|             | Packet 4(200B)|             | ...           |
   +---------------+             +---------------+             +---------------+
          |                             |                             |
          +-----------------------------+-----------------------------+
                                        |
                                        v
   +---------------------------------------------------------------------------+
   | DRR Scheduler: Deficit Round-Robin (new_flows vs old_flows Lists)         |
   | - new_flows: 신규/대화형 플로우 우선 처리 (극소 지연 보장)                 |
   | - old_flows: 퀀텀(quantum, 1514B) 소진 플로우 순환 분배                    |
   +---------------------------------------------------------------------------+
                                        |
                                        v
   +---------------------------------------------------------------------------+
   | CoDel Active Queue Management (Dequeue Engine)                            |
   | - 체류 시간(Sojourn Time) = current_time - pkt.enqueue_time                |
   | - target (5ms), interval (100ms)                                          |
   | - sojourn > target 지속 시: dropping 상태 진입!                           |
   | - 1/sqrt(count) 주기적 드롭 스케줄링 또는 ECN CE 마킹 (RFC 8290)           |
   +---------------------------------------------------------------------------+
                                        |
                                        v
                            [ NIC Transmit Ring ]
```

### 1. FQ-CoDel 2대 핵심 메커니즘

#### 1.1 결손 라운드로빈(DRR) 기반 흐름 격리 (Fair Queueing)
1. **플로우 분류**: 도착한 패킷은 5-튜플 해시를 통해 $N$개의 독립된 플로우 큐 중 하나로 배정됩니다.
2. **이중 연결 리스트 구조 (`new_flows` vs `old_flows`)**:
   - 빈 큐에 새로 패킷이 도착한 플로우는 `new_flows` 끝에 등록되며 `deficit = quantum`(기본 1514바이트)이 부여됩니다.
   - 디큐 시 `new_flows`가 항상 `old_flows`보다 우선권을 갖습니다.
   - 패킷을 송신할 때마다 해당 크기만큼 `flow.deficit -= pkt.size`를 차감합니다.
   - `deficit <= 0`이 되면 `deficit += quantum`을 충전한 후 `old_flows` 끝으로 이동합니다.
   - 큐가 비게 되면 즉시 리스트에서 제거됩니다.

#### 1.2 CoDel (Controlled Delay) 능동 큐 관리 (AQM)
패킷이 큐에서 나갈 때(Dequeue 시점) 실제 체류 시간(`sojourn_time = now - pkt.enqueue_time`)을 측정하여 제어합니다:
1. **소전 시간 검사**:
   - `sojourn_time < target_us (5000us)`: 정상 상태. `first_above_time_us = 0`, `dropping = False`. 패킷 정상 전송.
   - `sojourn_time >= target_us`:
     - 만약 `dropping == False`:
       - 최초 초과 시: `first_above_time_us = now + interval_us (100000us)`.
       - 만약 `now >= first_above_time_us`: 지속적인 버퍼블로트로 판단하고 `dropping = True`, `count = 1`, `drop_next_us = now + int(interval_us / sqrt(count))` 계산 후 드롭/마킹 실행.
     - 만약 `dropping == True`:
       - 만약 `now >= drop_next_us`: 드롭/마킹 실행, `count += 1`, `drop_next_us = now + int(interval_us / sqrt(count))`로 다음 드롭 주기 갱신.
2. **드롭 vs ECN 마킹**:
   - `ecn == True`이고 패킷의 `ecn_capable == True`인 경우: 패킷을 버리지 않고 `ecn_marked = True`로 설정하여 송신 (`CODEL_ECN_MARK`).
   - 그렇지 않은 경우: 패킷을 즉시 폐기(`CODEL_DROP`)하고, 다음 패킷을 연속으로 디큐하여 평가를 반복합니다.

#### 1.3 글로벌 버퍼 한도 초과 처리 (Overlimit Head-Drop)
새 패킷 인큐 시 전체 qdisc 패킷 수 `total_packets >= limit`인 경우, 가장 큐 길이가 긴 플로우(Fat Flow)의 맨 앞 패킷(Head Packet)을 강제 폐기(`OVERLIMIT_DROP`)하여 선량한 플로우의 고갈을 방지합니다.

---

## 입력 및 출력 형식

### 입력 형식 (JSON)
표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:
```json
{
  "config": {
    "flows_cnt": 4,
    "quantum": 1514,
    "target_us": 5000,
    "interval_us": 100000,
    "limit": 10,
    "ecn": true
  },
  "operations": [
    {
      "op": "ENQUEUE",
      "timestamp_us": 1000,
      "packet": {
        "pkt_id": 1,
        "flow_id": 0,
        "size": 1000,
        "ecn_capable": true
      }
    },
    {
      "op": "DEQUEUE",
      "timestamp_us": 3000
    }
  ]
}
```

### 출력 형식 (JSON)
표준 출력(stdout)으로 공백 없는 단일 행 압축 JSON을 출력합니다:
```json
{
  "stats": {
    "enqueued": 1,
    "dequeued": 1,
    "codel_drops": 0,
    "ecn_marks": 0,
    "overlimit_drops": 0
  },
  "total_packets": 0,
  "new_flows_count": 0,
  "old_flows_count": 0,
  "flows": {
    "0": {
      "queue_len": 0,
      "bytes": 0,
      "deficit": 514,
      "dropping": false,
      "count": 0
    }
  },
  "history": [...],
  "event_log": [...]
}
```
