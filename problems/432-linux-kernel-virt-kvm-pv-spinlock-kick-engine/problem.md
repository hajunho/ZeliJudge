# Problem #432: 리눅스 커널 가상화 & 동시성: KVM vCPU 반가상화 스핀락(PV Spinlocks) 및 PV Kick/Halt 기반 락 홀더 선점(LHP) 완화 엔진

## 🌟 개요 (Executive Summary)
클라우드 가상화 인프라(KVM, QEMU, AWS EC2, GCP Compute Engine)에서 게스트 OS 커널이 실행될 때, 가장 치명적인 성능 저하 요인 중 하나는 **락 홀더 선점(Lock Holder Preemption, LHP)** 현상입니다.
베어메탈 리눅스 커널의 스핀락(`spin_lock`)은 임계 구역(Critical Section)이 수십 나노초 내에 끝날 것으로 가정하고 CPU `PAUSE` 명령어를 실행하며 비지 웨이팅(Busy-waiting)을 수행합니다.

그러나 멀티테넌트 가상화 환경에서는 호스트 하이퍼바이저가 물리 CPU(pCPU) 스케줄링을 제어하므로:
1. 게스트 vCPU 0이 스핀락을 획득한 상태에서, 호스트 스케줄러에 의해 vCPU 0의 타임슬라이스가 만료되어 선점(Preempted)당할 수 있습니다 (LHP).
2. 이때 다른 게스트 vCPU 1, 2, 3이 동일한 락을 획득하려 시도하면, vCPU 0이 다시 물리 CPU를 할당받을 때까지(수 밀리초 = 수백만 클록 사이클 동안) 100% CPU를 불필요하게 낭비하며 헛돌게 됩니다.
3. 게스트 OS는 CPU 사용률 100%를 기록하면서도 실제 작업은 전혀 진척되지 않는 시스템 마비 상태에 빠집니다.

이를 해결하기 위해 리눅스 커널은 **KVM 반가상화 큐 스핀락(PV qspinlock / `CONFIG_PARAVIRT_SPINLOCKS`)** 메커니즘을 구현했습니다 (`arch/x86/kernel/kvm.c`, `kernel/locking/qspinlock_paravirt.h`):
- **유한 스핀 및 자발적 양보(`pv_wait`)**: 대기 vCPU는 무한정 회전하지 않고, 지정된 임계 횟수(`spin_threshold`, 통상 512 루프) 동안만 회전한 뒤 즉각 `kvm_pv_wait()`을 호출하여 VM-Exit `HLT` 또는 PAUSE-Loop Exiting(PLE)을 격발, 호스트 물리 CPU를 다른 생산적 스레드에 양보합니다.
- **하이퍼콜 기반 대기자 기상(`pv_kick`)**: 락 소유자 vCPU가 임계 구역을 빠져나와 락을 해제(`pv_queued_spin_unlock`)할 때, 대기 큐의 다음 vCPU가 수면(Halted) 상태임을 감지하면 KVM 전용 하이퍼콜 `KVM_HC_KICK_CPU`를 발송하여 호스트가 해당 vCPU를 즉각 스케줄링하도록 강제합니다.

본 문제에서는 KVM 반가상화 스핀락의 LHP 감지, 유한 스핀 및 `pv_wait` 수면 전이, `pv_kick` 하이퍼콜 핸드오프, 그리고 물리 CPU 클록 사이클 절감량 회계 엔진을 시뮬레이션합니다.

---

## 🏗️ 아키텍처 및 시스템 흐름도 (System Architecture)

```
        [ Guest vCPU: spin_lock() ]
                    │
           Lock Free? (Owner == None)
           ┌────────┴────────┐
         Yes                 No (Contention)
          │                  │
          ▼                  ▼
 [ ACQUIRED_FASTPATH ]   Check Lock Owner State
  Owner = vcpu_id        Is Owner PREEMPTED by Host? ──Yes──► [ LHP Detected! ]
  Cycles: 1                  │
                             ▼
                    Spin up to spin_threshold
                             │
                  Lock acquired in threshold?
                   ┌─────────┴─────────┐
                  Yes                  No
                   │                   │
                   ▼                   ▼
             [ ACQUIRED ]    [ Transition to HALTED ]
                             Call kvm_pv_wait() / HLT
                             Enqueue to MCS Wait Queue
                             Account Cycles Saved vs Host Timeslice

─────────────────────────────────────────────────────────────────────────────
        [ Guest vCPU: spin_unlock() ]
                    │
           Waiters in Queue?
           ┌────────┴────────┐
          No                Yes
           │                 │
           ▼                 ▼
 [ RELEASED_NO_WAITERS ]  Pop next waiter vcpu
  Owner = None            Was waiter HALTED?
                           ┌─────────┴─────────┐
                          Yes                  No
                           │                   │
                           ▼                   ▼
                 Issue KVM Hypercall      [ Direct Handoff ]
                 KVM_HC_KICK_CPU               │
                 pv_kicks_issued++             │
                           │                   │
                           └─────────┬─────────┘
                                     ▼
                          [ RELEASED_HANDOFF ]
                          New Owner = next_vcpu
```

