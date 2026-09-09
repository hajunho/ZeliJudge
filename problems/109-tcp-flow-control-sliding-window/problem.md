# [CS-109] 수신자가 숨넘어가는데 계속 쐈더니 패킷이 통째로 증발해요?!: TCP 흐름 제어(Flow Control) 슬라이딩 윈도우와 제로 윈도우 프로브(Zero Window Probe)

> **"선생님! 10Gbps 초고속 전용선인데, 대용량 파일을 전송하다가 전송 속도가 갑자기 0KB/s로 곤두박질치더니 멈춰버렸어요! 와이어샤크(Wireshark)를 켜보니 `TCP ZeroWindow`와 `TCP ZeroWindowProbe`라는 시뻘건 경고가 화면을 가득 채우고 있어요!"**
> 
> 고성능 파일 전송 데몬을 개발하던 신입 네트워크 엔지니어 현우는 이상한 병목을 마주했습니다.
> 송신 측 서버는 초당 수백 메가바이트의 데이터를 뿜어낼 준비가 되어 있었고, 네트워크 회선 대역폭도 넉넉했습니다.
> 하지만 수신 측 서버가 데이터베이스 저장 및 압축 작업으로 인해 CPU 100%를 치며 데이터를 천천히 읽자, 몇 초 지나지 않아 전송이 완전히 올스톱되었습니다.
> 
> "회선도 널널하고 송신 서버도 쌩쌩한데 왜 패킷 전송이 0으로 멈출까요?!"  
> 시니어 네트워크 아키텍트는 칠판에 슬라이딩 윈도우 다이어그램을 그리며 말했습니다.
> "현우 씨, 아무리 주방장(송신자)이 요리를 1초에 한 접시씩 만들어도, 손님 테이블(수신 버퍼)에 빈 접시 놓을 자리가 없으면 요리를 내보낼 수 없어요. 수신자가 '제발 그만 보내요, 자리가 없어요!(Zero Window)'라고 비명을 지른 겁니다."

---

## 1. 문제 배경과 현실 비유: 주방장의 요리 속도 vs 손님 테이블의 빈자리

TCP는 수신자의 소켓 수신 버퍼(Receive Buffer)가 넘쳐 패킷이 버려지는 것을 방지하기 위해 **흐름 제어(Flow Control)** 메커니즘을 제공합니다.

### 1) 수신 윈도우 (`rwnd`, Receive Window)
- 수신자는 ACK를 보낼 때마다 현재 수신 버퍼의 남은 빈 공간 크기인 `rwnd`를 헤더에 적어서 송신자에게 알립니다.
- 송신자는 수신자로부터 확인받지 못한 채 보낼 수 있는 데이터 양을 `rwnd` 이하로 엄격히 제한합니다.

### 2) 제로 윈도우 (Zero Window, `rwnd = 0`)
- 수신자 애플리케이션이 버퍼를 비우지 못하면 `rwnd`가 0으로 떨어지며, 송신자는 전송을 즉시 중단하고 대기합니다.

### 3) 윈도우 갱신 패킷 유실과 영구 교착상태(Deadlock)
- 수신자가 버퍼를 비운 뒤 "이제 자리 났어요(`rwnd = 2000`)!"라고 보낸 윈도우 갱신(Window Update) ACK 패킷이 네트워크 노이즈 등으로 유실되면:
  - 수신자는 새 데이터가 오기를 기다리고, 송신자는 윈도우가 열리기를 기다리는 **영구 교착상태**에 빠집니다.

### 4) 구원 투수: 지속 타이머(Persist Timer)와 제로 윈도우 프로브(ZWP)
- 송신자는 `rwnd = 0` 통보를 받는 즉시 지속 타이머를 가동합니다.
- 타이머 만료 시 1바이트짜리 정찰병 패킷인 **Zero Window Probe**를 강제로 전송합니다.
- 수신자는 이 프로브에 대해 현재 최신 `rwnd`를 담은 ACK를 무조건 회신해야 하므로, 유실되었던 교착상태가 즉시 깨지고 전송이 재개됩니다!

---

## 2. 요구사항 및 명령어 사양

당신은 TCP 슬라이딩 윈도우 흐름 제어, 제로 윈도우 경고, 패킷 유실 교착상태 및 제로 윈도우 프로브(ZWP) 복구 메커니즘을 시뮬레이션하는 `FlowControlSimulator` 엔진을 구현해야 합니다.
표준 입력(`stdin`)으로 들어오는 명령어들을 한 줄씩 파싱하여 정확한 형식으로 표준 출력(`stdout`)에 출력하십시오.

### 지원 명령어 목록

1. `INIT_FLOW <conn_id> <rcv_buf_size> <persist_interval_ms>`
   - 흐름 제어 연결을 생성합니다.
   - 초기 `rwnd = rcv_buf_size`.
   - 출력: `INIT_FLOW id=<conn_id> rcv_buf=<rcv_buf_size> rwnd=<rcv_buf_size> persist_interval=<persist_interval_ms>ms`

