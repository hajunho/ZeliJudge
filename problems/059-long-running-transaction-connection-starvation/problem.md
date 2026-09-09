# #059 이메일 발송 API가 느려졌는데 왜 쇼핑몰 전체가 마비돼요?!: 롱 러닝 트랜잭션과 커넥션 풀 고갈 (Long-Running Transaction & HikariCP Pool Starvation)

---

## 1. 현실 세계 비유: 화장실 변기에서 유튜브 보는 손님

번화가 대형 쇼핑몰에 화장실 칸이 딱 10개(DB 커넥션 풀 크기 = 10) 있습니다.

```text
❌ 롱 러닝 트랜잭션 (NAIVE):
   1. 손님 10명이 화장실에 들어가서 3초 만에 유저 저장(볼일)을 끝냈습니다.
   2. 그런데 문을 잠근 채 변기에 앉아서, 해외 이메일 발송 서버의 응답을 기다리며 30분 동안 유튜브(외부 I/O)를 보고 있습니다!
   3. 화장실 10칸이 꽉 차버렸습니다 (가용 커넥션: 0개).
   4. 밖에서 10초 만에 손만 씻고 나가려는 일반 손님 수백 명(로그인, 상품 검색, 장바구니 클릭)이 화장실 문 앞에서 발을 동동 구릅니다.
   5. 30초 대기 한계(Connection Timeout)를 넘기자 분노한 손님들이 500 에러를 뿜으며 쇼핑몰 전체가 마비됩니다!

✅ 트랜잭션 분리 및 즉시 반환 (OPTIMIZED):
   1. 손님이 화장실에 들어와 0.05초 만에 DB 저장을 끝냅니다.
   2. 즉시 물을 내리고 문을 열고 나와 화장실(DB 커넥션)을 다음 대기자에게 넘겨줍니다!
   3. 이메일 발송(유튜브 시청)은 화장실 밖 로비 의자(비동기 워커 스레드)에 편하게 앉아서 수행합니다.
   4. 화장실 10칸은 0.05초 단위로 쉼 없이 회전하며, 밖에서 기다리는 고객 대기열은 0명으로 완벽히 유지됩니다!
```

---

## 2. 문제 개요

당신은 대규모 이커머스 플랫폼의 코어 백엔드 아키텍트입니다.  
회원가입, 결제 승인, 배치 정산 등 다양한 비즈니스 로직이 실행될 때, 외부 PG사(결제사) 호출이나 외부 알림톡/이메일 발송과 같은 무거운 네트워크 I/O 작업이 수반됩니다.

이때,
1. 외부 I/O까지 통째로 `@Transactional` 단일 블록 안에 넣어 커넥션을 장시간 점유하는 **비대 트랜잭션 모델(NAIVE)**과
2. 순수 DB 작업에만 커넥션을 초단기로 대여하고 즉시 반환하는 **트랜잭션 분리 모델(OPTIMIZED)**

두 아키텍처의 동작 과정을 시뮬레이션하고, 커넥션 풀 고갈로 인한 500 에러 타임아웃 방어 건수(`TIMEOUTS_PREVENTED`)와 평균 대기 시간 단축 효과를 정밀 계측하세요.

---

## 3. 입력 형식

표준 입력(`sys.stdin`)으로 시스템 설정과 요청 스트림이 주어집니다.

```text
POOL_SIZE <pool_size>
CONNECTION_TIMEOUT_MS <timeout_ms>
REQUESTS
<req_id> <type> <db_work_ms> <external_io_ms> <timestamp>
<req_id> <type> <db_work_ms> <external_io_ms> <timestamp>
...
```

### 파라미터 규격
- `POOL_SIZE <pool_size>`: 데이터베이스 커넥션 풀의 최대 가용 커넥션 수 (정수, $1 \le pool\_size \le 1,000$, 기본값 `10`).
- `CONNECTION_TIMEOUT_MS <timeout_ms>`: 커넥션을 대여받기 위해 대기할 수 있는 최대 허용 시간 (ms 단위 정수, 기본값 `30000`).
- `REQUESTS`: 유입되는 비즈니스 요청 목록.
  - `req_id`: 고유 요청 식별자 문자열 (예: `r1`, `r2`).
  - `type`: 요청 성격 (`SLOW` 또는 `FAST`).
  - `db_work_ms`: 순수 DB 쿼리 실행 시간 (ms 단위 양의 정수).
  - `external_io_ms`: 외부 네트워크 API(결제사, 이메일, S3 등) 호출 시간 (ms 단위 $\ge 0$).
  - `timestamp`: 요청이 서버에 도달한 시각 (ms 단위 정수, $\ge 0$).

---

## 4. 시뮬레이션 상세 규칙

요청은 도달 시각(`timestamp`) 순서대로 유입됩니다. (도달 시각이 같을 경우 입력 파일 등장 순서 기준).

