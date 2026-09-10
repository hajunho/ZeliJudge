# #373 - 리눅스 커널 TCP Small Queues (TSQ) & 안티 버퍼블로트 페이싱 엔진

## 📖 문제 배경과 시스템 아키텍처

> *"전통적인 TCP 스택은 혼잡 윈도우(cwnd)가 허용하는 한 모든 세그먼트를 큐디스크(qdisc)와 디바이스 드라이버의 전송 링 버퍼(TX Ring)로 한꺼번에 쏟아부었습니다. 이는 전송 지연(RTT)을 수백 밀리초로 치솟게 만드는 버퍼블로트(Bufferbloat)의 주범이었습니다. TSQ(TCP Small Queues)는 소켓별로 디바이스 계층에 계류될 수 있는 미완료 바이트를 2개의 skb 수준(또는 동적 한도)으로 극단적으로 억제함으로써, 초저지연과 고처리량을 동시에 달성합니다."*  
> — **Eric Dumazet, Linux Kernel Network Subsystem Maintainer**

고속 네트워크 환경에서 TCP 송신 성능을 갉아먹는 가장 치명적인 병목 중 하나는 **버퍼블로트(Bufferbloat)** 현상입니다. 소켓 버퍼에서 생성된 패킷들이 네트워크 카드(NIC) 드라이버의 링 버퍼와 패킷 스케줄러(Qdisc) 큐에 과도하게 쌓이면, 패킷이 케이블로 송출되기도 전에 큐 내부에서 막대한 지연(Queueing Delay)이 발생합니다. 이는 RTT를 폭증시키고, 대화형(Interactive) 트래픽의 반응성을 파괴하며, 패킷 손실 시 재전송 타이머(RTO)를 지연시킵니다.

리눅스 커널 3.6부터 도입된 **TCP Small Queues (TSQ / `net/ipv4/tcp_output.c`, `include/net/sock.h`)**는 이 문제를 해결하기 위해 **소켓당 드라이버 계층 미완료 패킷 메모리(`sk->sk_wmem_alloc`)의 상한선(`sysctl_tcp_limit_output_bytes`)**을 강제합니다:

```
+-------------------------------------------------------------------------------+
|                      리눅스 커널 TSQ & BQL 데이터 흐름                        |
+-------------------------------------------------------------------------------+
  [User Application]
         │ write()
         ▼
  [TCP Socket Send Buffer] (send_buffer)
         │
         ├───► TSQ 검사: (sk_wmem_alloc + skb_truesize > tsq_limit_bytes) ?
         │        ├─ YES: TSQ_THROTTLED 플래그 설정 -> 소켓 전송 일시 정지 (Wait)
         │        └─ NO : 통과
         │
         ├───► Socket Pacing 검사: (current_time < pacing_next_time) ?
         │        ├─ YES: 페이싱 딜레이 대기
         │        └─ NO : 통과
         │
         ├───► BQL (Byte Queue Limits) 검사: (nic_in_flight >= bql_limit) ?
         │        ├─ YES: NIC TX 링 포화 -> 대기
         │        └─ NO : 통과
         ▼
  [NIC Driver Transmit Ring & Wire Transmission]
         │
         │ (하드웨어 직렬화 및 패킷 송출 완료 인터럽트 / TX Softirq)
         ▼
  [tcp_wfree() 호출]
         │
         ├───► sk->sk_wmem_alloc -= skb_truesize
         │
         └───► if (sk->tsq_throttled && sk->sk_wmem_alloc < tsq_limit_bytes):
                   TSQ_THROTTLED 해제 -> tcp_tsq_handler() -> 송신 파이프라인 재개!
```

### 핵심 메커니즘
1. **소켓 송신 제어 (`tcp_write_xmit`)**:
   - 패킷을 송출하기 전 소켓이 현재 드라이버/Qdisc에 계류 중인 총 바이트 메모리 `wmem_alloc`에 전송할 패킷의 `skb_truesize`를 더했을 때 `tsq_limit_bytes`를 초과하면, 소켓에 `TSQ_THROTTLED` 비트를 설정하고 송신을 중단합니다.
