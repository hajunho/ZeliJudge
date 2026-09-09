# 수신 버퍼 꽉 찼을 뿐인데 왜 영구 교착 상태에 빠져요?!: TCP Zero Window 교착 상태와 Persist Timer 탐침 vs 바보 윈도우 증후군 (SWS) 방어

## 1. 장애 현장: 새벽 2시, 배치 업로드 중 영구 정지(Hang)되는 서버의 비밀

대규모 빅데이터 파이프라인에서 수 기가바이트의 로그 데이터를 수신 저장소로 전송하는 고성능 스트리밍 서비스에서 기이한 현상이 보고되었습니다.

데이터 전송이 한창 진행되던 중, 네트워크 연결이 끊어진 것도 아니고(`ESTABLISHED` 유지), CPU나 메모리가 부족한 것도 아닌데, **데이터 전송이 그 자리에서 완전히 멈춰버린 채 수십 분간 영구 무응답(Hang)**에 빠지는 현상이 빈번하게 일어났습니다.

네트워크 패킷 덤프(`tcpdump`)를 확인한 결과, 충격적인 교착 상태의 진실이 드러났습니다:
```
14:02:01.100 Sender -> Receiver: [PSH, ACK] Seq=10001, Ack=1, Len=1000
14:02:01.110 Receiver -> Sender: [ACK] Seq=1, Ack=11001, Win=0 (Zero Window!)
           ... (Receiver 측 애플리케이션이 디스크 쓰기 병목으로 버퍼를 비우지 못함) ...
14:02:01.300 Receiver -> Sender: [ACK] Seq=1, Ack=11001, Win=2000 (Window Update) [PACKET DROP!]
           ... (스위치 순간 버퍼 오버플로우로 Window Update ACK 유실!) ...
14:02:01.310 ~ 14:15:00 (영구 침묵):
  - Sender: "Receiver가 Win=0이라고 했으니, 창문 열어줄 때까지 얌전히 기다려야지."
  - Receiver: "아까 Win=2000이라고 알려줬는데, Sender 녀석 왜 아무 데이터도 안 보내지?"
  - Result: 양쪽 모두 마냥 대기하며 영구 데드락(Deadlock)!
```

설상가상으로, 어떤 연결에서는 수신자가 버퍼를 10바이트씩 비울 때마다 10바이트짜리 윈도우 갱신을 보내고, 송신자가 40바이트 헤더를 붙여 10바이트짜리 패킷을 쏘아대는 **바보 윈도우 증후군(Silly Window Syndrome, SWS)**이 발생해 기가비트 네트워크가 80% 이상의 헤더 오버헤드로 마비되고 있었습니다!

RFC 793 / RFC 813 / RFC 1122 표준에 규정된 **TCP 슬라이딩 윈도우 흐름 제어, 지속 타이머(Persist Timer)와 제로 윈도우 탐침(ZWP), 그리고 클라크(Clark) & RFC 1122 SWS 회피 알고리즘**을 정밀하게 시뮬레이션하는 네트워크 엔진을 구현하여 시스템을 구원하세요!

---

## 2. 요구 사항 및 시뮬레이션 명세

입력으로 주어지는 TCP 구성 파라미터와 시간순 타임라인 이벤트(`timeline_events`)를 이산 사건 시뮬레이션(Discrete Event Simulation)으로 처리하여 최종 메트릭(`metrics`)과 타임라인(`sample_timeline`)을 출력해야 합니다.

### 2.1 주요 설정 파라미터
- `mss`: 최대 세그먼트 크기 (기본값: 1000 바이트)
- `rcv_buff_size`: 수신자의 물리 수신 소켓 버퍼 크기 (기본값: 4000 바이트)
- `rtt_ticks`: 왕복 시간 (단방향 전송 지연 = `rtt_ticks // 2`)
- `initial_rto`: 지속 타이머의 초기 만료 시간 (기본값: 200 ticks)
- `max_persist_timeout`: 지속 타이머 지수 백오프의 상한선 (기본값: 1600 ticks)
- `clark_enabled`: 수신자 SWS 방지 (클라크 알고리즘) 활성화 여부 (`True` / `False`)
- `sender_sws_enabled`: 송신자 SWS 방지 (RFC 1122 알고리즘) 활성화 여부 (`True` / `False`)

