# Problem 188: 리눅스 커널 메모리 관리: Transparent HugePages (THP) 단편화 지연 스파이크와 CoW 메모리 증폭 (Direct Compaction vs madvise)

## 문제 설명

초고성능 인메모리 캐시(Redis), 도큐먼트 데이터베이스(MongoDB), 고성능 JVM 애플리케이션을 운영하는 인프라 SRE 팀은 프로덕션 클러스터에서 원인 불명의 극심한 레이턴시 스파이크(p99 > 50ms)와 간헐적 OOM(Out of Memory) 프로세스 강제 종료 사태를 겪었습니다.

심층 커널 프로파일링(`perf`, `bpftrace`, `/proc/vmstat`) 결과, 주범은 리눅스 커널의 **Transparent HugePages (THP)** 서브시스템과 **동기적 다이렉트 컴팩션(Direct Compaction)**, 그리고 **Copy-on-Write (CoW) 메모리 증폭**이었습니다:

1. **외적 메모리 파편화(External Fragmentation)와 동기적 컴팩션 스톨**:
   - x86_64 리눅스에서 기본 페이지는 4KB이지만, THP는 2MB(연속된 512개의 4KB 물리 페이지, Order-9) 크기의 휴즈페이지를 자동으로 할당합니다.
   - 장기간 실행된 시스템에서는 메모리가 잘게 쪼개져 2MB 연속 물리 메모리 블록이 고갈됩니다.
   - 이 상태에서 애플리케이션 스레드가 메모리를 할당하려 하면, 커널이 유저 스레드를 동기적으로 블로킹하고 페이지 이동 및 메모리 압축(`compact_zone()`)을 강제 수행합니다. 이로 인해 마이크로초(μs) 단위여야 할 `malloc()`이 **수십 밀리초(ms)** 동안 굳어버리는 지연 스파이크가 발생합니다.
2. **Redis fork() 및 CoW(Copy-on-Write) 메모리 512배 증폭 재앙**:
   - Redis가 `BGSAVE`나 `AOF rewrite`를 위해 백그라운드 자식 프로세스를 `fork()`할 때, 부모와 자식은 메모리 페이지를 공유합니다.
   - 부모 프로세스가 단 1바이트의 키를 수정하더라도 커널의 Page Fault 핸들러(`do_huge_pmd_wp_page()`)는 4KB가 아닌 **2MB 전체 페이지를 물리적으로 복제**합니다!
   - 4KB 쓰기 대비 **512배의 메모리 쓰기 증폭(Write Amplification)**이 발생하여 불필요한 메모리가 폭발하고 대량 복제로 인한 CPU 캐시 오염 및 OOM 킬러 호출로 이어집니다.
3. **THP 튜닝 모드의 딜레마**:
   - `THP_ALWAYS`: 모든 프로세스에 2MB 휴즈페이지를 강제 적용. 파편화 환경에서 치명적인 다이렉트 컴팩션 스톨 및 CoW 증폭 유발.
   - `THP_NEVER`: THP를 완전히 비활성화 (`echo never > /sys/kernel/mm/transparent_hugepage/enabled`). 스톨과 CoW 증폭이 0이 되며 가장 안정적이나, 초대용량 분석 배치(OLAP/JVM 대용량 힙)에서 TLB(Translation Lookaside Buffer) 미스율이 증가할 수 있음.
   - `THP_MADVISE`: 커널 레벨에서는 대기하되, 애플리케이션이 `madvise(addr, len, MADV_HUGEPAGE)` 시스템 콜을 명시적으로 호출한 영역에만 선별적으로 2MB 휴즈페이지를 할당. 일반 OLTP/Redis는 안전한 4KB 페이지를 사용하고 분석 배치는 2MB 페이지를 사용하는 가장 정교한 최적 모드.

엔지니어링 팀은 리눅스 가상 메모리 관리자의 THP 동작, 동기/비동기 컴팩션 디프래그 모드, CoW 증폭 및 TLB 미스 페널티를 정밀하게 모델링하는 시뮬레이터를 개발하여 프로덕션 배포 전 시스템 성능을 검증하고자 합니다.

---

## 핵심 시스템 파라미터 및 동작 모드

### 1. THP 모드 (`thp_mode`)
- `THP_ALWAYS`: 모든 메모리 할당(`ALLOC`) 시도에 대해 2MB 휴즈페이지(`HUGE_PAGE_2MB`) 할당을 시도합니다.
- `THP_MADVISE`: 할당 요청에 `is_madvised: true` 플래그가 설정된 경우에만 2MB 휴즈페이지를 할당하고, 그렇지 않으면 표준 4KB 기본 페이지(`BASE_PAGE_4KB`)를 할당합니다.
- `THP_NEVER`: 모든 할당 요청에 대해 무조건 표준 4KB 기본 페이지(`BASE_PAGE_4KB`)를 할당합니다.

### 2. 디프래그 및 컴팩션 모드 (`thp_defrag_mode`)
- `SYNC_DIRECT_COMPACT`:
  - 메모리 외적 파편화율(`memory_fragmentation`)이 $0.5$ 이상인 상태에서 휴즈페이지(2MB)를 할당하려고 하면, 유저 스레드가 동기적으로 블로킹되어 다이렉트 컴팩션이 발생합니다.
  - 지연 시간: `direct_compaction_latency_us * hp_count` 추가.
  - `direct_compaction_stalls` 카운트가 증가하며 유저 스레드가 일시 정지(Stall)됩니다.
