# #044 DB 타임아웃을 3초로 걸었는데 왜 60초 동안 안 풀려요?!: 네트워크 소켓 타임아웃의 3대 덫 (Connect vs Socket Read vs Statement Timeout)

---

## 1. 현실 세계 비유: 음식점 배달 주문 3대 타임아웃

배고픈 저녁, 중화요리 집에 배달 주문을 시키는 상황을 상상해 보세요.

```text
1. 전화 신호음 대기 시간 (Connect Timeout, TCP Handshake):
   가게에 전화를 걸었을 때 직원이 "네, 만리장성입니다!" 하고 수화기를 들 때까지 기다리는 시간.
   만약 가게가 정전이거나 전화선이 끊겼다면(방화벽 패킷 드롭 / Silent Drop),
   뚜- 뚜- 소리만 나는데 무려 127초(리눅스 커널 기본 SYN 대기 시간) 동안 수화기를 귀에 댄 채 굳어버립니다!

2. 요리 접시 간 대기 시간 (Socket Read Timeout, SO_TIMEOUT):
   주문이 들어가서 첫 번째 짜장면이 나오고, 다음 탕수육 접시(TCP 패킷)가 나올 때까지 기다리는 최대 시간.
   주방장이 탕수육을 튀기다 말고 도망갔다면(DB 데드락 / 패킷 유실), 접시가 무한정 안 오므로 제때 끊어야 합니다.

3. 총 식사 완료 한도 시간 (Statement / Query Timeout):
   주문이 들어가서 마지막 후식까지 전체 코스 요리가 완성되어야 하는 총 시간 한도.
```

수많은 주니어 개발자와 AI 바이브 코더들이 스프링부트나 프레임워크 설정에  
`query-timeout: 3000` (3초) 하나만 덜렁 적어두고 "이제 우리 DB 쿼리는 아무리 늦어도 3초면 끝나겠지!"라며 안심합니다.

하지만 클라우드 보안 그룹(AWS Security Group) 설정 실수로 DB 포트가 막히거나 방화벽이 패킷을 조용히 폐기(Silent Drop)하면,  
**3초짜리 쿼리 타임아웃은 아예 시작조차 못 하고, 리눅스 커널의 기본 TCP SYN 타임아웃(127초) 동안 톰캣 스레드가 꼼짝없이 굳어버립니다!**  
스레드 풀 200개가 순식간에 고갈되어 전사 서비스가 마비되는 **스레드 기아(Thread Starvation)** 참사가 터지는 것입니다.

---

## 2. 문제 개요

당신은 금융 거래 네트워크의 지연 장애를 해결해야 하는 백엔드 아키텍트입니다.  
다양한 네트워크 지연 환경에서, 기존의 **쿼리 타임아웃만 설정한 초보자 모델(NAIVE_STATEMENT_ONLY)**과  
네트워크 계층을 완벽히 방어하는 **3계층 타임아웃 모델(LAYERED_TIMEOUT)**을 시뮬레이션하고,  
스레드가 블로킹되어 낭비되는 시간(`THREAD_STARVATION_REDUCED`)을 얼마나 줄일 수 있는지 정밀 계측하세요.

### 타임아웃 모델 상세 규칙

#### 1. 공통 설정
- `CONNECT_TIMEOUT <conn_to>`: TCP 3-Way Handshake 최대 허용 시간 (ms, $1 \le conn\_to \le 10,000$).
- `SOCKET_READ_TIMEOUT <read_to>`: TCP 패킷 간 최대 도착 허용 간격 (ms, $1 \le read\_to \le 30,000$).
- `STATEMENT_TIMEOUT <stmt_to>`: 쿼리 실행 시작부터 완료까지의 총 허용 시간 (ms, $1 \le stmt\_to \le 60,000$).
- OS 커널 기본 TCP SYN 타임아웃 상수: `OS_SYN_TIMEOUT = 127000` (127초).

