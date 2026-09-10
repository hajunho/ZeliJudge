# 문제 446: 리눅스 커널 가상화 비동기 I/O 바이패스 — KVM ioeventfd 및 irqfd 초고속 인터럽트/도어벨 가속 엔진 (`virt/kvm/eventfd.c`)

## 1. 개요 및 배경

클라우드 데이터센터와 초고성능 가상 머신(KVM/QEMU) 환경에서 게스트 OS가 초당 수백만 IOPS에 달하는 NVMe 스토리지 I/O 또는 100GbE VirtIO-Net 패킷을 송수신할 때, 전통적인 에뮬레이션 아키텍처는 극심한 성능 병목에 직면합니다.

### 1) 전통적인 QEMU 사용자 공간 에뮬레이션 병목
1. **도어벨 쓰기(Doorbell Write)**: 게스트 vCPU가 디바이스 큐에 작업을 적재하고 MMIO/PIO 도어벨 레지스터에 기록하면 `VM-Exit`(`EXIT_REASON_EPT_MISCONFIG` 또는 `KVM_EXIT_MMIO`)이 발생합니다.
2. **무거운 컨텍스트 스위칭**: KVM 커널 모듈은 이를 자체 처리하지 못하고 QEMU 사용자 공간 I/O 스레드로 제어를 넘깁니다(`ioctl(KVM_RUN)` 반환).
3. **스케줄링 지연**: QEMU 메인 루프 또는 디바이스 스레드가 깨어나 가상 디바이스 상태를 갱신하고 백엔드 I/O를 트리거합니다.
4. **인터럽트 주입**: I/O 완료 시 QEMU가 다시 `ioctl(KVM_IRQ_LINE)` 시스템 콜을 호출하여 커널에 인터럽트 주입을 요청하고, 게스트 vCPU에 전달됩니다.

이 일련의 과정에서 발생하는 I/O 왕복 지연 시간은 **15,000ns ~ 30,000ns**에 달하며, 수많은 CPU 사이클이 호스트-게스트 문맥 교환에 낭비됩니다.

```
[전통적인 에뮬레이션 경로 (지연 시간 ~25µs)]:
Guest vCPU ──(MMIO Write)──> VM-Exit ──> KVM Kernel ──(KVM_RUN exit)──> QEMU Userspace
                                                                             │
                                                                       Backend I/O
                                                                             │
Guest vCPU <──(Interrupt)─── KVM Kernel <──(ioctl KVM_IRQ_LINE)──────────────┘

[KVM ioeventfd & irqfd 패스트패스 바이패스 (~1.2µs)]:
Guest vCPU ──(MMIO Doorbell)──> VM-Exit ──> KVM ioeventfd ──(eventfd_signal)──> vhost-net / VFIO
                                                  │ (즉각 Guest 복귀, 0 Userspace Exit!)
                                                  ▼
Guest vCPU <──(APICv Posted-Intr)────────── KVM irqfd <────(DMA 완료 eventfd)───┘
```

리눅스 커널은 이를 해결하기 위해 `virt/kvm/eventfd.c`에 **`ioeventfd`**와 **`irqfd`**라는 초고속 인-커널 비동기 바이패스 메커니즘을 구현하였습니다.
- **`ioeventfd`**: 게스트의 MMIO/PIO 도어벨 쓰기 주소를 커널에 미리 등록하여, VM-Exit 발생 시 커널 내부 IO 버스(`kvm_io_bus`)에서 즉시 `eventfd`를 시그널링하고 QEMU를 거치지 않고 바로 게스트로 복귀합니다(지연 시간 95% 단축).
- **`irqfd`**: 백엔드 워커(`vhost-net`, `VFIO` 하드웨어 인터럽트)가 I/O 완료 시 `eventfd`를 시그널링하면, 커널 내 `irqfd_wakeup()` 콜백이 직접 GSI 라우팅 테이블(`kvm_irq_routing_table`)을 참조하여 MSI-X 또는 IOAPIC 인터럽트를 게스트 vCPU에 즉각 주입합니다. 하드웨어 가상화 지원 시 **APICv Posted-Interrupt**를 통해 0-VM-Exit로 인터럽트가 전달됩니다.

---

## 2. 핵심 메커니즘 및 상세 스펙

본 문제에서는 리눅스 커널 `virt/kvm/eventfd.c`, `virt/kvm/irqchip.c`, `arch/x86/kvm/lapic.c`의 핵심 로직을 완벽히 모사하는 KVM 비동기 바이패스 시뮬레이션 엔진을 구현합니다.

