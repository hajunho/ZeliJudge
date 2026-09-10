# 리눅스 커널 SCSI 미드레이어 오류 처리(SCSI EH) 4단계 에스컬레이션 및 센스 데이터(Sense Data) 복구 엔진

## 문제 설명

리눅스 커널의 스토리지 스택에서 **SCSI 미드레이어(SCSI Mid-Layer)**는 SAS/SATA 드라이브, 파이버 채널(Fibre Channel) HBA, iSCSI 이니시에이터, USB 매스 스토리지 등 모든 전통적 블록 디바이스의 I/O 발행과 장치 수명주기를 총괄하는 핵심 서브시스템입니다. 대규모 엔터프라이즈 SAN(Storage Area Network) 환경에서는 수백 개의 LUN(Logical Unit Number)과 다중 타깃 컨트롤러가 단일 호스트 버스 어댑터(HBA)에 연결되어 동작하므로, 특정 디바이스에서 하드웨어 오류나 타임아웃이 발생했을 때 이를 전체 스토리지의 장애로 확산시키지 않고 최소 단위에서 정밀하게 격리 및 복구하는 메커니즘이 필수적입니다.

리눅스 커널의 SCSI 오류 처리 서브시스템(`drivers/scsi/scsi_error.c`, `scsi_eh_<host_no>` 전용 커널 스레드)은 두 가지 핵심 축을 통해 무중단 스토리지 신뢰성을 보장합니다:
1. **SCSI 센스 데이터(Sense Data / SAM-5 / SPC-4) 자동 디코딩 및 재시도 제어**:
   - 타깃이 `CHECK_CONDITION` 상태를 반환할 때, 센스 키(Sense Key), ASC(추가 센스 코드), ASCQ(추가 센스 코드 한정자)를 분석합니다.
   - `RECOVERED_ERROR`는 즉시 성공 처리, `NOT_READY` 및 `UNIT_ATTENTION`(장치 리셋 후 복구 등)은 재시도(`retries`)를 통해 구제하며, `MEDIUM_ERROR`(배드 섹터) 및 `ILLEGAL_REQUEST`(잘못된 CDB)는 불필요한 재시도 없이 영구 실패로 신속히 반환합니다.
2. **SCSI EH 4단계 계층적 에스컬레이션 사다리(Escalation Ladder)**:
   - 명령 타임아웃 또는 심각한 하드웨어 장애 발생 시, 시스템 영향도를 최소화하기 위해 가장 좁은 범위부터 가장 넓은 범위로 복구 시도를 단계별로 격상합니다:
     - **1단계: 단일 명령 중단 (Command Abort / `eh_abort_handler`)**: 문제가 발생한 단일 명령만을 중단시켜 다른 I/O에 미치는 영향을 0으로 억제합니다.
     - **2단계: LUN 장치 리셋 (Device/LUN Reset / `eh_device_reset_handler`)**: 명령 중단 실패 시 해당 논리 유닛(LUN)의 큐만을 리셋합니다.
     - **3단계: 타깃 컨트롤러 리셋 (Target Reset / `eh_target_reset_handler`)**: LUN 리셋 실패 시 해당 타깃 포트 산하의 모든 LUN을 함께 재설정합니다.
     - **4단계: 호스트 버스/HBA 리셋 (Bus/Host Reset / `eh_host_reset_handler`)**: 물리 PCIe HBA 하드웨어를 재부팅하고 PHY 링크를 재협상합니다.
     - **5단계: 장치 오프라인 격리 (Device Offline / `SDEV_OFFLINE`)**: 4단계 리셋마저 실패하면 해당 디바이스를 영구 오프라인으로 격리하여 전체 시스템의 크래시를 방지합니다.

본 과제에서는 리눅스 커널 SCSI 미드레이어의 4단계 에스컬레이션 사다리 및 센스 데이터 복구 파이프라인을 100% 수리·시스템적으로 정밀 구현합니다.

---

## 시스템 아키텍처 및 에스컬레이션 다이어그램

