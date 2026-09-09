# 문제 218: 리눅스 가상 메모리 관리: vm.swappiness와 get_scan_count() 익명(Anon) vs 파일(File) 페이지 회수 비율 및 페이지 캐시 기아(Thrashing)

## 1. 개요 (Incident Scenario)

엔터프라이즈 전자상거래 플랫폼의 미션 크리티컬 RDBMS(PostgreSQL / MySQL) 클러스터를 운영하는 인프라 SRE 팀은 트래픽 피크 타임마다 데이터베이스 노드의 디스크 I/O가 100% 포화 상태(`%iowait > 80%`)에 도달하고 쿼리 레이턴시가 수십 배로 폭증하는 심각한 성능 저하 장애를 겪었습니다.

장애 분석 결과, 성능 엔지니어링 팀이 "스왑 디스크 I/O로 인한 지연을 원천 차단하겠다"는 의도로 커널 파라미터 `vm.swappiness = 0` (또는 `1`)을 설정한 것이 오히려 치명적인 독이 되었음이 밝혀졌습니다.

리눅스 커널의 가상 메모리 서브시스템(`mm/vmscan.c`)은 시스템 가용 메모리가 저수위선(`WMARK_LOW`) 아래로 떨어지면 비동기 메모리 회수 데몬(`kswapd`) 또는 직접 회수(Direct Reclaim)를 실행합니다. 이때 회수 대상 페이지를 선정하는 핵심 함수인 `get_scan_count()`는 `swappiness` 값을 기반으로 익명(Anonymous) 페이지와 파일 백업(File-backed Page Cache) 페이지의 스캔 비율을 결정합니다:
$$\text{anon\_ratio} = \frac{\text{swappiness}}{200}, \quad \text{file\_ratio} = \frac{200 - \text{swappiness}}{200}$$

이 메커니즘으로 인해 다음과 같은 이상 징후들이 연쇄적으로 발생했습니다:
1. **페이지 캐시 기아 및 디스크 쓰레싱 (`swappiness = 0` 또는 `1`)**:
   `swappiness = 0` 환경에서는 익명 메모리(DB 프로세스 힙, 커넥션 버퍼 등)가 스왑 아웃 대상에서 완전히 배제됩니다. 따라서 커널은 메모리 확보 압박을 $100\%$ 파일 백업 페이지 캐시에만 전가합니다. 그 결과 DB 테이블과 인덱스가 캐싱되어 있던 수십 GB의 페이지 캐시가 모조리 축출(Eviction)되어 적중률이 50% 미만으로 붕괴했습니다. 모든 쿼리가 물리 디스크를 직접 읽어야 하는 디스크 쓰레싱(`PAGE_CACHE_EVICTION_THRASHING`)이 발생했습니다.
2. **직접 메모리 회수 프리징 및 OOM Killer 강제 종료**:
   스왑이 완전히 비활성화되어 있거나 `swappiness = 0`인 상태에서 대용량 쿼리 힙 할당이 몰리자, 더 이상 축출할 페이지 캐시조차 고갈되어 커널이 Direct Reclaim 상태에서 수 초간 멈춘 뒤 OOM Killer가 동작하여 마스터 DB 프로세스를 사살(`OOM_KILLER_INVOCATION_STALL`)했습니다.
3. **느린 스왑 디스크로 인한 D-상태 I/O 스파이크 (`swappiness = 100`)**:
   반대로 회전식 HDD 스왑 환경에서 `swappiness = 100`으로 과도하게 높게 설정할 경우, 커널이 익명 페이지를 과도하게 스왑 아웃하면서 수십 초간 스왑 I/O 락에 갇혀 서비스가 멈추는 부작용(`EXCESSIVE_SWAP_IO_LATENCY_SPIKE`)이 관측되었습니다.
4. **균형 잡힌 메모리 회수 및 MGLRU (Multi-Gen LRU) 최적화**:
   초고속 NVMe 기반 스왑과 적절한 `swappiness = 20~30`을 조합하거나, zswap(인-메모리 압축 스왑) 또는 리눅스 6.1+ MGLRU를 활성화하여 세대별 참조 빈도를 추적함으로써, 활성 워킹셋 캐시 적중률을 80~95% 이상으로 보호하면서도 OOM과 스왑 지연을 완벽하게 예방할 수 있음을 증명해야 합니다.