### 2.2 패킷 헤더 오버헤드 규정
- 모든 TCP/IP 패킷(데이터 세그먼트, ACK, 윈도우 갱신, 제로 윈도우 탐침)은 **40바이트의 고정 헤더(IPv4 20B + TCP 20B)**를 갖습니다.
- 총 와이어 전송 바이트 = `total_payload_bytes_sent + total_header_bytes_sent`
- 헤더 오버헤드 비율 = `total_header_bytes_sent / total_wire_bytes` (소수점 4자리 반올림)

### 2.3 송신자 상태 머신 및 전송 규칙
1. **슬라이딩 윈도우 전송**:
   - 가용 윈도우 `usable_wnd = snd_wnd - (snd_nxt - snd_una)`
   - 전송 가능 데이터량 = `min(unsent, usable_wnd)`
   - 단, `sender_sws_enabled=True`인 경우 송신자 SWS 회피 규칙을 만족하지 못하면 세그먼트를 쪼개서 보내지 않고 전송을 유예(`SWS_AVOIDANCE_STALL`)합니다.
2. **지속 상태(Persist State)**:
   - 미전송 데이터(`unsent > 0`)가 존재하고 인플라이트 데이터가 없는데 `snd_wnd == 0`이 되면 송신자는 지속 상태에 진입합니다.
   - 지속 타이머가 만료되면 1바이트의 **제로 윈도우 탐침(ZWP)**을 전송합니다 (`zero_window_probes_sent += 1`).
   - 수신자로부터 유효한 윈도우(`rcv_wnd > 0`) ACK가 도착하면 지속 상태를 종료합니다. 만약 유실된 Window Update가 ZWP 탐침으로 인해 복구된 것이라면 `deadlocks_prevented_by_probe += 1`을 기록합니다.
   - 윈도우가 여전히 0이면 타이머를 2배로 지수 백오프(`persist_timer_backoffs += 1`)합니다 (최대 `max_persist_timeout`).

### 2.4 수신자 상태 머신 및 광고 규칙
1. **윈도우 계산**:
   - 버퍼 가용 공간 = `rcv_buff_size - rcv_buff_used`
   - `clark_enabled=True`인 경우, 가용 공간이 `min(mss, rcv_buff_size // 2)` 미만이면 윈도우를 열어주지 않고 **`0`**을 유지합니다.
   - 임계치 이상의 공간이 확보되거나 애플리케이션 `APP_READ`로 버퍼가 충분히 비워지면 비로소 확장된 윈도우를 광고합니다.
2. **윈도우 갱신 패킷 유실 (`DROP_NEXT_WINDOW_UPDATE`)**:
   - 해당 플래그가 설정된 직후 발송되는 1회의 순수 윈도우 갱신 ACK 패킷은 수신자에서 송신자로 전달되지 않고 네트워크상에서 유실 처리됩니다.

### 2.5 판정 기준 (`verdict`)
- `silly_window_packets_sent > 0` $\to$ `"SWS_PACKET_STORM"`
- `deadlocks_prevented_by_probe > 0` $\to$ `"PERSIST_PROBE_DEADLOCK_PREVENTED"`
- `zero_window_advertised_count > 0` $\to$ `"ZERO_WINDOW_FLOW_CONTROLLED"`
- 그 외 $\to$ `"NORMAL_STREAMING"`

---

## 3. 입출력 포맷

### 입력 형식 (JSON on stdin)
```json
{
  "mss": 1000,
  "rcv_buff_size": 4000,
  "rtt_ticks": 20,
  "initial_rto": 100,
  "max_persist_timeout": 800,
  "clark_enabled": true,
  "sender_sws_enabled": true,
  "timeline_events": [
    {"tick": 0, "type": "APP_WRITE", "bytes": 5000},
    {"tick": 50, "type": "DROP_NEXT_WINDOW_UPDATE"},
    {"tick": 100, "type": "APP_READ", "bytes": 2000}
  ]
}
```

### 출력 형식 (JSON on stdout)
```json
{
  "metrics": {
    "total_payload_bytes_sent": 5000,
    "total_header_bytes_sent": 480,
    "total_data_packets_sent": 5,
    "zero_window_probes_sent": 1,
    "acks_sent": 6,
    "zero_window_advertised_count": 1,
    "silly_window_packets_sent": 0,
    "sws_avoidance_stalls": 0,
    "persist_timer_backoffs": 0,
    "deadlocks_prevented_by_probe": 1,
    "completion_tick": 160,
    "header_overhead_ratio": 0.0876,
    "verdict": "PERSIST_PROBE_DEADLOCK_PREVENTED"
  },
  "sample_timeline": [...]
}
```
