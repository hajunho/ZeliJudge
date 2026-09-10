# 문제 307: 리눅스 커널 SLUB 메모리 할당자: Fast/Slow Path, Hardened Freelist 및 부분 슬랩 관리 엔진 (Linux Kernel SLUB Allocator Engine)

## 문제 배경
리눅스 커널에서 작은 크기(수십~수백 바이트)의 메모리 객체를 할당할 때, 페이지 단위(4KB)의 버디 할당자(Buddy Allocator)를 직접 호출하는 것은 극심한 내부 단편화와 오버헤드를 유발합니다. 이를 해결하기 위해 커널은 동일 크기의 객체들을 단일 페이지에 배열 형태로 모아 관리하는 **슬랩 할당자(Slab Allocator)**를 사용합니다.

리눅스 커널 2.6.23부터는 기존 SLAB의 복잡한 큐 계층을 제거하고 메타데이터를 최소화한 **SLUB 할당자(`mm/slub.c`)**가 기본 할당자로 채택되었습니다. SLUB의 핵심 강점은 **Per-CPU 락리스 패스트 패스(Lockless Fast Path)**와 **NUMA 노드 슬로우 패스(Slow Path)**의 2단계 구조에 있습니다:

1. **패스트 패스 (`kmem_cache_cpu`)**:
   - 각 CPU 코어마다 전용 활성 슬랩 페이지(`c->page`)와 락이 필요 없는 단일 연결 프리리스트(`c->freelist`)를 둡니다.
   - 메모리 할당 요청 시 전역 락 없이 $O(1)$의 원자적 연산으로 객체를 즉시 반환합니다.
2. **슬로우 패스 (`__slab_alloc`)**:
   - 로컬 `c->freelist`가 고갈되면:
     1) **원격 해제 객체 수거 (`page_freelist`)**: 타 CPU가 활성 슬랩에 반환해 둔 프리리스트를 수거.
     2) **NUMA 부분 슬랩 획득 (`kmem_cache_node->partial`)**: 전역 락을 잡고 일부 여유 공간이 있는 슬랩 페이지를 획득.
     3) **버디 할당자 신규 할당 (`new_slab`)**: 버디 할당자로부터 새로운 4KB 페이지를 할당받아 포맷팅.
3. **보안 하드닝 (`CONFIG_SLAB_FREELIST_HARDENED`)**:
   - 힙 오버플로우나 Use-After-Free(UAF) 취약점으로 인한 프리리스트 포인터 덮어쓰기 공격을 무력화하기 위해, 프리리스트 포인터를 난수 쿠키 및 객체 주소와 XOR 연산하여 암호화합니다:
     $$\text{EncodedPtr} = \text{TargetPtr} \oplus \text{Cookie} \oplus \text{ObjectAddr}$$
   - 포인터 디코딩 시 무결성이 손상되었거나 유효하지 않은 주소일 경우 즉시 커널 패닉(`BUG_ON`)을 발생시켜 공격을 차단합니다.

본 문제에서는 리눅스 커널 `mm/slub.c`의 Fast/Slow Path 전환, Per-CPU 프리리스트 순환, 원격 CPU 해제, NUMA partial 리스트 관리 및 Hardened Freelist 무결성 검증을 시뮬레이션하는 SLUB 할당자 엔진을 구현해야 합니다.

---

## 시스템 동작 규칙 및 엔진 명세

### 1. 할당자 계층 구조
- **슬랩 캐시 (`kmem_cache`)**:
  - 고정 크기 `object_size`, 슬랩당 객체 수 `objects_per_slab`, 하드닝 쿠키 `hardened_cookie`를 관리합니다.
- **Per-CPU 슬랩 (`cpu_slabs[cpu]`)**:
  - 현재 CPU가 독점 점유 중인 활성 슬랩 `slab`과 로컬 프리리스트 `freelist`를 유지합니다.
- **NUMA 부분 리스트 (`node_partial`)**:
  - 활성 슬랩에서 해제되어 여유 슬롯이 남아 있는 비활성 슬랩들의 대기 큐입니다.

### 2. 메모리 할당 경로 (`ALLOC`)
`cpu` 코어에서 `alloc_id` 할당 요청이 들어오면:
1. **패스트 패스 (`FAST_PATH`)**:
   - `c->freelist`에 여유 객체가 있으면 즉시 첫 번째 객체를 pop하여 반환합니다. `slab->inuse`가 1 증가합니다.