당신은 리눅스 커널 가상 메모리(VM) 및 데이터베이스 성능 최적화 전문가로서, `vm.swappiness`, 스왑 장치 유형, zswap, MGLRU 설정에 따른 메모리 회수 동역학을 정밀하게 모의(Simulation)하고 최종 진단 리포트를 도출하는 엔진을 구현해야 합니다.

---

## 2. 아키텍처 및 메모리 회수 상태 모델

```
 [가용 메모리 압박 발생: free_mb < alloc_anon + low_wmark_mb]
                        │
                        ▼
               [get_scan_count() 연산]
      anon_ratio = swappiness / 200
      file_ratio = (200 - swappiness) / 200
      (단, swappiness == 0 또는 스왑 0MB 시 anon_ratio = 0, file_ratio = 1.0)
                        │
       ┌────────────────┴────────────────┐
       ▼                                 ▼
 [파일 페이지 캐시 회수]           [익명 메모리 스왑 아웃]
 file_cache -= target * file_ratio  anon_mb -= target * anon_ratio
       │                                 │
       ▼                                 ▼
 페이지 캐시 축출로               스왑 장치 쓰기 지연:
 워킹셋 적중률 하락               - SLOW_HDD : 2.5ms / MB (치명적 I/O 스톨)
 (Hit Rate < 55% 시 쓰레싱)       - FAST_NVME: 0.05ms / MB
                                  - ZSWAP    : 0ms (3:1 인-메모리 압축)
                        │
                        ▼
           [가용 메모리 부족 시 Direct Reclaim]
           - 비상 파일 캐시 강제 축출
           - 여전히 부족할 경우: OOM Killer 가동!
```

### 시뮬레이션 동작 규격

1. **메모리 파라미터 및 워터마크**:
   - `total_ram_mb`: 전체 물리 메모리 (기본 32768 MB).
   - 저수위선: `low_wmark_mb = total_ram_mb * 0.05` (5%).
   - 고수위선: `high_wmark_mb = total_ram_mb * 0.08` (8%).
   - 초기 상태: `anon_mb`, `file_cache_mb`, `free_mb = total_ram_mb - anon_mb - file_cache_mb`.

2. **메모리 할당 및 회수 분배**:
   - 워크로드 단계별로 `alloc_anon_mb`의 익명 메모리 할당 요청이 발생합니다.
   - `free_mb < alloc_anon + low_wmark_mb`인 경우 회수 필요량 산출:
     $$reclaim\_target = (alloc\_anon + high\_wmark\_mb) - free\_mb$$
   - 회수 비율 결정:
     - `swap_capacity_mb <= 0` 또는 `swappiness == 0`:
       $$anon\_ratio = 0.0, \quad file\_ratio = 1.0$$
     - `mglru_enabled == True`:
       워킹셋 보호를 위해 `file_cache_mb <= working_set_mb * 1.1`이면 $anon\_ratio = 0.8, file\_ratio = 0.2$, 아니면 $anon\_ratio = 0.3, file\_ratio = 0.7$.
     - 일반 커널 LRU:
       $$anon\_ratio = \frac{swappiness}{200}, \quad file\_ratio = \frac{200 - swappiness}{200}$$
   - 파일 캐시 축출: `min(file_cache_mb, reclaim_target * file_ratio)` 만큼 차감 후 가용 메모리 증가.
   - 익명 메모리 스왑: `min(anon_mb * 0.6, reclaim_target * anon_ratio, avail_swap)` 만큼 차감 후 가용 메모리 증가.
     - `swap_device == "SLOW_HDD"`: MB당 2.5ms의 I/O 스톨 누적.
     - `zswap_enabled == True`: 메모리 내 3:1 압축으로 I/O 스톨 0ms.
     - `swap_device == "FAST_NVME"`: MB당 0.05ms 누적.
   - 만약 회수 후에도 `free_mb < alloc_anon`이면:
     - 비상 파일 캐시 직렬 회수(Direct Reclaim, MB당 0.2ms 스톨).
     - 그럼에도 부족하면 `oom_killed = True` 및 10,000ms 스톨 부여.

