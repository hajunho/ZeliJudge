# 문제 448: 리눅스 커널 트래픽 제어 — CAKE (Common Applications Kept Enhanced) AQM & ACK 필터링 엔진 (`net/sched/sch_cake.c`)

## 1. 개요 및 배경

가정용 초고속 인터넷(광랜, VDSL, DOCSIS 케이블) 및 클라우드 게이트웨이, 5G/Starlink 위성 통신망에서는 **버퍼블로트(Bufferbloat)**로 인한 지연 시간 급증 현상이 지속적으로 발생합니다. 대용량 파일 다운로드나 백업 트래픽이 회선을 가득 채우면 라우터의 대형 FIFO 버퍼에 수백 밀리초 분량의 패킷이 적재되어, 실시간 음성 통화(VoIP), 화상 회의(Zoom), 온라인 게임, DNS 질의 등의 핑(RTT)이 10ms에서 500ms 이상으로 치솟아 체감 품질이 붕괴됩니다.

또한 비대칭 회선(다운로드 1Gbps / 업로드 50Mbps 등)에서는 다운로드에 대한 TCP 순수 응답(Pure ACK) 패킷이 좁은 업링크 버퍼를 가득 채워 다운로드 속도 자체를 억제하는 **ACK 인캐스트 병목(ACK Incast Bottleneck)**이 발생합니다.

리눅스 커널 4.19에 도입된 **CAKE (`net/sched/sch_cake.c`)**는 이러한 복합적인 버퍼블로트 문제를 해결하기 위해 탄생한 차세대 큐잉 디시플린(Qdisc)입니다.

```
[CAKE 다계층 패킷 스케줄링 및 큐 관리 파이프라인]:
Ingress Packet ──> [DiffServ Classifier] (DSCP -> Voice, Video, BestEffort, Bulk)
                          │
                          ▼
                 [8-Way Set-Associative Flow Hashing] (1024 Flows)
                          │
                          ▼
                 [TCP ACK Filter] (동일 플로우 구형 Pure ACK 즉각 폐기)
                          │
                          ▼
                 [Per-Flow CoDel AQM & ECN Marking] (체류 시간 지속 초과 시 폐기/CE 마킹)
                          │
                          ▼
                 [Deficit Round-Robin (DRR) Scheduler] ──> Egress Wire
```

CAKE의 핵심 설계 요소:
1. **DiffServ 멀티-틴(Tin) 우선순위 분리**: 패킷 IP 헤더의 DSCP 값을 기반으로 Voice, Video, BestEffort, Bulk 틴으로 자동 분류.
2. **8-Way 세트 연관 해시 (8-Way Set-Associative Hashing)**: 기존 FQ-CoDel의 평면 해시 충돌 문제를 극복하여 99%의 플로우 격리 보장.
3. **TCP ACK 필터링 (`cake_ack_filter`)**: 큐 내에 존재하는 이전 순수 TCP ACK를 최신 ACK 수신 시 인-플레이스 폐기하여 업링크 대역폭 30~50% 회수.
4. **CoDel 기반 능동적 큐 관리 (AQM)**: 패킷 체류 시간(Sojourn Time)이 목표치(`target`)를 초과하여 유지될 때 ECN CE 비트를 마킹하거나 지능적 패킷 폐기.

---

## 2. 핵심 메커니즘 및 상세 스펙

본 문제에서는 리눅스 커널 `net/sched/sch_cake.c`의 핵심 로직을 모델링하는 CAKE Qdisc 시뮬레이션 엔진을 구현합니다.

### 1) 설정 파라미터 (`config`)
- `diffserv_mode`: `"DIFFSERV4"` (기본) 또는 `"DIFFSERV3"`.
- `ack_filter_enabled`: boolean (기본 true).
- `target_us`: CoDel 목표 체류 지연 시간 (기본 5000 µs = 5ms).
- `interval_us`: CoDel 윈도우 관찰 주기 (기본 100000 µs = 100ms).

### 2) DSCP 기반 틴(Tin) 분류 규칙
- `DIFFSERV4` 모드:
  - **Tin 3 (Voice)**: DSCP ∈ `{46, 48, 56}` (EF, CS5, CS6)
  - **Tin 2 (Video)**: DSCP ∈ `{24, 26, 32, 34, 40}` (CS3, AF31, CS4, AF41, CS5)
  - **Tin 0 (Bulk)**: DSCP ∈ `{8, 10, 12, 14}` (CS1, AF11, AF12, AF13)
  - **Tin 1 (BestEffort)**: 기타 모든 DSCP (CS0 포함)
