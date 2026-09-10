# 문제 303: 리눅스 커널 페이지 캐시 쓰기백 및 더티 쓰로틀링 엔진 (Linux Kernel Page Cache Writeback & Dirty Throttling Engine)

## 문제 설명

리눅스 커널 가상 메모리 및 파일 시스템 서브시스템(`mm/page-writeback.c`, `fs/fs-writeback.c`)은 고속 I/O 처리를 위해 애플리케이션의 `write(2)` 시스템 콜 요청을 즉시 스토리지 미디어에 기록하지 않고 메모리의 **페이지 캐시(Page Cache)**에 버퍼링합니다. 이 과정에서 수정된 페이지는 더티(`PG_dirty`) 상태가 됩니다.

만약 프로세스들이 디스크의 물리적 쓰기 속도보다 훨씬 빠른 속도로 메모리에 쓰기 작업을 쏟아부으면, 시스템의 가용 메모리가 순식간에 고갈되고 결국 OOM-Killer가 호출되거나 I/O 기아 현상이 발생합니다.

리눅스 커널은 이를 방어하기 위해 다음과 같은 3계층 쓰기백 및 쓰로틀링 메커니즘을 운영합니다:

1. **비동기 백그라운드 플러시 임계치 (`dirty_background_ratio` / `dirty_background_bytes`)**:
   - 시스템 전체 더티 페이지 수가 이 임계치를 초과하면, 커널 백그라운드 플러셔 스레드(`wb_workfn` / `bdi_writeback`)가 깨어나 디스크 대역폭에 맞춰 비동기적으로 페이지를 플러시(`CLEAN` 상태로 전이)합니다. 이때 사용자 프로세스는 블로킹되지 않습니다.
2. **동기적 프로세스 쓰로틀링 임계치 (`dirty_ratio` / `dirty_bytes`)**:
   - 디스크 쓰기 속도가 유입 속도를 따라가지 못해 더티 페이지 수가 하드 임계치를 넘어서면, 쓰기를 시도하는 사용자 프로세스는 `balance_dirty_pages()` 내부에서 강제로 일시 정지(Throttling/Sleep)되어 디스크 I/O가 따라잡을 때까지 블로킹됩니다.
3. **주기적 노화 플러시 (`dirty_expire_interval`)**:
   - 임계치를 넘지 않더라도, 더티 상태로 머문 시간이 만료 시간(`dirty_expire_ms`)을 초과한 페이지는 정전 시 데이터 손실을 최소화하기 위해 최우선 플러시 대상으로 선정됩니다.
4. **동기적 플러시 (`fsync(2)`)**:
   - 특정 파일(아이노드)에 대해 즉시 모든 더티 페이지를 디스크로 강제 플러시합니다.

본 문제에서는 리눅스 커널 `mm/page-writeback.c`의 핵심 로직을 모델링하여, 시간 경과(Tick)와 사용자 쓰기(`WRITE`), 동기화(`FSYNC`) 명령어 스트림을 처리하고 더티 페이지 수명 주기 및 프로세스 쓰로틀링 상태를 시뮬레이션하는 **페이지 캐시 쓰기백 엔진**을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 다음과 같은 단일 JSON 객체가 주어집니다:

```json
{
  "total_ram_pages": 10,
  "dirty_background_ratio_pct": 20,
  "dirty_ratio_pct": 40,
  "dirty_expire_ms": 5000,
  "commands": [
    {"op": "WRITE", "pid": 101, "page_id": 1, "inode": 10},
    {"op": "WRITE", "pid": 101, "page_id": 2, "inode": 10},
    {"op": "TICK", "elapsed_ms": 1000, "disk_write_rate_pages_per_sec": 2}
  ]
}
```

- `total_ram_pages`: 시스템 전체 RAM 페이지 수 ($1 \le \text{total\_ram\_pages} \le 10^5$).
- `dirty_background_ratio_pct`: 백그라운드 플러셔 기동 더티 비율 정수 백분율 (기본 20%).
  - $\text{dirty\_background\_pages} = \lfloor \text{total\_ram\_pages} \times \text{dirty\_background\_ratio\_pct} / 100 \rfloor$
- `dirty_ratio_pct`: 동기 쓰로틀링 발생 더티 비율 정수 백분율 (기본 40%).
  - $\text{dirty\_threshold\_pages} = \lfloor \text{total\_ram\_pages} \times \text{dirty\_ratio\_pct} / 100 \rfloor$
- `dirty_expire_ms`: 더티 페이지 만료 시간 (밀리초 단위).
- `commands`: 실행할 명령어 리스트:
  - `WRITE`: `{"op": "WRITE", "pid": int, "page_id": int, "inode": int}`
  - `TICK`: `{"op": "TICK", "elapsed_ms": int, "disk_write_rate_pages_per_sec": int}`
  - `FSYNC`: `{"op": "FSYNC", "inode": int}`

---

## 출력 형식

표준 출력(stdout)으로 다음 구조를 갖는 단일 JSON 객체를 한 줄로 출력합니다:

```json
{
  "command_results": [
    {
      "op": "WRITE",
      "result": {
        "page_id": 1,
        "dirty_count": 1,
        "throttled": false,
        "background_woken": false
      }
    },
    {
      "op": "WRITE",
      "result": {
        "page_id": 2,
        "dirty_count": 2,
        "throttled": false,
        "background_woken": true
      }
    },
    {
      "op": "TICK",
      "result": {
        "current_time_ms": 1000,
        "flushed_pages": [1, 2],
        "remaining_dirty": 0,
        "throttled_pids": []
      }
    }
  ],
  "final_summary": {
    "total_pages_in_cache": 2,
    "dirty_pages": 0,
    "total_flushed_count": 2,
    "throttled_pids": [],
    "final_time_ms": 1000
  }
}
```

---

## 제약 사항

- $1 \le \text{total\_ram\_pages} \le 10^5$
- $1 \le \text{commands} \le 1000$
- $1 \le \text{disk\_write\_rate\_pages\_per\_sec} \le 10^6$
- 플러시 우선순위: 만료(Expired) 페이지 우선 $\to$ 그 다음 오래된 더티 타임(`dirty_time`) 순 $\to$ `page_id` 오름차순.
- 메모리 제한: 512 MB
- 실행 시간 제한: 3.0 초
