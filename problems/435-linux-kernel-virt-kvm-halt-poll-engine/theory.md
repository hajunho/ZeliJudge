# Theory #435: 리눅스 커널 KVM 동적 홀트-폴링(Halt-Polling)과 클라우드 초저지연 가상화

## 1. 가상화 유휴 대기(Idle)와 HLT 명령어의 오버헤드

### 1.1 베어메탈 vs 가상 머신의 CPU 유휴 처리
베어메탈 OS에서 스케줄러가 실행할 작업이 없으면 유휴 루프(`cpu_idle_loop`)로 진입하여 x86 `HLT` 명령어를 실행합니다. CPU는 즉각 저전력 C-state로 진입하며, 하드웨어 인터럽트가 발생하면 서브 마이크로초 내에 깨어납니다.

그러나 KVM/QEMU 가상화 환경에서는 게스트의 `HLT` 실행이 **하드웨어 가상화 트랩(VM-Exit / Exit Reason: EXIT_REASON_HLT)**을 발생시킵니다:
1. vCPU 레지스터 상태를 VMCS(Virtual Machine Control Structure)에 저장하고 호스트 커널 모드로 복귀합니다.
2. KVM은 `kvm_vcpu_block()` 함수를 호출하여 호스트 스케줄러에게 물리 CPU를 양보(`schedule()`)합니다.
3. 호스트 커널은 다른 가상 머신이나 프로세스로 컨텍스트 스위칭을 수행합니다.
4. 잠시 후(예: 5~10μs 뒤) 가상 네트워크 카드에 패킷이 도착하여 가상 인터럽트가 주입될 때, 호스트는 vCPU 스레드를 깨우고 스케줄러 큐에 넣은 뒤 VMCS를 복원하고 VM-Entry를 실행합니다.
5. 이 일련의 호스트 컨텍스트 스위칭과 인터럽트 라우팅은 **최소 10μs에서 심할 경우 50μs 이상의 지연 시간(Tail Latency)**을 유발합니다.

---

## 2. KVM Halt-Polling 메커니즘 (virt/kvm/kvm_main.c)

리눅스 4.2 커널에 도입된 **Halt-Polling**은 초고속 NVMe-oF 스토리지 및 금융 트레이딩(HFT) 워크로드의 요구에 따라 설계되었습니다.

### 2.1 동작 원리
`kvm_vcpu_block()` 진입 시 곧바로 `schedule()`을 호출하지 않고:
```c
ktime_t start = ktime_get();
ktime_t stop = ktime_add_ns(start, vcpu->halt_poll_ns);

do {
    if (kvm_vcpu_check_block(vcpu) == 0) {
        /* 가상 인터럽트 또는 이벤트 도착! */
        ++vcpu->stat.halt_poll_success;
        goto out;
    }
    cpu_relax();
} while (ktime_before(ktime_get(), stop));
```
지정된 `halt_poll_ns` 동안 루프를 돌며 가상 인터럽트 레지스터(vAPIC IRR)를 직접 폴링합니다.
- 만약 폴링 도중 이벤트가 도착하면, 호스트 스케줄러를 전혀 거치지 않고 **0 마이크로초에 가깝게 즉각 게스트 모드로 복귀(Zero Context-Switch)**합니다.

---

## 3. 동적 적응형 윈도우 튜닝 (Adaptive Grow/Shrink)

폴링 시간(`halt_poll_ns`)을 무조건 길게 잡으면, 오랫동안 아무런 이벤트도 없는 유휴 상태에서도 호스트 물리 코어를 100% 비지 폴링으로 낭비하여 호스트 전력 소모와 CPU 도둑(Steal time)이 급증합니다.
따라서 KVM은 **피드백 기반 적응형 알고리즘**을 사용합니다:

### 3.1 Grow 조건
- 폴링 윈도우 내에 인터럽트가 성공적으로 도착한 경우:
  - 현재 워크로드가 매우 빈번한 I/O를 수행하고 있음을 의미합니다.
  - `halt_poll_ns`를 2배(`halt_poll_ns_grow`)로 확장하여 다음 번 폴링 적중 확률을 높입니다 (상한 `max_halt_poll_ns`까지).
  - 윈도우가 0이었던 경우 `halt_poll_ns_grow_start`(통상 10~20μs)로 초기화합니다.

### 3.2 Shrink 조건
- 폴링 윈도우가 만료될 때까지 인터럽트가 오지 않아 결국 호스트 수면(`schedule()`)으로 진입한 경우:
  - 헛되이 호스트 CPU를 낭비한 실패(Miss)입니다.
  - 다음 번 CPU 낭비를 막기 위해 `halt_poll_ns`를 즉각 1/2배(`halt_poll_ns_shrink`)로 축소하거나 0으로 리셋합니다.

---

## 4. 퍼블릭 클라우드 인프라의 표준 튜닝

- **AWS EC2 Nitro**: 인텔 및 Graviton 인스턴스에서 네트워킹 P99 지연시간을 낮추기 위해 `halt_poll_ns`를 200μs~400μs 수준으로 기본 활성화합니다.
- **쿠버네티스 고성능 파드**: vCPU 고정(CPU Pinning) 및 격리(Isolcpus) 환경에서 `halt_poll_ns`를 넉넉히 설정하면, 베어메탈 대비 99% 이상의 네트워크/스토리지 I/O 성능을 뽑아낼 수 있습니다.
