# 메모리 할당자 내부 아키텍처: Glibc Ptmalloc 아레나 락 경합 vs Jemalloc tcache(Thread-local Cache)와 지연 퍼징(Decay-based Purging)

## 문제 배경 및 개요
글로벌 핀테크 금융사의 초저지연 고빈도 거래(HFT / Order Matching Engine) 및 실시간 스트리밍 체결 서버(C++/Rust/Java Netty JNI)는 초당 수십만 건의 주문 및 호가 이벤트를 64~128개의 멀티스레드로 병렬 처리합니다.
스레드들은 거래 수명 동안 수십~수백 바이트 크기의 단기 객체(`OrderTicket`, `TradeFill`, `QuoteBook`)를 초당 수백만 번 `malloc()`하고 처리가 끝나는 즉시 `free()`합니다.

그러나 기본 시스템 C 라이브러리인 **Glibc Ptmalloc(ptmalloc3 기반)** 환경에서 운영하던 서버가 트래픽 피크 타임에 두 가지 파괴적인 물리적 병목에 부딪히며 지연시간(p99)이 수백 밀리초로 폭증하고 결국 OOM-Killer에게 강제 종료당하는 대참사가 발생했습니다:

1. **공유 아레나 뮤텍스 락 경합 (Arena Mutex Contention & Futex Stalls)**:
   - Glibc Ptmalloc은 스레드 간 경합을 완화하기 위해 복수의 아레나(`MALLOC_ARENA_MAX = 8 * cores`)를 유지하지만, 스레드-아레나 간 정적/해시 매핑 및 수많은 스레드의 동시 접근으로 인해 모든 `malloc()`과 `free()` 호출 시 해당 아레나의 스핀락/뮤텍스(`arena->mutex`)를 획득해야 합니다.
   - 코어 수가 많아지고 트랜잭션이 폭증할수록 CPU 프로파일러의 상위 70%가 커널 `sys_futex` 및 유저 레벨 `__lll_lock_wait_private`로 도배되며 모든 워커 스레드가 락 대기 상태로 얼어붙습니다 (`PTMALLOC_ARENA_LOCK_COLLAPSE`).
2. **외적 단편화(External Fragmentation) 및 물리 메모리(RSS) 영구 비대화 (Memory Bloat & Lack of Purging)**:
   - Ptmalloc은 메모리 해제 시 인접 청크를 병합하지만, 힙의 최상단(`top chunk`)만 `brk` 시스템 콜을 통해 OS 커널로 축소 반환할 수 있습니다.
   - 단 하나의 활성 객체가 힙 상단을 가로막고 있으면 중간에 수 기가바이트의 빈 공간(Hole)이 생겨도 커널로 반환되지 못합니다. 또한 `madvise(MADV_DONTNEED)`를 통한 비동기 물리 페이지 환원 메커니즘이 없어, 실제 활성 객체는 수십 MB에 불과한데 프로세스 RSS는 피크 시점의 수십 GB를 유지하다가 OOM-Killer에 의해 피살됩니다 (`PTMALLOC_FRAGMENTATION_RSS_BLOAT`).

현대 고성능 분산 인프라(Redis, TiDB, Rust 기본/선택 할당자, Meta Folly, FreeBSD 커널)는 이를 해결하기 위해 **Jemalloc** 아키텍처를 표준으로 채택했습니다:
- **스레드 로컬 캐시 (`tcache`)**: 각 스레드가 자신만의 무락(Lock-Free) 로컬 캐시(`tcache`)를 보유하여, 빈번한 소형 객체 할당/해제의 90% 이상을 공유 아레나 뮤텍스 접근 없이 $O(1)$로 즉시 처리합니다.
- **배치 리필 및 배치 플러시 (Batch Refill & Flush)**: tcache가 고갈되었을 때만 공유 아레나에서 한 번에 여러 슬롯(`batch_refill_count`)을 일괄 인출하고, 용량 초과(`tcache_max_per_bin`) 시 일괄 반환하여 락 획득 횟수를 수십 분의 일로 격감시킵니다.
- **지연 시간 기반 페이지 퍼징 (Decay-based Purging / `dirty_decay_ms`)**: 사용되지 않고 비어있는 4KB 물리 페이지를 감쇠 타이머(`decay_tick`)에 맞춰 커널에 `madvise(MADV_DONTNEED)`로 자율 반환함으로써 메모리 단편화와 RSS 낭비를 원천 봉쇄합니다 (`OPTIMAL_JEMALLOC_TCACHE_TUNED`).

