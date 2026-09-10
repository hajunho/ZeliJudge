# 문제 423 심층 이론: 리눅스 커널 rt_mutex 우선순위 상속(Priority Inheritance)과 PREEMPT_RT 실시간 동시성

---

## 1. 우선순위 역전 문제 (Priority Inversion)의 기원과 화성 패스파인더 사고

실시간 시스템(Real-Time Systems)에서 태스크는 엄격한 마감 시간(Deadline)과 결정론적 지연 시간(Deterministic Latency)을 보장받아야 합니다. 그러나 다중 스레드가 상호 배제(Mutual Exclusion)를 위해 락을 공유할 때, 스케줄러의 우선순위 기반 선점 정책과 상호 배제 원리가 충돌하면서 **우선순위 역전**이 발생합니다.

### 화성 패스파인더(Mars Pathfinder, 1997) 실시간 장애
1997년 7월 화성에 착륙한 NASA 패스파인더 로버는 착륙 며칠 만에 주기적으로 지상 관제소와의 통신이 끊어지며 소프트웨어 리셋(Watchdog Timer Reset)이 반복되는 위기에 직면했습니다:
- **정보 버스(Information Bus)**: 센서 데이터 등을 교환하기 위해 뮤텍스로 보호되는 공유 메모리.
- **저우선순위 태스크 (ASI/MET)**: 기상 센서 데이터를 버스에 기록하는 작업 (낮은 빈도, 긴 수행 시간).
- **고우선순위 태스크 (Attitude Control)**: 우주선의 자세 제어를 담당하는 고빈도 실시간 스레드.
- **중간 우선순위 태스크 (Communications Task)**: 지구로 원격 측정 데이터를 전송하는 긴 주기 스레드.

태스크 수행 중, ASI/MET가 버스 뮤텍스를 획득한 상태에서 Communication 태스크가 깨어나 ASI/MET를 선점했습니다. 그 사이 자세 제어 태스크가 버스 뮤텍스를 요청하다가 블록되었습니다. 결과적으로 **자세 제어 태스크(최고 우선순위)**가 **통신 태스크(중간 우선순위)**가 끝날 때까지 무한정 대기하게 되었고, 마감 시간을 놓친 시스템 감시 타이머(Watchdog)가 전체 시스템을 강제 재부팅시켰습니다.

지상 연구진은 탑재된 RTOS(VxWorks)의 뮤텍스 속성에 **우선순위 상속(Priority Inheritance)** 플래그를 원격으로 활성화하여 이 문제를 완벽히 해결했습니다.

---

## 2. 리눅스 PREEMPT_RT와 `rt_mutex` 아키텍처

표준 리눅스 커널의 기본 뮤텍스(`struct mutex`)와 스핀락(`spinlock_t`)은 우선순위 상속을 지원하지 않습니다. 락을 쥐고 있는 스레드가 CPU를 양보하거나 선점당하면 실시간 태스크의 지연 시간이 비결정론적(Non-deterministic)으로 치솟습니다.

리눅스 실시간 패치셋(**PREEMPT_RT**)은 커널 내의 거의 모든 동기화 기본 요소를 **`rt_mutex`** 기반으로 교체합니다:
- 기존 `spinlock_t`가 선점 가능한 `rt_mutex`로 대체됩니다.
- 인터럽트 핸들러가 스레드화(Threaded IRQ)되어 `rt_mutex`를 획득할 수 있게 됩니다.

### `rt_mutex` 핵심 자료구조 (`include/linux/rtmutex.h`, `kernel/locking/rtmutex_common.h`)

```c
struct rt_mutex_base {
    raw_spinlock_t      wait_lock;
    struct rb_root_cached waiters;  /* 우선순위 정렬된 대기자 레드-블랙 트리 */
    struct task_struct  *owner;     /* 현재 락을 소유한 태스크 포인터 */
};

struct rt_mutex_waiter {
    struct rb_node      tree_node;  /* mutex->waiters 트리에 삽입되는 노드 */
    struct rb_node      pi_tree_node; /* task->pi_waiters 트리에 삽입되는 노드 */
    struct task_struct  *task;
    struct rt_mutex_base *lock;
    int                 prio;       /* 대기 시점의 유효 우선순위 */
};
```

