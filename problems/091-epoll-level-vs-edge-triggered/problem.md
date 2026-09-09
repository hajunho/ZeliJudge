# Problem #091: epoll로 고성능 비동기 서버를 짰더니 CPU 100% 찍거나 패킷이 증발해요?!: Level-Triggered (LT) vs Edge-Triggered (ET)

## 1. 문제 설명
Nginx와 Redis의 아키텍처에 매료된 당신은 C/Go/Rust로 수만 개의 동시 접속을 처리하는 고성능 비동기 네트워크 서버를 개발하기 위해 Linux의 `epoll` I/O 다중화 시스템 콜을 도입했습니다.

그러나 프로덕션 테스트 환경에서 기이하고 치명적인 버그 2종이 발생했습니다:
1. **Level-Triggered (LT) 모드**: 클라이언트가 보낸 데이터 중 일부만 읽고 다음 루프로 넘어갔더니, `epoll_wait`이 블로킹되지 않고 0초 만에 무한히 깨어나며 **CPU 점유율이 100%로 치솟는 비지 루프(Busy Loop)** 가 발생했습니다!
2. **Edge-Triggered (ET) 모드**: CPU 낭비를 막기 위해 ET 모드로 변경하고 1회 `read()`를 호출했더니, 버퍼에 남아있던 수백 바이트의 데이터에 대해 **커널이 다시는 알림을 주지 않아 데이터가 영구 고립(Marooned Data)되고 클라이언트가 무한 응답 대기(Starvation)** 에 빠졌습니다!

당신은 Linux `epoll` 커널 이벤트 통지 메커니즘을 정밀하게 모사하여, LT와 ET 모드의 통지 특성을 분석하고 **EAGAIN 루프 배수(Drain) 패턴**을 검증하는 시뮬레이터를 구축해야 합니다.

---

## 2. 시스템 동작 규칙

### (1) 소켓 버퍼 및 epoll 모델
- 소켓(File Descriptor)은 고유한 정수 ID(`1, 2, ...`)를 가집니다.
- 각 소켓은 커널 수신 버퍼(`rcv_buf`, 바이트 단위)를 가집니다 (초기값 0).
- epoll 인스턴스에 소켓을 등록할 때 통지 모드를 지정합니다:
  - **LT (Level-Triggered, 기본 모드)**: 수신 버퍼에 미처리 데이터가 남아있는 한(`rcv_buf > 0`), `EPOLL_WAIT` 호출 시마다 지속적으로 준비 완료(Ready)로 보고됩니다.
  - **ET (Edge-Triggered, 에지 모드)**: 새 데이터가 도착하여 상태가 변화하는(Edge) 순간에만 준비 완료로 1회 보고됩니다. 한 번 보고된 소켓은 준비 목록에서 즉시 제거됩니다.

---

### (2) 액션 명세

1. `REGISTER <fd> <LT|ET>`:
   - 소켓 `<fd>`를 지정된 모드(`LT` 또는 `ET`)로 epoll에 등록합니다.
   - 출력:
     `ACT <idx> REGISTER FD:<fd> MODE:<LT|ET>`

2. `ARRIVE <fd> <bytes>`:
   - 네트워크로부터 `<fd>`의 수신 버퍼로 `<bytes>`만큼의 데이터가 도착합니다.
   - `rcv_buf[fd] += bytes`.
   - 만약 ET 모드라면, 새 데이터 도착에 따른 에지(Edge)가 발생하여 다음 `EPOLL_WAIT`을 위한 준비 플래그가 활성화됩니다.
   - 출력:
     `ACT <idx> ARRIVE FD:<fd> BYTES:+<bytes> TOTAL_BUF:<total> READY:TRUE`

3. `READ <fd> <limit>`:
   - 애플리케이션이 `<fd>`로부터 최대 `<limit>` 바이트를 읽어옵니다.
   - 실제 읽은 바이트: `actual = min(rcv_buf[fd], limit)`.
   - `rcv_buf[fd] -= actual`.
   - 남은 바이트: `rem = rcv_buf[fd]`.
   - 상태(`STATUS`):
     - `actual == 0`: `STATUS:EAGAIN` (버퍼에 더 이상 읽을 데이터가 없음)
     - `actual > 0` 이고 `rem == 0`: `STATUS:DRAINED` (버퍼를 완전히 비움)
     - `rem > 0`: `STATUS:REMAINING:<rem>` (일부 데이터가 버퍼에 남아있음)
   - 출력:
     `ACT <idx> READ FD:<fd> REQUESTED:<limit> READ:<actual> REMAINING:<rem> STATUS:<status>`