#### 2. 초보자 모델 (NAIVE_STATEMENT_ONLY)
오직 `STATEMENT_TIMEOUT`만 설정하고 네트워크 소켓 레벨 타임아웃을 지정하지 않은 모델입니다.
1. **연결 단계**:
   - $t\_conn > 127000$ (방화벽 블랙홀 등으로 무응답):
     - 리눅스 커널이 127초 만에 연결을 포기합니다: `OS_TCP_SYN_TIMEOUT (127000ms)`
     - 쿼리 실행 단계로 진입하지 못하고 종료됩니다.
   - $t\_conn \le 127000$:
     - 연결 성공! 소요 시간 $t\_conn$ 누적 후 쿼리 실행 단계로 진입합니다.
2. **데이터 수신 단계**:
   - 쿼리 누적 시간 $stmt\_elapsed = 0$.
   - 각 패킷 지연시간 $gap$이 도착할 때마다:
     - $stmt\_elapsed += gap$
     - 만약 $stmt\_elapsed > stmt\_to$:
       - 즉시 종료: `STATEMENT_TIMEOUT (t_conn + stmt_elapsed ms)`
   - 모든 패킷 수신 완료 시:
     - 정상 완료: `SUCCESS (t_conn + stmt_elapsed ms)`

#### 3. 올바른 계층형 모델 (LAYERED_TIMEOUT)
`Connect`, `Socket Read`, `Statement` 타임아웃이 유기적으로 협력하는 모델입니다.
1. **연결 단계**:
   - 만약 $t\_conn > conn\_to$:
     - 애플리케이션 레벨에서 설정된 커넥트 타임아웃이 즉시 발동: `CONNECT_TIMEOUT (conn_to ms)`
     - 불필요하게 127초 동안 대기하지 않고 $conn\_to$ 밀리초 만에 스레드를 즉시 석방합니다.
   - 만약 $t\_conn \le conn\_to$:
     - 연결 성공! 소요 시간 $t\_conn$ 누적 후 쿼리 실행 단계로 진입합니다.
2. **데이터 수신 단계**:
   - 쿼리 누적 시간 $stmt\_elapsed = 0$.
   - 각 패킷 지연시간 $gap$이 도착할 때마다:
     - 만약 $gap > read\_to$:
       - 패킷 간 응답 지연 발생! 소켓 리드 타임아웃 즉시 발동: `SOCKET_READ_TIMEOUT (t_conn + stmt_elapsed + read_to ms)`
       - 조리 도중 주방이 멈춘 것을 즉시 감지하고 스레드를 탈출시킵니다.
     - $stmt\_elapsed += gap$
     - 만약 $stmt\_elapsed > stmt\_to$:
       - 쿼리 총 실행 한도 초과: `STATEMENT_TIMEOUT (t_conn + stmt_elapsed ms)`
   - 모든 패킷 정상 수신 완료 시:
     - 정상 완료: `SUCCESS (t_conn + stmt_elapsed ms)`

---

## 3. 입력 형식

```text
CONNECT_TIMEOUT <conn_to>
SOCKET_READ_TIMEOUT <read_to>
STATEMENT_TIMEOUT <stmt_to>
REQUESTS <R>
REQ <req_id> CONNECT_TIME <t_conn> PACKETS <P> <gap_1> <gap_2> ... <gap_P>
... (총 R개의 요청)
```

- `conn_to`: 연결 타임아웃 (정수, ms)
- `read_to`: 소켓 읽기 타임아웃 (정수, ms)
- `stmt_to`: 쿼리 실행 총 타임아웃 (정수, ms)
- `R`: 총 요청 수 ($1 \le R \le 30,000$)
- 각 `REQ` 라인:
  - `req_id`: 요청 식별자 문자열 (예: `req_01`)
  - `t_conn`: 실제 TCP 연결에 걸린 시간 (정수, ms)
  - `P`: 응답 패킷 개수 ($P \ge 0$)
  - `gap_1 ... gap_P`: 이전 시점부터 각 패킷이 도착하기까지 걸린 시간 간격 (정수, ms)

---

## 4. 출력 형식

