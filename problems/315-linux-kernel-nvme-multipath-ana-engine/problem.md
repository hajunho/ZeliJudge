# 리눅스 커널 NVMe 네이티브 멀티패스 ANA 장애복구 및 I/O 경로 선택 엔진 (Linux Kernel NVMe Multipath ANA Failover Engine)

## 문제 설명

초대규모 엔터프라이즈 SAN 및 클라우드 스토리지 아키텍처(All-Flash Array, Ceph, NVMe-oF)에서는 고가용성(High Availability, HA)과 단일 장애점(SPOF) 제거를 위해 단일 NVMe 네임스페이스(블록 디바이스)에 다수의 네트워크 경로(Controller Paths)를 연결하는 **멀티패스(Multipathing)** 기술을 사용합니다.

과거에는 범용 SCSI 계층 기반의 `dm-multipath`(Device Mapper Multipath) 데몬을 사용했으나, 사용자 공간 데몬(`multipathd`)의 폴링 오버헤드와 락 경합으로 인해 마이크로초(µs) 수준의 초저지연을 제공하는 NVMe 하드웨어의 성능을 온전히 활용하지 못했습니다.

리눅스 커널 4.15부터 도입된 **NVMe 네이티브 멀티패스 서브시스템(`drivers/nvme/host/multipath.c`)**은 블록 계층(`blk-mq`) 수준에서 NVMe 사양의 **비대칭 네임스페이스 접근(Asymmetric Namespace Access, ANA - NVMe TP 4004)** 표준을 커널 네이티브로 직접 처리합니다.

```
+---------------------------------------------------------------------------------+
|                       NVMe 네이티브 멀티패스 아키텍처                           |
+---------------------------------------------------------------------------------+
| Application / VFS Filesystem Layer (I/O Request: /dev/nvme0n1)                  |
+---------------------------------------------------------------------------------+
                                         |
                                         v
+---------------------------------------------------------------------------------+
| nvme_find_path() / I/O Policy Selector (drivers/nvme/host/multipath.c)          |
| - round-robin: 가용 OPTIMIZED 경로 간 균등 순환 분배                            |
| - queue-depth: 현재 실행 중인 인플라이트 I/O(min_inflight)가 가장 적은 경로 선택|
+---------------------------------------------------------------------------------+
          |                                                    |
          v (우선 경로: OPTIMIZED)                             v (예비 경로: NON_OPTIMIZED)
+------------------------------------+               +----------------------------+
| Controller 1 (PCIe / RoCE Path)    |               | Controller 2 (Cross-link)  |
| ANA State: OPTIMIZED (로컬 고속)   |               | ANA State: NON_OPTIMIZED   |
+------------------------------------+               +----------------------------+
          |                                                    |
          +------------------------+---------------------------+
                                   |
                                   v
          [ I/O 실패 시: nvme_failover_req() & Requeue 메커니즘 ]
          - 경로 장애(NVME_SC_ANA_INACCESSIBLE / HOST_PATH_ERROR) 감지
          - 에러를 애플리케이션에 반환하지 않고 내부 requeue_list로 자동 회수!
          - alternative 경로로 즉각 투명 페일오버(Transparent Failover) 재시도
          - 모든 경로 두절 시 재시도 한도(max_retries) 초과 시에만 최종 EIO 반환
```

### 1. ANA(Asymmetric Namespace Access) 5대 상태
NVMe-oF 타깃 스토리지 어레이는 컨트롤러별로 각 네임스페이스에 대해 다음 5가지 ANA 상태를 비동기 이벤트(AEN) 및 로그 페이지(`NVME_LOG_ANA`)로 호스트에 통보합니다:
1. **`OPTIMIZED`**: 네임스페이스에 대한 직접적이고 최적화된 고속 경로 (기본 우선 선택).
2. **`NON_OPTIMIZED`**: 스토리지 컨트롤러 간 내부 인터커넥트(Cross-link)를 경유하여 접근 가능한 대체 경로 (OPTIMIZED 경로가 없을 때 폴백 선택).
3. **`INACCESSIBLE`**: 네트워크 케이블 단선, 포트 다운, 컨트롤러 재부팅 등으로 일시적 접근 불가 (I/O 투입 차단 및 재큐잉).
4. **`PERSISTENT_LOSS`**: 하드웨어 고장 등으로 인한 영구적 경로 상실.
5. **`CHANGE`**: 비대칭 접근 상태가 동적으로 변경 중인 과도기적 상태.

본 문제는 리눅스 커널 NVMe 멀티패스의 I/O 정책(`round-robin`, `queue-depth`), ANA 상태 기반 우선순위 경로 선택, 경로 장애 감지 시의 투명한 인-플라이트 요청 회수 및 페일오버(`failover_req`), 재큐잉 큐 버퍼링 및 재배포 엔진을 충실하게 구현하는 것입니다.

---

