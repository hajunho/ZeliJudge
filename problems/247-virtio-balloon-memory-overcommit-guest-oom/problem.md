# 문제 247: Linux Kernel 가상화 — KVM/QEMU virtio-balloon 메모리 오버커밋 vs 게스트 OOM Killer, Direct Reclaim 지연 및 HugePage 단편화

## 1. 개요 (Incident Scenario)

엔터프라이즈 클라우드 인프라(KVM, QEMU, OpenStack, Proxmox, AWS Firecracker)에서는 물리 서버의 메모리 활용률을 극대화하기 위해 **메모리 오버커밋(Memory Overcommit)** 기법을 적극 활용합니다. 하이퍼바이저는 각 게스트 가상머신(Guest VM)의 메모리를 동적으로 회수(Reclaim)하고 반환하기 위해 반가상화(Paravirtualization) 드라이버인 **`virtio-balloon`** (`drivers/virtio/virtio_balloon.c`)을 사용합니다.

어느 날 대규모 클라우드 클러스터에서 호스트 노드의 물리 메모리가 부족해지자, 클러스터 오케스트레이터는 실행 중인 게스트 VM들의 virtio-balloon 타깃을 급격히 증가(Inflation)시켰습니다. 그러나 이 과정에서 예상치 못한 대형 장애가 발생했습니다:
1. **게스트 핵심 DB 프로세스 강제 종료 (OOM Killer Disaster)**: 호스트에는 여유 메모리가 있었음에도 불구하고, 게스트 내부에서 메모리 부족 상태가 발생하자 리눅스 커널의 OOM Killer가 실행되어 미션 크리티컬 데이터베이스(PostgreSQL, ClickHouse)가 `SIGKILL`로 즉시 사망했습니다.
2. **Direct Reclaim Latency 폭증 (I/O & CPU Freeze)**: 풍선 드라이버가 초당 기가바이트 단위로 급격히 팽창하면서, 게스트의 백그라운드 메모리 회수 데몬(`kswapd`)의 처리 속도를 압도했습니다. 이로 인해 모든 사용자 스레드가 동기식 페이지 회수 루프(**Direct Reclaim**)에 빠져 p99 응답 지연 시간이 수 초 이상 치솟았습니다.
3. **Transparent HugePage (THP) 파괴 및 TLB Thrashing**: 2MB 단위로 매핑되어 있던 게스트의 HugePage들이 4KB 단위의 풍선 메모리 할당 요구에 의해 산산조각(Shatter)나며 TLB 미스율이 15배 이상 폭증하고 전반적인 처리량이 급락했습니다.
4. **호스트-게스트 이중 스왑(Double Swapping) 지옥**: 게스트 스왑이 활성화된 상태에서 호스트와 게스트가 서로의 스왑 공간을 연쇄적으로 스왑 아웃/인하는 '이중 페이징' 현상이 발생해 가상 디스크 I/O가 100% 포화되고 시스템이 멈췄습니다.

당신은 가상화 인프라 및 리눅스 커널 코어 엔지니어로서, 주어진 게스트 VM 구성, 프로세스 메모리 프로파일, 초기 메모리 상태, 그리고 하이퍼바이저 및 게스트 이벤트 스트림을 바탕으로 virtio-balloon의 상태 전이 및 메모리 할당/회수 메커니즘을 정밀 시뮬레이션하고, 근본 장애 원인(Root Cause)을 진단하며 최적의 엔터프라이즈 완화책(Actionable Recommendations)을 도출해야 합니다.

---

## 2. 가상화 메모리 모델 및 상태 머신 (Architectural State Machine)