당신은 가상 메모리 할당자 시뮬레이터를 구현하여, 유입되는 멀티스레드 메모리 할당/해제 워크로드에 대해 Ptmalloc과 Jemalloc의 동작을 정밀 시뮬레이션하고 병목 원인과 물리 메모리 상태를 정확히 진단해야 합니다.

---

## 메모리 할당 상태 머신 및 동작 규칙

### 1. 크기 클래스 (Size Classes) 및 슬랩 분할
- 지원되는 기본 크기 클래스: `[16, 32, 64, 128, 256, 512, 1024, 2048, 4096]`
- 요청 크기 `size`는 크거나 같은 가장 작은 크기 클래스 `sc`로 올림 정렬됩니다. (4096 초과 시 4096 배수로 정렬)
- OS 물리 페이지 크기는 기본 4096 바이트이며, 1개 페이지는 해당 크기 클래스의 슬롯 `total_slots = page_size // sc` 개로 균등 분할됩니다.

### 2. 스레드-아레나 매핑 (Thread-to-Arena Mapping)
- 각 스레드는 `thread_arena[thread_id] = thread_index % arenas_count` 방식으로 아레나에 배정됩니다.

### 3. Ptmalloc 동작 규칙
- **모든 `malloc`**:
  - 반드시 소속 아레나의 뮤텍스 락을 획득합니다 (`arena_lock_acquisitions += 1`).
  - 아레나의 프리 풀에서 슬롯을 인출하며, 빈 슬롯이 없으면 OS로부터 신규 4KB 페이지를 할당받습니다.
  - `tcache`가 없으므로 `tcache_hits`는 0입니다.
- **모든 `free`**:
  - 반드시 소속 아레나의 뮤텍스 락을 획득합니다 (`arena_lock_acquisitions += 1`).
  - 슬롯을 아레나 프리 풀로 반환하고 해당 페이지의 `used_slots`를 1 감소시킵니다.
- **페이지 반환 불가 (No Decay Purge)**:
  - Ptmalloc은 `decay_tick`이나 유휴 상태에서도 페이지를 커널로 반환하지 않습니다 (`pages_purged_to_os = 0`). 따라서 완전히 비어있는 페이지(`used_slots == 0`)가 발생해도 RSS에 그대로 유지됩니다.

### 4. Jemalloc 동작 규칙 (tcache 및 Decay)
- **`malloc`**:
  - `tcache_enabled`가 활성화되어 있고 해당 크기 클래스의 `tcache`에 여유 슬롯이 있다면:
    - 아레나 락 없이 로컬 슬롯을 팝(`tcache_hits += 1`)하고 즉시 반환합니다.
  - `tcache`가 비어있다면 (Cache Miss):
    - 소속 아레나 뮤텍스 락을 획득합니다 (`arena_lock_acquisitions += 1`).
    - 공유 아레나에서 `batch_refill_count`개의 슬롯을 일괄 인출합니다. (부족하면 신규 4KB 페이지 할당)
    - 1개 슬롯은 요청자에게 반환하고, 나머지 `batch_refill_count - 1`개는 로컬 `tcache`에 적재합니다.
- **`free`**:
  - `tcache_enabled`가 활성화되어 있고 `tcache` 크기가 `tcache_max_per_bin` 미만이라면:
    - 아레나 락 없이 로컬 `tcache`에 푸시(`tcache_hits += 1`)합니다.
  - `tcache`가 가득 찼다면 (Cache Overflow):
    - 소속 아레나 뮤텍스 락을 획득합니다 (`arena_lock_acquisitions += 1`).
    - `batch_refill_count`개 슬롯을 공유 아레나 프리 풀로 일괄 플러시(Batch Flush)합니다.
    - 현재 해제된 슬롯을 `tcache`에 보관합니다.
- **지연 퍼징 (Decay-based Purging)**:
  - `op == "decay_tick"`이 발생하거나 `decay_interval_ops > 0` 주기에 도달하면:
    - `used_slots == 0`인 모든 미반환 물리 페이지를 찾아 `purged = True`로 마킹하고 커널에 반환합니다 (`pages_purged_to_os += 1`).
    - 해당 페이지에 속한 슬롯들은 아레나 프리 풀 및 tcache에서 일괄 제거됩니다.
    - 반환된 페이지 수만큼 현재 RSS 물리 메모리(`current_rss_bytes`)가 즉시 감소합니다.

