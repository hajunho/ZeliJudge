# 이론: Linux Kernel KVM Split IRQCHIP 및 GSI 인터럽트 가상화 아키텍처

## 1. x86 인터럽트 하드웨어 구조와 가상화의 난제

물리 x86 아키텍처에서 인터럽트는 두 계층의 하드웨어 컨트롤러를 통해 CPU 코어로 전달됩니다:
1. **IOAPIC (I/O Advanced Programmable Interrupt Controller)**:
   - 마더보드 칩셋에 위치하며 물리 핀(GSI, Global System Interrupt)을 통해 디바이스(디스크, NIC, 타이머)로부터 인터럽트 신호를 수신합니다.
   - 리다이렉션 테이블(Redirection Table, REDIR_TBL)을 조회하여 목적지 로컬 APIC ID와 벡터 번호(32~255)를 결정한 뒤 APIC 버스/시스템 버스를 통해 메시지를 송출합니다.
2. **LAPIC (Local APIC)**:
   - 각 CPU 코어 다이에 내장되어 있으며, 인터럽트 요청 레지스터(IRR, Interrupt Request Register)에 비트를 세팅하고, CPU 코어가 인터럽트를 서비스할 때 서비스 중 레지스터(ISR, In-Service Register)로 이동시킵니다.
   - CPU가 인터럽트 핸들러 처리를 마치면 LAPIC의 EOI(End of Interrupt) 레지스터에 `0`을 기록합니다.

가상 머신(VM) 환경에서는 이 모든 레지스터와 하드웨어 버스를 소프트웨어로 에뮬레이션해야 합니다.

---

## 2. 통합 Kernel IRQCHIP vs Split IRQCHIP 아키텍처 비교

| 항목 | Full Kernel IRQCHIP (`KVM_CREATE_IRQCHIP`) | Split IRQCHIP (`KVM_CAP_SPLIT_IRQCHIP`) |
| :--- | :--- | :--- |
| **LAPIC 위치** | 호스트 커널 내부 | 호스트 커널 내부 |
| **IOAPIC / PIC 위치** | 호스트 커널 내부 | 사용자 공간 하이퍼바이저 (QEMU) |
| **MSI 직접 전달** | 커널 내부 직접 주입 | 커널 내부 직접 주입 (Zero Exit) |
| **레벨 트리거 EOI 처리** | 커널 내부 자체 클리어 | `KVM_EXIT_IOAPIC_EOI` 탈출 통지 |
| **보안 격리성** | 취약점 시 호스트 커널 장악 위험 | IOAPIC이 유저 공간에 있어 안전 |
| **디바이스 에뮬레이션** | 복잡한 커널-유저 동기화 필요 | QEMU가 디바이스 상태와 완벽 결합 |

리눅스 커널 4.4부터 도입된 Split IRQCHIP은 LAPIC만 커널에 유지함으로써, 고빈도로 발생하는 타이머 인터럽트와 vCPU 간 IPI의 지연 시간을 나노초 단위로 유지하면서도, QEMU의 보안성과 가상 디바이스 제어력을 극대화했습니다.

---

## 3. GSI 라우팅 테이블 (`KVM_SET_GSI_ROUTING`)

KVM은 `struct kvm_irq_routing_table` 구조체를 통해 전역 시스템 인터럽트 번호(GSI)를 인터럽트 엔트리로 변환합니다:
```c
struct kvm_irq_routing_entry {
    __u32 gsi;
    __u32 type; /* KVM_IRQ_ROUTING_IRQCHIP 또는 KVM_IRQ_ROUTING_MSI */
    __u32 flags;
    __u32 pad;
    union {
        struct kvm_irq_routing_irqchip irqchip;
        struct kvm_irq_routing_msi msi;
        struct kvm_irq_routing_s390_adapter adapter;
        struct kvm_irq_routing_hv_sint hv_sint;
        __u32 pad[8];
    } u;
};
```

- **MSI 라우트 (`KVM_IRQ_ROUTING_MSI`)**:
  virtio 디바이스나 PCI 패스스루 디바이스는 MSI-X 메시지를 사용합니다. `msi.address_lo`와 `msi.data`에 타깃 vCPU APIC ID와 벡터가 인코딩되어 있으므로, KVM 커널은 사용자 공간을 거치지 않고 대상 vCPU의 LAPIC IRR에 직접 비트를 켭니다 (`kvm_set_msi()`).
- **하드웨어 가속 (APIC-v / Posted Interrupts)**:
  인텔 APIC-v 및 AMD AVIC 가상화 확장이 활성화되어 있으면, 게스트 vCPU가 실행 중일 때 물리 인터럽트 알림(Notification Vector)을 보내 게스트 종료(VM-Exit)조차 없이 하드웨어적으로 vCPU 가상 APIC에 인터럽트를 즉각 주입합니다.

---

## 4. Split Mode에서의 레벨 트리거 EOI 브로드캐스트

레벨 트리거(Level-triggered) 인터럽트는 라인이 물리적으로 1(High)로 유지되는 동안 인터럽트가 지속적으로 발생합니다.
1. 디바이스가 라인을 Assert (level = 1) -> IOAPIC -> vCPU LAPIC IRR 세팅.
2. 게스트 OS가 ISR을 수행하고 디바이스 컨트롤러의 원인을 제거한 뒤 LAPIC EOI 레지스터에 기록.
3. **Split IRQCHIP 모드의 문제점**: LAPIC은 커널에 있지만, 어떤 GSI 라인이 해제되어야 하는지 알고 있는 IOAPIC은 사용자 공간(QEMU)에 있습니다!
4. **해결책**:
   - 커널은 라우팅 테이블 설정 시 레벨 트리거 인터럽트 벡터들을 `eoi_exit_bitmap`에 등록해 둡니다.
   - 게스트가 EOI를 쓰면 커널은 해당 비트맵을 검사하고, 비트가 켜져 있으면 즉시 vCPU 실행을 멈추고 `KVM_EXIT_IOAPIC_EOI` 이유로 QEMU로 리턴합니다.
   - QEMU는 사용자 공간 IOAPIC의 Remote IRR 비트를 클리어하고 라인을 완전히 Deassert합니다.

이와 같은 정교한 분리 설계 덕분에 KVM은 엔터프라이즈 클라우드 환경에서 탁월한 안정성과 최고 수준의 I/O 처리 성능을 동시에 달성할 수 있습니다.
