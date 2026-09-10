# Problem #435: 리눅스 커널 가상화: KVM vCPU 동적 홀트-폴링(Dynamic Halt-Polling) 및 지연 시간 단축(Zero Context-Switch) 적응형 윈도우 엔진

## 🌟 개요 (Executive Summary)
AWS Nitro, GCP Compute Engine 및 고빈도 트레이딩(HFT) 클라우드 인프라에서 가상 머신(vCPU)의 지연 시간(Tail Latency)을 악화시키는 주범은 x86 `HLT` 명령어에 의한 **가상 머신 탈출(VM-Exit)과 호스트 컨텍스트 스위칭**입니다.
게스트 OS 내에서 대기할 작업이 없어 vCPU가 `HLT`를 실행하면, 기본 KVM 동작은 다음과 같이 작동합니다:
1. 즉각 VM-Exit이 발생하고 호스트 커널의 `kvm_vcpu_block()`으로 진입합니다.
2. 호스트 스케줄러(`schedule()`)가 호출되어 현재 vCPU 스레드를 수면(`TASK_INTERRUPTIBLE`) 상태로 전환하고 물리 CPU를 다른 프로세스에 넘깁니다.
3. 불과 수 마이크로초 뒤에 가상 인터럽트(네트워크 패킷 도착, 타이머 완료 등)가 발생하면, 호스트는 IPI 인터럽트를 발송하고, 스케줄러가 다시 vCPU를 깨우며, VM-Entry를 실행합니다.
4. 이 일련의 과정으로 인해 단순 유휴 대기 후 복귀에 **15~30 마이크로초의 엄청난 지연 시간(Jitter)**이 추가됩니다.

이를 획기적으로 해결하기 위해 리눅스 커널에 도입된 서브시스템이 바로 **KVM vCPU 홀트-폴링(Halt-Polling, `virt/kvm/kvm_main.c`)**입니다:
- vCPU가 `HLT`를 실행했을 때 즉각 호스트 스케줄러로 들어가지 않고, 호스트 vCPU 스레드가 CPU를 쥐고 있으면서 **최대 `halt_poll_ns` 동안 가상 인터럽트 도달 여부를 선제적으로 폴링(Busy-polling)**합니다.
- 만약 폴링 시간 내에 이벤트가 도착하면(`HALT_POLL_HIT`), 호스트 컨텍스트 스위칭을 전혀 거치지 않고 **즉시 0-나노초 수준으로 게스트 실행을 재개(Zero Context-Switch)**합니다.
- **동적 적응형 윈도우 (Dynamic Grow/Shrink)**:
  - 이벤트가 폴링 윈도우 내에 적중하면, 유휴 시간이 매우 짧은 워크로드로 판단하여 폴링 윈도우를 지수적으로 확장(`halt_poll_ns_grow`, 기본 2배)합니다 (최대 `max_halt_poll_ns`까지).
  - 반대로 폴링 시간 동안 이벤트가 오지 않아 결국 잠들게 되면(`HALT_POLL_MISS_SLEEP`), 무의미한 호스트 CPU 낭비를 막기 위해 폴링 윈도우를 즉각 축소(`halt_poll_ns_shrink`, 기본 1/2배 또는 0으로 리셋)합니다.

본 문제에서는 KVM 커널의 vCPU 홀트-폴링 상태 머신, 동적 윈도우 적응 확장/축소 알고리즘, 그리고 절감된 컨텍스트 스위칭 레이턴시를 정밀하게 회계하는 엔진을 시뮬레이션합니다.

---

## 🏗️ 아키텍처 및 시스템 흐름도 (System Architecture)

```
                       [ Guest vCPU executes HLT ]
                                    │
                                    ▼
                         [ kvm_vcpu_halt() ]
                                    │
                         halt_poll_ns > 0 ?
                        ┌───────────┴───────────┐
                       Yes                      No
                        │                       │
                        ▼                       ▼
            [ Enter Polling Loop ]    [ DIRECT_SLEEP_NO_POLL ]
            (Up to halt_poll_ns)      If delay <= max_halt_poll_ns:
                        │             halt_poll_ns = grow_start
                        │             Sleep entire delay
                        │             Wakeup -> RUNNING
                        │
            Event arrived before halt_poll_ns?
             ┌──────────┴──────────┐
            Yes                    No (Timeout)
             │                     │
             ▼                     ▼
    [ HALT_POLL_HIT ]     [ HALT_POLL_MISS_SLEEP ]
    poll_time = delay     wasted_poll = halt_poll_ns
    Grow halt_poll_ns:    Shrink halt_poll_ns:
    new = min(max,        new = halt_poll_ns // shrink
              poll * 2)   Sleep remaining delay
    Zero Context-Switch!  Wakeup -> RUNNING
    state = RUNNING
```

