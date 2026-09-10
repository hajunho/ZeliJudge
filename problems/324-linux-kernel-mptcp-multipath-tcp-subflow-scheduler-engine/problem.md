# Linux Kernel MPTCP: 다중 경로 TCP 서브플로우 패킷 스케줄러 및 무중단 세션 복구 엔진 (Multipath TCP Subflow Scheduler Engine)

## 문제 개요

스마트폰, 자율주행 차량, 엣지 컴퓨팅 노드, 멀티홈(Multi-homed) 데이터센터 서버는 Wi-Fi, 5G/LTE 셀룰러, 유선 이더넷, 위성 링크 등 복수의 네트워크 인터페이스(NIC)를 동시에 탑재하고 있습니다. 그러나 전통적인 TCP(RFC 793)는 **단일 IP-포트 쌍(4-Tuple)**에 단단히 결속되어 있습니다. 따라서 사용자가 엘리베이터를 타거나 기지국 경계를 넘어가 Wi-Fi 연결이 끊어지면, 진행 중이던 대용량 다운로드, 화상회의, 스트리밍 세션의 TCP 소켓이 즉시 파괴(`ECONNRESET`)되고 처음부터 다시 연결해야 했습니다.

이 근본적 한계를 극복하기 위해 IETF(RFC 8684 / RFC 6824)와 리눅스 커널 커뮤니티(`net/mptcp/`)는 **MPTCP (Multipath TCP)** 표준을 리눅스 5.6+ 커널에 정식 통합했습니다:
1. **이중 시퀀스 공간 매핑 (Dual Sequence Space & DSS)**:
   - 애플리케이션 계층은 단일한 **64비트 데이터 시퀀스 번호(DSN: Data Sequence Number)**로 구성된 가상 메타 소켓(Meta-Socket)을 바라봅니다.
   - 각 물리 네트워크 경로는 독립적인 **32비트 서브플로우 시퀀스 번호(SSN: Subflow Sequence Number)**와 자체 혼잡 제어 창(`cwnd`)을 가진 독립 TCP 연결로 작동합니다.
   - TCP 옵션 헤더의 **DSS(Data Sequence Signal)**가 $(DSN, SSN, length)$ 매핑을 동적으로 중계합니다.
2. **패킷 스케줄러(Packet Scheduler: `net/mptcp/sched.c`)**:
   - `minrtt`: 가용 윈도우($cwnd - in\_flight \ge segment$)가 존재하는 활성 서브플로우 중 최저 지연시간($srtt$) 경로로 패킷을 우선 조향합니다. 혼잡 시 높은 RTT 경로로 자동 스필오버됩니다.
   - `redundant`: 초고신뢰 저지연 통신(URLLC)을 위해 모든 가용 경로에 복제 패킷을 동시 전송하여 패킷 손실률 0%를 달성합니다.
   - `backup`: 모든 일반 활성 경로가 포화되었을 때에만 고비용/위성 백업 경로를 가동합니다.
3. **무중단 경로 페일오버(Break-Before-Make Recovery)**:
   - 특정 서브플로우(예: Wi-Fi)가 단절되더라도, 해당 경로에 실려 있던 미확인(Unacknowledged) DSN 세그먼트들을 건강한 다른 서브플로우(5G)로 즉시 재스케줄링하여 소켓 리셋 없이 100% 무손실 복구합니다.
4. **아웃오브오더 메타 소켓 재조립 큐 (Out-of-Order Reassembly)**:
   - 서로 다른 RTT를 가진 경로들에서 도착한 불규칙한 세그먼트들을 DSN 시퀀스 순서대로 버퍼링하고, 시퀀스 갭이 메워지는 즉시 상위 애플리케이션 스트림으로 연속 전달합니다.

당신은 리눅스 커널 네트워크 서브시스템 엔지니어로서, `net/mptcp/`의 핵심 동작을 결정론적으로 시뮬레이션하는 **MPTCP 서브플로우 스케줄러 & 상태 복구 엔진**을 구현해야 합니다.

---

## 아키텍처 및 시스템 흐름도

