# Problem #438: 리눅스 커널 블록 레이어: block/blk-wbt.c 비동기 라이트백 스로틀링(Writeback Throttling / WBT) 및 읽기 지연 시간 기반 큐 깊이 동적 적응 스케일러

## 🌟 개요 (Executive Summary)
리눅스 커널의 블록 I/O 계층에서 백그라운드 플러시 워커(`kworker/flush`)나 더티 페이지 캐시 대량 동기화가 발생할 때, 수 기가바이트의 비동기 쓰기 요청이 스토리지 디바이스 큐(NVMe Submission Queue, SATA NCQ)를 순식간에 가득 채우는 **스토리지 버퍼블로트(Storage Bufferbloat)** 현상이 발생합니다.
이로 인해 포그라운드 사용자 프로세스(데이터베이스 인덱스 읽기, 웹 서버 응답, 대화형 셸)가 발주하는 동기식 읽기(READ) 요청이 방대한 쓰기 버퍼 뒤에 갇혀 **헤드-오브-라인 블로킹(Head-of-Line Blocking)**을 겪게 되며, 정상적인 50µs 읽기 지연 시간이 수 초(Seconds) 단위로 치솟아 시스템 체감 성능이 완전히 마비됩니다.

리눅스 커널 블록 레이어 메인테이너 Jens Axboe는 이를 해결하기 위해 **WBT (Writeback Throttling / `block/blk-wbt.c`, `block/blk-wbt.h`)**를 설계하였습니다:
- **I/O 스트림의 엄격한 분리**:
  - `READ`: 사용자의 실시간 작업에 직결되므로 절대로 스로틀링하지 않고 즉시 디바이스로 디스패치하며, 완료 시점의 지연 시간(소요 시간 $\mu s$)을 윈도우 샘플러에 수집합니다.
  - `SYNC_WRITE`: 저널링 커밋이나 `O_SYNC`/`fsync` 같은 동기식 쓰기로 포그라운드 지연에 민감하므로 스로틀링 대상에서 제외합니다.
  - `WB_WRITE`: 백그라운드 비동기 라이트백 요청으로, 현재 유효 큐 깊이(`cur_depth`) 한도 내에서만 발행을 허용하며 초과 시 대기 큐(`pending_wb_queue`)에 적재하여 슬립시킵니다.
- **슬라이딩 윈도우 지연 시간 샘플링 및 백분위 판정**:
  - 일정 시간 윈도우 동안 수집된 읽기 완료 지연 시간의 상위 백분위(P90) 값을 산출하여 관리자가 설정한 목표 지연 시간(`target_lat_us`, 예: NVMe SSD 2ms, HDD 75ms)과 비교합니다.
- **AIMD 스타일 적응형 큐 깊이 제어 (Adaptive Queue Scaling)**:
  - **지연 시간 위반 (Congestion Shock)**: P90 읽기 지연 시간이 목표치를 초과하면 스토리지 큐가 쓰기 I/O로 포화된 것으로 판단하고, 라이트백 큐 깊이를 절반으로 급격히 축소(`cur_depth = max(min_depth, cur_depth // 2)`)하여 쓰기 압력을 즉각 완화합니다.
  - **지연 시간 안정 (Healthy Recovery)**: 읽기 지연 시간이 목표치 이하로 안정되면 윈도우마다 점진적으로 큐 깊이를 단계적 확장(`cur_depth = min(max_depth, cur_depth + step_scale)`)하여 스토리지의 쓰기 처리량을 최대로 회복시킵니다.
- **대기 큐 공정 디스패치 (Fair Wakeup)**:
  - 기존 비동기 쓰기 I/O가 완료되거나 윈도우 확장에 의해 슬롯 여유가 생기면, 대기 중이던 비동기 쓰기 I/O를 FIFO 순서대로 즉시 깨워 디바이스로 발행합니다.

본 문제에서는 리눅스 커널 `block/blk-wbt.c`의 읽기 지연 시간 샘플링, 적응형 큐 깊이 제어(AIMD), I/O 분류 및 대기 큐 디스패치 엔진을 시뮬레이션합니다.

---

## 🏗️ 아키텍처 및 시스템 흐름도 (System Architecture)

