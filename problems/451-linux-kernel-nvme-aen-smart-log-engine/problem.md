# 문제 451: 리눅스 커널 블록 레이어 — NVMe 비동기 이벤트 통지(AEN), SMART 상태 모니터링 및 네임스페이스 재스캔 엔진 (`drivers/nvme/host/core.c`)

## 1. 개요 및 배경

엔터프라이즈 데이터센터 및 고성능 스토리지 서버에서 NVMe(Non-Volatile Memory Express) 솔리드 스테이트 드라이브(SSD)는 마이크로초 단위의 초저지연 I/O를 처리합니다. 
그러나 하드웨어 플래시 메모리는 지속적인 쓰기 작업으로 인해 블록 마모, 고온 과열, 예비 블록(Spare Blocks) 고갈, 플래시 메모리 신뢰성 저하 등의 치명적인 물리적 장애에 노출됩니다.

### 1) 폴링(Polling)의 비효율성과 비동기 이벤트 통지(AEN)의 필연성
- 호스트 OS가 정기적으로 수백 개의 NVMe 컨트롤러에 SMART 상태 로그 페이지(`SMART / Health Information Log Page 0x02`)를 폴링하는 방식은 막대한 관리자 큐(Admin Queue) 경합과 CPU 사이클 낭비를 초래합니다.
- 이에 NVMe 표준 규격(NVMe Base Specification) 및 리눅스 커널 호스트 드라이버(`drivers/nvme/host/core.c`)는 **비동기 이벤트 통지 (Asynchronous Event Notification / AEN)** 메커니즘을 규정하고 있습니다.

```
[NVMe AEN 비동기 이벤트 처리 파이프라인]:
Host Driver (core.c) ──(Admin Submission Queue)──> Submit AER Commands (최대 4개 Inflight 유지)
                                                                 │
                                                       (컨트롤러 내부 대기)
                                                                 │
                                                        장애/상태 변화 감지!
                                                                 │
Host ACQ 완료 핸들러 <──(Admin Completion Queue)── AEN 인터럽트 트리거! (Log Page ID 전달)
          │
          ├─ Log Page 0x02 (SMART): 치명적 경고 비트 파싱 -> READ_ONLY 모드 강제 전이!
          ├─ Log Page 0x04 (Changed NS): 네임스페이스 목록 재스캔 -> 온라인 핫플러그 반영
          └─ Log Page 0x07 (Telemetry): 하드웨어 패닉 덤프 자동 추출
```

호스트 커널 드라이버는 컨트롤러 초기화 시 관리자 큐에 **AER (Asynchronous Event Request)** 명령을 사전에 등록(보통 4개 Inflight 유지)해 둡니다.
컨트롤러 내부에서 임계 온도 초과나 미디어 읽기 전용 전이, 네임스페이스 변경 등의 이벤트가 발생하면, 컨트롤러는 대기 중이던 AER 명령의 완료 응답(CQE)을 통해 비동기 인터럽트를 발생시키고 로그 페이지 ID를 호스트에 알립니다.

---

## 2. 핵심 메커니즘 및 상세 스펙

본 문제에서는 리눅스 커널 `drivers/nvme/host/core.c`의 비동기 이벤트 통지(AEN), SMART/Health 로그 파싱, 읽기 전용 강제 격리, 네임스페이스 온라인 재스캔(Rescan), 컨트롤러 치명적 오류 복구(Reset) 로직을 모델링하는 엔진을 구현합니다.

### 1) 컨트롤러 구성 (`config`)
- `ctrl_id`: 컨트롤러 식별 문자열 (기본 `"nvme0"`).
- `aer_limit`: 호스트가 유지하는 최대 Inflight AER 명령 수 (기본 4).
- `initial_inflight_aer`: 초기 Inflight AER 수 (생략 시 `aer_limit`).
- `namespaces`: 네임스페이스 초기 목록 `[{"nsid": int, "size_lba": int, "block_size": int, "ro": bool}, ...]`.

### 2) AER 명령 제출 (`SUBMIT_AER`)
- 호스트가 소진된 AER 명령을 컨트롤러에 재등록하는 동작.
- `inflight_aer < aer_limit`인 경우:
  - 만약 컨트롤러 내부 대기 큐(`event_queue`)에 미처리된 이벤트가 있다면:
    - 즉시 대기 이벤트를 팝(Pop)하여 처리(`TRIGGER_EVENT` 동작 수행).
  - 대기 이벤트가 없다면:
    - `inflight_aer += 1`.
    - 반환: `{"status": "AER_SUBMITTED", "inflight_aer": inflight_aer}`.
