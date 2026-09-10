# Problem #293: Linux Kernel GRO (Generic Receive Offload) NAPI Aggregation & Out-of-Order Defense

## 1. 개요 및 배경 (Overview & Background)

초고속 100GbE/400GbE 데이터센터 네트워크 환경에서 1500바이트 표준 MTU 패킷은 초당 수천만 개(Mpps) 수준으로 수신됩니다. 만약 네트워크 카드(NIC)가 수신한 패킷마다 리눅스 커널의 네트워크 스택(`netif_receive_skb` -> `ip_rcv` -> `tcp_v4_rcv`)을 개별적으로 통과한다면, CPU는 `sk_buff` 할당/해제, 인터럽트 핸들러 오버헤드, 캐시 미스(Cache Miss), 계층별 패킷 디캡슐레이션으로 인해 100% 포화 상태에 빠집니다.

이를 해결하기 위해 리눅스 커널은 **GRO (Generic Receive Offload)** 메커니즘(`net/core/dev.c`, `net/ipv4/tcp_offload.c`)을 구현했습니다.
GRO는 NIC 드라이버의 **NAPI(New API) 폴링 루프** 내에서 동일한 5-튜플(Source IP, Dest IP, Source Port, Dest Port, Protocol)을 공유하는 연속된 TCP 패킷들을 상위 네트워크 스택으로 올리기 전에 최대 64KB(`gro_max_size`) 크기의 **단일 거대 슈퍼 패킷(Super-packet)**으로 병합(Coalescing)합니다.

```
+-------------------------------------------------------------------------------+
|                       Linux Kernel NAPI & GRO Pipeline                        |
+-------------------------------------------------------------------------------+
  [ 100GbE NIC ] ---> Ring Buffer (Rx Descriptors)
                            |
                     [ NAPI Poll Loop ] (napi_gro_receive)
                            |
                 +----------+----------+
                 | Flow Lookup (5-Tuple)|
                 +----------+----------+
                            |
       +--------------------+--------------------+
       | (Match Existing Flow)                   | (New Flow)
       v                                         v
 [ Sequential Check ]                      [ Create GRO SKB ]
   - Seq == NextSeq?                         - Init GRO candidate
   - Timeout < 50us?                         - Hold in gro_list
   - Size + Len <= 64KB?                         |
       |                                         |
   +---+---+                                     |
   |       |                                     |
(Pass)   (Fail / Out-of-Order / Flag)            |
   |       |                                     |
   v       +-------------> [ Flush Existing ] <--+
[ Coalesce Packet ]                 |
(Update NextSeq, Ack,               v
 TotalBytes, frag_list)     [ Upper IP/TCP Stack ]
                            (__netif_receive_skb)
```

이 문제에서는 리눅스 커널의 GRO 엔진과 NAPI 폴링 루프의 핵심 병합/방출(Flush) 로직을 정확하게 시뮬레이션하고, 비순차(Out-of-Order) 패킷 유입, 제어 플래그(SYN/FIN/RST), ACK 압축(ACK Compression), 타임아웃 페이싱에 따른 병합 성능 지표 및 병목 진단을 산출하는 프로그램을 작성합니다.

---

## 2. 입출력 규격 (Input & Output Specification)

### 입력 형식 (Standard Input)
표준 입력(stdin)으로 JSON 객체가 주어집니다.
```json
{
  "config": {
    "gro_max_size": 65536,
    "gro_flush_timeout_us": 50.0,
    "ack_compression_enabled": true
  },
  "traffic_events": [
    {
      "type": "RX",
      "time_us": 0.0,
      "packet": {
        "src_ip": "10.0.1.10",
        "dst_ip": "10.0.2.20",
        "src_port": 49152,
        "dst_port": 8080,
        "protocol": "TCP",
        "tcp_seq": 100000,
        "tcp_ack": 50000,
        "flags": ["ACK"],
        "payload_len": 1460,
        "wire_len": 1514
      }
    },
    {
      "type": "NAPI_CYCLE_END",
      "time_us": 50.0
    }
  ]
}
```

- `config`:
  - `gro_max_size` (int, 기본값 65536): 단일 GRO 슈퍼 패킷의 최대 페이로드 바이트 수.
  - `gro_flush_timeout_us` (float, 기본값 50.0): 단일 GRO 패킷이 유지될 수 있는 최대 시간 간격(마이크로초).
  - `ack_compression_enabled` (bool, 기본값 true): 순수 ACK(payload_len == 0) 패킷의 병합 및 압축 활성화 여부.
- `traffic_events`: 시간순으로 정렬된 네트워크 이벤트 목록.
  - `type`: `"RX"` (패킷 수신) 또는 `"NAPI_CYCLE_END"` (NAPI 폴링 주기 종료).
  - `time_us` (float): 이벤트 발생 시각 (마이크로초 단위).
  - `packet`: (type이 "RX"일 때) 패킷 헤더 및 페이로드 메타데이터.

### 처리 규칙 (Processing Rules)

1. **플로우 식별 (Flow Identification)**:
   - 5-튜플 `(src_ip, dst_ip, src_port, dst_port, protocol)`로 활성 플로우(`active_flows`)를 식별합니다.

2. **특수 플래그(SYN, FIN, RST) 처리**:
   - 수신 패킷의 `flags`에 `SYN`, `FIN`, `RST` 중 하나라도 포함되어 있다면:
     - 해당 플로우에 이미 활성 중인 GRO 패킷이 있다면 이유 `"SPECIAL_FLAG"`로 즉시 방출(Flush)합니다.
     - 수신된 특수 플래그 패킷 또한 단독 슈퍼 패킷으로 생성된 후 즉시 `"SPECIAL_FLAG"` 이유로 방출됩니다.

