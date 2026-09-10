# 400: 리눅스 커널 메모리 관리 — Maple Tree(RCU-Safe B-Tree VMA 할당자) 주소 공간 범위 인덱싱 및 무잠금 탐색 엔진

## 1. 개요 (Overview)

리눅스 커널에서 프로세스의 가상 주소 공간은 코드, 데이터, 힙, 스레드 스택, 메모리 매핑 파일 등 수많은 **가상 메모리 영역(VMA: Virtual Memory Area, `struct vm_area_struct`)** 들로 구성됩니다. 지난 25년 이상(리눅스 2.6부터 6.0까지) 커널은 이 VMA들을 관리하기 위해 **레드-블랙 트리(Red-Black Tree, `rb_node`)와 이중 연결 리스트(Doubly Linked List)** 의 조합을 사용해 왔습니다.

그러나 멀티코어 서버 환경에서 이 전통적인 구조는 치명적인 한계에 봉착했습니다:
1. **전역 락 병목 (`mmap_lock`)**: 레드-블랙 트리는 노드 삽입/삭제 시 발생하는 트리 회전(Rotation)으로 인해 여러 포인터가 동시에 변경되므로, **RCU(Read-Copy Update) 무잠금 병행 순회가 불가능**했습니다. 그 결과 수백 개의 스레드가 페이지 폴트를 처리할 때마다 전역 `mmap_lock` 세마포어를 획득해야 해 극심한 락 경합이 발생했습니다.
2. **범위 검색의 비효율**: 겹치지 않는 연속된 주소 범위(`[vm_start, vm_end)`)를 표현하는 데 레드-블랙 트리는 점(Point) 중심 인덱싱이어서 비효율적이었습니다.

오라클의 리암 하울렛(Liam Howlett)과 매튜 윌콕스(Matthew Wilcox)가 설계하여 **리눅스 커널 6.1에 공식 도입된 Maple Tree (`lib/maple_tree.c`)** 는 비중복 범위 인덱싱에 특화된 혁신적인 **RCU-Safe B-Tree** 변형체입니다.
Maple Tree는 64바이트/256바이트 캐시라인 정렬 노드 구조와 피벗(Pivots) 배열을 기반으로:
- `rcu_read_lock()` 하에서 락 없이 고속 범위 탐색(`mas_walk`, `mas_find`)을 수행하고,
- 리눅스 6.4+에서 도입된 **Per-VMA Lock (`vma->vm_lock`)** 의 기술적 기반이 되어 멀티스레드 동시 페이지 폴트 성능을 수배 이상 향상시켰습니다.

본 문제에서는 리눅스 커널 Maple Tree의 범위 삽입(`mmap`), 범위 분할/천공(`munmap` 및 VMA Splitting), RCU 무잠금 단일 주소 탐색(`mas_walk`), 빈 가상 주소 공간 탐색(`mas_find_gap`) 엔진을 설계 및 구현합니다.

---

## 2. Maple Tree VMA 아키텍처 다이어그램

```
+========================================================================================+
|                       Process Virtual Address Space [0x00000000, ...)                  |
|                                                                                        |
|  +--------------------+      +--------------------+      +--------------------------+  |
|  | VMA 0: Text        |      | VMA 1: Heap        |      | VMA 2: Stack             |  |
|  | [0x00010000, 14000)|      | [0x00020000, 24000)|      | [0x7f000000, 7f020000)   |  |
|  +--------------------+      +--------------------+      +--------------------------+  |
+========================================================================================+
                                            ||
                                            VV
+========================================================================================+
|                        Maple Tree (RCU-Safe Range B-Tree Node)                         |
|                                                                                        |
|   Pivots Array:  [ 0x00014000,   0x00024000,   0x7f020000,   ULONG_MAX ]               |
|   Slots Array:   [ &VMA_Text,    &VMA_Heap,    &VMA_Stack,   NULL      ]               |
+========================================================================================+
        ||                                  ||                                ||
        || (RCU Lockless Walk: mas_walk)    || (Range Erase: munmap)          || (Find Gap)
        VV                                  VV                                VV
[ Zero-Lock Point Lookup ]       [ Mid-Range Split / Truncate ]     [ Search Unmapped Space ]
- do_page_fault() reads VMA      - Unmap middle of VMA ->           - Find first free hole
  without taking mmap_lock!        Splits VMA into 2 pieces!          with size >= requested
```