```
+-----------------------------------------------------------------------------------+
|                        Linux Kernel MPTCP Meta-Socket                             |
|                        (net/mptcp/protocol.c, sched.c)                            |
+-----------------------------------------------------------------------------------+
                                          |
                      Application Stream: "Hello_World!..."
                                          |
             [ 64-bit Data Sequence Space: DSN (next_tx_dsn, una_dsn) ]
                                          |
                        +-----------------+-----------------+
                        | MPTCP Packet Scheduler: 'minrtt'  |
                        +-----------------+-----------------+
                                          |
               Check: status == "ACTIVE" & (cwnd - in_flight >= MSS)
                         Sort Candidates by srtt_ms ASC
                                          |
             +----------------------------+----------------------------+
             |                                                         |
     [ Subflow 0: Wi-Fi ]                                      [ Subflow 1: 5G/LTE ]
     - Path RTT: 15ms                                          - Path RTT: 40ms
     - 32-bit SSN: 1000..                                      - 32-bit SSN: 5000..
     - DSS Mapping: (DSN_0, SSN_0, len)                        - DSS Mapping: (DSN_1, SSN_1, len)
             |                                                         |
             +----------------------------+----------------------------+
                                          |
                          [ Subflow ACKs & Data ACKs ]
                 - Subflow ACK: releases subflow.in_flight
                 - Data ACK: retires DSS mapping, advances una_dsn
                                          |
                    [ Network Disruption / Path Failure ]
           Wi-Fi status -> "FAILED" (Failover Retransmission)
           Reschedule unacked DSN mappings to Subflow 1 (5G)
                                          |
                [ Peer Receiver: DSN Reassembly Queue ]
           Buffer out-of-order DSN segments -> Deliver contiguous stream
```

---

## 상세 기술 사양

### 1. 서브플로우(MPTCPSubflow) 모델
- `subflow_id`: 고유 식별자 문자열 (예: `"wifi"`, `"cellular_5g"`)
- `status`: `"ACTIVE"`, `"BACKUP"`, `"FAILED"` 중 하나
- `is_backup`: 불리언 (true이면 초기 상태 `"BACKUP"`, false이면 `"ACTIVE"`)
- `srtt_ms`: 부동소수점 (Smoothed Round-Trip Time 밀리초)
- `cwnd`: 정수 (혼잡 제어 윈도우 크기, 바이트 단위)
- `in_flight`: 정수 (현재 네트워크 상에 떠 있는 미확인 전송 바이트 수)
- `available_window`: $status 
eq 	ext{"FAILED"}$일 때 $\max(0, cwnd - in\_flight)$, 실패 상태면 0.
- `tx_ssn`, `rx_ssn`: 각 경로별 32비트 TCP 서브플로우 시퀀스 번호 (기본 1000 시작)
- 전송 통계: `tx_bytes`, `tx_packets`, `rx_bytes`, `retransmissions`

### 2. 메타 소켓 및 DSN 시퀀스 관리
- `token`: 32비트 16진수 토큰 문자열
- `scheduler`: `"minrtt"`, `"redundant"`, `"round_robin"`
- `mss`: 세그먼트 최대 크기 (바이트 단위, 기본 1400)
- `next_tx_dsn`: 64비트 단조 증가 전송 DSN
- `una_dsn`: 가장 오래된 미확인 DSN (Data ACK 수신 시 전진)
- `rx_next_dsn`: 수신 측에서 기다리는 연속된 DSN 시퀀스 번호
- `in_flight_mappings`: 전송된 각 세그먼트의 DSS 매핑 리스트:
  `{"dsn": dsn, "ssn": ssn, "length": length, "subflow_id": subflow_id, "data": data}`

### 3. 패킷 전송 및 스케줄러 로직 (`SEND_DATA`)
- 입력된 UTF-8 문자열 페이로드를 바이트 단위로 분할합니다.
- 오프셋 단위로 $\min(mss, remaining)$ 크기의 세그먼트를 추출합니다:
  - **`minrtt` 스케줄러**:
    1. 가용 윈도우가 세그먼트 크기 이상인 `ACTIVE` 서브플로우들을 탐색합니다.
    2. 없다면 가용 윈도우가 충분한 `BACKUP` 서브플로우들을 탐색합니다.
    3. 후보군이 비어있다면(모든 경로 윈도우 포화) 전송을 중단하고 루프를 빠져나옵니다.
    4. 후보군 중 `srtt_ms` 오름차순(동점 시 `subflow_id` 오름차순)으로 최적 서브플로우를 선택합니다.
  - **`redundant` 스케줄러**:
    - 가용 윈도우가 충분한 모든 `ACTIVE` 및 `BACKUP` 서브플로우에 동일한 DSN의 복제 세그먼트를 동시 전송합니다. (하나도 없으면 중단).
  - **`round_robin` 스케줄러**:
    - 활성 서브플로우들을 ID 오름차순으로 순환 선택합니다.
