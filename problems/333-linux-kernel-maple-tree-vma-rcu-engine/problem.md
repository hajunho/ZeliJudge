# Linux Kernel Maple Tree (v6.1+) Range-based B-Tree VMA Tracking & Lockless RCU 엔진

## 문제 설명

리눅스 커널에서 프로세스의 가상 주소 공간(`struct mm_struct`)을 구성하는 가상 메모리 영역(Virtual Memory Area, VMA)은 1997년 커널 2.1부터 25년 동안 **Red-Black Tree (`mm->mm_rb`)**와 **단일 연결 리스트(`mm->mmap`)**라는 듀얼 데이터 구조로 관리되어 왔습니다.

그러나 멀티코어 서버와 테라바이트급 메모리 환경이 보편화되면서 이 고전적 구조는 치명적인 병목점을 드러냈습니다:
1. **`mmap_lock` (구 `mmap_sem`) 락 경합**:
   - R-B Tree는 노드 회전(Rotation) 시 부모/자식 포인터가 변경되므로 RCU(Read-Copy Update) 락리스 조회가 불가능합니다.
   - 수십 개의 스레드가 동시에 페이지 폴트(#PF)를 일으킬 때, 각 스레드는 주소에 매핑된 VMA를 찾기 위해 `mmap_lock` 읽기 락을 획득해야 하며, 단 하나의 스레드가 `mmap()`/`munmap()`으로 쓰기 락을 잡는 순간 모든 스레드가 수 밀리초 동안 멈추는 레이턴시 절벽이 발생합니다.
2. **캐시 라인 미스 및 연결 리스트 순회 비효율**:
   - 가상 메모리 범위 순회 시 연결 리스트의 다음 포인터를 따라가느라 L1/L2 캐시 미스가 폭증했습니다.

리눅스 커널 6.1에서 리암 하울릿(Liam Howlett)과 매튜 윌콕스(Matthew Wilcox)는 R-B Tree와 연결 리스트를 완전히 제거하고, 가상 메모리 영역을 구간(Interval) 단위로 관리하는 최신 B-Tree 변형인 **메이플 트리 (Maple Tree: `lib/maple_tree.c`)**를 커널 메인라인에 정식 도입했습니다:

1. **구간 기반 B-Tree (Range-based B-Tree)**:
   - 각 노드는 피벗(Pivot, 상한 주소)과 슬롯(Slot, 자식 노드 또는 VMA 포인터)을 캐시 라인(64바이트 또는 256바이트) 크기로 묶어 관리합니다.
   - `[start, end]` 범위를 단일 엔트리로 저장하여 메모리 조각화를 방지합니다.
2. **락리스 RCU 읽기 지원 (Lockless RCU Readers: `rcu_read_lock()`)**:
   - 트리가 갱신되거나 분할(Split)될 때 기존 노드를 직접 수정하지 않고 섀도 복사본을 만들어 원자적으로 포인터를 교체(`rcu_assign_pointer`)합니다.
   - 따라서 읽기 스레드는 `mmap_lock` 없이 RCU 읽기 잠금만으로 `mas_find()` 및 `mas_walk()`를 수행할 수 있습니다.
3. **동적 분할(Split) 및 클리핑(Clipping)**:
   - 노드 용량을 초과하면 B-트리 규칙에 따라 노드가 좌우로 분할되며 부모 노드로 피벗이 승격됩니다.
   - 기존 VMA의 일부분을 덮어쓰거나 해제(`munmap`)하면 VMA가 좌우로 분절되고 피벗이 재정렬됩니다.

당신은 리눅스 커널 메모리 관리(MM) 서브시스템 엔지니어로서, **리눅스 6.1+ `lib/maple_tree.c`, `include/linux/maple_tree.h`, `mm/mmap.c`에 기반한 메이플 트리 VMA 상태 머신 시뮬레이션 엔진**을 구현해야 합니다.

```
+-------------------------------------------------------------------------+
|      Linux Kernel 6.1+ Maple Tree (Range-based B-Tree) VMA Engine       |
+-------------------------------------------------------------------------+
| [Root Node (Branch / Leaf)]                                             |
|   - Pivots: [0x2FFF, 0x4FFF, 0x7FFF] (Upper address boundaries)         |
|   - Slots:  [Node 0 / VMA 0, Node 1 / VMA 1, ...]                       |
+------------------------------------+------------------------------------+
                                     |
             +-----------------------+-----------------------+
             v                                               v
+-----------------------------+               +-----------------------------+
| Leaf Node 0 (Pivots: ...)   |               | Leaf Node 1 (Pivots: ...)   |
| Slots: [VMA A, VMA B]       |               | Slots: [VMA C, VMA D]       |
+-----------------------------+               +-----------------------------+
   (0x1000..0x2FFF: /bin/app)                    (0x5000..0x7FFF: [heap])

[Operations]
- mas_walk(addr): Lockless RCU point lookup -> O(log_B N)
- mas_find(start, end): Range query across intervals
- mas_store(start, end, vma): B-Tree node split & pivot promotion
- mas_erase(start, end): Range unmapping & boundary VMA clipping
```

---

## 엔진 규격 및 수리적 모델링

### 1. 초기화 (`INIT`)
- `max_capacity`: 단일 메이플 노드가 가질 수 있는 최대 슬롯/피벗 수 $B$ (예: 2, 4, 8).

### 2. VMA 등록 (`STORE_VMA`)
- 입력: `start` (시작 주소), `end` (끝 주소, 포함), `vma_id` (문자열 식별자), `flags` (리스트, 예: `["READ", "WRITE", "EXEC"]`), `name` (문자열)
- 동작:
  - 기존 등록된 VMA들과 `[start, end]` 범위가 겹치면:
    - 겹치는 부분은 새로 등록되는 VMA로 대체됩니다.
    - 기존 VMA의 왼쪽(`s < start`)이 남으면 `[s, start - 1]` 구간으로 축소 보존.
    - 기존 VMA의 오른쪽(`e > end`)이 남으면 `[end + 1, e]` 구간으로 축소 보존.
  - 새 VMA 엔트리를 트리에 삽입.
  - 노드의 원소 수가 `max_capacity`를 초과하면 B-트리 분할(Split)을 수행하여 부모 노드를 생성/승격하고 트리의 높이를 증가시킵니다.

### 3. 단일 주소 조회 (`FIND_VMA`)
- 입력: `addr` (가상 주소)
- 동작:
  - 루트 노드부터 피벗을 순차 비교하며 해당 주소를 포함하는 슬롯/자식 노드를 탐색(`mas_walk`).
  - 매핑된 VMA가 존재하면 `FOUND` 및 VMA 정보 반환, 미매핑 영역이면 `NOT_FOUND` 반환.

### 4. 구간 범위 질의 (`RANGE_QUERY`)
- 입력: `start`, `end`
- 동작:
  - `[start, end]` 범위와 1바이트라도 겹치는 모든 VMA 목록을 오름차순으로 반환.

### 5. VMA 해제 (`ERASE_VMA`)
- 입력: `start`, `end`
- 동작:
  - `[start, end]` 범위에 해당하는 가상 메모리를 해제(`munmap`).
  - 걸쳐 있는 VMA는 경계에 맞춰 클리핑되며, 완전히 포함되는 VMA는 삭제됩니다.
  - 해제된 바이트 수(`bytes_unmapped`)와 영향받은 VMA 수(`affected_vmas`) 반환.

### 6. RCU 동시 읽기 시뮬레이션 (`RCU_BATCH_READ`)
- 입력: `addrs` (주소 리스트)
- 동작:
  - 락 경합 없이 순수 RCU 읽기 상태(`rcu_read_lock`)에서 각 주소의 VMA 매핑 여부와 히트 수를 일괄 산출.

### 7. 트리 상태 검사 (`INSPECT_TREE`)
- 트리 높이(`tree_height`), 노드 수(`node_count`), VMA 수(`vma_count`), 총 매핑 바이트 수, 누적 통계 반환.

---

## 입력 형식

표준 입력(stdin)으로 JSON 배열 형태의 명령어 목록이 주어집니다.

```json
[
  {"op": "INIT", "max_capacity": 4},
  {"op": "STORE_VMA", "start": 4096, "end": 12287, "vma_id": "text_segment", "flags": ["READ", "EXEC"], "name": "/bin/app"},
  {"op": "FIND_VMA", "addr": 5000},
  {"op": "INSPECT_TREE"}
]
```

---

## 출력 형식

표준 출력(stdout)으로 각 명령어의 실행 결과를 담은 JSON 배열을 공백 없이 한 줄로 출력합니다.

```json
[{"op":"INIT","status":"OK","max_capacity":4},{"op":"STORE_VMA","result":{"status":"VMA_STORED","vma_id":"text_segment","start":4096,"end":12287,"size":8192}},{"op":"FIND_VMA","result":{"status":"FOUND","addr":5000,"vma":{"vma_id":"text_segment","start":4096,"end":12287,"flags":["READ","EXEC"],"name":"/bin/app","size":8192}}},{"op":"INSPECT_TREE","result":{"tree_height":1,"node_count":1,"vma_count":1,"total_mapped_bytes":8192,"stats":{"total_stores":1,"total_erases":0,"total_lookups":1,"rcu_reads_count":0}}}]
```

---

## 제약 사항

- 가상 주소 범위: $0 \le start \le end < 2^{48}$ (x86_64 48비트 가상 주소 공간)
- 노드 최대 용량 $B \in \{2, 4, 8, 16\}$
- 명령어 수 $M \le 10,000$
- 시간 제한: 5.0초
- 메모리 제한: 512MB
