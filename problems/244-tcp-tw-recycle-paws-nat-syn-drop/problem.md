# Problem 244: 리눅스 커널 네트워크: `tcp_tw_recycle`, PAWS(Protection Against Wrapped Sequences) NAT 게이트웨이 SYN 드롭 대참사 및 `tcp_tw_reuse`

## 1. 개요 및 배경 시나리오

초당 수만 건의 인바운드 HTTP/TCP 연결을 처리하는 대규모 웹 서비스 및 API 게이트웨이 클러스터에서 서버 엔지니어들은 소켓이 종료될 때 생성되는 수많은 **`TIME_WAIT` 소켓**으로 인한 메모리 및 로컬 포트 고갈 문제를 자주 겪습니다.

과거 많은 시스템 관리자들은 인터넷 블로그와 오래된 성능 튜닝 가이드를 참고하여 다음과 같이 리눅스 커널 파라미터를 설정했습니다:
```bash
sysctl -w net.ipv4.tcp_timestamps=1
sysctl -w net.ipv4.tcp_tw_recycle=1
```
이 옵션을 켜면 커널은 표준 60초($2 \times \text{MSL}$) 동안 대기하는 `TIME_WAIT` 상태를 불과 $3.5 \times \text{RTO}$ (약 $1\sim3$초) 만에 초고속으로 회수(Recycle)하여 `TIME_WAIT` 소켓 수를 0에 가깝게 유지해 줍니다.

```
                  tcp_tw_recycle와 NAT 환경의 PAWS SYN 드롭 대참사
                  
 [동일한 회사 공인 IP(203.0.113.50) 뒤의 사내망 직원 A와 B]
 
 Device A (노트북 켜진 지 4시간: TSval = 15,000,000)
    │
    │── 1. SYN (TSval = 15,000,000) ──► Linux Web Server (tcp_tw_recycle=1)
    │◄── 2. SYN-ACK / Established ────┤ [inet_peer 캐시 기록: 203.0.113.50 -> TS=15,000,000]
    │── 3. FIN / Connection Close ────┘ [TIME_WAIT 초고속 3초 회수 완료]
 
 Device B (노트북 방금 켬: TSval = 12,000,000)
    │
    │── 4. SYN (TSval = 12,000,000) ──► Linux Web Server
    │                                         │
    │      (서버의 무응답 침묵!)                  ▼ [tcp_v4_conn_request() 검사]
    │      Client Retransmit Timeout!          incoming_TS (12,000,000) < peer_TS (15,000,000)
    │      (1초, 3초, 7초 재전송 루프...)         "과거 세션의 지연 패킷이다! (PAWS 거부)"
    ▼                                         ▼
 Connection Timeout Failure!              [SYN 패킷 사일런트 드롭 (Silent Drop)]
```

그러나 프로덕션 배포 직후, 회사 사내망이나 통신사 모바일 망(CGNAT) 등 **대규모 NAT 게이트웨이 환경에서 접속하는 고객들에게서 정체불명의 간헐적 접속 불능 장애**가 터져 나오기 시작했습니다:

1. **NAT IP 공유 클라이언트의 무작위 SYN 사일런트 드롭 (`TCP_TW_RECYCLE_NAT_PAWS_SYN_DROP`)**:
   - 동일한 공인 IP(`203.0.113.50`)를 공유하는 수백 명의 사용자 중, 부팅 시간이 긴 기기 A가 먼저 접속하면 서버의 전역 피어 캐시(`inet_peer`)에 높은 타임스탬프($\text{TSval} = 15,000,000$)가 기록됩니다.
   - 직후 부팅된 지 얼마 안 되어 타임스탬프가 작은 기기 B($\text{TSval} = 12,000,000$)가 동일 IP에서 `SYN`을 보내면, 서버 커널은 **PAWS(Protection Against Wrapped Sequence Numbers) 검사**에 의해 이 SYN을 이전 연결의 오래된 지연 복제 패킷으로 오판하고 **어떠한 RST나 에러 응답도 없이 조용히 버려버립니다(Silent Drop)**.

2. **클라이언트 무한 대기 및 연결 타임아웃 장애 (`INTERMITTENT_CLIENT_CONNECTIVITY_TIMEOUT`)**:
   - 클라이언트는 서버로부터 아무런 응답을 받지 못하므로 1초, 3초, 7초 간격으로 SYN 재전송(Retransmission)을 반복하다가 결국 `Connection timed out` 에러로 실패합니다.
   - 특정 사무실에서는 누구는 접속되고 누구는 영구 접속 불능에 빠지는 극단적인 간헐적 장애가 발생합니다.

3. **`tcp_tw_recycle`의 완전한 폐기와 `tcp_tw_reuse`**:
   - 이 치명적인 결함으로 인해 리눅스 커널 메인라인은 4.12 버전에서 `net.ipv4.tcp_tw_recycle` 옵션을 **완전히 영구 삭제**했습니다.
   - 올바른 해결책은 `tcp_tw_recycle`을 즉시 비활성화(`0`)하고, 아웃바운드 클라이언트 소켓 재사용을 위해 안전한 **`net.ipv4.tcp_tw_reuse = 1`**을 사용하는 것입니다.

본 과제에서는 리눅스 커널의 피어 캐시, 타임스탬프 PAWS 거부 알고리즘, NAT 환경의 타임스탬프 역전 시뮬레이션을 구현하고 시스템을 진단해야 합니다.

---

## 2. 상태 머신 및 동작 명세

시뮬레이터는 서버 커널 설정(`server_config`)과 일련의 네트워크 연결 이벤트(`events`)를 처리합니다.

