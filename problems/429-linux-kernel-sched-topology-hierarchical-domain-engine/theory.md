# 문제 429 심층 이론: 리눅스 커널 sched_domain 계층 토폴로지와 NUMA 캐시 친화도 로드 밸런싱

---

## 1. 현대 서버의 이종 캐시/메모리 위계 (Memory Hierarchy)

현대 멀티코어 서버(AMD EPYC, Intel Xeon, Ampere Altra)는 단일 프로세서 버스에 연결된 균일한 구조가 아닙니다:
- **SMT (Simultaneous Multithreading)**: 단일 물리 코어의 정수 연산기, 부동소수점 유닛, L1 명령어/데이터 캐시(32KB~64KB), L2 캐시(512KB~1MB)를 2개 이상의 하드웨어 스레드가 공유합니다.
- **MC (Multi-Core / LLC)**: 동일 다이 내부의 여러 코어가 수십~수백 메가바이트의 공유 L3 캐시(Last-Level Cache)를 공유합니다. 코어 간 통신 지연은 수 나노초($\approx 10\text{ns}$) 수준입니다.
- **NUMA (Non-Uniform Memory Access)**: 서로 다른 CPU 소켓이나 NUMA 노드 간 통신은 점대점 상호연결 인터페이스(UPI/Infinity Fabric)를 경유해야 하므로, 지연 시간이 로컬 메모리 접근 대비 1.5배~3배($\approx 100\text{ns}$) 이상 증가하고 상호연결 대역폭의 병목을 유발합니다.

리눅스 커널은 이러한 하드웨어 토폴로지를 소프트웨어 계층 구조인 **스케줄 도메인(`sched_domain`)**과 **스케줄 그룹(`sched_group`)**으로 모델링합니다.

---

## 2. 스케줄 도메인(`sched_domain`)과 스케줄 그룹(`sched_group`) 아키텍처

커널 부팅 시 `build_sched_domains()`(`kernel/sched/topology.c`)는 각 CPU마다 계층적 도메인 링크를 구축합니다:

```c
struct sched_domain {
    struct sched_domain *parent;   /* 상위 도메인 (SMT -> MC -> NUMA) */
    struct sched_group  *groups;   /* 순환 연결 리스트로 구성된 하위 그룹 */
    unsigned int        min_interval; /* 밸런싱 최소 주기 (ms) */
    unsigned int        max_interval; /* 밸런싱 최대 주기 (ms) */
    unsigned int        imbalance_pct;/* 불균형 허용 퍼센트 (117% ~ 150%) */
    unsigned int        cache_nice_tries;
    unsigned long       flags;        /* SD_BALANCE_NEWIDLE, SD_SHARE_PKG_RESOURCES 등 */
};
```

각 도메인 레벨의 속성은 하드웨어 특성에 따라 다르게 튜닝됩니다:
- **SMT 도메인**: `min_interval = 1ms`, `flags = SD_SHARE_CPUCAPACITY | SD_SHARE_PKG_RESOURCES`. 파이프라인 자원 경합을 해소하기 위해 매우 민첩하게 동작.
- **NUMA 도메인**: `min_interval = 32ms~128ms`, 높은 `imbalance_pct`. 원격 노드로의 잦은 태스크 이동(Ping-pong migration)을 엄격히 차단.

---

## 3. 부하 불균형 산출과 캐시 친화도(Cache Affinity) 수학적 모델

CPU $i$가 유휴 상태가 되었을 때(`newidle_balance()`), 스케줄러는 도메인 트리를 상향 순회하며 부하를 가져올 바쁜 그룹을 탐색합니다.

### 3.1 부하 불균형 산출 공식
그룹 $A$와 유휴 CPU가 속한 그룹 $B$ 간의 부하 차이는 다음과 같이 정의됩니다:
$$\text{Imbalance} = \frac{\text{Load}(A) - \text{Load}(B)}{2}$$
- NUMA 도메인에서는 원격 메모리 마이그레이션 페널티 비용을 고려하여 $\text{Imbalance} \ge \tau_{\text{numa}}$ 일 때만 마이그레이션을 승인합니다.

### 3.2 캐시 핫니스(Cache Hotness)와 마이그레이션 비용
태스크 $T$가 CPU $A$에서 마지막으로 실행된 시각을 $t_{\text{last}}$라 할 때, 현재 시각 $t_{\text{curr}}$과의 차이:
$$\Delta t = t_{\text{curr}} - t_{\text{last}}$$
- 만약 $\Delta t < \tau_{\text{cache\_hot}}$ (통상 `sysctl_sched_migration_cost = 500,000ns`):
  태스크의 워킹 세트가 CPU $A$의 L1/L2 캐시에 아직 남아 있으므로, 다른 코어로 이주하면 대량의 캐시 미스(Cold Cache Penalty)가 발생합니다.
- 따라서 대상 CPU가 완전 유휴(`idle_load == 0`)가 아니라면 마이그레이션을 거부하고 스케줄러는 해당 태스크의 지역성(Locality)을 보존합니다.

---

## 4. SMT 자원 스케줄링 전략: Spreading vs Packing

SMT 환경에서는 두 개의 독립된 스레드가 단일 물리 코어의 실행 파이프라인을 공유하므로, 두 스레드가 모두 CPU 집약적 연산을 수행하면 개별 스레드의 IPC(Instructions Per Cycle)는 단일 코어 대비 최대 40~50%까지 저하될 수 있습니다.

따라서 리눅스 스케줄러는 다음과 같은 **확산(Spreading) 우선 정책**을 채택합니다:
1. 새로운 태스크가 진입하거나 부하 분산을 수행할 때, 이미 한 스레드가 점유 중인 코어의 형제 SMT 스레드보다 **완전히 유휴 상태인 다른 물리 코어(Idle Core)**를 최우선으로 선택합니다.
2. 시스템 부하가 전체 물리 코어 수를 초과할 때만 형제 SMT 스레드로 태스크를 패킹(Packing)하여 CPU 처리량을 극대화합니다.

---

## 5. 결론

리눅스 커널의 계층형 스케줄 도메인은 현대 이종 멀티코어 및 거대 NUMA 시스템에서 시스템 전체의 처리량(Throughput)과 개별 태스크의 캐시 지역성(Latency & Cache Locality) 사이의 최적 균형점을 찾아내는 정교한 운영체제 제어 공학의 결정체입니다.
