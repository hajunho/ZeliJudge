# Linux Kernel zsmalloc Compressed Memory Pool Allocator, zspage Fullness Groups & Memory Compaction 엔진

## 문제 설명

스마트폰(Android ZRAM) 및 고밀도 클라우드 서버(ZSWAP) 환경에서는 RAM 용량 한계를 극복하기 위해 자주 쓰이지 않는 익명 페이지(Anonymous Pages)를 압축(LZO, LZ4, ZSTD)하여 DRAM 상의 압축 풀에 보관합니다.

그러나 4KB 페이지를 압축했을 때 나오는 결과물의 크기는 데이터 엔트로피에 따라 수십 바이트에서 3.8KB까지 천차만별입니다:
- 표준 버디 할당자(Buddy Allocator)로 4KB 페이지를 매번 할당하면 극심한 **내부 단편화(Internal Fragmentation)**로 인해 압축의 이점이 사라집니다.
- 전통적인 슬랩 할당자(SLUB)는 물리 페이지 경계를 넘는 객체를 허용하지 않아 다양한 크기의 압축 데이터를 수납하기에 부적합합니다.

리눅스 커널은 이를 해결하기 위해 메모리 관리 서브시스템에 **zsmalloc (`mm/zsmalloc.c`)** 특화 슬랩 할당자를 도입했습니다:

1. **멀티페이지 할당 단위: `zspage`**:
   - 단일 물리 페이지의 한계를 넘어 최대 4개의 물리 페이지(`ZS_MAX_PAGES_PER_ZSPAGE`)를 하나로 체이닝하여 단일 할당 단위인 `zspage`를 구성합니다.
   - 각 크기 클래스(Size Class)는 낭비 공간이 12.5% 이하가 되도록 `pages_per_zspage`와 슬롯 수를 계산하여 내부 단편화를 극적으로 억제합니다.
2. **풀니스 그룹 (Fullness Groups)**:
   - 각 크기 클래스는 `zspage`의 슬롯 사용률에 따라 4개의 풀니스 리스트로 분류합니다:
     - `ZS_EMPTY` (0% 사용, OS로 즉각 반환 대기)
     - `ZS_ALMOST_EMPTY` (1% ~ 49% 사용)
     - `ZS_ALMOST_FULL` (50% ~ 99% 사용)
     - `ZS_FULL` (100% 포화)
   - 새로운 할당 요청 시: 가용 슬롯이 적게 남은 `ZS_ALMOST_FULL`을 최우선 선택하고, 그 다음 `ZS_ALMOST_EMPTY`를 탐색하며, 모두 없으면 새 `zspage`를 할당합니다.
3. **간접 핸들 (Indirect Handle)**:
   - 메모리 컴팩션(Compaction) 시 객체의 물리 위치가 바뀌므로, 사용자는 원시 포인터 대신 64비트 간접 핸들(`handle_id`)을 소유합니다.
4. **메모리 컴팩션 (`zs_compact`)**:
   - 사용률이 낮은 소스 `zspage`(`ZS_ALMOST_EMPTY`)에서 객체를 꺼내 타깃 `zspage`(`ZS_ALMOST_FULL`)의 빈 슬롯으로 이주(Migrate)시키고 간접 핸들을 갱신합니다.
   - 완전히 비워진 `zspage`의 물리 페이지를 OS 버디 할당자로 즉시 반환하여 외부 단편화를 해소합니다.

당신은 리눅스 커널 메모리 관리(MM) 엔지니어로서, **리눅스 커널 `mm/zsmalloc.c`, `include/linux/zsmalloc.h`에 명시된 zsmalloc 슬랩 할당, 풀니스 그룹 전이 및 메모리 컴팩션 엔진**을 구현해야 합니다.

```
+-------------------------------------------------------------------------+
|     Linux Kernel mm/zsmalloc.c Compressed Memory Pool Architecture      |
+-------------------------------------------------------------------------+
| [Size Classes: 256B, 512B, 1024B, 2048B, ...]                           |
|   - struct size_class { fullness_lists[4]; pages_per_zspage; }          |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| [zspage Structure (1 ~ 4 Chained Physical Pages)]                       |
|   - Slots: [Handle 1] [Handle 2] [FREE] [Handle 3]                      |
|   - Fullness: ZS_FULL <-> ZS_ALMOST_FULL <-> ZS_ALMOST_EMPTY            |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| [zs_compact: Two-Pointer Compaction & Handle Remapping]                 |
|   - Source (Almost Empty) ---> Move Object ---> Target (Almost Full)    |
|   - Emptied zspage Physical Pages Freed Back to OS Buddy Allocator      |
+-------------------------------------------------------------------------+
```

---

## 엔진 규격 및 수리적 모델링

### 1. 풀 초기화 (`INIT_POOL`)
- 입력: `pool_name` (문자열), `classes` (리스트: `[{"size": int, "pages_per_zspage": int}, ...]`)
- 기본 물리 페이지 크기: 4096 바이트 (`PAGE_SIZE = 4096`)
- 슬롯 수: $TotalSlots = (pages\_per\_zspage 	imes 4096) // size$

