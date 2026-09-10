# Linux Kernel Device Mapper Multipath (dm-multipath) ALUA Priority Groups & Path Selector Failover Engine

> **실무/시니어 트랙 #351 / 누적 842문제 달성!**  
> *엔터프라이즈 스토리지 SAN/NVMe-oF 인프라의 핵심 가용성 중추: SCSI ALUA(Asymmetric Logical Unit Access) 타깃 포트 그룹 상태 머신, service-time / queue-length 동적 경로 선택자 및 queue_if_no_path 장애 복구 엔진 (`drivers/md/dm-mpath.c`, `drivers/md/dm-path-selector.c`)*

---

## 1. 개요 및 배경

엔터프라이즈 데이터 센터와 클라우드 인프라에서 단일 서버와 대용량 스토리지 어레이(SAN, NVMe-oF, iSCSI, Fibre Channel) 사이의 연결은 절대로 단일 케이블이나 단일 HBA(Host Bus Adapter)에 의존하지 않습니다. 케이블 단선, 스위치 고장, HBA 펌웨어 충돌, 스토리지 컨트롤러 장애가 발생하더라도 I/O가 영구 중단되지 않도록 **다중 물리적 경로(Multipath)**를 구성합니다.

리눅스 커널의 **Device Mapper Multipath (`dm-multipath`, `drivers/md/dm-mpath.c`)**는 하위의 개별 블록 디바이스(예: `/dev/sda`, `/dev/sdb`, `/dev/sdc`, `/dev/sdd`)들을 하나의 가상 블록 디바이스(예: `/dev/mapper/mpatha`)로 추상화하여 제공합니다.

`dm-multipath` 아키텍처의 핵심 축은 다음과 같습니다:

1. **SCSI ALUA (Asymmetric Logical Unit Access - SPC-3 / SPC-4)**:
   - 현대의 액티브-액티브 스토리지 어레이는 컨트롤러 간 내부 캐시 동기화를 수행하지만, 특정 LUN(Logical Unit)의 소유권은 특정 컨트롤러에 최적화되어 있습니다.
   - 각 타깃 포트 그룹(Target Port Group, TPG)은 다음과 같은 우선순위 상태를 가집니다:
     - `active/optimized` (선호 컨트롤러 직접 경로, 최고 우선순위)
     - `active/non-optimized` (피어 컨트롤러 경유 경로, CMI 인터스위치 링크 오버헤드 존재, 차순위)
     - `standby` (대기 경로, I/O 불가)
     - `unavailable` (오프라인)
   - `dm-multipath`는 우선순위가 가장 높은 활성 우선순위 그룹(Priority Group, PG)을 선택하여 I/O를 전송합니다.

2. **동적 경로 선택자 (Path Selectors - `dm-path-selector.c`)**:
   - 동일한 활성 우선순위 그룹 내에 여러 경로가 존재할 때, I/O를 어떻게 분배할 것인가를 결정합니다:
     - `round-robin`: 활성 경로들에 순차적으로 균등 배분.
     - `queue-length`: 현재 처리 중인 인플라이트 I/O 수(`inflight_ios`)가 가장 적은 경로 선택.
     - `service-time`: 경로별 대역폭 가중치 대비 잔여 바이트 비율($\frac{\text{inflight\_bytes}}{\text{throughput\_weight}}$)이 가장 낮은 경로를 선택하여, 32Gbps FC와 16Gbps FC가 혼재된 이종 네트워크에서 대역폭을 극대화.

3. **페일오버(Failover) 및 페일백(Failback)**:
   - 활성 그룹의 모든 경로가 장애(`PATH_DOWN`)를 일으키면 차순위 그룹으로 즉시 전환(Failover)합니다.
   - 고우선순위 주 경로가 복구되면 설정(`failback: immediate`)에 따라 다시 주 그룹으로 자동 복귀(Failback)합니다.

