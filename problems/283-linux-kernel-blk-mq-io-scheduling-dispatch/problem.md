# 문제 283: 리눅스 커널 blk-mq 멀티큐 I/O 스케줄링 & 하드웨어 디스패치 엔진 (Linux Kernel blk-mq Multi-Queue I/O Scheduling & Dispatch Engine)

## 문제 설명

전통적인 리눅스 커널의 단일 큐 블록 계층(Single Request Queue Block Layer, `struct request_queue`)은 단일 전역 스핀락(`queue_lock`)으로 모든 I/O 요청을 동기화했습니다. 과거 회전식 하드 디스크(HDD) 시절에는 초당 입출력 횟수(IOPS)가 수백 건 수준이었으므로 전역 락이 병목이 되지 않았으나, 수백만 IOPS와 수십 개의 하드웨어 큐를 지원하는 초고속 NVMe SSD와 수십~수백 코어의 NUMA 멀티코어 서버가 등장하면서 극심한 락 경합(Lock Contention)과 CPU 캐시 바운싱으로 인해 성능이 급격히 저하되었습니다.

이를 해결하기 위해 옌스 악스보(Jens Axboe)는 리눅스 3.13 커널에서 **`blk-mq` (Block Multi-Queue)** 아키텍처를 도입했습니다. `blk-mq`는 블록 계층을 2단계 큐(Two-Level Queue) 구조로 전면 혁신하였습니다:

1. **소프트웨어 스테이징 큐 (Software Staging Queues, `struct blk_mq_ctx`)**:
   - 각 CPU 코어마다 독립적인 `per-CPU` 큐를 할당합니다.
   - I/O 제출 시 다른 CPU 코어와 전역 락 경합 없이 순수 로컬 연산으로 bio를 요청(`struct request`)으로 변환합니다.
2. **태스크 플러그 및 섹터 병합 (Task Plugs & Bio Merging, `struct blk_plug`)**:
   - `blk_start_plug()`와 `blk_finish_plug()`를 통해 태스크 수준에서 연속된 bio들을 배치(batch)로 모아 병합합니다.
   - **Back Merge**: 기존 request의 끝 섹터와 새 bio의 시작 섹터가 일치할 때 (`req.end_sector == bio.sector`)
   - **Front Merge**: 새 bio의 끝 섹터와 기존 request의 시작 섹터가 일치할 때 (`bio.sector + bio.nr_sectors == req.start_sector`)
   - **최대 섹터 제한 (`max_sectors`)**: 단일 request의 총 섹터 수가 하드웨어 허용치(`max_sectors`)를 초과하지 않도록 병합을 제한합니다.
3. **하드웨어 디스패치 큐 (Hardware Dispatch Queues, `struct blk_mq_hw_ctx`)**:
   - 실제 스토리지 컨트롤러(NVMe)의 하드웨어 제출 큐(Submission Queue)와 1:1 또는 N:1로 매핑됩니다(`cpu_to_hw_map`).
   - 각 하드웨어 큐는 유한한 하드웨어 태그(`0 .. queue_depth-1`)를 가집니다.
   - 태그 고갈 시 `BLK_STS_RESOURCE`(혼잡/자원 부족)가 발생하며 요청은 하드웨어 디스패치 대기열에 머무릅니다.
4. **I/O 스케줄러 (`NONE` vs `MQ-DEADLINE`)**:
   - `NONE`: 소프트웨어 큐에서 넘어온 요청을 순서대로 즉시 하드웨어에 디스패치합니다.
   - `MQ-DEADLINE`: 읽기(`READ`)와 쓰기(`WRITE`) 요청에 서로 다른 만료 기한(`deadline = submit_ts + expire_delta`)을 부여합니다. 만료된 요청(`deadline <= current_ts`)이 발생하면 만료 기한 오름차순으로 최우선 디스패치하며, 만료 요청이 없을 경우 읽기 요청을 쓰기 요청보다 우선하고 섹터 번호 오름차순(엘리베이터 정렬)으로 디스패치합니다.
5. **비동기 요청 완료 처리 (`blk_mq_complete_request`)**:
   - 디바이스가 I/O 처리를 완료하면 하드웨어 태그가 회수(`free_tags`)되고 요청 레이턴시(`complete_ts - submit_ts`)를 기록합니다.

당신은 리눅스 커널의 `blk-mq` 코어 서브시스템을 시뮬레이션하는 결정론적 엔진을 구현해야 합니다.

---

