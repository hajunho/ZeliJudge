# Problem #387: Linux Kernel KVM APICv & Posted-Interrupt Processing (PIR/PID) Engine (`arch/x86/kvm/vmx/posted_intr.c`, `arch/x86/kvm/lapic.c`)

## 문제 설명

하이퍼바이저(KVM/QEMU) 기반 클라우드 인프라에서 가상 CPU(vCPU)로의 인터럽트 전달은 역사적으로 가장 무거운 연산 중 하나였습니다.
전통적인 가상화 환경에서는 외부 물리 디바이스(SR-IOV NIC, NVMe) 또는 다른 vCPU가 인터럽트를 전송할 때마다 **VM-Exit**가 발생하여 호스트 커널(KVM)로 제어가 강제 전환되었고, 소프트웨어 vAPIC 상태를 수정한 뒤 **VM-Entry**로 게스트를 재개해야 했습니다. 100GbE 고대역폭 환경에서는 수십만 건의 VM-Exit 폭풍(VM-Exit Storm)으로 인해 전체 시스템 성능의 40% 이상이 낭비되었습니다.

인텔과 리눅스 커널은 이를 근본적으로 해결하기 위해 **APICv(APIC 가상화)** 및 **포스티드 인터럽트(Posted-Interrupt Processing / PIR, PID)** 메커니즘을 도입했습니다:

```
+----------------------------------------------------------------------------------------------------+
|                                KVM APICv Posted Interrupt Flow                                     |
+----------------------------------------------------------------------------------------------------+
| [ Source: PCIe Device (VT-d PI) / Another vCPU ]                                                   |
|   | 1. Atomically set bit 'vector' in Posted-Interrupt Descriptor (PID) PIR bitmap (256 bits)      |
|   | 2. Check 'ON' (Outstanding Notification) bit and 'SN' (Suppress Notification) bit              |
|   | 3. Send physical Notification Event (NV: 0xf2) to target Physical CPU core                     |
+---+------------------------------------------------------------------------------------------------+
| [ Destination Physical Core Hardware Microcode ]                                                   |
|   | Case A: vCPU in 'GUEST_RUNNING' (Guest Non-Root Mode):                                         |
|   |   -> CPU Hardware Microcode atomically syncs PIR bits into vAPIC IRR (NO VM-EXIT!)             |
|   |   -> Clear PID.ON bit, Guest OS services interrupt directly (Zero-Exit Fastpath)              |
|   | Case B: vCPU in 'GUEST_BLOCKED' (HLT / Idle Sleep):                                            |
|   |   -> Wakeup Vector (NV: 0xf3) wakes host physical core from idle sleep                         |
|   |   -> KVM kicks vCPU thread back to GUEST_RUNNING and delivers interrupt                        |
|   | Case C: vCPU in 'HOST_ROOT' (Inside Hypervisor / Exited):                                       |
|   |   -> Bits remain pending in memory PIR; automatically synced upon next VM-Entry                |
+----------------------------------------------------------------------------------------------------+
```

### 포스티드 인터럽트 디스크립터 (PID, `struct pi_desc`) 구조
- `pir[8]`: 256비트 포스티드 인터럽트 요청 비트맵.
- `on` (Bit 0): 미처리 통지(Outstanding Notification) 플래그. 이미 1인 경우 중복 IPI 발송을 억제하여 IPI 결합(Coalescing) 수행.
- `sn` (Bit 1): 통지 억제(Suppress Notification) 플래그. 게스트가 인터럽트를 처리 중이거나 인터럽트가 비활성화된 경우 물리 IPI 생성을 차단.
- `nv`: 통지 벡터 (`POSTED_INTR_VECTOR = 0xf2`).
- `wakeup_nv`: 유휴 vCPU 깨우기 통지 벡터 (`POSTED_INTR_WAKEUP_VECTOR = 0xf3`).

### 가상 APIC (vAPIC) 및 우선순위 제어
- `irr` (Interrupt Request Register, 256비트): PIR에서 동기화된 대기 인터럽트 비트맵.
- `isr` (In-Service Register, 256비트): 현재 게스트에서 처리 중인 최고 우선순위 벡터.
- `tpr` (Task Priority Register): 작업 우선순위 레지스터. $	ext{PPR} = \max(	ext{TPR}, 	ext{highest\_isr})$보다 높은 벡터만이 게스트에 디스패치됩니다.
- `EOI` (End of Interrupt): 게스트가 ISR 최상위 벡터를 클리어합니다.

당신은 KVM APICv의 포스티드 인터럽트 디스크립터(PID), 3대 실행 상태 전이, 제로-엑시트 다이렉트 전달, 억제 플래그(SN) 및 vAPIC 우선순위 레지스터 상태 머신을 시뮬레이션하는 엔진을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "num_vcpus": 4
  },
  "commands": [
    {"op": "POST_INTR", "target_vcpu": 0, "vector": 48},
    {"op": "GUEST_STEP", "vcpu_id": 0},
    {"op": "GUEST_EOI", "vcpu_id": 0}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없이 컴팩트한 단일 JSON 객체를 출력합니다:

```json
{
  "vcpus": {
    "0": {
      "state": "GUEST_RUNNING",
      "highest_irr": -1,
      "highest_isr": -1,
      "tpr": 0,
      "pid_on": 0,
      "pid_sn": 0
    }
  },
  "direct_deliveries": 1,
  "wakeup_ipis": 0,
  "suppressed_notifications": 0,
  "vm_exits_avoided": 1,
  "events": [ ... ]
}
```
