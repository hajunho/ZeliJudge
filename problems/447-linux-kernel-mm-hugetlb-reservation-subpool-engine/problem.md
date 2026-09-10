# 문제 447: 리눅스 커널 메모리 관리 — HugeTLB 사전 예약(`resv_map`) 및 서브풀 쿼터 회계 엔진 (`mm/hugetlb.c`)

## 1. 개요 및 배경

엔터프라이즈 데이터베이스(Oracle RDBMS SGA, PostgreSQL `huge_pages=on`, SAP HANA) 및 가상화 하이퍼바이저(KVM 2MB/1GB HugePage 백킹)는 메모리 접근 시 TLB 미스 오버헤드를 줄이기 위해 **HugeTLB** 서브시스템을 광범위하게 활용합니다.

그러나 일반적인 4KB 메모리 매핑과 달리, HugeTLB는 메모리 공간이 사전에 고갈되었을 때 런타임에 디스크 스왑(Swap)으로 폴백할 수 없습니다. 따라서 사전에 충분한 물리 거대 페이지가 확보되지 않은 상태에서 프로세스가 페이지 폴트를 일으키면 커널은 해당 프로세스에 **`SIGBUS` (Bus Error)** 시그널을 강제 전송하여 프로세스를 비정상 사살(Kill)합니다.

```
[일반 4KB 페이징 vs HugeTLB 2MB 페이징의 런타임 고갈 차이]:
4KB Anonymous:  메모리 부족 시 ──> kswapd / LRU 회수 / Swap 장치로 회피 (생존)
HugeTLB (2MB):  물리 페이지 부족 시 ──> 스왑 불가! ──> 프로세스 즉각 SIGBUS Crash!
```

이와 같은 런타임 `SIGBUS` 참사를 원천 차단하기 위해, 리눅스 커널은 `mm/hugetlb.c`에 **사전 예약(Reservation) 및 서브풀(Subpool) 회계 메커니즘**을 구현하였습니다.
1. **`mmap(MAP_HUGETLB)` 호출 시점**: 커널은 실제 물리 메모리를 즉시 할당하지 않더라도, 향후 발생할 페이지 폴트가 100% 성공할 수 있도록 필요한 페이지 수만큼 전역 풀 및 서브풀에서 **사전 예약(`resv_map`)**을 걸어둡니다.
2. **페이지 폴트 시점**: 예약된 범위에 대한 접근인 경우, 다른 프로세스가 가로채지 못하도록 보호된 예약 카운트를 차감하고 물리 페이지를 즉각 매핑하여 **`SIGBUS`를 영구 차단**합니다.
3. **서브풀(`subpool`) 쿼터 제어**: 다중 테넌트 환경에서 특정 hugetlbfs 마운트 지점이 전역 풀을 독점하지 못하도록 `max_pages` 한도를 엄격히 집행합니다.

---

## 2. 핵심 메커니즘 및 상세 스펙

본 문제에서는 리눅스 커널 `mm/hugetlb.c`의 예약 맵(`struct resv_map`), 서브풀(`struct hugepage_subpool`), 풀 리사이징(`hugetlb_sysctl_handler`) 로직을 모사하는 시뮬레이션 엔진을 구현합니다.

### 1) 전역 풀 및 서브풀 상태 불변식
- `total_pages`: 시스템 전체에 프로비저닝된 총 거대 페이지 수.
- `free_pages`: 현재 어떤 페이지 테이블에도 매핑되지 않은 유휴 물리 거대 페이지 수.
- `resv_pages`: 시스템 전체에서 예약되었으나 아직 물리 페이지로 소비(Commit)되지 않은 총 예약 페이지 수.
- **예약 보증 불변식 (Reservation Invariant)**:
  $$\text{free\_pages} \ge \text{resv_pages}$$
  $$\text{unresv\_free} = \text{free\_pages} - \text{resv\_pages}$$
  모든 기등록된 예약은 향후 페이지 폴트 시 100% 물리 페이지를 배정받을 수 있어야 합니다.

### 2) VMA 생성 (`CREATE_VMA`)
- `vma_id`: 고유 문자열 식별자
- `subpool_id`: 소속 서브풀 ID (지정되지 않으면 `"default"`, 제한 없음 `max_pages = -1`)
- 초기 상태에서 VMA는 빈 예약 맵(`resv_map`)과 빈 할당 세트(`allocated_pages`)를 가집니다.

### 3) 페이지 사전 예약 (`RESERVE_PAGES`)
- `vma_id`, `start`, `end`: 대상 거대 페이지 인덱스 구간 `[start, end)`.
- **필요 예약 수량 계산**:
  $$\text{needed} = (\text{end} - \text{start}) - \text{existing\_resv} - \text{already\_allocated}$$
  (이미 해당 VMA에 예약되어 있거나 물리 할당된 페이지는 중복 예약하지 않음)
