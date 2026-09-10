# Problem #436: 리눅스 커널 디바이스 드라이버 & 메모리: mm/dmapool.c 일관성 DMA 소형 할당자(dma_pool) 및 페이지 슬라이싱·하드웨어 주소 매핑 엔진

## 🌟 개요 (Executive Summary)
현대 리눅스 커널의 고성능 PCIe 디바이스 드라이버(NVMe SSD 드라이버 `drivers/nvme/host/pci.c`, Intel 100GbE `ice/i40e`, Mellanox `mlx5`, USB 3.0 `xhci-hcd`)는 하드웨어와 통신하기 위해 수만 개의 소형 디스크립터(Descriptor, 예: 64바이트 NVMe SQE, 16바이트 CQE, 32바이트 이더넷 패킷 디스크립터)를 필요로 합니다.
이러한 디스크립터는 CPU 캐시와 PCIe 디바이스 버스 간의 데이터 불일치를 방지하기 위해 반드시 **캐시 일관성(Cache-Coherent)이 보장된 DMA 메모리**에 위치해야 합니다.

그러나 커널의 기본 일관성 할당 함수인 `dma_alloc_coherent()`는 **최소 페이지 단위(4KB / 4096바이트)**로만 메모리를 할당할 수 있습니다. 만약 64바이트 디스크립터 하나를 할당하기 위해 4KB 페이지 전체를 소모한다면:
1. 메모리의 98.4%(4032바이트)가 버려지는 극심한 내부 단편화가 발생합니다.
2. 시스템의 연속 물리 메모리 풀(CMA / ZONE_DMA32)이 수 분 만에 고갈되어 드라이버 초기화가 실패합니다.

리눅스 커널은 이를 해결하기 위해 **DMA 전용 슬랩 할당자인 `dma_pool` (`mm/dmapool.c`, `include/linux/dmapool.h`)**을 제공합니다:
- **일관성 페이지 슬라이싱(Coherent Page Slicing)**: `dma_alloc_coherent()`로 4KB 물리 연속 페이지를 미리 할당받은 뒤, 지정된 블록 크기(`block_size`)와 정렬 경계(`align`)에 맞춰 수십~수백 개의 소형 청크로 균등하게 분할합니다.
- **인-페이지 프리리스트(In-page Freelist)**: 각 페이지 구조체(`struct dma_page`) 내부에 미사용 오프셋 목록을 유지하여 $O(1)$ 속도로 블록을 할당하고 반환합니다.
- **동적 페이지 확장 및 회수(Dynamic Grow & Reclaim)**:
  - 현재 페이지의 모든 블록이 소진되면 자동으로 새로운 4KB 일관성 페이지를 할당하여 풀을 확장합니다.
  - 임의의 페이지에서 모든 블록이 반환되어 사용 중인 블록이 0개가 되면(`in_use == 0`), 해당 페이지를 즉각 `dma_free_coherent()`를 통해 OS에 반환하여 불필요한 DMA 메모리 점유를 방지합니다.
- **정밀한 64비트 하드웨어 DMA 주소 계산**: $DMA_{\text{addr}} = DMA_{\text{base}} + \text{offset}$을 산출하여 디바이스 레지스터에 즉시 기록할 수 있도록 제공합니다.

본 문제에서는 리눅스 커널 `mm/dmapool.c`의 슬라이싱, 동적 페이지 확장/해제, 핸들 관리 및 하드웨어 주소 변환 엔진을 시뮬레이션합니다.

---

## 🏗️ 아키텍처 및 시스템 흐름도 (System Architecture)