## 입력 형식 (JSON)

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "config": {
    "num_cpus": 4,
    "num_hw_queues": 2,
    "cpu_to_hw_map": [0, 0, 1, 1],
    "queue_depth": 4,
    "max_sectors": 128,
    "scheduler": "MQ-DEADLINE",
    "read_expire_us": 500,
    "write_expire_us": 5000
  },
  "operations": [
    {
      "step": 1,
      "op": "START_PLUG",
      "cpu_id": 0
    },
    {
      "step": 2,
      "op": "SUBMIT_BIO",
      "cpu_id": 0,
      "bio_id": "bio-1",
      "type": "READ",
      "sector": 100,
      "nr_sectors": 16,
      "timestamp": 1000
    },
    {
      "step": 3,
      "op": "FINISH_PLUG",
      "cpu_id": 0
    },
    {
      "step": 4,
      "op": "DISPATCH_HW",
      "timestamp": 1050
    },
    {
      "step": 5,
      "op": "COMPLETE_REQUEST",
      "hctx_id": 0,
      "hw_tag": 0,
      "timestamp": 1200
    },
    {
      "step": 6,
      "op": "GET_SNAPSHOT"
    }
  ]
}
```

### 연산 종류
1. `START_PLUG`: 지정된 `cpu_id`에서 태스크 플러그를 활성화합니다.
2. `SUBMIT_BIO`: bio를 제출합니다. 플러그가 활성화되어 있으면 플러그 리스트에서, 플러그가 없으면 해당 CPU의 소프트웨어 스테이징 큐(`sw_queues`)에서 병합을 시도하고, 병합 불가 시 새 `REQ-xxxx` 요청을 생성합니다.
3. `FINISH_PLUG`: 플러그 리스트에 쌓인 모든 요청을 해당 CPU의 `sw_queues`로 일괄 플러시하고 플러그를 해제합니다.
4. `DISPATCH_HW`: 모든 CPU의 소프트웨어 큐 요청들을 매핑된 하드웨어 큐(`cpu_to_hw_map`)의 `dispatch_list`로 이동시킨 후, 스케줄러 정책에 따라 태그(`0 .. queue_depth-1`)를 할당하여 `in_flight`로 디스패치합니다. 사용 가능한 태그가 없으면 디스패치를 멈추고 `tag_starvation_events`를 1 증가시킵니다.
5. `COMPLETE_REQUEST`: 지정된 하드웨어 큐(`hctx_id`)의 특정 태그(`hw_tag`)의 처리를 완료하고 태그를 회수하며 레이턴시를 기록합니다.
6. `GET_SNAPSHOT`: 현재 전체 큐 상태 및 통계 스냅샷을 캡처합니다.

---

## 출력 형식 (JSON)

표준 출력(stdout)으로 다음 스키마를 만족하는 단일 줄 JSON 객체를 출력합니다.

```json
{
  "operations_log": [
    {
      "step": 1,
      "op": "START_PLUG",
      "cpu_id": 0,
      "success": true
    },
    {
      "step": 2,
      "op": "SUBMIT_BIO",
      "action": "PLUGGED_NEW_REQ",
      "req_id": "REQ-0001",
      "bio_id": "bio-1",
      "target": "PLUG"
    }
  ],
  "final_state": {
    "sw_queues": {
      "cpu_0": {
        "plugged_count": 0,
        "is_plugged": false,
        "sw_queue_count": 0
      }
    },
    "hw_queues": {
      "hctx_0": {
        "in_flight_count": 0,
        "free_tags_count": 4,
        "pending_dispatch_count": 0,
        "active_tags": []
      }
    },
    "metrics": {
      "total_bios_submitted": 1,
      "front_merges": 0,
      "back_merges": 0,
      "total_merges": 0,
      "requests_dispatched": 1,
      "requests_completed": 1,
      "read_requests_completed": 1,
      "write_requests_completed": 0,
      "tag_starvation_events": 0,
      "avg_latency_us": 200.0
    }
  }
}
```

---

## 제약 조건

- CPU 코어 수: $1 \le \text{num\_cpus} \le 16$
- 하드웨어 큐 수: $1 \le \text{num\_hw\_queues} \le 8$
- 하드웨어 큐 깊이(`queue_depth`): $1 \le \text{queue\_depth} \le 64$
- `cpu_to_hw_map`: 길이 `num_cpus`의 배열, 각 원소 $0 \le \text{hctx\_id} < \text{num\_hw\_queues}$
- 연산 수: $1 \le M \le 100$
- 모든 타임스탬프는 마이크로초($\mu s$) 단위의 정수.
- `avg_latency_us`는 소수점 둘째 자리까지 반올림(`round(val, 2)`). 완료된 요청이 없을 경우 `0.0`.
