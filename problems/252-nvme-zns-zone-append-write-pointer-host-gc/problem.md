# 문제 252: Linux Storage & Flash Architecture — NVMe ZNS (Zoned Namespaces) 순차 쓰기 포인터 위반, Zone Append 락프리 동시성 및 호스트 주도 가비지 컬렉션(Host GC)

## 1. 개요 (Incident Scenario)

하이퍼스케일 클라우드 데이터센터와 초고성능 LSM-Tree 스토리지 엔진(RocksDB ZenFS, Ceph Crimson)에서는 기존 NVMe SSD의 고질적인 문제인 FTL(Flash Translation Layer) 오버헤드, 쓰기 증폭(WAF, Write Amplification Factor $> 3.0$), 그리고 드라이브 내부 GC에 의한 극심한 테일 레이턴시 스파이크($p99.99 > 50	ext{ms}$)를 원천 박멸하기 위해 **NVMe ZNS(Zoned Namespaces, NVMe 2.0 / TP 4053)** SSD를 도입했습니다.

ZNS SSD는 드라이브 내부의 복잡한 FTL 주소 변환 계층을 제거하고, 전체 저장 공간을 수 기가바이트 단위의 고정 크기 **Zone(존)**들로 분할하여 호스트에게 노출합니다. 각 존 내부에서는 데이터가 반드시 **Write Pointer(WP, 쓰기 포인터)** 위치에서부터 엄격한 순차 쓰기(Strict Sequential Write)로만 기록되어야 합니다.

그러나 대규모 분산 스토리지 노드를 ZNS 기반으로 전환하는 과정에서 치명적인 I/O 장애가 발생했습니다:
1. **멀티스레드 쓰기 포인터 위반 참사 (`NVME_SC_ZONE_INVALID_WRITE`)**: 기존 블록 디바이스용 드라이버가 다중 스레드 환경에서 종래의 `NVME_NVM_CMD_WRITE` 명령을 사용했습니다. 각 스레드가 로컬에서 계산한 타깃 LBA로 동시에 쓰기를 요청했으나, 스케줄링 레이스 컨디션으로 인해 패킷 도착 순서가 뒤바뀌면서 쓰기 포인터와 타깃 LBA가 불일치하여 드라이브 컨트롤러가 요청을 `0x2DF (Invalid Write Pointer)` 에러로 거부했습니다.
2. **컨트롤러 활성 존 자원 고갈 (`NVME_SC_ZONE_TOO_MANY_OPEN / ACTIVE`)**: 애플리케이션이 이전 존을 닫지 않은 채 동시에 수많은 존을 열어 쓰기를 시도하다가, 하드웨어 컨트롤러의 최대 오픈 존 제한(`max_open_zones`, MOR) 및 최대 활성 존 제한(`max_active_zones`, MAR)을 초과하여 `0x2DA` 에러가 발생했습니다.
3. **호스트 주도 GC(Host GC) 기아로 인한 전체 쓰기 정체 (Zone Exhaustion Write Stall)**: ZNS는 제자리 덮어쓰기(In-place Overwrite)가 불가능하므로, 삭제된 데이터가 누적되어 존이 가득 차면(`state: FULL`), 호스트가 직접 유효 데이터를 새 존으로 복사(Compaction)한 뒤 해당 존에 **`Zone Reset`** 명령을 내려 물리 블록을 지워야 합니다. 그러나 호스트 GC 스케줄러가 지연되면서 모든 존이 무효 데이터로 꽉 차 가용 존이 0개가 되어 전체 쓰기가 완전히 멈췄습니다.

당신은 NVMe 스토리지 아키텍트이자 리눅스 블록 계층 엔지니어로서, ZNS 구성, 초기 존 상태, 그리고 쓰기/GC 이벤트 스트림을 바탕으로 ZNS 컨트롤러, Write Pointer 전진, Zone Append 원자적 할당, 활성 존 자원 관리 및 Host GC 메커니즘을 정확하게 시뮬레이션하고, 장애 근본 원인(Root Cause)과 최적의 아키텍처 완화책을 도출해야 합니다.

---

## 2. 아키텍처 및 상태 머신 (System Architecture & State Machine)

```
 [ Multi-Threaded Host Application (RocksDB ZenFS / Ceph) ]
         │ Thread A (Write 128MB)         │ Thread B (Write 128MB)
         ▼                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ Race Condition with Conventional Write (NVME_NVM_CMD_WRITE) │
 │ - Thread B packet arrives before Thread A!                  │
 │ - Target LBA (256) != Current WP (128)                      │
 │ ==> NVME_SC_ZONE_INVALID_WRITE (0x2DF) Error!               │
 └──────────────────────────────┬──────────────────────────────┘
                                │
               ┌────────────────┴────────────────┐
               ▼                                 ▼
   [ Conventional Write Mode ]         [ Zone Append Command ]
   - Host specifies Target LBA         - Host specifies Zone Start LBA (ZSLBA)
   - Race condition causes errors!     - Drive atomically assigns WP & returns LBA!
                                       - 100% Lockless Parallelism!

 ══════════════════════════════════════════════════════════════════════════
 [ NVMe ZNS Zone State Machine ]
 
   [EMPTY] ──(Write / Open)──► [OPEN (Explicit/Implicit)] ──► [CLOSED]
      ▲                               │                          │
      │                               ▼                          ▼
   [ZONE RESET] ◄────────────── [FULL (WP = Capacity)] ◄─────────┘
   (Host GC: Copy valid data -> Zone Reset)
```

