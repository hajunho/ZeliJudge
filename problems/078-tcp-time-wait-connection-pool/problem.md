# Problem 078: TCP TIME_WAIT 소켓 고갈과 HTTP 커넥션 풀링 (TCP TIME_WAIT & Connection Pool Starvation)

## 문제 설명

수백 대의 마이크로서비스 간에 HTTP API를 호출하거나 외부 결제/인증 게이트웨이를 연동하던 백엔드 시스템에 원인을 알 수 없는 통신 전면 마비 장애가 발생했습니다:
> "평소에는 아무 문제 없던 서버가 블랙 프라이데이 이벤트로 트래픽이 몰리자마자 10분 만에 모든 외부 API 호출이 멈추고 `Cannot assign requested address (Errno 99 / EADDRNOTAVAIL)` 에러가 쏟아집니다!  
> CPU나 메모리는 20%도 안 쓰고 있고 네트워크 대역폭도 널널한데, 서버 내부에서 나가는 모든 새 연결이 OS 레벨에서 거부당하고 있습니다!"

이 기괴한 장애의 원인은 단기 TCP 연결(Short-lived Connection, `Connection: close`) 안티패턴과 **TCP 프로토콜의 수호신이자 저주인 `TIME_WAIT` 상태로 인한 임시 포트(Ephemeral Port) 고갈**이었습니다:
- **TCP 4-Way Teardown과 `TIME_WAIT`의 정체**:
  - TCP 통신에서 먼저 연결 종료(`FIN`)를 선언한 쪽(Active Closer, 주로 클라이언트)은 마지막 `ACK`를 보낸 뒤 소켓을 즉시 파괴하지 않고, **`TIME_WAIT` 상태로 60초~120초(2MSL: Maximum Segment Lifetime) 동안 유지**합니다.
  - 이는 네트워크 상을 떠돌던 지연 패킷(Lost Segment)이 우연히 새로 열린 소켓에 잘못 흘러들어가 데이터를 오염시키는 것을 방지하기 위한 TCP 표준 규약입니다.
- **임시 포트(Ephemeral Port) 고갈의 덫**:
  - 리눅스/윈도우 OS가 클라이언트 소켓에 할당할 수 있는 로컬 포트 범위(Ephemeral Port Range)는 약 28,000개(예: 32768 ~ 60999)로 물리적 한계가 있습니다.
  - `requests.get()`이나 Node.js 기본 HTTP 클라이언트를 호출할 때 커넥션 풀 없이 매번 새 연결을 맺고 끊으면, **1분 동안 수만 개의 소켓이 `TIME_WAIT`에 갇혀 28,000개의 포트가 순식간에 전멸**합니다.
  - 가용 포트가 0개가 되는 순간 OS 커널은 새 소켓을 열지 못하고 `Cannot assign requested address` 에러를 뿜으며 서버를 마비시킵니다.

말 한마디 할 때마다 전화를 걸어 "재고 있나요?" 묻고 뚝 끊어버리자, 전화국이 회선 혼선을 막으려고 끊긴 전화선을 60초 동안 잠금(`TIME_WAIT`)해 두는 바람에, 50번 질문하자마자 사무실 전화선 50개가 전부 잠겨 아무 데도 전화를 걸 수 없게 된 것과 같습니다!

이를 해결하려면 **HTTP Keep-Alive와 커넥션 풀링(Connection Pooling)**을 사용해야 합니다:
1. **커넥션 재사용**: 이미 맺어진 TCP 커넥션을 풀(Pool)에 보관해 두고 다음 요청에 재사용합니다. 3-Way Handshake(SYN $\to$ SYN-ACK $\to$ ACK)가 생략되어 응답 속도가 70% 이상 빨라집니다.
2. **`TIME_WAIT` 발생 제로**: 요청이 끝나도 연결을 끊지 않으므로(`FIN`을 보내지 않음) 소켓이 `TIME_WAIT`에 빠지지 않습니다.
3. 단 10~20개의 커넥션만으로도 임시 포트 고갈 없이 초당 수만 건의 요청을 100% 무에러로 처리할 수 있습니다.

당신은 동일한 HTTP 요청 및 시간 경과 스트림에 대해 단순 단기 연결을 생성하는 **Naive 클라이언트**와 커넥션 풀을 사용하는 **Pooled 클라이언트**의 포트 점유율, `TIME_WAIT` 소켓 수, 실패율, 총 지연시간을 비교 검증하는 TCP/HTTP 소켓 시뮬레이터를 작성해야 합니다.

---

## 시스템 요구사항 및 동작 규칙

