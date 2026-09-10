# 문제 422 심층 이론: 리눅스 커널 CXL 이종 메모리 계층화(Memory Tiering)와 NUMA 밸런싱 아키텍처

---

## 1. CXL 2.0 / 3.0 프로토콜과 이종 메모리 하드웨어 아키텍처

현대 엔터프라이즈 서버와 클라우드 데이터센터 인프라에서 AI/ML 거대 모델 추론, 대규모 인메모리 데이터베이스(Redis, SAP HANA) 등의 워크로드는 테라바이트(TB) 단위의 메모리 용량을 요구합니다. 하지만 기존 DDR 채널 확장 방식은 신호 무결성(Signal Integrity) 저하와 CPU 패키징 핀 수 제한으로 인해 채널당 1~2개 Dimm 이상의 확장이 물리적으로 불가능합니다.

이를 해결하기 위해 인텔, AMD, ARM, 삼성전자, SK하이닉스 등이 주도하여 표준화한 **CXL(Compute Express Link)** 아키텍처는 고속 직렬 차동 신호 방식(PCIe Gen5/Gen6 PHY)을 기반으로 다음과 같은 3가지 서브 프로토콜을 다중화(Multiplexing)하여 제공합니다:

1. **CXL.io**: PCIe 표준과 완벽히 호환되는 I/O 프로토콜로, 디바이스 탐색(Enumeration), 구성 공간 레지스터 접근, 오류 보고 및 가상화 관리 기능을 수행합니다.
2. **CXL.cache**: 호스트 프로세서의 L1/L2/L3 캐시와 가속기(Accelerator) 로컬 캐시 간의 캐시 일관성 트랜잭션을 저지연 플릿(Flit, Flow Control Unit) 단위로 동기화합니다.
3. **CXL.mem**: CPU 코어의 로드/스토어(Load/Store) 명령어를 바이트 단위(Byte-addressable)로 CXL 디바이스의 메모리 컨트롤러로 라우팅하는 프로토콜입니다.

### CXL Type 3 메모리 익스팬더(Memory Expander)의 토폴로지 매핑
CXL Type 3 장치는 CXL.io 및 CXL.mem 프로토콜을 지원하며, 시스템 펌웨어(UEFI/BIOS)는 부팅 과정에서 ACPI 테이블(특히 **CEDT: CXL Early Discovery Table** 및 **HMAT: Heterogeneous Memory Attribute Table**, **CDAT: Coherent Device Attribute Table**)을 통해 CXL 메모리의 물리 주소 범위(SPA, System Physical Address)와 접근 지연 시간(Read/Write Latency), 대역폭(Bandwidth) 특성을 커널에 보고합니다.

리눅스 커널은 이를 **CPU가 없는 노드(CPU-less NUMA Node)**로 등록하며, `mm/memory-tiers.c`는 이 노드들을 대기 시간 및 대역폭 성능에 따라 추상화된 **메모리 티어(Memory Tier)**로 그룹화합니다.

---

## 2. 리눅스 커널 `mm/memory-tiers.c` 계층화 서브시스템

커널 v5.18 이전에는 원격 NUMA 노드나 이종 메모리는 단순히 NUMA 거리(`node_distance`)에 의존하여 처리되었으나, 이는 다양한 지연 시간을 갖는 HBM, DDR5, CXL.mem, PMEM(Persistent Memory)의 다층 계층 구조를 효율적으로 표현하지 못했습니다.

### 2.1 추상 계층 구조: `memory_tier` 와 `memory_dev_type`
리눅스 커널의 계층화 프레임워크는 다음과 같은 핵심 자료구조로 구현됩니다:

```c
struct memory_tier {
    struct list_head list;
    int id;
    nodemask_t nodelist;       /* 해당 티어에 속한 NUMA 노드 비트마스크 */
    int adistance_start;       /* Abstract Distance 구간 */
};

struct memory_dev_type {
    int adistance;             /* 추상 거리: 성능 지표 (낮을수록 고성능) */
    struct list_head tier_sysfs_list;
};
```

- **Abstract Distance ($d_{abs}$)**: 메모리의 성능을 나타내는 무차원 수치입니다. 통상 로컬 DDR 메모리를 기본값(`MEMTIER_DEFAULT = 512`)으로 설정하고, CXL.mem의 읽기 지연 시간 $\Delta t_{latency}$과 대역폭 $\beta$의 비율에 따라 다음과 같이 추상 거리가 할당됩니다:
  $$d_{abs}(CXL) = MEMTIER\_DEFAULT \times \left( \frac{\tau_{CXL}}{\tau_{DDR}} \right) \times \left( \frac{\beta_{DDR}}{\beta_{CXL}} \right)^{\gamma}$$
- 커널은 추상 거리가 짧은 티어를 **상위 티어(Top-Tier)**, 긴 티어를 **하위 티어(Slow-Tier)**로 계층 링크를 형성합니다.

---

## 3. Cold Page 강등 (Demotion) 파이프라인과 `vmscan.c`