2. **소켓 페이싱 (`sk_pacing_rate`)**:
   - 패킷을 전송할 때마다 다음 패킷 전송 가능 시점(`pacing_next_ns`)을 $\Delta t = \frac{\text{packet\_bytes} \times 10^9}{\text{pacing\_rate\_bps}}$ 만큼 갱신하여 패킷 간 간격을 균일하게 분산합니다.
3. **디바이스 완료 인터럽트와 `tcp_wfree()`**:
   - NIC 하드웨어가 패킷을 실제 선로(Wire)로 송출 완료하면 `tcp_wfree()`가 호출되어 `wmem_alloc`에서 해당 패킷의 `skb_truesize`를 차감합니다.
   - 이때 소켓이 `TSQ_THROTTLED` 상태이고 차감 후 `wmem_alloc < tsq_limit_bytes`가 되면, 스로틀링이 즉시 해제되어 송신 큐가 다시 깨어납니다.
4. **BQL (Byte Queue Limits)**:
   - NIC 드라이버 링 버퍼에 적재된 총 바이트(`nic_in_flight_bytes`)가 `bql_limit_bytes` 이상이면 하드웨어 버퍼 오버플로우를 막기 위해 모든 소켓의 송출이 차단됩니다.

---

## 📥 입력 형식 (Input Specification)