### 1) 초기 VM 구성 (`INIT_VM`)
- `max_gsi`: 가상 머신이 지원하는 최대 GSI 번호 (기본 1024).
- `apicv_enabled`: 인텔 APICv / AMD AVIC 하드웨어 가상화 활성화 여부 (boolean).
- `vcpus`: vCPU 목록 `[{"vcpu_id": int, "apic_id": int}, ...]`.

### 2) GSI 라우팅 설정 (`SET_GSI_ROUTING`)
- `routes`: GSI 엔트리 목록:
  - `gsi`: 정수
  - `type`: `"MSI"` 또는 `"IRQCHIP"`
  - `type == "MSI"`:
    - `dest_apic_id`: 대상 vCPU의 APIC ID
    - `vector`: 인터럽트 벡터 번호 (예: 32 ~ 255)
    - `delivery_mode`: `"FIXED"`
  - `type == "IRQCHIP"`:
    - `irqchip`: `"IOAPIC"`
    - `pin`: IOAPIC 핀 번호
    - `vector`: 매핑된 인터럽트 벡터

### 3) ioeventfd 등록 및 해제 (`REGISTER_IOEVENTFD` / `UNREGISTER_IOEVENTFD`)
- 등록: `fd_id`, `bus`(`"MMIO"` 또는 `"PIO"`), `addr`, `len`(1, 2, 4, 8), `flags`, `datamatch`
  - `flags`에 `"DATAMATCH"`가 포함된 경우, 게스트가 기록한 값(`val`)이 등록된 `datamatch`와 일치해야만 적중합니다 (다중 큐 분기 처리).
  - `"DATAMATCH"`가 없는 경우, 해당 주소와 길이에 대한 모든 쓰기를 적중(와일드카드) 처리합니다.
  - 중복 등록 시 `{"status": "ERROR_ALREADY_EXISTS", "fd_id": fd_id}` 반환.
  - 성공 시 `{"status": "IOEVENTFD_REGISTERED", "fd_id": fd_id}` 반환.
- 해제: 동일 속성 일치 엔트리 제거. 존재하지 않으면 `ERROR_NOT_FOUND`, 성공 시 `IOEVENTFD_DEASSIGNED`.

### 4) irqfd 등록 및 해제 (`REGISTER_IRQFD` / `UNREGISTER_IRQFD`)
- 등록: `fd_id`, `gsi`, `flags`, `resample_fd_id`
  - `flags`에 `"RESAMPLE"`이 포함된 경우, 레벨 트리거 인터럽트로 동작하며 향후 게스트 EOI 수신 시 `resample_fd_id`를 시그널링합니다.
  - 중복 등록 시 `{"status": "ERROR_ALREADY_EXISTS", "fd_id": fd_id}`.
  - 성공 시 `{"status": "IRQFD_REGISTERED", "fd_id": fd_id, "gsi": gsi}`.
- 해제: 등록된 irqfd 제거. 성공 시 `IRQFD_DEASSIGNED`, 실패 시 `ERROR_NOT_FOUND`.

### 5) 게스트 I/O 접근 (`GUEST_IO_ACCESS`)
- `vcpu_id`, `bus`, `type`(`"WRITE"` 또는 `"READ"`), `addr`, `len`, `val`
- **검증 규칙**:
  - `type == "WRITE"`인 경우에만 `ioeventfd` 대상이 됩니다.
  - 등록된 `ioeventfd` 목록에서 `bus`, `addr`, `len`이 일치하는 항목을 검색합니다.
  - `has_datamatch`인 경우 `datamatch == val` 확인, 아니면 즉시 적중.
  - **패스트패스 적중 시**:
    - 해당 `fd_id`의 시그널 카운트를 1 증가시킵니다.
    - `ioeventfd_fastpath_hits` 통계 카운터 1 증가.
    - 반환: `{"status": "HANDLED_IN_KERNEL", "bypassed_userspace": true, "signaled_fd": fd_id, "val": val}`.
  - **미적중 / READ 시**:
    - 사용자 공간(QEMU)으로 탈출(`KVM_EXIT_IO`).
    - `userspace_exits` 통계 카운터 1 증가.
    - 반환: `{"status": "KVM_EXIT_IO", "bypassed_userspace": false, "exit_reason": bus, "access_type": type, "addr": addr, "len": len, "val": val}`.