---

## 3. 핵심 수리 및 알고리즘 규칙

### 3.1 범위 불변식 및 중복 배제 (Non-overlapping Invariant)
모든 VMA $V_i = [	ext{start}_i, 	ext{end}_i)$는 상호 겹치지 않아야 합니다:
$$orall i 
e j: \quad (	ext{end}_i \le 	ext{start}_j) \lor (	ext{start}_i \ge 	ext{end}_j)$$
새로운 영역 매핑(`MMAP`) 시 기존 VMA와 충돌이 발생하면 `ERROR_OVERLAP`과 충돌 VMA 정보를 반환합니다.

### 3.2 범위 분할 및 천공 (`MUNMAP`)
해제 범위 $[S, E)$에 대해 교차하는 VMA $V$는 다음과 같이 분할/절단됩니다:
1. **완전 포함 ($V \subseteq [S, E)$)**: $V$가 트리에서 완전히 제거됩니다.
2. **중간 천공 ($V.	ext{start} < S 	ext{ and } V.	ext{end} > E$)**:
   $V$가 2개의 독립된 VMA $[V.	ext{start}, S)$와 $[E, V.	ext{end})$로 분할됩니다 (`VMA Splitting`).
3. **좌측 절단 ($V.	ext{start} < S 	ext{ and } V.	ext{end} \le E$)**: $[V.	ext{start}, S)$로 우측 끝이 축소됩니다.
4. **우측 절단 ($V.	ext{start} \ge S 	ext{ and } V.	ext{end} > E$)**: $[E, V.	ext{end})$로 좌측 시작이 이동됩니다.

### 3.3 무잠금 단일 주소 탐색 (`MAS_WALK`)
주어진 가상 주소 $A$에 대해:
$$V.	ext{start} \le A < V.	ext{end}$$
를 만족하는 유일한 VMA를 탐색합니다. 존재하면 `FOUND`, 없으면 `NOT_FOUND`를 반환하며, 탐색 시마다 `rcu_reads` 카운터를 증가시킵니다.

### 3.4 여유 주소 공간 탐색 (`FIND_GAP`)
요청 크기 $Z$에 대해 $[	ext{min\_addr}, 	ext{max\_addr}]$ 범위 내에서 다른 VMA와 겹치지 않는 가장 낮은 시작 주소 $G$를 탐색합니다:
$$	ext{Gap } [G, G+Z) \cap V = \emptyset \quad (orall V \in 	ext{VMAs})$$

---

## 4. 입출력 형식 (I/O Specification)

### 4.1 입력 형식 (Input Format)
```json
{
  "max_slots": 4,
  "operations": [
    {"action": "MMAP", "start": 65536, "end": 81920, "flags": "r-xp", "name": "code"},
    {"action": "MAS_WALK", "addr": 70000},
    {"action": "FIND_GAP", "size": 65536, "min_addr": 65536, "max_addr": 2147483648}
  ]
}
```

### 4.2 출력 형식 (Output Format)
```json
{
  "total_vmas": 1,
  "node_splits": 0,
  "node_merges": 0,
  "rcu_reads": 1,
  "vmas": [
    {
      "start": "0x00010000",
      "end": "0x00014000",
      "size_bytes": 16384,
      "flags": "r-xp",
      "name": "code"
    }
  ],
  "operation_results": [
    {
      "op": "MMAP",
      "status": "SUCCESS",
      "vma": {
        "start": "0x00010000",
        "end": "0x00014000",
        "size_bytes": 16384,
        "flags": "r-xp",
        "name": "code"
      }
    }
  ]
}
```