- 이미 상한에 도달한 경우:
  - 반환: `{"status": "AER_QUEUE_FULL", "inflight_aer": inflight_aer}`.

### 3) 컨트롤러 이벤트 트리거 (`TRIGGER_EVENT`)
- `event`:
  - `event_type`: `"SMART_HEALTH"`, `"NOTICE"`, `"TELEMETRY"`
  - `log_page`: 2 (SMART), 4 (Changed NS), 7 (Telemetry)
  - `payload`: 상세 데이터
- **AER 버짓 검증**:
  - `inflight_aer == 0`인 경우: 호스트의 대기 AER이 없으므로 컨트롤러 내부 큐(`event_queue`)에 이벤트를 적재.
    반환: `{"status": "EVENT_QUEUED_NO_AER", "event_type": event_type}`.
  - `inflight_aer > 0`인 경우:
    - 호스트가 이벤트를 정상 수신함 (`total_events_handled += 1`).
    - **A. SMART / Health 이벤트 (Log Page 2)**:
      - `critical_warning_bits`: 8비트 정수 플래그
        - Bit 0 (`0x01`): `SPARE_BELOW_THRESHOLD` (예비 블록 임계치 미만)
        - Bit 1 (`0x02`): `TEMPERATURE_EXCEEDED` (과열 또는 저온 임계치 초과)
        - Bit 2 (`0x04`): `RELIABILITY_DEGRADED` (NVM 서브시스템 신뢰성 훼손)
        - Bit 3 (`0x08`): `MEDIA_READ_ONLY` (플래시 미디어 읽기 전용 모드 진입)
        - Bit 4 (`0x10`): `VOLATILE_BACKUP_FAILED` (휘발성 메모리 백업 배터리 장애)
      - 매칭되는 경고마다 `smart_warnings_logged` 1 증가.
      - **Bit 3 (`MEDIA_READ_ONLY`) 감지 시**: 데이터 무결성을 보호하기 위해 컨트롤러의 **모든 네임스페이스의 `ro` 속성을 즉시 `true`로 강제 전이** (`set_disk_ro()`).
      - 반환: `{"status": "EVENT_PROCESSED", "type": "SMART_HEALTH", "warnings": [...], "ro_enforced": bool}`.
    - **B. 네임스페이스 변경 통지 (Log Page 4)**:
      - `changed_nsids`: 변경된 NSID 목록.
      - `ns_updates`: NSID별 변경 액션 (`"ATTACH"`, `"UPDATE"`, `"REMOVE"`).
      - 각 NSID를 재스캔하여 네임스페이스 맵을 갱신하거나 삭제.
      - 반환: `{"status": "EVENT_PROCESSED", "type": "NOTICE_CHANGED_NS", "scanned_nsids": sorted_list}`.
    - **C. 텔레메트리 덤프 (Log Page 7)**:
      - `dump_id`: 덤프 식별자.
      - 반환: `{"status": "EVENT_PROCESSED", "type": "TELEMETRY_CAPTURED", "dump_id": dump_id}`.

### 4) 컨트롤러 리셋 (`RESET_CONTROLLER`)
- 치명적 컨트롤러 상태(Controller Fatal Status) 감지 시 PCIe 인터페이스 하드 리셋 및 큐 재생성 시뮬레이션.
- `reset_count` 1 증가.
- `inflight_aer = aer_limit`로 가득 복원.
- 대기 이벤트 큐(`event_queue`) 플러시(비움).
- 반환: `{"status": "CTRL_RESET_COMPLETE", "ctrl_id": ctrl_id, "inflight_aer": inflight_aer}`.

### 5) 통계 조회 (`QUERY_STATS`)
- `ctrl_id`, `inflight_aer`, `total_events_handled`, `smart_warnings_logged`, `reset_count`, 그리고 정렬된 네임스페이스 목록을 반환합니다.

---

## 3. 입력 및 출력 형식

### 입력 포맷 (표준 입력 JSON)
```json
{
  "config": {
    "ctrl_id": "nvme0",
    "aer_limit": 4,
    "namespaces": [
      {"nsid": 1, "size_lba": 1000000, "block_size": 4096, "ro": false}
    ]
  },
  "operations": [
    {
      "op": "TRIGGER_EVENT",
      "event": {
        "event_type": "SMART_HEALTH",
        "log_page": 2,
        "payload": {"critical_warning_bits": 9}
      }
    },
    {"op": "SUBMIT_AER"},
    {"op": "QUERY_STATS"}
  ]
}
```

### 출력 포맷 (표준 출력 단일 라인 JSON)
```json
{"results":[...]}
```
모든 키와 값은 공백 없는 압축 JSON(`separators=(',', ':')`) 형식으로 출력합니다.