### 6) irqfd 시그널링 (`SIGNAL_IRQFD`)
- `fd_id`, `count` (기본 1)
- 동작:
  - 등록되지 않은 irqfd인 경우 `{"status": "ERROR_UNKNOWN_IRQFD", "fd_id": fd_id}` 반환.
  - `fd_id`의 시그널 카운트 `count`만큼 누적.
  - 바인딩된 `gsi`가 GSI 라우팅 테이블에 없는 경우: `{"status": "UNROUTED_GSI", "fd_id": fd_id, "gsi": gsi}` 반환.
  - `irqfd_injections` 통계 카운터 1 증가.
  - **MSI 라우트**:
    - `dest_apic_id`에 해당하는 대상 vCPU 식별.
    - `apicv_enabled == true`:
      - 대상 vCPU의 PIR(Posted-Interrupt Request) 비트맵에 `vector` 추가 및 ON(Outstanding Notification) 플래그 설정.
      - `apicv_posted_count` 1 증가.
      - 반환: `{"status": "INJECTED", "gsi": gsi, "type": "MSI", "target_vcpu": target_vcpu, "vector": vector, "method": "APICV_POSTED_INTR"}`.
    - `apicv_enabled == false`:
      - 대상 vCPU의 vAPIC IRR(Interrupt Request Register)에 `vector` 추가.
      - 반환: `{"status": "INJECTED", "gsi": gsi, "type": "MSI", "target_vcpu": target_vcpu, "vector": vector, "method": "LAPIC_IRR_INJECT"}`.
  - **IRQCHIP 라우트**:
    - 해당 IOAPIC 핀의 레벨을 1(`asserted`)로 설정.
    - 만약 `"RESAMPLE"` 설정이 되어 있고 `resample_fd_id`가 지정되어 있다면 핀의 리샘플 대기 세트에 등록.
    - 반환: `{"status": "LINE_ASSERTED", "gsi": gsi, "type": "IRQCHIP", "pin": pin, "vector": vector}`.

### 7) 게스트 인터럽트 처리 완료 (`GUEST_EOI`)
- `vcpu_id`, `vector`
- 동작:
  - IOAPIC 핀 중 해당 `vector`에 매핑되어 있고 레벨이 1인 핀을 탐색.
  - 핀의 레벨을 0으로 해제(`deassert`).
  - 핀에 등록된 모든 `resample_fd_id`에 대해 시그널링(`eventfd_signal(1)`)을 수행하고, `resample_events` 카운터 1 증가.
  - 통지된 resample fd 목록을 알파벳 오름차순으로 정렬하여 반환.
  - 반환: `{"status": "EOI_HANDLED", "vcpu_id": vcpu_id, "vector": vector, "resampled_fds": [...]}`.

### 8) 통계 조회 (`QUERY_STATS`)
- 반환 형식:
  ```json
  {
    "ioeventfd_fastpath_hits": int,
    "userspace_exits": int,
    "irqfd_injections": int,
    "apicv_posted_count": int,
    "resample_events": int,
    "active_ioeventfds": int,
    "active_irqfds": int,
    "eventfd_signals": {"fd_name": int, ...}
  }
  ```
  (`eventfd_signals` 딕셔너리는 키 알파벳 오름차순 정렬)

---

## 3. 입력 및 출력 명세

### 입력 포맷 (표준 입력 JSON)
```json
{
  "vm_config": {
    "max_gsi": 1024,
    "apicv_enabled": true,
    "vcpus": [
      {"vcpu_id": 0, "apic_id": 0},
      {"vcpu_id": 1, "apic_id": 1}
    ]
  },
  "operations": [
    { "op": "SET_GSI_ROUTING", "routes": [...] },
    { "op": "REGISTER_IOEVENTFD", "fd_id": "...", "bus": "MMIO", "addr": 4096, "len": 2, "flags": ["DATAMATCH"], "datamatch": 0 },
    { "op": "REGISTER_IRQFD", "fd_id": "...", "gsi": 32, "flags": [] },
    { "op": "GUEST_IO_ACCESS", "vcpu_id": 0, "bus": "MMIO", "type": "WRITE", "addr": 4096, "len": 2, "val": 0 },
    { "op": "SIGNAL_IRQFD", "fd_id": "...", "count": 1 },
    { "op": "GUEST_EOI", "vcpu_id": 0, "vector": 64 },
    { "op": "QUERY_STATS" }
  ]
}
```

### 출력 포맷 (표준 출력 단일 라인 JSON)
```json
{"results":[...]}
```
모든 키와 값은 불필요한 공백 없는 압축 JSON(`separators=(',', ':')`) 형식으로 출력합니다.
