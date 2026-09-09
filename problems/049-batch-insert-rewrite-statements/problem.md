# #049 100만 건 INSERT 쳤더니 새벽 내내 안 끝나요?!: 단건 쿼리 RTT 지옥 vs JDBC 배치 인서트(Batch Insert & rewriteBatchedStatements)

---

## 1. 현실 세계 비유: 벽돌 10만 장을 나르는 인부와 지게차

공사장에 벽돌 10만 장을 날라야 하는 상황을 상상해 보세요.

```text
❌ 초보자의 단건 순차 INSERT (인부가 두 손으로 1장씩 나르기):
   인부가 벽돌 1장을 양손에 들고 공사장까지 걸어가서 내려놓고 돌아옵니다.
   벽돌 1장당 왕복 100미터(네트워크 RTT, Round-Trip Time)를 걸어야 하므로,
   10만 장을 나르면 총 10,000,000미터(1만 km, 서울-런던 거리!)를 걸어야 합니다.
   인부는 새벽 내내 땀을 뻘뻘 흘리며 걷다가 탈진해서 쓰러집니다.

✅ JDBC 배치 인서트 (지게차가 파레트에 1,000장씩 묶어 나르기):
   지게차가 벽돌 1,000장을 파레트에 차곡차곡 쌓은 뒤, 단 1번의 왕복으로 공사장에 싣고 갑니다.
   10만 장을 나르는 데 단 100번의 왕복이면 충분합니다!
   왕복 횟수가 1,000분의 1로 급감하며, 5시간 걸리던 작업이 10초 만에 끝납니다.
```

스프링/JPA를 사용하는 수많은 주니어 개발자와 AI 바이브 코더들이 "대량 데이터를 넣어야지!"라며  
신나게 `repository.saveAll(list)`를 호출합니다.  
그리고 **새벽 2시에 시작한 데이터 마이그레이션이 아침 9시 출근 시간까지 안 끝나서 전사 DB가 마비되는 대참사**를 겪습니다.

엔티티 ID 생성 전략을 `GenerationType.IDENTITY`로 지정해 두었기 때문에,  
**Hibernate가 배치 처리를 완전히 꺼버리고 단건 INSERT를 10만 번 날리는 "네트워크 RTT 지옥"**에 빠졌기 때문입니다!

---

## 2. 문제 개요

당신은 대규모 금융 거래 원장의 야간 정산 배치를 최적화해야 하는 데이터 플랫폼 엔지니어입니다.  
초당 수만 건의 레코드가 유입될 때, 기존의 **JPA IDENTITY 단건 INSERT 모델(NAIVE_IDENTITY)**과  
`rewriteBatchedStatements=true`가 적용된 **JDBC 배치 인서트 모델(BATCH_REWRITE)**을 시뮬레이션하고,  
네트워크 패킷 왕복 횟수 절감률(`RTT_REDUCTION_RATE`)과 작업 속도 가속 배율(`SPEEDUP`)을 정밀 계측하세요.

### 시뮬레이션 상세 규칙

#### 1. 공통 환경
- `NETWORK_RTT_MS <rtt_ms>`: 앱 서버와 DB 간 1회 네트워크 패킷 왕복 시간 (ms, $1 \le rtt\_ms \le 100$).
- `FSYNC_MS <fsync_ms>`: 트랜잭션 커밋 시 DB가 디스크 WAL(Redo Log)에 플러시하는 I/O 오버헤드 시간 (ms, $1 \le fsync\_ms \le 50$).
- `BATCH_SIZE <batch_size>`: 배치 버퍼 크기 ($1 \le batch\_size \le 5,000$).
- 트랜잭션 모드 `current_tx_mode`: 기본값은 `AUTOCOMMIT`. `TX_MODE` 명령으로 `MANUAL_TX`로 전환 가능.

#### 2. 1회 통신당 소요 시간 계산
- `AUTOCOMMIT` 모드: 1회 쿼리/패킷 통신마다 RTT와 디스크 fsync가 매번 발생합니다:
  $$unit\_time = rtt\_ms + fsync\_ms$$
- `MANUAL_TX` 모드: 단일 트랜잭션 내에서 처리되므로 건별 fsync가 생략되고 순수 네트워크 왕복만 발생합니다:
  $$unit\_time = rtt\_ms$$

#### 3. 단건 INSERT 모델 (NAIVE_IDENTITY)
`GenerationType.IDENTITY`로 인해 배치가 무력화되어 레코드 1건마다 개별 SQL과 TCP 패킷을 날립니다.
- `STREAM <count>` 발생 시:
  - 전송 쿼리 수 = $count$개 (네트워크 RTT $count$회 발생).
  - 소요 시간 = $count \times unit\_time$.

#### 4. 배치 인서트 모델 (BATCH_REWRITE)
레코드들을 메모리 버퍼(`batch_size`)에 모아두었다가 묶음(Multi-row)으로 전송합니다.
- `STREAM <count>` 발생 시:
  - 기존 버퍼 잔여량과 합산: $new\_total = batch\_buffer + count$.
  - 플러시 횟수 $flushes = new\_total // batch\_size$.
  - 새로운 버퍼 잔여량 $batch\_buffer = new\_total \% batch\_size$.
  - 네트워크 RTT 발생 횟수 = $flushes$회.
  - 소요 시간 = $flushes \times unit\_time$.