과거 커널에서 메모리 부족(`MEM_PRESSURE`)이 발생하면, 백그라운드 스왑 데몬인 `kswapd` 또는 직접 회수(Direct Reclaim) 루틴은 메모리를 확보하기 위해 페이지를 디스크 스왑 디바이스(`zRAM`, NVMe Swap)로 방출했습니다. 이는 수 마이크로초($\mu s$)에서 수 밀리초($ms$)의 심각한 I/O 스톨(Stall)을 유발합니다.

### 3.1 `demote_page_list()`
CXL 티어링이 활성화된 환경에서 커널의 페이지 스캐너(`vmscan.c`)는 스왑 디스크로 페이지를 내리기 전에 먼저 **하위 메모리 티어로의 페이지 마이그레이션(Demotion)**을 시도합니다:

```
[Page Reclaim Trigger] 
       │
       ▼
 shrink_page_list()
       │
       ├─► Page Pinned (mlock, DMA, PageWriteback)? ──► Skip / Keep in Tier 0
       │
       ▼
 demote_page_list()
       │
       ├─► Find Lower Memory Tier Target Node (CXL)
       │
       ├─► migrate_pages(from_node -> to_node, MIGRATE_ASYNC)
       │
       ▼
 Success: Page moves Tier 0 -> Tier 1 (DDR5 -> CXL.mem) [No Disk I/O!]
 Fail: Fallback to Disk Swap
```

이 메커니즘을 통해 NVMe 디스크 I/O 트래픽을 거의 발생시키지 않으면서도, 나노초($ns$) 단위의 레이턴시를 유지하는 CXL 메모리로 콜드 페이지를 투명하게 축출(Eviction)할 수 있습니다.

---

## 4. Hot Page 승격 (Promotion)과 AutoNUMA Hinting Fault

CXL 메모리에 상주하는 페이지가 다시 애플리케이션의 핵심 핫스팟(Working Set)이 되었을 때, 계속 CXL 메모리에서만 읽고 쓰면 버스 레이턴시 오버헤드로 인해 IPC(Instructions Per Cycle) 성능이 저하됩니다. 따라서 리눅스 커널은 **AutoNUMA 밸런싱(`CONFIG_NUMA_BALANCING`)** 엔진을 확장하여 핫 페이지를 고속 로컬 DDR5로 승격(Promotion)시킵니다.

### 4.1 NUMA Hinting Fault의 동작 원리
1. **PTE 비트 조작 (`change_prot_numa`)**:
   커널 스레드는 주기적으로 태스크의 가상 주소 공간을 순회하면서, 하위 티어(CXL)에 매핑된 페이지 테이블 엔트리(PTE)의 유효 비트를 일시적으로 무효화(특수 권한 `PROT_NONE` 플래그 설정)합니다.
2. **페이지 폴트 트랩 (`do_numa_page`)**:
   애플리케이션 코드가 해당 메모리 주소에 접근하는 순간 CPU MMU는 하드웨어 페이지 폴트(Page Fault)를 발생시킵니다.
   커널의 폴트 핸들러인 `do_numa_page()`는 이 폴트가 실제 유효하지 않은 주소 접근(Segmentation Fault)이 아니라, 접근 빈도를 측정하기 위한 의도적인 **힌팅 폴트(NUMA Hinting Fault)**임을 식별합니다.
3. **핫니스 판별 및 마이그레이션**:
   커널은 해당 페이지의 접근 이력을 추적하여 임계값(`promotion_threshold`)을 초과하면 `migrate_misplaced_page()`를 호출하여 페이지를 최상위 DDR5 티어로 비동기/동기 승격시킵니다.
4. **역방향 압박 해소 (Balance Cascade)**:
   이때 DDR5 티어의 가용 용량이 부족하면, DDR5에서 가장 차가운 페이지를 즉시 CXL 티어로 맞교환(Swap/Demote)하여 상위 티어의 오버플로우를 방지합니다.

---

## 5. 결론 및 실무 시스템 엔지니어링 통찰

CXL 이종 메모리 티어링은 클라우드 가상화 및 하이퍼스케일러 환경에서 메모리 TCO(Total Cost of Ownership)를 30% 이상 절감하는 핵심 기술입니다.
실무 커널 엔지니어는 다음 설계 트레이드오프를 반드시 고려해야 합니다:
- **쓰래싱(Thrashing) 방지**: 페이지가 DDR5와 CXL 사이를 빈번하게 오가는 핑퐁 현상(Ping-pong migration)을 방지하기 위해 이력 윈도우(History window)와 이중 임계값(Hysteresis threshold)을 엄격히 설계해야 합니다.
- **DMA 및 핀 고정 페이지 격리**: RDMA, DPDK, GPU P2P DMA 등 하드웨어 디바이스가 물리 주소를 직접 참조하는 버퍼(`mlock`, `pin_user_pages`)는 마이그레이션 도중 물리 주소가 변경되면 데이터 오염이 발생하므로 반드시 강등 대상에서 완전히 배제되어야 합니다.
