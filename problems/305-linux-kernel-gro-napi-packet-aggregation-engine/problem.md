# 문제 305: 리눅스 커널 NAPI & GRO(Generic Receive Offload) 슈퍼 패킷 집적 및 플러시 엔진 (Linux Kernel NAPI & GRO Super-Packet Aggregation Engine)

## 문제 배경
초고속 네트워크 인터페이스(10GbE, 40GbE, 100GbE 이상)가 보편화된 클라우드 데이터센터 환경에서, 운영체제 네트워크 스택의 성능 병목은 패킷 처리 횟수(Packet Per Second, PPS)에 크게 좌우됩니다. 이더넷 표준 MTU(1,500 바이트) 환경에서 초당 수백만 개의 패킷이 도착할 경우, 각 패킷마다 커널 `sk_buff` 구조체 할당/해제, 인터럽트 발생, L2/L3/L4 헤더 역직렬화, 방화벽(Netfilter/eBPF) 순회 및 소켓 락 경합이 발생하여 CPU가 패킷 처리에 소진됩니다.

하드웨어 수준에서 패킷을 강제로 합치는 기존 LRO(Large Receive Offload)는 패킷 헤더 정보의 유실, 포워딩/라우팅 환경에서의 손상, ECN(Explicit Congestion Notification) 및 SACK 플래그 왜곡 등의 치명적인 문제를 안고 있었습니다.

이를 해결하기 위해 리눅스 커널(`net/core/dev.c`, `net/ipv4/tcp_offload.c`)은 소프트웨어 레벨에서 프로토콜 의미론을 엄격하게 유지하면서 연속된 수신 패킷을 최대 64KB 크기의 단일 대형 **슈퍼 패킷(Super-Packet)**으로 병합하는 **GRO(Generic Receive Offload)** 엔진과 **NAPI(New API) 폴링 루프**를 설계했습니다.

본 문제에서는 NAPI 수신 큐(`napi_gro_receive`)와 TCP 오프로드 핸들러(`tcp_gro_receive`)의 상태 머신을 정밀하게 시뮬레이션하여, 수신된 이더넷/IP/TCP 패킷 스트림을 실시간으로 집적하고 적절한 사유로 플러시(Flush)하여 상위 계층으로 전달하는 커널 레벨 GRO 슈퍼 패킷 엔진을 구현해야 합니다.

---

## 시스템 동작 규칙 및 엔진 명세

### 1. NAPI 폴링 루프 및 활성 플로우 관리
- 엔진은 NAPI 폴링 구조체에 대응하여 현재 집적 중인 활성 플로우 목록(`held_flows`)을 관리합니다.
- 각 플로우는 고유한 5-튜플 및 VLAN 태그 `(vlan, src_ip, dst_ip, proto, src_port, dst_port)`로 식별됩니다.
- NAPI 구조체는 동시에 최대 `max_flows`개의 플로우만을 보유할 수 있습니다.

### 2. 패킷 수신 시 사전 검사 (Timeout Flush & Control Packet)
새로운 패킷이 도착하면 엔진은 다음 순서로 검사를 수행합니다:
1. **인터벌 만료 검사 (`TIMEOUT`)**:
   - 현재 보유 중인 모든 플로우에 대해, 마지막 관측 시각과 새 패킷 도착 시각의 차이가 `gro_flush_interval_us`를 초과하면(`ts - held.last_seen_us > gro_flush_interval_us`), 해당 플로우를 대기 큐에서 즉시 상위 스택으로 전달(`delivered_packets`)합니다.
   - 만료된 플로우가 여러 개일 경우 `last_seen_us` 오름차순(동일 시각일 경우 flow 키 문자열 오름차순)으로 방출합니다.
2. **비(非) GRO 패킷 및 제어 패킷 검사 (`BYPASS` / `CONTROL_PACKET`)**:
   - 프로토콜이 TCP가 아니거나(예: UDP), TCP 제어 플래그 중 `SYN`, `RST`, `FIN`, `URG` 중 하나라도 포함되어 있거나, 페이로드 길이가 0인 순수 ACK 패킷인 경우:
     - 만약 해당 플로우에 이미 보류 중인 집적 패킷이 있다면, 기존 집적 패킷을 즉시 사유 `"CONTROL_PACKET"`으로 상위 스택에 방출합니다.
     - 현재 입력 패킷은 GRO 집적 없이 즉시 1개 세그먼트(`gso_segs = 1`)로 상위 스택에 방출합니다. (제어 플래그가 있으면 사유 `"CONTROL_PACKET"`, 단순 비-TCP/순수ACK이면 `"BYPASS"`).

