# 문제 418: Linux 커널 메모리 관리 및 RAS(신뢰성·가용성) MCE 하드웨어 메모리 장애 격리 및 memory_failure 페이지 복구 엔진

## 문제 설명

하이퍼스케일 클라우드 데이터센터(AWS, Google Cloud, Meta)와 수천 대의 물리 노드를 운영하는 고성능 컴퓨팅(HPC) 클러스터에서 서버 다운타임의 가장 빈번한 원인은 **DRAM 하드웨어 메모리 오류**입니다.
우주 방사선(Cosmic Rays)에 의한 소프트 에러, 물리적 실리콘 노화, 전압 변동, 그리고 인접 셀 간섭(Rowhammer) 등으로 인해 메모리 컨트롤러는 복구 불가능한 다중 비트 ECC 에러(**UCE, Uncorrectable Error**)를 감지합니다.

과거 레거시 리눅스 커널에서는 UCE가 발생하는 순간, 시스템 전체를 즉시 중단시키는 **커널 패닉 (Kernel Panic)** 또는 하드웨어 리셋을 유발했습니다.
이로 인해 손상된 단 1개의 4KB 메모리 페이지 때문에 해당 물리 서버에서 실행 중이던 수백 개의 무관한 가상 머신(VM)과 컨테이너가 한순간에 전멸하는 대규모 서비스 장애가 발생했습니다.

이 문제를 종식시키고 클라우드 서버의 고가용성(RAS: Reliability, Availability, Serviceability)을 보장하기 위해 리눅스 커널 2.6.32에 도입되고 5.x~6.x에 걸쳐 완성된 핵심 메모리 서브시스템이 바로 **`memory_failure` 하드웨어 메모리 장애 격리 엔진 (`mm/memory-failure.c`, `arch/x86/kernel/cpu/mce/core.c`, `CONFIG_MEMORY_FAILURE`)**입니다.

---

### MCE 및 `memory_failure()` 복구 상태 머신

하드웨어 메모리 컨트롤러가 2비트 이상의 ECC 오류를 감지하면 CPU는 **머신 체크 예외 (`#MC`, Machine Check Exception, Vector 18)**를 발생시키며 캐시라인에 포이즌(Poison) 비트를 마킹합니다.
리눅스 커널은 해당 물리 프레임 번호(PFN)를 전달받아 `memory_failure(pfn, flags)`를 호출하며, **손상된 페이지의 종류와 상태에 따라 차별화된 복구 정책을 실행**합니다:

1. **유휴 버디 페이지 (`FREE_BUDDY`)**:
   - 현재 어떤 프로세스나 커널도 사용하고 있지 않은 버디 할당자의 프리 리스트(Free List)에 있는 페이지입니다.
   - **복구 전략**: 버디 프리 리스트에서 해당 페이지를 안전하게 적출(`take_page_off_buddy`)한 후 영구 격리(`HWPOISON`) 풀로 이동시킵니다.
   - **결과**: **어떤 프로세스도 사살하지 않고(0 tasks killed) 100% 무손실 복구**됩니다.

2. **클린 페이지 캐시 (`CLEAN_PAGECACHE`)**:
   - 파일 백업(File-backed) 메모리로, 내용이 백엔드 스토리지(NVMe/SSD)와 완전히 동기화되어 있는 클린 페이지입니다.
   - **복구 전략**: 디스크에 원본 데이터가 안전하게 보존되어 있으므로, 페이지 테이블 매핑을 해제(`try_to_unmap`)하고 페이지 캐시 인덱스 트리(XArray)에서 손상된 페이지를 무효화(Evict)합니다.
   - **결과**: **프로세스를 종료하지 않고 무손실 복구**됩니다. 이후 프로세스가 해당 파일 영역을 다시 읽으려 하면 디스크로부터 깨끗한 새 물리 페이지로 온디맨드 리필됩니다!

3. **더티 페이지 캐시 (`DIRTY_PAGECACHE`)**:
   - 메모리에서 수정되었으나 아직 디스크로 플러시되지 않은 페이지입니다.
   - **복구 전략**: 디스크에 최신 데이터가 없고 메모리 내용도 파괴되었으므로 미반영 데이터가 영구 유실됩니다. 커널은 손상된 페이지를 격리하고, 해당 페이지를 매핑하고 있던 프로세스들에게 하드웨어 에러 시그널 **`SIGBUS`**를 발송하여 안전하게 사살(Terminate)합니다.

4. **사용자 익명 메모리 (`ANONYMOUS`)**:
   - 사용자 프로세스의 힙(Heap), 스택(Stack), BSS 영역 등 디스크 백업이 없는 순수 인메모리 데이터입니다.
   - **복구 전략**: 페이지 테이블 매핑을 끊고(`try_to_unmap`), `PG_hwpoison`을 설정한 뒤 해당 메모리에 접근한 태스크에 **`SIGBUS`**를 전송합니다.
     - **동기적 접근 (`SYNC_ACCESS`)**: 실행 중이던 CPU 코어가 직접 손상된 메모리를 로드(`mov`)하여 `#MC`가 발생한 경우, 원인이 된 스레드에 **`si_code = BUS_MCEERR_AR` (Action Required)**를 전송하여 즉각 사살합니다.
     - **비동기 스크러버 (`PATROL_SCRUBBER`)**: 백그라운드 메모리 패트롤 스크러버가 유휴 상태에서 에러를 먼저 발견한 경우, 해당 페이지를 매핑한 프로세스들에 **`si_code = BUS_MCEERR_AO` (Action Optional)**를 통지합니다.

