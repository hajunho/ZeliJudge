# 093. 초당 1만 번 외부 API 쐈더니 'Cannot assign requested address' 에러로 서버가 통째로 죽었어요?!: TCP 4-Way Handshake, TIME_WAIT 상태와 임시 포트(Ephemeral Port) 고갈

---

## 1. 비극의 시작 (Real-World Disaster)

이커머스 스타트업 백엔드 개발자 준호는 대규모 타임세일 이벤트를 앞두고 외부 PG사(결제대행사)와 카카오 알림톡 웹훅을 연동하는 배치 모듈을 작성했습니다.

```python
# ❌ 준호가 작성한 결제 승인 확인 루프
import requests

def verify_all_orders(order_ids):
    for order_id in order_ids:
        # 매 주문마다 외부 결제 API를 단발성으로 호출
        response = requests.get(f"https://api.pg-company.com/orders/{order_id}")
        process_order(response.json())
```

로컬 테스트에서 10건, 20건을 테스트했을 때는 100% 정상 작동했습니다.  
하지만 이벤트 당일 12시 정각, 주문 5만 건이 한꺼번에 몰려들자 **불과 30초 만에 전사 시스템이 올스톱**되는 대재앙이 터졌습니다:

```text
OSError: [Errno 99] Cannot assign requested address
requests.exceptions.ConnectionError: HTTPSConnectionPool(host='api.pg-company.com', port=443): 
Max retries exceeded with url: /orders/12345 (Caused by NewConnectionError('<...>: Failed to establish a new connection: [Errno 99] Cannot assign requested address'))
```

서버 CPU는 10% 미만이었고 메모리도 80% 이상 넉넉히 남아 있었습니다. 네트워크 케이블도 정상이었고 외부 PG사 서버도 멀쩡했습니다.  
그런데 왜 우리 서버는 **"요청된 주소를 할당할 수 없습니다(`Cannot assign requested address`)"**라며 비명을 지르고 외부와의 모든 통신을 차단해 버린 걸까요?

---

## 2. 공중전화 부스의 비유: 도대체 TIME_WAIT가 무엇인가?

당신의 서버가 외부 서버로 HTTP 통신을 보낼 때, OS는 자신이 가진 **임시 포트(Ephemeral Port, 보통 32,768 ~ 60,999번 약 28,232개)** 중 하나를 골라 바인딩합니다.

이것은 마을의 **1인용 공중전화 부스**와 완벽하게 똑같습니다:

### 1) 단발성 호출의 비극 (단일 요청마다 전화 걸고 끊기)
손님이 도착해서 한 문장 말하고 전화를 끊습니다:
1. 손님이 전화를 먼저 끊으면(**Active Close**), 보건 당국은 부스 안에 남아있을지 모르는 바이러스(**네트워크 지연 패킷**)를 없애기 위해 **부스 문을 걸어 잠그고 60초(2MSL) 동안 소독 방역(`TIME_WAIT`)**을 진행합니다.
2. 초당 1,000명의 손님이 와서 전화 걸고 끊기를 반복하면:
   - 1초에 1,000개 부스가 소독 중(`TIME_WAIT`)으로 잠김!
   - 28,232개 / 1,000개 $\approx$ **불과 28초 만에 마을의 모든 공중전화 부스가 전량 잠겨버립니다!**
3. **29초째 도착한 손님**:  
   들어갈 수 있는 전화 부스가 1개도 남아있지 않아 길바닥에서 쫓겨납니다!  
   $\rightarrow$ **`Cannot assign requested address` (포트 고갈 참사)**

### 2) 커넥션 풀(Connection Pool & Keep-Alive)의 구원
지혜로운 손님은 부스에 들어가서 전화를 끊지 않고 들고 있습니다(**Keep-Alive**):
- 1번째 결제 용건을 말하고, 대기하다가 다음 손님이 오면 같은 전화기로 2번째 결제 용건을 말합니다.
- **부스 딱 1개(포트 1개)로 수만 건의 요청을 소독 방역 없이 초고속으로 처리**합니다!
- 나머지 28,231개의 부스는 평화롭고 여유롭게 비어 있습니다(**Healthy**).

---

## 3. 핵심 아키텍처 및 요구사항

당신은 OS 커널의 아웃바운드 TCP 포트 할당자, 4-Way Handshake 종료에 따른 `TIME_WAIT` FSM, 그리고 HTTP 커넥션 풀 시뮬레이터를 구현해야 합니다.

