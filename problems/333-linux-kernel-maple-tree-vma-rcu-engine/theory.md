# Linux Kernel Maple Tree (v6.1+) Range-based B-Tree VMA Tracking & Lockless RCU 심층 이론

## 1. 개요: 25년 만의 리눅스 가상 메모리 관리(VMA) 대변혁

1997년 리눅스 커널 2.1 시절부터 프로세스의 가상 메모리 공간(`struct mm_struct`) 내 모든 가상 메모리 영역(VMA, `struct vm_area_struct`)은 다음 두 자료구조의 결합으로 관리되었습니다:
1. **레드-블랙 트리 (Red-Black Tree, `mm->mm_rb`)**:
   - 가상 주소 기반 $O(\log N)$ 검색을 위한 자가 균형 이진 탐색 트리.
2. **단일 연결 리스트 (Singly-Linked List, `mm->mmap`)**:
   - 메모리 주소 순서대로 정렬된 선형 순회를 위한 연결 리스트.

### 고전적 R-B Tree 아키텍처의 한계
- **`mmap_lock` 락 경합 (Lock Contention)**:
  - R-B Tree는 노드 삽입/삭제 시 피벗 회전(Rotation)을 수행하며, 이 과정에서 부모와 자식 노드의 포인터가 일시적으로 불일치 상태가 됩니다.
  - 따라서 RCU(Read-Copy Update) 메커니즘을 통한 락리스 조회가 원천적으로 불가능했습니다.
  - 멀티스레드 애플리케이션에서 수많은 스레드가 동시에 페이지 폴트(#PF)를 일으킬 때, 각 스레드는 VMA를 찾기 위해 `mmap_lock` 읽기 락을 획득해야 했습니다. 쓰기 작업(`mmap`, `munmap`, `mprotect`)이 발생하면 전역 락 대기로 인해 모든 스레드가 멈추는 **확장성 절벽(Scalability Cliff)**이 발생했습니다.
- **캐시 지역성 부족**:
  - 이진 트리의 포인터를 따라가는 방식은 CPU L1/L2 캐시 라인을 비효율적으로 낭비했습니다.

리눅스 커널 6.1에서 오라클의 리암 하울릿(Liam Howlett)과 매튜 윌콕스(Matthew Wilcox)는 **메이플 트리 (Maple Tree: `lib/maple_tree.c`)**를 설계하여 R-B Tree와 연결 리스트를 완전히 대체했습니다.

---

## 2. 메이플 트리 아키텍처 및 노드 레이아웃

메이플 트리는 **범위/구간(Interval/Range)을 직접 저장하도록 최적화된 B-Tree 변형**입니다:

```c
struct maple_tree {
    spinlock_t ma_lock;
    unsigned int ma_flags;
    void __rcu *ma_root;
};

struct ma_state {
    struct maple_tree *tree;
    unsigned long index;  /* Start of range */
    unsigned long last;   /* End of range */
    struct maple_node *node;
    ...
};
```

### 캐시 라인 크기 노드 (B-Tree Node Sizing)
- 메이플 트리의 노드는 아키텍처 캐시 라인(일반적으로 64바이트 또는 256바이트)에 정확히 들어맞도록 패킹됩니다:
  - **`maple_range_64` (브랜치 노드)**: 최대 15개의 피벗(상한 주소)과 16개의 자식 노드 슬롯.
  - **`maple_arange_64` (리프/할당 노드)**: 연속된 가상 메모리 홀(Gap)과 할당 정보를 추적.
- 단일 노드 안에서 이진 탐색 대신 CPU 벡터 명령어나 순차 비교를 통해 캐시 미스를 최소화합니다.

---

## 3. 락리스 RCU 읽기 (Lockless RCU Readers) 메커니즘

메이플 트리가 R-B Tree 대비 갖는 가장 강력한 혁신은 **RCU 안전성(RCU Safety)**입니다:

1. **Copy-on-Write 섀도 노드 갱신**:
   - VMA가 삽입되거나 삭제될 때, 수정이 필요한 노드를 인플레이스(In-place)로 덮어쓰지 않습니다.
   - 새 노드를 메모리에 복제한 뒤 피벗과 슬롯을 정렬하고, 부모 노드의 포인터를 원자적으로 교체(`rcu_assign_pointer`)합니다.
2. **동시 읽기 스레드의 무중단 순회**:
   - 페이지 폴트를 처리하는 스레드는 `mmap_lock`을 잡지 않고 `rcu_read_lock()` 상태에서 `mas_find()` 또는 `mas_walk()`를 호출합니다.
   - 읽기 도중 트리가 재편되더라도 기존 노드는 RCU 유예 기간(Grace Period) 동안 해제되지 않으므로, 충돌이나 크래시 없이 안전하게 VMA를 조회할 수 있습니다.
   - 이를 통해 리눅스 커널 6.2+에서는 **스펙큘레이티브 페이지 폴트(Speculative Page Faults / Per-VMA Locks)**가 메이플 트리 위에서 완벽히 구동됩니다.

---

## 4. 구간 연산 및 클리핑(Clipping) 로직

가상 메모리는 점(Point)이 아니라 범위(`[vm_start, vm_end]`)입니다:
- **`STORE_VMA` (mmap)**:
  - 새 VMA가 기존 VMA의 일부분과 겹치면, 겹치지 않는 잔여 영역(`[s, start - 1]`, `[end + 1, e]`)으로 기존 VMA를 분할하고 새 VMA를 가운데 삽입합니다.
- **`ERASE_VMA` (munmap)**:
  - 해제 요청된 범위와 겹치는 VMA를 잘라내어(Clipping) 미매핑 홀(Gap)을 형성합니다.
- **구간 질의 (`RANGE_QUERY` / `mas_find`)**:
  - 연결 리스트 없이도 B-트리 리프 노드를 인덱스 순으로 전진하며 $O(K)$ 시간에 겹치는 모든 VMA를 열거합니다.

---

## 5. 커널 소스 코드 매핑

- `lib/maple_tree.c`:
  - `mas_walk()`: 주소 탐색 커서 전진.
  - `mas_store()`: 새 VMA 삽입 및 노드 분할.
  - `mas_erase()`: VMA 삭제 및 홀 병합.
- `include/linux/maple_tree.h`:
  - `struct maple_tree`, `struct maple_node`, `struct ma_state` 정의.
- `mm/mmap.c`:
  - `vma_mas_store()`, `find_vma()`, `do_vmi_align_munmap()`: VMA 할당 및 해제 시 메이플 트리 인터페이스 호출.