4. **`queue_if_no_path` (경로 전멸 시 완충 vs 고속 실패)**:
   - 모든 경로가 동시에 다운되었을 때:
     - `queue_if_no_path: true`: 애플리케이션에 I/O 에러를 던지지 않고 메모리 큐에 대기(Suspension)시켰다가, 경로 복구 시 일괄 플러시하여 서비스 무중단을 유지합니다.
     - `queue_if_no_path: false`: 즉각적으로 `-EIO` (I/O Failure) 에러를 애플리케이션으로 반환(Fail-Fast)합니다.

본 과제에서는 리눅스 커널 `drivers/md/dm-mpath.c`의 핵심 메커니즘을 모델링하여, 다중 ALUA 우선순위 그룹, 다양한 경로 선택 정책(`round-robin`, `queue-length`, `service-time`), 경로 상태 전이 및 I/O 큐잉/완충을 완벽하게 시뮬레이션하는 **Device Mapper Multipath 엔진**을 구현합니다.

---

## 2. 시스템 아키텍처 및 I/O 파이프라인

```
+-------------------------------------------------------------------------+
|             User / Application I/O (/dev/mapper/mpatha)                 |
+-------------------------------------------------------------------------+
                                   |
                                   v
+-------------------------------------------------------------------------+
| [1단계] 우선순위 그룹 (Priority Group, PG) 관리 및 페일오버              |
|   · 모든 PG 중 최소 1개 이상의 UP 경로를 가진 최고 우선순위 그룹 탐색   |
|   · 주 PG 경로 전멸 시 -> 차순위 PG로 즉각 페일오버 (Failover)          |
|   · 고우선순위 PG 경로 복구 시 -> 즉각 페일백 (Failback)                |
|   · 모든 경로 다운 시 -> queue_if_no_path에 따라 큐잉 또는 -EIO 실패    |
+-------------------------------------------------------------------------+
                                   | (Active PG 선택 완료)
                                   v
+-------------------------------------------------------------------------+
| [2단계] 동적 경로 선택자 (Path Selector Algorithm)                      |
|   · round-robin: active_paths[rr_pointer % len(active_paths)]          |
|   · queue-length: min(active_paths, key=inflight_ios)                   |
|   · service-time: min(active_paths, key=inflight_bytes / weight)        |
+-------------------------------------------------------------------------+
                                   | (선택된 단일 물리 경로: sda, sdc 등)
                                   v
+-------------------------------------------------------------------------+
| [3단계] I/O 디스패치 및 인플라이트 상태 갱신                            |
|   · path.inflight_ios += 1, path.inflight_bytes += io.bytes             |
|   · 완료(completion) 이벤트 시 inflight 카운터 자동 차감                |
+-------------------------------------------------------------------------+
```

---

## 3. 핵심 규칙 및 알고리즘 명세

### 3.1 우선순위 그룹(PG) 정렬 및 선정
- `priority_groups` 리스트의 각 그룹은 `pg_id`, `alua_state`, `priority` (정수), `paths` 리스트를 가집니다.
- 그룹들을 `priority` 내림차순(높은 우선순위가 먼저 오도록)으로 정렬합니다.
- 매 타임스텝마다 현재 상태가 `UP`인 경로를 하나라도 포함하는 가장 높은 `priority`의 그룹을 **활성 그룹(`current_active_pg_id`)**으로 선택합니다.
- 만약 활성 가능한 그룹이 없다면 `current_active_pg_id = None`이 됩니다.

### 3.2 경로 선택 정책 (`path_selector`)
활성 그룹에 속한 `UP` 상태의 경로 리스트 `active_up_paths` 중에서 하나를 선택합니다:
1. `"round-robin"`:
   - 포인터 인덱스를 순환하며 선택: `active_up_paths[rr_pointer % len(active_up_paths)]`. 선택 후 `rr_pointer += 1`.
