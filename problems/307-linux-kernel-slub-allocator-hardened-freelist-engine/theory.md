# 기술 이론: 리눅스 커널 SLUB 메모리 할당자(mm/slub.c) 아키텍처

## 1. 개요 및 설계 진화 (SLAB vs SLUB)
초기 리눅스 커널의 SLAB 할당자는 본 오프젝트(Bonwick)의 Solaris 슬랩 알고리즘을 모방하여 정교한 큐(Queue)와 슬랩 디스크립터를 유지했습니다. 그러나 멀티코어 NUMA 시스템이 대형화되면서 슬랩 자체를 관리하기 위한 메타데이터 오버헤드와 큐 동기화 락 경합이 심각한 병목으로 대두되었습니다.

크리스토프 라메터(Christoph Lameter)가 설계한 **SLUB 할당자**는 슬랩 디스크립터를 별도로 두지 않고, 커널의 물리 페이지 구조체인 `struct page`의 유휴 필드(union)를 직접 슬랩 메타데이터로 재활용하여 메모리 낭비를 0으로 줄이고 구조를 극단적으로 단순화했습니다.

```
 [ kmem_cache ]
      │
      ├─► kmem_cache_cpu (Per-CPU Fast Path, No Lock)
      │     ├── freelist ──► [ Obj 0 ] ──► [ Obj 1 ] ──► NULL
      │     └── page (Active Slab)
      │
      └─► kmem_cache_node (Per-NUMA Node, spin_lock)
            └── partial (Partial Slab List)
                  ├── [ Slab A (1/8 used) ]
                  └── [ Slab B (3/8 used) ]
```

---

## 2. Fast Path와 Slow Path 상태 전이

### (1) Lockless Fast Path
Per-CPU 포인터 `c->freelist`가 가리키는 객체는 오직 해당 CPU만 접근하므로 스핀락이나 뮤텍스가 일체 필요 없습니다:
1. `void *object = c->freelist;`
2. `c->freelist = get_freelist_ptr(s, object);`
3. `return object;`

### (2) Multi-Tier Slow Path
로컬 프리리스트가 고갈되었을 때만 커널은 단계별 탐색을 시작합니다:
- **Tier 1 (page_freelist)**: 다른 코어가 활성 슬랩에 반환해 둔 객체를 수거 (`cmpxchg_double`로 스왑).
- **Tier 2 (Node Partial)**: NUMA 노드의 `partial` 리스트에서 이미 생성된 슬랩을 가져와 활성 슬랩으로 승격.
- **Tier 3 (Buddy Allocator)**: `alloc_pages()`를 호출하여 신규 물리 페이지를 할당받고 슬랩으로 초기화.

---

## 3. Hardened Freelist와 보안 방어 기제

메모리 오염 공격(Heap Overflow, Use-After-Free)의 고전적 기법은 유휴 객체 내부의 `next` 포인터를 임의의 주소로 조작하여 다음 `kmalloc()` 호출 시 해커가 원하는 위치를 덮어쓰는 것입니다.

리눅스 커널의 `CONFIG_SLAB_FREELIST_HARDENED`는 이를 원천 봉쇄합니다:
$$\text{ptr} = \text{encoded} \oplus \text{cookie} \oplus \text{addr}$$
- 부팅 시 생성된 64비트 랜덤 비밀키(`cookie`)와 해당 객체의 고유 물리 주소(`addr`)를 결합하므로, 공격자가 힙 주소를 완전히 leak하지 못하면 유효한 포인터를 위조할 수 없습니다.
- 복호화된 포인터가 슬랩 페이지 범위를 벗어나거나 비정렬 상태일 경우 커널은 즉시 시스템을 패닉 시킵니다.
