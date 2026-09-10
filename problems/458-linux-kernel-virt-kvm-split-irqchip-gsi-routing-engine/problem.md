# 문제 458: Linux Kernel KVM Split IRQCHIP 및 GSI 라우팅 엔진

## 문제 설명

하드웨어 가상화(KVM, Kernel-based Virtual Machine, `arch/x86/kvm/`) 환경에서 가상 디바이스(virtio-net, virtio-blk, PCI 패스스루)가 발생시키는 인터럽트를 게스트 vCPU로 전달하는 인터럽트 가상화 아키텍처는 가상 머신의 I/O 지연 시간과 처리량에 결정적인 영향을 미칩니다.

초기 KVM의 고전적 인터럽트 제어기(`KVM_CREATE_IRQCHIP`)는 레거시 PIC(8259), IOAPIC, 로컬 APIC(LAPIC)을 모두 호스트 커널 내부에서 통째로 에뮬레이션했습니다. 그러나 이는 다음과 같은 치명적인 한계를 유발했습니다:
1. **보안 및 공격 표면(Attack Surface)**: 호스트 커널 내부에 거대한 IOAPIC 상태 머신이 존재하여, 게스트 취약점 공격 시 호스트 커널 전체가 손상될 위험이 큼.
2. **사용자 공간 에뮬레이션과의 충돌**: QEMU 등 사용자 공간 하이퍼바이저가 커스텀 가상 디바이스의 레벨 트리거 인터럽트 라인을 세밀하게 제어하기 어려움.

이 문제를 해결하기 위해 도입된 핵심 아키텍처가 **Split IRQCHIP 모드 (`KVM_CAP_SPLIT_IRQCHIP`)**입니다:
- **로컬 APIC(LAPIC)**은 고속 타이머 인터럽트, vCPU 간 IPI, 하드웨어 APIC-v 가속을 위해 **호스트 커널 내부**에 남겨둡니다.
- **PIC 및 IOAPIC**은 유연한 디바이스 에뮬레이션을 위해 **사용자 공간 하이퍼바이저(QEMU)**로 분리합니다.

```
+-----------------------------------------------------------------------------------------+
|                  Linux KVM Split IRQCHIP & GSI Routing Pipeline                         |
+-----------------------------------------------------------------------------------------+

 [Userspace: QEMU / Virtio]                                 [KVM Host Kernel]
      |                                                            |
      | 1. KVM_SET_GSI_ROUTING                                     |
      +----------------------------------------------------------->| Configures GSI Table:
      |                                                            |   GSI 16 -> MSI (vCPU 0, vec 48)
      |                                                            |   GSI 24 -> IRQCHIP (vCPU 1, vec 64, level)
      |                                                            |
      | 2. KVM_IRQ_LINE / irqfd (GSI 16)                           |
      +----------------------------------------------------------->| MSI Fast Path:
      |                                                            | Direct injection into vCPU 0 IRR!
      |                                                            | Zero VM-Exit to userspace!
      |                                                            |
      | 3. Level Trigger EOI (GSI 24)                              |
      |                                                            | Guest writes EOI register:
      | <--- KVM_EXIT_IOAPIC_EOI (vector 64) ----------------------+ Split Mode EOI Notification!
      |      (Userspace IOAPIC clears line level)                  |
      v                                                            v
```

### 핵심 메커니즘
1. **GSI (Global System Interrupt) 라우팅 테이블 (`KVM_SET_GSI_ROUTING`)**:
   - 시스템 내의 모든 인터럽트 핀(GSI 번호)을 목적지 vCPU, 인터럽트 벡터(`vector`), 전달 모드(`type`: `"MSI"` 또는 `"IRQCHIP"`), 트리거 모드(`level_triggered`: True/False)로 매핑합니다.
   - `dest_id = 0xff` (255)는 모든 vCPU로 브로드캐스트 전달됩니다.
2. **직접 MSI 전달 (MSI Fast Path)**:
   - virtio 디바이스나 PCI MSI는 사용자 공간 인터럽트 칩을 거치지 않고 호스트 커널의 LAPIC IRR(Interrupt Request Register)로 직접 주입됩니다.
3. **Split Mode 레벨 트리거 EOI 탈출 (`KVM_EXIT_IOAPIC_EOI`)**:
   - 레벨 트리거 인터럽트는 게스트의 서비스 완료 통지(EOI, End of Interrupt)가 필수적입니다.
   - Split IRQCHIP 모드에서는 IOAPIC이 사용자 공간에 있으므로, 게스트 vCPU가 LAPIC EOI 레지스터에 쓰기를 수행할 때 커널은 사용자 공간으로 `KVM_EXIT_IOAPIC_EOI` 이벤트를 발생시켜 QEMU에 인터럽트 라인이 해제되었음을 알립니다.
   - 단, `split_mode = False` (통합 커널 irqchip)인 경우 커널 내부에서 자체 처리되므로 사용자 공간 EOI 탈출(`kvm_exit_ioapic_eoi: False`)이 발생하지 않습니다.
4. **LAPIC 우선순위 딜리버리**:
   - vCPU가 인터럽트를 수락할 때(`VCPU_DELIVER_INTERRUPT`), IRR에 대기 중인 벡터 중 **가장 높은 벡터 번호**가 먼저 ISR(In-Service Register)로 이동하여 서비스됩니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:
- `config`:
  - `num_vcpus`: int (기본값: 4)
  - `split_mode`: bool (기본값: True)
- `operations`: 일련의 연산 배열.

지원되는 연산:
1. `{"op": "SET_GSI_ROUTING", "routes": [{"gsi": int, "type": "MSI"|"IRQCHIP", "dest_id": int, "vector": int, "level_triggered": bool}, ...]}`
   - GSI 라우팅 테이블을 구성합니다.
2. `{"op": "INJECT_GSI", "gsi": int, "level": int}`
   - 지정된 GSI 핀에 인터럽트를 주입합니다. 미등록 GSI인 경우 `EINVAL_UNROUTED_GSI` 반환 및 `invalid_gsi_drops` 카운트.
3. `{"op": "VCPU_DELIVER_INTERRUPT", "vcpu_id": int}`
   - vCPU의 IRR에 대기 중인 최고 우선순위 인터럽트를 ISR로 승격합니다.
4. `{"op": "VCPU_EOI", "vcpu_id": int, "vector": int}`
   - 게스트가 EOI를 수행합니다. Split 모드이고 레벨 트리거 벡터인 경우 `kvm_exit_ioapic_eoi = True` 및 `ioapic_eoi_exits` 카운트.
5. `{"op": "QUERY_IRQ_STATE"}`
   - vCPU별 IRR/ISR 상태, 설정된 GSI 목록, 통계(`stats`)를 반환합니다.

---

## 출력 형식

표준 출력(stdout)으로 각 연산의 결과를 담은 JSON을 한 줄(compact)로 출력합니다:
```json
{"results": [...]}
```
