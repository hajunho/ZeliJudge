# 문제 250: Linux Kernel Memory — 버디 할당자 외부 단편화, Direct Compaction CPU 잠식 vs kcompactd 선제적 컴팩션 및 Pageblock 격리

## 1. 개요 (Incident Scenario)

초고성능 인메모리 데이터베이스(SAP HANA, Redis, In-Memory Feature Store) 및 대규모 AI 추론 클러스터에서는 메모리 접근 지연 시간을 최소화하고 TLB(Translation Lookaside Buffer) 미스율을 극적으로 낮추기 위해 **2MB Transparent HugePage(THP, Order-9)**를 광범위하게 활용합니다. 리눅스 커널의 버디 할당자(Buddy Allocator)는 $2^0(4	ext{KB})$부터 $2^{10}(4	ext{MB})$까지 연속된 2의 거듭제곱 크기의 물리 페이지 프레임(PFN) 단위로 메모리를 관리합니다.

그러나 서버가 수 주 동안 가동된 후, 시스템에 총 50% 이상의 여유 메모리(`free_ram_mb`)가 충분히 남아있음에도 불구하고 치명적인 성능 저하 및 정지(Freeze) 현상이 발생했습니다:
1. **동기식 Direct Compaction CPU 락업 (p99 Latency Explosion)**: 새로운 대형 쿼리나 AI 배치 작업이 2MB 거대 페이지를 할당받으려 할 때, 연속된 512개의 4KB 페이지(Order-9 블록)가 존재하지 않았습니다. 커널 설정이 `transparent_hugepage/defrag = always`로 되어 있어 할당 요청 스레드가 즉시 동기식 메모리 압축(**Direct Compaction**, `compact_zone`) 루프로 진입했습니다. 양방향 스캐너(`migrate_scanner`, `free_scanner`)가 물리 메모리 영역 전체를 뒤지며 수십만 개의 페이지를 강제 이동시키고 전 코어에 TLB Flush IPI 인터럽트를 난사하여, 커널 모드 CPU(`%sys`)가 100%를 치고 요청 지연 시간이 수 초 이상 멈췄습니다.
2. **이동 불가(Unmovable) 슬랩에 의한 Pageblock 오염 및 컴팩션 실패**: 커널 `min_free_kbytes`가 너무 낮게 설정된 상태에서 네트워크 소켓 버퍼(`sk_buff`) 및 덴트리/아이노드 슬랩 캐시가 폭증하자, 커널의 이동 불가(`MIGRATE_UNMOVABLE`) 할당이 사용자 이동 가능(`MIGRATE_MOVABLE`) 페이지블록으로 침범(Fallback Allocation)했습니다. 2MB 크기의 페이지블록에 단 하나의 4KB 언무버블 슬랩 객체만 박혀 있어도 해당 2MB 영역은 압축이 불가능해져, 컴팩션 시도가 전부 실패(`unmovable_pin_failures`)하고 4KB 페이지 분할로 폴백되었습니다.
3. **선제적 컴팩션(Proactive Compaction) 과다 튜닝으로 인한 백그라운드 CPU 고갈**: 리눅스 5.x의 백그라운드 데몬인 `kcompactd`를 활성화했으나, 운영팀이 `vm.compaction_proactiveness`를 95 이상으로 과도하게 높게 설정하여 단편화가 거의 없는 평상시에도 데몬이 끝없이 메모리를 뒤적거리며 백그라운드 CPU를 낭비했습니다.

당신은 리눅스 커널 메모리 관리 서브시스템 엔지니어로서, 커널 구성, 초기 메모리 단편화 점수, 오염된 페이지블록 수, 가용 Order-9 블록 수, 그리고 메모리 할당/슬랩 이벤트 스트림을 바탕으로 버디 할당자, Direct Compaction, kcompactd 및 Pageblock 격리 상태 머신을 정확하게 시뮬레이션하고, 장애 원인(Root Cause)과 최적의 커널 튜닝 방안을 도출해야 합니다.

