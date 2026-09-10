# Linux Kernel Tree RCU (Read-Copy-Update) 심층 아키텍처 및 유예 기간 이론 분석

## 1. 개요 및 설계 철학

전통적인 상호 배제 기법(뮤텍스, 세마포어, 스핀락, rwlock)은 데이터 구조를 읽을 때도 락을 획득하거나 최소한 공유 캐시라인에 원자적 카운터(`atomic_inc`)를 갱신해야 합니다.
그러나 코어 수가 수십~수백 개로 증가하면, 캐시 일관성 프로토콜(MESI)에 의해 동일 캐시라인이 코어들 사이를 오가며 버스를 마비시키는 **캐시라인 핑퐁(Cacheline Bouncing)**이 발생하여 시스템 전체 확장성이 붕괴합니다.

폴 매케니(Paul E. McKenney)가 리눅스 커널에 완성한 **RCU(Read-Copy-Update)**는 다음의 혁신적 설계로 이 문제를 해결합니다:
1. **읽기 작업자(Readers)**: 원자적 연산이나 락을 일절 사용하지 않고 단순히 포인터를 역참조합니다 ($O(1)$ 사이클).
2. **쓰기 작업자(Writers)**: 원본을 직접 수정하지 않고 사본을 만들어 변경한 뒤, 원자적 포인터 치환(`rcu_assign_pointer`)으로 공개합니다.
3. **메모리 회수(Reclamation)**: 구버전 객체를 읽고 있을 수 있는 모든 리더가 임계 구역을 완전히 빠져나올 때까지 기다린 후 비동기/동기적으로 메모리를 해제합니다.

---

## 2. 유예 기간(Grace Period)과 정지 상태(Quiescent State)

### 2.1 정지 상태 (Quiescent State, QS)
어떤 CPU가 RCU 읽기 측 임계 구역(`rcu_read_lock() ~ rcu_read_unlock()`) 외부에 머물고 있음이 확실한 상태를 뜻합니다:
- 프로세스 컨텍스트 스위치 (`schedule()`)
- 유저 공간 애플리케이션 실행
- CPU 유휴 루프 (`idle`)

### 2.2 유예 기간 (Grace Period, GP)
유예 기간 시작 시점에 이미 존재하던 모든 RCU 읽기 임계 구역이 종료되는 기간입니다.
수학적으로:
> **"시스템의 모든 온라인 CPU가 적어도 한 번 이상의 정지 상태(QS)를 통과했다면, 유예 기간 시작 전에 시작되었던 모든 리더는 반드시 종료되었음이 보장된다."**

---

## 3. 트리 RCU (Tree RCU)의 계층적 확장성

단일 전역 비트마스크를 사용하여 모든 CPU의 QS를 추적하면, 코어 수가 1,024개일 때 QS 보고 자체가 전역 스핀락 경합을 유발합니다.
**트리 RCU(`kernel/rcu/tree.c`)**는 CPU들을 트리 형태(`struct rcu_node`)로 그룹화합니다:

```c
struct rcu_node {
    raw_spinlock_t lock;
    unsigned long qsmask;       /* 현재 노드에서 아직 QS를 보고하지 않은 자식 비트마스크 */
    unsigned long qsmaskinit;
    struct rcu_node *parent;
    int grplo;                  /* 이 노드가 커버하는 최소 CPU ID */
    int grphi;                  /* 이 노드가 커버하는 최대 CPU ID */
};
```

1. 각 CPU는 자신이 속한 리프(Leaf) `rcu_node`의 락만 잡고 자신의 비트를 지웁니다.
2. 리프 노드의 `qsmask`가 0이 되면, 그 노드의 대표자가 부모 노드로 올라가 부모의 `qsmask`에서 해당 리프의 비트를 지웁니다.
3. 이 과정이 루트(Root) 노드에 도달하여 루트의 `qsmask == 0`이 되는 순간, 전역 유예 기간이 만료됩니다.
이 계층 구조 덕분에 락 경합은 $O(\log N)$으로 억제되어 수천 코어에서도 완벽한 선형 확장을 달성합니다.

---

## 4. RCU CPU 스톨 감지기 (RCU Stall Detector)

커널 내부의 버그(무한 루프, 선점 금지 상태에서의 블록, 데드락)로 인해 특정 CPU가 RCU 읽기 임계 구역에서 빠져나오지 못하면:
- 유예 기간이 영원히 끝나지 않아 메모리 콜백(`call_rcu`)이 누적되고 결국 시스템이 OOM에 빠집니다.
- 트리 RCU의 스톨 감지기(`rcu_check_gp_kthread_starvation`)는 설정된 타임아웃(기본 21초) 동안 QS를 보고하지 않은 범인 CPU의 콜스택(`dump_stack`)을 콘솔에 출력하여 개발자가 버그를 즉각 식별할 수 있도록 지원합니다.
