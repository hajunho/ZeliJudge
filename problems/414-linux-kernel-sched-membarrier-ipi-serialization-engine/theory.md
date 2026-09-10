# 이론 문서 414: Linux 커널 동시성 및 스케줄링 membarrier(2) 아키텍처와 코어 직렬화 내부 원리

## 1. 개요 및 배경 (Historical Context & Motivation)

현대 SMP(Symmetric Multiprocessing) 아키텍처에서 메모리 일관성 모델은 하드웨어 성능을 극대화하기 위해 **완화된 메모리 순서(Relaxed Memory Ordering)**를 채택하고 있습니다.
x86 아키텍처는 TSO(Total Store Order)를 따르며 스토어-로드 순서 역전(Store-Load Reordering)을 허용하고, ARM64 및 RISC-V 아키텍처는 약한 순서(Weak Ordering)를 채택하여 컴파일러와 하드웨어 파이프라인이 임의의 로드와 스토어를 자유롭게 재정렬할 수 있도록 허용합니다.

### 1.1 비대칭 동기화 문제 (Asymmetric Synchronization Problem)
고성능 런타임 환경에서는 **읽기 빈도와 쓰기 빈도 사이의 극단적인 불균형**이 발생합니다:
- **URCU (User-space Read-Copy Update)**: 읽기 스레드는 락이나 원자적 명령어 없이 포인터를 역참조하여 공유 데이터를 읽습니다. 초당 수천만 번 실행됩니다.
- **JIT 컴파일러 (V8, JVM, WebKit)**: 기계어 코드가 생성되면 수억 번 실행되지만, 최적화 기계어 코드 덮어쓰기나 역최적화(Deoptimization) 가드 패칭은 극히 드물게 발생합니다.

만약 읽기 스레드가 공유 데이터를 읽을 때마다 메모리 배리어(`mfence`, `dmb ish`)를 실행하거나 동기화 락(`pthread_mutex_t`)을 획득해야 한다면, 현대 수십 코어 CPU에서 캐시 라인 바운싱(Cache Line Bouncing)과 파이프라인 스톨로 인해 단일 스레드 대비 심각한 성능 저하가 발생합니다.

이를 해결하기 위해 등장한 개념이 **메모리 장벽 전가(Barrier Offloading)**입니다:
> "읽기 스레드는 완벽한 0ns (무장벽, Zero-Barrier)로 실행하고, 극히 드물게 발생하는 쓰기 스레드가 커널을 통해 원격 읽기 코어들에 강제로 메모리 장벽을 주입한다."

이 메커니즘을 표준 POSIX 인터페이스로 공식 구현한 시스템 호출이 바로 리눅스 커널의 `membarrier(2)`입니다.

---

## 2. membarrier(2) 커널 내부 아키텍처 (`kernel/sched/membarrier.c`)

### 2.1 커맨드 상태 머신 및 등록 절차

`membarrier(2)` 시스템 호출은 무분별한 전역 IPI로 인한 서비스 거부(DoS) 공격 및 성능 저하를 방지하기 위해 엄격한 사전 등록 메커니즘을 강제합니다:

```
                  +-----------------------------------+
                  |        초기 상태 (state = 0)       |
                  +-----------------------------------+
                       |                           |
   REGISTER_PRIVATE_EXPEDITED          REGISTER_PRIVATE_EXPEDITED_SYNC_CORE
                       |                           |
                       v                           v
          +-------------------------+ +----------------------------------+
          | state |= 1 (PRIVATE)    | | state |= 2 (PRIVATE_SYNC_CORE)   |
          +-------------------------+ +----------------------------------+
```

1. **미등록 상태에서의 방어**:
   - 프로세스가 `MEMBARRIER_CMD_REGISTER_PRIVATE_EXPEDITED`를 호출하지 않고 곧바로 `MEMBARRIER_CMD_PRIVATE_EXPEDITED`를 호출하면, 커널은 `mm->membarrier_state`를 확인한 뒤 즉시 `-EPERM` (`-1`) 에러를 반환합니다.
   - 이는 스케줄러가 해당 `mm`을 인식하고 있지 않은 상태에서 불필요한 IPI를 발송하는 것을 원천 차단합니다.

2. **`MEMBARRIER_CMD_GLOBAL` vs `MEMBARRIER_CMD_PRIVATE_EXPEDITED`**:
   - `GLOBAL`: 시스템 내 모든 온라인 비유휴(Non-idle) CPU에 IPI를 브로드캐스트합니다. 커널 권한이 필요하지 않으나 전체 시스템의 인터럽트 지연을 유발합니다.
   - `PRIVATE_EXPEDITED`: 동일한 메모리 디스크립터(`mm_struct`)를 공유하는 활성 CPU들만을 `smp_call_function_many` 대상 마스크(`cpumask`)로 계산하여 선별적으로 IPI를 발송합니다.

