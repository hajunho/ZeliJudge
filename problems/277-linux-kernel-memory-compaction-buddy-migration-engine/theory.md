# 리눅스 커널 메모리 컴팩션(Memory Compaction)과 버디 할당자(Buddy Allocator) 이론

## 1. 물리 메모리 외부 단편화(External Fragmentation) 문제
현대 리눅스 운영체제는 가상 메모리(Virtual Memory)의 연속성을 MMU(페이징 유닛)를 통해 지원하지만, 다음과 같은 시나리오에서는 **물리적으로 연속된 수 메가바이트의 메모리 버퍼**가 절대적으로 필요합니다:
1. **2MB / 1GB 대형 페이지(Transparent Huge Pages, THP)**: TLB(Translation Lookaside Buffer) 미스 오버헤드를 줄여 데이터베이스와 AI 워크로드 성능을 수십 % 향상.
2. **디바이스 드라이버 DMA 버퍼**: Scatter-Gather 기능을 지원하지 않는 구형 하드웨어 또는 대규모 고속 RDMA 링 버퍼.
3. **네트워크 점보 프레임(Jumbo Frames)** 수신 버퍼.

오랜 시간 시스템이 기동되면 4KB(order-0) 페이지들이 체스판처럼 분산되어 고위수(High-Order) 연속 블록이 전멸하게 되며, 이를 해결하기 위해 전통적으로는 디스크 스왑을 동반한 강제 페이지 회수(`page reclaim / kswapd`)를 시도했으나 심각한 I/O 스톨(Latency Spike)을 유발했습니다.

---

## 2. 듀얼 스캐너 컴팩션(Dual-Scanner Compaction) 아키텍처
리눅스 커널(`mm/compaction.c`)의 메모리 컴팩션은 디스크 I/O 없이 순수 RAM 내부의 복사(Memory-to-Memory Copy)만으로 연속된 공간을 창출하는 혁신적인 기법입니다.

```
Zone Start (Low PFN)                                           Zone End (High PFN)
+--------------------------------------------------------------------------------+
| Pageblock 0 (MOVABLE)  | Pageblock 1 (UNMOVABLE) | Pageblock 2 (MOVABLE)       |
| [1, 0, 1, 0, 1, 0...]  | [2, 2, 2, 2, 2, 2...]   | [0, 1, 0, 0, 0, 0...]       |
+--------------------------------------------------------------------------------+
       |                                                               |
  [Migrate Scanner] ->                                       <- [Free Scanner]
  (Scans upward for movable pages)                 (Scans downward for free slots)
```

1. **마이그레이션 스캐너 (`migrate_pfn`)**:
   - 존의 시작점(`zone_start_pfn`)에서 시작하여 높은 주소 방향으로 스캔.
   - `MIGRATE_UNMOVABLE`로 지정된 페이지블록을 만나면 페이지 단위가 아닌 **페이지블록(`pageblock_nr_pages`) 단위**로 한 번에 건너뛰어 스캔 효율을 극대화합니다.
   - 이동 가능한 페이지를 만나면 이동 소스로 격리합니다.
2. **유휴 스캐너 (`free_pfn`)**:
   - 존의 끝점(`zone_end_pfn`)에서 시작하여 낮은 주소 방향으로 스캔.
   - 비어 있는 `PAGE_FREE` 슬롯을 찾아 이동 목적지로 지정합니다.
3. **수렴 및 조기 종료(Early Exit)**:
   - 두 스캐너가 서로 마주칠 때까지(`migrate_pfn >= free_pfn`) 진행됩니다.
   - 단, 중간에 요청된 order-$K$ 크기의 자연 정렬(`pfn % (1 << K) == 0`)된 버디 블록이 형성되는 즉시 루프를 중단하여 불필요한 메모리 복사 오버헤드를 억제합니다.

---

## 3. 페이지블록 이동성 그룹화(Grouping by Mobility)
리눅스 커널은 외부 단편화를 근본적으로 억제하기 위해 페이지블록마다 `migratetype`을 지정합니다:
- `MIGRATE_MOVABLE`: 유저 공간 프로세스의 힙, 스택, 무명 페이지(Anonymous Memory) 및 페이지 캐시. 가상 메모리 매핑 테이블(PTE)만 업데이트하면 물리 주소를 언제든 자유롭게 이전할 수 있습니다.
- `MIGRATE_RECLAIMABLE`: 디렉터리 엔트리(dentry), inode 캐시 등 필요 시 즉시 해제 가능한 슬랩.
- `MIGRATE_UNMOVABLE`: 커널 코드 영역, 하드웨어 페이지 테이블(PGD/PUD/PMD), DMA 버퍼 등 주소가 고정되어 이전이 불가능한 메모리. 컴팩션 스캐너는 이 영역을 침범할 수 없습니다.

---

## 4. 실무 성능 튜닝 및 부작용 방지
1. **워터마크 보존 (`min_watermark_pages`)**:
   컴팩션 과정 자체도 페이지 디스크립터 할당 등을 위해 최소한의 여유 메모리가 필요합니다. 워터마크 이하로 여유 메모리가 떨어지면 컴팩션을 시도하는 대신 직접 회수(Direct Reclaim)로 전환해야 합니다.
2. **단편화 지수 (`sysctl_extfrag_threshold`)**:
   커널은 단편화 지수가 임계값(기본 500)을 초과할 때만 kcompactd 데몬을 기동하여 CPU 사이클 낭비를 방지합니다.
