# Theory #432: 리눅스 커널 KVM vCPU 반가상화 스핀락(PV Spinlocks)과 하이퍼콜 아키텍처

## 1. 개요 및 배경 (Virtualization Concurrency Pathology)

### 1.1 베어메탈 스핀락 vs 가상화 스핀락
스핀락(`spinlock_t`)은 임계 구역(Critical Section)이 수십 나노초 내외로 짧을 때, 스레드를 블로킹(수면)시키고 컨텍스트 스위칭을 유발하는 뮤텍스보다 압도적으로 빠릅니다.
베어메탈 환경에서는 전용 물리 코어가 보장되므로, 락 소유자는 항상 코어에서 명령어를 실행 중입니다.

그러나 클라우드 가상 머신(vCPU) 환경에서는 상황이 근본적으로 달라집니다:
- **물리적 CPU 오버커밋(Oversubscription)**: 호스트 시스템에 32개의 물리 코어(pCPU)가 있을 때, 하이퍼바이저는 수십 개의 VM에 걸쳐 128개 이상의 vCPU를 시분할 스케줄링합니다.
- **스케줄러 계층의 비동기성**: 게스트 OS 커널은 자신이 언제 물리 코어에서 축출(Preempt)될지 알지 못합니다.

### 1.2 가상화 2대 병리 현상: LHP와 LWP
1. **락 홀더 선점 (Lock Holder Preemption, LHP)**:
   - vCPU $A$가 스핀락을 획득하고 임계 구역을 실행하는 도중, 호스트 스케줄러에 의해 vCPU $A$의 타임슬라이스가 끝나 선점당합니다.
   - 다른 vCPU $B$가 동일한 스핀락을 획득하려 시도합니다.
   - vCPU $B$는 vCPU $A$가 호스트에 의해 다시 스케줄링될 때까지(통상 1ms ~ 10ms 동안) 무의미하게 물리 CPU 사이클을 100% 소모하며 헛돕니다.
2. **락 대기자 선점 (Lock Waiter Preemption, LWP)**:
   - 큐 기반 스핀락(qspinlock)에서 MCS 대기 큐의 선두에 있는 vCPU가 선점당하면, 그 뒤에 줄 선 수많은 대기자 vCPU들이 락을 넘겨받지 못하고 연쇄적으로 멈추는 **지연 폭포(Latency Cascade)**가 발생합니다.

---

## 2. KVM PV Queued Spinlocks (qspinlock_paravirt.h)

리눅스 커널은 `CONFIG_PARAVIRT_SPINLOCKS`를 통해 `qspinlock`의 슬로우패스를 반가상화(Paravirtualization) 콜백으로 교체했습니다.

### 2.1 2단계 하이브리드 대기 (Two-Phase Polling & Halt)
대기 vCPU는 무조건 즉시 수면하거나 무한정 회전하지 않고 2단계 알고리즘을 수행합니다:
1. **1단계: 바운디드 스핀(Bounded Spinning)**
   - 대기 vCPU는 `PV_REST_SPIN` (기본 512~2048회) 동안 로컬 캐시라인 플래그를 폴링합니다.
   - 임계 구역이 정상적으로 수 나노초 내에 끝나면 오버헤드 없이 즉시 락을 획득합니다 (Zero-Hypercall Fast Path).
2. **2단계: 자발적 정지(`pv_wait`)**
   - 지정된 루프를 돌았음에도 락이 풀리지 않는다면, 락 소유자가 호스트에 의해 선점당했거나(LHP) 임계 구역이 비정상적으로 길다고 판단합니다.
   - vCPU는 MCS 노드에 `_Q_SLOW_VAL` 비트를 마킹하고 `kvm_pv_wait()`을 호출합니다.
   - 이는 내부적으로 x86 `HLT` 명령어를 실행하여 호스트 VM-Exit을 격발하고, 호스트 물리 CPU를 다른 VM에 즉각 반환합니다.

---

## 3. pv_kick: KVM 전용 하이퍼콜 메커니즘

### 3.1 하이퍼콜 프로토콜 (KVM_HC_KICK_CPU)
수면 중인 vCPU는 스스로 일어날 수 없습니다. 따라서 락을 방금 해제한 vCPU가 깨워주어야 합니다:
```c
void pv_queued_spin_unlock_slowpath(struct qspinlock *lock, u8 locked)
{
    struct pv_node *node;
    ...
    if (READ_ONCE(node->state) == PV_WAITING) {
        /* 대기자가 HLT 상태로 잠들어 있음 */
        pv_kick(node->cpu);
    }
}
```
`pv_kick(cpu)`은 x86 `VMCALL` (또는 AMD `VMMCALL`) 명령어를 통해 호스트 KVM 커널 모듈로 진입합니다:
- 하이퍼콜 번호: `KVM_HC_KICK_CPU` (0x2)
- 파라미터: 깨울 대상 vCPU의 가상 APIC ID
- 호스트 KVM 동작:
  1. 대상 vCPU의 vcpu 스레드를 즉각 `TASK_RUNNING`으로 전이시킵니다.
  2. 대상 vCPU가 다른 물리 코어에서 슬립 중이라면 IPI(Inter-Processor Interrupt)를 발송하여 즉각 깨웁니다.
  3. 대상 vCPU는 HLT에서 깨어나 MCS 락 핸드오프를 수령하고 임계 구역으로 진입합니다.

---

## 4. 하드웨어 지원: Intel PLE vs 반가상화 PV Spinlock

인텔 x86 하드웨어는 VMX 확장에서 **PAUSE-Loop Exiting (PLE)**을 지원합니다:
- 게스트가 연속해서 `PAUSE` 명령어를 `PLE_Window` 사이클 동안 실행하면, 하드웨어가 자동으로 VM-Exit을 일으킵니다.
- **PLE의 한계**: 하이퍼바이저가 누가 락을 쥐고 있는지 알지 못하므로, 무작위로 다른 vCPU를 스케줄링하여 비효율적인 컨텍스트 스위칭 폭풍이 일어납니다.
- **PV Spinlock의 우월성**: 커널 내부에서 MCS 큐를 통해 **정확히 다음 순번의 대기자 vCPU**를 지목하여 `KVM_HC_KICK_CPU`로 핀포인트 기상시키므로 스위칭 낭비가 0에 가깝습니다.

---

## 5. 실무 시스템 최적화 요약

- **`CONFIG_PARAVIRT_SPINLOCKS=y`**: 멀티소켓 클라우드 VM 및 8코어 이상의 가상 머신에서 반드시 활성화해야 하는 필수 옵션입니다.
- **CPU 도둑(Steal Time) 모니터링**: `top`이나 `vmstat`의 `%st`(Steal Time)가 높고 애플리케이션 지연이 급증할 때, PV Spinlocks 통계(`/sys/kernel/debug/kvm/pv_hash_waits`, `pv_hash_kicks`)를 분석하여 LHP 병목을 진단할 수 있습니다.
