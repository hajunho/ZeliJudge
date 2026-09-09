# 문제 253: Linux Kernel Network — TCP 아웃바운드 Ephemeral Port 고갈(EADDRNOTAVAIL), TIME_WAIT 버킷 오버플로우 vs tcp_tw_reuse 및 멀티 IP 이그레스 확장

## 1. 개요 (Incident Scenario)

대규모 마이크로서비스 아키텍처(MSA) 및 API 게이트웨이(Envoy, Nginx, HAProxy) 환경에서는 수많은 인입 클라이언트 트래픽을 단일 또는 소수의 업스트림 백엔드 서비스(예: `10.0.0.50:8080`)로 프록시 전달합니다. TCP 연결은 `(Source_IP, Source_Port, Dest_IP, Dest_Port)`라는 4-Tuple(4개 튜플)로 유일하게 식별됩니다. 목적지 `(Dest_IP, Dest_Port)`가 고정되어 있고 게이트웨이 호스트의 아웃바운드 IP(`Source_IP`)가 1개인 경우, 생성 가능한 최대 동시 세션 수는 커널의 임시 포트 범위(**Ephemeral Port Range**, 기본 `32768 ~ 60999`, 총 28,232개)에 의해 엄격히 제한됩니다.

블랙 프라이데이 정기 프로모션으로 초당 수천 건의 트래픽이 폭증하던 날, API 게이트웨이에서 대규모 서비스 장애가 발생했습니다:
1. **커넥션 생성 전면 중단 및 502 Bad Gateway 폭풍 (`-EADDRNOTAVAIL`)**: 백엔드로 향하는 HTTP 요청에 커넥션 풀링(Keep-Alive)이 적용되지 않아 매 요청마다 연결을 맺고 끊었습니다. 능동적 종료(Active Close)를 수행한 소켓들이 $2	ext{MSL}(60	ext{초})$ 동안 **`TIME_WAIT`** 상태로 묶이면서 60초 이내에 28,232개의 모든 포트가 소진되었습니다. 이후 유입된 모든 `connect()` 시스템 콜이 `dial tcp 10.0.0.50:8080: connect: cannot assign requested address (-EADDRNOTAVAIL)` 에러를 뿜으며 수만 명의 사용자에게 502 에러가 반환되었습니다.
2. **`tcp_max_tw_buckets` 오버플로우와 의문의 TCP RST 패킷 방출**: 시스템 전체의 `TIME_WAIT` 소켓 수가 커널 상한선(`tcp_max_tw_buckets`)을 초과하자, 커널은 `TCP: time wait bucket table overflow` 경고를 출력하며 기존 소켓을 강제 파괴하고 원격 피어로 TCP RST 패킷을 날려 정상 통신 중이던 다른 세션들까지 연쇄 강제 종료시켰습니다.
3. **`tcp_tw_reuse` 설정의 은밀한 함정**: 운영팀이 사태를 수습하기 위해 `net.ipv4.tcp_tw_reuse = 1`을 적용했으나, 패킷 크기 최적화를 위해 이전에 꺼두었던 `net.ipv4.tcp_timestamps = 0`으로 인해 RFC 1323 PAWS(Protection Against Wrapped Sequence Numbers) 검증이 불가능해져 `tcp_tw_reuse`가 내부적으로 무력화되었습니다.

당신은 리눅스 네트워크 스택 및 SRE 엔지니어로서, 네트워크 커널 설정, 목적지 주소, 초기 상태 및 아웃바운드 요청 스트림을 바탕으로 TCP 4-Tuple 포트 할당자, TIME_WAIT 소켓 라이프사이클, `tcp_tw_reuse`, 타임스탬프 요구조건, 버킷 오버플로우 및 HTTP 커넥션 풀링 상태 머신을 시뮬레이션하고, 장애 원인(Root Cause)과 아웃바운드 대역폭 확장 완화책을 도출해야 합니다.

---

## 2. 아키텍처 및 상태 머신 (System Architecture & State Machine)

```
 [ API Gateway / Reverse Proxy (192.168.1.10) ]
        │
        │ Requests to Backend (10.0.0.50:8080)
        ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ Outbound TCP 4-Tuple Allocator                              │
 │ Tuple = (Source_IP, Ephemeral_Port, Dest_IP, Dest_Port)     │
 │ Available Ports = port_range_end - port_range_start + 1     │
 └──────────────────────────────┬──────────────────────────────┘
                                │
               ┌────────────────┴────────────────┐
               ▼                                 ▼
   [ Port Available in Pool ]          [ Port in TIME_WAIT (2MSL=60s) ]
   - Allocate (Src_IP, Port)           - Can it be reused?
   - Request Successful!                 ├─ tcp_tw_reuse==1 & timestamps==1
   - Active Close -> Enters TIME_WAIT!   │  ──► REUSED! (No Port Starvation!)
                                         └─ ELSE:
                                            ──► Cannot allocate port!
                                                connect() -> -EADDRNOTAVAIL!
 ══════════════════════════════════════════════════════════════════════════
 [ Kernel TIME_WAIT Table & Bucket Limit ]
 
   Total TIME_WAIT Sockets >= tcp_max_tw_buckets?
   ├─► NO  ──► Normal 2MSL draining (60s timer)
   └─► YES ──► BUCKET OVERFLOW! Evict oldest socket + Send TCP RST!
```