```
       [ Host Physical RAM (HPA) ]
                ▲
                │  madvise(MADV_DONTNEED)
       [ QEMU / KVM Hypervisor ]
                ▲
         virtqueue (inflateq / deflateq)
                │
   ══════════════════════════════════════════════════════════════════
   [ Guest OS (Linux Kernel) ]
   
    ┌─────────────────────────────────────────────────────────────┐
    │                      Total RAM (16GB)                       │
    ├──────────────┬──────────────┬───────────────┬───────────────┤
    │ Free Pages   │ Page Cache   │ Process RSS   │ virtio-balloon│
    │ (min_free)   │ (clean/dirty)│ (THP 2MB/4KB) │ (Locked PFNs) │
    └──────┬───────┴──────┬───────┴───────┬───────┴───────┬───────┘
           │              │               │               │
           ▼              ▼               │               ▼
    [ alloc_pages ] [ kswapd / Direct ]   │       [ Host Memory ]
           │        [   Reclaim       ]   │       [  Reclaimed  ]
           │                              ▼
           └──────────────► [ OOM Killer ] ◄── (deflate-on-oom: OFF)
                                  │
                                  ▼
                         [ Victim Process Kill ]
```

### (1) 메모리 회수 및 할당 규칙
- **가용 메모리 할당 우선순위**:
  1. `usable_free = max(0, free_ram_mb - min_free_kbytes_mb)`: 워터마크 여유 공간에서 우선 차감.
  2. `clean_cache = max(0, page_cache_mb - dirty_cache_mb)`: 여유 메모리가 부족하면 Clean Page Cache를 즉시 해제. (해제량이 $\ge 512	ext{MB}$이거나 추가 메모리가 계속 필요하면 `direct_reclaim_stalls += 1`).
  3. `guest_swap_mb`: 게스트 스왑 공간이 있고 `swappiness > 0`인 경우 익명 페이지를 스왑 아웃. 이때 호스트 스왑(`host_swap_used_mb > 0`)도 이미 발생 중이면 **`double_swapping_detected = true`**.
  4. `deflate_on_oom`: 만약 프로세스 메모리 할당(`PROCESS_ALLOC_BURST`) 도중 메모리가 고갈되었고, `deflate_on_oom == true`라면 virtio-balloon이 즉시 자동 수축(Deflation)하여 부족분을 게스트에게 반환하고 OOM Kill을 방지함.
  5. **OOM Killer 발동**: 위 단계로도 메모리를 확보하지 못한 경우 `out_of_memory()`가 호출됨.

### (2) Linux OOM Score 계산 및 희생자(Victim) 선정 공식
각 생존 프로세스의 OOM 점수는 표준 리눅스 공식에 따라 산출됩니다:
$$	ext{points} = \lfloor rac{	ext{rss\_mb} 	imes 1000}{	ext{total\_ram\_mb}} floor + 	ext{oom\_score\_adj}$$
- `oom_score_adj == -1000`인 프로세스는 **절대 종료되지 않음 (OOM Unkillable)**.
- 유효 OOM 점수는 $[0, 1000]$ 범위로 클램핑됩니다.
- 점수가 가장 높은 프로세스가 희생자로 선정되어 `SIGKILL`을 수신하고, 그 프로세스의 전체 `rss_mb`가 `free_ram_mb`로 즉시 반환됩니다. 점수가 동일할 경우 PID가 더 큰 프로세스가 선택됩니다.
- 한 번의 킬로도 부족할 경우 다음 순위 프로세스를 연쇄적으로 종료합니다.

### (3) Balloon 팽창 및 THP 단편화
- `max_inflation_rate_mb_per_sec > 0`인 경우, 초당 팽창량이 이 한도를 초과하면 `direct_reclaim_stalls += 1`이 기록됩니다.
- `thp_enabled == true`이고 `balloon_granularity == "4KB"`인 경우, 풍선이 4KB 단위로 페이지를 요구하면서 연속된 2MB HugePage가 분할(Shatter)됩니다:
  $$	ext{shattered\_thp\_count} = \min(	ext{balloon\_delta\_mb}, \sum 	ext{thp\_mb}) // 2$$
- 반면 `balloon_granularity == "2MB"`(virtio-mem 호환 모드)인 경우 HugePage가 파괴되지 않고 정렬이 유지됩니다.

---

## 3. 입력 사양 (Input Specification)

표준 입력(`sys.stdin`)으로 단일 JSON 객체가 전달됩니다:

