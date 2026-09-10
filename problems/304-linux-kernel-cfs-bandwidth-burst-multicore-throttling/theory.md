# 이론 정리: 리눅스 커널 CFS 대역폭 컨트롤러와 CPU 버스트(Burst) 최적화 아키텍처

## 1. 컨테이너 CPU 제한과 CFS Quota의 딜레마

쿠버네티스에서 Pod의 `resources.limits.cpu: "1"`을 설정하면, 컨테이너 런타임은 CFS Bandwidth Controller를 통해 다음 Cgroup 매개변수를 적용합니다:
- `cpu.cfs_period_us = 100000` (100ms)
- `cpu.cfs_quota_us = 100000` (100ms)

이 설정은 컨테이너가 100ms마다 최대 100ms(1코어 100%)의 CPU 시간만 사용하도록 강제합니다.

그러나 실무 프로덕션 환경에서 마이크로서비스는 다음과 같은 치명적인 **불필요한 쓰로틀링(Unwanted Throttling)** 문제를 겪었습니다:
- 100ms 주기의 처음 20ms 동안 멀티스레드 요청이 쏟아져 4개 코어가 각각 25ms씩 CPU를 소비하여 합계 100ms 쿼터를 소진함.
- 남은 80ms 동안 전역 쿼터가 0이 되어 컨테이너의 모든 스레드가 일시 정지(Throttled)됨.
- 다음 주기(100ms 후)가 시작될 때까지 수십 밀리초 동안 API 응답 지연(Tail Latency Spike)이 급증함.

---

## 2. 멀티코어 슬라이스 대여(Slice Borrowing) 메커니즘

모든 CPU 코어가 단일 전역 쿼터 카운터에 매 클록마다 접근하면 극심한 락 경합(Spinlock Contention)이 발생합니다.
리눅스 커널(`kernel/sched/fair.c`)은 이를 방지하기 위해 **슬라이스 대여(Slice Borrowing)** 모델을 사용합니다:

```
[ 전역 cfs_bandwidth 쿼터 풀 (예: 100ms) ]
      │               │               │
      │ 5ms 슬라이스  │ 5ms 슬라이스  │ 5ms 슬라이스
      ▼               ▼               ▼
 [ cfs_rq (CPU 0) ] [ cfs_rq (CPU 1) ] [ cfs_rq (CPU 2) ]
   (로컬 소비)     (로컬 소비)     (로컬 소비)
```

1. 각 코어의 로컬 런큐(`cfs_rq`)는 태스크를 실행할 때 `cfs_b->runtime`에서 `sched_cfs_bandwidth_slice`(기본 5,000μs)를 대여해 옵니다.
2. 로컬 슬라이스가 소진되면 다시 전역 풀에서 5ms를 요청합니다.
3. 전역 풀에 남아있는 쿼터가 0 이하이면 대여가 거부되고, 해당 코어의 `cfs_rq`는 `throttle_cfs_rq()`에 의해 즉시 동결됩니다.

---

## 3. 리눅스 5.14+의 구원: CFS Burst (`cpu.cfs_burst_us`)

2021년 리눅스 커널 5.14에 머지된 **CFS Burst** 기능은 사용하지 않은 잉여 쿼터를 다음 주기로 이월(Carry-over)할 수 있도록 허용합니다:

```
[ 주기 1: 유휴 상태 ]
- 할당 쿼터: 100ms, 실제 사용: 40ms ──► 60ms 잉여 발생!
- 버스트 버퍼(최대 50ms)에 50ms 적립 (10ms는 폐기).

[ 주기 2: 트래픽 스파이크 인입 ]
- 기본 쿼터(100ms) + 이월 버스트(50ms) = [ 총 150ms 가용 런타임 확보! ]
- 150ms 동안 쓰로틀링 없이 트래픽 폭주를 완벽히 소화!
```

### 핵심 수식 및 동작 규칙:
- **버스트 적립**: $\text{Burst}_{\text{accum}} = \min(\text{max\_burst\_us}, \text{Burst}_{\text{prev}} + \text{Unused}_{\text{runtime}})$
- **주기 시작 시 충전 런타임**: $\text{Runtime}_{\text{replenish}} = \text{quota\_us} + \text{Burst}_{\text{accum}}$
- **안전성 보장**:
  - 장기적으로 볼 때 컨테이너의 평균 CPU 사용량은 원래 설정된 `quota / period`를 초과할 수 없습니다. (버스트는 오직 이전에 아껴둔 쿼터의 범위 내에서만 인출 가능하기 때문입니다.)
  - 이로써 다중 테넌트(Multi-tenant) 클러스터에서 이웃 노드의 CPU를 독점하지 않으면서도 스파이크 트래픽의 P99 지연시간을 최대 90%까지 단축시킵니다.

---

## 4. 실무 클라우드 엔지니어링 시사점

- **Uber, 메타, 구글의 실측 결과**:
  - 전통적인 CFS Quota 환경에서 P99 응답 지연의 주원인은 CPU 절대량 부족이 아니라 짧은 밀리초 단위의 미세 쓰로틀링(Micro-throttling)이었습니다.
  - `cpu.cfs_burst_us`를 적절히 설정(예: 쿼터의 20%~50%)하면 컨테이너 리소스를 증설하지 않고도 쓰로틀링 발생 빈도를 거의 0으로 억제할 수 있습니다.
