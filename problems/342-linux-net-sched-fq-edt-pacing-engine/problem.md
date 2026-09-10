# Linux Kernel Fair Queueing (sch_fq) 및 EDT(Earliest Departure Time) 패킷 페이싱 엔진

## 문제 설명

현대 인터넷과 리눅스 커널 네트워크 스택(`net/sched/sch_fq.c`)에서 **sch_fq (Fair Queueing with Pacing)**는 Google BBR(Bottleneck Bandwidth and RTT) 혼잡 제어 알고리즘의 핵심 토대로 동작하는 최첨단 큐잉 규율(qdisc)입니다. 기존의 버퍼블로트(Bufferbloat) 문제를 해결하고 대역폭 폭주를 완화하기 위해, `sch_fq`는 각 소켓/흐름별 **DRR(Deficit Round Robin)** 공정 큐잉과 **EDT(Earliest Departure Time)** 기반의 마이크로초 단위 하드웨어/소프트웨어 패킷 페이싱(Pacing)을 융합하여 구현합니다.

본 문제에서는 리눅스 커널 네트워크 스케줄러의 `sch_fq` 아키텍처를 정밀하게 모사하는 **이산 시간 FQ/EDT 페이싱 엔진**을 설계 및 구현해야 합니다.

```
                    +------------------------------------------+
                    |           리눅스 네트워크 스택 (BBR)      |
                    +------------------------------------------+
                                         |
                                         v
                            skb->tstamp (EDT) / sk_pacing_rate
                                         |
                                         v
       +--------------------------------------------------------------------+
       |                   sch_fq 패킷 스케줄러 (Qdisc)                      |
       |                                                                    |
       |  +--------------------+         +-------------------------------+  |
       |  | new_flows (FIFO)   |         | old_flows (FIFO)              |  |
       |  | [Flow A] -> [Flow B]        | [Flow C] -> [Flow D]          |  |
       |  +--------------------+         +-------------------------------+  |
       |            |                                   ^                   |
       |            | quantum 소진 (credit <= 0)         |                   |
       |            +-----------------------------------+                   |
       |                                                                    |
       |  +---------------------------------------------------------------+  |
       |  | throttled_flows (EDT Min-Heap / Red-Black Tree)               |  |
       |  | Key = time_next_packet (EDT Departure Timestamp)              |  |
       |  | [Flow E (T=1.2ms)] -> [Flow F (T=1.5ms)] ...                   |  |
       |  +---------------------------------------------------------------+  |
       +--------------------------------------------------------------------+
                                         |
                                         v
                             NIC 송신 큐 (Ring Buffer)
```

---

## 핵심 메커니즘 및 명세

### 1. 흐름(Flow) 및 큐잉 상태 머신
각 소켓 또는 5-tuple로 식별되는 흐름(`flow_id`)은 다음 4가지 상태 중 하나를 가집니다:
- `INACTIVE`: 큐에 대기 중인 패킷이 없는 비활성 상태.
- `NEW`: 새로 도착하여 아직 최초 할당된 `quantum`을 소진하지 않은 우선 처리 상태 (`new_flows` 큐에 위치).
- `OLD`: 할당된 `quantum`을 소진하여 일반 라운드 로빈 순환 큐로 이동한 상태 (`old_flows` 큐에 위치).
- `THROTTLED`: 패킷의 송출 예정 시각(`time_next_packet`) 또는 소켓 EDT 요구 시각(`skb_tstamp_ns`)이 현재 시각(`current_time_ns`)보다 미래여서 송출이 보류된 상태 (`throttled_flows` 최소 힙에 위치).

### 2. 패킷 유입 (`ENQUEUE`)
- 입력: `packet_id`, `flow_id`, `size_bytes`, `arrival_time_ns`, `skb_tstamp_ns`(기본 0), `pacing_rate_bps`(기본 0)
1. **시각 동기화**: `arrival_time_ns > current_time_ns`인 경우, 시뮬레이션 시각을 `arrival_time_ns`로 전진시키고 지연 해제(Unthrottle)를 수행합니다.
2. **소켓 페이싱 속도 갱신**: `pacing_rate_bps > 0`이면 해당 흐름의 `socket_pacing_rate`를 갱신합니다.
3. **버퍼 한계 검사 및 드롭 정책**:
   - `total_qlen >= limit`이면 전역 버퍼 초과로 패킷을 즉시 드롭하고 `status: "DROPPED_GLOBAL_LIMIT"`를 반환합니다.
   - `len(flow.queue) >= flow_limit`이면 흐름별 큐 한계 초과로 패킷을 드롭하고 `status: "DROPPED_FLOW_LIMIT"`를 반환합니다.
4. **엔큐 및 상태 전이**:
   - 패킷을 흐름 큐에 적재하고, 전역 통계(`total_qlen`, `total_byte_len`)를 갱신합니다.
   - 흐름이 `INACTIVE` 상태였다면:
     - `credit = initial_quantum`으로 초기화합니다.
     - 흐름의 기준 시각 `time_next_packet = max(time_next_packet, arrival_time_ns)`로 정렬합니다.
     - 필수 송출 시각 $T_{\text{req}} = \max(\text{time\_next\_packet}, \text{skb\_tstamp\_ns})$를 계산합니다.
     - $T_{\text{req}} > \text{current\_time\_ns}$이면 `flow.state = "THROTTLED"`로 설정하고 최소 힙에 삽입합니다.
     - 그렇지 않으면 `flow.state = "NEW"`로 설정하고 `new_flows` 꼬리에 추가합니다.
   - 반환 형식: `{"status": "ENQUEUED", "packet_id": ..., "flow_id": ..., "flow_qlen": ..., "total_qlen": ...}`