### (1) 쓰기 모드 및 Write Pointer(WP) 전진 규칙
- `CONVENTIONAL_WRITE`:
  - 호스트가 지정한 `target_lba_mb`가 존의 현재 `wp_mb`와 정확히 일치해야 함.
  - 불일치 시 `wp_violation_errors += 1`이 기록되고 쓰기 실패.
- `ZONE_APPEND`:
  - 호스트는 존의 시작 LBA(`ZSLBA`)로 명령을 전송.
  - NVMe 컨트롤러가 하드웨어 내부에서 현재 `wp_mb`에 데이터를 원자적으로 기록하고 `wp_mb += size_mb` 전진. 락 경합 없는 완전한 동시성 보장.
- `wp_mb == zone_capacity_mb`에 도달하면 존 상태는 `FULL`로 전이됨.

### (2) 존 자원 제한 (Active / Open Limits)
- `max_open_zones (MOR)`: 동시에 `OPEN` 상태에 머무를 수 있는 최대 존 수.
- `max_active_zones (MAR)`: 동시에 `OPEN` 또는 `CLOSED` 상태에 머무를 수 있는 최대 존 수.
- 한도 초과 시 `zone_resource_errors += 1`이 발생하고 명령이 거부됨.

### (3) 호스트 주도 가비지 컬렉션 (Host GC) 및 Zone Reset 규칙
- `TRIGGER_HOST_GC`:
  - `state == FULL`인 존 중 무효 데이터 비율($1.0 - 	ext{valid\_mb} / 	ext{capacity}$)이 `gc_threshold_ratio` 이상인 존을 희생 존(Victim)으로 선정.
  - 유효 데이터(`valid_mb > 0`)가 남아있는 경우, 비어있거나 열려있는 다른 존으로 유효 데이터를 복사(`gc_relocated_mb += valid_mb`).
  - 복사할 여유 존이 없으면 `free_zone_exhaustion_stalls += 1`.
  - 데이터 복사 완료 후 컨트롤러에 `ZONE_RESET`을 전송하여 `wp_mb = 0, valid_mb = 0, state = EMPTY`로 재설정하고 `zones_reset_count += 1`.

---

## 3. 입력 사양 (Input Specification)

표준 입력(`sys.stdin`)으로 다음 구조의 JSON 객체가 주어집니다:

```json
{
  "zns_config": {
    "num_zones": 4,
    "zone_capacity_mb": 1024,
    "max_open_zones": 4,
    "max_active_zones": 4,
    "write_command_mode": "CONVENTIONAL_WRITE",
    "gc_threshold_ratio": 0.5,
    "gc_rate_limit_mb_per_sec": 512
  },
  "initial_zones": [
    {"zone_id": 0, "wp_mb": 256, "valid_mb": 256, "state": "EXPLICITLY_OPEN"}
  ],
  "events": [
    {
      "time_sec": 1,
      "type": "CONCURRENT_WRITE",
      "zone_id": 0,
      "writes": [
        {"thread_id": 101, "size_mb": 128, "target_lba_mb": 256},
        {"thread_id": 102, "size_mb": 128, "target_lba_mb": 256}
      ]
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
    "num_empty_zones": 3,
    "num_full_zones": 0,
    "num_open_zones": 1,
    "total_valid_data_mb": 384
  },
  "metrics": {
    "successful_writes": 1,
    "wp_violation_errors": 1,
    "zone_resource_errors": 0,
    "gc_runs": 0,
    "zones_reset_count": 0,
    "gc_relocated_mb": 0,
    "free_zone_exhaustion_stalls": 0
  },
  "root_cause": "ZONE_WRITE_POINTER_VIOLATION_CONVENTIONAL_WRITE_RACE",
  "recommendations": [
    "MIGRATE_TO_NVME_ZONE_APPEND_COMMAND",
    "ENFORCE_ZONE_LIFECYCLE_CLOSE_INACTIVE_ZONES",
    "CONFIGURE_BACKGROUND_HOST_ZONE_COMPACTION"
  ]
}
```

### 진단 규칙 (Root Cause Hierarchy)
1. `wp_violation_errors > 0` $ightarrow$ `"ZONE_WRITE_POINTER_VIOLATION_CONVENTIONAL_WRITE_RACE"`
2. `zone_resource_errors > 0` $ightarrow$ `"NVME_ZONE_RESOURCE_EXHAUSTION_TOO_MANY_ACTIVE_OPEN"`
3. `free_zone_exhaustion_stalls > 0` $ightarrow$ `"HOST_GC_STARVATION_ZONE_EXHAUSTION_WRITE_STALL"`
4. 기타 정상 상태 $ightarrow$ `"STABLE_NVME_ZNS_LOCKLESS_OPERATION"`

### 권고사항 도출 규칙
- `write_mode == "CONVENTIONAL_WRITE"`: `"MIGRATE_TO_NVME_ZONE_APPEND_COMMAND"`
- `zone_resource_errors > 0` 또는 `max_open < 8`: `"ENFORCE_ZONE_LIFECYCLE_CLOSE_INACTIVE_ZONES"`
- `free_zone_exhaustion_stalls > 0` 또는 `zones_reset_count == 0`: `"CONFIGURE_BACKGROUND_HOST_ZONE_COMPACTION"`
- 해당 사항이 없으면: `["MAINTAIN_CURRENT_ZNS_STORAGE_PIPELINE"]`