- **용량 검증**:
  1. 서브풀 쿼터: `subpool.max_pages != -1`인 경우,
     $$\text{subpool.used\_pages} + \text{subpool.rsv\_pages} + \text{needed} \le \text{subpool.max\_pages}$$
     위반 시: `{"status": "ENOMEM", "reason": "SUBPOOL_QUOTA_EXCEEDED", "needed": needed}`.
  2. 전역 풀 용량:
     $$\text{unresv\_free} \ge \text{needed}$$
     위반 시: `{"status": "ENOMEM", "reason": "GLOBAL_POOL_EXHAUSTED", "needed": needed}`.
- **예약 커밋**:
  - `subpool.rsv_pages += needed`
  - `global.resv_pages += needed`
  - VMA의 `resv_map`에 구간 병합(인접 및 중복 구간 Coalescing).
  - 반환: `{"status": "RESERVED", "vma_id": vma_id, "start": start, "end": end, "reserved_pages": needed}`.

### 4) 페이지 폴트 (`PAGE_FAULT`)
- `vma_id`, `page_idx`
- 이미 물리 페이지가 할당된 경우: `{"status": "ALREADY_PRESENT", "vma_id": vma_id, "page_idx": page_idx}`.
- **Case A: 예약 맵에 존재하는 경우 (`from_reservation = true`)**:
  - `resv_map`에서 `page_idx` 소비(해당 구간 축소 또는 분할).
  - `subpool.rsv_pages -= 1`, `subpool.used_pages += 1`
  - `global.resv_pages -= 1`, `global.free_pages -= 1`
  - 반환: `{"status": "FAULT_SUCCESS", "vma_id": vma_id, "page_idx": page_idx, "from_reservation": true}`.
- **Case B: 예약 맵에 없는 경우 (`from_reservation = false`)**:
  - 미예약 페이지에 대한 폴트이므로 비예약 유휴 풀에서 충당해야 함.
  - 서브풀 한도 초과 시: `sigbus_count += 1`, `{"status": "SIGBUS", "vma_id": vma_id, "page_idx": page_idx, "reason": "SUBPOOL_QUOTA_EXCEEDED"}`.
  - 전역 비예약 유휴 페이지 부족(`unresv_free < 1`) 시: `sigbus_count += 1`, `{"status": "SIGBUS", "vma_id": vma_id, "page_idx": page_idx, "reason": "NO_UNRESERVED_HUGEPAGE"}`.
  - 충당 가능한 경우:
    - `subpool.used_pages += 1`, `global.free_pages -= 1`
    - 반환: `{"status": "FAULT_SUCCESS", "vma_id": vma_id, "page_idx": page_idx, "from_reservation": false}`.

### 5) 페이지 매핑 해제 / 홀 펀칭 (`UNMAP_PAGES`)
- `vma_id`, `start`, `end`: 해제할 범위 `[start, end)`.
- 범위 내 물리 할당된 페이지:
  - VMA 할당 세트에서 제거, `subpool.used_pages -= 1`, `global.free_pages += 1`.
- 범위 내 미소비된 예약:
  - `resv_map`에서 제거, `freed_resv`만큼 `subpool.rsv_pages -= freed_resv`, `global.resv_pages -= freed_resv`.
- 반환: `{"status": "UNMAPPED", "vma_id": vma_id, "start": start, "end": end, "freed_physical": freed_phys, "freed_resv": freed_resv}`.

### 6) 동적 풀 리사이징 (`RESIZE_POOL`)
- 관리자가 `/proc/sys/vm/nr_hugepages`에 새로운 `new_total`을 기록하는 동작.
- 축소 제한 검증:
  $$\text{min\_allowable} = (\text{total\_pages} - \text{free\_pages}) + \text{resv\_pages}$$
  이미 할당되었거나 예약된 페이지는 축소할 수 없음!
  - `new_total < min_allowable`인 경우:
    반환: `{"status": "EBUSY", "min_allowable": min_allowable, "attempted": new_total}`.
  - 합법적인 경우:
    - $\Delta = \text{new\_total} - \text{total\_pages}$
    - `total_pages = new_total`, `free_pages += delta`
    - 반환: `{"status": "RESIZED", "total_pages": new_total, "free_pages": free_pages}`.

### 7) 통계 조회 (`QUERY_STATS`)
- 현재 전역 풀 및 각 서브풀(알파벳 오름차순 정렬) 상태와 누적 `sigbus_count`를 반환합니다.

---

## 3. 입력 및 출력 형식

### 입력 포맷 (표준 입력 JSON)
```json
{
  "config": {
    "total_pages": 50,
    "subpools": [
      {"id": "db_pool", "max_pages": 40}
    ]
  },
  "operations": [
    {"op": "CREATE_VMA", "vma_id": "vma_1", "subpool_id": "db_pool"},
    {"op": "RESERVE_PAGES", "vma_id": "vma_1", "start": 0, "end": 10},
    {"op": "PAGE_FAULT", "vma_id": "vma_1", "page_idx": 3},
    {"op": "UNMAP_PAGES", "vma_id": "vma_1", "start": 0, "end": 5},
    {"op": "RESIZE_POOL", "new_total": 60},
    {"op": "QUERY_STATS"}
  ]
}
```

### 출력 포맷 (표준 출력 단일 라인 JSON)
```json
{"results":[...]}
```
모든 키와 값은 공백 없는 압축 JSON(`separators=(',', ':')`) 형식으로 출력합니다.
