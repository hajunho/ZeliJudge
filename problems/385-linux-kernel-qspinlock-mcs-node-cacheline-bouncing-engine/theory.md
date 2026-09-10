# Theory: Linux Kernel Queued Spinlock (qspinlock) & Cache Coherence Scalability (`kernel/locking/qspinlock.c`)

## 1. 멀티코어 동기화의 역사와 캐시라인 바운싱 병목

초기 SMP(대칭형 다중 처리) 시스템에서 리눅스 커널은 단순 **Test-and-Set / TAS 스핀락**을 사용했습니다. 이후 공정성(Fairness)을 보장하기 위해 줄서기 번호표 방식의 **티켓 스핀락(Ticket Spinlock)**이 도입되었습니다.

### 1.1 티켓 스핀락의 $O(N^2)$ 캐시라인 바운싱 재앙
티켓 스핀락에서 각 CPU는 자신의 `my_ticket`을 발급받은 뒤, 공통 메모리 주소의 `now_serving` 필드를 지속적으로 읽으며 폴링합니다.
- 코어 수 $N$이 증가할수록, 락 해제자 코어가 `now_serving++`을 수행하는 순간 MESI/MOESI 캐시 일관성 프로토콜에 의해 대기 중인 모든 $N-1$개 코어의 L1/L2 캐시라인이 일제히 **Invalidate**됩니다.
- 즉시 $N-1$개 코어가 상호연결 버스(QPI, UPI, Infinity Fabric)를 통해 새 값을 가져오기 위해 경쟁적인 Read-Shared 트랜잭션을 발생시킵니다.
- 락 핸드오프 1회당 $O(N)$ 버스 트랜잭션, 총 $N$회 경합 시 $O(N^2)$ 트래픽이 발생하여 수십~수백 코어 NUMA 머신에서 CPU 가동률이 버스 스톨(Interconnect Saturation)로 급락합니다.

---

## 2. MCS 락(Mellor-Crummey and Scott)과 qspinlock의 통합

1991년 발표된 MCS 락은 각 대기 스레드가 고유한 큐 노드를 할당받아 자신의 **로컬 캐시라인(Local Variable)**만을 폴링하도록 설계되었습니다. 선행 노드가 해제될 때 직후 대기자의 노드 플래그 하나만 갱신하므로 버스 트래픽이 정확히 $O(1)$로 억제됩니다.

그러나 순수 MCS 락은 포인터 크기(64비트 기준 8~16바이트)가 커서 리눅스 커널의 기본 `spinlock_t`(크기 4바이트 요구)에 들어갈 수 없었습니다.

### 2.2 리눅스 qspinlock(Queued Spinlock)의 기술적 도약
Waiman Long과 Peter Zijlstra 등이 설계한 qspinlock은 MCS 락의 $O(1)$ 로컬 폴링 장점을 유지하면서 정확히 **32비트(4바이트)** 락 워드에 압축 인코딩하는 혁신을 이뤄냈습니다:

```c
typedef struct qspinlock {
    union {
        atomic_t val;
        struct {
            u8    locked;
            u8    pending;
        };
        struct {
            u16   locked_pending;
            u16   tail;
        };
    };
} run_qspinlock_t;
```

1. **Locked 바이트 (Bits 0..7)**:
   - 락 보유 상태 플래그. `_Q_LOCKED_VAL = 1`.
2. **Pending 비트 (Bit 8)**:
   - 2번째 대기자를 위한 고속 패스.
   - MCS 노드를 할당하지 않고도 2번째 코어가 메인 락 워드의 locked 바이트만을 감시할 수 있도록 허용하여 지연 시간을 극소화합니다.
3. **Tail 필드 (Bits 16..31)**:
   - 3번째 이상의 대기자가 진입할 때 활성화됩니다.
   - 64비트 포인터 주소를 직접 저장하는 대신, Per-CPU MCS 노드 인덱스인 `(cpu_id << 2) | nesting_idx` (16비트)만을 저장합니다.
   - 커널은 최대 $2^{14} = 16,384$개의 CPU 코어와 코어당 4단계 중첩 실행 컨텍스트(Task, Softirq, Hardirq, NMI)를 지원합니다.

---

## 3. 알고리즘 흐름과 상태 전이 매트릭스

```
[Uncontended Lock (val = 0x0)]
          |
   (cmpxchg val: 0 -> 1)
          v
[Holder Acquires (val = 0x1)]
          |
   (2nd CPU arrives: pending = 1)
          v
[Pending Waiter (val = 0x101)]
          |
   (3rd+ CPU arrives: tail = (cpu<<2)|idx)
          v
[MCS Queue Formed (val = (tail<<16) | 0x101)]
          |
   (Holder releases: locked = 0)
          v
[Pending Waiter takes lock: locked = 1, pending = 0]
          |
   (MCS Head transitions to wait on locked_pending)
          |
   (Pending releases: MCS Head acquires lock, notifies successor)
```

이와 같은 정교한 설계를 통해 리눅스 커널은 수백 코어 서버에서도 선형에 가까운 락 처리량과 완벽한 캐시 일관성 분리를 실현합니다.
