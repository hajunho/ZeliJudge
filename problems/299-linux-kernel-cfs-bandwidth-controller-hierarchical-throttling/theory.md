# 리눅스 커널 CFS 대역폭 제어기와 CPU 버스트 아키텍처 (CFS Bandwidth Controller & CPU Burst Architecture)

## 1. 개요: 컨테이너 CPU 제한과 CFS의 역할

클라우드 네이티브 환경에서 컨테이너 오케스트레이션(Kubernetes)은 노드의 물리 자원을 안전하게 공유하기 위해 CPU Limits를 설정합니다. 리눅스 커널은 이를 구현하기 위해 **CFS 대역폭 제어기(`kernel/sched/fair.c`)**를 사용합니다.

CFS는 본래 가중치 기반 비례 배분(Proportional Share / `cpu.weight`) 스케줄러이지만, 특정 컨테이너가 다른 컨테이너의 성능을 침해하지 못하도록 상한선(Hard Cap / Bandwidth Limit)을 강제하는 메커니즘이 바로 대역폭 제어기입니다:
- `cpu.cfs_period_us`: 측정 주기 (일반적으로 100ms = 100,000µs).
- `cpu.cfs_quota_us`: 주기 동안 허용된 총 CPU 시간 (예: 2코어 할당 시 200,000µs).

---

## 2. 2단계 런타임 배분 모델: 슬라이스 대여 (Slice Borrowing)

수십 개의 CPU 코어가 단 하나의 전역 쿼터 변수에 직접 원자적(Atomic) 연산을 수행할 경우 극심한 캐시 라인 바운싱(Cache Line Bouncing)과 락 경합이 발생합니다.
이를 방지하기 위해 커널은 2단계 계층 구조를 사용합니다:

```
[cfs_bandwidth (Global Pool: cfs_quota_us)]
                 │
   Slice Refill  │ (min_cfs_rq_runtime = 5ms)
                 ▼
[Per-CPU cfs_rq (Local Slice: 5ms buffer)]
                 │
                 ▼
[Running Tasks on CPU Core]
```

1. 작업이 CPU에서 실행될 때 먼저 로컬 `cfs_rq->runtime_remaining`에서 실행 시간을 차감합니다.
2. 로컬 슬라이스가 0에 도달하면 전역 풀 `cfs_b->runtime`에서 기본 5ms 슬라이스를 일괄 인출(Claim)합니다.
3. 전역 풀마저 고갈되면 커널은 즉시 `throttle_cfs_rq()`를 호출하여 해당 런큐의 모든 태스크를 스케줄러 레드-블랙 트리(RB-Tree)에서 언링크하고 잠재웁니다.

---

## 3. 주기 타이머와 언쓰로틀링 (Period Timer & Unthrottling)

쓰로틀링된 프로세스는 주기 타이머(`period_timer`)가 만료될 때까지 어떠한 CPU 연산도 수행하지 못합니다.
100ms 경계에서 타이머 인터럽트가 발생하면:
1. `cfs_b->runtime`에 다시 `quota_us`가 채워집니다.
2. `distribute_cfs_runtime()` 함수가 호출되어 쓰로틀 상태였던 모든 런큐에 슬라이스를 배분하고 태스크들을 다시 깨웁니다 (`unthrottle_cfs_rq()`).

이로 인해 쿼터가 빡빡하게 설정된 컨테이너는 주기의 초반에 CPU를 몰아 쓰고 후반 수십 밀리초 동안 완전히 멈추는 **주기적 지연 스파이크(Periodic Latency Spikes)** 현상을 겪게 됩니다.

---

## 4. 리눅스 5.14+ CPU 버스트 (`cpu.cfs_burst_us`) 혁신

현실의 웹 서버나 마이크로서비스 트래픽은 균일하지 않고 순간적인 스파이크(Burst)를 보입니다. 이전 주기에서 CPU를 거의 쓰지 않았더라도(예: 10ms/100ms), 다음 주기에 일시적으로 120ms의 요청이 들어오면 기존 CFS는 즉시 20ms 동안 쓰로틀링을 걸어 P99 응답 지연을 급증시켰습니다.

리눅스 5.14 커널에 머지된 **CPU 버스트(`CONFIG_CFS_BANDWIDTH_BURST`)**는 토큰 버킷(Token Bucket) 알고리즘처럼 이전 주기의 미사용 쿼터를 저축할 수 있도록 지원합니다:
$$	ext{burst\_buffer} = \min(	ext{max\_burst\_us}, 	ext{burst\_buffer} + 	ext{unused\_runtime})$$
$$	ext{available\_runtime} = 	ext{quota\_us} + 	ext{burst\_buffer}$$

이를 통해 장기적인 평균 CPU 사용률은 엄격하게 `quota_us` 이하로 유지하면서도, 순간적인 스파이크 시 쓰로틀링 없이 버스트를 허용하여 테일 레이턴시(Tail Latency)를 최대 90% 이상 획기적으로 개선합니다.