### 1) 시스템 설정 (`CONFIG`)
- `CONFIG <port_start> <port_end> <tw_duration_ms> <tw_reuse:0|1>`
  - 임시 포트 범위: `port_start` ~ `port_end` (양 끝 포함). 초기 상태의 모든 포트는 `FREE`입니다.
  - `tw_duration_ms`: 연결 종료 후 `TIME_WAIT` 상태로 유지되는 시간(ms).
  - `tw_reuse`: `1`이면 `net.ipv4.tcp_tw_reuse = 1` 활성화 (TIME_WAIT 포트 재사용 허용), `0`이면 비활성화.
  - 시간(`current_time_ms`)은 0ms에서 시작합니다.
  - 출력: `CONFIG_OK ports=<start>-<end> total=<count> tw_duration=<tw_duration_ms>ms tw_reuse=<0|1>`

### 2) 포트 할당 우선순위 (`_allocate_port`)
1. **1순위 (`FREE` 포트)**: 현재 완전히 비어 있는 포트 중 **가장 번호가 작은 포트**를 할당합니다.
2. **2순위 (`tw_reuse == 1` 재사용)**: 비어 있는 포트가 없고 `tw_reuse == 1`인 경우:
   - `TIME_WAIT` 상태인 포트 중, **최소 1,000ms(1초) 이상 TIME_WAIT를 유지한 포트**를 탐색합니다.
   - 대상 포트 중 **`tw_entered_at`이 가장 오래된 포트**(동률이면 포트 번호가 작은 것)를 선택하여 재사용합니다 (`[REUSED]`).
3. **3순위 (고갈)**: 할당 가능한 포트가 없으면 포트 고갈 에러를 발생시키고 `exhaustion_errors += 1`을 기록합니다.

### 3) 단발성 요청 (`REQ_SHORT <req_id> <dst>`)
- 새 TCP 연결을 맺고 즉시 클라이언트가 먼저 끊는(Active Close) 단발성 HTTP 요청:
  - 포트 할당 실패 시: `REQ:<req_id> ERROR:CANNOT_ASSIGN_REQUESTED_ADDRESS`
  - 포트 할당 성공 시:
    - 즉시 닫혀 `TIME_WAIT` 상태로 진입 (`port.tw_entered_at = current_time`, `port.tw_expires_at = current_time + tw_duration_ms`).
    - 재사용된 경우: `reused_count += 1`, 출력 `REQ:<req_id> PORT:<port> STATUS:CLOSED_TO_TIME_WAIT [REUSED]`
    - 신규 할당된 경우: 출력 `REQ:<req_id> PORT:<port> STATUS:CLOSED_TO_TIME_WAIT`

### 4) 커넥션 풀 요청 (`REQ_POOL <req_id> <pool_id> <dst>`)
- HTTP Connection Pool(Keep-Alive)을 통한 요청:
  - 지정한 `pool_id`에 유휴 소켓(`IDLE`)이 이미 존재하는 경우:
    - 풀 내 가장 오래 유휴 상태였던 포트를 꺼내어 요청을 처리하고, 다시 풀에 반환합니다.
    - 새 포트를 할당할 필요가 없으며 `TIME_WAIT`도 발생하지 않습니다!
    - 출력: `REQ:<req_id> POOL:<pool_id> PORT:<port> STATUS:REUSED_FROM_POOL`
  - 유휴 소켓이 없는 경우:
    - 포트를 새로 할당받아 `ACTIVE` 상태로 전환하고, `pool_id`에 등록합니다.
    - 재사용된 경우: `reused_count += 1`, 출력 `REQ:<req_id> POOL:<pool_id> PORT:<port> STATUS:NEW_POOL_CONN [REUSED]`
    - 신규 할당된 경우: 출력 `REQ:<req_id> POOL:<pool_id> PORT:<port> STATUS:NEW_POOL_CONN`
  - 포트 할당 실패 시:
    - 출력: `REQ:<req_id> ERROR:CANNOT_ASSIGN_REQUESTED_ADDRESS`

### 5) 커넥션 풀 해제 (`RELEASE_POOL <pool_id>`)
- 지정한 커넥션 풀을 닫고 모든 연결을 종료(Active Close)합니다.
- 풀에 보관된 모든 소켓은 `TIME_WAIT` 상태로 진입합니다 (`tw_entered_at = current_time`, `tw_expires_at = current_time + tw_duration_ms`).
- 출력: `POOL_RELEASED:<pool_id> closed_conns=<closed_count>`

### 6) 시간 경과 (`TICK <delta_ms>`)
- 가상 시간을 `delta_ms` 만큼 전진시킵니다 (`current_time_ms += delta_ms`).
- `TIME_WAIT` 상태인 포트 중 `current_time_ms >= port.tw_expires_at`을 만족하는 포트들은 소독이 끝나 즉시 `FREE` 상태로 회수됩니다.
- 출력: `TICK_OK time=<current_time_ms>ms expired_tw=<expired_count> free_ports=<free_count>`

