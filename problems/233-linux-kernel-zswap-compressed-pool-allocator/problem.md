# 문제 233: 리눅스 커널 압축 스왑: zswap vs zram과 압축 풀 할당자(zsmalloc vs zbud) 및 압축률 기반 쓰기백(Writeback) 쓰레싱 방어

## 1. 개요 및 배경 (Incident Scenario)

대규모 컨테이너 가상화(Kubernetes) 워커 노드와 메모리 집약형 캐시/데이터베이스(Redis, PostgreSQL) 서버에서 스왑(Swap) 설정과 관련하여 극단적인 딜레마에 부딪혔습니다:

1. **스왑을 켜두었을 때 (Traditional Swap Bottleneck)**:
   - 메모리 압박 발생 시 익명(Anonymous) 페이지가 NVMe/SATA SSD 스왑 파티션으로 밀려납니다.
   - 아무리 빠른 고성능 NVMe라 하더라도 페이지 I/O 지연시간은 $100\mu\text{s} \sim 10\text{ms}$에 달하며, 페이지 폴트가 발생할 때마다 스레드가 D-상태(Uninterruptible Sleep)에 빠져 P99 응답 시간이 수백 배 폭증합니다. 게다가 지속적인 스왑 쓰기로 인해 SSD 플래시 메모리의 쓰기 수명(TBW)이 급속도로 고갈됩니다.
2. **스왑을 껐을 때 (Swapoff & OOM Disaster)**:
   - 스왑을 비활성화(`swapoff -a`)하면 일시적인 버스트 메모리 요청에도 페이지 캐시만 강제 회수되다가 여유 메모리가 없으면 커널이 즉시 **OOM Killer**를 호출하여 주요 데이터베이스 프로세스를 사살합니다.

이에 엔지니어링 팀은 DRAM의 일부를 압축 캐시로 활용하는 리눅스 커널의 **압축 스왑(Compressed RAM Swap)** 기술(`zswap` 및 `zram`)을 도입하기로 결정했습니다.

```
[Linux Kernel Compressed Swap Architecture: zswap vs zram]

1. zram (RAM-based Compressed Block Device):
   User / VM Page ---> [ /dev/zram0 (Compressed in RAM) ] ---> (No backing disk by default)
                       * If RAM full: OOM Killer invocation!

2. zswap (Compressed Writeback Cache for Physical Swap):
   User / VM Page ---> [ zswap (Compressed RAM Pool) ] 
                               | (If pool full: LRU Writeback)
                               v
                       [ Physical Swap Disk (NVMe/SSD) ]
```

하지만 압축 스왑을 실제 운영 환경에 배포했을 때 잘못된 파라미터 조합으로 인해 다양한 성능 참사가 발생했습니다:
- **`zram` 무백업 OOM 참사 (`ZRAM_OUT_OF_MEMORY_NO_BACKING_STORE`)**: 백킹 스왑 디스크 없이 zram 용량을 초과하여 대량 스왑이 발생했을 때 OOM Killer가 격발됨.
- **비압축성 데이터 쓰레싱 (`INCOMPRESSIBLE_DATA_ZSWAP_BYPASS_THRASHING`)**: 암호화 데이터나 기압축 페이로드는 zswap 압축 시 용량이 줄지 않아 zswap이 처리를 거부(Reject/Bypass)하고 전량 물리 디스크로 밀어내어 CPU만 낭비됨.
- **`zbud` 할당자의 내부 단편화 조기 축출 (`ZBUD_ALLOCATOR_FRAGMENTATION_PREMATURE_EVICTION`)**: 페이지당 최대 2개 청크만 저장하는 `zbud`의 구조적 한계로 인해 압축률이 50%를 초과할 경우 페이지당 1개 청크만 담겨 50% 이상의 메모리가 낭비되고 조기 쓰기백이 폭증함.
- **zswap 백킹 디스크 부재 풀 고갈 (`ZSWAP_POOL_EXHAUSTION_NO_BACKING_SWAP`)**: zswap 풀이 찼으나 물리 스왑 디스크가 없어 더 이상 페이지를 비우지 못하고 OOM 크래시 발생.
- **과도한 쓰기백 지연 스톨 (`ZSWAP_POOL_SATURATION_WRITEBACK_STALL`)**: 풀 한도 초과로 인해 압축 해제 및 디스크 동기 쓰기백이 다량 발생하여 지연시간 증가.
- **최적 구성 (`OPTIMAL_ZSWAP_COMPRESSED_MEMORY_POOL`)**: `zswap` + `zsmalloc` + `LZ4` + NVMe 조합으로 100% 디스크 I/O 절감 및 서브마이크로초 초저지연 스왑 달성.

본 문제에서는 시스템 설정과 워크로드 특성에 따른 압축 스왑 메커니즘의 거동, 메모리 풀 소모량, 디스크 쓰기량 및 지연시간을 정밀하게 분석하는 시뮬레이터를 구현합니다.

---

