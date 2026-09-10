# 리눅스 커널 SLUB 메모리 할당자 이론 백서: Per-CPU Lockless Freelist, 슬랩 동결(Slab Freezing), 그리고 NUMA 노드 스핀락 경합 제어

## 1. 슬랩 할당자의 계보: SLAB, SLOB, 그리고 SLUB

리눅스 커널의 물리 메모리는 기본적으로 4KB 크기의 연속된 페이지 프레임을 다루는 **버디 할당자(Buddy Allocator, `alloc_pages`)**에 의해 관리됩니다. 그러나 커널 내부의 수많은 핵심 자료구조(`struct task_struct`, `struct dentry`, `struct inode`, `struct sk_buff`, `struct file`)는 수십 바이트에서 수백 바이트 크기에 불과합니다.

만약 256바이트 크기의 `dentry`를 생성할 때마다 4KB 페이지 전체를 할당한다면 93% 이상의 심각한 **내부 단편화(Internal Fragmentation)**가 발생하며, 페이지 테이블 매핑 및 버디 트리 분할에 막대한 CPU 사이클이 낭비됩니다.

이를 해결하기 위해 본 저프 호(Jeff Bonwick)가 1994년 SunOS에서 고안한 **슬랩 할당자(Slab Allocator)**가 리눅스 커널에 도입되었습니다:

```
+-------------------------------------------------------------+
|               버디 할당자 (Buddy Allocator)                 |
|       order-0 (4KB), order-1 (8KB) ... order-10 (4MB)       |
+-------------------------------------------------------------+
                              ▲
                              │ alloc_pages() / free_pages()
                              ▼
+-------------------------------------------------------------+
|                  SLUB 할당자 (kmem_cache)                   |
|  +-------------------------------------------------------+  |
|  | kmem_cache_cpu (Per-CPU Fast-Path)                    |  |
|  |  - c->freelist (락 없는 LIFO 로컬 할당/해제)          |  |
|  |  - c->page     (동결된 활성 슬랩 페이지)              |  |
|  |  - c->partial  (CPU 전용 부분 목록)                   |  |
|  +-------------------------------------------------------+  |
|                             ▲                               |
|                             │ Slow-path (스핀락 획득)       |
|                             ▼                               |
|  +-------------------------------------------------------+  |
|  | kmem_cache_node (NUMA 노드 공용)                      |  |
|  |  - n->partial  (노드 전역 부분 목록)                  |  |
|  |  - list_lock   (스핀락 경합 지점)                     |  |
|  +-------------------------------------------------------+  |
+-------------------------------------------------------------+
```

### 3대 슬랩 할당자 비교
1. **SLAB (전통적 할당자)**:
   - 각 CPU마다 포인터 배열 큐(`struct array_cache`)를 유지.
   - 대규모 SMP(다중 코어) 시스템에서 객체 포인터 큐 자체가 수십 메가바이트의 메모리를 소비.
   - 큐가 비거나 넘칠 때마다 노드 락 경합 발생.
2. **SLOB (Simple List Of Blocks)**:
   - 임베디드 및 극소형 RAM 시스템을 위한 단순 퍼스트-핏(First-Fit) 연결 리스트.
   - 단편화가 심하고 멀티코어 확장성 전무 (리눅스 6.4에서 퇴출).
3. **SLUB (현대 기본 할당자, Linux 2.6.23+)**:
   - 크리스토프 람페터(Christoph Lameter)가 설계.
   - 객체 포인터 큐를 완전히 제거하고, **비어 있는 객체 자체의 메모리 공간에 다음 빈 객체의 포인터를 직접 저장(Intrusive Freelist)**.
   - 메타데이터 오버헤드를 극적으로 축소하고 **슬랩 동결(Slab Freezing)**을 통해 완벽한 Per-CPU Fast Path를 구현.

---

## 2. Intrusive Freelist와 메모리 레이아웃

SLUB 할당자의 가장 천재적인 최적화는 별도의 연결 리스트 노드나 배열을 할당하지 않고, **미사용 객체의 내부 바이트를 그대로 다음 객체의 주소 포인터로 사용하는 침투형(Intrusive) 기법**입니다:

```text
[Slab Page (4KB)]
+-------------------+-------------------+-------------------+-------------------+
|  Object 0 (Alloc) |  Object 1 (Free)  |  Object 2 (Free)  |  Object 3 (Free)  |
|  [User Payload]   |  [*ptr -> Obj 2]  |  [*ptr -> Obj 3]  |  [*ptr -> NULL]   |
+-------------------+-------------------+-------------------+-------------------+
                              ▲
                              │
                    c->freelist 포인터
```

* **할당 시 (`kmem_cache_alloc`)**:
  - `obj = c->freelist;`
  - `c->freelist = *(void **)obj;` (객체의 첫 워드에 적힌 다음 객체 주소로 이동)
  - 단 2번의 메모리 로드로 할당 완료!
* **해제 시 (`kmem_cache_free`)**:
  - `*(void **)obj = c->freelist;`
  - `c->freelist = obj;`
  - 단 2번의 메모리 저장으로 반환 완료 (LIFO 캐시 적중률 극대화)!

---

## 3. 슬랩 동결(Slab Freezing)과 원격 해제(Remote Free) 동역학

멀티코어 시스템에서 가장 치명적인 문제는 **CPU A에서 할당된 객체가 네트워크 드라이버나 파이프를 통해 CPU B로 전달된 후 CPU B에서 해제될 때** 발생합니다.

