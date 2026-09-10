# 심층 시스템 이론: 리눅스 커널 rwsem (`kernel/locking/rwsem.c`) 및 하이브리드 락 스틸링/핸드오프 아키텍처

## 1. 커널 동기화에서 rwsem의 위치와 확장성 병목

리눅스 커널에서 프로세스의 가상 주소 공간(VMA 트리)을 보호하는 `mmap_lock`은 대표적인 `rw_semaphore`입니다. 멀티스레드 애플리케이션에서 수십 개의 스레드가 동시에 페이지 폴트(Page Fault)를 처리할 때는 읽기 잠금(`down_read`)을 획득하고, 동적 메모리 할당(`mmap`/`munmap`) 시에는 쓰기 잠금(`down_write`)을 획득합니다.

### 1) 독점적 스핀락 vs 수면 세마포어의 딜레마
- 스핀락(Spinlock)은 CPU를 양보하지 않고 루프를 돌므로 임계 구역이 극도로 짧을 때 최적이지만, I/O나 페이지 폴트처럼 임계 구역 내에서 잠들 수 있는(Sleepable) 연산에는 사용이 불가능합니다.
- 반면 전통적인 세마포어는 경합 시 즉시 `schedule()`을 호출하여 대기 큐로 들어가므로, 2~5µs의 엄청난 문맥 교환 지연이 발생합니다.

---

## 2. 64비트 원자적 카운트(`atomic_long_t count`) 설계

현대 64비트 x86-64 및 ARM64 커널에서 `rw_semaphore`는 64비트 정수 하나로 락의 모든 상태를 표현합니다:

```
64-bit rwsem count layout:
┌────────────────────────┬───────┬───────┬───────┬────────────────────────┐
│      Bits 63..32       │ Bit 9 │ Bit 8 │ Bit 7 │        Bits 6..0       │
└────────────────────────┴───────┴───────┴───────┴────────────────────────┘
     Active Readers        Rsvd   HANDOFF WAITERS        Writer Locked
```

- **패스트패스 (Fast-path 1-Cycle)**:
  - `down_read`: `atomic_long_add_return(RWSEM_READER_BIAS, &sem->count)`
    하위 비트에 `WRITER_LOCKED`나 `HANDOFF` 플래그가 없으면 단 1클록 만에 획득 성공!
  - `down_write`: `atomic_long_cmpxchg(&sem->count, 0, RWSEM_WRITER_LOCKED)`
    카운트가 0이면 즉시 원자적 획득 성공.

---

## 3. 낙관적 스피닝 (Optimistic Spinning)과 락 가로채기 (Lock Stealing)

슬로우패스로 진입하기 직전, 커널은 `rwsem_optimistic_spin()`을 수행합니다.

### 1) OSQ (Optimistic Spinning Queue) Lock
- 대기 중인 스레드들이 전역 락 변수를 동시에 폴링하면 멀티소켓 NUMA 시스템에서 캐시라인 바운싱(Cacheline Bouncing) 폭풍이 일어납니다.
- 따라서 커널은 Per-CPU 노드로 구성된 **MCS 락(OSQ Lock)**에 줄을 서서, 오직 큐의 맨 앞 스레드 하나만이 실제 `rwsem->owner`의 CPU 상주 여부를 확인하며 스핀합니다.

### 2) 락 가로채기 (Lock Stealing)
- 소유자가 락을 해제하는 순간, 이미 깨어 있는 스피닝 스레드는 대기 큐에 잠들어 있는 스레드가 깨어나기 전에 락을 즉각 낚아챕니다(`cmpxchg` 성공).
- 이를 통해 수면/기상 지연(Sleep/Wakeup Latency)을 완전히 제거하여 초당 잠금 처리량을 최대 5배 이상 끌어올립니다.

---

## 4. 기아 방지: 핸드오프 메커니즘 (`RWSEM_FLAG_HANDOFF`)

락 가로채기가 통제 없이 계속 허용되면, 대기 큐에 잠들어 있는 스레드는 뒤이어 도착하는 스피너들에 의해 영구적으로 락을 뺏기며 기아(Starvation) 상태에 빠집니다.

```
[Lock Stealing vs Hand-off Trade-off]:
Without Handoff: New Spinners keep stealing lock ──> Wait Queue Starvation! (Latency Spike)
With Handoff:    Wait Time > Threshold ──> Set HANDOFF bit ──> Stealing Prohibited!
                 Releasing Thread MUST directly hand lock to Wait Queue Head.
```

1. **시간 임계치 초과**: 대기 큐의 헤드 태스크가 일정 시간(예: 1ms) 이상 대기하면 `RWSEM_FLAG_HANDOFF` 비트를 활성화합니다.
2. **스틸링 원천 차단**: `HANDOFF` 비트가 켜지면 모든 신규 진입 스레드의 `down_read`/`down_write` 및 스핀 획득(`try_spin_acquire`)이 전면 거절됩니다.
3. **직접 인계 (Direct Hand-off)**: 현재 소유자가 락을 반환할 때, 락을 허공에 놓지 않고 대기열 헤드 태스크의 소유로 원자적 양도(`owner = head`)한 뒤 기상시킵니다.

---

## 5. 리더 깨우기 일괄 처리 (Reader Wakeup Batching)

쓰기 락 소유자가 락을 반환할 때 대기 큐의 첫 번째 엔트리가 읽기 요청(`READ`)이라면:
- 쓰기 락과 달리 읽기 락은 무제한 동시성을 지원합니다.
- 따라서 커널은 대기 큐 전두에 대기 중인 모든 연속된 `READ` 요청들을 단일 루프에서 한꺼번에 깨워 동시 실행으로 전이시킵니다 (`rwsem_wake_readers`).
- 이는 읽기 작업이 집중되는 대규모 웹 서버 및 병렬 컴파일 작업에서 극적인 처리량 향상을 보장합니다.

---

## 6. 결론

리눅스 커널의 rwsem은 **"무경합 패스트패스의 극단적 속도"**, **"경합 시 낙관적 스피닝을 통한 컨텍스트 스위치 회피"**, 그리고 **"핸드오프 비트를 통한 공정성 및 기아 방지"**라는 세 가지 상충되는 목표를 완벽하게 조화시킨 엔지니어링의 정수입니다.
