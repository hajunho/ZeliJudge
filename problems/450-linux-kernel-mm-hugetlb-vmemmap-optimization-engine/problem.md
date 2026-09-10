# 문제 450: 리눅스 커널 메모리 관리 — HugeTLB Vmemmap 최적화(HVO) 및 테일 페이지 재매핑 회계 엔진 (`mm/hugetlb_vmemmap.c`)

## 1. 개요 및 배경

엔터프라이즈 하이퍼바이저(KVM) 및 초대규모 클라우드 데이터센터 서버(테라바이트 단위의 물리 RAM 장착)에서는 가상화 및 고성능 DB(Oracle, SAP HANA)를 위해 대량의 거대 페이지(2MB HugePage 및 1GB Gigantic HugePage)를 상시 프로비저닝합니다.

### 1) 구조체 페이지(struct page) 메타데이터의 막대한 메모리 낭비
리눅스 커널의 물리 메모리 모델(`SPARSEMEM_VMEMMAP`)에서 커널은 시스템의 모든 4KB 물리 프레임마다 정확히 하나의 64바이트 `struct page` 메타데이터를 선형 가상 메모리 공간(`vmemmap`)에 유지합니다.
- **2MB 거대 페이지**: 512개의 4KB 하위 페이지로 구성되며, 메타데이터 공간으로 $512 \times 64\text{ B} = 32\text{ KB}$ (정확히 8개의 4KB vmemmap 페이지)를 소모합니다.
- **1GB 기가 페이지**: 262,144개의 4KB 하위 페이지로 구성되며, 메타데이터 공간으로 $262,144 \times 64\text{ B} = 16\text{ MB}$ (정확히 4,096개의 4KB vmemmap 페이지)를 소모합니다.

만약 1TB의 RAM을 2MB 거대 페이지로 프로비저닝하면, 오직 `struct page` 메타데이터를 저장하는 데만 **16GB의 귀중한 물리 RAM이 영구 소모**됩니다!

```
[전통적인 2MB HugePage vmemmap (8개 물리 4KB 페이지 점유)]:
vmemmap Pages:   [Page 0]    [Page 1]    [Page 2]    [Page 3]    [Page 4]    [Page 5]    [Page 6]    [Page 7]
                  (Head)      (Tail 1)    (Tail 2)    (Tail 3)    (Tail 4)    (Tail 5)    (Tail 6)    (Tail 7)
물리 RAM 점유:     4KB         4KB         4KB         4KB         4KB         4KB         4KB         4KB  = 총 32KB

[HVO 최적화 적용 후: 7개 물리 페이지 버디 할당자로 즉시 반환 (87.5% 절감!)]:
vmemmap Pages:   [Page 0]    [Page 1]    [Page 2]    [Page 3]    [Page 4]    [Page 5]    [Page 6]    [Page 7]
                  (Head: RW)  (Tail 1: RO)
                      │           ▲
                      │           └───────────┴───────────┴───────────┴───────────┴───────────┘
                      │                 (Tail 2~7의 PTE가 물리 Page 1을 공유 참조!)
물리 RAM 점유:     4KB         4KB (공유)  ==> 7개 물리 4KB 페이지(28KB) 버디 시스템으로 즉각 반환!
```

리눅스 커널 5.14에 머지된 **HugeTLB Vmemmap Optimization (HVO / `mm/hugetlb_vmemmap.c`)**은 거대 페이지 내의 모든 테일(Tail) `struct page`들이 사실상 동일한 메타데이터(헤드 페이지를 가리키는 `compound_head`)만을 보유한다는 점에 착안하였습니다.
커널은 테일 vmemmap 페이지들의 페이지 테이블 엔트리(PTE)를 단 하나의 물리 테일 페이지로 일괄 재매핑하고, 불필요해진 **7개(1GB의 경우 4,095개)의 물리 4KB 페이지를 버디 할당자로 즉각 반환**합니다.

---

## 2. 핵심 메커니즘 및 상세 스펙

본 문제에서는 리눅스 커널 `mm/hugetlb_vmemmap.c`의 HVO 할당, 테일 페이지 읽기 전용(RO) 보호, HugePage 해체(Dissolve) 시 vmemmap 복원 및 버디 메모리 고갈 에러 로직을 모델링하는 시뮬레이션 엔진을 구현합니다.

### 1) 시스템 설정 (`config`)
- `page_size`: 기본 4096 (4KB)
- `struct_page_size`: 기본 64 (bytes)
- `hvo_enabled`: boolean (HVO 기능 활성화 여부, 기본 true)
- `buddy_free_pages`: 초기 버디 할당자 유휴 4KB 페이지 수

### 2) 거대 페이지 할당 (`ALLOC_HUGEPAGE`)
- `hugepage_id`: 고유 문자열 ID
- `page_type`: `"2MB"` 또는 `"1GB"`
- **계산 규칙**:
  - `page_type == "2MB"`:
    - 하위 페이지 수: 512개
    - 총 vmemmap 페이지 수: $(512 \times 64) / 4096 = 8$ 페이지
    - `hvo_enabled == true`:
      - 7개의 테일 물리 페이지가 회수되어 버디 할당자로 반환: `buddy_free_pages += 7`.
      - `freed_vmemmap_pages = 7`.
      - `net_saved_bytes = 7 * 4096 = 28,672` 바이트.
    - `hvo_enabled == false`: `freed_vmemmap_pages = 0`.
  - `page_type == "1GB"`:
    - 하위 페이지 수: 262,144개
    - 총 vmemmap 페이지 수: $(262,144 \times 64) / 4096 = 4096$ 페이지
    - `hvo_enabled == true`:
      - 4095개의 테일 물리 페이지가 회수되어 버디 할당자로 반환: `buddy_free_pages += 4095`.
      - `freed_vmemmap_pages = 4095`.
      - `net_saved_bytes = 4095 * 4096 = 16,773,120` 바이트.
    - `hvo_enabled == false`: `freed_vmemmap_pages = 0`.
