# Problem 191: 리눅스 커널 메모리 관리: Zone Watermarks와 비동기 kswapd vs 다이렉트 리클레임(Direct Reclaim) 지연 스톨

## 문제 설명

초고처리량 분산 메시징 큐(Apache Kafka), 대규모 분산 검색 엔진(Elasticsearch), 그리고 메모리 집약적 JVM 애플리케이션을 운영하는 인프라 SRE 엔지니어링 팀은 주기적으로 알 수 없는 **치명적인 p99/p999 지연 시간 폭발(수십~수백 ms)** 현상과 유저 스레드 동결(Uninterruptible Sleep, D-State) 현상을 겪었습니다.

리눅스 커널 심층 추적 도구(`perf`, `bpftrace`, `vmstat`, `/proc/zoneinfo`)로 분석한 결과, 주원인은 메모리가 완전히 고갈되지 않았음에도 불구하고 커널이 유저 공간 애플리케이션 스레드를 강제로 정지시키고 페이지를 직접 회수하는 **동기적 다이렉트 리클레임(Direct Reclaim, `try_to_free_pages()`)** 스톨 때문이었습니다.

---

## 핵심 시스템 배경 및 원리

### 1. 리눅스 가상 메모리 존(Zone)과 워터마크 3계층
리눅스 커널 버디 할당자(Buddy Allocator)는 메모리 존(예: `ZONE_NORMAL`, `ZONE_DMA32`)의 여유 메모리 상태를 감시하기 위해 3단계의 **수위선(Zone Watermarks)**을 유지합니다:

1. **`WMARK_MIN` (최저 수위선)**:
   - 시스템 콜 파라미터 `vm.min_free_kbytes`에 의해 직접 결정됩니다.
   - 여유 페이지 수가 이 수위선 이하로 떨어지면, 일반 유저 스레드의 메모리 할당이 **즉각 차단(Block)**됩니다.
   - 오직 `GFP_ATOMIC`(인터럽트 컨텍스트 등) 할당만이 이 수위선 아래의 긴급 메모리를 사용할 수 있습니다.
2. **`WMARK_LOW` (저수위선 - kswapd 기상선)**:
   - 커널 기본값: `WMARK_MIN + (WMARK_MIN / 4)` 또는 `vm.watermark_scale_factor`에 의해 계산된 버퍼.
   - 여유 페이지가 `WMARK_LOW` 이하로 떨어지면, 커널 백그라운드 스와핑 데몬인 **`kswapd`**가 깨어나 비동기적으로 페이지 캐시를 회수하기 시작합니다.
   - **중요**: 이때 메모리를 요청한 유저 스레드는 멈추지 않고 즉시 메모리를 받아 실행을 계속합니다!
3. **`WMARK_HIGH` (고수위선 - kswapd 취침선)**:
   - `WMARK_MIN + 2 * (WMARK_LOW - WMARK_MIN)`.
   - `kswapd`는 여유 페이지 수가 `WMARK_HIGH`에 도달할 때까지 회수를 진행한 뒤 다시 수면(Sleep) 상태로 들어갑니다.

### 2. 다이렉트 리클레임 지연 참사 메커니즘 (Direct Reclaim Disaster)
- **근본 원인**:
  - 기본 커널 설정에서 `vm.min_free_kbytes`가 수십 MB(예: 64MB)로 지나치게 작고, `watermark_scale_factor`가 기본값(10, 0.1%)으로 좁게 설정되어 있으면 `WMARK_LOW`와 `WMARK_MIN` 사이의 완충 버퍼(Buffer Zone)가 극도로 협소합니다.
  - 대용량 데이터 인제스천이나 객체 생성이 순간적으로 몰아칠 때(Burst Inflow), `kswapd`가 미처 깨어나서 페이지를 회수하기도 전에 여유 메모리가 `WMARK_MIN`을 뚫고 추락합니다.
- **참사 발생**:
  - `free_pages <= WMARK_MIN`이 되는 순간, 메모리를 요청한 애플리케이션 스레드는 커널 함수 `try_to_free_pages()`에 강제로 갇힙니다.
  - 유저 스레드가 직접 활성/비활성 LRU(Least Recently Used) 리스트를 스캔하고, 파일 시스템 더티 페이지를 플러시하거나 페이지를 해제하느라 **수십~수백 밀리초 동안 CPU를 잡고 얼어붙는 지연시간 스파이크**가 발생합니다.

### 3. 프로덕션 커널 파라미터 최적화
1. **`vm.min_free_kbytes` 상향 조정**:
   - 시스템 메모리의 $1\% \sim 5\%$ 수준(예: 32GB 메모리 서버 기준 $512\,\text{MB} \sim 1\,\text{GB}$)으로 넉넉히 설정하여 안전 여유 공간을 확보합니다.
2. **`vm.watermark_scale_factor` 상향 조정**:
   - 리눅스 4.6부터 도입된 이 파라미터를 기본값 10(0.1%)에서 100~300(1%~3%)으로 확대하여, `WMARK_LOW`와 `WMARK_MIN` 사이의 완충 폭을 대폭 넓힙니다.
   - 서지 트래픽이 유입되더라도 `kswapd`가 훨씬 일찍 깨어나 비동기적으로 대량의 메모리를 미리 회수하므로, 다이렉트 리클레임 유입률을 0%로 통제할 수 있습니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "system": {
    "total_memory_mb": 8192,
    "page_size_kb": 4,
    "min_free_kbytes": 524288,
    "watermark_scale_factor": 200,
    "initial_free_mb": 600,
    "initial_page_cache_mb": 5000,
    "kswapd_rate_pages_per_ms": 10000,
    "direct_reclaim_cost_per_page_us": 0.5
  },
  "workload": [
    {
      "timestamp_ms": 0.0,
      "type": "ALLOC",
      "size_mb": 80.0,
      "caller": "worker_1"
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 형식 결과를 출력합니다.

```json
{
  "status": "SUCCESS",
  "watermarks": {
    "wmark_min_pages": 131072,
    "wmark_low_pages": 172032,
    "wmark_high_pages": 212992,
    "buffer_pages": 40960
  },
  "metrics": {
    "total_allocations": 4,
    "fast_path_allocations": 2,
    "kswapd_wakeups": 2,
    "direct_reclaim_stalls": 0,
    "max_stall_latency_ms": 0.0,
    "total_pages_reclaimed_kswapd": 81920,
    "total_pages_reclaimed_direct": 0,
    "oom_killer_invocations": 0,
    "verdict": "OPTIMAL_ASYNC_KSWAPD_RECLAIM"
  },
  "events_log": [
    {
      "time_ms": 0.0,
      "event": "ALLOC_FAST_PATH",
      "caller": "worker_1",
      "pages": 20480,
      "free_pages": 133120,
      "latency_ms": 0.001
    }
  ]
}
```

### 판정 규칙 (Verdict Rules)
1. `oom_killer_invocations > 0`:
   - `status = "FAILED"`, `verdict = "OOM_KILLER_INVOKED_DISASTER"`
2. `direct_reclaim_stalls > 0`:
   - `status = "FAILED"`, `verdict = "DIRECT_RECLAIM_LATENCY_STALL_DISASTER"`
3. 유저 스레드 스톨이 0건이고 모든 메모리가 안전하게 할당된 경우:
   - `status = "SUCCESS"`, `verdict = "OPTIMAL_ASYNC_KSWAPD_RECLAIM"`