각 요청마다 다음 형식으로 한 줄씩 출력합니다:
```text
REQ <req_id> NAIVE:<naive_status>(<naive_time>ms) LAYERED:<layered_status>(<layered_time>ms) TIME_SAVED:<time_saved>ms
```
- `<naive_status>`, `<layered_status>`: `SUCCESS`, `CONNECT_TIMEOUT`, `SOCKET_READ_TIMEOUT`, `STATEMENT_TIMEOUT`, `OS_TCP_SYN_TIMEOUT` 중 하나
- `<time_saved>`: 스레드가 불필요하게 대기하지 않고 절약된 시간 $\max(0, naive\_time - layered\_time)$

전체 요청 처리가 끝난 후, 마지막 줄에 요약 통계를 출력합니다:
```text
SUMMARY TOTAL_REQS:<R> NAIVE_TOTAL_BLOCKED_TIME:<naive_sum>ms LAYERED_TOTAL_BLOCKED_TIME:<layered_sum>ms TOTAL_BLOCKED_TIME_SAVED:<saved_sum>ms THREAD_STARVATION_REDUCED:<percent>%
```
- `<percent>`: 스레드 블로킹 시간 절감율 $\frac{saved\_sum}{naive\_sum} \times 100$ (소수점 첫째 자리까지 반올림 표기, 예: `88.5%`, `0.0%`). 만약 `naive_sum == 0`이면 `0.0%`.

---

## 5. 입출력 예시

### 예시 입력 1
```text
CONNECT_TIMEOUT 3000
SOCKET_READ_TIMEOUT 5000
STATEMENT_TIMEOUT 10000
REQUESTS 4
REQ req_01 CONNECT_TIME 150000 PACKETS 0
REQ req_02 CONNECT_TIME 100 PACKETS 2 2000 6000
REQ req_03 CONNECT_TIME 50 PACKETS 6 2000 2000 2000 2000 2000 1000
REQ req_04 CONNECT_TIME 50 PACKETS 3 500 500 500
```

### 예시 출력 1
```text
REQ req_01 NAIVE:OS_TCP_SYN_TIMEOUT(127000ms) LAYERED:CONNECT_TIMEOUT(3000ms) TIME_SAVED:124000ms
REQ req_02 NAIVE:STATEMENT_TIMEOUT(10100ms) LAYERED:SOCKET_READ_TIMEOUT(7100ms) TIME_SAVED:3000ms
REQ req_03 NAIVE:STATEMENT_TIMEOUT(10050ms) LAYERED:STATEMENT_TIMEOUT(10050ms) TIME_SAVED:0ms
REQ req_04 NAIVE:SUCCESS(1550ms) LAYERED:SUCCESS(1550ms) TIME_SAVED:0ms
SUMMARY TOTAL_REQS:4 NAIVE_TOTAL_BLOCKED_TIME:148700ms LAYERED_TOTAL_BLOCKED_TIME:21700ms TOTAL_BLOCKED_TIME_SAVED:127000ms THREAD_STARVATION_REDUCED:85.4%
```

### 설명
- **`req_01` (방화벽 패킷 드롭 참사)**:
  - NAIVE 모델은 쿼리 타임아웃만 믿다가 리눅스 커널이 포기할 때까지 무려 **127,000ms (2분 이상!) 동안 스레드가 굳어버렸습니다.**
  - LAYERED 모델은 3,000ms 만에 커넥트 타임아웃으로 스레드를 즉시 구출하여 **124초의 스레드 기아를 방지**했습니다.
- **`req_02` (패킷 간 지연/Slowloris)**:
  - 1번째 패킷(2,000ms) 이후 2번째 패킷이 6,000ms 동안 오지 않았습니다.
  - LAYERED 모델은 5,000ms 시점에 `SOCKET_READ_TIMEOUT`을 터뜨려 7,100ms에 스레드를 회수했습니다 (NAIVE 대비 3,000ms 절약).
- **최종 요약**:
  - 타임아웃 3계층 방어를 통해 스레드가 블로킹되어 마비되는 시간을 무려 **85.4%나 절감**했습니다!