### 1. 전역 설정 (`SYSTEM_CONFIG`)
- `TOTAL_EPHEMERAL_PORTS <int>`: OS가 제공하는 가용 임시 포트 총 개수 (포트 번호: 10001부터 순차 할당).
- `TIME_WAIT_TICKS <int>`: 단기 소켓 종료 후 `TIME_WAIT` 상태로 대기해야 하는 가상 틱 수.
- `HANDSHAKE_LATENCY_MS <int>`: TCP 3-Way Handshake 지연 시간(ms).
- `REQUEST_LATENCY_MS <int>`: HTTP 요청/응답 데이터 송수신 지연 시간(ms).
- `POOL_MAX_SIZE <int>`: Pooled 엔진의 최대 커넥션 풀 크기.

---

### 2. 두 가지 클라이언트 엔진 메커니즘

#### 1) Naive Client Engine (Short-lived Connection, Connection: close)
- `SEND_REQ <req_id>`:
  - 가용 임시 포트가 비어있는 경우 (`available_ports` 0개):
    - 포트 고갈 실패: `STATUS:FAILED_(PORT_EXHAUSTED)`, `PORT:EXHAUSTED`, `LATENCY:0ms`.
  - 가용 임시 포트가 있는 경우:
    - 가장 작은 번호의 포트 할당.
    - 소요 지연시간: `HANDSHAKE_LATENCY_MS + REQUEST_LATENCY_MS`.
    - 요청 즉시 완료 후 능동 종료(Active Close): 해당 포트는 즉시 `TIME_WAIT` 상태로 진입하며 `TIME_WAIT_TICKS` 동안 점유.
- `TICK <num_ticks>`:
  - 가상 시간 경과에 따라 `TIME_WAIT` 소켓들의 잔여 틱 감소.
  - 잔여 틱이 0 이하가 된 포트들은 회수되어 다시 `available_ports`로 반환(재사용 가능).

#### 2) Pooled Client Engine (HTTP Keep-Alive & Connection Pool)
- `SEND_REQ <req_id>`:
  - 풀에 유휴(Idle) 커넥션이 있는 경우:
    - 기존 커넥션 즉시 재사용 (`CONN:REUSED`).
    - Handshake 생략! 소요 지연시간: `REQUEST_LATENCY_MS`.
  - 풀에 유휴 커넥션이 없고, 현재 커넥션 수 < `POOL_MAX_SIZE`인 경우:
    - 신규 커넥션 생성 및 1회 Handshake 발생 (`CONN:NEW`).
    - 소요 지연시간: `HANDSHAKE_LATENCY_MS + REQUEST_LATENCY_MS`.
  - 풀이 꽉 찬 경우:
    - 기존 커넥션 재사용 (`CONN:REUSED`), 소요 지연시간: `REQUEST_LATENCY_MS`.
  - 요청 완료 후 커넥션을 닫지 않고 풀의 유휴 목록에 유지하므로, **`TIME_WAIT` 소켓이 절대 발생하지 않고 포트 고갈 실패율 0.00%**를 유지합니다!

---

### 3. 액션 명세

#### 1) `SEND_REQ <req_id>`
- HTTP 요청 전송.
- 출력 (3줄):
  ```text
  ACT <idx> SEND_REQ ID:<req_id>
    NAIVE: PORT:<port|EXHAUSTED> STATUS:<SUCCESS|FAILED_(PORT_EXHAUSTED)> LATENCY:<lat>ms TIME_WAIT_SOCKETS:<cnt>
    POOLED: CONN:<NEW|REUSED> STATUS:SUCCESS LATENCY:<lat>ms POOL_CONNS:<conns>/<max> TIME_WAIT_SOCKETS:0
  ```

#### 2) `TICK <num_ticks>`
- 가상 시간 `<num_ticks>` 경과.
- 출력 (2줄):
  ```text
  ACT <idx> TICK <num_ticks>
    NAIVE: EXPIRED_TIME_WAIT:<exp_cnt> REMAINING_TIME_WAIT:<rem_cnt> AVAILABLE_PORTS:<avail_cnt>/<total_ports>
  ```

#### 3) `CHECK_METRICS`
- 누적 메트릭 점검.
- 출력 (3줄):
  ```text
  ACT <idx> CHECK_METRICS
    NAIVE: TOTAL:<tot> SUCCESS:<succ> FAILED:<fail> TOTAL_LATENCY:<lat>ms TIME_WAIT_ACTIVE:<cnt>
    POOLED: TOTAL:<tot> SUCCESS:<succ> FAILED:0 TOTAL_LATENCY:<lat>ms POOL_CONNS:<conns>/<max>
  ```

---

## 입력 형식

```text
SYSTEM_CONFIG
TOTAL_EPHEMERAL_PORTS <ports>
TIME_WAIT_TICKS <ticks>
HANDSHAKE_LATENCY_MS <hs_ms>
REQUEST_LATENCY_MS <req_ms>
POOL_MAX_SIZE <pool_size>
ACTIONS
<action_cmd> <args...>
...
```

