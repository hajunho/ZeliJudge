# 리눅스 커널 NVDIMM/DAX(Direct Access) 영구 메모리(PMEM) 제로카피 폴트 및 캐시라인 플러시(clwb/sfence) 일관성 엔진

## 문제 설명

현대 초저지연 인메모리 데이터베이스, 고성능 트랜잭션 저널(WAL), 분산 파일시스템에서 **비휘발성 듀얼 인라인 메모리 모듈(NVDIMM / Persistent Memory, PMEM)**은 DRAM 버스(DDR/CXL)에 직접 장착되어 수십~수백 나노초(ns)의 바이트 단위 접근성(Byte-Addressability)과 영속성(Non-Volatility)을 동시에 제공하는 혁신적인 차세대 스토리지 하드웨어입니다.

전통적인 리눅스 블록 스토리지 계층에서는 디바이스와 사용자 공간 사이에 DRAM 페이지 캐시(Page Cache)를 두고, 더티 페이지를 `kswapd`/플러셔 스레드가 비동기 `bio` 요청으로 블록 디바이스에 기록했습니다. 그러나 PMEM에 페이지 캐시를 적용하면 PMEM에서 DRAM으로, 다시 DRAM에서 PMEM으로 데이터가 이중 복사(Double Copy)되어 메모리 대역폭이 반토막 나고 심각한 복사 지연이 발생합니다.

리눅스 커널은 이를 해결하기 위해 **DAX (Direct Access, `fs/dax.c`, `include/linux/dax.h`)** 아키텍처를 도입하였습니다:
1. **페이지 캐시 바이패스 및 직접 매핑**:
   - 사용자가 `-o dax`로 마운트된 파일시스템(ext4-DAX, XFS-DAX)의 파일을 `mmap(..., MAP_SHARED)`할 때, 커널은 DRAM 페이지 캐시를 전혀 할당하지 않습니다.
   - `dax_iomap_fault()`는 파일시스템 익스텐트 트리를 조회하여, 실제 PMEM의 물리 프레임 번호(PFN)를 사용자 가상 메모리 페이지 테이블(PTE: 4KB 또는 PMD: 2MB 휴지 페이지)에 직접 삽입합니다.
   - 애플리케이션은 CPU의 일반적인 메모리 읽기/쓰기 명령(`MOV`)을 통해 커널 시스템 콜이나 I/O 컨텍스트 스위칭 없이 하드웨어 PMEM에 0-Copy로 직접 접근합니다.
2. **CPU 캐시라인 플러시와 영속성 보장 (Persistence Boundary)**:
   - CPU가 메모리에 데이터를 쓸 때, 데이터는 즉시 PMEM 미디어에 기록되는 것이 아니라 CPU의 휘발성 L1/L2/L3 캐시라인에 머무릅니다.
   - 정전(Power Failure) 시 휘발성 캐시에 남은 데이터는 영구 유실되므로, 소프트웨어는 **`clwb` (Cache Line Write Back)** 명령을 통해 캐시라인을 PMEM의 비휘발성 컨트롤러 버퍼로 밀어내고, **`sfence` (Store Fence)** 명령으로 메모리 가시성 순서를 강제해야 합니다.
   - **eADR (Extended Asynchronous DRAM Refresh)** 하드웨어 지원 시, CPU 캐시 자체가 배터리/커패시터 백업 도메인에 포함되므로 `clwb`를 우회하고 `sfence`만으로 영속성을 즉각 달성할 수 있습니다.

본 과제에서는 리눅스 커널 NVDIMM/DAX 서브시스템의 4KB/2MB 페이지 폴트 핸들러, 제로카피 직접 메모리 I/O, `clwb`/`sfence` 캐시라인 추적, `msync` 동기화 및 정전 시 데이터 보존성을 100% 수리·시스템적으로 정밀 시뮬레이션하는 **DAX PMEM Persistence Engine**을 구축합니다.

---

## 시스템 아키텍처 및 메모리 파이프라인

