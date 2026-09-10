# 심층 시스템 이론: 리눅스 커널 HugeTLB 사전 예약(`resv_map`) 및 서브풀 회계 아키텍처 (`mm/hugetlb.c`)

## 1. HugePage와 전통적인 가상 메모리 관리의 근본적 차이

리눅스 커널의 가상 메모리 서브시스템(`mm/`)에서 일반 4KB 페이지(Anonymous Page)와 거대 페이지(HugeTLB Page, x86-64 기준 2MB PMD / 1GB PUD)는 물리적 메모리 고갈 상황에서 근본적으로 다른 동작 양상을 보입니다.

### 1) 4KB 페이징의 완충 장치: 디스크 스왑 및 LRU 축출
- 일반적인 4KB 익명 메모리는 물리 RAM이 부족할 때 `kswapd` 백그라운드 스캐너 또는 직접 회수(Direct Reclaim) 파이프라인을 통해 클린 파일 페이지 캐시를 폐기하거나, 더티 익명 페이지를 스왑(Swap) 파티션 또는 zswap/zram으로 압축 방출합니다.
- 따라서 일시적인 물리 메모리 압박이 발생해도 프로세스는 I/O 지연(Major Page Fault)만 겪을 뿐, 비정상 사살(Crash)을 당하지 않고 생존할 수 있습니다.

### 2) HugeTLB의 태생적 제약: 스왑 불가능성(Non-swapability)
- 반면 `hugetlbfs` 기반의 거대 페이지는 **커널에 의해 스왑 아웃되거나 일반 LRU 리스트에 들어갈 수 없습니다**.
- 2MB 단위의 연속된 물리 프레임을 온디맨드로 디스크에 연속 기입하고 스왑 맵을 관리하는 것은 엄청난 I/O 오버헤드와 물리 단편화를 유발하기 때문입니다.
- 만약 특정 데이터베이스 프로세스가 `mmap(MAP_HUGETLB)`을 통해 100GB의 가상 주소 공간을 열어두고, 런타임에 쓰기를 수행하다가 물리 HugePage 풀이 바닥난다면:
  - 커널은 페이지를 회수할 방법이 전혀 없으므로 프로세스에 즉시 **`SIGBUS` (Bus Error - Page not available)** 시그널을 전달합니다.
  - 미션 크리티컬한 데이터베이스 인스턴스(Oracle, SAP HANA, PostgreSQL)가 즉시 크래시하며 전사적인 서비스 장애가 발생합니다.

---

## 2. 리눅스 커널의 사전 예약 메커니즘 (`struct resv_map`)

이러한 런타임 `SIGBUS` 참사를 사전에 100% 방어하기 위해 리눅스 커널은 `mm/hugetlb.c`에서 **예약 맵(`resv_map`)**을 통한 2단계 회계(2-Phase Accounting)를 집행합니다.

```
mmap(MAP_HUGETLB)
      │
      ▼
hugetlb_reserve_pages()  ──(resv_pages += needed)──> [예약 확보 완료]
      │                                                     │
      │ (시간 경과 / 지연 할당)                               │ (SIGBUS 절대 미발생 보장!)
      ▼                                                     ▼
Page Fault (hugetlb_no_page) ──(from resv_map)────> Commit Reservation
                                                     resv_pages -= 1
                                                     free_pages -= 1
                                                     물리 2MB 프레임 매핑
```

### 1) 구조체 정의
커널 내부에서 예약 맵은 `struct resv_map` 구조체로 관리됩니다:
```c
struct resv_map {
    struct kref refs;
    spinlock_t lock;
    struct list_head regions;
    long adds_in_progress;
    struct list_head purge_list;
};

struct file_region {
    struct list_head link;
    long from;
    long to;
};
```
- `from`과 `to`는 거대 페이지 단위의 논리적 오프셋입니다 (예: 오프셋 0부터 20까지는 2MB 페이지 20개를 의미).
- 커널은 새로운 예약 구간이 들어올 때마다 기존 구간들과 병합(Coalescing)하여 리스트를 항상 **정렬되고 상호 중복되지 않는 최소 구간 집합**으로 유지합니다.

