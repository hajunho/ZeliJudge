# 🌟 [Grand Milestone 990] 리눅스 커널 SLUB 할당자 CPU 슬랩 프리리스트 인버트(Invert) 및 부분 리스트 하베스팅 엔진

## 1. 개요 및 배경

리눅스 커널의 메모리 할당 계층은 페이지 단위(4KB) 관리를 담당하는 버디 할당자(Buddy Allocator) 위에 작은 객체(몇 바이트~수 킬로바이트)를 바이트 정밀도로 고속 할당하는 **슬랩 할당자(SLAB/SLUB/SLOB)**를 두고 있습니다.
초기 유닉스와 리눅스를 지배했던 본윅(Jeff Bonwick)의 전통적 SLAB 할당자는 CPU별 객체 큐와 3가지 리스트(`slabs_full`, `slabs_partial`, `slabs_empty`)를 유지하여 수백 코어의 거대 NUMA 시스템에서 수 기가바이트의 큐 메타데이터 메모리를 낭비하고 전역 스핀락 경합을 유발했습니다.

크리스토프 라메터(Christoph Lameter)가 설계하여 리눅스 2.6.22에 머지된 **SLUB 할당자(`mm/slub.c`)**는 모든 대기열 큐를 제거하고 슬랩 페이지 자체에 포인터를 내장하는 획기적인 Unqueued 아키텍처로 커널 메모리 관리의 새로운 표준이 되었습니다:
1. **패스트 패스(Fast Path, `kmem_cache_cpu`)**:
   - 각 CPU는 `struct kmem_cache_cpu`를 통해 단 하나의 활성 슬랩 페이지(`page`)와 로컬 프리리스트 포인터(`freelist`)만을 유지합니다.
   - 단 3~4개의 레지스터 명령어(CMPXCHG 또는 로컬 포인터 갱신)만으로 스핀락 없이 즉각 객체를 할당받습니다.
2. **프로즌 슬랩(Frozen Page, `page->frozen = 1`)**:
   - 특정 CPU의 활성 슬랩으로 지정된 페이지는 "동결(Frozen)"됩니다.
   - 오직 해당 CPU만이 로컬 `freelist`에서 객체를 할당할 수 있습니다.
   - 그러나 **다른 CPU가 해당 슬랩에 속한 객체를 `kfree()`할 경우**, 활성 CPU의 작업을 방해하지 않고 원자적 연산을 통해 슬랩 페이지의 원격 프리리스트(`page->freelist`)에 객체를 반환합니다.
3. **슬로우 패스(Slow Path)와 프리리스트 인버트(Invert)**:
   - 활성 CPU가 로컬 프리리스트를 모두 소진(`freelist == NULL`)하면:
     - **인버트(Invert)**: 다른 CPU들이 원격으로 반환해 둔 `page->freelist`를 통째로 가져와 로컬 `freelist`로 반전(Invert)시켜 즉시 패스트 패스로 복귀합니다!
     - **언프리즈(Unfreeze)**: 원격 프리리스트마저 비어있으면 슬랩이 완전히 꽉 찼으므로 동결을 해제(`page->frozen = 0`)합니다.
     - **노드 부분 리스트 하베스팅(Node Partial Harvesting)**: NUMA 노드의 공유 부분 리스트(`kmem_cache_node->partial`)에서 반쯤 찬 슬랩을 수확(Harvest)하여 새 활성 슬랩으로 동결합니다.
     - **버디 할당자 폴백(Buddy Fallback)**: 가용 슬랩이 없으면 버디 할당자로부터 새로운 복합 페이지(Compound Page)를 할당받아 포맷합니다.
4. **빈 슬랩 회수(Empty Slab Reclamation)**:
   - 동결 해제된 슬랩의 모든 객체가 해제되어 완전히 비었을 때, `min_partial` 임계치를 초과하면 해당 물리 페이지를 즉시 버디 할당자에 반납하여 시스템 메모리를 회수합니다.

