# Problem 065: 커넥션 풀 크기의 함정과 리틀의 법칙 (Connection Pool Sizing & Little's Law)

## 문제 설명

대규모 트래픽을 처리하는 백엔드 개발자인 당신의 팀에서 기이한 성능 역전 현상이 발생했습니다:
> "동시 접속자가 늘어나서 DB가 지연되길래, HikariCP의 `maximum-pool-size`를 10개에서 100개로 10배 늘렸습니다.  
> 그런데 빨라지기는커녕, 쿼리 응답 시간이 10ms에서 80ms로 8배나 더 느려지고 DB CPU 사용률이 100%로 치솟았습니다!"

원인은 운영체제와 하드웨어의 물리적 한계인 **CPU 컨텍스트 스위칭(Context Switching) 오버헤드**와 **리틀의 법칙(Little's Law)**을 간과했기 때문입니다.
- DB 서버의 CPU 코어가 4개뿐일 때, 100개의 커넥션이 동시에 쿼리를 실행하면 OS 스케줄러가 수백 번의 스레드 교체(Time-sharing)와 L1/L2 CPU 캐시 무효화(Cache Thrashing)를 일으키며 막대한 연산 자원을 낭비합니다.
- 반면 PostgreSQL과 HikariCP의 권장 공식인 $Pool = Core \times 2 + Spindle$ 에 맞춰 풀 크기를 9개로 제한하면, 쿼리들이 4개의 코어에 집중되어 컨텍스트 스위칭 낭비 없이 최고 속도로 처리됩니다.

당신은 동일한 쿼리 스트림에 대해 **과도한 커넥션 풀(Oversized Pool)**과 **적정 커넥션 풀(Optimal Pool)**의 실행 경과 및 지연 시간(Latency)을 이산 사건 시뮬레이션(Discrete Event Simulation)으로 정밀 비교 분석하는 엔진을 작성해야 합니다.

---

## 시스템 요구사항 및 물리 모델

### 1. 물리적 처리 속도 모델
- DB 서버의 물리 CPU 코어 수: $C$.
- 컨텍스트 스위칭 페널티 계수: $\alpha$.
- 현재 DB에서 동시에 실행 중인 활성 쿼리의 수: $K$.
- 각 쿼리의 초당 진행 속도 $\text{speed}(K)$:
  $$\text{speed}(K) = \begin{cases} 1.0 & \text{if } K \le C \\ \frac{1.0}{(K / C) \times (1.0 + \alpha \times (K - C))} & \text{if } K > C \end{cases}$$
  - $K \le C$: CPU 코어가 충분하므로 컨텍스트 스위칭 없이 100% 정상 속도($\text{speed} = 1.0$)로 진행됩니다.
  - $K > C$: CPU 시분할($(K/C)$)과 스케줄링 오버헤드($(1 + \alpha(K-C))$)로 인해 진행 속도가 급감합니다.

### 2. 커넥션 풀 동작 메커니즘
- 풀 크기: `pool_size`.
- 쿼리 도착 시:
  - 현재 실행 중인 쿼리 수 $K < \text{pool\_size}$ 이면 즉시 커넥션을 획득하여 실행을 시작합니다 (`START = current_time`).
  - 현재 $K == \text{pool\_size}$ 이면 커넥션 풀의 FIFO 대기 큐(`wait_queue`)에서 대기합니다.
- 쿼리 완료 시:
  - 남은 작업량(`work_remaining`)이 0에 도달하면 완료(`END = current_time`)되며 커넥션을 즉시 반환합니다.
  - 대기 큐에서 가장 오래 기다린 쿼리가 즉시 커넥션을 획득하여 실행을 시작합니다.
- 지연 시간: $\text{LATENCY} = \text{END} - \text{arrival\_time}$.

---

## 입력 형식

```text
SYSTEM_CONFIG
CORES <core_count>
OPTIMAL_POOL_SIZE <optimal_size>
OVERSIZED_POOL_SIZE <oversized_size>
PENALTY_ALPHA <alpha>
REQUESTS
<req_id> <arrival_time> <base_duration>
...
```

- `CORES`: DB 서버의 CPU 코어 수 $C$ (1 이상 정수)
- `OPTIMAL_POOL_SIZE`: 적정 커넥션 풀 크기 (보통 $C \times 2 + 1$)
- `OVERSIZED_POOL_SIZE`: 과대 설정된 커넥션 풀 크기
- `PENALTY_ALPHA`: 컨텍스트 스위칭 페널티 계수 (양의 실수)
- `REQUESTS` 이후 줄들: `<req_id> <arrival_time> <base_duration>`
  - `arrival_time`: 도착 시각 (밀리초, 오름차순)
  - `base_duration`: 100% 속도($\text{speed}=1.0$)일 때 필요한 순수 실행 시간 (밀리초)

---

## 출력 형식

각 요청마다 1줄씩 다음 형식으로 출력합니다 (모든 수치는 소수점 둘째 자리까지 표기):
```text
REQ <req_id> OVERSIZED:START=<start>,END=<end>,LATENCY=<lat> OPTIMAL:START=<start>,END=<end>,LATENCY=<lat>
```

모든 요청 처리가 끝난 후, 최종 요약 3줄을 출력합니다:
```text
SUMMARY OVERSIZED AVG_LATENCY:<avg> P99_LATENCY:<p99> MAX_CONCURRENT_RUNNING:<max_k>
SUMMARY OPTIMAL AVG_LATENCY:<avg> P99_LATENCY:<p99> MAX_CONCURRENT_RUNNING:<max_k>
SUMMARY LATENCY_IMPROVEMENT: OPTIMAL_IS_<ratio>X_FASTER (SAVED:<diff>ms)
```
- `P99_LATENCY`: 전체 쿼리 지연 시간을 오름차순 정렬했을 때 $\lceil 0.99 \times N \rceil - 1$ 번째 인덱스의 지연 시간.
- `ratio`: `oversized_avg / optimal_avg` 배율.
- `diff`: `oversized_avg - optimal_avg` 절감 시간.

---

## 입출력 예시

### 예시 1: 4코어 환경 20개 쿼리 동시 유입

**입력:**
```text
SYSTEM_CONFIG
CORES 4
OPTIMAL_POOL_SIZE 9
OVERSIZED_POOL_SIZE 40
PENALTY_ALPHA 0.05
REQUESTS
req-01 0.0 10.0
req-02 0.0 10.0
req-03 0.0 10.0
req-04 0.0 10.0
req-05 0.0 10.0
req-06 0.0 10.0
req-07 0.0 10.0
req-08 0.0 10.0
req-09 0.0 10.0
req-10 0.0 10.0
req-11 0.0 10.0
req-12 0.0 10.0
req-13 0.0 10.0
req-14 0.0 10.0
req-15 0.0 10.0
req-16 0.0 10.0
req-17 0.0 10.0
req-18 0.0 10.0
req-19 0.0 10.0
req-20 0.0 10.0
```

**출력:**
```text
REQ req-01 OVERSIZED:START=0.00,END=90.00,LATENCY=90.00 OPTIMAL:START=0.00,END=28.12,LATENCY=28.12
REQ req-02 OVERSIZED:START=0.00,END=90.00,LATENCY=90.00 OPTIMAL:START=0.00,END=28.12,LATENCY=28.12
REQ req-03 OVERSIZED:START=0.00,END=90.00,LATENCY=90.00 OPTIMAL:START=0.00,END=28.12,LATENCY=28.12
REQ req-04 OVERSIZED:START=0.00,END=90.00,LATENCY=90.00 OPTIMAL:START=0.00,END=28.12,LATENCY=28.12
REQ req-05 OVERSIZED:START=0.00,END=90.00,LATENCY=90.00 OPTIMAL:START=0.00,END=28.12,LATENCY=28.12
REQ req-06 OVERSIZED:START=0.00,END=90.00,LATENCY=90.00 OPTIMAL:START=0.00,END=28.12,LATENCY=28.12
REQ req-07 OVERSIZED:START=0.00,END=90.00,LATENCY=90.00 OPTIMAL:START=0.00,END=28.12,LATENCY=28.12
REQ req-08 OVERSIZED:START=0.00,END=90.00,LATENCY=90.00 OPTIMAL:START=0.00,END=28.12,LATENCY=28.12
REQ req-09 OVERSIZED:START=0.00,END=90.00,LATENCY=90.00 OPTIMAL:START=0.00,END=28.12,LATENCY=28.12
REQ req-10 OVERSIZED:START=0.00,END=90.00,LATENCY=90.00 OPTIMAL:START=28.12,END=56.25,LATENCY=56.25
REQ req-11 OVERSIZED:START=0.00,END=90.00,LATENCY=90.00 OPTIMAL:START=28.12,END=56.25,LATENCY=56.25
REQ req-12 OVERSIZED:START=0.00,END=90.00,LATENCY=90.00 OPTIMAL:START=28.12,END=56.25,LATENCY=56.25
REQ req-13 OVERSIZED:START=0.00,END=90.00,LATENCY=90.00 OPTIMAL:START=28.12,END=56.25,LATENCY=56.25
REQ req-14 OVERSIZED:START=0.00,END=90.00,LATENCY=90.00 OPTIMAL:START=28.12,END=56.25,LATENCY=56.25
REQ req-15 OVERSIZED:START=0.00,END=90.00,LATENCY=90.00 OPTIMAL:START=28.12,END=56.25,LATENCY=56.25
REQ req-16 OVERSIZED:START=0.00,END=90.00,LATENCY=90.00 OPTIMAL:START=28.12,END=56.25,LATENCY=56.25
REQ req-17 OVERSIZED:START=0.00,END=90.00,LATENCY=90.00 OPTIMAL:START=28.12,END=56.25,LATENCY=56.25
REQ req-18 OVERSIZED:START=0.00,END=90.00,LATENCY=90.00 OPTIMAL:START=28.12,END=56.25,LATENCY=56.25
REQ req-19 OVERSIZED:START=0.00,END=90.00,LATENCY=90.00 OPTIMAL:START=56.25,END=66.25,LATENCY=66.25
REQ req-20 OVERSIZED:START=0.00,END=90.00,LATENCY=90.00 OPTIMAL:START=56.25,END=66.25,LATENCY=66.25
SUMMARY OVERSIZED AVG_LATENCY:90.00 P99_LATENCY:90.00 MAX_CONCURRENT_RUNNING:20
SUMMARY OPTIMAL AVG_LATENCY:44.60 P99_LATENCY:66.25 MAX_CONCURRENT_RUNNING:9
SUMMARY LATENCY_IMPROVEMENT: OPTIMAL_IS_2.02X_FASTER (SAVED:45.40ms)
```

**설명:**
- Oversized Pool은 20개 쿼리가 한꺼번에 DB에 진입하여 $K=20$개의 동시 실행 경합을 벌였고, 극심한 컨텍스트 스위칭으로 인해 쿼리 하나당 무려 90.00ms가 소요되었습니다.
- 반면 Optimal Pool은 동시 실행을 최대 9개로 제한하고 나머지는 메모리 큐에서 대기시켰습니다. 그 결과 앞선 9개 쿼리가 28.12ms 만에 신속하게 완료되고, 전체 평균 지연 시간이 **44.60ms로 2.02배(45.40ms 단축) 대폭 개선**되었습니다!