만약 CPU B가 CPU A의 `c->freelist`에 직접 접근하려 한다면 원자적 락이나 무거운 캐시 라인 바운싱(Bouncing)이 발생하여 양쪽 CPU의 성능이 파괴됩니다. SLUB은 이를 **슬랩 동결(Slab Freezing)** 메커니즘으로 우아하게 분리했습니다:

### 동결 상태 (`slab.frozen == True`)
- 슬랩 페이지가 특정 CPU의 `c->page`로 바인딩되는 순간, 커널은 이 슬랩을 **동결(Frozen)** 상태로 표시합니다.
- 동결된 슬랩에 대한 의미론:
  1. **로컬 CPU (소유자)**: `c->freelist`를 통해 락 없이 단독으로 할당과 해제를 수행합니다.
  2. **원격 CPU (타 코어)**: 객체를 해제할 때, 로컬 `c->freelist`를 건드리지 않고 해당 슬랩 페이지 구조체의 `page->freelist`에 원자적 `cmpxchg_double`로 조용히 반환합니다.
  3. **노드 목록 격리**: 동결된 슬랩은 원격에서 객체가 반환되어 빈 공간이 생기더라도 **절대로 노드 부분 목록(`node.partial`)으로 이동하지 않습니다**. 오직 활성 소유자인 CPU의 배타적 권한 하에 머뭅니다.

```text
[CPU 0]                                             [CPU 1] (Remote Core)
  c->page = Slab A (Frozen)                           Free(Object X in Slab A)
  c->freelist ──► [Obj 0] ──► [Obj 1]                     │
                                                          │ (Atomic cmpxchg)
                                                          ▼
                                                    Slab A->freelist ──► [Obj X]
                                                    (Zero Lock on CPU 0 cache!)
```

### 페이지 프리리스트 재충전 (`SLOW_PATH_CPU_PAGE_REFILL`)
CPU 0의 로컬 `c->freelist`가 모두 소진되었을 때, CPU 0은 즉시 새 슬랩을 가져오지 않고 자신의 활성 페이지 `c->page->freelist`를 확인합니다.
타 코어들이 비동기로 반환해 놓은 객체들이 있다면, 단 한 번의 포인터 교체로 로컬 `c->freelist`로 가져와 재활용합니다.

---

## 4. 슬랩 부분 목록 위계와 노드 스핀락 경합 제어

CPU가 자신의 활성 슬랩과 로컬 프리리스트를 모두 소진하면 다음 단계의 캐시 계층으로 이동합니다:

```text
               ┌───────────────────────────────┐
               │    ALLOC(cpu) 요청 도착       │
               └──────────────┬────────────────┘
                              │
               [c->freelist 비어 있는가?]
                 ├── 아니오 ──► [FAST PATH: c->freelist.pop(0)] (0ns, Lockless)
                 └── 예
                              │
               [c->page->freelist 있는가?]
                 ├── 예 ──────► [SLOW PATH 2: c->freelist 재충전] (원격 반환 수확)
                 └── 아니오 (슬랩 완전 소진)
                              │
               [c->page 동결 해제 (Full 슬랩 배출)]
                              │
               [c->partial 에 슬랩 있는가?]
                 ├── 예 ──────► [SLOW PATH 3: CPU Partial에서 슬랩 팝] (Lockless)
                 └── 아니오
                              │
               ┌──────────────▼────────────────┐
               │  node->list_lock 스핀락 획득  │ (경합 지점!)
               └──────────────┬────────────────┘
                              │
               [node->partial 에 슬랩 있는가?]
                 ├── 예 ──────► [SLOW PATH 4: Node Partial에서 슬랩 추출]
                 │              + CPU Partial 프리페치 (최대 cpu_partial_limit개)
                 └── 아니오
                              │
               [SLOW PATH 5: 버디 할당자 alloc_pages() 호출]
                 ├── 새 SlabPage 생성 및 초기화
                 └── 호출자에게 1개 반환, 나머지 c->freelist 적재
```

### CPU Partial 프리페치(Pre-fetching) 기법
만약 CPU가 노드 부분 목록에서 슬랩을 하나씩만 가져온다면, 수많은 코어가 빈번하게 `node->list_lock`을 획득하기 위해 몰려들어 극심한 스핀락 지연이 발생합니다.
따라서 SLUB은 노드 락을 한 번 잡았을 때 최대 `cpu_partial_limit`개의 부분 슬랩을 한꺼번에 CPU 전용 큐(`c->partial`)로 옮겨 담습니다. 이를 통해 이후 수십 번의 슬랩 교체가 노드 락 없이 로컬에서 즉시 수행됩니다.

---

## 5. 빈 슬랩 회수와 버디 할당자 단편화 방지

시스템 워크로드가 폭주한 후 평온한 상태로 돌아왔을 때, 수천 개의 슬랩이 부분적으로만 사용된 채 방치된다면 심각한 메모리 낭비가 발생합니다.

SLUB은 해제 시 슬랩의 `inuse`가 0이 되는 순간을 감지합니다:
- 현재 노드 부분 목록(`node.partial`)에 충분한 여유 슬랩(`len(node.partial) > min_partial`)이 존재한다면, 커널은 해당 슬랩을 부분 목록에서 제거하고 `free_pages()`를 통해 버디 할당자에 물리 페이지를 즉시 반환합니다.
- 이를 통해 커널은 메모리 스파이크에 신속하게 대응하면서도 유휴 메모리를 물리 연속 메모리로 재합성하여 시스템의 장기 단편화를 방지합니다.
