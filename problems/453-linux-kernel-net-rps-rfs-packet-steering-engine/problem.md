# 문제 453: 리눅스 커널 초고속 네트워킹 — RPS (Receive Packet Steering) & RFS (Receive Flow Steering) 패킷 분배 및 캐시 친화도 엔진 (`net/core/dev.c`)

## 1. 개요 및 배경

초고속 10GbE / 100GbE 네트워크 환경에서 단일 CPU 코어가 초당 수백만 패킷의 인터럽트와 프로토콜 스택 처리(`NET_RX_SOFTIRQ`)를 모두 감당하는 것은 물리적으로 불가능합니다.
하드웨어 다중 큐 NIC는 **RSS(Receive Side Scaling)**를 통해 패킷 해시별로 서로 다른 하드웨어 RX 큐에 패킷을 분산시키지만, 다음과 같은 근본적인 한계가 존재합니다:
1. **하드웨어 제약**: 저가형 단일 큐 NIC나 가상 머신 가상 NIC(VirtIO-Net 등)에서는 하드웨어 RSS 지원이 불가능하거나 큐 수가 제한적입니다.
2. **캐시 비국소성 (Cache Locality Miss)**: NIC 인터럽트와 NAPI SoftIRQ가 CPU 코어 A에서 실행되더라도, 소켓으로부터 실제 데이터를 읽어가는 사용자 공간 애플리케이션(Nginx, Redis, Netty)은 CPU 코어 B에서 실행될 수 있습니다.
   이 경우 CPU A의 L1/L2 캐시에 적재된 패킷 헤더와 페이로드가 CPU B로 이동할 때 거대한 **CPU 간 캐시라인 바운싱(Inter-Core Cacheline Bouncing)**과 메모리 버스 지연이 발생합니다.

```
[RPS vs RFS 패킷 스티어링 비교]:
1) RPS (Receive Packet Steering):
   Ingress Packet ──> Hash(4-Tuple) ──> rps_cpus Bitmap ──> Target Core Backlog Queue (정적 분산)

2) RFS (Receive Flow Steering):
   User App (Core 2) ──(recvmsg)──> rps_sock_flow_table[flow] = Core 2
                                          │
   Ingress Packet ─────────(RFS Lookup)───┘
                                  │
                                  ├─ [Core 2로 즉각 배송! (L1/L2 캐시 적중률 99% 극대화)]
                                  └─ (코어 이주 감지 시: 이전 코어 큐가 드레인될 때까지 Reorder 방어 홀딩)
```

리눅스 커널은 이를 해결하기 위해 `net/core/dev.c`에 소프트웨어 기반 분산 기술인 **RPS**와 소켓 캐시 친화도 라우팅인 **RFS**를 구현하였습니다.
- **RPS (`get_rps_cpu`)**: 단일 큐 수신 패킷을 소프트웨어 해싱을 통해 지정된 멀티코어의 `input_pkt_queue` (Backlog Queue)로 고르게 분산시키고 IPI 인터럽트를 발송.
- **RFS (`rps_sock_flow_table`, `rps_dev_flow_table`)**: 소켓 시스템 콜(`recvmsg`)을 실행 중인 사용자 스레드의 CPU 코어를 실시간 추적하여, 해당 플로우의 패킷을 애플리케이션이 실행 중인 코어로 직통 배달.
- **패킷 역전 방어 장벽 (Out-of-Order Barrier)**: 애플리케이션이 코어 간 마이그레이션할 때, 이전 코어의 백로그에 남아있는 패킷들이 먼저 완전히 소진(`processed >= last_qtail`)될 때까지 신규 코어로의 전환을 지연시켜 TCP 패킷 역전(Out-of-Order) 현상을 완벽히 차단.

---

## 2. 핵심 메커니즘 및 상세 스펙

본 문제에서는 리눅스 커널 `net/core/dev.c`의 RPS/RFS 플로우 테이블 갱신, 패킷 스티어링, 백로그 큐 초과 드롭, NAPI 배치 처리 로직을 모델링하는 엔진을 구현합니다.

### 1) 시스템 설정 (`config`)
- `num_cpus`: CPU 코어 수 (기본 4).
- `netdev_max_backlog`: 코어당 허용되는 최대 백로그 패킷 수 (기본 100).
- `napi_weight`: NAPI 1회 실행당 처리 가능한 최대 패킷 수 (기본 64).
- `rps_cpus`: RPS 대상 CPU 코어 리스트 (기본 `[0, ..., num_cpus-1]`).
- `rfs_enabled`: RFS 활성화 여부 (boolean, 기본 true).