5. **커널 핵심 슬랩 및 예약 메모리 (`SLAB_KERNEL`, `RESERVED_KERNEL`)**:
   - 커널 내부 메타데이터, 페이지 테이블 페이지, 또는 커널 실행 코드가 손상된 경우입니다.
   - **복구 전략**: 커널 메모리의 손상은 시스템 전체의 보안 및 무결성을 보장할 수 없으므로, 즉시 **`panic("Fatal machine check on kernel memory")`**을 호출하여 시스템을 패닉시킵니다.

6. **선제적 소프트 오프라인 (`soft_offline_page`)**:
   - 메모리 모듈에서 단일 비트 정정 가능 오류(CE, Correctable Error) 빈도가 임계치를 초과할 때 호출됩니다.
   - 완전한 하드웨어 장애(UCE)가 터지기 전에 **정상 메모리 내용을 예비 페이지(Spare PFN)로 사전 마이그레이션**하고 노화된 원본 물리 페이지를 오프라인(`HWPOISON_OFFLINE`)으로 안전하게 격리합니다 (제로 다운타임!).

여러분은 리눅스 커널 `mm/memory-failure.c`의 페이지 유형별 정밀 상태 머신, 클린 캐시 무손실 퇴출, 익명 메모리 `BUS_MCEERR_AR`/`AO` 시그널 디스패치, 커널 메모리 패닉 처리, 그리고 선제적 소프트 오프라인 마이그레이션 엔진을 구현해야 합니다.

---

## 시스템 아키텍처 다이어그램

```
+==================================================================================================+
|                 Linux Kernel Memory Failure & MCE Poison Recovery Architecture                   |
+==================================================================================================+

   [ Hardware DRAM Error (Cosmic Ray / Silicon Wearout / Rowhammer) ]
                                |
                                | Multi-bit Uncorrectable Error (UCE)
                                v
               [ CPU Hardware MCE Interrupt (#MC) ]
                                |
                                | Calls memory_failure(pfn, flags)
                                v
 +-------------------------------------------------------------------------------------------------+
 | mm/memory-failure.c : Page State Machine & Recovery Decision Tree                               |
 +-------------------------------------------------------------------------------------------------+
                                |
        +-----------------------+-----------------------+-----------------------+
        |                       |                       |                       |
        v                       v                       v                       v
 [ FREE_BUDDY ]         [ CLEAN_PAGECACHE ]      [ DIRTY_PAGECACHE /     [ KERNEL_SLAB /
                                                    ANONYMOUS ]             RESERVED ]
        |                       |                       |                       |
        | take_page_off_buddy   | Invalidate XArray     | try_to_unmap(page)    | Unrecoverable!
        | Quarantined!          | Evicted from Cache!   | Deliver SIGBUS        |
        v                       v                       v                       v
 (0 Tasks Killed)        (0 Tasks Killed)        (Target Tasks Killed)   (KERNEL PANIC!)
 100% Zero-Loss          Reloadable from NVMe    BUS_MCEERR_AR / AO      System Halts
 Quarantined             Cleanly Recovered       Graceful Isolation
 +-------------------------------------------------------------------------------------------------+
 | Proactive Maintenance: soft_offline_page(source_pfn, spare_pfn)                                |
 |   - Correctable Error Threshold Exceeded -> Migrate Page Data -> Offline Source PFN             |
 +-------------------------------------------------------------------------------------------------+
```

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "config": {
    "total_pages": 128,
    "panic_on_kernel_error": true
  },
  "trace": [
    {"time": 0, "type": "ALLOC_PAGE", "pfn": 20, "page_type": "CLEAN_PAGECACHE", "pids": [101], "inode": 5001},
    {"time": 1, "type": "MCE_INJECT_ERROR", "pfn": 20, "severity": "UCE", "trigger": "SYNC_ACCESS", "accessing_pid": 101}
  ]
}
```

- `config.total_pages`: 시스템 전체 물리 페이지(PFN) 수.
- `config.panic_on_kernel_error`: 커널 메모리 손상 시 커널 패닉 발생 여부 (기본 true).
- `trace`: 시간 순서대로 실행되는 이벤트 리스트:
  - `ALLOC_PAGE`: `{"time": t, "type": "ALLOC_PAGE", "pfn": p, "page_type": "...", "pids": [...], "inode": n}`
  - `DIRTY_PAGE`: `{"time": t, "type": "DIRTY_PAGE", "pfn": p}`
  - `FREE_PAGE`: `{"time": t, "type": "FREE_PAGE", "pfn": p}`
  - `MCE_INJECT_ERROR`: `{"time": t, "type": "MCE_INJECT_ERROR", "pfn": p, "severity": "UCE", "trigger": "SYNC_ACCESS" | "PATROL_SCRUBBER", "accessing_pid": pid}`
  - `SOFT_OFFLINE_PAGE`: `{"time": t, "type": "SOFT_OFFLINE_PAGE", "pfn": src, "spare_pfn": dst}`

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 JSON 객체를 한 줄로 출력합니다 (compact JSON, `ensure_ascii=False`):

```json
{
  "summary": {
    "total_mce_events": 1,
    "pages_hwpoisoned": 1,
    "clean_cache_evictions": 1,
    "free_pages_isolated": 0,
    "tasks_killed": 0,
    "soft_offlines_succeeded": 0,
    "kernel_panics": 0,
    "system_panicked": false
  },
  "killed_pids": [],
  "recovery_logs": [
    {
      "time": 1,
      "pfn": 20,
      "original_state": "CLEAN_PAGECACHE",
      "severity": "UCE",
      "trigger": "SYNC_ACCESS",
      "action": "EVICTED_CLEAN_CACHE",
      "result": "SUCCESS",
      "killed_tasks": []
    }
  ],
  "event_logs": [ ... ]
}
```