- `ASYNC_KHUGEPAGED`:
  - 파편화가 발생해도 유저 스레드는 즉시 반환되며, 백그라운드 커널 데몬 `khugepaged`가 비동기로 조각 모음을 수행하므로 즉각적인 스톨이 발생하지 않습니다 (`stall_time = 0.0`).
- `NEVER`:
  - 어떠한 컴팩션도 수행하지 않습니다.

### 3. CoW (Copy-on-Write) 메모리 복제
- `COW_WRITE` 작업 시:
  - 대상 메모리가 `HUGE_PAGE_2MB`인 경우: 단 몇 바이트의 수정이라도 2048KB 전체가 물리적으로 복제됩니다 (`copied_kb = 2048`). 이상적인 복제 단위(4KB) 대비 증폭된 메모리는 `amplified_kb = 2048 - 4 = 2044KB`입니다.
  - 대상 메모리가 `BASE_PAGE_4KB`인 경우: 오직 수정된 4KB 페이지만 복제됩니다 (`copied_kb = 4`, `amplified_kb = 0`).
  - 복제 지연 시간: `copied_kb * cow_copy_per_kb_us` 소요.

### 4. 순차 읽기 스캔과 TLB 미스 (`READ_SCAN`)
- 64페이지를 초과하는 대규모 순차 스캔 시:
  - `BASE_PAGE_4KB`는 페이지 엔트리가 많아 TLB 미스 페널티 발생: `(pages_to_scan / 64) * tlb_miss_penalty_per_req_us`.
  - `HUGE_PAGE_2MB`는 1개의 TLB 엔트리로 2MB를 커버하므로 TLB 미스 페널티가 0입니다 (`tlb_penalty = 0.0`).

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "system": {
    "thp_mode": "THP_MADVISE",
    "thp_defrag_mode": "ASYNC_KHUGEPAGED",
    "base_page_size_kb": 4,
    "huge_page_size_kb": 2048,
    "standard_alloc_latency_us": 2.0,
    "direct_compaction_latency_us": 15000.0,
    "cow_copy_per_kb_us": 0.5,
    "tlb_miss_penalty_per_req_us": 5.0,
    "initial_fragmentation": 0.6
  },
  "workload": [
    {"op": "SET_FRAGMENTATION", "wallclock_ms": 0.0, "fragmentation": 0.6},
    {"op": "ALLOC", "wallclock_ms": 10.0, "alloc_id": "redis_kv_1", "size_kb": 128, "is_madvised": false},
    {"op": "COW_WRITE", "wallclock_ms": 20.0, "alloc_id": "redis_kv_1", "bytes_modified": 32},
    {"op": "ALLOC", "wallclock_ms": 30.0, "alloc_id": "spark_batch_2", "size_kb": 2048, "is_madvised": true},
    {"op": "READ_SCAN", "wallclock_ms": 40.0, "alloc_id": "spark_batch_2", "pages_to_scan": 256}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 JSON 객체를 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "summary": {
    "thp_mode": "THP_MADVISE",
    "defrag_mode": "ASYNC_KHUGEPAGED",
    "total_allocations": 2,
    "huge_pages_allocated": 1,
    "base_pages_allocated": 32,
    "direct_compaction_stalls": 0,
    "total_stall_time_us": 0.0
  },
  "metrics": {
    "total_allocations": 2,
    "huge_pages_allocated": 1,
    "base_pages_allocated": 32,
    "total_memory_allocated_kb": 2176,
    "direct_compaction_stalls": 0,
    "total_stall_time_us": 0.0,
    "cow_copied_memory_kb": 4,
    "cow_amplified_memory_kb": 0,
    "average_latency_us": 3.75,
    "verdict": "OPTIMAL_MADVISE_SELECTIVE_HUGEPAGE"
  },
  "sample_events": [
    {
      "wallclock_ms": 10.0,
      "op": "ALLOC",
      "alloc_id": "redis_kv_1",
      "size_kb": 128,
      "page_type": "BASE_PAGE_4KB",
      "stalled": false,
      "latency_us": 2.0
    }
  ]
}
```

### 판정(Verdict) 규칙:
1. `THP_ALWAYS` 모드에서 다이렉트 컴팩션 스톨(`direct_compaction_stalls > 0`) 발생 시:
   `verdict: "SYNCHRONOUS_DIRECT_COMPACTION_LATENCY_SPIKE"` (`status: FAILED`)
2. `THP_ALWAYS` 모드에서 CoW 증폭(`cow_amplified_memory_kb > 0`) 발생 시:
   `verdict: "COW_MEMORY_AMPLIFICATION_EXPLOSION"` (`cow_amplified_memory_kb >= 4096`이면 `status: FAILED`)
3. `THP_MADVISE` 모드인 경우:
   `verdict: "OPTIMAL_MADVISE_SELECTIVE_HUGEPAGE"`
4. 그 외 (`THP_NEVER` 등):
   `verdict: "STABLE_4KB_PAGES_NO_STALLS"`