3. **페이지 캐시 적중률 및 쿼리 지연 시간**:
   - 각 스텝마다 `queries` 건의 읽기 요청이 발생합니다.
   - 워킹셋 캐시 적중 비율:
     $$cached\_fraction = \min(1.0, file\_cache\_mb / working\_set\_mb)$$
   - 적중 쿼리: `int(queries * cached_fraction)`, 미스 쿼리: `queries - hits`.
   - 적중률: $hit\_rate\_pct = (total\_cache\_hits / total\_queries) \times 100$.
   - 평균 쿼리 레이턴시: 기본 0.5ms + (디스크 읽기 미스당 2.0ms 패널티 / 총 쿼리 수).

---

## 3. 입력 사양 (Input Specification)

JSON 형식으로 표준 입력(`sys.stdin`)을 통해 전달됩니다.

```json
{
  "config": {
    "swappiness": 30,
    "total_ram_mb": 32768,
    "swap_capacity_mb": 8192,
    "swap_device": "FAST_NVME",
    "zswap_enabled": false,
    "mglru_enabled": false,
    "initial_anon_mb": 16384,
    "initial_file_cache_mb": 14336,
    "working_set_mb": 12288
  },
  "workload": [
    {"alloc_anon_mb": 1800, "queries": 5000},
    {"alloc_anon_mb": 1800, "queries": 5000}
  ]
}
```

- `swappiness` (integer): 커널 swappiness 값 (0 ~ 200).
- `total_ram_mb` (number): 총 물리 메모리 크기 (MB).
- `swap_capacity_mb` (number): 스왑 공간 크기 (MB).
- `swap_device` (string): `"FAST_NVME"`, `"SLOW_HDD"`, `"ZSWAP"`, `"NONE"`.
- `zswap_enabled` (boolean): zswap 압축 스왑 활성화 여부.
- `mglru_enabled` (boolean): Multi-Gen LRU 활성화 여부.
- `working_set_mb` (number): 데이터베이스 활성 워킹셋 크기 (MB).
- `workload` (array): 메모리 할당 및 쿼리 트레이스 단계 목록.

---

## 4. 출력 사양 (Output Specification)

JSON 형식으로 표준 출력(`sys.stdout`)에 출력합니다.

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_BALANCED_MEMORY_RECLAIM",
  "metrics": {
    "final_anon_mb": 22960.0,
    "final_file_cache_mb": 7186.6,
    "final_free_mb": 2621.4,
    "final_swap_used_mb": 1432.0,
    "page_cache_hit_rate_pct": 75.3,
    "total_disk_reads": 6175,
    "average_query_latency_ms": 0.99,
    "total_reclaim_stall_ms": 71.8,
    "oom_killed": false
  }
}
```

### 진단 판정(Verdict) 기준:
1. `oom_killed == true`: `"OOM_KILLER_INVOCATION_STALL"` (`status: "FAILED"`)
2. `page_cache_hit_rate_pct < 55.0`: `"PAGE_CACHE_EVICTION_THRASHING"` (`status: "FAILED"`)
3. `total_reclaim_stall_ms > 2000.0` 및 `swap_device == "SLOW_HDD"`: `"EXCESSIVE_SWAP_IO_LATENCY_SPIKE"` (`status: "FAILED"`)
4. `mglru_enabled == true` 및 `page_cache_hit_rate_pct >= 85.0`: `"OPTIMAL_CGROUP_V2_MGLRU_RECLAIM"` (`status: "SUCCESS"`)
5. `page_cache_hit_rate_pct >= 75.0` 및 `total_reclaim_stall_ms < 500.0`: `"OPTIMAL_BALANCED_MEMORY_RECLAIM"` (`status: "SUCCESS"`)
6. 그 외: `"SUBOPTIMAL_MEMORY_PRESSURE"` (`status: "SUCCESS"`)
