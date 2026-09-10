# 이론적 배경: LSM-Tree 레벨드 컴팩션과 톰스톤 생명주기 관리

## 1. B-Tree vs LSM-Tree 아키텍처 비교

전통적인 RDBMS(MySQL InnoDB, PostgreSQL)의 저장 구조인 **B+Tree**는 페이지(Page) 단위로 제자리 갱신(In-Place Update)을 수행합니다.
- **장점**: 포인트 쿼리 시 정확히 해당 키가 위치한 리프 노드 페이지만 읽으면 되므로 읽기 지연이 매우 낮음 ($O(\log_B N)$).
- **단점**: 쓰기 발생 시 디스크의 무작위 위치에 페이지를 기록(Random I/O)해야 하므로 쓰기 처리량(Throughput)이 하드웨어 한계에 부딪힘.

1996년 패트릭 오닐(Patrick O'Neil) 등이 제안한 **LSM-Tree (Log-Structured Merge-tree)**는 쓰기를 절대 제자리에서 수정하지 않고, 메모리의 MemTable(Skiplist 또는 Red-Black Tree)에 순차 기록한 뒤 주기적으로 불변의 SSTable로 디스크에 추가(Append-Only)합니다.

| 비교 항목 | B+ Tree | LSM-Tree (Leveled Compaction) |
| :--- | :--- | :--- |
| **쓰기 패턴** | 랜덤 I/O (In-Place Page Overwrite) | 순차 I/O (Append-only SSTable Flush) |
| **쓰기 처리량** | 낮음 ~ 보통 | 극도로 높음 (10배~100배) |
| **읽기 증폭 (RA)** | 매우 낮음 (1~3회 페이지 I/O) | 보통 ~ 높음 (블룸필터 없을 시 여러 레벨 탐색) |
| **공간 증폭 (SA)** | 보통 (페이지 단편화 30~50%) | 낮음 (레벨드 컴팩션 시 10~20%) |
| **쓰기 증폭 (WA)** | 낮음 ~ 보통 (WAL + 더티 페이지) | 높음 (컴팩션으로 인해 동일 데이터 반복 기록) |

---

## 2. 레벨드 컴팩션 (Leveled Compaction)의 메커니즘

RocksDB와 LevelDB의 기본 컴팩션 모드인 **Leveled Compaction**은 계층마다 데이터 크기를 기하급수적으로 증가시키는 다단계 구조를 채택합니다 ($L_i = L_1 \times T^{i-1}$, 보통 $T = 10$).

```
[ MemTable (RAM) ]
       | Flush
       v
Level 0: [ SST-1 (k1..k9) ] [ SST-2 (k3..k7) ] [ SST-3 (k2..k8) ]  <-- Overlapping Allowed!
       |
       | Compaction (All L0 files + Overlapping L1 files)
       v
Level 1: [ SST-4 (a..f) ] [ SST-5 (g..m) ] [ SST-6 (n..z) ]        <-- Non-Overlapping!
       |
       | Compaction (Pick 1 L1 file + Overlapping L2 files)
       v
Level 2: [ SST-7 (a..c) ] [ SST-8 (d..h) ] [ SST-9 (i..p) ] ...   <-- Non-Overlapping!
```

### 왜 Level 1 이상에서는 키 범위가 겹치지 않아야 하는가?
- $L_0$은 메모리에서 즉시 덤프되므로 파일 간에 키가 겹칠 수밖에 없습니다. 따라서 $L_0$에서 키를 찾으려면 최악의 경우 모든 $L_0$ 파일을 다 뒤져야 합니다.
- 반면 $L_1$ 이상의 레벨에서는 SSTable 간 키가 완벽히 정렬 및 분할되어 있으므로, 레벨당 최대 **단 1개의 파일**만 이진 탐색(Binary Search)하면 키의 존재 여부를 즉시 확정할 수 있습니다. 이것이 읽기 성능을 비약적으로 개선합니다.

---

## 3. 톰스톤(Tombstone)과 유령 부활(Phantom Resurrection) 방지

LSM-Tree는 불변 파일 구조이므로 데이터를 삭제할 때 디스크의 이전 파일을 열어서 지우지 않습니다. 대신 **"이 키는 삭제되었음"**을 나타내는 특별한 마커인 **톰스톤(Tombstone)**을 최신 시퀀스 번호로 기록합니다.

### 톰스톤 제거의 위험성 (The Tombstone Purge Trap)
- 만약 $L_1$ 컴팩션 중에 어떤 키의 톰스톤을 발견하고, "어차피 삭제된 키니까 파일 용량을 아끼기 위해 새 SSTable에서 빼버리자!"라고 성급히 제거하면 어떻게 될까요?
- 만약 $L_2$나 $L_3$에 과거에 기록되었던 동일한 키의 유효 데이터가 남아있다면, 상위 레벨의 톰스톤이 사라짐으로써 하위 레벨의 옛날 데이터가 다시 노출되는 **유령 데이터 부활(Phantom Resurrection)** 참사가 발생합니다.
- **안전한 제거 규칙 (Bottommost Purge Rule)**:
  - 톰스톤은 대상 레벨 $L_{\text{tgt}}$보다 더 깊은 모든 레벨($L > L_{\text{tgt}}$)에 해당 키가 **단 하나도 존재하지 않을 때에만** 디스크에서 완전히 영구 소멸(Purge)시킬 수 있습니다.

---

## 4. 쓰기 증폭(Write Amplification)과 I/O 경제학

LSM-Tree의 가장 큰 대가는 **쓰기 증폭(Write Amplification)**입니다.
사용자가 1바이트를 쓸 때, 컴팩션 프로세스가 상위 레벨과 하위 레벨의 파일들을 반복적으로 읽고 다시 쓰면서 실제 디스크에는 $10 \sim 30$배 이상의 바이트가 기록됩니다.
- 레벨 비율이 $T$일 때, 한 레벨에서 다음 레벨로 넘어갈 때마다 약 $T$배의 데이터가 다시 쓰여집니다.
- 총 $L$개의 레벨을 통과하는 경우 이론적 쓰기 증폭은 $O(T \times L)$에 달합니다.
- SSD의 플래시 메모리는 쓰기 횟수가 유한하므로(P/E Cycle), 과도한 쓰기 증폭은 SSD의 수명을 단축시키고 스토리지 I/O 대역폭을 고갈시킵니다. 따라서 RocksDB 등은 동적 레벨 베이스 크기 조정(Dynamic Level Base Sizing)이나 유니버설 컴팩션(Universal Compaction) 등을 통해 쓰기 증폭을 최적화합니다.