### 2.1 서버 설정 (`server_config`)
- `tcp_timestamps`: `0` (비활성화) | `1` (활성화).
- `tcp_tw_recycle`: `0` (비활성화 - 안전) | `1` (활성화 - NAT 환경에서 위험).
- `tcp_tw_reuse`: `0` (비활성화) | `1` (아웃바운드 안전 재사용).
- `time_wait_timeout_sec`: 표준 TIME_WAIT 유지 시간 (기본 60초).
- `recycle_timeout_sec`: 초고속 회수 시간 (기본 3초).

### 2.2 커널 검사 및 소켓 상태 전이 규칙
1. **`SYN_PACKET` 수신 시**:
   - `tcp_timestamps == 1` 및 `tcp_tw_recycle == 1`인 경우:
     - 커널 전역 `peer_cache`에서 해당 `client_ip`의 이전 기록을 조회합니다.
     - 직전 기록이 최근 60초 이내에 존재하고, 현재 수신된 `ts_val`이 직전 기록의 `last_ts_val`보다 작으면:
       - **PAWS 검사 실패! SYN 패킷을 사일런트 드롭(`syn_dropped_paws` 증가)**합니다.
       - 소켓을 생성하지 않고 즉시 처리를 종료합니다.
     - 통과 시: `peer_cache[client_ip]`의 타임스탬프를 갱신하고 소켓을 `SYN_RCVD` 상태로 등록합니다.
   - `tcp_tw_recycle == 0`인 경우:
     - 전역 IP 단위의 타임스탬프 검사를 수행하지 않으므로, NAT 뒤의 타임스탬프 역전과 무관하게 **모든 정상 SYN을 수락**합니다.

2. **`CONNECTION_ESTABLISHED`**:
   - 소켓 상태를 `ESTABLISHED`로 변경하고 연결 지연시간(`max_conn_latency_ms`)을 계산합니다.

3. **`CONNECTION_CLOSE`**:
   - 서버가 먼저 종료(`initiator == "SERVER"`)한 경우 소켓은 `TIME_WAIT` 상태로 전이됩니다.
   - 만료 대기 시간: `tcp_tw_recycle == 1`이면 `recycle_timeout_sec`(3초), 그렇지 않으면 `time_wait_timeout_sec`(60초).

---

### 2.3 감지해야 할 이상 징후 (`anomalies`) 및 권장안 (`recommendations`)

- `"TCP_TW_RECYCLE_NAT_PAWS_SYN_DROP"`:
  - `tcp_tw_recycle=1` 상태에서 동일 IP의 타임스탬프 역전으로 인해 SYN 드롭이 1건 이상 발생한 경우.
  - 권장안: `"DISABLE_TCP_TW_RECYCLE_IMMEDIATELY"`, `"UPGRADE_KERNEL_VERSION_4_12_PLUS"`
- `"INTERMITTENT_CLIENT_CONNECTIVITY_TIMEOUT"`:
  - SYN 드롭으로 인해 재전송 카운트가 3회 이상이거나 연결 지연시간이 3,000ms 이상 소요된 경우.
- `"TIME_WAIT_SOCKET_EXHAUSTION_RISK"`:
  - 활성 TIME_WAIT 소켓이 5,000개 이상 누적되고 `tcp_tw_reuse == 0`인 경우.
  - 권장안: `"ENABLE_TCP_TW_REUSE_FOR_OUTBOUND_CLIENTS"`

---

## 3. 입력 형식 (`sys.stdin`)

표준 입력으로 단일 JSON 객체가 주어집니다.

```json
{
  "server_config": {
    "tcp_timestamps": 1,
    "tcp_tw_recycle": 1,
    "tcp_tw_reuse": 0,
    "time_wait_timeout_sec": 60,
    "recycle_timeout_sec": 3
  },
  "events": [
    {"time_ms": 100, "type": "SYN_PACKET", "conn_id": "c-1", "client_ip": "203.0.113.50", "client_port": 40001, "ts_val": 150000},
    {"time_ms": 110, "type": "CONNECTION_ESTABLISHED", "conn_id": "c-1"},
    {"time_ms": 150, "type": "CONNECTION_CLOSE", "conn_id": "c-1", "initiator": "SERVER"},
    {"time_ms": 200, "type": "SYN_PACKET", "conn_id": "c-2", "client_ip": "203.0.113.50", "client_port": 40002, "ts_val": 120000}
  ]
}
```

---

## 4. 출력 형식 (`sys.stdout`)

표준 출력으로 JSON 객체를 단일 행으로 출력합니다 (`ensure_ascii=False`).

```json
{
  "server_config": {
    "tcp_timestamps": 1,
    "tcp_tw_recycle": 1,
    "tcp_tw_reuse": 0
  },
  "total_syn_packets": 2,
  "established_connections": 1,
  "syn_dropped_paws": 1,
  "retransmitted_syn_count": 0,
  "active_time_wait_sockets": 1,
  "recycled_time_wait_sockets": 0,
  "max_connection_latency_ms": 10,
  "anomalies": [
    "TCP_TW_RECYCLE_NAT_PAWS_SYN_DROP"
  ],
  "recommendations": [
    "DISABLE_TCP_TW_RECYCLE_IMMEDIATELY",
    "UPGRADE_KERNEL_VERSION_4_12_PLUS"
  ],
  "diagnosis": "동일 NAT IP 뒤의 복수 클라이언트 간 타임스탬프 불일치로 인해 서버가 SYN 패킷 1건을 사일런트 드롭함 (PAWS 거부)."
}
```