### (1) 4-Tuple 포트 할당 및 고갈 규칙
- 유효 포트 수: $	ext{total\_ports} = (	ext{port\_range\_end} - 	ext{port\_range\_start} + 1) 	imes 	ext{len}(	ext{egress\_ips})$.
- HTTP 커넥션 풀링(`http_keepalive_enabled == true` 및 `connection_pool_size > 0`):
  - 연결을 재사용하여 새 포트를 소모하지 않고 `pool_hits += 1`, `successful_requests += 1`로 처리.
- 숏 리브드(Short-lived) 연결:
  - 사용 가능한 `(src_ip, port)`를 순회 탐색.
  - 해당 포트가 현재 `TIME_WAIT` 상태인 경우:
    - `tcp_tw_reuse >= 1` **AND** `tcp_timestamps == 1`인 경우에만 **재사용(Reuse) 성공** $ightarrow$ `tw_reused_count += 1`, `successful_requests += 1`.
    - 조건을 만족하지 못하면 해당 포트는 사용 불가.
  - 모든 이그레스 IP의 모든 포트가 고갈된 경우 `connect()` 실패 $ightarrow$ **`eaddrnotavail_errors += 1`**.

### (2) TIME_WAIT 수명 주기 및 버킷 오버플로우
- 정상 할당된 소켓은 요청 완료(능동 종료) 후 $T + 60$초 시점까지 `TIME_WAIT` 테이블에 상주.
- 현재 `TIME_WAIT` 소켓 수 $\ge 	ext{tcp\_max\_tw\_buckets}$인 경우:
  - 커널 버킷 오버플로우 발생 $ightarrow$ **`tw_bucket_overflow_resets += 1`**.
  - 가장 오래된 소켓을 강제 축출하고 RST 패킷 방출.
- `DRAIN_TIME_WAIT` 이벤트 또는 경과 시간 $T \ge 	ext{expire\_sec}$ 시 소켓은 정상 폐기되어 포트가 반환됨.

---

## 3. 입력 사양 (Input Specification)

표준 입력(`sys.stdin`)으로 다음 구조의 JSON 객체가 주어집니다:

```json
{
  "network_config": {
    "tcp_tw_reuse": 0,
    "tcp_timestamps": 1,
    "tcp_max_tw_buckets": 65536,
    "port_range_start": 32768,
    "port_range_end": 32787,
    "egress_ips": ["192.168.1.10"],
    "http_keepalive_enabled": false,
    "connection_pool_size": 0
  },
  "destination": {
    "ip": "10.0.0.50",
    "port": 8080
  },
  "events": [
    {"time_sec": 1, "type": "OUTBOUND_REQUEST_BATCH", "count": 30}
  ]
}
```

---

## 4. 출력 사양 (Output Specification)

표준 출력(`sys.stdout`)으로 다음 필드를 포함하는 JSON 객체를 출력합니다:

```json
{
  "final_state": {
    "current_sec": 1,
    "active_time_wait_sockets": 20,
    "total_ephemeral_tuples": 20,
    "active_pool_connections": 0
  },
  "metrics": {
    "successful_requests": 20,
    "eaddrnotavail_errors": 10,
    "tw_bucket_overflow_resets": 0,
    "tw_reused_count": 0,
    "pool_hits": 0
  },
  "root_cause": "TCP_EPHEMERAL_PORT_EXHAUSTION_EADDRNOTAVAIL",
  "recommendations": [
    "ENABLE_TCP_TW_REUSE_SYSCTL",
    "ENABLE_HTTP_KEEPALIVE_CONNECTION_POOLING",
    "SCALE_EGRESS_SOURCE_IPS_AND_EXPAND_PORT_RANGE"
  ]
}
```

### 진단 규칙 (Root Cause Hierarchy)
1. `eaddrnotavail_errors > 0`:
   - `tw_reuse >= 1`이고 `timestamps == 0`인 경우: `"TCP_TIMESTAMP_DISABLED_TW_REUSE_INEFFECTIVE"`
   - 그 외: `"TCP_EPHEMERAL_PORT_EXHAUSTION_EADDRNOTAVAIL"`
2. `tw_bucket_overflow_resets > 0`: `"TCP_TW_BUCKET_OVERFLOW_RST_STORM"`
3. 기타 정상 상태: `"STABLE_OUTBOUND_NETWORK_THROUGHPUT"`

### 권고사항 도출 규칙
- `eaddrnotavail_errors > 0` 또는 `tw_reuse == 0`:
  - `timestamps == 0`: `"ENABLE_TCP_TIMESTAMPS_FOR_PAWS"`
  - `tw_reuse == 0`: `"ENABLE_TCP_TW_REUSE_SYSCTL"`
- `not keepalive_enabled` 또는 `pool_size == 0`: `"ENABLE_HTTP_KEEPALIVE_CONNECTION_POOLING"`
- 단일 IP(`len(egress_ips) == 1`)이고 튜플 수 $\le 30,000$: `"SCALE_EGRESS_SOURCE_IPS_AND_EXPAND_PORT_RANGE"`
- `tw_bucket_overflow_resets > 0` 또는 `max_tw_buckets <= 10000`: `"INCREASE_TCP_MAX_TW_BUCKETS"`
- 해당 사항이 없으면: `["MONITOR_ESTABLISHED_AND_TIME_WAIT_SOCKETS"]`