### 7) 포트 상태 및 건전성 진단 (`STATS`)
- `ports`: 전체 임시 포트 수
- `free`: 현재 `FREE` 상태인 포트 수
- `active`: 현재 풀 등에서 유지 중인 `ACTIVE` 소켓 수
- `time_wait`: 현재 소독 중인 `TIME_WAIT` 소켓 수
- `exhaustions`: 누적 포트 고갈 에러 횟수
- `reused`: 누적 `tw_reuse` 재사용 횟수
- `util`: 포트 점유율 ($\frac{\text{active} + \text{time\_wait}}{\text{ports}} \times 100\%$, 소수점 1자리)
- `health` 판정 기준:
  - `free == 0`: **`EXHAUSTED`** (즉시 신규 연결 불능)
  - `util >= 75.0%`: **`WARNING`** (포트 고갈 임박)
  - 그 외: **`HEALTHY`** (안전)
- 출력 형식:
  `STATS ports=<total> free=<free> active=<active> time_wait=<tw> exhaustions=<errs> reused=<reused> util=<util>% health=<health>`

---

## 4. 입출력 형식

### 입력
표준 입력(stdin)으로 여러 줄의 명령어가 주어집니다. 빈 줄이나 `#`으로 시작하는 주석은 무시합니다.

- `CONFIG <port_start> <port_end> <tw_duration_ms> <tw_reuse>`
- `REQ_SHORT <req_id> <dst>`
- `REQ_POOL <req_id> <pool_id> <dst>`
- `RELEASE_POOL <pool_id>`
- `TICK <delta_ms>`
- `STATS`

### 출력
각 명령어의 실행 결과를 표준 출력(stdout)으로 한 줄씩 출력합니다.

---

## 5. 입출력 예시

### 예시 1: 단발성 요청 폭주로 인한 포트 고갈 및 60초 만료 회수
**입력:**
```text
CONFIG 30000 30002 60000 0
REQ_SHORT req_1 api.bank.com
REQ_SHORT req_2 api.bank.com
REQ_SHORT req_3 api.bank.com
STATS
REQ_SHORT req_4 api.bank.com
TICK 30000
STATS
TICK 30000
STATS
REQ_SHORT req_5 api.bank.com
STATS
```

**출력:**
```text
CONFIG_OK ports=30000-30002 total=3 tw_duration=60000ms tw_reuse=0
REQ:req_1 PORT:30000 STATUS:CLOSED_TO_TIME_WAIT
REQ:req_2 PORT:30001 STATUS:CLOSED_TO_TIME_WAIT
REQ:req_3 PORT:30002 STATUS:CLOSED_TO_TIME_WAIT
STATS ports=3 free=0 active=0 time_wait=3 exhaustions=0 reused=0 util=100.0% health=EXHAUSTED
REQ:req_4 ERROR:CANNOT_ASSIGN_REQUESTED_ADDRESS
TICK_OK time=30000ms expired_tw=0 free_ports=0
STATS ports=3 free=0 active=0 time_wait=3 exhaustions=1 reused=0 util=100.0% health=EXHAUSTED
TICK_OK time=60000ms expired_tw=3 free_ports=3
STATS ports=3 free=3 active=0 time_wait=0 exhaustions=1 reused=0 util=0.0% health=HEALTHY
REQ:req_5 PORT:30000 STATUS:CLOSED_TO_TIME_WAIT
STATS ports=3 free=2 active=0 time_wait=1 exhaustions=1 reused=0 util=33.3% health=HEALTHY
```

---

## 6. 실무 아키텍트 가이드: 어떻게 해결해야 하는가?

1. **외부 API 호출 시 무조건 HTTP Connection Pool(Keep-Alive)을 사용하라**:
   - Python `requests.get()`을 루프나 함수 안에서 무심코 단발성으로 호출하지 마세요. 반드시 `session = requests.Session()`을 싱글톤으로 유지하여 TCP 연결을 재사용하세요.
   - Go 언어는 `http.Client`의 `Transport` 풀을 재사용하고 응답 바디를 반드시 `resp.Body.Close()`로 닫아 소켓 누수를 막아야 합니다.
2. **리눅스 커널 파라미터 `tcp_tw_reuse = 1` 활성화**:
   - `sysctl -w net.ipv4.tcp_tw_reuse=1`과 `net.ipv4.tcp_timestamps=1`을 설정하면, 1초 이상 경과한 안전한 TIME_WAIT 소켓을 새 아웃바운드 연결에 즉시 재사용할 수 있습니다.
3. **`tcp_tw_recycle`는 절대로 켜지 마라**:
   - NAT(공유기, AWS NAT Gateway, 로드밸런서) 환경에서 클라이언트들의 TCP Timestamp가 꼬여 패킷이 무작위로 사살당하는 치명적인 참사가 발생합니다.