### 2. 압축 객체 할당 (`ZS_MALLOC`)
- 입력: `handle_id` (고유 문자열), `size` (바이트)
- 절차:
  1. $size \le class\_size$를 만족하는 가장 작은 크기 클래스 선택.
  2. 후보 `zspage` 선택:
     - 1순위: 해당 클래스의 `ZS_ALMOST_FULL` 큐의 첫 번째 zspage.
     - 2순위: 해당 클래스의 `ZS_ALMOST_EMPTY` 큐의 첫 번째 zspage.
     - 3순위: 모두 비어있으면 새 `zspage` 할당 (`total_pages_allocated += pages_per_zspage`).
  3. 첫 번째 빈 슬롯에 `handle_id` 배치, 풀니스 갱신 후 알맞은 풀니스 리스트로 이동.
  4. 전역 핸들 테이블에 `handle_id -> (class_size, zspage_id, slot_idx)` 매핑 등록.

### 3. 압축 객체 해제 (`ZS_FREE`)
- 입력: `handle_id`
- 절차:
  1. 핸들 테이블에서 `(class_size, zspage_id, slot_idx)` 조회.
  2. 해당 `zspage`의 슬롯을 `None`으로 비움.
  3. 풀니스 갱신:
     - 사용 슬롯이 0이 되면 (`ZS_EMPTY`): 풀니스 리스트에서 제거하고 해당 `zspage`가 점유하던 물리 페이지를 OS로 반환 (`total_pages_freed += pages_per_zspage`).
     - 잔여 슬롯이 있으면 변경된 풀니스 리스트로 이동.
  4. 핸들 테이블에서 제거.

### 4. 메모리 컴팩션 (`ZS_COMPACT`)
- 입력: `target_class` (선택적 크기 클래스, 미지정 시 전체 클래스 대상)
- 절차:
  - 각 대상 크기 클래스에 대해:
    - 소스 `zspage`는 `ZS_ALMOST_EMPTY` 중 사용 슬롯이 가장 적은 순으로 정렬.
    - 타깃 `zspage`는 `ZS_ALMOST_FULL` 중 빈 슬롯이 적은 순으로 정렬.
    - 소스의 할당된 슬롯들을 타깃의 빈 슬롯으로 차례로 이주시키고 핸들 테이블의 위치를 갱신.
    - 소스가 완전히 비워지면(`ZS_EMPTY`), 해당 물리 페이지를 OS로 반환.
  - 이주된 객체 수(`objects_migrated`) 및 회수된 물리 페이지 수(`pages_freed`) 반환.

### 5. 풀 상태 검사 (`INSPECT_POOL`)
- 활성 물리 페이지 수(`active_pages`), 총 저장 객체 수, 메모리 사용 효율(`memory_utilization`), 클래스별 풀니스 분포 및 누적 통계 반환.

---

## 입력 형식

표준 입력(stdin)으로 JSON 배열 형태의 명령어 목록이 주어집니다.

```json
[
  {
    "op": "INIT_POOL",
    "pool_name": "zram_pool_0",
    "classes": [{"size": 1024, "pages_per_zspage": 1}]
  },
  {"op": "ZS_MALLOC", "handle_id": "h1", "size": 800},
  {"op": "ZS_FREE", "handle_id": "h1"},
  {"op": "INSPECT_POOL"}
]
```

---

## 출력 형식

표준 출력(stdout)으로 각 명령어의 실행 결과를 담은 JSON 배열을 공백 없이 한 줄로 출력합니다.

```json
[{"op":"INIT_POOL","status":"OK","pool_name":"zram_pool_0"},{"op":"ZS_MALLOC","result":{"status":"ALLOCATED","handle_id":"h1","class_size":1024,"zspage_id":1,"slot_idx":0,"fullness":"ZS_ALMOST_EMPTY","is_new_zspage":true}},{"op":"ZS_FREE","result":{"status":"FREED","handle_id":"h1","zspage_id":1,"fullness":"RELEASED_TO_OS","pages_freed":1}},{"op":"INSPECT_POOL","result":{"pool_name":"zram_pool_0","active_pages":0,"total_objects":0,"memory_utilization":0.0,"class_stats":{"1024":{"zspages_count":0,"used_slots":0,"total_slots":0,"fullness":{"ALMOST_FULL":0,"ALMOST_EMPTY":0,"FULL":0,"EMPTY":0}}},"stats":{"total_pages_allocated":1,"total_pages_freed":1,"total_mallocs":1,"total_frees":1,"total_compactions":0,"total_objects_migrated":0}}}]
```

---

## 제약 사항

- 크기 클래스 수 $\le 32$
- 페이지 크기: 4096 바이트
- 명령어 수 $M \le 10,000$
- 시간 제한: 5.0초
- 메모리 제한: 512MB
