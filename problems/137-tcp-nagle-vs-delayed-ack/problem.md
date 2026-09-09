# 패킷 하나 보냈는데 왜 매번 정확히 40ms씩 멈춰요?!: TCP 네이글 알고리즘(Nagle's Algorithm) vs 지연 ACK(Delayed ACK)의 충돌과 TCP_NODELAY

## 1. 실무 시나리오

당신은 사내 고성능 마이크로서비스 간 RPC(Remote Procedure Call) 통신 클라이언트를 개발 중인 백엔드 엔지니어입니다.

모든 서버는 동일한 사내 클라우드 데이터센터에 위치해 있어 네트워크 핑(Ping) 왕복 지연 시간(RTT)은 고작 **2ms**에 불과하며, 서버 CPU 사용률도 1% 미만으로 매우 여유롭습니다.  
그런데 클라이언트가 수백 바이트 크기의 작은 JSON 요청을 보낼 때마다 응답 시간이 **기이하게도 정확히 42ms 또는 84ms**씩 지연되는 기현상이 발생했습니다!

```python
# 문제의 RPC 클라이언트 전송 코드
def send_rpc_request(sock, header, body):
    sock.send(header)  # 100 바이트 (HTTP/RPC 헤더)
    sock.send(body)    # 50 바이트  (JSON 페이로드 바디)
```

네트워크 패킷 캡처 도구(Wireshark / tcpdump)를 분석해 본 결과, 첫 번째 패킷(헤더 100B)이 날아간 뒤 서버로부터 ACK가 오지 않아 클라이언트 커널이 두 번째 패킷(바디 50B)의 송신을 **정확히 40ms 동안 보류(Stall)**하고 있었습니다.  
동시에 서버는 "혹시 다음 패킷이 연달아 오면 묶어서 확인응답(ACK)을 보내야지"라며 **정확히 40ms 동안 ACK 전송을 지연**시키고 있었습니다!

이것이 바로 컴퓨터 네트워킹 역사에서 가장 악명 높은 **"네이글 알고리즘(Nagle's Algorithm)과 지연 확인응답(Delayed ACK)의 충돌"**입니다.

당신은 TCP 스택의 내부 동작을 완벽히 시뮬레이션하여, 송신측의 `TCP_NODELAY` 옵션 및 수신측의 `Delayed ACK` 설정, 그리고 버퍼 통합 전송에 따른 패킷 수, ACK 수, 네이글 스톨 횟수, 타임아웃 횟수 및 최종 통신 완료 시간을 정확하게 계측하는 저지 솔루션을 구현해야 합니다.

---

## 2. TCP 통신 및 알고리즘 시뮬레이션 규칙

### (1) 송신측 동작 규칙 (Sender & Nagle's Algorithm)
- 송신자는 애플리케이션의 `writes` 요청에 따라 데이터를 송신 버퍼(`send_buffer`)에 적재합니다.
- 송신 버퍼에 데이터가 있을 때 세그먼트 전송 가능 여부는 다음 규칙에 따릅니다:
  1. **`tcp_nodelay == True`인 경우**:
     - 네이글 알고리즘이 비활성화됩니다. 미확인 데이터 유무에 상관없이 버퍼에 있는 데이터를 최대 $MSS$ 크기 단위로 **즉시 세그먼트로 분할하여 송신**합니다.
  2. **`tcp_nodelay == False` (네이글 활성화)인 경우**:
     - 현재 네트워크에 아직 수신측 ACK를 받지 못한 미확인 데이터(`in_flight_bytes`)가 **0개**인 경우:
       $	o$ 버퍼 크기에 상관없이 즉시 최대 $MSS$ 크기만큼 세그먼트를 송신합니다.
     - 미확인 데이터(`in_flight_bytes > 0`)가 1바이트라도 남아있는 경우:
       - 송신 버퍼에 모인 데이터가 **$MSS$ 이상**이면: 즉시 $MSS$ 크기 세그먼트 1개를 송신합니다.
       - 송신 버퍼에 모인 데이터가 **$MSS$ 미만**이면: ⛔ **송신을 보류(Nagle Stall)하고 대기**합니다.
       - 이 시점에 `nagle_stalls` 카운터를 1 증가시킵니다 (한 번의 전송 평가 턴에서 1회만 카운트).
- 전송된 세그먼트는 편도 지연 시간 $T_{one\_way} = RTT / 2$ 후에 수신측에 도착합니다.