```
                     [ Driver calls dma_pool_alloc() ]
                                    │
                         Page with free blocks?
                        ┌───────────┴───────────┐
                       Yes                      No
                        │                       │
                        │                       ▼
                        │             [ Allocate new Page ]
                        │             dma_alloc_coherent()
                        │             Slice page by block_size & align
                        │             pages_allocated_count++
                        ▼                       │
           ┌────────────────────────────────────┘
           ▼
     [ Pop free offset from page.free_offsets ]
     page.in_use++
     dma_addr = page.dma_base + offset
     allocations[handle_id] = (page_id, offset, dma_addr)
     Return SUCCESS with dma_addr (Hex)

─────────────────────────────────────────────────────────────────────────────
                     [ Driver calls dma_pool_free() ]
                                    │
                         Handle found in active?
                        ┌───────────┴───────────┐
                       Yes                      No
                        │                       │
                        ▼                       ▼
     [ Push offset back to free_offsets ]  [ EINVAL_HANDLE_NOT_FOUND ]
     page.in_use--
     Is page.in_use == 0 && len(pages) > 1?
      ┌─────────────────┴─────────────────┐
     Yes                                  No
      │                                   │
      ▼                                   ▼
 [ Free Coherent Page to OS ]     Keep page in pool
   dma_free_coherent()
   pages_freed_count++
   coherent_page_freed = true
```

---

## 🔢 수학적 공식 및 판정 기준 (Mathematical Formulations)

### 1. 페이지 내 블록 오프셋 정렬 (Aligned Block Offsets)
페이지 크기 $S_{\text{page}}$, 블록 크기 $S_{\text{block}}$, 정렬 기준 $A_{\text{align}}$에 대해:
유효 오프셋 $O$는 다음을 만족하며 순차 생성됩니다:
$$O \equiv 0 \pmod{A_{\text{align}}} \quad \land \quad O + S_{\text{block}} \le S_{\text{page}}$$

### 2. 하드웨어 물리 DMA 주소 계산 (Hardware DMA Address)
페이지의 물리 DMA 기저 주소를 $DMA_{\text{base}}$라 할 때:
$$DMA_{\text{addr}} = DMA_{\text{base}} + O$$

### 3. 절감된 DMA 메모리 양 (Memory Saved Accounting)
단일 디스크립터마다 4KB 페이지를 낭비하지 않고 `dma_pool`로 절약한 총 메모리 바이트 수는:
$$M_{\text{saved}} = (N_{\text{allocs}} \times S_{\text{page}}) - (N_{\text{pages\_allocated}} \times S_{\text{page}})$$

---

## 📥 입력 형식 (Input Specification)

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "config": {
    "name": "nvme_sqe_pool",
    "block_size": 64,
    "align": 64,
    "page_size": 256,
    "base_dma_start": 536870912
  },
  "trace": [
    {"op": "DMA_POOL_ALLOC", "handle_id": "SQ0"},
    {"op": "DMA_POOL_ALLOC", "handle_id": "SQ1"},
    {"op": "DMA_POOL_FREE", "handle_id": "SQ0"},
    {"op": "GET_POOL_INFO"}
  ]
}
```

### 지원 명령어 (Supported Operations):
1. `DMA_POOL_ALLOC`:
   - 파라미터: `handle_id` (str)
   - 블록을 할당하고 물리 DMA 주소(16진수 문자열 `0x...`)와 소속 페이지 ID를 반환합니다.
2. `DMA_POOL_FREE`:
   - 파라미터: `handle_id` (str)
   - 블록을 반환하고, 페이지가 비었을 경우 OS로의 페이지 해제 여부(`coherent_page_freed`)를 반환합니다.
3. `GET_POOL_INFO`:
   - 현재 활성 페이지 수, 총 할당/해제 횟수, 활성 블록 수 등을 조회합니다.

---

## 📤 출력 형식 (Output Specification)

표준 출력(stdout)으로 공백이 없는 콤팩트 JSON 문자열을 단일 행으로 출력합니다:
```json
{"events":[{"op":"DMA_POOL_ALLOC","handle_id":"SQ0","status":"SUCCESS","page_id":0,"offset":0,"dma_addr":"0x20000000","new_page_allocated":true,"page_in_use":1,"page_remaining":3}],"summary":{"total_allocs":1,"total_frees":0,"pages_allocated_count":1,"pages_freed_count":0,"active_pages":1,"active_allocations":1,"memory_saved_bytes":0}}
```

---

## 💡 제약 조건 (Constraints)
- 모든 시뮬레이션 연산은 단일 스레드 결정론적으로 처리됩니다.
- DMA 주소(`dma_addr`)는 소문자 16진수 문자열(`hex()`, 예: `"0x10000040"`)로 출력됩니다.
- 페이지 내 빈 오프셋들은 항상 선입선출(FIFO) 또는 오름차순 순서로 재활용됩니다.