2. `"queue-length"`:
   - `inflight_ios`가 가장 작은 경로 선택 (동률 시 `path_id` 사전순).
3. `"service-time"`:
   - $rac{	ext{inflight\_bytes}}{	ext{throughput\_weight}}$ 비율이 가장 작은 경로 선택 (동률 시 `path_id` 사전순).

### 3.3 타임라인 단계별 실행 순서
매 스텝은 다음 순서로 엄격히 처리됩니다:
1. **완료 이벤트 (`completed_ios`)**:
   - 완료된 I/O의 `path_id`와 `bytes`를 찾아 `inflight_ios = max(0, inflight_ios - 1)`, `inflight_bytes = max(0, inflight_bytes - bytes)`로 갱신.
2. **경로 링크 상태 이벤트 (`path_events`)**:
   - `new_state` ("UP" 또는 "DOWN")를 반영.
3. **활성 PG 결정**:
   - 우선순위 평가 후 PG 전환 여부(`pg_switched`) 판단.
4. **I/O 디스패칭**:
   - 기존 대기 큐(`queued_ios`)에 현재 스텝의 신규 유입 I/O(`incoming_ios`)를 병합하여 처리.
   - 가용 경로가 없는 경우:
     - `queue_if_no_path == true`: `queued_ios`에 보관 유지.
     - `queue_if_no_path == false`: 실패 리스트(`failed_step`)에 `FAILED_EIO` 기록.
   - 가용 경로가 있는 경우:
     - 선택자 알고리즘에 따라 경로 배정 후 인플라이트 및 누적 통계 갱신.

---

## 4. 입출력 형식 및 제약 조건

### 입력 형식 (JSON)
```json
{
  "multipath_config": {
    "queue_if_no_path": true,
    "path_selector": "round-robin",
    "failback": "immediate"
  },
  "priority_groups": [
    {
      "pg_id": "PG_OPT",
      "alua_state": "active/optimized",
      "priority": 50,
      "paths": [
        {"path_id": "sda", "initial_state": "UP", "throughput_weight": 100},
        {"path_id": "sdb", "initial_state": "UP", "throughput_weight": 100}
      ]
    }
  ],
  "events_and_io_timeline": [
    {
      "step": 1,
      "path_events": [],
      "incoming_ios": [{"io_id": "IO_1", "bytes": 4096}],
      "completed_ios": []
    }
  ]
}
```

### 출력 형식 (JSON)
```json
{
  "mpath_summary": {
    "selector_policy": "round-robin",
    "total_steps": 1,
    "total_ios_dispatched": 1,
    "total_bytes_dispatched": 4096,
    "final_active_pg": "PG_OPT",
    "final_queued_ios_count": 0
  },
  "path_statistics": {
    "sda": {
      "path_id": "sda",
      "pg_id": "PG_OPT",
      "alua_state": "active/optimized",
      "priority": 50,
      "state": "UP",
      "throughput_weight": 100,
      "inflight_ios": 1,
      "inflight_bytes": 4096,
      "total_dispatched_ios": 1,
      "total_dispatched_bytes": 4096
    },
    "sdb": { ... }
  },
  "timeline_trace": [
    {
      "step": 1,
      "active_pg": "PG_OPT",
      "pg_switched": false,
      "available_paths_count": 2,
      "dispatched_count": 1,
      "queued_count": 0,
      "failed_count": 0,
      "dispatches": [
        {
          "io_id": "IO_1",
          "dispatched_path": "sda",
          "pg_id": "PG_OPT",
          "bytes": 4096
        }
      ],
      "failed_ios": []
    }
  ]
}
```

### 제약 조건
- $1 \le \text{len(priority\_groups)} \le 16$
- $1 \le \text{total\_paths} \le 64$
- $1 \le \text{len(events\_and\_io\_timeline)} \le 100$
- $1 \le \text{throughput\_weight} \le 1000$
- $512 \le \text{io.bytes} \le 10^7$
