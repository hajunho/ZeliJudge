# Linux Kernel Network Page Pool 심층 아키텍처 및 고성능 무복사 메모리 관리 분석

## 1. 개발 배경과 문제 의식

현대 100GbE 및 400GbE 네트워크 환경에서 64바이트 최소 크기 패킷이 쏟아져 들어올 때, 초당 처리해야 할 패킷 수(PPS: Packets Per Second)는 약 **1억 4,880만 PPS**에 달합니다. 이는 패킷 1개당 CPU가 소모할 수 있는 처리 시간이 약 **6.72 나노초(약 20~30 CPU 사이클)**에 불과함을 의미합니다.

전통적인 리눅스 네트워크 스택에서 NIC 드라이버가 패킷 수신용 버퍼를 준비할 때:
1. `alloc_pages_node()`를 호출하여 버디 할당자의 존 스핀락(`zone->lock`)과 프리리스트를 탐색 (약 200~300 사이클 소모).
2. IOMMU(가상화 입출력 메모리 관리 유닛) 매핑을 위해 `dma_map_page()`를 호출하여 하드웨어 IOTLB 갱신 및 플러시 발생 (약 500~1,000 사이클 소모).

결과적으로 메모리 할당과 DMA 매핑에만 수천 사이클이 허비되어, 패킷 페이로드를 처리하기도 전에 하드웨어 수신 링 버퍼에 패킷 드롭(Rx Missed Errors)이 폭증하게 됩니다.

---

## 2. 페이지 풀(Page Pool) 아키텍처의 혁신

리눅스 커널 4.18에 도입되고 5.x~6.x에서 완성된 `net/core/page_pool.c`는 다음과 같은 설계 철학으로 이 병목을 완전히 제거합니다:

```c
struct page_pool {
    struct page_pool_params p;
    struct delayed_work release_dw;
    struct ptr_ring ring;           /* 원격 반환용 다중 생산자 FIFO 링 */
    struct page_pool_alloc_cache alloc; /* 동일 코어 NAPI 전용 LIFO 캐시 */
};
```

### 2.1 락 없는 고속 Per-CPU 할당 캐시 (`alloc_cache`)
- NAPI 소프트웨어 인터럽트는 동일 CPU 코어에서 단일 스레드 형태로 폴링 루프(`napi_poll`)를 실행합니다.
- 따라서 `alloc_cache`에 접근할 때는 상호 배제 락(Spinlock)이나 원자적 연산(`atomic_t`)이 일절 필요 없습니다.
- 단순히 배열 인덱스만 조작하여 L1 데이터 캐시에 상주하는 포인터를 팝(Pop)하므로 단 **10~15 CPU 사이클** 만에 할당이 완료됩니다.

### 2.2 영구 DMA 매핑 유지 (Persistent DMA Mapping)
- 페이지 풀에서 관리되는 페이지는 최초 할당 시 1회만 `dma_map_page()`를 거칩니다.
- 패킷이 드라이버나 상위 스택에서 해제되어 풀로 반환되어도 **DMA 매핑을 해제(Unmap)하지 않고 유지**합니다.
- NIC 드라이버는 केवल 캐시 무효화/동기화(`dma_sync_single_for_cpu`)만을 수행하여 DMA 오버헤드를 99% 이상 절감합니다.

### 2.3 포인터 링 버퍼 (`ptr_ring`)를 통한 크로스 코어 재활용
- 수신된 패킷(skb)이 다른 CPU 코어의 애플리케이션으로 전달되어 소켓 버퍼에서 해제되는 경우, 리모트 코어는 락리스/최소 스핀락 구조의 `ptr_ring`에 페이지를 반납합니다.
- 로컬 NAPI 코어는 자신의 `alloc_cache`가 비었을 때만 `ptr_ring`에서 배치 단위(`refill_batch_size`)로 페이지를 긁어오므로 락 경합 빈도를 획기적으로 낮춥니다.

---

## 3. 실무 드라이버 및 XDP 최적화 전략

1. **XDP_REDIRECT 및 AF_XDP**:
   - 커널 네트워크 스택을 우회하는 초고속 패킷 처리 경로에서 페이지 풀은 드라이버 메모리 재활용의 핵심 기반을 제공합니다.
2. **페이지 조각화(Page Fragment Allocator)**:
   - 4KB 페이지 1장으로 1.5KB MTU 패킷 2개를 나누어 수용하기 위해 바이어스 레퍼런스 카운팅(`page_pool_alloc_frag`)을 지원합니다.
3. **메모리 압박 시 우아한 성능 저하(Graceful Degradation)**:
   - 풀 링 버퍼가 포화되면 초과 페이지를 시스템 버디 할당자로 즉시 언맵하여 방출함으로써 시스템 전반의 OOM(Out of Memory) 위험을 방지합니다.