### (2) 수신측 동작 규칙 (Receiver & Delayed ACK)
- 수신측에 세그먼트가 도착했을 때:
  1. **`delayed_ack_enabled == False` (TCP_QUICKACK 모드)**:
     - 세그먼트가 도착할 때마다 **즉시 단독 ACK를 송신**합니다.
  2. **`delayed_ack_enabled == True` (RFC 1122 지연 ACK 모드)**:
     - 아직 확인응답을 보내지 않은 미확인 세그먼트 개수(`unacked_segments`)를 1 증가시킵니다.
     - **`unacked_segments >= 2`인 경우**:
       $	o$ 즉시 활성화된 지연 ACK 타이머를 취소하고, 2개 세그먼트를 한 번에 확인하는 **누적 ACK(Cumulative ACK)**를 전송합니다 (`quick_acks_sent += 1`).
     - **`unacked_segments == 1`인 경우**:
       $	o$ 즉시 ACK를 보내지 않고, $T_{expire} = T_{current} + delayed\_ack\_timeout\_ms$ 시점에 만료되는 **Delayed ACK 타이머를 시작**합니다.
  3. **Delayed ACK 타이머 만료 시**:
     - 만약 타이머가 취소되지 않고 만료 시점에 도달했으며 아직 확인되지 않은 세그먼트가 있다면:
       $	o$ `delayed_ack_timeouts` 카운터를 1 증가시키고, 현재까지 수신한 모든 바이트를 확인하는 **단독 ACK를 강제 전송**합니다.
- 수신측이 전송한 ACK는 편도 지연 시간 $T_{one\_way} = RTT / 2$ 후에 송신측에 도착합니다.

### (3) 송신측의 ACK 수신 및 통신 종료
- 송신측이 수신측의 ACK를 받으면, 확인된 바이트 수만큼 `in_flight_bytes`를 감소시킵니다.
- 미확인 데이터가 감소했으므로, 송신 버퍼에 대기 중이던 데이터에 대해 네이글 알고리즘 전송 조건을 재평가합니다.
- **최종 통신 완료 시간 (`completion_time_ms`)**:
  - 애플리케이션의 모든 `writes`가 발생하고, 모든 바이트가 전송되었으며, **송신측이 모든 바이트에 대한 최종 ACK를 성공적으로 수신하여 `in_flight_bytes == 0` 및 `send_buffer == 0`이 된 시점**의 타임스탬프입니다. (전송할 데이터가 전혀 없는 경우 0)

### (4) 시스템 진단 판정 (`overall_verdict`)
- `total_bytes_written == 0`: `"NO_DATA_TRANSMITTED"`
- `nagle_stalls > 0` AND `delayed_ack_timeouts > 0`: `"NAGLE_DELAYED_ACK_DEADLOCK"`
- `tcp_nodelay == True` AND `nagle_stalls == 0`: `"OPTIMAL_TCP_NODELAY_STREAMING"`
- `delayed_ack_enabled == False`: `"QUICK_ACK_LOW_LATENCY"`
- `nagle_stalls == 0`: `"FULL_MSS_STREAMING"`
- 그 외: `"NAGLE_STALL_NO_TIMEOUT"`

---

## 3. 입력 형식 (JSON)

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:

```json
{
  "mss": 1460,
  "rtt_ms": 2,
  "delayed_ack_timeout_ms": 40,
  "tcp_nodelay": false,
  "delayed_ack_enabled": true,
  "writes": [
    {"timestamp_ms": 0, "bytes": 100},
    {"timestamp_ms": 0, "bytes": 50}
  ]
}
```

- `mss` (int, 기본값 1460): TCP 최대 세그먼트 크기 (바이트).
- `rtt_ms` (int, 기본값 2): 왕복 전파 지연 시간 (ms, 항상 짝수 정수).
- `delayed_ack_timeout_ms` (int, 기본값 40): 수신측 지연 ACK 타이머 만료 시간 (ms).
- `tcp_nodelay` (bool, 기본값 false): 송신측 `TCP_NODELAY` 옵션 활성화 여부.
- `delayed_ack_enabled` (bool, 기본값 true): 수신측 지연 확인응답(Delayed ACK) 활성화 여부.
- `writes` (list of dict): 애플리케이션의 쓰기 호출 목록. 각 항목은 `timestamp_ms`와 `bytes`를 가짐.

---

## 4. 출력 형식 (JSON)

표준 출력(stdout)으로 다음 구조의 JSON 객체를 인덴트(2칸)를 적용하여 출력합니다:

```json
{
  "summary": {
    "mss": 1460,
    "rtt_ms": 2,
    "delayed_ack_timeout_ms": 40,
    "tcp_nodelay": false,
    "delayed_ack_enabled": true,
    "total_bytes_written": 150,
    "total_packets_sent": 2,
    "total_acks_sent": 2,
    "nagle_stalls": 1,
    "delayed_ack_timeouts": 2,
    "quick_acks_sent": 0,
    "completion_time_ms": 84,
    "overall_verdict": "NAGLE_DELAYED_ACK_DEADLOCK"
  },
  "sample_timeline": [
    {
      "time_ms": 0,
      "event": "PACKET_SENT",
      "bytes": 100,
      "in_flight": 100
    },
    {
      "time_ms": 0,
      "event": "NAGLE_STALL",
      "buffer_bytes": 50,
      "in_flight": 100
    },
    ...
  ]
}
```