```
+-------------------------------------------------------------------------+
|                  SCSI Command Execution (scsi_cmnd)                     |
+------------------------------------+------------------------------------+
                                     |
           +-------------------------+-------------------------+
           | Error Type                                        |
           v                                                   v
+------------------------+                           +--------------------+
|    CHECK_CONDITION     |                           |   Command TIMEOUT  |
|  - Decode Sense Key:   |                           +---------+----------+
|    * RECOVERED -> OK   |                                     |
|    * MEDIUM -> FAIL    |                                     v
|    * UNIT_ATTN-> Retry |                      +-------------------------------+
|    * HARDWARE -> ESCAL |                      | Stage 1: Command Abort        |
+------------------------+                      | (scsi_try_to_abort_cmd)       |
                                                +---------------+---------------+
                                                                | Fail
                                                                v
                                                +-------------------------------+
                                                | Stage 2: Device / LUN Reset   |
                                                | (scsi_try_bus_device_reset)   |
                                                +---------------+---------------+
                                                                | Fail
                                                                v
                                                +-------------------------------+
                                                | Stage 3: Target Reset         |
                                                | (scsi_try_target_reset)       |
                                                +---------------+---------------+
                                                                | Fail
                                                                v
                                                +-------------------------------+
                                                | Stage 4: Host Adapter Reset   |
                                                | (scsi_try_host_reset)         |
                                                +---------------+---------------+
                                                                | Fail
                                                                v
                                                +-------------------------------+
                                                | Stage 5: SDEV_OFFLINE Isolation
                                                +-------------------------------+
```

---

## 핵심 요구사항 및 동작 규칙

### 1. 장치 상태 및 사전 검사
- 각 디바이스는 `target:lun` 튜플로 식별됩니다.
- 디바이스 상태(`state`)가 `OFFLINE`이거나 등록되지 않은 경우, 명령은 즉시 실패(`status = "DEVICE_OFFLINE_OR_NOT_FOUND"`, `completed = false`) 처리됩니다.

### 2. 센스 데이터(Sense Data) 처리 규칙
명령의 `error_type`이 `CHECK_CONDITION`인 경우:
- `sense_key`가 `0x00` (`NO_SENSE`) 또는 `0x01` (`RECOVERED_ERROR`):
  - `completed = true`, `final_stage = "SENSE_RECOVERED"`, `commands_completed_success` 1 증가.
- `sense_key`가 `0x03` (`MEDIUM_ERROR`) 또는 `0x05` (`ILLEGAL_REQUEST`):
  - `completed = false`, `final_stage = "SENSE_UNRECOVERABLE_FAIL"`, `commands_failed_permanently` 1 증가.
- `sense_key`가 `0x02` (`NOT_READY`), `0x06` (`UNIT_ATTENTION`), `0x0B` (`ABORTED_COMMAND`):
  - `retries_available > 0`인 경우: `completed = true`, `retries_used = 1`, `final_stage = "SENSE_RETRY_SUCCESS"`, `commands_completed_success` 1 증가.
  - `retries_available <= 0`인 경우: `completed = false`, `final_stage = "SENSE_RETRIES_EXHAUSTED"`, `commands_failed_permanently` 1 증가.
- `sense_key`가 `0x04` (`HARDWARE_ERROR`):
  - 센스 수준에서 복구 불가능하므로 즉시 4단계 SCSI EH 에스컬레이션 사다리로 전환됩니다.

### 3. SCSI EH 4단계 에스컬레이션 사다리
`error_type`이 `TIMEOUT`이거나 `HARDWARE_ERROR`인 경우:
1. **1단계 (Command Abort)**:
   - `metrics["eh_aborts_attempted"]` 1 증가.
   - `lldd_abort_ok == true`이면: `eh_aborts_succeeded` 1 증가, `final_stage = "EH_ABORT_SUCCESS"`, `completed = true`, 복구 완료.
2. **2단계 (Device / LUN Reset)**:
   - 1단계 실패 시: `metrics["eh_device_resets"]` 1 증가.
   - `lldd_dev_reset_ok == true`이면: `final_stage = "EH_DEVICE_RESET_SUCCESS"`, `completed = true`, 복구 완료.