---

## 판정 기준 (System Status)

1. `PTMALLOC_FRAGMENTATION_RSS_BLOAT`:
   - `allocator_config.type == "ptmalloc"`이고, `unpurged_empty_pages >= 1`이며 해제 요청 비율이 충분할 때 (`total_free_requests >= total_alloc_requests * 0.3`).
   - 또는 Jemalloc에서 decay가 비활성화되어 비어있는 페이지가 2개 이상 방치되었을 때.
2. `PTMALLOC_ARENA_LOCK_COLLAPSE`:
   - `allocator_config.type == "ptmalloc"`에서 위 단편화 조건이 아닌 일반 락 경합 상태.
   - 또는 Jemalloc에서 `tcache_enabled == false`이거나 `tcache_hit_ratio_pct < 60.0`으로 락 경합이 심각할 때.
3. `OPTIMAL_JEMALLOC_TCACHE_TUNED`:
   - Jemalloc에서 tcache가 정상 작동(`tcache_hit_ratio_pct >= 60.0`)하고, 미사용 빈 페이지가 decay 퍼징을 통해 커널로 정상 환원되어 메모리와 락이 모두 최적화되었을 때.

---

## 입력 형식
표준 입력(`sys.stdin`)으로 다음 필드를 갖는 단일 JSON 객체가 주어집니다:
- `allocator_config`: 할당자 설정
  - `type`: `"ptmalloc"` 또는 `"jemalloc"`
  - `arenas_count`: 공유 아레나 개수 (정수, $\ge 1$)
  - `tcache_enabled`: tcache 활성화 여부 (boolean, jemalloc 전용)
  - `tcache_max_per_bin`: 크기 클래스당 tcache 최대 슬롯 수 (정수)
  - `batch_refill_count`: tcache 리필/플러시 단위 슬롯 수 (정수)
  - `decay_interval_ops`: 자동 decay 연산 주기 (0이면 명시적 decay_tick만 수행)
  - `page_size`: OS 페이지 크기 (기본 4096)
- `threads`: 스레드 ID 목록 (예: `["T1", "T2", "T3", "T4"]`)
- `events`: 시간순 메모리 연산 이벤트 목록
  - `op`: `"malloc"`, `"free"`, `"decay_tick"`
  - `thread_id`: 연산을 수행하는 스레드 ID
  - `id`: 할당 객체 고유 식별자 (malloc 시 등록, free 시 해제)
  - `size`: 요청 바이트 크기 (malloc 시)

---

## 출력 형식
표준 출력(`sys.stdout`)으로 다음 필드를 갖는 단일 JSON 객체를 인덴트 2칸(`indent=2`)으로 출력해야 합니다:
- `status`: 판정 결과 문자열 (`PTMALLOC_ARENA_LOCK_COLLAPSE` | `PTMALLOC_FRAGMENTATION_RSS_BLOAT` | `OPTIMAL_JEMALLOC_TCACHE_TUNED`)
- `metrics`:
  - `total_alloc_requests`: 총 malloc 요청 건수
  - `total_free_requests`: 총 free 요청 건수
  - `arena_lock_acquisitions`: 공유 아레나 뮤텍스 락 획득 총 횟수
  - `tcache_hits`: tcache에서 무락(Lock-free)으로 처리된 요청 건수
  - `tcache_hit_ratio_pct`: tcache 적중률 백분율 (소수점 1자리 반올림)
  - `current_active_bytes`: 현재 생존 중인 객체들의 실제 바이트 합
  - `current_rss_bytes`: OS에 유지 중인 물리 메모리 크기 (`active_pages * page_size`)
  - `fragmentation_ratio`: 단편화율 (`(current_rss_bytes - current_active_bytes) / current_rss_bytes`, 소수점 2자리 반올림)
  - `pages_purged_to_os`: madvise 등으로 커널에 반환된 4KB 페이지 수
- `thread_stats`: 스레드별 `allocs`, `frees`, `lock_acquisitions` 통계 딕셔너리
- `root_cause_analysis`: 한국어 원인 분석 및 아키텍처 진단 메시지
