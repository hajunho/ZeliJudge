# Problem 215: 파일이 없다는데 왜 메모리가 64GB나 꽉 차요?!: 리눅스 VFS Negative Dentry 폭증과 커널 슬랩(Slab) 캐시 고갈: 존재하지 않는 경로 조회 스톰 시 dentry_cache 누수와 `vfs_cache_pressure` 및 Shrinker 락 경합 방어 (Linux Kernel VFS: Negative Dentry Cache Bloat & Slab Memory Exhaustion vs vfs_cache_pressure Tuning & Bloom Filter Guard)

## 문제 배경 및 개요

대규모 전자상거래 CDN 엣지 프록시 및 컨테이너 호스트 노드를 관리하는 플랫폼 인프라 팀은 해외 봇넷의 악의적인 취약점 스캔 공격(404 Not Found 스톰) 도중 원인을 알 수 없는 **"커널 슬랩(Slab) 메모리 고갈 및 OOM Killer 강제 사살 참사"**를 겪었습니다:

> "호스트의 물리 메모리가 64GB나 되는데, `free -m`을 확인해 보니 가용 메모리가 200MB밖에 남지 않았습니다!  
> 애플리케이션 메모리(`RES`)는 고작 4GB에 불과했고, Page Cache도 거의 없었는데, `cat /proc/meminfo`를 확인해 보니 `Slab: 58 GB`, `SReclaimable: 56 GB`로 커널이 메모리의 90%를 독점하고 있었습니다!  
> 결국 커널 OOM Killer가 깨어나 호스트에서 실행 중이던 메인 데이터베이스와 Nginx 프로세스를 무차별 강제 종료(SIGKILL)시켜 전사 장애가 발생했습니다!"

많은 엔지니어들이 리눅스의 파일 캐시를 "메모리가 부족하면 언제든 커널이 알아서 회수해 주는 페이지 캐시(Page Cache)" 정도로만 생각합니다. 그러나 파일의 디렉터리 경로와 메타데이터를 캐싱하는 **VFS 덴트리 캐시(dentry_cache)**는 **커널 슬랩(SLAB/SLUB) 할당기 내부의 고정된 슬래브 객체(`struct dentry`)**로 관리됩니다.

특히 리눅스는 성능 최적화를 위해 **"존재하지 않는 파일"**을 조회했을 때도 디스크 I/O를 다시 하지 않도록 **Negative Dentry(`d_inode == NULL`)**를 커널 슬랩 메모리에 등록합니다:

```
[Negative Dentry 폭증과 슬랩 고갈 참사 메커니즘]

공격자 / 크롤러: 존재하지 않는 무작위 경로 수천만 건 요청! (GET /scan/uuid_01.php, /missing_02.jpg)
      │
      ▼ open() / stat() 시스템 콜 호출
[리눅스 커널 VFS 계층]
      │
1. dentry_cache 룩업 ──► MISS! (캐시에 없음)
2. 디스크 ext4/xfs inode 탐색 ──► 파일 없음(ENOENT 404 확인)!
3. 다음 조회를 가속하기 위해 커널 슬랩에 Negative Dentry 생성!
   kmem_cache_alloc(dentry_cache) ──► struct dentry (192B + 파일명 문자열)
      │
      ▼ 수백만 개의 404 조회가 쏟아지자...
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 커널 슬랩 메모리 (dentry_cache) 58 GB 폭발!                                             │
│ [NegDentry: /missing_1] [NegDentry: /missing_2] ... [NegDentry: /missing_50000000]    │
└────────────────────────────────────────────────────────────────────────────────────────┘
      │
      ▼ 가용 메모리가 최소 수위(min_watermark) 밑으로 추락!
[다이렉트 메모리 회수 (Direct Reclaim) 발동]
- dentry_shrinker가 깨어나 전역 dcache_lru_lock 스핀락을 쥐고 LRU 순회 시작!
- 초당 수만 개의 스레드가 dcache_lru_lock을 잡으려 경쟁하며 CPU 시스템 시간(sys) 95% 폭증!
- 회수가 역부족이자 커널 OOM Killer 발동! ──► 정상 비즈니스 프로세스 강제 학살!
```

이 고질적인 커널 슬랩 고갈과 락 경합을 방어하기 위해 시스템 엔지니어는 커널의 **`vfs_cache_pressure`** 파라미터 동작 특성을 이해하고, 유저 공간에서 비존재 경로를 차단하는 **블룸 필터(Bloom Filter) 사전 방어선**을 구축해야 합니다.

당신은 리눅스 커널 및 스토리지 엔지니어로서, Negative Dentry 누수로 인한 슬랩 고갈, 과도한 Shrinker 스핀락 경합, 그리고 블룸 필터 기반 사전 방어 아키텍처를 검증하는 시뮬레이션 진단 엔진을 완성해야 합니다.

---

## 3대 VFS 덴트리 처리 모드 명세