각 `task_struct`는 본인이 보유한 락들로 인해 자신에게 걸려 있는 대기자들을 추적하기 위해 `struct rb_root_cached pi_waiters`를 유지합니다.

---

## 3. 전이적 체인 전파 알고리즘 (`rt_mutex_adjust_prio_chain`)

현대 소프트웨어 아키텍처에서는 다중 계층 락 구조가 보편적입니다. 단순히 락의 직속 소유자만 부스팅하는 것으로는 불충분하며, 체인 상의 모든 중간 소유자 태스크들에게 우선순위가 연쇄적으로 상속되어야 합니다.

### 전이적 전파 수학적 정의
체인이 $T_n \xrightarrow{\text{waits on } M_n} T_{n-1} \xrightarrow{} \dots \xrightarrow{\text{waits on } M_1} T_0$ 로 연결되어 있을 때,
새로운 최상위 태스크 $T_{\text{top}}$이 $M_n$을 요청하여 블록되면:

$$\forall i \in \{0, 1, \dots, n-1\}, \quad P_{\text{eff}}(T_i) \leftarrow \min \left( P_{\text{eff}}(T_i), P_{\text{eff}}(T_{\text{top}}) \right)$$

전파는 다음 두 조건 중 하나를 만족할 때 즉시 종료됩니다:
1. 어떤 소유자 $T_k$의 유효 우선순위가 이미 상속받을 우선순위보다 높거나 같을 때 ($\le$).
2. 소유자 $T_k$가 어떠한 다른 락에도 블록되어 있지 않고 현재 실행(Runnable) 가능한 상태일 때.

---

## 4. 대기-그래프(Wait-For-Graph) 순환과 데드락 탐지

우선순위 상속 체인을 순회하는 도중, 탐색 경로가 이미 지나온 태스크나 최초 요청 태스크 자신으로 회귀하는 경우, 이는 상호 대기 순환(Circular Wait)이 발생했음을 의미합니다.

리눅스 커널의 `rt_mutex_adjust_prio_chain()`은 전파 루프 내부에서 방문 노드를 검사하여 순환이 발견되면 즉시 탐색을 중단하고 `-EDEADLK` 에러 코드를 반환합니다. 이를 통해 커널 스택 오버플로우(무한 재귀)를 방지하고 시스템 프리징을 원천 차단합니다.

---

## 5. 락 핸드오프(Lock Handoff)와 락 스틸링(Lock Stealing)

소유자가 `rt_mutex_unlock()`을 호출할 때의 동작은 성능 최적화를 위해 두 가지 경로로 나뉩니다:
1. **락 핸드오프 (Direct Handoff)**:
   락 소유권을 대기 큐의 최우선순위 대기자(`top_waiter`)에게 원자적으로 직접 양도합니다. 이전 소유자는 자신의 유효 우선순위를 원래 상태로 디부스팅(Deboost)합니다.
2. **락 스틸링 (Lock Stealing)**:
   락이 풀리는 찰나에 새로 진입한 고우선순위 스레드가 기존 대기자보다 우선순위가 높다면, 락을 가로채어 컨텍스트 스위칭 지연(Context Switch Latency)을 극소화하는 고성능 패스트패스 메커니즘입니다.

---

## 6. 결론

리눅스 커널의 `rt_mutex`는 실시간 로보틱스, 산업 제어, 자동차 자율주행(AUTOSAR / ROS2), 금융 HFT(High-Frequency Trading) 시스템 등 초저지연과 시간 결정성이 절대적으로 요구되는 도메인에서 시스템 신뢰성을 보장하는 가장 필수적인 락 엔진입니다.