---

## 2. 아키텍처 및 상태 머신 (System Architecture & State Machine)

```
 [ Buddy Allocator: Zone Normal (Free RAM: 16GB) ]
 
  Order 0 (4KB) : [P][P][P][P][P][P]... (Millions of isolated pages)
  Order 9 (2MB) : [NONE AVAILABLE!] <── External Fragmentation High (80%)
 
 ══════════════════════════════════════════════════════════════════════
 
  [ Allocation Request: 2MB Order-9 ]
                │
                ├─► Order-9 Free Block available? ──► YES ──► Allocate instantly!
                │
                ▼ NO
  [ Check thp_defrag_policy ]
   ├─► "never"  ──► Fallback to 4KB (Allocation Failure)
   ├─► "defer"  ──► Wake up kcompactd in background, Fallback to 4KB (Zero Stall!)
   └─► "always" ──► Synchronous DIRECT COMPACTION!
                           │
       ┌───────────────────┴───────────────────┐
       ▼                                       ▼
  [ Unmovable Pageblock Contaminated? ]    [ Clean Movable Blocks ]
  (unmovable_blocks > 100)                 Two-Pointer Memory Compaction:
  Compaction IMPOSSIBLE!                   - migrate_scanner (PFN Low -> High)
  ==> thp_allocation_failures += 1         - free_scanner    (PFN High -> Low)
                                           ==> Direct Compaction Stall!
                                               CPU 100% sys, p99 > 2s!
```

### (1) 메모리 단편화 및 kcompactd 동작 규칙
- 커널의 외부 단편화 지수: `extfrag_score` ($0 \sim 100$).
- 백그라운드 `kcompactd` 기동 임계치:
  $$	ext{threshold} = 100 - 	ext{compaction\_proactiveness}$$