본 Grand Milestone 990 과제에서는 리눅스 커널 SLUB 할당자의 락리스 패스트 패스, 프로즌 페이지 원격 해제, 프리리스트 인버트, 노드 부분 리스트 하베스팅 및 버디 메모리 회수 파이프라인을 정밀하게 구현합니다.

---

## 2. 아키텍처 다이어그램

```
+-----------------------------------------------------------------------------------+
|               Per-CPU kmem_cache_cpu (Fast Path, Zero Locks)                      |
|                                                                                   |
|   [ CPU 0 Cache ]                                [ CPU 1 Cache ]                  |
|    - Active Slab: Slab 0 (FROZEN by CPU 0)        - Active Slab: Slab 1 (FROZEN)   |
|    - Local freelist: [ obj1 -> obj2 ]             - Local freelist: [ obj4 ]       |
+-----------------------------------------------------------------------------------+
       ^                                                   |
       | Local Alloc (Fast Path)                           | Remote kfree(obj0)
       v                                                   v
+-----------------------------------+       +------------------------------------+
|       Slab 0 (Frozen by CPU 0)    |       |   Remote Free List (page->freelist)|
|   - In-use: 3/4                   | <==== |    [ obj0 ] (Pushed by CPU 1 via   |
|   - Local: [ obj1, obj2 ]         |       |              atomic CMPXCHG!)      |
+-----------------------------------+       +------------------------------------+
       |
       | When Local freelist exhausted:
       v
  [ SLOW PATH INVERT ]: Swap page->freelist into CPU 0 Local freelist!
       |
       | If both Local & Remote empty (Slab Full):
       v
  [ UNFREEZE ]: page->frozen = 0
       |
       v
+-----------------------------------------------------------------------------------+
|               Per-Node kmem_cache_node (Shared Partial Slabs)                     |
|                                                                                   |
|   [ Node Partial List (n->partial) ]                                              |
|    - [ Slab 2 (Unfrozen, Inuse 2/4) ] -> [ Slab 3 (Unfrozen, Inuse 1/4) ]         |
|    * Protected by n->list_lock                                                    |
|    * Harvested by starving CPUs (Frozen & moved to CPU cache)                     |
+-----------------------------------------------------------------------------------+
       |
       | When Partial List empty:
       v
  [ BUDDY ALLOCATOR ]: allocate_slab() -> new compound page
```

---

## 3. 핵심 규칙 및 상태 전이 모델

### 3.1 객체 할당 파이프라인 (`ALLOC_OBJECT`)
1. **패스트 패스**:
   - CPU 로컬 `freelist`에 객체가 있으면 즉시 팝하여 반환 (`status: "SUCCESS"`, `path: "FAST_PATH"`).
2. **슬로우 패스 - 인버트(Invert)**:
   - 로컬 `freelist`가 비어있으나 활성 슬랩의 `remote_freelist`에 원격 해제된 객체가 존재하는 경우:
   - `remote_freelist`의 객체들을 로컬 `freelist`로 가져와 첫 번째 객체를 반환 (`path: "SLOW_PATH_INVERT"`).
3. **슬로우 패스 - 동결 해제(Unfreeze) 및 하베스팅**:
   - 활성 슬랩의 모든 객체가 사용 중이면 슬랩 동결을 해제(`frozen_by_cpu = None`).
   - `node_partial` 리스트에 가용 슬랩이 존재하면:
     - 첫 번째 슬랩을 꺼내 해당 CPU의 활성 슬랩으로 동결(`frozen_by_cpu = cpu`).
     - 슬랩의 프리리스트를 로컬 `freelist`로 가져와 할당 (`path: "PARTIAL_HARVEST"`).
4. **슬로우 패스 - 버디 할당자 폴백**:
   - `node_partial`마저 비어있으면 버디 할당자로부터 새 슬랩(`new_slab_id`)을 생성.
   - 새 슬랩을 동결하고 객체 하나를 할당 (`path: "BUDDY_NEW_SLAB"`).