2. **슬로우 패스 1단계 (`PAGE_FREELIST`)**:
   - `c->freelist`가 비어 있지만, 타 CPU에 의해 활성 슬랩에 반환된 객체들(`slab->page_freelist`)이 있다면:
   - 이를 로컬 `c->freelist`로 가져온 뒤 첫 객체를 반환합니다.
3. **슬로우 패스 2단계 (`NODE_PARTIAL`)**:
   - `node_partial` 대기 큐에 슬랩이 존재한다면:
   - 큐의 첫 번째 부분 슬랩을 꺼내 새로운 활성 슬랩으로 바인딩하고 첫 객체를 반환합니다.
4. **슬로우 패스 3단계 (`NEW_SLAB`)**:
   - 위 조건이 모두 없으면, 버디 할당자로부터 신규 슬랩을 생성하여 활성 슬랩으로 등록하고 첫 객체를 반환합니다.

### 3. 메모리 해제 경로 (`FREE`)
`alloc_id`의 반환 요청 시:
- 해당 객체가 할당된 슬랩을 탐색합니다:
  1) **로컬 CPU 활성 슬랩인 경우**: 즉시 로컬 `c->freelist`의 헤드에 LIFO 방식으로 재삽입합니다.
  2) **타 CPU의 활성 슬랩인 경우**: 해당 슬랩의 `page_freelist`에 삽입합니다 (락리스 원격 해제).
  3) **비활성 슬랩(partial)인 경우**: 해당 슬랩의 자체 `freelist`에 삽입합니다.
- `slab->inuse`가 1 감소합니다.
- 만약 슬랩의 모든 객체가 반환되어 `inuse == 0`이 되었고, 해당 슬랩이 `node_partial`에 위치하며 남은 partial 슬랩 수가 `min_partial`을 초과한다면:
  - 해당 빈 슬랩은 버디 할당자로 즉시 회수(`SLAB_DISCARDED_TO_BUDDY`)됩니다.

### 4. 무결성 검증 및 커널 패닉 (`CORRUPT_FREELIST`)
- 비정상적인 힙 덮어쓰기로 인해 암호화된 프리리스트 포인터가 손상된 경우:
- 즉시 상태 `"KERNEL_PANIC_FREELIST_CORRUPTION"`을 기록하고 이후 모든 연산은 거부(`PANIC_IGNORED`)됩니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "object_size": 64,
    "objects_per_slab": 4,
    "hardened_cookie": 305419896,
    "min_partial": 2
  },
  "operations": [
    {"op_id": 1, "type": "ALLOC", "cpu": 0, "alloc_id": "a1"},
    {"op_id": 2, "type": "ALLOC", "cpu": 0, "alloc_id": "a2"},
    {"op_id": 3, "type": "FREE", "cpu": 0, "alloc_id": "a2"},
    {"op_id": 4, "type": "ALLOC", "cpu": 0, "alloc_id": "a3"}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 단일 행으로 출력합니다:

```json
{
  "summary": {
    "total_allocations": 3,
    "total_frees": 1,
    "fast_path_allocations": 2,
    "slow_path_allocations": 1,
    "active_slabs_in_node_partial": 0,
    "panic_triggered": false
  },
  "operations": [
    {
      "op_id": 1,
      "type": "ALLOC",
      "alloc_id": "a1",
      "status": "SUCCESS",
      "alloc_path": "NEW_SLAB",
      "slab_id": 1,
      "obj_idx": 0,
      "obj_addr": "0x1000"
    },
    {
      "op_id": 2,
      "type": "ALLOC",
      "alloc_id": "a2",
      "status": "SUCCESS",
      "alloc_path": "FAST_PATH",
      "slab_id": 1,
      "obj_idx": 1,
      "obj_addr": "0x1040"
    },
    {
      "op_id": 3,
      "type": "FREE",
      "alloc_id": "a2",
      "status": "FREE_SUCCESS",
      "slab_id": 1,
      "obj_idx": 1
    },
    {
      "op_id": 4,
      "type": "ALLOC",
      "alloc_id": "a3",
      "status": "SUCCESS",
      "alloc_path": "FAST_PATH",
      "slab_id": 1,
      "obj_idx": 1,
      "obj_addr": "0x1040"
    }
  ]
}
```

---

## 제약 사항
- `1 <= len(operations) <= 1,000`
- `32 <= object_size <= 4096`
- `2 <= objects_per_slab <= 128`
- `0 <= cpu <= 15`
