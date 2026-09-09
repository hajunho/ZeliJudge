# 깊이 있는 컴퓨터 과학: 리눅스 CFS 대역폭 제어기와 쿠버네티스 CPU 스로틀링

## 1. 리눅스 CFS(Completely Fair Scheduler)와 cgroup 대역폭 제어

리눅스 커널의 CFS는 가상 실행 시간(`vruntime`)을 기반으로 프로세스 간의 CPU 공평성을 보장합니다.
그러나 컨테이너 가상화(cgroup v1/v2)에서는 공평성 외에도 컨테이너가 소비할 수 있는 최대 CPU 자원을 강제하는 **대역폭 제한(Bandwidth Enforcement)**이 필요합니다.

이를 위해 리눅스 3.2부터 **CFS Bandwidth Controller**가 도입되었습니다:
- 커널 내부 구조체 `cfs_bandwidth`는 고정 주기 타이머(`period_timer`)를 등록합니다.
- 매 주기가 시작될 때 타이머가 발화하여 `cfs_quota_us`만큼의 CPU 시간을 충전합니다.
- 각 CPU 코어의 실행 큐(`cfs_rq`)는 전역 풀에서 실행 시간 슬라이스(기본 5ms, `min_cfs_rq_runtime`)를 인출하여 소비합니다.
- 전역 쿼터가 소진되면, 해당 cgroup에 속한 모든 태스크는 런큐에서 제거(Throttle)되고 `throttled_cfs_rq` 리스트에 갇혀 다음 주기가 올 때까지 동결됩니다.

---

## 2. 거짓 스로틀링(False Throttling)의 수학적 원리

### 2.1 벽시계 시간(Wall-Clock) vs CPU 시간(CPU-Time)
- **벽시계 시간 ($T_{wall}$)**: 사람이 체감하는 물리적 경과 시간.
- **CPU 시간 ($T_{cpu}$)**: 멀티스레드가 병렬로 소비한 CPU 코어 시간의 총합.
  $$T_{cpu} = \sum_{i=1}^{M} t_i \le M \times T_{wall}$$
  ($M$은 동시 실행 중인 활성 스레드 수).

### 2.2 쿼터 조기 고갈과 스톨 발생
컨테이너에 할당된 쿼터가 $Q$, 주기가 $P$일 때, 할당 코어 수는 $C = Q / P$입니다.
만약 호스트의 물리 코어 수 $M$에 맞춰 $M$개의 스레드가 동시에 실행된다면:
$$T_{exhaust} = \frac{Q}{M} = \frac{C \times P}{M} = P \times \frac{C}{M}$$
- 만약 $C = 2$ 코어, $P = 100\,\text{ms}$인데 $M = 16$개의 스레드가 실행된다면:
  $$T_{exhaust} = 100\,\text{ms} \times \frac{2}{16} = 12.5\,\text{ms}$$
- 주기 시작 후 단 **$12.5\,\text{ms}$** 만에 쿼터가 전액 소진됩니다.
- 결과적으로 스레드들은 남은 **$87.5\,\text{ms}$** 동안 아무 일도 하지 못하고 완전히 정지합니다.
- 이 주기가 끝날 때까지 컨테이너의 실제 CPU 사용률은 $C / M = 12.5\%$에 불과한데도, 응답 지연 시간은 $87.5\,\text{ms}$나 지연되는 **거짓 스로틀링(False Throttling)**이 발생합니다.

---

## 3. 업계의 해결책 및 진화

### 3.1 `uber-go/automaxprocs` (Go 언어 생태계)
Go 런타임의 기본 스레드 수 `GOMAXPROCS`는 호스트 노드의 논리 코어 수를 기준으로 설정됩니다.
32코어 노드에서 Limit이 2코어인 Pod가 뜨면 `GOMAXPROCS=32`가 되어 극심한 스로틀링이 발생합니다.
Uber는 `/sys/fs/cgroup/cpu/cpu.cfs_quota_us`와 `cpu.cfs_period_us`를 읽어 런타임 시작 시 자동으로 `GOMAXPROCS = max(1, floor(quota / period))`로 설정하는 라이브러리(`automaxprocs`)를 오픈소스화하여 문제를 해결했습니다.

### 3.2 Java JVM의 cgroup 인식 개선
- Java 8u191 및 Java 11부터 JVM 플래그 `-XX:+UseContainerSupport`가 기본 활성화되었습니다.
- JVM이 cgroup의 CPU 쿼터를 인식하여 GC 스레드와 `ForkJoinPool.commonPool()` 크기를 자동으로 컨테이너 쿼터에 맞춥니다.

### 3.3 리눅스 5.14+ CFS Burst (`cpu.cfs_burst_us`)
리눅스 5.14부터 이전 주기의 미사용 쿼터를 저축할 수 있는 버스트 기능이 공식 커널에 머지되었습니다:
- 유휴(Idle) 상태에서 남은 쿼터의 일부를 `cfs_burst_us` 한도 내에서 누적.
- 다음 주기에 순간적인 멀티스레드 서지가 들어오더라도 저축된 버스트 버퍼를 소진하여 스로틀링 없이 매끄럽게 통과.
