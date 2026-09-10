# 이론 문서 408: Linux 커널 CMA(Contiguous Memory Allocator) 및 물리적 메모리 조각화 제어 아키텍처

## 1. 개요 및 배경: 물리적 연속 메모리 요구와 외부 단편화(External Fragmentation)

현대 범용 운영체제는 가상 메모리(Virtual Memory)와 MMU(Memory Management Unit)의 페이징(Paging) 메커니즘 덕분에 사용자 프로세스에게 연속된 가상 주소 공간(Virtual Address Space)을 제공합니다. 가상 주소 공간에서 연속된 수백 MB의 버퍼라 할지라도, 실제 물리적 RAM 프레임(Physical Page Frame)은 시스템 전체에 흩어져 있는 불연속적인 4KB 페이지들로 구성되는 것이 일반적입니다.

그러나 멀티미디어 및 고성능 I/O 하드웨어의 세계는 완전히 다릅니다:
1. **DMA 마스터 하드웨어 제약**: 고해상도 카메라 센서 ISP, 4K/8K H.265 비디오 디코더/엔코더 하드웨어, GPU 디스플레이 스캔아웃 엔진 등은 Scatter-Gather I/O를 지원하지 않거나, 지원하더라도 높은 하드웨어 복잡도와 전력 소모, 버스 대역폭 낭비가 발생합니다.
2. **IOMMU 오버헤드**: IOMMU(ARM SMMU, Intel VT-d)가 장착된 고성능 서버 환경이라 하더라도, IOTLB 미스(Miss)로 인한 지연 시간(Latency) 스파이크와 추가적인 페이지 테이블 워크(Page Table Walk) 오버헤드는 지연 시간에 극도로 민감한 초고화질 실시간 비디오 프레임 레이트 처리에 치명적일 수 있습니다.
3. **외부 단편화(External Fragmentation)의 필연성**: 시스템이 수 시간~수 주 동안 가동되면서 파일 캐시 생성, 프로세스 포크 및 종료, 소규모 커널 오브젝트 할당이 반복되면, 여유 메모리가 수 GB 이상 남아있더라도 물리적으로 연속된 64MB~128MB 크기의 단일 버퍼는 전혀 찾아볼 수 없는 극심한 외부 단편화 상태에 직면합니다.

과거 임베디드 리눅스 시스템은 이를 해결하기 위해 부팅 시점 커널 파라미터(`mem=...`)로 특정 물리 메모리 주소를 일반 커널 풀에서 완전히 배제하는 **예약 메모리(Carveout Memory)** 기법을 사용했습니다. 하지만 이 방식은 비디오 재생이나 카메라 촬영을 하지 않는 동안에도 귀중한 시스템 RAM의 상당 부분이 영구적으로 방치되어 유휴화되는 치명적인 자원 낭비를 유발했습니다.

---

## 2. Linux 커널 CMA의 아키텍처 및 철학

리눅스 커널 3.5에 도입된 **CMA (Contiguous Memory Allocator, `mm/cma.c`)**는 "물리적 연속성 보장"과 "평상시 메모리 활용 극대화"라는 상충되는 두 목표를 완벽하게 조화시킨 아키텍처입니다.

```
+--------------------------------------------------------------------------------------------------+
| Normal Operation: CMA as MOVABLE Memory                                                          |
|                                                                                                  |
| [ Physical DRAM Address Space ]                                                                  |
|   +---------------------------------------+---------------------------------------------------+  |
|   | Regular Buddy System (ZONE_NORMAL)    | CMA Reserved Region (MIGRATE_CMA)                 |  |
|   | [Kernel Slab] [Page Tables] [App Heap]| [Page Cache Chunk 1] [App Anonymous Pages]        |  |
|   +---------------------------------------+---------------------------------------------------+  |
|                                                     |                                            |
|                                                     v                                            |
|                                            Freely utilized by MOVABLE allocations!               |
+--------------------------------------------------------------------------------------------------+
                                                     |
                                                     | DMA Driver calls cma_alloc(size=64MB)
                                                     v
+--------------------------------------------------------------------------------------------------+
| On-Demand Evacuation & Pageblock Isolation                                                       |
|                                                                                                  |
| 1. Pageblock Migration Type: MIGRATE_CMA ---> MIGRATE_ISOLATE (Stop new allocations)             |
| 2. migrate_pages() evacuates Page Cache & Anonymous Pages into Buddy Movable Pool               |
| 3. Hand over pristine, zero-overhead physically contiguous buffer to DMA Device                  |
+--------------------------------------------------------------------------------------------------+
```

### 2.1 마이그레이션 타입(Migrate Types)과 페이지블록(Pageblock)
리눅스 버디 할당기는 물리적 메모리를 `pageblock_order`(ARM64의 경우 4KB 페이지 기준 Order 9: 512페이지 = 2MB, 또는 Order 10: 1024페이지 = 4MB) 단위의 페이지블록으로 분할하여 관리합니다. 각 페이지블록은 `pageblock_flags`에 마이그레이션 타입을 부여받습니다:
- `MIGRATE_UNMOVABLE`: 커널 슬랩, 페이지 테이블, 소켓 버퍼 등 물리 주소를 변경할 수 없는 할당.
- `MIGRATE_RECLAIMABLE`: 디렉터리 엔트리(Dentry), 아이노드(Inode) 캐시 등 드롭할 수 있는 메모리.
- `MIGRATE_MOVABLE`: 파일 시스템 페이지 캐시, 사용자 익명 메모리 등 페이지 테이블 엔트리(PTE)나 페이지 캐시 라디스 트리/xarray를 수정하여 안전하게 다른 물리 주소로 복사/이동시킬 수 있는 메모리.
- `MIGRATE_CMA`: CMA 전용 마이그레이션 타입. 오직 `MIGRATE_MOVABLE` 성격의 할당만 이 영역에 들어올 수 있으며, `UNMOVABLE` 요청은 절대로 이 블록에 진입할 수 없습니다.
- `MIGRATE_ISOLATE`: 마이그레이션 및 연속 할당 작업을 수행하기 위해 외부 접근을 완전히 차단한 격리 상태.