### 1. `UNPROTECTED_NEGATIVE_DENTRY_STORM` (무방비 404 스톰 모드)
- 블룸 필터 방어 없이 존재하지 않는 무작위 파일 조회가 VFS 커널 계층으로 직격합니다.
- `vfs_cache_pressure`가 낮거나 기본값인 상태에서 수천 개의 Negative Dentry가 `dentry_cache` 슬랩을 장악합니다.
- 슬랩 메모리가 임계값(70MB)을 초과하거나 가용 메모리가 고갈되어 `oom_killer_triggered = True`가 발생합니다.
- 평가 판정: OOM 발동 또는 슬랩 폭증 시 `NEGATIVE_DENTRY_SLAB_EXHAUSTION_OOM` (`status: FAILED`).

### 2. `HIGH_CACHE_PRESSURE_SHRINKER_STALL` (과도한 캐시 프레셔 락 경합 모드)
- 슬랩 메모리 누수를 억제하겠다고 `vfs_cache_pressure`를 500 이상으로 극단적으로 높인 상태입니다.
- 매 조회마다 커널 `dentry_shrinker`가 전역 `dcache_lru_lock` 스핀락을 잡고 LRU 대량 회수를 시도합니다.
- 지속적인 슬랩 회수 연산으로 인해 스핀락 경합(`shrinker_lock_contention_events >= 15`)이 폭증하고 평균 조회 지연시간이 25us 이상으로 치솟아 시스템 CPU가 마비됩니다.
- 평가 판정: 락 경합 폭증 및 지연시간 스파이크 발생 시 `SHRINKER_LOCK_CONTENTION_CPU_STALL` (`status: FAILED`).

### 3. `OPTIMAL_BLOOM_FILTER_VFS_GUARD` (블룸 필터 사전 방어 최적화 모드)
- 애플리케이션 / 프록시(Nginx, API 게이트웨이) 계층에서 인메모리 블룸 필터를 통해 유효한 파일 경로를 사전에 검증합니다.
- 존재하지 않는 무작위 404 경로는 VFS `open()`/`stat()`을 호출하기 전에 유저 공간에서 즉각 차단(`bloom_filter_rejected_requests` 카운트)됩니다.
- 커널 `dentry_cache`에 불필요한 Negative Dentry가 전혀 생성되지 않으므로, 슬랩 점유율 0% 유지, 락 경합 0건, $0.5\,\mu\text{s}$ 이하의 극초저지연을 달성합니다.
- 평가 판정: `OPTIMAL_BLOOM_FILTER_VFS_GUARD` (`status: SUCCESS`).

---

## 입력 형식

표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "mode": "OPTIMAL_BLOOM_FILTER_VFS_GUARD",
    "total_memory_mb": 1000,
    "initial_app_memory_mb": 620,
    "initial_page_cache_mb": 310,
    "min_watermark_mb": 60,
    "vfs_cache_pressure": 100,
    "dentry_size_bytes": 20480
  },
  "existing_files": [
    "/app/static/asset_0.js",
    "/app/static/asset_1.js"
  ],
  "requests": [
    {"path": "/scan/missing_0.php"},
    {"path": "/app/static/asset_0.js"}
  ]
}
```

---

## 출력 형식

표준 출력(Standard Output)으로 진단 시뮬레이션 결과 JSON을 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_BLOOM_FILTER_VFS_GUARD",
  "mode": "OPTIMAL_BLOOM_FILTER_VFS_GUARD",
  "metrics": {
    "total_requests": 4600,
    "existing_file_hits": 100,
    "negative_dentry_hits": 0,
    "negative_dentries_created": 0,
    "negative_dentries_reclaimed": 0,
    "bloom_filter_rejected_requests": 4500,
    "peak_slab_memory_mb": 1.95,
    "direct_reclaim_events": 0,
    "shrinker_lock_contention_events": 0,
    "oom_killer_triggered": false,
    "average_lookup_latency_us": 0.54
  }
}
```

---

## 판정 기준 (Verdict Rules)

1. **`NEGATIVE_DENTRY_SLAB_EXHAUSTION_OOM`**: 존재하지 않는 경로 스톰으로 인해 Negative Dentry가 슬랩을 잠식하고 가용 메모리를 고갈시켜 OOM Killer가 발동하거나 슬랩 메모리가 70MB 이상 팽창한 경우 (`status: FAILED`).
2. **`SHRINKER_LOCK_CONTENTION_CPU_STALL`**: 과도한 `vfs_cache_pressure` 설정으로 인해 Shrinker 스핀락 경합이 15회 이상 발생하거나 평균 파일 조회 지연시간이 25us 이상으로 치솟은 경우 (`status: FAILED`).
3. **`OPTIMAL_BLOOM_FILTER_VFS_GUARD`**: 블룸 필터 사전 검증으로 404 스톰을 VFS 진입 전 차단하여 슬랩 메모리 안정과 초저지연을 달성한 경우 (`status: SUCCESS`).
4. **`NORMAL_VFS_OPERATION`**: 정상적인 파일 조회 환경에서 덴트리 캐시가 효율적으로 동작한 경우 (`status: SUCCESS`).