- 선택된 서브플로우에 DSS 매핑을 기록하고, $subflow.in\_flight \leftarrow in\_flight + len$, $subflow.tx\_ssn \leftarrow tx\_ssn + len$, $next\_tx\_dsn \leftarrow next\_tx\_dsn + len$ 갱신합니다.

### 4. ACK 처리
- `SUBFLOW_ACK`: 특정 서브플로우의 `in_flight`를 $\max(0, in\_flight - bytes\_acked)$로 해제합니다.
- `DATA_ACK`: `ack_dsn`까지 완전히 전송된 DSS 매핑($dsn + length \le ack\_dsn$)을 `in_flight_mappings`에서 은퇴(제거)시키고 $una\_dsn \leftarrow ack\_dsn$으로 전진합니다.

### 5. 무중단 페일오버 (`FAILOVER_RETRANSMIT`)
- 지정된 `failed_subflow_id`의 상태를 `"FAILED"`로 변경하고 `in_flight`를 0으로 리셋합니다.
- 해당 서브플로우에 할당되어 있던 미확인(`in_flight_mappings`) 세그먼트들을 순회하며, 건강한 다른 가용 서브플로우로 재스케줄링합니다:
  - 새 서브플로우를 선택하고 $mapping.subflow\_id \leftarrow new\_sf.subflow\_id$, $mapping.ssn \leftarrow new\_sf.tx\_ssn$ 재바인딩.
  - 새 서브플로우의 $in\_flight, tx\_ssn, tx\_bytes, tx\_packets, retransmissions$를 갱신합니다.

### 6. 수신 및 아웃오브오더 재조립 (`RECEIVE_PACKET`)
- 패킷 수신 시 해당 서브플로우의 $rx\_ssn$과 $rx\_bytes$를 갱신합니다.
- $dsn \ge rx\_next\_dsn$이면 재조립 버퍼(`rx_reorder_queue[dsn]`)에 저장합니다.
- $rx\_next\_dsn$부터 연속된 세그먼트가 버퍼에 존재하는 동안 루프를 돌며, 상위 `delivered_stream`에 데이터를 추가하고 $rx\_next\_dsn \leftarrow rx\_next\_dsn + length$로 전진시킵니다.

---

## 입력 및 출력 형식

### 입력 JSON 스키마
```json
{
  "config": {
    "token": "0x5a1b2c3d",
    "scheduler": "minrtt",
    "mss": 1000,
    "initial_dsn": 1000000,
    "initial_rx_dsn": 5000000,
    "subflows": [
      {
        "subflow_id": "wifi",
        "srtt_ms": 15.0,
        "cwnd": 5000,
        "is_backup": false
      },
      {
        "subflow_id": "cellular_5g",
        "srtt_ms": 35.0,
        "cwnd": 8000,
        "is_backup": false
      }
    ]
  },
  "commands": [
    {
      "type": "SEND_DATA",
      "payload": "Application payload string..."
    },
    {
      "type": "SUBFLOW_ACK",
      "subflow_id": "wifi",
      "bytes_acked": 2000
    },
    {
      "type": "DATA_ACK",
      "ack_dsn": 1002000
    },
    {
      "type": "FAILOVER_RETRANSMIT",
      "failed_subflow_id": "wifi"
    },
    {
      "type": "RECEIVE_PACKET",
      "subflow_id": "cellular_5g",
      "ssn": 5000,
      "dsn": 5000000,
      "payload": "Delivered_chunk"
    },
    {
      "type": "QUERY_STATE"
    }
  ]
}
```

### 출력 JSON 스키마
```json
{
  "token": "0x5a1b2c3d",
  "scheduler": "minrtt",
  "una_dsn": 1002000,
  "next_tx_dsn": 1003000,
  "rx_next_dsn": 5000015,
  "delivered_stream": "Delivered_chunk",
  "total_tx_bytes": 3000,
  "total_rx_bytes": 15,
  "total_retransmissions": 1,
  "in_flight_mappings_count": 1,
  "subflows": {
    "cellular_5g": { ... },
    "wifi": { ... }
  },
  "event_logs": [ ... ]
}
```
