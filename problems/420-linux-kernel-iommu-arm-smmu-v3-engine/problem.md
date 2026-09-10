# 문제 420: Linux 커널 ARM64 하드웨어 가상화 SMMUv3(System MMU) 2단계 주소 변환(Stage 1+2), Stream Table(STE), 명령 큐(CMDQ) 동기화 및 DMA 이벤트 큐(EVTQ) 장애 처리 엔진

## 문제 설명

현대 엔터프라이즈 ARM64 클라우드 서버(AWS Graviton3/4, Ampere Altra, NVIDIA Grace Hopper, Apple Silicon M-series)와 5G 통신 인프라에서 고성능 I/O 디바이스(PCIe NVMe SSD, 100GbE/400GbE 스마트 NIC, GPU, DPU)는 CPU의 개입 없이 물리 메모리에 직접 접근하는 **DMA (Direct Memory Access)**를 수행합니다.

그러나 IOMMU(I/O Memory Management Unit)가 없는 시스템에서 디바이스가 물리 주소(Physical Address)에 직접 접근하면 다음과 같은 치명적인 보안 및 가상화 한계가 발생합니다:
1. **DMA 보안 취약점 (DMA Attacks)**: 오작동하거나 악의적으로 조작된 PCIe 디바이스가 커널 영역이나 다른 사용자의 메모리를 덮어쓸 수 있습니다.
2. **연속 물리 메모리 강제**: 물리적으로 단편화된 4KB 페이지들에 대해 대용량 DMA를 수행하기 위해 고비용의 바운스 버퍼(Bounce Buffer) 복사가 필요합니다.
3. **가상 머신(KVM/VFIO) 패스스루 불가**: 가상 머신(게스트 OS)이 알고 있는 주소는 게스트 물리 주소(GPA)이므로, 호스트 물리 주소(HPA)로의 하드웨어 변환 계층 없이는 디바이스 직접 할당(Direct Device Assignment)이 불가능합니다.

이 문제를 해결하고 ARM64 서버의 고성능 가상화와 메모리 격리를 완벽하게 실현하기 위해 ARM과 리눅스 커널 커뮤니티가 개발한 하드웨어 가상화 표준이 바로 **ARM SMMUv3 (System MMU Architecture v3, `drivers/iommu/arm/arm-smmu-v3/arm-smmu-v3.c`, `CONFIG_ARM_SMMU_V3`)**입니다.

---

### ARM SMMUv3 핵심 아키텍처 및 동작 메커니즘

SMMUv3는 CPU의 2단계 페이징(MMU) 아키텍처와 완전히 대칭되는 I/O 가상화 서브시스템을 제공합니다:

1. **스트림 테이블 (Stream Table, STE)**:
   - PCIe 디바이스의 Requester ID(Bus:Device:Function)는 32비트 크기의 **`StreamID`**로 매핑됩니다.
   - SMMU는 메모리에 위치한 스트림 테이블에서 `StreamID`를 인덱스로 하여 **STE(Stream Table Entry)**를 조회합니다:
     - **`BYPASS`**: 주소 변환을 수행하지 않고 $IOVA == PA$로 직접 통과시킵니다 (레거시 부팅 모드).
     - **`STAGE1`**: 호스트 프로세스의 가상 주소 공간($IOVA \to PA/IPA$)을 변환합니다. Context Descriptor(CD) 테이블을 참조합니다.
     - **`STAGE2`**: 가상 머신(KVM 게스트)의 게스트 물리 주소를 호스트 물리 주소($GPA \to HPA$)로 변환하여 완벽한 VM 간 메모리 격리를 보장합니다.
     - **`NESTED` (Stage 1 + Stage 2)**: 2단계 중첩 변환을 수행합니다! 게스트 OS가 관리하는 $IOVA \to GPA$ (Stage 1) 변환과 하이퍼바이저가 제어하는 $GPA \to HPA$ (Stage 2) 변환이 하드웨어 내부에서 연속으로 일어납니다.
     - **`ABORT`**: 해당 스트림의 모든 DMA 요청을 즉시 거부합니다.

2. **명령 큐 (Command Queue, `CMDQ`)**:
   - 커널 드라이버가 SMMU 하드웨어에 제어 명령을 전달하는 링 버퍼(Circular Buffer)입니다:
     - `CFGI_STE`: 변경된 Stream Table Entry 캐시를 무효화합니다.
     - `CFGI_CD`: 변경된 Context Descriptor 캐시를 무효화합니다.
     - `TLBI_NH_VA`: Non-secure 가상 주소에 대한 SMMU 하드웨어 TLB 캐시라인을 무효화합니다.
     - **`CMD_SYNC`**: 하드웨어 동기화 장벽(Barrier) 명령어로, 이전에 제출된 모든 무효화 명령이 SMMU 내부 파이프라인에서 완전히 완료되었음을 보장합니다.

3. **이벤트 큐 (Event Queue, `EVTQ`)**:
   - DMA 주소 변환 실패나 접근 권한 위반이 발생했을 때 SMMU 하드웨어가 커널로 오류 로그를 기록하는 링 버퍼입니다:
     - **`F_TRANSLATION`**: 대상 가상 주소(IOVA/GPA)에 대한 페이지 매핑이 존재하지 않는 경우 (DMA 페이지 폴트).
     - **`F_PERMISSION`**: 읽기 전용(Read-Only) 도메인에 대해 DMA 쓰기를 시도한 경우.
     - **`F_STREAM_DISABLED`**: STE가 설정되지 않았거나 `ABORT` 모드인 경우.
     - **`F_BAD_STE`**: 잘못된 STE 포맷이나 미지원 모드인 경우.