3. **3단계 (Target Reset)**:
   - 2단계 실패 시: `metrics["eh_target_resets"]` 1 증가.
   - `lldd_target_reset_ok == true`이면: `final_stage = "EH_TARGET_RESET_SUCCESS"`, `completed = true`, 해당 타깃의 모든 LUN 복구 카운터 갱신.
4. **4단계 (Host Adapter / Bus Reset)**:
   - 3단계 실패 시: `metrics["eh_bus_host_resets"]` 1 증가.
   - `lldd_host_reset_ok == true`이면: `final_stage = "EH_HOST_RESET_SUCCESS"`, `completed = true`, 호스트 레벨 복구 완료.
5. **5단계 (Device Offline)**:
   - 4단계마저 실패한 경우:
     - `final_stage = "EH_ESCALATION_FAILED_OFFLINE"`, `completed = false`.
     - 디바이스 상태를 `OFFLINE`으로 전이 (`dev["state"] = "OFFLINE"`).
     - `metrics["devices_offlined"]` 1 증가, `metrics["commands_failed_permanently"]` 1 증가.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "config": {"max_retries": 3},
  "devices": [
    {"target": 0, "lun": 0},
    {"target": 0, "lun": 1},
    {"target": 1, "lun": 0}
  ],
  "commands": [
    {"id": "CMD_01", "target": 0, "lun": 0, "error_type": "NONE"},
    {"id": "CMD_02", "target": 0, "lun": 0, "error_type": "TIMEOUT", "lldd_abort_ok": true},
    {"id": "CMD_03", "target": 0, "lun": 1, "error_type": "TIMEOUT", "lldd_abort_ok": false, "lldd_dev_reset_ok": true},
    {"id": "CMD_04", "target": 1, "lun": 0, "error_type": "TIMEOUT", "lldd_abort_ok": false, "lldd_dev_reset_ok": false, "lldd_target_reset_ok": false, "lldd_host_reset_ok": false}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없는 압축 JSON(`separators=(',', ':')`, `ensure_ascii=False`)을 출력합니다:
```json
{
  "metrics": {
    "commands_total": 4,
    "commands_completed_success": 3,
    "commands_failed_permanently": 1,
    "eh_aborts_attempted": 3,
    "eh_aborts_succeeded": 1,
    "eh_device_resets": 2,
    "eh_target_resets": 1,
    "eh_bus_host_resets": 1,
    "devices_offlined": 1
  },
  "devices": {
    "0:0": {"target": 0, "lun": 0, "state": "RUNNING", "active_cmds": 0, "failed_cmds": 0, "recovered_cmds": 2},
    "0:1": {"target": 0, "lun": 1, "state": "RUNNING", "active_cmds": 0, "failed_cmds": 0, "recovered_cmds": 1},
    "1:0": {"target": 1, "lun": 0, "state": "OFFLINE", "active_cmds": 0, "failed_cmds": 1, "recovered_cmds": 0}
  },
  "cmd_results": [
    {"cmd_id": "CMD_01", "target": 0, "lun": 0, "completed": true, "final_stage": "NORMAL", "retries_used": 0},
    {"cmd_id": "CMD_02", "target": 0, "lun": 0, "completed": true, "final_stage": "EH_ABORT_SUCCESS", "retries_used": 0},
    {"cmd_id": "CMD_03", "target": 0, "lun": 1, "completed": true, "final_stage": "EH_DEVICE_RESET_SUCCESS", "retries_used": 0},
    {"cmd_id": "CMD_04", "target": 1, "lun": 0, "completed": false, "final_stage": "EH_ESCALATION_FAILED_OFFLINE", "retries_used": 0}
  ]
}
```

---

## 제약 사항

- $1 \le \text{len}(commands) \le 100$
- $0 \le \text{target} \le 15$, $0 \le \text{lun} \le 255$
- $0 \le \text{max\_retries} \le 10$
