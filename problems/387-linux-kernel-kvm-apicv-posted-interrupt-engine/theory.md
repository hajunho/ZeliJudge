# Theory: Linux Kernel KVM APICv & Hardware Posted Interrupt Processing (`arch/x86/kvm/vmx/posted_intr.c`)

## 1. 가상화 인터럽트 가속과 VM-Exit의 근본적 병목

전통적인 x86 CPU 가상화(Intel VT-x / AMD-V)에서 가상 로컬 APIC(vLAPIC)은 하이퍼바이저 소프트웨어에 의해 에뮬레이션되었습니다.
- 게스트 OS가 APIC 레지스터(TPR, EOI, ICR 등)를 읽거나 쓸 때마다 하드웨어 **VM-Exit**가 발생합니다.
- VM-Exit 1회당 수백~수천 CPU 사이클의 파이프라인 플러시, 레지스터 저장/복원 오버헤드가 동반됩니다.
- 외부 PCI 디바이스(SR-IOV 가상 기능 VF)에서 수신된 패킷 인터럽트가 vCPU로 주입될 때도 반드시 VM-Exit를 경유해야 했습니다.

---

## 2. Intel APICv (APIC Virtualization) 기술

인텔은 Ivy Bridge/Haswell 마이크로아키텍처부터 하드웨어 레벨의 **APICv**를 제공합니다:

1. **APIC-Register Virtualization (Virtual-APIC Page)**:
   - 게스트의 4KB vAPIC 레지스터 접근을 하이퍼바이저 개입 없이 하드웨어 마이크로코드가 직접 가상 APIC 페이지에 읽고 씁니다.
   - TPR 가상화 및 EOI 브로드캐스트가 Zero VM-Exit로 처리됩니다.
2. **Virtual-Interrupt Delivery**:
   - 하드웨어 VMCS 필드에 가상 인터럽트 제어 비트를 두어, 게스트 실행 도중 인터럽트 평가 및 주입을 CPU 코어가 직접 수행합니다.
3. **Posted-Interrupt Processing (PIR / PID)**:
   - APICv의 정점으로, 락리스 메모리 구조체인 **Posted-Interrupt Descriptor (PID)**를 통해 외부 IPI 및 PCI 디바이스 인터럽트를 물리 CPU와 동기화합니다.

---

## 3. 포스티드 인터럽트 디스크립터(PID)와 3단계 전이

`struct pi_desc`는 64바이트 캐시라인 정렬 구조체입니다:

```c
struct pi_desc {
    u32 pir[8];     /* 256-bit posted interrupt requests */
    union {
        struct {
            u16 on : 1,     /* Outstanding notification */
                sn : 1,     /* Suppress notification */
                rsvd_1 : 14;
            u8  nv;         /* Notification vector */
            u8  rsvd_2;
            u32 ndst;       /* Notification destination (APIC ID) */
        };
        u64 control;
    };
    u32 rsvd[6];
} __aligned(64);
```

### 3.1 동기화 메커니즘
- **GUEST_RUNNING 상태**: 대상 vCPU가 Guest Non-Root 모드에서 실행 중일 때 Notification Vector(NV: 0xf2)가 물리 코어로 도달하면, 하드웨어 마이크로코드는 VM-Exit를 발생시키지 않고 원자적으로 `pir` 비트들을 `vAPIC.irr`로 복사하고 `on` 비트를 클리어한 뒤 즉각 게스트 인터럽트 서비스 루틴(ISR)으로 점프합니다 (**Zero-Exit Fastpath**).
- **GUEST_BLOCKED 상태**: 게스트가 HLT 명령으로 슬립 중일 때 Wakeup Vector(NV: 0xf3)를 전송하여 물리 코어를 깨우고, KVM 스케줄러가 해당 vCPU 스레드를 러너블로 전환합니다.
- **SN (Suppress Notification) 비트**: 게스트 인터럽트 처리 중 폭풍처럼 밀려드는 물리 IPI를 억제하고 PIR 비트맵에만 누적시킴으로써 상호연결 버스 과부하를 방지합니다.