여러분은 ARM SMMUv3의 Stream Table(STE) 설정, 4대 변환 모드(BYPASS, STAGE1, STAGE2, NESTED), CMDQ 명령 발행 및 `CMD_SYNC` 장벽, EVTQ 오류 감지 및 DMA 주소 변환 엔진을 충실히 모델링하는 시뮬레이터를 구현해야 합니다.

---

## 시스템 아키텍처 다이어그램

```
+==================================================================================================+
|                         ARM64 SMMUv3 Hardware Architecture & DMA Flow                            |
+==================================================================================================+

   [ PCIe Device (StreamID: Requester ID B:D:F) ]
          |
          | DMA Request (IOVA, Read/Write)
          v
 +-------------------------------------------------------------------------------------------------+
 | ARM SMMUv3 Hardware Controller (drivers/iommu/arm/arm-smmu-v3/)                                 |
 |                                                                                                 |
 |  [ Step 1: Stream Table Lookup ]                                                                |
 |    Index Stream Table by StreamID ===> Retrieves STE (Stream Table Entry)                       |
 |    Config Mode: BYPASS | STAGE1 | STAGE2 | NESTED | ABORT                                       |
 |                                                                                                 |
 |  [ Step 2: Address Translation Pipeline ]                                                       |
 |                                                                                                 |
 |    * Mode BYPASS:                                                                               |
 |        PA = IOVA (No Translation, Direct Physical Access)                                       |
 |                                                                                                 |
 |    * Mode STAGE1 (Host Process SVA):                                                            |
 |        IOVA =====[ Stage 1 Context Descriptor (CD) ]=====> PA                                   |
 |                                                                                                 |
 |    * Mode STAGE2 (KVM Hypervisor VM Isolation):                                                 |
 |        GPA (IOVA) =====[ Stage 2 Page Table (VMID) ]=====> HPA (Physical Memory)                |
 |                                                                                                 |
 |    * Mode NESTED (Two-Stage Nested Virtualization):                                             |
 |        GVA (IOVA) =====[ Stage 1 (Guest OS) ]=====> GPA =====[ Stage 2 (Host KVM) ]=====> HPA   |
 |                                                                                                 |
 |  [ Step 3: Hardware Exception & Fault Handling ]                                                |
 |    - If Unmapped IOVA/IPA   ===> Record F_TRANSLATION in EVTQ Ring Buffer                       |
 |    - If Write to Read-Only  ===> Record F_PERMISSION in EVTQ Ring Buffer                        |
 |    - If STE Disabled/Abort  ===> Record F_STREAM_DISABLED in EVTQ Ring Buffer                   |
 +-------------------------------------------------------------------------------------------------+
          ^                                                                  |
          |                                                                  v
 +-----------------------+                                        +-----------------------+
 | Command Queue (CMDQ)  |                                        | Event Queue (EVTQ)    |
 |  - CFGI_STE           |                                        |  - F_TRANSLATION      |
 |  - TLBI_NH_VA         |                                        |  - F_PERMISSION       |
 |  - CMD_SYNC (Barrier) |                                        |  - F_STREAM_DISABLED  |
 +-----------------------+                                        +-----------------------+
```

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "config": {
    "cmdq_size": 32,
    "evtq_size": 32
  },
  "trace": [
    {
      "time": 0,
      "type": "CONFIG_STE",
      "stream_id": 10,
      "config": "STAGE1",
      "s1_mappings": {"4096": 2281705472},
      "s1_ro": false
    },
    {
      "time": 1,
      "type": "DMA_REQUEST",
      "stream_id": 10,
      "iova": 4096,
      "access_type": "READ"
    },
    {
      "time": 2,
      "type": "SUBMIT_CMD",
      "op": "CMD_SYNC"
    }
  ]
}
```

- `config.cmdq_size`: 커맨드 큐 용량.
- `config.evtq_size`: 이벤트 큐 용량.
- `trace`: 시간 순서대로 실행되는 이벤트 리스트:
  - `CONFIG_STE`: `{"time": t, "type": "CONFIG_STE", "stream_id": s, "config": "...", "s1_mappings": {...}, "s2_mappings": {...}, "s1_ro": bool, "s2_ro": bool}`
  - `SUBMIT_CMD`: `{"time": t, "type": "SUBMIT_CMD", "op": "CMD_SYNC" | "CFGI_STE" | "TLBI_NH_VA", "args": ...}`
  - `DMA_REQUEST`: `{"time": t, "type": "DMA_REQUEST", "stream_id": s, "iova": addr, "access_type": "READ" | "WRITE"}`

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 JSON 객체를 한 줄로 출력합니다 (compact JSON, `ensure_ascii=False`):

```json
{
  "summary": {
    "total_dma_requests": 1,
    "successful_dma": 1,
    "faulted_dma": 0,
    "cmdq_commands_processed": 1,
    "sync_completions": 1,
    "evtq_events_logged": 0,
    "translations_by_mode": {
      "BYPASS": 0,
      "STAGE1": 1,
      "STAGE2": 0,
      "NESTED": 0
    }
  },
  "evtq": [],
  "dma_logs": [
    {
      "time": 1,
      "stream_id": 10,
      "mode": "STAGE1",
      "iova": "0x1000",
      "pa": "0x88001000",
      "access_type": "READ",
      "status": "SUCCESS"
    }
  ],
  "event_logs": [ ... ]
}
```