- `DIFFSERV3` 모드:
  - **Tin 3 (Voice)**: DSCP ∈ `{46, 48, 56}`
  - **Tin 0 (Bulk)**: DSCP ∈ `{8, 10, 12, 14}`
  - **Tin 1 (BestEffort)**: 기타 모든 DSCP (Video 트래픽도 Tin 1로 통합)

### 3) 8-Way 세트 연관 플로우 해싱
- 5-튜플 문자열: `"{src_ip}:{src_port}->{dst_ip}:{dst_port}/{proto}"`
- MD5 해시의 상위 16비트 mod 128로 `set_idx` (0~127) 결정.
- 하위 16비트 mod 8로 `way_idx` (0~7) 결정.
- 고유 플로우 ID: `flow_id = set_idx * 8 + way_idx`.

### 4) TCP ACK 필터링 (`ack_filter_enabled == true`)
- 조건: `proto == "TCP"` AND `tcp_flags == ["ACK"]` (순수 ACK) AND `len <= 64` (페이로드 없음).
- 플로우 큐에 이미 존재하는 순수 ACK 중 `existing.ack_seq < new_pkt.ack_seq`인 패킷이 발견되면:
  - 기존 구형 ACK를 큐에서 즉시 제거(폐기).
  - `ack_filtered_count` 1 증가.
  - 신규 ACK 인큐 시 `ack_filtered: true` 설정.
- 페이로드가 포함된 데이터 패킷(`len > 64`)이나 SYN/FIN/PSH 플래그가 포함된 패킷은 절대로 필터링하지 않습니다.

### 5) 디큐 및 CoDel AQM 처리 (`DEQUEUE`)
- **틴 스케줄링 순서**: Voice (3) -> Video (2) -> BestEffort (1) -> Bulk (0) 우선순위 순회.
- 플로우 순회: 틴 내 활성 플로우 ID 오름차순 정렬 순회.
- 선택된 플로우 큐의 헤드 패킷 체류 시간 계산:
  $$\text{sojourn\_us} = \text{time\_us} - \text{pkt.enqueue\_time}$$
- **CoDel 상태 머신**:
  - `sojourn_us > target_us`인 경우:
    - 처음 임계치를 넘었을 때: `first_above_time = time_us + interval_us`.
    - 현재 시각 `time_us >= first_above_time`인 경우: `dropping = true` 진입!
  - `sojourn_us <= target_us`인 경우:
    - `first_above_time = 0`, `dropping = false`.
- **패킷 처리 액션 결정**:
  - `dropping == true`인 경우:
    - 패킷이 ECN 지원(`pkt.ecn ∈ {1, 2}`):
      - ECN CE 비트 마킹: `pkt.ecn = 3`.
      - `ecn_marked_count` 1 증가.
      - `action = "ECN_MARKED"`, 패킷 디큐 및 전송.
    - 패킷이 ECN 미지원(`pkt.ecn == 0`):
      - 패킷 영구 폐기 (`queue.pop(0)`).
      - `aqm_dropped_count` 1 증가.
      - `action = "AQM_DROPPED"`, 반환.
  - `dropping == false`인 경우:
    - 정상 전송: `action = "DELIVERED"`.

### 6) 통계 조회 (`QUERY_STATS`)
- `total_enqueued`, `total_dequeued`, `ack_filtered_count`, `aqm_dropped_count`, `ecn_marked_count`, 그리고 틴별 패킷 수 및 바이트 수를 집계하여 반환합니다.

---

## 3. 입력 및 출력 형식

### 입력 포맷 (표준 입력 JSON)
```json
{
  "config": {
    "diffserv_mode": "DIFFSERV4",
    "ack_filter_enabled": true,
    "target_us": 5000,
    "interval_us": 100000
  },
  "operations": [
    {"op": "ENQUEUE", "packet": {"pkt_id": "p1", "time_us": 1000, "dscp": 46, "proto": "UDP", "len": 128}},
    {"op": "ENQUEUE", "packet": {"pkt_id": "ack1", "time_us": 1010, "dscp": 0, "proto": "TCP", "tcp_flags": ["ACK"], "ack_seq": 1000, "len": 54}},
    {"op": "DEQUEUE", "time_us": 2000},
    {"op": "QUERY_STATS"}
  ]
}
```

### 출력 포맷 (표준 출력 단일 라인 JSON)
```json
{"results":[...]}
```
모든 키와 값은 공백 없는 압축 JSON(`separators=(',', ':')`) 형식으로 출력합니다.