```
+-------------------------------------------------------------------------+
|                User Application (Direct Memory Load / Store)            |
+------------------------------------+------------------------------------+
                                     | mmap() / Direct Access
                                     v
+-------------------------------------------------------------------------+
|                    Linux Kernel DAX Subsystem (fs/dax.c)                |
|  - Page Cache 100% Bypassed (Zero-Copy)                                 |
|  - Fault Handling: 4KB PTE or 2MB PMD -> Direct PFN Table Insertion     |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                  CPU Volatile L1 / L2 / L3 Cachelines                   |
|  - Data dirtied in cacheline (Requires explicit flushing)               |
|  - clwb: Push dirty cacheline to PMEM without eviction                  |
|  - sfence: Memory store barrier guaranteeing global visibility          |
+------------------------------------+------------------------------------+
                                     |
            +------------------------+------------------------+
            | Standard ADR                                    | eADR Supported
            v                                                 v
+---------------------------------------+   +-----------------------------+
|    PMEM Asynchronous DRAM Refresh     |   | Battery-Backed Cache Domain |
|    (Persistent on Memory Bus)         |   | (Immediate Persistence)     |
+---------------------------------------+   +-----------------------------+
```

---

## 핵심 요구사항 및 동작 규칙

### 1. 페이지 폴트 핸들링 (`MMAP_FAULT`)
- 요청된 파일 `offset`에 대해 등록된 `extents` 중 $[\text{start}, \text{start} + \text{length})$ 구간에 포함되는지 검사합니다.
- 매칭되는 경우:
  - $\text{pfn} = \text{pfn\_start} + ((\text{offset} - \text{start}) // 4096)$.
  - `fault_size == 2097152` (2MB): `pmd_faults_2m` 1 증가, 레이턴시 `t_page_fault_2m_ns` 가산.
  - `fault_size == 4096` (4KB): `pte_faults_4k` 1 증가, 레이턴시 `t_page_fault_4k_ns` 가산.
  - 가상 주소 `va`에 PFN 및 크기를 페이지 테이블에 매핑 (`status = "PFN_MAPPED"`).
- 매칭되지 않는 경우: `status = "FAULT_SIGBUS"`.

### 2. 직접 메모리 I/O (`DIRECT_READ`, `DIRECT_WRITE`)
- 요청된 가상 주소 `va`가 매핑되어 있지 않으면 `status = "UNMAPPED_FAULT"`.
- 매핑되어 있는 경우:
  - 오프셋으로부터 정확한 PFN 및 캐시라인 인덱스 산출:
    $$\text{pfn} = \text{entry.pfn} + ((\text{va} - \text{base\_va}) // 4096)$$
    $$\text{offset\_in\_page} = (\text{va} - \text{base\_va}) \% 4096$$
    $$\text{cacheline\_idx} = (\text{pfn} \ll 6) + (\text{offset\_in\_page} // 64)$$
  - 소모 레이턴시: `t_load_store_ns`.
  - `DIRECT_READ`: `direct_memory_reads` 1 증가, `status = "DAX_READ_SUCCESS"`.
  - `DIRECT_WRITE`: `direct_memory_writes` 1 증가, 해당 `cacheline_idx`를 휘발성 캐시 집합(`volatile_cachelines`) 및 `dirty_pfns`에 등록 (`status = "DAX_WRITE_SUCCESS"`).

### 3. 캐시라인 플러시 및 배리어 (`CLWB`, `SFENCE`)
- `CLWB`:
  - `eadr_supported == false`인 경우:
    - 소모 레이턴시: `t_clwb_ns`.
    - `cachelines_flushed_clwb` 1 증가.
    - 해당 `cacheline_idx`가 `volatile_cachelines`에 존재하면 제거하여 비휘발성 미디어로 영속화 (`status = "CLWB_FLUSHED"`).
  - `eadr_supported == true`인 경우:
    - 하드웨어가 캐시를 보존하므로 플러시 불필요 (`status = "EADR_BYPASSED"`, 0ns 소모).
- `SFENCE`:
  - 소모 레이턴시: `t_sfence_ns`.
  - `sfence_barriers_issued` 1 증가 (`status = "SFENCE_ORDERED"`).

### 4. 커널 동기화 및 정전 시뮬레이션 (`MSYNC`, `POWER_FAILURE_SIM`)
- `MSYNC`:
  - `msync_fsync_commits` 1 증가.
  - `eadr_supported == false`이면 현재 남아있는 모든 `volatile_cachelines`에 대해 `clwb` 및 `sfence`를 일괄 실행하여 영속화.
  - `dirty_pfns` 클리어 (`status = "MSYNC_COMMITTED"`).
- `POWER_FAILURE_SIM`:
  - 정전 발생 시, `eadr_supported == false`인 상태에서 `volatile_cachelines`에 아직 남아있는 캐시라인은 전부 영구 소실됩니다.
  - 소실된 캐시라인 수만큼 `metrics["persistence_violations"]` 가산 (`status = "DATA_LOST_DUE_TO_UNFLUSHED_CACHELINE"`).
  - 남아있는 캐시라인이 없거나 `eadr_supported == true`이면 데이터가 온전히 보존됩니다 (`status = "PERSISTED_SAFE"`).

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "config": {
    "eadr_supported": false,
    "t_load_store_ns": 10,
    "t_clwb_ns": 40,
    "t_sfence_ns": 20,
    "t_page_fault_4k_ns": 800,
    "t_page_fault_2m_ns": 1200
  },
  "extents": [
    {"offset": 0, "length": 4194304, "pfn_start": 1048576}
  ],
  "operations": [
    {"id": "OP_01", "type": "MMAP_FAULT", "va": 140733193388032, "offset": 0, "fault_size": 2097152},
    {"id": "OP_02", "type": "DIRECT_WRITE", "va": 140733193388032, "size": 64},
    {"id": "OP_03", "type": "CLWB", "va": 140733193388032},
    {"id": "OP_04", "type": "SFENCE"},
    {"id": "OP_05", "type": "POWER_FAILURE_SIM"}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없는 압축 JSON(`separators=(',', ':')`, `ensure_ascii=False`)을 출력합니다:
```json
{
  "metrics": {
    "operations_total": 5,
    "total_latency_ns": 1270,
    "pte_faults_4k": 0,
    "pmd_faults_2m": 1,
    "direct_memory_reads": 0,
    "direct_memory_writes": 1,
    "cachelines_flushed_clwb": 1,
    "sfence_barriers_issued": 1,
    "msync_fsync_commits": 0,
    "persistence_violations": 0
  },
  "active_mappings_count": 1,
  "dirty_pfns_remaining": 0,
  "op_results": [
    {"op_id": "OP_01", "type": "MMAP_FAULT", "status": "PFN_MAPPED", "va": 140733193388032, "pfn": 1048576, "fault_size": 2097152},
    {"op_id": "OP_02", "type": "DIRECT_WRITE", "status": "DAX_WRITE_SUCCESS", "pfn": 1048576, "cacheline_dirtied": 67108864},
    {"op_id": "OP_03", "type": "CLWB", "status": "CLWB_FLUSHED", "cacheline": 67108864},
    {"op_id": "OP_04", "type": "SFENCE", "status": "SFENCE_ORDERED"},
    {"op_id": "OP_05", "type": "POWER_FAILURE_SIM", "status": "PERSISTED_SAFE", "unpersisted_cachelines_lost": 0}
  ]
}
```

---

## 제약 사항

- $1 \le \text{len}(operations) \le 100$
- $0 \le \text{va} < 2^{64}$
- 모든 시간 파라미터는 $1 \le t \le 100,000$ 범위의 나노초(ns) 정수
- 메모리 계산 및 캐시라인 인덱스는 64비트 정수 연산으로 수행합니다.