---

## 3. 페이지블록 격리 및 마이그레이션 세부 동작 흐름

`cma_alloc()`이 호출되었을 때 커널 내부(`mm/cma.c`, `mm/page_isolation.c`, `mm/migrate.c`)에서 수행되는 트랜잭션 절차는 다음과 같습니다:

```
    cma_alloc(cma, count, align_order)
                   |
                   v
    [ Bitmap First-Fit Search ]  ---> (No contiguous slot?) ---> return -ENOMEM
                   |
                   | Found aligned PFN range [start, start + count)
                   v
    [ start_isolate_page_range() ]
      - Convert covering pageblocks from MIGRATE_CMA to MIGRATE_ISOLATE
      - Buddy allocator can no longer allocate new pages in this range
                   |
                   v
    [ Scan Occupied Pages in Range ]
      - Check PagePinned (get_user_pages, Direct I/O pin)
      - If ANY page is PINNED:
          ===> ABORT!
          ===> undo_isolate_page_range()
          ===> Return CMA_ERR_PINNED_PAGE_COLLISION
      - Check Buddy Free Movable Memory
      - If buddy_movable_free < occupied_pages:
          ===> ABORT!
          ===> undo_isolate_page_range()
          ===> Return CMA_ERR_MIGRATION_NO_MEM
                   |
                   | Pre-checks passed
                   v
    [ migrate_pages() Engine ]
      - Allocate new target pages from Buddy Movable Pool
      - Copy page data & sync PageStruct flags
      - Update Virtual Memory PTEs / File PageCache radix-tree to point to new PFN
      - Flush CPU TLBs for updated mappings
      - Free old CMA physical page frames
                   |
                   v
    [ Handover Buffer to DMA Driver ]
      - Mark range as DMA-occupied
      - Pageblocks remain MIGRATE_ISOLATE (or partial block CMA tracking)
      - Return physical address / dma_addr_t
```

### 3.1 Pinned Page(고정된 페이지) 충돌과 원자적 롤백의 당위성
사용자 프로세스가 `read(fd, buf, size)` 시스템 콜을 호출하거나, 네트워크 RDMA가 사용자 버퍼를 등록할 때 커널은 메모리 복사를 방지하기 위해 `get_user_pages()`를 통해 해당 가상 주소에 매핑된 물리 페이지의 참조 카운트(`page->_refcount`)를 증가시키고 핀(Pin) 상태로 만듭니다.
- 하드웨어 컨트롤러가 현재 해당 물리 주소로 직접 DMA 쓰기를 수행하고 있을 수 있으므로, 이 페이지는 물리 주소를 절대 옮길 수 없습니다.
- 만약 CMA 할당기가 고정된 페이지를 강제로 마이그레이션하려 한다면 DMA 데이터 오염이나 커널 패닉이 발생합니다.
- 따라서 커널은 단 하나의 페이지라도 핀되어 있다면 전체 작업을 즉시 취소하고, 앞서 `MIGRATE_ISOLATE`로 설정했던 모든 페이지블록을 원자적으로 `undo_isolate_page_range()`를 통해 원상태(`MIGRATE_CMA`)로 복구해야 합니다.

---

## 4. 실무 시스템 최적화 및 고려사항

1. **CMA 풀 크기 산정의 트레이드오프**:
   - CMA 풀을 너무 크게 잡으면 부팅 시 커널 가상 메모리 맵(`struct page` 배열) 오버헤드가 증가하며, 마이그레이션 대상 페이지가 많아져 `cma_alloc()` 시의 대기 지연 시간(Allocation Latency)이 길어집니다.
   - 반대로 너무 작게 잡으면 4K 고화질 비디오 녹화 중 버퍼 할당 실패로 프레임 드롭(Frame Drop)이 발생합니다.
2. **다중 CMA 영역(Multi-CMA Pools)**:
   - 최신 안드로이드 및 리눅스 시스템은 장치별 특성에 따라 여러 개의 독립된 CMA 영역을 운영합니다 (예: `cma_vpu`, `cma_camera`, `cma_audio`).
   - 특정 장치의 빈번한 할당/해제가 다른 장치의 연속 메모리 가용성에 영향을 주지 않도록 하드웨어 도메인별로 풀을 분리합니다.
3. **메모리 압박(Memory Pressure) 하에서의 마이그레이션 지연**:
   - 시스템 전체의 메모리가 고갈된 상태에서 CMA 할당이 발생하면, 기존 CMA 페이지들을 대피시킬 일반 버디 풀 여유 메모리가 없어 페이지 회수(Reclaim) 및 스왑(Swap-out)이 연쇄적으로 발동하며 심각한 시스템 버벅임(Jank)을 초래할 수 있습니다.
