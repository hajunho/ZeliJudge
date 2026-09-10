# 문제 #287: 리눅스 커널 SLUB 메모리 할당자: Per-CPU Freelist Fast-Path, 슬랩 동결(Slab Freezing) 및 노드 부분 목록 스핀락 경합 방어 시뮬레이터

## 실무 배경: 초당 2,000만 패킷 처리 서버의 kmem_cache 스핀락 병목과 캐시 쓰레싱 참사
대규모 금융 결제 망 및 100Gbps CDN 엣지 프록시 인프라를 운영하는 빅테크 기업에서, 64코어 대형 NUMA 서버를 도입한 직후 네트워크 패킷 처리 엔진(`sk_buff`)과 epoll 이벤트 버퍼의 지연 시간이 P99 150ns에서 무려 85μs(약 560배)로 폭증하며 심각한 처리량 절벽(Throughput Collapse)이 발생했습니다.

리눅스 커널 프로파일링 도구 `perf top` 및 `perf lock`을 가동한 결과, CPU 코어들의 실행 시간 중 72.4%가 `kmem_cache_node->list_lock` 스핀락을 획득하기 위해 대기하는 경합(Lock Contention)에 소모되고 있었습니다:
```text
  72.41%  [kernel.kallsyms]  [k] native_queued_spin_lock_slowpath
          |-- get_partial_node.isra.0
          |-- ___slab_alloc
          |-- kmem_cache_alloc
          +-- __alloc_skb
```

과거 리눅스 커널의 고전적 `SLAB` 할당자는 CPU별로 포인터 큐(`struct array_cache`)를 유지했으나, 메모리 오버헤드가 극심하고 큐가 빌 때마다 중앙 락을 잡아야 했습니다. 이에 리눅스 2.6.23부터 도입된 현대적 `SLUB` 할당자(`mm/slub.c`)는 객체 내부에 포인터를 직접 임베딩하는 침투형 연결 리스트(Intrusive Freelist) 구조와 **슬랩 동결(Slab Freezing)** 기법을 통해 락 없는(Lockless) Per-CPU Fast-Path 할당을 실현했습니다.

그러나 분산 패킷 파이프라인에서 수신 CPU(Core 0)가 패킷을 할당하고 전송/워커 CPU(Core 1~63)가 이를 비동기로 해제하는 **원격 해제(Cross-CPU Remote Free)** 패턴이 발생할 때, 슬랩의 라이프사이클(동결 상태, CPU 부분 목록 `c->partial`, 노드 부분 목록 `n->partial`)이 어떻게 전이되는지 이해하지 못하면 심각한 슬랩 고갈 및 버디 할당자(Buddy Allocator) 폴백 지연이 초래됩니다.

시스템 코어 엔지니어로서, 리눅스 커널 `mm/slub.c`의 5단계 할당 경로(Fast Path $	o$ CPU 페이지 재충전 $	o$ CPU Partial $	o$ Node Partial $	o$ Buddy Alloc)와 슬랩 동결/해제(Slab Freezing/Unfreezing) 상태 머신을 정확하게 모델링하고 메모리 단편화와 락 경합을 방어하는 시뮬레이터를 구현하십시오.

---

## 5단계 할당 경로 및 원격 해제 상태 머신 사양

### 1. 자료구조 사양
* **`SlabPage`**: 버디 할당자로부터 할당받은 물리 페이지 단위 슬랩.
  - `page_id`: 슬랩 고유 식별자 (`slab-1`, `slab-2`, ...).
  - `objects`: 슬랩당 고정 객체 수 (`objects_per_slab`).
  - `inuse`: 현재 외부에서 사용 중인 객체 수.
  - `frozen`: 슬랩이 특정 CPU에 활성 슬랩(`c->page`)으로 바인딩되어 있는지 여부. 활성 상태인 동안 `frozen = True`.
  - `cpu_owner`: 현재 바인딩된 CPU 번호 (바인딩 해제 시 `None`).
  - `freelist`: 원격 해제되었거나 부분 목록에 있을 때 사용 가능한 객체 ID 목록.
* **`kmem_cache_cpu` (Per-CPU 캐시)**:
  - `page`: 해당 CPU에 활성 바인딩된 `SlabPage` (없으면 `None`).
  - `freelist`: CPU 전용 Fast-Path 객체 풀 (락 없이 LIFO로 꺼냄).
  - `partial`: 해당 CPU 전용 슬랩 부분 목록 (최대 `cpu_partial_limit`개까지 보관).