- `FLUSH` 발생 시:
  - 만약 $batch\_buffer > 0$ 이라면:
    - 잔여 레코드들을 1번의 멀티 행 쿼리로 전송 (네트워크 RTT 1회 발생, 소요 시간 $1 \times unit\_time$).
    - $batch\_buffer = 0$으로 리셋.
  - 만약 $batch\_buffer == 0$ 이라면 아무 통신도 발생하지 않습니다.

---

## 3. 입력 형식

```text
NETWORK_RTT_MS <rtt_ms>
FSYNC_MS <fsync_ms>
BATCH_SIZE <batch_size>
EVENTS <E>
TX_MODE <AUTOCOMMIT | MANUAL_TX>
STREAM <count>
FLUSH
... (총 E개의 줄)
```

- `rtt_ms`: 네트워크 RTT 지연 (정수, ms)
- `fsync_ms`: 디스크 fsync 오버헤드 (정수, ms)
- `batch_size`: 배치 버퍼 크기 (정수)
- `E`: 이벤트 줄 수 ($1 \le E \le 30,000$)
- 각 명령:
  - `TX_MODE <AUTOCOMMIT | MANUAL_TX>`: 트랜잭션 모드 변경
  - `STREAM <count>`: 레코드 유입 ($1 \le count \le 100,000$)
  - `FLUSH`: 잔여 버퍼 강제 플러시

---

## 4. 출력 형식

각 `STREAM` 및 `FLUSH` 명령마다 한 줄씩 출력합니다:
- `TX_MODE`:
  ```text
  TX_MODE CHANGED_TO:<mode>
  ```
- `STREAM`:
  ```text
  OP STREAM RECORDS:<count> NAIVE:RTT=<n_rtt>,TIME=<n_time>ms BATCH:RTT=<b_rtt>,TIME=<b_time>ms BUFFER:<buf>/<batch_size>
  ```
- `FLUSH`:
  ```text
  OP FLUSH RECORDS:<flushed_cnt> NAIVE:RTT=0,TIME=0ms BATCH:RTT=<b_rtt>,TIME=<b_time>ms BUFFER:<buf>/<batch_size>
  ```

모든 이벤트 처리 후 마지막 줄에 통계 요약을 출력합니다:
```text
SUMMARY TOTAL_RECORDS:<total> NAIVE_TOTAL_TIME:<n_time>ms BATCH_TOTAL_TIME:<b_time>ms TIME_SAVED:<saved>ms SPEEDUP:<speedup>x RTT_REDUCTION_RATE:<rate>%
```
- `<speedup>`: 작업 속도 향상 배율 $\frac{n\_time}{b\_time}$ (소수점 첫째 자리까지 반올림 표기, 예: `250.0x`). 만약 `b_time == 0`이면 `1.0x`.
- `<rate>`: 네트워크 RTT 절감율 $\frac{n\_rtt - b\_rtt}{n\_rtt} \times 100$ (소수점 첫째 자리까지 반올림 표기, 예: `99.8%`).

---

## 5. 입출력 예시

### 예시 입력 1
```text
NETWORK_RTT_MS 2
FSYNC_MS 5
BATCH_SIZE 500
EVENTS 4
STREAM 1200
TX_MODE MANUAL_TX
STREAM 800
FLUSH
```

### 예시 출력 1
```text
OP STREAM RECORDS:1200 NAIVE:RTT=1200,TIME=8400ms BATCH:RTT=2,TIME=14ms BUFFER:200/500
TX_MODE CHANGED_TO:MANUAL_TX
OP STREAM RECORDS:800 NAIVE:RTT=800,TIME=1600ms BATCH:RTT=2,TIME=4ms BUFFER:0/500
OP FLUSH RECORDS:0 NAIVE:RTT=0,TIME=0ms BATCH:RTT=0,TIME=0ms BUFFER:0/500
SUMMARY TOTAL_RECORDS:2000 NAIVE_TOTAL_TIME:10000ms BATCH_TOTAL_TIME:18ms TIME_SAVED:9982ms SPEEDUP:555.6x RTT_REDUCTION_RATE:99.8%
```

### 설명
- **1번째 스트림 (1,200건, AUTOCOMMIT)**:
  - 건당 $2\text{ms} + 5\text{ms} = 7\text{ms}$ 소요.
  - NAIVE: 1,200번의 RTT 발생 $\to$ 8,400ms 소요.
  - BATCH: 500개씩 2번 플러시(RTT=2회) $\to$ 14ms 소요, 잔여 버퍼 200개 보관.
- **2번째 스트림 (800건, MANUAL_TX)**:
  - 순수 RTT(2ms)만 소요. 기존 버퍼 200개 + 800개 = 1,000개로 딱 2번 플러시(RTT=2회).
- **최종 요약**:
  - 단건 전송은 총 2,000번의 RTT와 10,000ms(10초)가 걸렸지만, 배치 전송은 단 4번의 RTT와 18ms 만에 완료!
  - **네트워크 RTT 99.8% 절감, 작업 속도 555.6배(`555.6x`) 가속**을 달성했습니다.