---

## 3. JIT 컴파일러와 `SYNC_CORE` 명령어 직렬화

일반적인 메모리 장벽(`smp_mb()`)은 데이터 캐시와 스토어 버퍼의 가시성을 보장하지만, **CPU의 명령어 파이프라인(Instruction Pipeline)과 프리페치 큐(Prefetch Queue)**까지 플러시하지는 못합니다.

### 3.1 자기 수정 코드(Self-Modifying Code)와 JIT의 위기
현대 CPU(x86, ARM)는 분기 예측(Branch Prediction)과 공격적인 명령어 프리페칭을 수행합니다. JIT 컴파일러가 어떤 메모리 주소의 기계어 코드 바이트를 수정했을 때:
- 원격 코어가 이미 수정 전의 구버전 명령어 바이트를 프리페치 큐나 L1 Instruction Cache에 로드해 두었다면, 수정된 코드가 아닌 구버전 코드를 실행하여 심각한 충돌(Crash)이나 런타임 불일치가 발생할 수 있습니다.

### 3.2 `MEMBARRIER_CMD_PRIVATE_EXPEDITED_SYNC_CORE`의 해결책
이 커맨드는 원격 코어에 IPI를 전송하여 다음과 같은 하드웨어 명령어를 강제 실행합니다:
- **x86**: 직렬화 명령어(`cpuid` 또는 인라인 복귀 `iret`)를 실행하여 명령어 디코더 및 프리페치 파이프라인을 완전히 비웁니다.
- **ARM64**: `isb` (Instruction Synchronization Barrier) 명령어를 실행하여 파이프라인을 플러시하고 L1I 캐시와 명령어 버퍼를 재동기화합니다.

이를 통해 고성능 자바스크립트 엔진(V8)이나 JVM은 비용이 큰 프로세스 정지(Stop-the-world) 없이 백그라운드 스레드에서 생성한 JIT 기계어 코드를 즉시 안전하게 메인 실행 스레드에 반영할 수 있습니다.

---

## 4. 스케줄러 문맥 교환 연계 (`finish_task_switch()`)

IPI 기반 동기화의 가장 치명적인 코너 케이스는 **"IPI가 전송되는 순간에 대상 스레드가 CPU에서 스케줄 아웃(Context Switch Out)되는 경우"**입니다.

리눅스 커널은 이를 해결하기 위해 `kernel/sched/core.c`의 `finish_task_switch()`에 정교한 배리어 로직을 내장하고 있습니다:

```c
static inline void membarrier_task_switch(struct task_struct *prev,
                                          struct task_struct *next)
{
    struct mm_struct *prev_mm = prev->mm;
    struct mm_struct *next_mm = next->mm;

    if (atomic_read(&next_mm->membarrier_state) & MEMBARRIER_STATE_PRIVATE_EXPEDITED) {
        smp_mb(); /* 스케줄러 진입 시 메모리 장벽 보장 */
    }
}
```

- 스레드가 CPU에 다시 스케줄 인(Schedule In)될 때, 해당 스레드의 `mm->membarrier_state`에 프라이빗 비트가 설정되어 있다면 커널은 자동으로 완전 메모리 장벽(`smp_mb()`)을 실행합니다.
- 따라서 IPI 발송 시점에 런큐에 잠들어 있던 스레드라 할지라도, 깨어나서 실행을 재개하는 즉시 최신 메모리 상태를 완벽하게 관측할 수 있습니다.

---

## 5. 성능 및 비용 수학적 모델

전체 시스템에서 읽기 연산의 수를 $N_R$, 쓰기 연산의 수를 $N_W$ ($N_R \gg N_W$)라고 할 때:

### 5.1 전통적 배리어 방식의 총 비용
$$	ext{Cost}_{	ext{traditional}} = N_R \cdot T_{	ext{barrier}} + N_W \cdot T_{	ext{barrier}}$$
여기서 $T_{	ext{barrier}} pprox 10 \sim 30	ext{ns}$ 이므로, $N_R = 10^8$ 일 때 엄청난 성능 손실이 누적됩니다.

### 5.2 membarrier(2) 무장벽 방식의 총 비용
$$	ext{Cost}_{	ext{membarrier}} = N_R \cdot 0 + N_W \cdot (T_{	ext{syscall}} + T_{	ext{IPI}} \cdot |\mathcal{C}_{	ext{target}}|)$$
여기서 $T_{	ext{syscall}} pprox 300	ext{ns}$, $T_{	ext{IPI}} pprox 1 \sim 2\mu	ext{s}$ 이지만, $N_W$가 작기 때문에 전체 시스템 처리량이 최대 30%~50% 향상됩니다.
