# 리눅스 CFS 스케줄러와 CPU 스로틀링의 저주 (Linux CFS Quota & Throttling)

## 문제 설명

쿠버네티스(Kubernetes)나 도커(Docker) 환경에서 마이크로서비스를 운영하는 개발자들이 가장 많이 겪는 미스터리 중 하나는 다음과 같습니다:

> *"모니터링 대시보드를 보면 파드의 CPU 사용률이 20%밖에 안 되는데, 왜 사용자 API 요청의 p99 지연 시간이 100ms씩 튀고 504 Gateway Timeout이 발생하는 걸까요?"*

이 기현상의 주범은 바로 리눅스 커널의 **CFS(Completely Fair Scheduler) CPU 대역폭 제어기(Bandwidth Controller)**와 **CPU 스로틀링(Throttling)**입니다.

쿠버네티스에서 `resources.limits.cpu: "2"`를 설정하면, 리눅스 커널 Cgroup은 이를 100ms 주기(`cpu.cfs_period_us = 100000`)당 200ms의 CPU 런타임 쿼터(`cpu.cfs_quota_us = 200000`)로 제한합니다.

### 💥 멀티스레드의 함정: 25ms 만에 쿼터 탕진
애플리케이션이 톰캣이나 고루틴 등으로 **8개의 워커 스레드**를 돌리고 있다고 가정해 봅시다.
1. 100ms 주기가 시작되는 순간(0ms), 8개의 스레드가 동시에 CPU 연산을 수행합니다.
2. 8개 스레드가 동시에 돌기 때문에 CPU 쿼터는 벽시계 시간의 8배 속도(1us 벽시계당 8us CPU)로 증발합니다.
3. 결국 불과 **25ms($200,000 \div 8$) 만에 이번 100ms 주기에 배정된 200ms CPU 쿼터가 전량 고갈**됩니다!
4. **결과**: 리눅스 커널은 컨테이너 내부의 모든 스레드를 즉시 동결(Freeze/Throttle)시킵니다. 주기가 끝날 때까지 남은 **75ms 동안 단 1개의 스레드도 실행되지 못하고 멍하니 멈춰 서서 대기**해야 합니다.
5. 100ms가 되어 다음 주기가 시작되면 쿼터가 재충전되어 다시 실행되지만, 곧바로 다시 동결되는 악순환이 반복됩니다.

이 문제를 완화하기 위해 최신 리눅스 커널(5.14+)에서는 이전 주기의 미사용 쿼터를 저축하여 일시적 버스트에 활용하는 **CFS Burst(`cpu.cfs_burst_us`)** 기능이 도입되었습니다.

당신은 리눅스 CFS 스케줄러의 쿼터 관리, 스로틀링 감지 및 버스트 저축 메커니즘을 시뮬레이션하는 엔진을 구현해야 합니다.

---

## 시뮬레이션 규칙

### 1. CFS 쿼터 및 스레드 소비 규칙
- **주기 (`period_us`)**: CPU 쿼터가 갱신되는 기본 주기(기본값: `100,000` us = 100ms).
- **쿼터 (`quota_us`)**: 한 주기 동안 컨테이너의 모든 스레드가 합산하여 사용할 수 있는 최대 CPU 시간(기본값: `200,000` us = 2.0 코어).
- **버스트 상한 (`burst_us`)**: 이전 주기의 잉여 쿼터를 저축할 수 있는 최대 버스트 풀 크기(기본값: `0` = 비활성화).
- **활성 스레드 (`threads`)**: 현재 실행을 대기/요청하는 스레드 개수.
  - 활성 스레드가 $T$개일 때, 1us의 벽시계(Wall-clock) 시간이 흐르면 $T$us의 CPU 쿼터가 소진됩니다. ($T=0$이면 CPU 소진 없음)

### 2. 스로틀링(Throttling) 및 주기 마감
- 주기가 시작될 때 잔여 쿼터(`curr_quota_remaining_us`)는 `quota_us + burst_pool_us`로 충전되고, `burst_pool_us`는 0으로 리셋됩니다.
- 스레드가 실행되다가 잔여 쿼터가 0 이하가 되는 순간:
  - 컨테이너는 즉시 **동결(`is_throttled = true`)**됩니다.
  - 해당 주기는 스로틀링된 주기(`curr_period_throttled = true`)로 기록되며, `nr_throttled += 1`이 누적됩니다.
  - 남은 주기가 끝날 때까지 스레드는 실행되지 못하고, 흐른 시간만큼 `throttled_time_us`에 누적됩니다.
- 주기 경계(`period_us`)에 도달하면:
  - 주기가 1회 완료(`nr_periods += 1`)됩니다.
  - 만약 해당 주기에서 스로틀링이 한 번도 발생하지 않고 쿼터가 남았다면:
    - 잉여 쿼터(`unused_quota = curr_quota_remaining_us`)를 버스트 풀에 누적합니다:  
      `burst_pool_us = min(burst_us, burst_pool_us + unused_quota)`
  - 새 주기가 시작되며 `is_throttled = false`로 복구됩니다.

---

## 명령어 명세

모든 명령어는 표준 입력(stdin)으로 한 줄씩 주어지며, 인자는 `key=value` 형태 또는 공백 구분 위치 인자를 지원합니다.

1. **`CONFIG period_us=<int> quota_us=<int> [burst_us=<int>]`**
   - CFS 파라미터를 설정합니다. (기본값: `period=100000, quota=200000, burst=0`)
   - 출력: `CONFIG_OK period_us=<P> quota_us=<Q> burst_us=<B>`

2. **`SET_THREADS <count>`**
   - 활성 실행 스레드 개수를 설정합니다.
   - 출력: `SET_THREADS_OK count=<count>`

3. **`ELAPSE <duration_ms>`**
   - 벽시계 시뮬레이션 시간을 `<duration_ms>` 밀리초(ms)만큼 전진시킵니다.
   - 출력: `ELAPSE_OK duration_ms=<duration_ms>`

4. **`REPORT`**
   - 현재까지의 CFS CPU 통계를 덤프합니다.
   - 스로틀링 비율(`THROTTLED_PERIODS_PCT`)은 지금까지 발생/진행된 총 주기 수 대비 `nr_throttled` 비율(%)을 소수점 둘째 자리까지 표시합니다.
   - 출력 형식:
     ```
     --- CFS_CPU_STAT ---
     NR_PERIODS: <int>
     NR_THROTTLED: <int>
     THROTTLED_PERIODS_PCT: <float:.2f>%
     THROTTLED_TIME_US: <int>
     TOTAL_CPU_TIME_US: <int>
     BURST_POOL_US: <int>
     STATUS: <THROTTLED|RUNNABLE>
     --- END_REPORT ---
     ```

5. **`RESET`**
   - 모든 설정과 누적 상태를 초기 상태로 리셋합니다.
   - 출력: `RESET_OK`

---

## 입출력 예시

### 예시 입력
```
CONFIG period_us=100000 quota_us=200000 burst_us=0
SET_THREADS count=8
ELAPSE duration_ms=100
REPORT
```

### 예시 출력
```
CONFIG_OK period_us=100000 quota_us=200000 burst_us=0
SET_THREADS_OK count=8
ELAPSE_OK duration_ms=100
--- CFS_CPU_STAT ---
NR_PERIODS: 1
NR_THROTTLED: 1
THROTTLED_PERIODS_PCT: 100.00%
THROTTLED_TIME_US: 75000
TOTAL_CPU_TIME_US: 200000
BURST_POOL_US: 0
STATUS: RUNNABLE
--- END_REPORT ---
```