입력은 표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "tsq_limit_bytes": 16384,
    "bql_limit_bytes": 32768,
    "mss": 1460,
    "skb_truesize": 2048,
    "nic_rate_bps": 10000000
  },
  "sockets": [
    {
      "id": "sock1",
      "pacing_rate_bps": 100000000,
      "initial_send_buffer": 65536
    }
  ],
  "operations": [
    {
      "type": "ADVANCE_TIME",
      "to_time_ns": 1000000
    }
  ]
}
```

### 제약조건 및 파라미터 규칙:
1. `config`:
   - `tsq_limit_bytes`: 소켓별 TSQ 제한 바이트 (기본값 `131072`, 양의 정수).
   - `bql_limit_bytes`: NIC 드라이버 TX 링 BQL 바이트 한계 (기본값 `65536`, 양의 정수).
   - `mss`: TCP 세그먼트 최대 크기 (기본값 `1460`, 패킷당 페이로드 바이트).
   - `skb_truesize`: 커널 `sk_buff` 구조체 및 오버헤드를 포함한 메모리 할당 크기 (기본값 `2048`).
   - `nic_rate_bps`: NIC 선로 대역폭 (Bytes per second, 기본값 `125000000` = 1Gbps).
2. `sockets`:
   - `id`: 소켓 식별자 문자열.
   - `pacing_rate_bps`: 초당 송출 페이싱 속도 (Bytes per second, 기본값 `50000000`).
   - `initial_send_buffer`: 시뮬레이션 시작 시 소켓 버퍼 바이트 (기본값 `0`).
3. `operations`: 시간 순으로 주어지는 시뮬레이션 제어 이벤트 리스트:
   - `APP_WRITE`:
     - 파라미터: `socket` (소켓 ID), `bytes` (추가할 전송 바이트), `time_ns` (해당 쓰기가 발생한 시각, 나노초).
     - 동작: `time_ns`까지 시뮬레이션 시간을 전진시키고, 소켓의 `send_buffer`에 `bytes`를 추가한 후 즉시 송출 가능한 패킷을 전송합니다.
   - `SET_PACING_RATE`:
     - 파라미터: `socket` (소켓 ID), `pacing_rate_bps` (새 페이싱 속도), `time_ns` (변경 시각, 나노초).
     - 동작: `time_ns`까지 시뮬레이션 시간을 전진시키고, 해당 소켓의 `pacing_rate_bps`를 즉시 갱신합니다.
   - `ADVANCE_TIME`:
     - 파라미터: `to_time_ns` (도달할 목표 시각, 나노초).
     - 동작: 현재 시간부터 `to_time_ns`까지 이산 사건(NIC 송출 완료, 페이싱 대기 해제 등)을 순차적으로 처리하며 전진합니다.

### 패킷 송출 및 스케줄링 세부 규칙:
1. 매 나노초 시점(또는 이벤트 발생 시점)에서 전송 대기 중인 소켓들을 `sockets` 입력 순서대로 순회하며 검사합니다.
2. 소켓 $S$가 송출하기 위한 조건:
   - `sock.send_buffer > 0`
   - `not sock.tsq_throttled`
   - `nic_in_flight_bytes < bql_limit_bytes`
   - `current_time_ns >= sock.pacing_next_ns`
3. 패킷 크기 $L = \min(\text{mss}, \text{sock.send\_buffer})$.
4. TSQ 검사:
   - 만약 $\text{sock.wmem\_alloc} + \text{skb\_truesize} > \text{tsq\_limit\_bytes}$ 이면:
     - `sock.tsq_throttled = True` 설정.
     - `sock.throttle_count += 1`.
     - `sock.throttle_start_ns = current_time_ns`.
     - 전송 중단하고 다음 소켓으로 넘어감.
5. 송출 실행:
   - `sock.send_buffer -= L`
   - `sock.wmem_alloc += skb_truesize`
   - `sock.packets_sent += 1`, `sock.bytes_sent += L`
   - 다음 페이싱 시점: $\text{pacing\_next\_ns} = \text{current\_time\_ns} + \lfloor \frac{L \times 10^9}{\text{sock.pacing\_rate\_bps}} \rfloor$
   - NIC 와이어 전송 소요 시간: $\text{wire\_tx\_ns} = \lfloor \frac{L \times 10^9}{\text{nic\_rate\_bps}} \rfloor$
   - NIC 하드웨어 전송 완료 시각: $\text{comp\_ns} = \max(\text{current\_time\_ns}, \text{nic\_busy\_until\_ns}) + \text{wire\_tx\_ns}$
   - $\text{nic\_busy\_until\_ns} = \text{comp\_ns}$
   - $\text{nic\_in\_flight\_bytes} += L$
   - NIC 전송 큐에 패킷 등록.
6. 완료 처리 (`tcp_wfree`):
   - $\text{current\_time\_ns} \ge \text{comp\_ns}$가 되면 NIC 큐에서 패킷 제거.
   - $\text{nic\_in\_flight\_bytes} = \max(0, \text{nic\_in\_flight\_bytes} - L)$
   - $\text{sock.wmem\_alloc} = \max(0, \text{sock.wmem\_alloc} - \text{skb\_truesize})$
   - 만약 $\text{sock.tsq\_throttled}$이고 $\text{sock.wmem\_alloc} < \text{tsq\_limit\_bytes}$이면:
     - $\text{sock.tsq\_throttled} = \text{False}$
     - 지속 시간: $\Delta D = \text{comp\_ns} - \text{sock.throttle\_start\_ns}$
     - $\text{sock.total\_throttle\_duration\_ns} += \Delta D$
     - $\text{sock.throttle\_start\_ns} = \text{None}$

---

## 📤 출력 형식 (Output Specification)

시뮬레이션 종료 시각의 커널 네트워킹 상태를 압축 JSON(`separators=(',', ':')`, `ensure_ascii=False`)으로 출력합니다:

```json
{
  "final_time_ns": 1000000,
  "nic_in_flight_bytes": 11680,
  "nic_queued_packets": 8,
  "sockets": {
    "sock1": {
      "packets_sent": 14,
      "bytes_sent": 20440,
      "remaining_buffer": 45096,
      "wmem_alloc": 16384,
      "tsq_throttled": true,
      "throttle_count": 7,
      "total_throttle_duration_ns": 795600
    }
  },
  "events_count": 13
}
```

*참고*: 시뮬레이션 종료 시점에 아직 `tsq_throttled`가 풀리지 않은 상태라면, 종료 시점까지의 스로틀 지속 시간($\text{final\_time\_ns} - \text{throttle\_start\_ns}$)을 `total_throttle_duration_ns`에 합산합니다.

---

## 🎯 채점 기준 및 엣지 케이스

1. 정확성 100%: 8개 모든 테스트케이스의 수치 및 플래그가 완벽히 일치해야 합니다.
2. 부동소수점 오차 방지: 나노초 계산은 정수 나눗셈 `int((L * 1_000_000_000) / rate)`를 사용합니다.
3. 결정론적 이벤트 루프: 다중 소켓 간 스케줄링 시 정의된 순서와 조건을 엄격히 준수해야 합니다.
