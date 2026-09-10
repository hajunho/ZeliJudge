# Theory #436: 리눅스 커널 mm/dmapool.c 일관성 DMA 소형 할당자 아키텍처

## 1. 개요 및 배경 (Coherent DMA Memory & Sub-Page Allocation)

### 1.1 하드웨어 DMA와 캐시 일관성(Coherency)의 문제
PCIe 버스에 연결된 고속 디바이스(NVMe 컨트롤러, 100GbE NIC)는 호스트 CPU의 개입 없이 시스템 메모리에 직접 읽고 쓰는 DMA(Direct Memory Access)를 수행합니다.
- **스트리밍 DMA (Streaming DMA)**: 네트워크 패킷 데이터 버퍼처럼 한 번 전송하고 끝나는 경우 `dma_map_single()`을 통해 CPU 캐시라인을 무효화(Invalidate) 또는 플러시(Flush)합니다.
- **일관성 DMA (Consistent/Coherent DMA)**: 명령 큐 디스크립터(Ring Descriptor, Doorbell, Status Buffer)처럼 CPU와 디바이스가 동시에 빈번하게 읽고 써야 하는 메타데이터는 캐시 플러시 오버헤드 없이 하드웨어 레벨에서 일관성이 보장되는 **비캐시형(Uncached) 또는 하드웨어 스누핑(Coherent) 메모리**에 위치해야 합니다.

### 1.2 dma_alloc_coherent의 페이지 단위 제약
커널이 일관성 DMA 메모리를 요청할 때 호출하는 `dma_alloc_coherent()`는 페이지 테이블(PTE)의 캐시 무효화 속성(x86의 `_PAGE_PWT | _PAGE_PCD` 또는 ARM64의 `PROT_DEVICE_nGnRE`)을 조작해야 하므로, **최소 단위가 4KB 물리 페이지**입니다.
- NVMe 제출 큐 엔트리(SQE) 크기: 정확히 64바이트
- 이더넷 수신 디스크립터 크기: 16~32바이트
- 만약 디스크립터마다 4KB를 할당하면 메모리의 99%가 낭비되며, IOMMU 매핑 테이블과 ZONE_DMA32가 즉각 고갈됩니다.

---

## 2. mm/dmapool.c의 설계 및 데이터 구조

`mm/dmapool.c`는 `kmem_cache`(SLAB)의 설계 원리를 DMA 일관성 메모리에 적용한 특수 할당자입니다.

```c
struct dma_pool {
    struct list_head page_list;  /* 할당된 dma_page 연결 리스트 */
    size_t size;                 /* 블록 크기 (bytes) */
    struct device *dev;          /* 소속 디바이스 포인터 */
    size_t allocation;           /* 단일 페이지 크기 (PAGE_SIZE) */
    size_t boundary;             /* DMA 경계 (주소 랩어라운드 방지) */
};

struct dma_page {
    struct list_head page_list;
    void *vaddr;                 /* CPU 가상 주소 */
    dma_addr_t dma;              /* PCIe 버스 물리 DMA 주소 */
    unsigned int in_use;         /* 현재 사용 중인 블록 개수 */
    unsigned int offset;         /* 다음 번 프리 블록 오프셋 */
};
```

---

## 3. 핵심 알고리즘 및 생명주기

### 3.1 할당 알고리즘 (dma_pool_alloc)
1. `dma_pool`의 `page_list`를 순회하며 여유 블록이 남아있는 `dma_page`를 탐색합니다.
2. 만약 모든 페이지가 가득 찼다면:
   - `dma_alloc_coherent(pool->dev, pool->allocation, &dma, flags)`를 호출하여 새로운 4KB 일관성 페이지를 확보합니다.
   - 페이지를 슬라이싱하여 프리 오프셋 큐를 구성하고 `page_list`에 추가합니다.
3. 대상 페이지에서 블록 오프셋을 추출하고 `page->in_use++`를 수행합니다.
4. 디바이스가 접근할 물리 주소 `*dma_handle = page->dma + offset`과 CPU 포인터 `page->vaddr + offset`을 반환합니다.

### 3.2 해제 알고리즘 (dma_pool_free)
1. 해제할 가상 주소와 DMA 핸들이 속한 `dma_page`를 찾습니다.
2. 블록 오프셋을 프리리스트에 반환하고 `page->in_use--`를 수행합니다.
3. **페이지 자동 반환(Reclaim)**:
   - 만약 `page->in_use == 0`이 되고 풀에 다른 여유 페이지가 존재한다면, 해당 페이지 전체를 `dma_free_coherent()`로 OS에 즉각 반환합니다.
   - 이를 통해 장시간 구동되는 서버에서 불필요한 DMA 메모리 누수를 원천 차단합니다.

---

## 4. 실무 디바이스 드라이버 활용 사례

- **NVMe 호스트 컨트롤러 (`drivers/nvme/host/pci.c`)**:
  - `nvme_alloc_queue()`에서 PRP(Physical Region Page) 리스트 풀을 `dma_pool_create("nvme-prp", dev, 512, 4, 0)`로 생성하여 I/O 디스크립터를 초저지연 할당합니다.
- **xHCI USB 3.0 컨트롤러 (`drivers/usb/host/xhci-mem.c`)**:
  - 수천 개의 USB 엔드포인트 전송 링(TRB, 16바이트)을 `dma_pool`로 관리하여 단편화 없는 안정적인 데이터 스트리밍을 구현합니다.