### 3. 시간 전진 및 Throttled 해제 (`ADVANCE_TIME`)
- `current_time_ns`가 주어지면 시각을 전진시킵니다.
- `throttled_flows` 힙에서 `time_next_packet <= current_time_ns`인 모든 흐름을 추출(Pop)합니다.
- 대기 큐에 패킷이 남아있으면 `flow.state = "OLD"`로 변경하고 `old_flows` 꼬리에 추가합니다. (패킷이 없으면 `INACTIVE`)
- 반환 형식: `{"status": "TIME_ADVANCED", "current_time_ns": ...}`

### 4. 패킷 디큐 및 DRR 송출 (`DEQUEUE`)
- 입력: `count` (최대 디큐 패킷 수)
- 각 디큐 시도 시 다음 순서로 송출할 흐름을 탐색합니다:
  1. `new_flows`의 헤드 검사:
     - 큐가 비어있으면 제거 후 `INACTIVE`.
     - 헤드 패킷의 요구 시각 $\max(\text{time\_next}, \text{skb\_tstamp}) > \text{current\_time}$이면 `THROTTLED`로 전환 후 힙 삽입.
     - `credit <= 0`이면 `credit += quantum` 후 `OLD` 상태로 변경하여 `old_flows` 꼬리로 이동.
     - 조건을 만족하는 첫 흐름을 선택.
  2. `new_flows`에서 선택하지 못한 경우, `old_flows`의 헤드 검사:
     - 동일한 규칙으로 검사하여 전송 가능한 첫 흐름을 선택.
  3. 전송 가능한 흐름이 없으면 즉시 디큐 루프를 종료합니다.
- 흐름에서 패킷 1개를 디큐하고 다음 처리를 수행합니다:
  - `departure_time_ns = current_time_ns`
  - `credit -= size_bytes`
  - 차기 패킷 송출 가능 시각 갱신:
    $$\Delta t = \begin{cases} \lfloor \frac{\text{size\_bytes} \times 10^9}{\text{socket\_pacing\_rate}} \rfloor & (\text{socket\_pacing\_rate} > 0) \\ 0 & (\text{기본값}) \end{cases}$$
    $$\text{time\_next\_packet} = \text{departure\_time\_ns} + \Delta t$$
  - 만약 `credit <= 0`이면 `credit += quantum`을 즉시 수행합니다 (Deficit 보충).
  - 송출 후 후속 처리:
    - 큐가 비었으면 흐름 제거 후 `INACTIVE`.
    - 큐에 패킷이 남아있고, 다음 헤드 패킷의 요구 시각이 현재 시각보다 크면 `THROTTLED`로 전환 후 힙 삽입.
    - 큐에 패킷이 남아있고 크레딧이 방금 보충되었거나 소진 상태였으면, `new_flows` 또는 `old_flows`의 헤드에서 제거하여 `old_flows` 꼬리로 이동.
    - 큐에 패킷이 남아있고 크레딧이 남아있으며 쓰로틀되지 않았다면, 현재 큐 헤드 위치를 유지하여 버스트 송출을 지속합니다.
- 반환 형식: `{"dequeued": [ {"packet_id": ..., "flow_id": ..., "size_bytes": ..., "departure_time_ns": ..., "flow_credit_after": ...}, ... ], "count": len(dequeued)}`

### 5. 통계 조회 (`GET_FLOW_STATS`, `GET_QDISC_STATS`)
- `GET_FLOW_STATS`: 흐름의 `flow_id`, `state`, `credit`, `qlen`, `byte_len`, `time_next_packet`, `packets_enqueued`, `packets_dequeued`, `bytes_dequeued`, `packets_dropped`. (흐름 미존재 시 `null`)
- `GET_QDISC_STATS`: `current_time_ns`, `total_qlen`, `total_byte_len`, `new_flows_count`, `old_flows_count`, `throttled_flows_count`, `drops_global_limit`, `drops_flow_limit`.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "config": {
    "quantum": 1514,
    "initial_quantum": 1514,
    "limit": 100,
    "flow_limit": 20
  },
  "operations": [
    { "op": "ENQUEUE", "packet_id": "p1", "flow_id": "f1", "size_bytes": 1000, "arrival_time_ns": 0, "pacing_rate_bps": 1000000 },
    { "op": "DEQUEUE", "count": 1 },
    { "op": "ADVANCE_TIME", "current_time_ns": 1000000 },
    { "op": "GET_FLOW_STATS", "flow_id": "f1" },
    { "op": "GET_QDISC_STATS" }
  ]
}
```

## 출력 형식

표준 출력(stdout)으로 연산 수행 결과를 담은 JSON 배열을 공백 없이(compact) 출력합니다.

---

## 제약 사항

- $1 \le \text{quantum} \le 65535$
- $1 \le \text{limit} \le 10000$
- $1 \le \text{flow\_limit} \le 1000$
- $0 \le \text{arrival\_time\_ns} \le 10^{15}$
- 연산 수 $N \le 5000$
- 시간 복잡도: 각 연산당 $O(\log K)$ (여기서 $K$는 쓰로틀된 흐름 수), 전체 $O(N \log K)$ 이내.