3. **기존 활성 플로우와의 병합 판정 (Coalescing Decision)**:
   - 플로우가 아직 활성 상태가 아니라면, 새 GRO 패킷을 생성하고 등록합니다.
   - 플로우가 이미 활성 상태라면 다음 조건을 순서대로 검사합니다:
     1. **타임아웃 검사**: `(time_us - flow.first_time_us) >= gro_flush_timeout_us`이면, 기존 패킷을 `"TIMEOUT"`으로 방출하고 새 패킷으로 시작합니다.
     2. **패킷 유형 불일치 검사**: 기존 플로우가 순수 ACK 플로우인데 데이터 패킷이 오거나, 데이터 플로우인데 순수 ACK가 오면, 기존 플로우를 `"OUT_OF_ORDER"`로 방출하고 새 패킷으로 시작합니다.
     3. **시퀀스 연속성 검사**:
        - 순수 ACK(payload_len == 0): `ack_compression_enabled`가 true이고 `tcp_ack >= flow.last_ack_num`이면 유효. 아니면 `"OUT_OF_ORDER"`로 방출.
        - 데이터 패킷(payload_len > 0): `tcp_seq == flow.next_seq`이어야 병합 가능. 시퀀스 번호가 어긋나면 `"OUT_OF_ORDER"`로 방출하고 새 패킷으로 시작합니다.
     4. **최대 크기 검사**: `(flow.total_payload_bytes + payload_len) > gro_max_size`이면, 기존 패킷을 `"SIZE_LIMIT"`으로 방출하고 새 패킷으로 시작합니다.
     5. 위 조건을 모두 통과하면 기존 플로우에 성공적으로 병합(Coalesce)합니다:
        - `packet_count += 1`, `payload_bytes += payload_len`, `wire_bytes += wire_len`
        - `next_seq = tcp_seq + payload_len`, `last_time_us = time_us`, `last_ack_num = tcp_ack`
        - 순수 ACK인 경우 `ack_count += 1`.

4. **NAPI 주기 종료 (`NAPI_CYCLE_END`) 및 시뮬레이션 종료**:
   - `NAPI_CYCLE_END` 이벤트 또는 모든 이벤트 처리 완료 시, 현재 활성 중인 모든 플로우를 `first_time_us` 오름차순(동률 시 5-튜플 사전순)으로 정렬하여 이유 `"NAPI_CYCLE_END"`로 방출합니다.

5. **지표 및 진단 산출**:
   - `aggregation_ratio = round(total_rx_packets / max(1, flushed_count), 2)`
   - `packet_reduction_pct = round((1.0 - (flushed_count / max(1, total_rx_packets))) * 100.0, 2)`
   - 방출 이유별 통계 (`OUT_OF_ORDER`, `SPECIAL_FLAG`, `SIZE_LIMIT`, `TIMEOUT`, `NAPI_CYCLE_END`).
   - 이상 징후 진단:
     - `OUT_OF_ORDER` 방출 비율이 전체 방출 패킷의 25% 초과 시: `collapse_detected = True`, `anomalies`에 `"HIGH_OUT_OF_ORDER_RATE_GRO_COLLAPSE"` 추가, 상태는 `"GRO_COLLAPSED"`.
     - 패킷 수가 10개 이상인데 `aggregation_ratio < 2.0`인 경우: `"LOW_AGGREGATION_EFFICIENCY"` 추가, 상태는 `"SUBOPTIMAL_GRO"`.
     - `TIMEOUT` 방출이 발생하고 `aggregation_ratio < 4.0`인 경우: `"FREQUENT_TIMEOUT_FLUSH"` 추가.
     - 정상인 경우 상태는 `"OPTIMAL_GRO_AGGREGATION"`.

### 출력 형식 (Standard Output)
단일 행의 표준 JSON 형식으로 출력합니다.
```json
{
  "flushed_super_packets": [
    {
      "flow_id": "10.0.1.10:49152->10.0.2.20:8080",
      "packet_count": 20,
      "payload_bytes": 29200,
      "wire_bytes": 30280,
      "start_seq": 100000,
      "end_seq": 129200,
      "duration_us": 28.5,
      "flush_reason": "NAPI_CYCLE_END",
      "ack_compressed_count": 0
    }
  ],
  "metrics": {
    "total_rx_packets": 20,
    "total_rx_bytes": 30280,
    "flushed_super_packets_count": 1,
    "aggregation_ratio": 20.0,
    "packet_reduction_pct": 95.0,
    "flush_reasons": {
      "OUT_OF_ORDER": 0,
      "SPECIAL_FLAG": 0,
      "SIZE_LIMIT": 0,
      "TIMEOUT": 0,
      "NAPI_CYCLE_END": 1
    }
  },
  "diagnostics": {
    "status": "OPTIMAL_GRO_AGGREGATION",
    "collapse_detected": false,
    "anomalies": []
  }
}
```

---

## 3. 제약 사항 (Constraints)
- `traffic_events` 길이: $1 \le N \le 20,000$
- 시간값 `time_us`: $0.0 \le time\_us \le 10,000,000.0$ (단조 증가)
- 패킷 크기: $54 \le wire\_len \le 9000$ (표준 MTU 및 점보 프레임 지원)
- 모든 수치 계산은 결정론적이어야 하며 부동소수점 출력은 `round(val, 2)`를 준수합니다.
- Python 3 표준 라이브러리만 사용합니다 (`json`, `sys`).