### 3. GRO 병합 유효성 검증 (Eligibility Check)
TCP 데이터 패킷에 대해 동일 플로우의 보류 패킷이 존재하는 경우, 아래 조건을 모두 만족해야만 슈퍼 패킷으로 병합(`Coalesce`)될 수 있습니다:
1. **L2/L3 헤더 일치**:
   - 송수신 MAC 주소가 기존 패킷과 동일해야 함.
   - IP ToS(Type of Service) 필드가 동일해야 함.
   - IP DF(Don't Fragment) 비트가 False인 경우: `ip.id == held.last_ip_id + 1` (연속된 식별자여야 함). DF가 True인 경우 ID 검사는 통과함.
2. **L4 헤더 및 시퀀스 무결성**:
   - 허용 플래그: `ACK` 및 `PSH`만 허용.
   - 연속 시퀀스 번호: `tcp.seq == held.expected_seq` (단, `expected_seq = held.last_seq + held.last_payload_len`).
   - 단조 증가 ACK 번호: `tcp.ack_seq >= held.ack_seq`.
3. **용량 한계**:
   - 병합 후 총 페이로드 크기가 `max_gro_size` 이하: `held.total_payload_len + payload_len <= max_gro_size`.
   - 병합 후 세그먼트 개수가 `max_gro_segs` 이하: `held.gso_segs + 1 <= max_gro_segs`.

### 4. 집적 및 플러시 (Coalescing & Flush)
- **병합 성공 시**:
  - `held.total_payload_len += payload_len`
  - `held.gso_segs += 1`
  - `held.expected_seq += payload_len`
  - `held.ack_seq = max(held.ack_seq, tcp.ack_seq)`
  - PSH 플래그가 들어왔다면 `held.flags`에 추가.
  - 만약 용량 한계에 도달(`total_payload_len >= max_gro_size` 또는 `gso_segs >= max_gro_segs`)했다면, 즉시 사유 `"MAX_SIZE"` 또는 `"MAX_SEGS"`로 방출합니다.
- **병합 실패 시**:
  - 기존 보류 패킷을 플러시합니다. 플러시 사유는 시퀀스 불일치 시 `"OUT_OF_ORDER"`, 크기 초과 시 `"MAX_SIZE"`, 세그먼트 초과 시 `"MAX_SEGS"`입니다.
  - 그 후 현재 패킷을 새로운 플로우의 시작점으로 등록합니다.
- **플로우 테이블 포화 (`TABLE_FULL`)**:
  - 신규 플로우 등록 시 활성 플로우 개수가 `max_flows`에 도달한 상태라면, 가장 오래 참조되지 않은 플로우(LRU: `last_seen_us`가 가장 작은 플로우)를 사유 `"TABLE_FULL"`로 방출합니다.

### 5. 폴링 배치 종료 플러시 (`POLL_END`)
- 모든 수신 패킷 이벤트 처리가 끝난 후, 여전히 대기 중인 모든 활성 플로우를 `last_seen_us` 오름차순으로 상위 계층에 최종 방출합니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "max_gro_size": 65536,
    "max_gro_segs": 64,
    "max_flows": 8,
    "gro_flush_interval_us": 100
  },
  "packets": [
    {
      "timestamp_us": 10,
      "eth": {
        "src_mac": "52:54:00:12:34:56",
        "dst_mac": "52:54:00:ab:cd:ef",
        "vlan": null
      },
      "ip": {
        "src_ip": "192.168.1.10",
        "dst_ip": "192.168.1.20",
        "proto": "TCP",
        "tos": 0,
        "df": true,
        "id": 1001
      },
      "tcp": {
        "src_port": 8080,
        "dst_port": 45678,
        "seq": 1000,
        "ack_seq": 500,
        "flags": ["ACK"],
        "window": 65535,
        "tsval": 10
      },
      "payload_len": 1460
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 단일 행으로 출력합니다:

```json
{
  "summary": {
    "total_received_packets": 4,
    "total_delivered_packets": 1,
    "total_gro_coalesced": 3,
    "aggregation_ratio": 4.0,
    "max_super_packet_bytes": 5840,
    "max_super_packet_segs": 4
  },
  "delivered_packets": [
    {
      "flow_id": "192.168.1.10:8080->192.168.1.20:45678",
      "start_seq": 1000,
      "end_seq": 6840,
      "ack_seq": 500,
      "gso_segs": 4,
      "gso_size": 1460,
      "total_payload_len": 5840,
      "flags": ["ACK"],
      "flush_reason": "MAX_SEGS"
    }
  ]
}
```

---

## 제약 사항
- `1 <= len(packets) <= 2,000`
- `1,000 <= max_gro_size <= 65536`
- `2 <= max_gro_segs <= 64`
- `1 <= max_flows <= 64`
- `flags` 배열은 사전순(`sorted`)으로 정렬되어야 합니다.
- `aggregation_ratio`는 소수점 넷째 자리까지 반올림합니다(`round(..., 4)`).