---

## 🔢 수학적 공식 및 판정 기준 (Mathematical Formulations)

### 1. 홀트-폴링 적중 및 적응 확장 (Halt-Poll Hit & Grow)
이벤트 지연 시간을 $D_{\text{event}}$, 현재 폴링 윈도우를 $T_{\text{poll}}$, 상한을 $T_{\text{max}}$라 할 때:
$$D_{\text{event}} \le T_{\text{poll}} \implies \text{HALT\_POLL\_HIT}$$
이때 새로운 폴링 윈도우 $T_{\text{new}}$는:
$$T_{\text{new}} = \begin{cases} T_{\text{grow\_start}} & \text{if } T_{\text{poll}} = 0 \\ \min(T_{\text{max}}, T_{\text{poll}} \times G_{\text{grow}}) & \text{if } T_{\text{poll}} > 0 \end{cases}$$
절감된 호스트 지연 시간(Saved Latency)은:
$$S_{\text{latency}} = \max(0, C_{\text{context\_switch}} - D_{\text{event}})$$

### 2. 홀트-폴링 실패 및 적응 축소 (Halt-Poll Miss & Shrink)
$$D_{\text{event}} > T_{\text{poll}} \implies \text{HALT\_POLL\_MISS\_SLEEP}$$
낭비된 폴링 시간은 $T_{\text{poll}}$, 실제 수면 시간은 $D_{\text{event}} - T_{\text{poll}}$입니다.
새로운 축소 윈도우는:
$$T_{\text{new}} = \begin{cases} 0 & \text{if } S_{\text{shrink}} = 0 \\ \lfloor \frac{T_{\text{poll}}}{S_{\text{shrink}}} \rfloor & \text{if } S_{\text{shrink}} > 0 \end{cases}$$

---

## 📥 입력 형식 (Input Specification)

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "config": {
    "initial_halt_poll_ns": 0,
    "max_halt_poll_ns": 160000,
    "halt_poll_ns_grow": 2,
    "halt_poll_ns_shrink": 2,
    "halt_poll_ns_grow_start": 20000,
    "context_switch_cost_ns": 15000,
    "vcpus": [0, 1]
  },
  "trace": [
    {"op": "VCPU_HALT", "vcpu_id": 0, "event_delay_ns": 5000},
    {"op": "VCPU_HALT", "vcpu_id": 0, "event_delay_ns": 8000},
    {"op": "VCPU_HALT", "vcpu_id": 0, "event_delay_ns": 200000},
    {"op": "GET_VCPU_STATS", "vcpu_id": 0}
  ]
}
```

### 지원 명령어 (Supported Operations):
1. `VCPU_HALT`:
   - 파라미터: `vcpu_id` (int), `event_delay_ns` (int)
   - 폴링 적중/실패 여부를 판정하고 동적 윈도우 확장/축소를 실행합니다.
2. `SET_PARAMS`:
   - 파라미터: `vcpu_id` (int), `halt_poll_ns` (int, optional), `max_halt_poll_ns` (int, optional)
   - vCPU의 홀트 폴링 파라미터를 동적으로 변경합니다.
3. `GET_VCPU_STATS`:
   - 파라미터: `vcpu_id` (int)
   - 해당 vCPU의 누적 통계(적중/실패 횟수, 폴링 시간, 절감 지연)를 반환합니다.

---

## 📤 출력 형식 (Output Specification)

표준 출력(stdout)으로 공백이 없는 콤팩트 JSON 문자열을 단일 행으로 출력합니다:
```json
{"events":[{"op":"VCPU_HALT","vcpu_id":0,"status":"DIRECT_SLEEP_NO_POLL","sleep_time_ns":5000,"new_halt_poll_ns":20000,"state":"RUNNING"}],"summary":{"total_poll_success":1,"total_poll_fails":2,"total_poll_time_ns":88000,"total_saved_latency_ns":7000,"final_vcpus_poll_ns":{"0":40000,"1":0}}}
```

---

## 💡 제약 조건 (Constraints)
- 모든 시뮬레이션 연산은 나노초(`ns`) 정수 단위로 단일 스레드 결정론적으로 처리됩니다.
- vCPU별 폴링 상태와 윈도우는 완전히 독립적으로 유지됩니다.
- `summary.final_vcpus_poll_ns`의 키는 문자열(`"0"`, `"1"`)로 직렬화됩니다.