- `kcompactd` 동작:
  - `proactiveness == 0`: 백그라운드 선제적 컴팩션 완전 비활성화.
  - `proactiveness > 80`: 단편화가 적어도 지속적으로 동작하여 **`kcompactd_cpu_thrashing = true`** 유발.
  - `extfrag_score > threshold`일 때: 단편화 점수를 감소시키고 새로운 Order-9 2MB 블록을 생성:
    $$	ext{reduction} = \min(	ext{extfrag\_score}, 	ext{proactiveness})$$
    $$	ext{new\_blocks} = \lfloor 	ext{reduction} 	imes (	ext{free\_ram\_mb} // 2) / 100 floor$$

### (2) Order-9 할당 및 Direct Compaction 규칙
- `free_order9_blocks > 0`이면 블록을 1개 차감하고 즉시 성공.
- 블록이 0개일 때:
  - `thp_defrag_policy == "never"`: 즉시 실패 (`thp_allocation_failures += 1`).
  - `unmovable_contaminated_blocks > 100`: 이동 불가 페이지가 페이지블록을 고정(Pinning)하고 있으므로 컴팩션이 불가능하여 `unmovable_pin_failures += 1`, `thp_allocation_failures += 1`.
  - `thp_defrag_policy == "defer"`: 백그라운드로 `run_kcompactd()`를 깨우고 현재 요청은 동기식 지연 없이 4KB로 폴백 (`thp_allocation_failures += 1`, `direct_compaction_stalls`는 발생하지 않음).
  - `thp_defrag_policy == "always"`: **동기식 Direct Compaction 강제 수행** (`direct_compaction_stalls += 1`). 단편화 점수가 완화되지만 큰 레이턴시 스파이크가 발생함.

### (3) 이동 불가(Unmovable) 슬랩 폭증 및 Pageblock 오염 규칙
- `KERNEL_SLAB_BURST`:
  - `unmovable_isolation_enabled == false`이거나 `min_free_kbytes_mb < 256`인 경우:
    - 커널 여유 공간 부족으로 인해 `MIGRATE_UNMOVABLE` 할당이 `MIGRATE_MOVABLE` 페이지블록으로 넘쳐흘러 오염 발생:
      $$	ext{contaminated} = 	ext{alloc\_mb} // 2$$
      $$	ext{unmovable\_contaminated\_blocks} += 	ext{contaminated}$$
      $$	ext{extfrag\_score} = \min(100, 	ext{extfrag\_score} + 30)$$
- `DROP_CACHES`:
  - 메모리 캐시 및 슬랩 정리로 `unmovable_contaminated_blocks = max(0, unmovable_contaminated_blocks - 50)`, `extfrag_score = max(10, extfrag_score - 20)`.

---

## 3. 입력 사양 (Input Specification)

표준 입력(`sys.stdin`)으로 다음 구조의 JSON 객체가 주어집니다:

```json
{
  "kernel_config": {
    "compaction_proactiveness": 0,
    "thp_defrag_policy": "always",
    "min_free_kbytes_mb": 128,
    "unmovable_isolation_enabled": true
  },
  "initial_state": {
    "total_ram_mb": 32768,
    "free_ram_mb": 16384,
    "external_fragmentation_score": 80,
    "unmovable_contaminated_pageblocks": 0,
    "free_order9_blocks_2mb": 0
  },
  "events": [
    {"time_sec": 1, "type": "ALLOC_HUGEPAGE_ORDER9", "count_2mb": 3}
  ]
}
```

---

## 4. 출력 사양 (Output Specification)

표준 출력(`sys.stdout`)으로 다음 필드를 포함하는 JSON 객체를 출력합니다:

```json
{
  "final_state": {
    "external_fragmentation_score": 25,
    "free_order9_blocks_2mb": 0,
    "unmovable_contaminated_pageblocks": 0
  },
  "metrics": {
    "direct_compaction_stalls": 3,
    "thp_allocation_failures": 0,
    "kcompactd_wakeups": 0,
    "kcompactd_cpu_thrashing": false,
    "unmovable_pin_failures": 0
  },
  "root_cause": "DIRECT_COMPACTION_SYNCHRONOUS_LATENCY_STALL",
  "recommendations": [
    "TUNE_VM_COMPACTION_PROACTIVENESS_TO_RECOMMENDED_RANGE",
    "CHANGE_THP_DEFRAG_TO_DEFER_OR_MADVISE",
    "INCREASE_MIN_FREE_KBYTES_AND_ISOLATE_UNMOVABLE"
  ]
}
```

### 진단 규칙 (Root Cause Hierarchy)
1. `unmovable_pin_failures > 0` $ightarrow$ `"COMPACTION_FAILED_UNMOVABLE_PAGEBLOCK_CONTAMINATION"`
2. `kcompactd_cpu_thrashing == true` $ightarrow$ `"KCOMPACTD_PROACTIVE_OVERTUNED_CPU_THRASHING"`
3. `direct_compaction_stalls >= 2` $ightarrow$ `"DIRECT_COMPACTION_SYNCHRONOUS_LATENCY_STALL"`
4. 기타 정상 상태 $ightarrow$ `"STABLE_EFFICIENT_COMPACTION_AND_ALLOCATION"`

### 권고사항 도출 규칙
- `proactiveness > 80` 또는 `proactiveness == 0`: `"TUNE_VM_COMPACTION_PROACTIVENESS_TO_RECOMMENDED_RANGE"`
- `thp_defrag_policy == "always"`: `"CHANGE_THP_DEFRAG_TO_DEFER_OR_MADVISE"`
- `not unmovable_isolation_enabled` 또는 `min_free_kbytes_mb < 256`: `"INCREASE_MIN_FREE_KBYTES_AND_ISOLATE_UNMOVABLE"`
- 해당 사항이 없으면: `["MONITOR_EXTFRAG_INDEX_AND_COMPACTION_STATS"]`