4. `EPOLL_WAIT`:
   - 준비된 소켓 목록을 FD 번호 오름차순으로 확인하여 반환합니다.
   - **준비 판정 규칙**:
     - `LT` 소켓: `rcv_buf[fd] > 0` 이면 준비 완료.
     - `ET` 소켓: 새 도착 에지가 발생한 상태(`et_ready == True`)이면 준비 완료 (반환 즉시 `et_ready = False`로 소멸).
   - **이상 상태 감지 (Anomaly Detection)**:
     - **`[BUSY_LOOP_SPIN]`**: 직전 `EPOLL_WAIT`에서 준비 완료로 보고되었던 `LT` 소켓에 대해, 이후 `READ`를 단 1바이트도 수행하지 않은 채 다시 `EPOLL_WAIT`을 호출하여 동일한 소켓이 또 반환된 경우.
     - **`[MAROONED_DATA_DETECTED]`**: `ET` 소켓 중 `rcv_buf[fd] > 0`이지만 준비 목록에 포함되지 못한 소켓이 존재하는 경우 (버퍼에 데이터가 갇힌 채 알림이 오지 않음).
   - 출력:
     `ACT <idx> EPOLL_WAIT READY:[<ready_fds>] [FLAGS]`
     (준비된 소켓이 없다면 `READY:[]`. 플래그가 있다면 한 칸 띄우고 뒤에 붙임)
     예: `READY:[FD:1] [BUSY_LOOP_SPIN]`
     예: `READY:[] [MAROONED_DATA_DETECTED]`

---

## 3. 입력 형식

```text
SYSTEM_CONFIG
ACTIONS
<ACTION_1>
<ACTION_2>
...
```

---

## 4. 출력 형식

각 액션마다 `ACT <act_idx> ...` 한 줄씩 결과를 출력합니다.  
모든 액션 완료 후 `SUMMARY`를 출력합니다:

```text
SUMMARY TOTAL_ACTIONS:<cnt>
SUMMARY TOTAL_BYTES_ARRIVED:<bytes>
SUMMARY TOTAL_BYTES_READ:<bytes>
SUMMARY REMAINING_UNREAD_BYTES:<bytes>
SUMMARY BUSY_LOOP_EVENTS:<cnt>
SUMMARY MAROONED_DATA_EVENTS:<cnt>
SUMMARY I_O_HEALTH: <HEALTHY | BUSY_LOOP_BURNING | DATA_MAROONED_STARVATION | DEGRADED (BUSY_LOOP & MAROONED)>
```

- `BUSY_LOOP_EVENTS`: `[BUSY_LOOP_SPIN]`이 발생한 `EPOLL_WAIT` 횟수.
- `MAROONED_DATA_EVENTS`: `[MAROONED_DATA_DETECTED]`가 발생한 `EPOLL_WAIT` 횟수.
- `I_O_HEALTH`:
  - 둘 다 0건: `HEALTHY`
  - `BUSY_LOOP_EVENTS > 0` 이고 `MAROONED_DATA_EVENTS > 0`: `DEGRADED (BUSY_LOOP & MAROONED)`
  - `BUSY_LOOP_EVENTS > 0`: `BUSY_LOOP_BURNING`
  - `MAROONED_DATA_EVENTS > 0`: `DATA_MAROONED_STARVATION`

---

## 5. 입출력 예시

### 예시 입력 1 (LT 모드 비지 루프)
```text
SYSTEM_CONFIG
ACTIONS
REGISTER 1 LT
ARRIVE 1 1000
EPOLL_WAIT
READ 1 100
EPOLL_WAIT
EPOLL_WAIT
```

### 예시 출력 1
```text
ACT 1 REGISTER FD:1 MODE:LT
ACT 2 ARRIVE FD:1 BYTES:+1000 TOTAL_BUF:1000 READY:TRUE
ACT 3 EPOLL_WAIT READY:[FD:1]
ACT 4 READ FD:1 REQUESTED:100 READ:100 REMAINING:900 STATUS:REMAINING:900
ACT 5 EPOLL_WAIT READY:[FD:1]
ACT 6 EPOLL_WAIT READY:[FD:1] [BUSY_LOOP_SPIN]
SUMMARY TOTAL_ACTIONS:6
SUMMARY TOTAL_BYTES_ARRIVED:1000
SUMMARY TOTAL_BYTES_READ:100
SUMMARY REMAINING_UNREAD_BYTES:900
SUMMARY BUSY_LOOP_EVENTS:1
SUMMARY MAROONED_DATA_EVENTS:0
SUMMARY I_O_HEALTH: BUSY_LOOP_BURNING
```

---

### 예시 입력 2 (ET 모드 잔여 데이터 고립)
```text
SYSTEM_CONFIG
ACTIONS
REGISTER 2 ET
ARRIVE 2 1000
EPOLL_WAIT
READ 2 500
EPOLL_WAIT
```

### 예시 출력 2
```text
ACT 1 REGISTER FD:2 MODE:ET
ACT 2 ARRIVE FD:2 BYTES:+1000 TOTAL_BUF:1000 READY:TRUE
ACT 3 EPOLL_WAIT READY:[FD:2]
ACT 4 READ FD:2 REQUESTED:500 READ:500 REMAINING:500 STATUS:REMAINING:500
ACT 5 EPOLL_WAIT READY:[] [MAROONED_DATA_DETECTED]
SUMMARY TOTAL_ACTIONS:5
SUMMARY TOTAL_BYTES_ARRIVED:1000
SUMMARY TOTAL_BYTES_READ:500
SUMMARY REMAINING_UNREAD_BYTES:500
SUMMARY BUSY_LOOP_EVENTS:0
SUMMARY MAROONED_DATA_EVENTS:1
SUMMARY I_O_HEALTH: DATA_MAROONED_STARVATION
```