- `summary`:
  - `total_bytes_written`: 애플리케이션이 작성한 총 데이터 바이트 수.
  - `total_packets_sent`: 송신측이 보낸 총 데이터 세그먼트 수.
  - `total_acks_sent`: 수신측이 보낸 총 ACK 수.
  - `nagle_stalls`: 네이글 알고리즘으로 인해 송신이 보류된 횟수.
  - `delayed_ack_timeouts`: 수신측 지연 ACK 타이머 만료 횟수.
  - `quick_acks_sent`: 연속 2개 세그먼트 수신으로 지연 없이 즉시 발송된 누적 ACK 횟수.
  - `completion_time_ms`: 최종 ACK 수신 완료 시점 (ms).
  - `overall_verdict`: 시스템 진단 결과 문자열.
- `sample_timeline`: 시뮬레이션 타임라인의 최초 10개 이벤트 목록 (`timeline[:10]`).

---

## 5. 입출력 예시

### 예시 1: 네이글과 지연 ACK의 전형적인 40ms 데드락
**입력:**
```json
{
  "mss": 1460,
  "rtt_ms": 2,
  "delayed_ack_timeout_ms": 40,
  "tcp_nodelay": false,
  "delayed_ack_enabled": true,
  "writes": [
    {"timestamp_ms": 0, "bytes": 100},
    {"timestamp_ms": 0, "bytes": 50}
  ]
}
```

**출력:**
```json
{
  "summary": {
    "mss": 1460,
    "rtt_ms": 2,
    "delayed_ack_timeout_ms": 40,
    "tcp_nodelay": false,
    "delayed_ack_enabled": true,
    "total_bytes_written": 150,
    "total_packets_sent": 2,
    "total_acks_sent": 2,
    "nagle_stalls": 1,
    "delayed_ack_timeouts": 2,
    "quick_acks_sent": 0,
    "completion_time_ms": 84,
    "overall_verdict": "NAGLE_DELAYED_ACK_DEADLOCK"
  },
  "sample_timeline": [
    {
      "time_ms": 0,
      "event": "PACKET_SENT",
      "bytes": 100,
      "in_flight": 100
    },
    {
      "time_ms": 0,
      "event": "NAGLE_STALL",
      "buffer_bytes": 50,
      "in_flight": 100
    },
    {
      "time_ms": 1,
      "event": "PACKET_RECEIVED",
      "bytes": 100,
      "total_received": 100
    },
    {
      "time_ms": 41,
      "event": "ACK_SENT_TIMEOUT",
      "ack_bytes": 100
    },
    {
      "time_ms": 42,
      "event": "ACK_RECEIVED",
      "ack_bytes": 100,
      "in_flight": 0
    },
    {
      "time_ms": 42,
      "event": "PACKET_SENT",
      "bytes": 50,
      "in_flight": 50
    },
    {
      "time_ms": 43,
      "event": "PACKET_RECEIVED",
      "bytes": 50,
      "total_received": 150
    },
    {
      "time_ms": 83,
      "event": "ACK_SENT_TIMEOUT",
      "ack_bytes": 150
    },
    {
      "time_ms": 84,
      "event": "ACK_RECEIVED",
      "ack_bytes": 150,
      "in_flight": 0
    }
  ]
}
```

---

### 예시 2: `TCP_NODELAY` 활성화를 통한 42배 성능 개선
**입력:**
```json
{
  "mss": 1460,
  "rtt_ms": 2,
  "delayed_ack_timeout_ms": 40,
  "tcp_nodelay": true,
  "delayed_ack_enabled": true,
  "writes": [
    {"timestamp_ms": 0, "bytes": 100},
    {"timestamp_ms": 0, "bytes": 50}
  ]
}
```

**출력:**
```json
{
  "summary": {
    "mss": 1460,
    "rtt_ms": 2,
    "delayed_ack_timeout_ms": 40,
    "tcp_nodelay": true,
    "delayed_ack_enabled": true,
    "total_bytes_written": 150,
    "total_packets_sent": 2,
    "total_acks_sent": 1,
    "nagle_stalls": 0,
    "delayed_ack_timeouts": 0,
    "quick_acks_sent": 1,
    "completion_time_ms": 2,
    "overall_verdict": "OPTIMAL_TCP_NODELAY_STREAMING"
  },
  "sample_timeline": [
    {
      "time_ms": 0,
      "event": "PACKET_SENT",
      "bytes": 100,
      "in_flight": 100
    },
    {
      "time_ms": 0,
      "event": "PACKET_SENT",
      "bytes": 50,
      "in_flight": 150
    },
    {
      "time_ms": 1,
      "event": "PACKET_RECEIVED",
      "bytes": 100,
      "total_received": 100
    },
    {
      "time_ms": 1,
      "event": "PACKET_RECEIVED",
      "bytes": 50,
      "total_received": 150
    },
    {
      "time_ms": 1,
      "event": "ACK_SENT_CUMULATIVE",
      "ack_bytes": 150
    },
    {
      "time_ms": 2,
      "event": "ACK_RECEIVED",
      "ack_bytes": 150,
      "in_flight": 0
    }
  ]
}
```