* **`kmem_cache_node` (NUMA 노드 공용 캐시)**:
  - `partial`: 노드 전역 슬랩 부분 목록 (`SlabPage` 리스트).
  - `node_lock_acquisitions`: 노드 스핀락(`list_lock`) 획득 횟수 카운터.

---

### 2. 5단계 객체 할당 (`ALLOC(cpu)`)
할당 요청이 들어오면 다음 5단계 경로를 순서대로 탐색하여 최초로 성공하는 경로에서 객체를 할당합니다:

1. **Path 1: `FAST_PATH_CPU_FREELIST` (락 0회)**
   - `c->page`가 존재하고 `c->freelist`에 원소가 남아 있는 경우:
     - `c->freelist.pop(0)`으로 객체 추출, `c->page.inuse += 1`.
2. **Path 2: `SLOW_PATH_CPU_PAGE_REFILL` (락 0회)**
   - `c->page`가 존재하고 `c->freelist`는 비었으나, 원격 CPU들이 반환한 `c->page.freelist`에 객체가 있는 경우:
     - `c->freelist = c->page.freelist`, `c->page.freelist = []`.
     - `c->freelist.pop(0)`으로 객체 추출, `c->page.inuse += 1`.
3. **슬랩 소진 및 동결 해제 (`c->page` unfreeze)**:
   - 만약 이전 `c->page`가 존재하지만 완전히 꽉 찬 상태(`inuse == objects`이고 양쪽 freelist 모두 공백)라면:
     - `c->page.frozen = False`, `c->page.cpu_owner = None`, `c->page = None`.
4. **Path 3: `SLOW_PATH_CPU_PARTIAL` (락 0회)**
   - `c->partial`에 슬랩이 1개 이상 존재하는 경우:
     - 첫 번째 슬랩을 꺼내 `c->page`로 바인딩 (`frozen = True`, `cpu_owner = cpu`).
     - 슬랩의 `freelist`를 `c->freelist`로 가져옴 (`slab.freelist = []`).
     - `c->freelist.pop(0)` 추출, `c->page.inuse += 1`.
5. **Path 4: `SLOW_PATH_NODE_PARTIAL` (스핀락 `node_lock_acquisitions += 1`)**
   - `node.partial`에 슬랩이 1개 이상 존재하는 경우:
     - 노드 락 획득 후 첫 번째 슬랩을 꺼내 `c->page`로 바인딩 (`frozen = True`, `cpu_owner = cpu`).
     - 슬랩의 `freelist`를 `c->freelist`로 가져옴.
     - **프리페치 최적화**: 이후 CPU partial 용량(`cpu_partial_limit`)이 찰 때까지 `node.partial`의 슬랩들을 꺼내 `c->partial`로 미리 채워 락 경합을 예방함.
     - 노드 락 해제 후 `c->freelist.pop(0)` 추출, `c->page.inuse += 1`.
6. **Path 5: `SLOW_PATH_BUDDY_ALLOC` (스핀락 1회 시도 후 실패 시)**
   - 노드 partial도 비어 있는 경우 (`node_lock_acquisitions += 1` 발생):
     - 버디 할당자를 호출하여 신규 `SlabPage`(`slab-k`)를 생성.
     - `c->page = slab`, `frozen = True`, `cpu_owner = cpu`.
     - 총 $N$개 객체 중 첫 번째 객체를 호출자에게 반환하고, 나머지 $N-1$개 객체를 `c->freelist`에 적재 (`c->page.inuse = 1`).

---

### 3. 객체 해제 (`FREE(cpu, obj_id)`)
해제 대상 객체가 속한 `slab`의 `inuse`를 1 감소시키고 다음 조건에 따라 처리합니다:

1. **Case 1: `FAST_PATH_LOCAL_FREE` (락 0회)**
   - 해제하는 CPU가 해당 슬랩의 현재 활성 소유자(`c->page == slab`)인 경우:
     - `c->freelist.insert(0, obj_id)`로 즉시 LIFO 반환.
2. **Case 2: `SLOW_PATH_REMOTE_FREE_FROZEN` (락 0회, Atomic cmpxchg)**
   - 슬랩이 다른 CPU에서 활성 상태(`slab.frozen == True`)인 경우:
     - 원격 CPU의 캐시 라인을 침범하지 않고 `slab.freelist.append(obj_id)`에 안전하게 적재.