---

## 🔢 수학적 공식 및 판정 기준 (Mathematical Formulations)

### 1. 스핀 소모 사이클 (Spinning Cycles Consumed)
시뮬레이션된 스핀 횟수를 $S$ (단, $S \le S_{\text{threshold}}$), 1회 회전당 비용을 $C_{\text{spin}}$이라 할 때:
$$C_{\text{consumed}} = S \times C_{\text{spin}}$$

### 2. PV 스핀락 사이클 절감량 (Cycles Saved via PV Wait)
전통적 무한 스핀락이 LHP 발생 시 호스트 타임슬라이스 $T_{\text{host}}$ 동안 낭비하는 사이클과 비교했을 때, 조기 HLT 전이로 절감된 CPU 클록 사이클은:
$$C_{\text{saved}} = \max\left(0, T_{\text{host}} - (C_{\text{consumed}} + C_{\text{halt\_cost}})\right)$$

### 3. LHP (Lock Holder Preemption) 판정
락 획득 시점에 현재 락 소유자 vCPU가 호스트에 의해 비활성화(선점)된 상태일 때:
$$\text{IsLHP} = (\text{LockOwner} \neq \text{None}) \land (\text{vCPU}[\text{LockOwner}].\text{state} = \text{"PREEMPTED"})$$

---

## 📥 입력 형식 (Input Specification)

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "config": {
    "spin_threshold": 512,
    "cycles_per_spin": 2,
    "cycles_halted_cost": 50,
    "host_timeslice_cycles": 10000,
    "vcpus": [0, 1, 2, 3]
  },
  "trace": [
    {"op": "ACQUIRE", "vcpu_id": 0},
    {"op": "HOST_PREEMPT", "vcpu_id": 0},
    {"op": "ACQUIRE", "vcpu_id": 1, "requested_spins": 512},
    {"op": "HOST_RESUME", "vcpu_id": 0},
    {"op": "RELEASE", "vcpu_id": 0},
    {"op": "RELEASE", "vcpu_id": 1}
  ]
}
```

### 지원 명령어 (Supported Operations):
1. `ACQUIRE`:
   - 파라미터: `vcpu_id` (int), `requested_spins` (int, optional)
   - 락이 비어있으면 `ACQUIRED_FASTPATH`.
   - 경합 시 스핀 후 `PV_WAIT_HALTED`로 대기 큐 인큐 및 절감 사이클 계산.
2. `RELEASE`:
   - 파라미터: `vcpu_id` (int)
   - 소유자 불일치 시 `EPERM_NOT_LOCK_OWNER`.
   - 대기자 존재 시 `KVM_HC_KICK_CPU` 발행 여부 판정 및 핸드오프.
3. `HOST_PREEMPT`:
   - 파라미터: `vcpu_id` (int)
   - 호스트 하이퍼바이저가 해당 vCPU를 물리 코어에서 선점 제거.
4. `HOST_RESUME`:
   - 파라미터: `vcpu_id` (int)
   - 호스트 하이퍼바이저가 해당 vCPU를 다시 실행 상태로 복귀.
5. `GET_STATE`:
   - 현재 락 소유자, 대기 큐, vCPU 실행 상태 덤프.

---

## 📤 출력 형식 (Output Specification)

표준 출력(stdout)으로 공백이 없는 콤팩트 JSON 문자열을 단일 행으로 출력합니다:
```json
{"events":[{"op":"ACQUIRE","vcpu_id":0,"status":"ACQUIRED_FASTPATH","cycles":1,"lock_owner":0}],"summary":{"pv_fastpath_locks":1,"pv_waits_halted":0,"pv_kicks_issued":0,"lhp_detected_count":0,"total_spins":0,"total_cycles_consumed":0,"total_cycles_saved":0,"final_lock_owner":0,"final_queue_length":0}}
```

---

## 💡 제약 조건 (Constraints)
- 모든 시뮬레이션 상태는 단일 스레드 결정론적(Deterministic)으로 동작해야 합니다.
- `vcpus` 상태 딕셔너리의 키는 문자열(`"0"`, `"1"` 등)로 직렬화됩니다.
- 대기 큐는 선입선출(FIFO) MCS 큐 순서를 엄격히 유지합니다.