## 알고리즘 및 상태 전이 명세

### 1. 경로 선택 알고리즘 (`select_path`)
1. **우선순위 계층 탐색**:
   - 1순위: `ana_state == "OPTIMIZED"` 인 컨트롤러 집합.
   - 2순위 (OPTIMIZED 경로 전무 시): `ana_state == "NON_OPTIMIZED"` 인 컨트롤러 집합.
   - 가용 경로가 전혀 없는 경우: `None` 반환 (요청은 `requeue_queue`로 이동).
2. **이전 실패 경로 배제**:
   - 현재 I/O 요청의 이번 재시도 주기에서 이미 실패한 경로(`failed_paths`)를 후보에서 제외합니다.
3. **I/O 정책(iopolicy) 적용**:
   - `"queue-depth"`: 가용 후보 컨트롤러 중 `inflight` 수가 가장 작은 컨트롤러 선택 (동률 시 `ctrl_id` 오름차순).
   - `"round-robin"`: 가용 후보 컨트롤러 목록을 `rr_index`를 이용하여 라운드로빈 순환 선택.

### 2. I/O 제출 및 완료
- `SUBMIT_IO`:
  - 경로 선택 성공: `ctrl["inflight"] += 1`, `ctrl["total_ios"] += 1`, 상태 `"IN_FLIGHT"` 설정.
  - 경로 선택 실패: `req["status"] = "REQUEUED"`, `requeue_queue`에 추가.
- `COMPLETE_IO`:
  - 할당된 컨트롤러의 `inflight`를 1 감소시키고 `completed_ios`에 성공 기록.

### 3. 경로 장애 및 페일오버 (`FAIL_PATH`)
- `FAIL_PATH`:
  - 할당된 컨트롤러의 `inflight` 1 감소, `failed_ios` 1 증가.
  - 요청의 `retries += 1`, 실패 경로를 `failed_paths`에 추가.
  - `retries > max_retries` 인 경우: 영구 실패(`FAILED_EIO`) 처리.
  - 그 외: `select_path(req)`를 호출하여 대체 경로 탐색.
    - 대체 경로 발견 시: 즉각 페일오버(`FAILOVER_RETRY`), 신규 컨트롤러에 배정.
    - 대체 경로 부재 시: `requeue_queue`에 삽입 대기.

### 4. 재큐잉 큐 처리 (`DRAIN_REQUEUE`)
- 컨트롤러 상태가 복구되었을 때 대기 중인 `requeue_queue`의 요청들을 순차적으로 재배정하여 `IN_FLIGHT` 상태로 전이합니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 전달됩니다:

```json
{
  "config": {
    "iopolicy": "round-robin",
    "max_retries": 3,
    "controllers": [
      {"ctrl_id": 1, "ana_state": "OPTIMIZED"},
      {"ctrl_id": 2, "ana_state": "OPTIMIZED"}
    ]
  },
  "operations": [
    {"op": "SUBMIT_IO", "io_id": 101},
    {"op": "SUBMIT_IO", "io_id": 102},
    {"op": "FAIL_PATH", "io_id": 101, "error_status": "NVME_SC_ANA_INACCESSIBLE"},
    {"op": "COMPLETE_IO", "io_id": 101},
    {"op": "COMPLETE_IO", "io_id": 102}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 한 줄로 출력합니다:

```json
{
  "stats": {
    "ios_submitted": 2,
    "ios_completed": 2,
    "ios_requeued": 0,
    "failovers": 1,
    "ios_failed_permanently": 0
  },
  "controllers": {
    "1": {"ana_state": "OPTIMIZED", "inflight": 0, "total_ios": 1, "failed_ios": 1},
    "2": {"ana_state": "OPTIMIZED", "inflight": 0, "total_ios": 2, "failed_ios": 0}
  },
  "active_ios_count": 0,
  "requeue_queue": [],
  "completed_ios": [
    {"io_id": 101, "ctrl_id": 2, "retries": 1, "status": "SUCCESS"},
    {"io_id": 102, "ctrl_id": 2, "retries": 0, "status": "SUCCESS"}
  ],
  "history": [
    {"op": "SUBMIT_IO", "io_id": 101, "status": "IN_FLIGHT", "ctrl_id": 1},
    {"op": "SUBMIT_IO", "io_id": 102, "status": "IN_FLIGHT", "ctrl_id": 2},
    {"op": "FAIL_PATH", "io_id": 101, "status": "FAILOVER_RETRY", "new_ctrl_id": 2},
    {"op": "COMPLETE_IO", "io_id": 101, "status": "SUCCESS", "ctrl_id": 2},
    {"op": "COMPLETE_IO", "io_id": 102, "status": "SUCCESS", "ctrl_id": 2}
  ],
  "event_log": [
    "SUBMIT_IO io_id=101 assigned to ctrl=1 state=OPTIMIZED inflight=1",
    ...
  ]
}
```