3. **Case 3: `SLOW_PATH_UNFREEZE_TO_PARTIAL` (스핀락 `node_lock_acquisitions += 1`)**
   - 슬랩이 동결 상태가 아니며(`frozen == False`), 어떤 부분 목록에도 속해 있지 않던 만석(Full) 슬랩인 경우:
     - 이제 1개의 빈 공간이 생겼으므로 부분 슬랩으로 전이.
     - `slab.freelist.append(obj_id)`.
     - 노드 스핀락 획득 후 `node.partial.append(slab)`.
4. **Case 4: `SLOW_PATH_PARTIAL_FREED` 및 빈 슬랩 버디 회수 (`SLOW_PATH_DISCARD_EMPTY_SLAB`)**
   - 슬랩이 이미 부분 목록에 있는 경우:
     - `slab.freelist.append(obj_id)`.
     - 만약 슬랩의 사용 중 객체 수가 0(`slab.inuse == 0`)이 되었고, `node.partial`의 총 슬랩 수가 임계치(`min_partial`)를 초과한다면:
       - 메모리 단편화를 방지하기 위해 노드 스핀락 획득 후 슬랩을 `node.partial`에서 제거하고 버디 할당자에 물리 메모리를 반환(`buddy_free_count += 1`).

---

### 4. CPU 슬랩 동결 해제 (`UNFREEZE(cpu)`)
CPU 컨텍스트 스위칭, 오프라인 또는 주기적 플러시 시:
- `c->page`의 남은 `c->freelist`를 `c->page.freelist`로 반환.
- `c->page.frozen = False`, `c->page.cpu_owner = None`, `c->page = None`.
- 슬랩이 완전히 비었으면 버디로 즉시 반환.
- 슬랩이 일부 차 있는 경우 `c->partial` 한도 내라면 `c->partial`에 보관, 초과 시 노드 스핀락을 획득하고 `node.partial`로 방출.

---

## 입력 형식
표준 입력(stdin)으로 JSON 객체가 주어집니다:
```json
{
  "config": {
    "objects_per_slab": 4,
    "cpu_count": 2,
    "cpu_partial_limit": 2,
    "min_partial": 1
  },
  "operations": [
    {"op": "ALLOC", "cpu": 0},
    {"op": "ALLOC", "cpu": 0},
    {"op": "FREE", "cpu": 0, "obj_id": "slab-1-obj0"},
    {"op": "ALLOC", "cpu": 0}
  ]
}
```

## 출력 형식
표준 출력(stdout)으로 연산 처리 결과 및 종합 통계 지표를 JSON 단일 라인으로 출력합니다:
```json
{
  "operations_processed": 4,
  "history": [
    {"allocated_obj": "slab-1-obj0", "path": "SLOW_PATH_BUDDY_ALLOC", "slab": "slab-1"},
    {"allocated_obj": "slab-1-obj1", "path": "FAST_PATH_CPU_FREELIST", "slab": "slab-1"},
    {"status": "OK", "path": "FAST_PATH_LOCAL_FREE", "slab": "slab-1"},
    {"allocated_obj": "slab-1-obj0", "path": "FAST_PATH_CPU_FREELIST", "slab": "slab-1"}
  ],
  "metrics": {
    "alloc_paths": {
      "fast_path_cpu": 2,
      "refill_from_page": 0,
      "cpu_partial": 0,
      "node_partial": 0,
      "buddy_alloc": 1
    },
    "free_paths": {
      "fast_path_local": 1,
      "remote_frozen": 0,
      "unfreeze_to_partial": 0,
      "partial_freed": 0,
      "discard_empty_slab": 0
    },
    "node_lock_acquisitions": 1,
    "live_objects_inuse": 2,
    "live_slabs_count": 1,
    "total_buddy_slabs_allocated": 1,
    "total_buddy_slabs_freed": 0,
    "node_partial_slabs": [],
    "cpu_caches": {
      "0": {"active_slab": "slab-1", "local_free_count": 2, "cpu_partial_slabs": []},
      "1": {"active_slab": null, "local_free_count": 0, "cpu_partial_slabs": []}
    },
    "memory_efficiency_pct": 50.0
  }
}
```