```
                       [ Incoming Bio Request ]
                                   │
                           Bio Type Check
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
           [ READ ]          [ SYNC_WRITE ]        [ WB_WRITE ]
              │                    │                    │
      inflight_reads++     inflight_sync_writes++       │
      SUBMITTED_IMMEDIATE  SUBMITTED_SYNC               │
              │                    │                    ▼
              │                    │         inflight_wb < cur_depth?
              │                    │               ┌────┴────┐
              │                    │              Yes        No
              │                    │               │         │
              │                    │               ▼         ▼
              │                    │        inflight_wb++  [ Push to Pending ]
              │                    │        SUBMITTED_WB   THROTTLED_WAITING
              │                    │               │         │
              ▼                    ▼               ▼         ▼
      ────────────────── Storage Controller Device ───────────────────
                                   │
                          [ COMPLETE_BIO ]
                                   │
              ┌────────────────────┴────────────────────┐
              ▼                                         ▼
         [ READ Done ]                            [ WB Done ]
      inflight_reads--                         inflight_wb--
      record duration_us to window_samples     If pending & inflight < cur_depth:
                                                  Pop pending bio & dispatch!
                                                  inflight_wb++
 ─────────────────────────────────────────────────────────────────────────────
                          [ STEP_WINDOW ]
   Evaluate window_samples (P90 vs target_lat_us):
   - If P90 > target_lat_us: cur_depth = max(min_depth, cur_depth // 2) [SCALED_DOWN]
   - If P90 <= target_lat_us: cur_depth = min(max_depth, cur_depth + step) [SCALED_UP]
   - If samples == 0: [WINDOW_IDLE]
   Dispatch any pending bios if new cur_depth > inflight_wb!
```

---

## ⚙️ I/O 데이터 규격 (Input/Output Specifications)

### 1. 입력 JSON 구조
```json
{
  "config": {
    "target_lat_us": 2000,
    "min_depth": 2,
    "max_depth": 32,
    "step_scale": 2
  },
  "trace": [
    {"op": "SUBMIT_BIO", "bio_id": "WB_1", "type": "WB_WRITE", "timestamp_us": 100},
    {"op": "SUBMIT_BIO", "bio_id": "READ_1", "type": "READ", "timestamp_us": 150},
    {"op": "COMPLETE_BIO", "bio_id": "READ_1", "completion_us": 1150},
    {"op": "STEP_WINDOW"},
    {"op": "COMPLETE_BIO", "bio_id": "WB_1", "completion_us": 2000},
    {"op": "GET_STATS"}
  ]
}
```

### 2. 필드 정의
- `config`:
  - `target_lat_us` (int, default=2000): 목표 읽기 지연 시간 ($\mu s$). 초과 시 혼잡으로 간주.
  - `min_depth` (int, default=2): 비동기 라이트백 큐 깊이 최소 하한값 (기아 방지).
  - `max_depth` (int, default=32): 비동기 라이트백 큐 깊이 최대 상한값.
  - `step_scale` (int, default=2): 안정 상태에서 윈도우마다 큐 깊이를 증량하는 단계 크기.
- `trace` 명령어:
  1. `SUBMIT_BIO`:
     - `bio_id` (str): I/O 식별자.
     - `type` (str): `"READ"`, `"SYNC_WRITE"`, `"WB_WRITE"` 중 하나.
     - `timestamp_us` (int): 요청 제출 타임스탬프 ($\mu s$).
  2. `COMPLETE_BIO`:
     - `bio_id` (str): 완료된 I/O 식별자.
     - `completion_us` (int): 요청 완료 타임스탬프 ($\mu s$).
  3. `STEP_WINDOW`:
     - 현재 윈도우 동안 수집된 읽기 샘플의 P90 지연 시간을 평가하여 큐 깊이 조정.
  4. `GET_STATS`:
     - 현재 누적 통계 조회.

### 3. 출력 JSON 구조
```json
{
  "events": [
    {
      "op": "SUBMIT_BIO",
      "bio_id": "WB_1",
      "type": "WB_WRITE",
      "status": "SUBMITTED_WB",
      "inflight_wb_writes": 1,
      "cur_depth": 32
    },
    ...
  ],
  "summary": {
    "final_cur_depth": 32,
    "total_reads_completed": 1,
    "total_wb_completed": 1,
    "total_throttled_events": 0,
    "scale_down_count": 0,
    "scale_up_count": 0,
    "remaining_pending_wb": 0
  }
}
```