## 2. 입력 형식 (Input Specification)

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "mechanism": "ZSWAP",
    "allocator": "ZSMALLOC",
    "compressor": "LZ4",
    "max_pool_percent": 25.0,
    "total_ram_mb": 8192.0,
    "swap_disk_type": "NVME"
  },
  "workload": {
    "swap_candidate_pages": 400000,
    "compressible_ratio": 0.30,
    "access_pattern": "RANDOM"
  }
}
```

### 필드 설명
- `config`:
  - `mechanism` (str): `"ZSWAP"`, `"ZRAM"`, `"TRADITIONAL_SWAP"`
  - `allocator` (str): `"ZSMALLOC"`, `"ZBUD"`, `"Z3FOLD"`, `"NONE"`
  - `compressor` (str): `"LZ4"`, `"ZSTD"`, `"NONE"`
  - `max_pool_percent` (float): zswap/zram이 사용할 수 있는 최대 메모리 풀 비율 (%)
  - `total_ram_mb` (float): 노드의 총 물리 메모리 크기 (MB)
  - `swap_disk_type` (str): `"NVME"`, `"SATA_SSD"`, `"NONE"`
- `workload`:
  - `swap_candidate_pages` (int): 스왑 아웃 요청된 4KB 익명 페이지 수
  - `compressible_ratio` (float): 원본 크기 대비 압축 후 크기 비율 (예: 0.30은 4KB가 1.2KB로 압축됨)
  - `access_pattern` (str): 접근 패턴 (`"RANDOM"`, `"TEMPORAL_LOCALITY"`)

---

## 3. 출력 형식 (Output Specification)

표준 출력(stdout)으로 다음 JSON 구조를 반환해야 합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_ZSWAP_COMPRESSED_MEMORY_POOL",
  "metrics": {
    "total_swap_candidate_mb": 1562.5,
    "zpool_used_mb": 515.62,
    "disk_write_mb": 0.0,
    "writeback_pages": 0,
    "swap_io_reduction_pct": 100.0,
    "avg_swap_latency_us": 3.5,
    "oom_killed": false
  }
}
```

### 상태(Status) 및 판정(Verdict) 규칙
1. **`mechanism == "TRADITIONAL_SWAP"`**:
   - 압축 없이 전량 스왑 디스크로 기록 (`disk_write_mb = total_swap_mb`, `zpool_used_mb = 0.0`)
   - 지연시간: NVME는 120.0$\mu\text{s}$, SATA_SSD는 850.0$\mu\text{s}$
   - `status`: `"WARNING"`, `verdict`: `"TRADITIONAL_SWAP_IO_BOTTLENECK"`
2. **`mechanism == "ZRAM"`**:
   - 필요한 풀 메모리가 `max_pool_mb`를 초과할 때:
     - `swap_disk_type == "NONE"`: 백킹 디스크 부재로 OOM Killer 격발 (`status`: `"FAILED"`, `verdict`: `"ZRAM_OUT_OF_MEMORY_NO_BACKING_STORE"`, `oom_killed`: `true`, `avg_swap_latency_us`: 9999.0)
     - `swap_disk_type != "NONE"`: 초과분이 백킹 디스크로 유출 (`status`: `"WARNING"`, `verdict`: `"ZRAM_BACKING_DEV_SPILLOVER"`)
   - 메모리가 충분한 경우:
     - `status`: `"SUCCESS"`, `verdict`: `"OPTIMAL_ZRAM_COMPRESSED_STORAGE"`, `avg_swap_latency_us`: 4.2
3. **`mechanism == "ZSWAP"`**:
   - `effective_ratio >= 0.90` (비압축성 데이터):
     - zswap이 압축 저장을 거부하고 물리 디스크로 직행 바이패스 (`zpool_used_mb = 0.0`, `disk_write_mb = total_swap_mb`)
     - `status`: `"FAILED"`, `verdict`: `"INCOMPRESSIBLE_DATA_ZSWAP_BYPASS_THRASHING"`
   - `allocator == "ZBUD"` 및 단편화로 인한 풀 초과:
     - `status`: `"FAILED"`, `verdict`: `"ZBUD_ALLOCATOR_FRAGMENTATION_PREMATURE_EVICTION"`
   - 풀 초과 시:
     - `swap_disk_type == "NONE"`: 쓰기백 불가능으로 OOM (`status`: `"FAILED"`, `verdict`: `"ZSWAP_POOL_EXHAUSTION_NO_BACKING_SWAP"`, `oom_killed`: `true`)
     - `swap_disk_type != "NONE"`: LRU 쓰기백 발생 (`status`: `"WARNING"`, `verdict`: `"ZSWAP_POOL_SATURATION_WRITEBACK_STALL"`)
   - 정상 수용 시:
     - `status`: `"SUCCESS"`, `verdict`: `"OPTIMAL_ZSWAP_COMPRESSED_MEMORY_POOL"` (LZ4: 3.5$\mu\text{s}$, ZSTD: 5.8$\mu\text{s}$)

---

## 4. 예제 입출력

### 예제 1 (입력)
```json
{
  "config": {
    "mechanism": "ZSWAP",
    "allocator": "ZSMALLOC",
    "compressor": "LZ4",
    "max_pool_percent": 25.0,
    "total_ram_mb": 8192.0,
    "swap_disk_type": "NVME"
  },
  "workload": {
    "swap_candidate_pages": 400000,
    "compressible_ratio": 0.30,
    "access_pattern": "RANDOM"
  }
}
```

### 예제 1 (출력)
```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_ZSWAP_COMPRESSED_MEMORY_POOL",
  "metrics": {
    "total_swap_candidate_mb": 1562.5,
    "zpool_used_mb": 515.62,
    "disk_write_mb": 0.0,
    "writeback_pages": 0,
    "swap_io_reduction_pct": 100.0,
    "avg_swap_latency_us": 3.5,
    "oom_killed": false
  }
}
```