- 중복 ID 존재 시 `{"status": "ERROR_ALREADY_EXISTS", "hugepage_id": hugepage_id}`.
- 성공 시 `{"status": "ALLOCATED", "hugepage_id": hugepage_id, "page_type": page_type, "hvo_applied": hvo_enabled, "freed_vmemmap_pages": freed_vmemmap_pages, "net_saved_bytes": net_saved_bytes}`.

### 3) 거대 페이지 해체 (`DISSOLVE_HUGEPAGE`)
- 거대 페이지를 4KB 기본 페이지들로 쪼개어 반환하는 연산.
- 미존재 시 `{"status": "ERROR_NOT_FOUND", "hugepage_id": hugepage_id}`.
- **HVO 복원 역과정 (Vmemmap Reconstruction)**:
  - HVO가 적용된 경우, 해체하기 전에 회수했던 `freed_vmemmap_pages`만큼 버디 할당자로부터 새로운 4KB 물리 페이지들을 다시 할당받아 테일 페이지들을 1:1 독립 매핑으로 복원해야 합니다.
  - 만약 `buddy_free_pages < freed_vmemmap_pages`라면:
    - 버디 메모리 부족으로 vmemmap 복원 불가능! 해체 실패!
    - `dissolve_failures` 1 증가.
    - 반환: `{"status": "ENOMEM_RESTORE_VMEMMAP", "hugepage_id": hugepage_id, "needed_pages": freed_vmemmap_pages, "buddy_free_pages": buddy_free_pages}`.
  - 충분한 경우:
    - `buddy_free_pages -= freed_vmemmap_pages`.
    - 거대 페이지 정상 해체.
    - 반환: `{"status": "DISSOLVED", "hugepage_id": hugepage_id, "restored_vmemmap_pages": freed_vmemmap_pages}`.

### 4) 구조체 페이지 접근 검증 (`ACCESS_STRUCT_PAGE`)
- `hugepage_id`, `subpage_index`, `access_type` (`"READ"` 또는 `"WRITE"`)
- `subpage_index`의 유효 범위 초과 시 `{"status": "ERROR_INDEX_OUT_OF_BOUNDS", "subpage_index": subpage_index}`.
- `vmemmap_page_idx = (subpage_index * struct_page_size) // page_size`.
- **보안 및 무결성 불변식**:
  - `hvo_applied == true`인 경우:
    - `vmemmap_page_idx == 0` (헤드 페이지): 읽기/쓰기 모두 허용 (`ACCESS_SUCCESS`, `is_head_page = true`).
    - `vmemmap_page_idx >= 1` (공유 테일 페이지):
      - 여러 가상 페이지가 단 하나의 물리 테일 페이지를 공유 참조하므로, 커널은 이를 **읽기 전용(Read-Only)**으로 매핑합니다.
      - `access_type == "WRITE"`인 경우:
        커널 MMU 하드웨어 쓰기 보호 폴트 발생!
        반환: `{"status": "PAGE_FAULT_RO", "hugepage_id": hugepage_id, "vmemmap_page_idx": vmemmap_page_idx, "subpage_index": subpage_index}`.
      - `access_type == "READ"`인 경우:
        반환: `{"status": "READ_SUCCESS", "hugepage_id": hugepage_id, "is_shared_tail": true, "vmemmap_page_idx": vmemmap_page_idx}`.
  - `hvo_applied == false`인 경우:
    - 모든 vmemmap 페이지가 독립 물리 페이지이므로 읽기/쓰기 모두 정상 허용 (`ACCESS_SUCCESS`).

### 5) 통계 조회 (`QUERY_STATS`)
- `total_hugepages`: 현재 활성 거대 페이지 수.
- `total_saved_vmemmap_pages`: HVO로 절감된 총 4KB vmemmap 페이지 수.
- `total_saved_bytes`: 절감된 총 바이트 수 (`total_saved_vmemmap_pages * 4096`).
- `buddy_free_pages`: 현재 버디 할당자 유휴 페이지 수.
- `dissolve_failures`: vmemmap 복원 메모리 부족으로 실패한 해체 시도 횟수.

---

## 3. 입력 및 출력 형식

### 입력 포맷 (표준 입력 JSON)
```json
{
  "config": {
    "page_size": 4096,
    "struct_page_size": 64,
    "hvo_enabled": true,
    "buddy_free_pages": 100000
  },
  "operations": [
    {"op": "ALLOC_HUGEPAGE", "hugepage_id": "hp_1", "page_type": "2MB"},
    {"op": "ACCESS_STRUCT_PAGE", "hugepage_id": "hp_1", "subpage_index": 0, "access_type": "WRITE"},
    {"op": "ACCESS_STRUCT_PAGE", "hugepage_id": "hp_1", "subpage_index": 64, "access_type": "WRITE"},
    {"op": "DISSOLVE_HUGEPAGE", "hugepage_id": "hp_1"},
    {"op": "QUERY_STATS"}
  ]
}
```

### 출력 포맷 (표준 출력 단일 라인 JSON)
```json
{"results":[...]}
```
모든 키와 값은 공백 없는 압축 JSON(`separators=(',', ':')`) 형식으로 출력합니다.