```json
{
  "vm_config": {
    "total_ram_mb": 16384,
    "thp_enabled": true,
    "deflate_on_oom": false,
    "balloon_granularity": "4KB",
    "guest_swap_mb": 0,
    "swappiness": 0,
    "min_free_kbytes_mb": 256,
    "max_inflation_rate_mb_per_sec": 0
  },
  "processes": [
    {"pid": 1001, "name": "postgres", "rss_mb": 8192, "oom_score_adj": 0, "thp_mb": 4096},
    {"pid": 1002, "name": "java_app", "rss_mb": 4096, "oom_score_adj": 100, "thp_mb": 2048},
    {"pid": 1003, "name": "exporter", "rss_mb": 256, "oom_score_adj": 500, "thp_mb": 0}
  ],
  "initial_state": {
    "balloon_inflated_mb": 1024,
    "page_cache_mb": 2048,
    "dirty_cache_mb": 512,
    "free_ram_mb": 864,
    "guest_swap_used_mb": 0,
    "host_free_ram_mb": 1024,
    "host_swap_used_mb": 0
  },
  "events": [
    {
      "time_sec": 1,
      "type": "BALLOON_TARGET_UPDATE",
      "target_balloon_mb": 3072
    },
    {
      "time_sec": 2,
      "type": "PROCESS_ALLOC_BURST",
      "pid": 1001,
      "alloc_mb": 2048,
      "is_thp": false
    }
  ]
}
```

---

## 4. 출력 사양 (Output Specification)

표준 출력(`sys.stdout`)으로 다음 필드를 포함하는 JSON 객체를 출력합니다:

```json
{
  "final_state": {
    "balloon_inflated_mb": 3072,
    "free_ram_mb": 6752,
    "page_cache_mb": 512,
    "guest_swap_used_mb": 0,
    "host_swap_used_mb": 0
  },
  "metrics": {
    "direct_reclaim_stalls": 2,
    "oom_killed_pids": [1003, 1001],
    "thp_shattered_count_2mb": 1024,
    "double_swapping_detected": false
  },
  "living_processes": [
    {
      "pid": 1002,
      "name": "java_app",
      "rss_mb": 4096
    }
  ],
  "root_cause": "GUEST_OOM_KILL_DUE_TO_DISABLED_DEFLATE_ON_OOM",
  "recommendations": [
    "ENABLE_VIRTIO_BALLOON_DEFLATE_ON_OOM",
    "RATE_LIMIT_INFLATION_STEPS",
    "MIGRATE_TO_VIRTIO_MEM_PRESERVE_THP"
  ]
}
```

### 진단 규칙 (Root Cause Hierarchy)
1. `len(oom_killed_pids) > 0` $ightarrow$ `"GUEST_OOM_KILL_DUE_TO_DISABLED_DEFLATE_ON_OOM"`
2. `double_swapping_detected == true` $ightarrow$ `"HOST_GUEST_DOUBLE_SWAP_THRASHING"`
3. `direct_reclaim_stalls >= 2` 또는 (`max_inflation_rate == 0` and `direct_reclaim_stalls >= 1`) $ightarrow$ `"BALLOON_RAPID_INFLATION_DIRECT_RECLAIM_STALL"`
4. `thp_shattered_count_2mb >= 512` $ightarrow$ `"THP_SHATTERING_TLB_PERFORMANCE_DEGRADATION"`
5. 기타 정상 상태 $ightarrow$ `"STABLE_BALLOON_OPERATION"`

### 권고사항 (Actionable Recommendations)
- `deflate_on_oom == false`인 경우: `"ENABLE_VIRTIO_BALLOON_DEFLATE_ON_OOM"`
- `max_inflation_rate_mb_per_sec == 0`인 경우: `"RATE_LIMIT_INFLATION_STEPS"`
- `granularity == "4KB"`이고 `thp_enabled == true`인 경우: `"MIGRATE_TO_VIRTIO_MEM_PRESERVE_THP"`
- `guest_swap_total > 0`인 경우: `"DISABLE_GUEST_SWAP_UNDER_OVERCOMMIT"`
- 아무 플래그도 해당하지 않을 경우: `["MONITOR_BALLOON_AND_COMPACT_MEMORY"]`