---

## 출력 형식

1. 각 액션별 실행 결과 (위 명세 참조)
2. 모든 액션 종료 후 최종 통계 요약 (5줄):
```text
SUMMARY TOTAL_HTTP_REQUESTS:<tot>
SUMMARY NAIVE SUCCESS:<succ> FAILED:<fail> FAILURE_RATE:<pct:.2f>% TOTAL_LATENCY:<lat>ms
SUMMARY POOLED SUCCESS:<succ> FAILED:0 FAILURE_RATE:0.00% TOTAL_LATENCY:<lat>ms
SUMMARY LATENCY_SAVED:<lat_saved>ms (LATENCY_REDUCTION:<pct:.2f>%)
SUMMARY SOCKET_STABILITY: POOLING_PREVENTS_TIME_WAIT_EXHAUSTION
```

---

## 입출력 예시

### 예시 1

**입력:**
```text
SYSTEM_CONFIG
TOTAL_EPHEMERAL_PORTS 3
TIME_WAIT_TICKS 3
HANDSHAKE_LATENCY_MS 20
REQUEST_LATENCY_MS 5
POOL_MAX_SIZE 2
ACTIONS
SEND_REQ R1
SEND_REQ R2
SEND_REQ R3
SEND_REQ R4
CHECK_METRICS
TICK 3
SEND_REQ R5
CHECK_METRICS
```

**출력:**
```text
ACT 1 SEND_REQ ID:R1
  NAIVE: PORT:10001 STATUS:SUCCESS LATENCY:25ms TIME_WAIT_SOCKETS:1
  POOLED: CONN:NEW STATUS:SUCCESS LATENCY:25ms POOL_CONNS:1/2 TIME_WAIT_SOCKETS:0
ACT 2 SEND_REQ ID:R2
  NAIVE: PORT:10002 STATUS:SUCCESS LATENCY:25ms TIME_WAIT_SOCKETS:2
  POOLED: CONN:REUSED STATUS:SUCCESS LATENCY:5ms POOL_CONNS:1/2 TIME_WAIT_SOCKETS:0
ACT 3 SEND_REQ ID:R3
  NAIVE: PORT:10003 STATUS:SUCCESS LATENCY:25ms TIME_WAIT_SOCKETS:3
  POOLED: CONN:REUSED STATUS:SUCCESS LATENCY:5ms POOL_CONNS:1/2 TIME_WAIT_SOCKETS:0
ACT 4 SEND_REQ ID:R4
  NAIVE: PORT:EXHAUSTED STATUS:FAILED_(PORT_EXHAUSTED) LATENCY:0ms TIME_WAIT_SOCKETS:3
  POOLED: CONN:REUSED STATUS:SUCCESS LATENCY:5ms POOL_CONNS:1/2 TIME_WAIT_SOCKETS:0
ACT 5 CHECK_METRICS
  NAIVE: TOTAL:4 SUCCESS:3 FAILED:1 TOTAL_LATENCY:75ms TIME_WAIT_ACTIVE:3
  POOLED: TOTAL:4 SUCCESS:4 FAILED:0 TOTAL_LATENCY:40ms POOL_CONNS:1/2
ACT 6 TICK 3
  NAIVE: EXPIRED_TIME_WAIT:3 REMAINING_TIME_WAIT:0 AVAILABLE_PORTS:3/3
ACT 7 SEND_REQ ID:R5
  NAIVE: PORT:10001 STATUS:SUCCESS LATENCY:25ms TIME_WAIT_SOCKETS:1
  POOLED: CONN:REUSED STATUS:SUCCESS LATENCY:5ms POOL_CONNS:1/2 TIME_WAIT_SOCKETS:0
ACT 8 CHECK_METRICS
  NAIVE: TOTAL:5 SUCCESS:4 FAILED:1 TOTAL_LATENCY:100ms TIME_WAIT_ACTIVE:1
  POOLED: TOTAL:5 SUCCESS:5 FAILED:0 TOTAL_LATENCY:45ms POOL_CONNS:1/2
SUMMARY TOTAL_HTTP_REQUESTS:5
SUMMARY NAIVE SUCCESS:4 FAILED:1 FAILURE_RATE:20.00% TOTAL_LATENCY:100ms
SUMMARY POOLED SUCCESS:5 FAILED:0 FAILURE_RATE:0.00% TOTAL_LATENCY:45ms
SUMMARY LATENCY_SAVED:55ms (LATENCY_REDUCTION:55.00%)
SUMMARY SOCKET_STABILITY: POOLING_PREVENTS_TIME_WAIT_EXHAUSTION
```