2. `APP_WRITE <conn_id> <bytes>`
   - 송신자가 데이터를 소켓에 씁니다.
   - 현재 `rwnd > 0`이고 제로 윈도우 상태가 아닌 경우:
     - 송신 가능 바이트: `sendable = min(bytes, rwnd)`.
     - 남은 바이트(`bytes - sendable`)는 송신 버퍼(`sender_buffer`)에 누적 대기.
     - 수신 버퍼 점유 및 윈도우 축소: `rcv_buf_used += sendable`, `rwnd = rcv_buf_max - rcv_buf_used`.
     - 출력: `DATA_SENT id=<conn_id> sent=<sendable> buffered=<sender_buffer> rwnd=<rwnd>`
     - 만약 `rwnd == 0`이 되면 제로 윈도우 상태 돌입:
       - 출력: `ZERO_WINDOW_ADVERTISED id=<conn_id> rwnd=0 persist_timer=<persist_interval>ms`
   - 현재 `rwnd == 0`이거나 제로 윈도우 상태인 경우:
     - 전송 불가! 전량 송신 버퍼에 누적:
     - 출력: `DATA_BLOCKED id=<conn_id> requested=<bytes> buffered=<sender_buffer> reason=ZERO_WINDOW`

3. `APP_READ <conn_id> <bytes>`
   - 수신자가 버퍼에서 최대 `<bytes>`만큼 데이터를 읽어 처리합니다.
   - `read_bytes = min(bytes, rcv_buf_used)`.
   - `rcv_buf_used -= read_bytes`, `new_rwnd = rcv_buf_max - rcv_buf_used`.
   - 출력: `APP_READ id=<conn_id> read=<read_bytes> remaining_in_buf=<rcv_buf_used> new_rwnd=<new_rwnd>`

4. `SIMULATE_WINDOW_UPDATE_LOST <conn_id>`
   - 수신자가 버퍼를 비워 실제로는 윈도우가 열렸으나, 이 갱신 알림 패킷이 네트워크에서 유실된 상황을 시뮬레이션합니다.
   - 송신자는 여전히 제로 윈도우 상태로 인식합니다.
   - 출력: `WINDOW_UPDATE_LOST id=<conn_id> actual_rwnd=<rwnd> sender_still_sees_zero_window=True`

5. `TICK_PERSIST_TIMER <conn_id> <elapsed_ms>`
   - 지속 타이머가 만료되어 제로 윈도우 프로브(ZWP) 1바이트를 전송합니다.
   - 출력:
     - `ZERO_WINDOW_PROBE_SENT id=<conn_id> probe_bytes=1B`
     - `PROBE_ACK_RECEIVED id=<conn_id> received_rwnd=<rwnd>`
   - 수신자의 실제 `rwnd > 0`인 경우:
     - 윈도우 열림 및 송신 버퍼 데이터 방출: `drain = min(sender_buffer, rwnd)`.
     - 출력: `WINDOW_OPENED id=<conn_id> drained_from_buffer=<drain> remaining_buffer=<rem> current_rwnd=<rwnd>`
     - 만약 방출 후 다시 `rwnd == 0`이고 버퍼에 데이터가 남아있으면 다시 `ZERO_WINDOW_ADVERTISED` 출력.
   - 여전히 `rwnd == 0`인 경우:
     - 출력: `ZERO_WINDOW_PERSISTS id=<conn_id> rwnd=0 persist_timer_reset=<persist_interval>ms`

6. `STATS <conn_id>`
   - 현재 흐름 제어 상태를 출력합니다.
   - 출력: `STATS id=<conn_id> total_sent=<sent> total_recv=<recv> rcv_buf_used=<used> rwnd=<rwnd> sender_buffer=<buf> zero_window_events=<events> zwp_sent=<zwp>`

---

## 3. 입출력 예시

### 예시 입력 1
```text
INIT_FLOW conn1 4000 500
APP_WRITE conn1 2500
APP_WRITE conn1 2000
APP_WRITE conn1 1000
APP_READ conn1 2000
SIMULATE_WINDOW_UPDATE_LOST conn1
STATS conn1
TICK_PERSIST_TIMER conn1 500
STATS conn1
```

### 예시 출력 1
```text
INIT_FLOW id=conn1 rcv_buf=4000 rwnd=4000 persist_interval=500ms
DATA_SENT id=conn1 sent=2500 buffered=0 rwnd=1500
DATA_SENT id=conn1 sent=1500 buffered=500 rwnd=0
ZERO_WINDOW_ADVERTISED id=conn1 rwnd=0 persist_timer=500ms
DATA_BLOCKED id=conn1 requested=1000 buffered=1500 reason=ZERO_WINDOW
APP_READ id=conn1 read=2000 remaining_in_buf=2000 new_rwnd=2000
WINDOW_UPDATE_LOST id=conn1 actual_rwnd=2000 sender_still_sees_zero_window=True
STATS id=conn1 total_sent=4000 total_recv=2000 rcv_buf_used=2000 rwnd=2000 sender_buffer=1500 zero_window_events=1 zwp_sent=0
ZERO_WINDOW_PROBE_SENT id=conn1 probe_bytes=1B
PROBE_ACK_RECEIVED id=conn1 received_rwnd=2000
WINDOW_OPENED id=conn1 drained_from_buffer=1500 remaining_buffer=0 current_rwnd=500
STATS id=conn1 total_sent=5500 total_recv=2000 rcv_buf_used=3500 rwnd=500 sender_buffer=0 zero_window_events=1 zwp_sent=1
```

---

## 4. 실무 핵심 요약 (Architecture Takeaway)

1. **소켓 버퍼 튜닝의 중요성**:
   - 고속 네트워크망에서 수신 버퍼(`SO_RCVBUF`)가 너무 작으면, 아주 잠깐의 애플리케이션 I/O 지연에도 즉시 Zero Window가 발생하여 전체 회선 대역폭이 0으로 죽어버립니다.
2. **비동기 넌블로킹 I/O 처리**:
   - 수신 I/O 스레드가 무거운 DB 작업이나 CPU 연산에 묶이지 않도록 즉시 워커 스레드 풀로 오프로딩하여, 수신 소켓 버퍼를 상시 여유 있게 유지해야 합니다.