### 커넥션 풀 동작 및 대기 큐(FIFO Wait Queue)
- 요청 도착 시 가용 커넥션이 있다면 즉시 1개를 획득(`ACQUIRE`)하여 작업을 시작합니다.
- 가용 커넥션이 없다면 대기 큐(FIFO)에 진입하여 대기합니다.
- 대기 시간이 `CONNECTION_TIMEOUT_MS`를 초과하면 커넥션을 얻지 못하고 즉시 `CONNECTION_TIMEOUT` (500 에러)으로 실패 처리됩니다.
- 커넥션이 반환(`CONN_RELEASE`)되는 순간, 대기 큐의 맨 앞에서 아직 타임아웃되지 않은 요청에게 즉시 커넥션이 인계됩니다.
- 같은 밀리초에 `CONN_RELEASE`와 `REQ_ARRIVE`, `REQ_TIMEOUT`이 겹치는 경우, **반환(`CONN_RELEASE`) $\to$ 타임아웃(`REQ_TIMEOUT`) $\to$ 신규 도착(`REQ_ARRIVE`)** 순서로 우선순위를 가집니다.

### 모델 A: 비대 트랜잭션 모델 (NAIVE)
- 메서드 전체가 단일 트랜잭션으로 묶여 있으므로, 요청 시작부터 외부 I/O가 끝날 때까지 커넥션을 계속 쥐고 있습니다.
- 커넥션 점유 시간(Hold Duration):
  $$\text{hold\_duration} = \text{db\_work\_ms} + \text{external\_io\_ms}$$
- 외부 네트워크가 1~4초간 지연되면 그 시간 동안 커넥션 풀이 완전히 말라버려, 이후 들어오는 빠른 웹 요청들이 줄줄이 `CONNECTION_TIMEOUT`으로 터집니다.

### 모델 B: 트랜잭션 범위 분리 모델 (OPTIMIZED)
- 외부 네트워크 I/O는 트랜잭션 밖에서 수행하며, 순수 DB 쿼리 실행 중에만 커넥션을 점유합니다.
- 커넥션 점유 시간(Hold Duration):
  $$\text{hold\_duration} = \text{db\_work\_ms}$$
- `db_work_ms`가 끝나자마자 **즉시 커넥션을 풀에 반환**합니다. (외부 I/O는 커넥션 없이 독립 수행).
- 커넥션 회전율이 수십~수백 배 상승하여 풀 고갈과 대기 지연이 완벽히 해소됩니다.

---

## 5. 출력 형식

표준 출력(`sys.stdout`)으로 각 요청의 결과와 요약 통계를 출력합니다.

```text
REQ <req_id> NAIVE:<naive_status> OPTIMIZED:<opt_status>
...
SUMMARY NAIVE SUCCESS:<naive_success> TIMEOUTS:<naive_timeouts> PEAK_CONNS:<naive_peak_conns> AVG_WAIT_MS:<naive_avg_wait:.1f>
SUMMARY OPTIMIZED SUCCESS:<opt_success> TIMEOUTS:<opt_timeouts> PEAK_CONNS:<opt_peak_conns> AVG_WAIT_MS:<opt_avg_wait:.1f>
SUMMARY TIMEOUTS_PREVENTED:<naive_timeouts - opt_timeouts>
```

---

## 6. 입출력 예시

### 예시 입력
```text
POOL_SIZE 2
CONNECTION_TIMEOUT_MS 1000
REQUESTS
r1 SLOW 100 2000 0
r2 SLOW 100 2000 10
r3 FAST 10 0 50
r4 FAST 10 0 60
```

### 예시 출력
```text
REQ r1 NAIVE:SUCCESS OPTIMIZED:SUCCESS
REQ r2 NAIVE:SUCCESS OPTIMIZED:SUCCESS
REQ r3 NAIVE:CONNECTION_TIMEOUT OPTIMIZED:SUCCESS
REQ r4 NAIVE:CONNECTION_TIMEOUT OPTIMIZED:SUCCESS
SUMMARY NAIVE SUCCESS:2 TIMEOUTS:2 PEAK_CONNS:2 AVG_WAIT_MS:0.0
SUMMARY OPTIMIZED SUCCESS:4 TIMEOUTS:0 PEAK_CONNS:2 AVG_WAIT_MS:25.0
SUMMARY TIMEOUTS_PREVENTED:2
```

### 결과 해석
- **NAIVE 모델**:
  - `r1`과 `r2`가 2개의 커넥션을 잡고 외부 I/O(2,000ms)가 끝날 때까지 2,100ms 동안 놓아주지 않았습니다.
  - 뒤따라온 빠른 웹 요청 `r3(50ms)`와 `r4(60ms)`는 1,000ms를 넘게 기다려도 커넥션을 얻지 못해 500 `CONNECTION_TIMEOUT`으로 장렬히 폭사했습니다!
- **OPTIMIZED 모델**:
  - `r1`은 100ms 만에 DB 작업을 끝내고 즉시 커넥션을 반환했습니다.
  - `r3`와 `r4`는 대기 시간 불과 50ms 만에 커넥션을 획득하여 `SUCCESS` 처리되었습니다!
  - 2건의 500 에러 타임아웃을 완벽히 방어해 냈습니다.

---

## 7. 제약 조건 및 복잡도 요구사항
- 총 요청 수 $R \le 100,000$.
- 풀 크기 $P \le 1,000$.
- 우선순위 큐(이산 사건 힙)를 활용하여 $O(R \log R)$ 이하의 시간 복잡도로 5.0초 제한 시간 내에 통과해야 합니다.