### 3.2 객체 해제 파이프라인 (`FREE_OBJECT`)
1. **동결 슬랩(`frozen_by_cpu != None`) 해제**:
   - 동결한 CPU 자신이 해제한 경우: 로컬 `freelist` 앞부분에 삽입 (`type: "LOCAL_FREE"`).
   - 타 CPU가 원격 해제한 경우: 슬랩의 `remote_freelist`에 삽입 (`type: "REMOTE_FREE_FROZEN"`).
2. **비동결 슬랩(`frozen_by_cpu == None`) 해제**:
   - 슬랩의 `remote_freelist`에 객체 삽입.
   - 직전 상태가 완전 포화(`inuse == objs_per_slab`)였다면 부분 가용 상태로 전이되므로 `node_partial` 리스트에 삽입 (`type: "UNFROZEN_TO_PARTIAL"`).
   - 슬랩의 모든 객체가 해제되어 `inuse == 0`이 된 경우:
     - `len(node_partial) > min_partial`이면 `node_partial`에서 제거하고 버디 할당자로 완전 반납 (`type: "EMPTY_SLAB_FREED_TO_BUDDY"`).
     - 그렇지 않으면 파편화 방지를 위해 `node_partial`에 보존 (`type: "EMPTY_SLAB_KEPT_IN_PARTIAL"`).

---

## 4. 입출력 규격

### 입력 JSON 구조
```json
{
  "config": {
    "objs_per_slab": 4,
    "min_partial": 1,
    "nr_cpus": 2
  },
  "operations": [
    {"type": "ALLOC_OBJECT", "cpu": 0, "alloc_id": "a1"},
    {"type": "ALLOC_OBJECT", "cpu": 0, "alloc_id": "a2"},
    {"type": "ALLOC_OBJECT", "cpu": 0, "alloc_id": "a3"},
    {"type": "ALLOC_OBJECT", "cpu": 0, "alloc_id": "a4"},
    {"type": "FREE_OBJECT", "cpu": 1, "alloc_id": "a2"},
    {"type": "ALLOC_OBJECT", "cpu": 0, "alloc_id": "a5"},
    {"type": "QUERY_SLUB_STATE"}
  ]
}
```

### 출력 JSON 구조
```json
{
  "operation_results": [
    {
      "op_index": 0,
      "type": "ALLOC_OBJECT",
      "cpu": 0,
      "alloc_id": "a1",
      "status": "SUCCESS",
      "path": "BUDDY_NEW_SLAB",
      "slab_id": 0,
      "obj": "s0_o0"
    },
    {
      "op_index": 1,
      "type": "ALLOC_OBJECT",
      "cpu": 0,
      "alloc_id": "a2",
      "status": "SUCCESS",
      "path": "FAST_PATH",
      "slab_id": 0,
      "obj": "s0_o1"
    },
    {
      "op_index": 4,
      "type": "FREE_OBJECT",
      "cpu": 1,
      "alloc_id": "a2",
      "status": "SUCCESS",
      "type": "REMOTE_FREE_FROZEN",
      "slab_id": 0,
      "frozen_by": 0,
      "obj": "s0_o1"
    },
    {
      "op_index": 5,
      "type": "ALLOC_OBJECT",
      "cpu": 0,
      "alloc_id": "a5",
      "status": "SUCCESS",
      "path": "SLOW_PATH_INVERT",
      "slab_id": 0,
      "obj": "s0_o1"
    }
  ],
  "summary": {
    "total_operations": 7,
    "active_allocations_count": 4,
    "active_slabs_count": 1,
    "node_partial_count": 0,
    "stats": {
      "fast_path_allocs": 3,
      "slow_path_inverts": 1,
      "partial_harvests": 0,
      "buddy_new_slabs": 1,
      "local_frees": 0,
      "remote_frees": 1,
      "slabs_freed_to_buddy": 0
    }
  }
}
```
