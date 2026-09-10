# Theory #439: 리눅스 커널 메모리 관리: mm/page_alloc.c 고차 Per-CPU 페이지 세트(PCP) 및 멀티코어 락 경합 완화 이론

## 1. 전역 zone->lock 경합의 물리학적 한계와 캐시라인 바운싱

대규모 멀티소켓 NUMA 서버(예: AMD EPYC 128코어, Intel Xeon 4소켓 224코어)에서 메인보드의 물리 메모리는 여러 개의 `struct zone`으로 추상화됩니다.
기존 리눅스 버디 할당자(Buddy System)의 핵심 불변식(Invariant)은 각 존의 프리 리스트(`free_area[order]`)를 수정할 때마다 반드시 해당 존의 전역 스핀락인 `zone->lock`을 획득해야 한다는 점입니다.

```
       [ Core 0 ]     [ Core 1 ]     [ Core 2 ] ... [ Core 127 ]
           │              │              │              │
           └──────────────┼──────────────┼──────────────┘
                          │ (Atomic CAS Contention)
                          ▼
                 [ zone->lock Spinlock ]
                          │
                          ▼
            [ free_area[0..MAX_ORDER] ]
```

### (1) 캐시라인 바운싱(Cacheline Bouncing)의 파괴적 비용
`zone->lock`을 획득하기 위해 실행되는 `spin_lock()`(내부적으로 `lock cmpxchg` 또는 `qspinlock` 아토믹 연산)은 MESI/MOESI 캐시 일관성 프로토콜 상에서 해당 스핀락 캐시라인을 독점(Modified) 상태로 가져와야 합니다.
수십 개의 코어가 동시에 메모리를 할당하려 할 때:
1. **인터커넥트 포화**: UPI/Infinity Fabric 버스 상에 `Read-For-Ownership (RFO)` 브로드캐스트가 폭주합니다.
2. **지연 시간 폭증**: 단일 메모리 할당의 지연 시간이 통상 30ns에서 10,000ns(10µs) 이상으로 300배 이상 폭증합니다.

---

## 2. Order-0 PCP의 역사적 성과와 고차(High-Order) 할당의 새로운 병목

1990년대 후반 도입된 **Per-CPU Pages (`struct per_cpu_pages`)**는 각 CPU 코어마다 전용 4KB 페이지 풀을 부여하여 단일 페이지 할당을 100% 락리스(Lockless)로 처리하는 쾌거를 이루었습니다.

그러나 2010년대 후반 클라우드 및 초고속 네트워킹의 급격한 발전으로 인해 새로운 양상이 나타났습니다:
1. **네트워크 점보 프레임 (Jumbo Frames)**: 100GbE NIC 수신 드라이버(`mlx5`, `ice`)는 9000바이트 MTU를 수용하기 위해 skb 버퍼로 최소 Order-1(8KB) 또는 Order-2(16KB) 물리 연속 페이지를 지속적으로 할당받습니다.
2. **복합 페이지 및 폴리오 (Compound Pages & Folios)**: 고성능 NVMe direct I/O 및 대규모 데이터베이스(PostgreSQL, Redis)의 파일 페이지 캐시는 효율적인 I/O 병합을 위해 Order-1~Order-3 폴리오를 대량 사용합니다.
3. **SLUB 슬랩 할당자**: 고빈도 커널 객체(예: `struct kmem_cache_node`, `sk_buff`)의 슬랩 페이지는 단편화를 줄이기 위해 Order-1이나 Order-2 페이지를 기본 슬랩 크기로 채택합니다.

결과적으로 시스템 전체 메모리 할당 중 30~50%를 차지하는 고차 할당이 기존 Order-0 PCP를 완전히 우회하여 전역 `zone->lock`에 직접 충돌하는 역설적인 상황이 발생했습니다.

---

## 3. Mel Gorman의 고차 PCP (Linux 5.14+) 아키텍처

리눅스 커널 5.14에서 Mel Gorman은 `struct per_cpu_pages`의 내부 구조를 다차원 배열로 개편하여 `PAGE_ALLOC_COSTLY_ORDER` (Order-3)까지의 고차 페이지를 코어별로 직접 캐싱하도록 혁신했습니다.

```
struct per_cpu_pages {
    int count;             /* 코어에 캐싱된 총 블록 수 */
    int high;              /* 상한선 (워터마크) */
    int batch;             /* 리필 / 드레인 배치 단위 */
    ...
    struct list_head lists[PAGE_ALLOC_COSTLY_ORDER + 1];
};
```

### (1) 수학적 락 상환 모델 (Lock Amortization)
요청 빈도가 높은 Order $k$ 할당에서 배치 크기가 $B = \text{batch}$일 때, $N$회의 연속 메모리 할당이 발생할 경우 `zone->lock` 획득 횟수 $L$은 다음과 같이 획기적으로 줄어듭니다:

$$L_{\text{legacy}} = N \quad \Longrightarrow \quad L_{\text{high-order-pcp}} = \left\lceil \frac{N}{B} \right\rceil$$

만약 $B = 4$ 또는 $B = 8$이라면 전역 존 락 획득 횟수와 캐시라인 바운싱이 **75%~87.5% 즉각 소멸**합니다.

### (2) LIFO (Last-In-First-Out)와 CPU 캐시 핫니스(Cache Warmth)
PCP 리스트는 블록을 반환할 때 리스트의 맨 앞에 추가하고, 할당할 때도 맨 앞의 블록을 꺼냅니다.
이 LIFO 정책의 핵심 이유는 **하드웨어 L1/L2 CPU 캐시 보존**입니다:
- 방금 전 동일 코어에서 해제된 메모리는 CPU의 L1/L2/L3 캐시에 데이터가 여전히 살아있습니다 (Cache Warm).
- 직후 발생하는 할당 요청에 동일 메모리 주소를 즉각 재할당함으로써 메모리 쓰기 시 캐시 미스를 0으로 억제하고 메모리 컨트롤러 DRAM 버스 대역폭 소모를 최소화합니다.

### (3) 하이 워터마크(`high`)와 일괄 드레인 (`free_pcppages_bulk`)
만약 코어별 PCP가 무한정 메모리를 보관한다면, 특정 코어가 대량의 메모리를 할당했다가 해제한 뒤 유휴 상태에 들어갈 때 시스템의 다른 코어가 사용 가능한 메모리가 고갈되어 불필요한 직접 재할당(Direct Reclaim)이나 OOM이 발생할 수 있습니다.
이를 방지하기 위해 `count >= high` 조건이 충족되면 자동으로 `batch`개의 블록을 일괄 인출하여 1회의 `zone->lock` 점유 하에 전역 버디 시스템의 `free_area`로 안전하게 반환합니다.