### 2) 예약 보증 불변식 (The Invariant)
전역 풀의 총 거대 페이지 수를 $T$, 유휴 페이지 수를 $F$, 예약된 페이지 수를 $R$이라 할 때, 커널은 항상 다음 불변식을 유지합니다:
$$F \ge R$$
$$U = F - R \quad (\text{Unreserved Free Pages})$$
- $U$는 아직 아무에게도 예약되지 않은 순수 유휴 페이지입니다.
- 새로운 예약 요청 $N$이 들어오면, 커널은 $U \ge N$을 검증합니다.
- 만약 $U < N$이라면 커널은 `mmap` 호출 시점에 즉각 `-ENOMEM`을 반환합니다.
- **핵심 의미**: 실패를 런타임 페이지 폴트 시점(`SIGBUS`)에서 사전에 `mmap` 시점(`-ENOMEM`)으로 당겨옴으로써, 애플리케이션이 안전하게 에러를 처리하거나 크기를 조절할 수 있도록 보장합니다.

---

## 3. 서브풀(Subpool) 계층과 멀티테넌트 쿼터 제어

클라우드 및 컨테이너 환경에서는 서로 다른 서비스가 동일한 노드의 HugeTLB 풀을 공유합니다. 특정 컨테이너가 거대 페이지를 모두 예약해버려 시스템 서비스가 굶어 죽는 사태를 방지하기 위해 `hugetlbfs` 마운트 옵션(`min_size`, `max_size`)을 통해 **서브풀(`struct hugepage_subpool`)**을 생성합니다.

```c
struct hugepage_subpool {
    spinlock_t lock;
    long count;
    long max_hpages;
    long used_hpages;
    long rsv_hpages;
    long min_hpages;
    struct hstate *hstate;
};
```

### 1) 서브풀 쿼터 회계 규칙
각 서브풀 $S$에 대해:
$$\text{committed}(S) = \text{used\_hpages}(S) + \text{rsv\_hpages}(S)$$
$$\text{committed}(S) \le \text{max\_hpages}(S)$$
- 어떤 VMA가 서브풀 $S$ 내에서 $N$개의 추가 예약을 시도할 때:
  $$\text{committed}(S) + N \le \text{max\_hpages}(S)$$
  조건과 전역 $U \ge N$ 조건을 **동시에** 만족해야만 예약이 승인됩니다.

---

## 4. 동적 풀 리사이징과 EBUSY 보호 메커니즘

관리자는 운영 중에 `/proc/sys/vm/nr_hugepages`에 새로운 숫자를 써서 HugeTLB 풀의 크기를 동적으로 늘리거나 줄일 수 있습니다.

### 1) 확장 (Expansion)
새로운 크기 $T_{\text{new}} > T_{\text{curr}}$인 경우:
$$\Delta = T_{\text{new}} - T_{\text{curr}}$$
커널은 버디 할당자(`alloc_contig_pages` 또는 `alloc_pages`)로부터 연속된 물리 블록을 확보하여 풀에 추가하고, 유휴 페이지 $F \leftarrow F + \Delta$로 즉각 확장합니다.

### 2) 축소 (Shrinkage) 및 EBUSY 방어
새로운 크기 $T_{\text{new}} < T_{\text{curr}}$인 경우, 커널은 무조건 풀을 줄이지 않습니다.
이미 프로세스에 물리 할당된 페이지($T - F$)와 향후 폴트를 위해 약속된 예약 페이지($R$)는 절대로 회수할 수 없습니다:
$$\text{min\_allowable} = (T - F) + R$$
- 만약 $T_{\text{new}} < \text{min\_allowable}$이라면 커널은 축소를 단호히 거절하고 `-EBUSY` 오류를 반환합니다.
- 이를 통해 메모리 관리자의 부주의한 sysctl 명령으로 인해 실행 중인 데이터베이스가 `SIGBUS` 크래시를 겪는 대형 장애를 원천 봉쇄합니다.

---

## 5. 요약 및 실무적 의미

리눅스 커널의 HugeTLB 사전 예약과 서브풀 회계 엔진은 **"스왑 불가능한 대용량 하드웨어 자원을 무중단 고가용성 환경에서 어떻게 안전하게 가상화하고 분배할 것인가?"**라는 시스템 아키텍처적 난제에 대한 가장 정교하고 완성도 높은 해답입니다.