### 2) 소켓 수신 위치 갱신 (`APP_SOCKET_RECV`)
- `flow_hash`: 플로우 해시값 (int)
- `app_cpu`: 현재 애플리케이션 스레드가 `recvmsg()`를 호출한 CPU ID
- 글로벌 소켓 플로우 테이블 갱신: `rps_sock_flow_table[flow_hash] = app_cpu`.
- 반환: `{"status": "SOCK_FLOW_UPDATED", "flow_hash": flow_hash, "app_cpu": app_cpu}`.

### 3) 수신 패킷 인그레스 스티어링 (`INGRESS_PACKET`)
- `pkt_id`, `time_us`, `flow_hash`, `len`
- **목적지 CPU 선정 알고리즘 (`get_rps_cpu`)**:
  1. `rfs_enabled == true`이고 `flow_hash`가 `rps_sock_flow_table`에 존재하는 경우:
     - `desired_cpu = rps_sock_flow_table[flow_hash]`
     - 만약 디바이스 플로우 테이블(`rps_dev_flow_table`)에 미등록된 플로우라면:
       - `target_cpu = desired_cpu`, `method = "RFS"`.
     - 등록되어 있는 플로우인 경우 (`curr_cpu = dev_flow.cpu`):
       - `desired_cpu == curr_cpu`: `target_cpu = desired_cpu`, `method = "RFS"`.
       - `desired_cpu != curr_cpu` (코어 마이그레이션 발생!):
         - **패킷 역전 방어 검증**:
           $$\text{cpu\_processed}[\text{curr\_cpu}] \ge \text{dev\_flow.last\_qtail}$$
           - 이전 코어의 모든 기존 패킷이 이미 NAPI로 처리 완료된 경우:
             안전하게 새 코어로 전환 승인!
             `dev_flow.cpu = desired_cpu`, `target_cpu = desired_cpu`, `method = "RFS"`.
           - 이전 코어에 미처리 패킷이 남아있는 경우:
             TCP 패킷 역전을 막기 위해 이전 코어로 계속 전송!
             `target_cpu = curr_cpu`, `method = "RFS_DRAIN_HOLD"`.
  2. RFS 미적용 시 (RPS 폴백):
     - `target_cpu = rps_cpus[flow_hash % len(rps_cpus)]`, `method = "RPS"`.
- **백로그 큐 인큐**:
  - `target_cpu`의 백로그 큐 크기가 `netdev_max_backlog` 미만인 경우:
    - 큐에 패킷 적재, `cpu_enqueued[target_cpu] += 1`.
    - `dev_flow.last_qtail = cpu_enqueued[target_cpu]`로 갱신.
    - 반환: `{"status": "STEERED", "pkt_id": pkt_id, "target_cpu": target_cpu, "method": method, "backlog_len": len(queue)}`.
  - `netdev_max_backlog`에 도달한 경우:
    - 패킷 폐기! `total_dropped_backlog += 1`.
    - 반환: `{"status": "DROPPED_BACKLOG_FULL", "pkt_id": pkt_id, "target_cpu": target_cpu}`.

### 4) NAPI 소프트웨어 인터럽트 처리 (`PROCESS_NAPI`)
- `cpu_id`, `budget` (지정되지 않으면 `napi_weight`)
- `cpu_id`의 백로그 큐에서 최대 `budget`개의 패킷을 팝하여 프로토콜 스택으로 전달 처리.
- `cpu_processed[cpu_id] += processed_count`.
- 반환: `{"status": "NAPI_PROCESSED", "cpu_id": cpu_id, "processed_count": processed, "remaining_backlog": remaining}`.

### 5) 통계 조회 (`QUERY_STATS`)
- `total_steered_rps`, `total_steered_rfs`, `total_dropped_backlog`, `total_napi_processed`, 각 CPU별 잔여 백로그 큐 길이(`per_cpu_backlog`), 각 CPU별 누적 처리 패킷 수(`per_cpu_processed`)를 반환합니다.

---

## 3. 입력 및 출력 형식

### 입력 포맷 (표준 입력 JSON)
```json
{
  "config": {
    "num_cpus": 4,
    "netdev_max_backlog": 100,
    "napi_weight": 64,
    "rfs_enabled": true
  },
  "operations": [
    {"op": "APP_SOCKET_RECV", "flow_hash": 4660, "app_cpu": 2},
    {"op": "INGRESS_PACKET", "pkt_id": "p1", "time_us": 100, "flow_hash": 4660},
    {"op": "PROCESS_NAPI", "cpu_id": 2, "budget": 64},
    {"op": "QUERY_STATS"}
  ]
}
```

### 출력 포맷 (표준 출력 단일 라인 JSON)
```json
{"results":[...]}
```
모든 키와 값은 공백 없는 압축 JSON(`separators=(',', ':')`) 형식으로 출력합니다.
