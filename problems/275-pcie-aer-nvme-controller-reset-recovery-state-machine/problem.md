# PCIe AER(Advanced Error Reporting) 에러 분류 및 NVMe 비동기 리셋(nvme_reset_work) 복구 상태 머신

## 문제 설명

수천 대의 NVMe SSD가 장착된 대규모 클라우드 데이터센터 및 엔터프라이즈 올플래시(All-Flash) 스토리지 시스템에서 가장 치명적인 인프라 장애 중 하나는 PCIe 물리 버스 신호 무결성(Signal Integrity) 저하 또는 컨트롤러 내부 펌웨어 멈춤으로 인한 **컨트롤러 무응답 및 마운트 증발 참사**입니다.

서버가 가동되는 동안 전기적 노이즈나 일시적 신호 감쇠로 인해 PCIe TLP(Transaction Layer Packet) 또는 DLLP(Data Link Layer Packet)가 손상되면 하드웨어는 **PCIe AER(Advanced Error Reporting)** 서브시스템을 통해 에러를 호스트로 통보합니다. 이때 리눅스 커널의 NVMe 드라이버(`drivers/nvme/host/pci.c`)는 에러의 심각도에 따라 정밀한 정책을 집행해야 합니다:

1. **수정 가능 에러 (Correctable Errors)**:
   - `BAD_TLP`, `BAD_DLLP`, `RECEIVER_ERR`, `REPLAY_TIMER_TIMEOUT` 등.
   - PCIe 데이터 링크 계층의 NAK & Replay 버퍼 메커니즘을 통해 하드웨어가 자동으로 패킷을 재전송하여 100% 자가 복구합니다.
   - **호스트 동작**: 에러 통계만 카운트하고, 실행 중인 I/O 및 컨트롤러 상태는 정상(`NVME_CTRL_LIVE`)으로 유지합니다. 리셋을 유발해서는 안 됩니다.

2. **수정 불가능 비치명 에러 (Uncorrectable Non-Fatal Errors)**:
   - `POISONED_TLP`, `COMPLETER_ABORT`, `UNEXPECTED_COMPLETION` 등.
   - 특정 트랜잭션이 손상되었으나 PCIe 링크 자체의 통신 무결성은 유지되는 상태입니다.
   - **호스트 동작**: 해당 특정 명령어만 `-EIO`로 중단(Abort)합니다. 그러나 단시간 내에 연속으로 임계치(`uncor_nonfatal_threshold`) 이상의 비치명 에러가 누적되면 컨트롤러 내부 고장으로 판단하여 컨트롤러 리셋으로 에스컬레이션합니다.

3. **수정 불가능 치명 에러 (Uncorrectable Fatal Errors)**:
   - `DATA_LINK_PROTOCOL_ERR`, `SURPRISE_DOWN`, `MALFORMED_TLP`, `FLOW_CONTROL_PROTOCOL_ERR` 등.
   - PCIe 링크가 단절되거나 프로토콜 상태가 회복 불가능한 교착 상태에 빠진 경우입니다.
   - **호스트 동작**: 즉시 비동기 리셋 워커(`nvme_reset_work`)를 스케줄링하여 전체 컨트롤러 복구 파이프라인을 기동합니다.

4. **NVMe 컨트롤러 치명 상태 (`CSTS.CFS == 1`) 및 KATO**:
   - 하드웨어 컨트롤러 레지스터의 `CSTS.CFS`(Controller Fatal Status) 비트가 1로 세팅되거나, Keep Alive 타이머가 만료(`KATO`)된 경우에도 즉각적인 리셋 복구가 필요합니다.

### NVMe 리셋 복구 상태 머신 (`nvme_reset_work`)

리셋이 발동되면 커널 드라이버는 다음 단계의 엄격한 하드웨어 레지스터 시퀀스를 수행합니다:
1. `NVME_CTRL_LIVE` $\to$ `NVME_CTRL_RESETTING` 전이.
2. **I/O 큐 동결(Quiesce) 및 인플라이트 명령어 처리**: 현재 비행 중(In-flight)인 모든 I/O 명령어를 수거하여, 재시도 횟수가 `max_retries` 미만인 명령어는 블록 레이어 재큐잉(`requeued_commands`) 목록에 보관하고, 초과된 명령어는 영구 중단(`aborted_commands`) 처리합니다.
3. **컨트롤러 비활성화 (Disable)**: `CC.EN = 0` 레지스터 쓰기 후 컨트롤러가 준비 해제(`CSTS.RDY == 0`)될 때까지 폴링합니다. `CAP.TO` 타임아웃 내에 해제되지 않으면 복구 실패로 판정하여 컨트롤러를 영구 사망(`NVME_CTRL_DEAD`) 상태로 격리합니다.
4. **어드민 큐 재초기화 및 활성화 (Enable)**: 어드민 SQ/CQ 링을 재설정한 후 `CC.EN = 1`을 기록하고 `CSTS.RDY == 1`을 대기합니다. 타임아웃 발생 시 `NVME_CTRL_DEAD`로 격리됩니다.
5. **어드민 Identify 및 I/O 큐 재생성**: `Identify Controller` 명령어를 수행하고 모든 I/O CQ/SQ를 재생성합니다.
6. **동결 해제 및 큐잉 재개**: 컨트롤러 상태를 `NVME_CTRL_LIVE`로 복귀시키고, 보관해 둔 재큐잉 명령어들을 즉시 하드웨어로 재전송(`recovered_commands`)합니다!

당신은 리눅스 커널 스토리지 서브시스템의 핵심 엔지니어로서, PCIe AER 에러 분류기, 하드웨어 MMIO 레지스터 프로토콜, 그리고 비동기 리셋 복구 상태 머신을 완벽하게 모사하는 **NVMe Controller AER & Reset State Machine**을 완성해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "cap_timeout_ms": 2000,
    "max_io_queues": 4,
    "max_retries": 2,
    "uncor_nonfatal_threshold": 3
  },
  "initial_state": {
    "state": "NVME_CTRL_LIVE",
    "cc_en": 1,
    "csts_rdy": 1,
    "csts_cfs": 0
  },
  "events": [
    {"type": "IO_SUBMIT", "cmd_id": "CMD_01", "qid": 1, "op": "READ", "lba": 100, "blocks": 4},
    {"type": "PCI_AER_ERR", "severity": "CORRECTABLE", "code": "BAD_TLP"},
    {"type": "IO_COMPLETE", "cmd_id": "CMD_01", "status": "SUCCESS"},
    {"type": "IO_SUBMIT", "cmd_id": "CMD_02", "qid": 2, "op": "WRITE", "lba": 200, "blocks": 8},
    {"type": "PCI_AER_ERR", "severity": "UNCOR_FATAL", "code": "DATA_LINK_PROTOCOL_ERR", "reset_params": {"disable_success": true, "enable_success": true, "identify_success": true}}
  ]
}
```

### 이벤트 유형 (`events`)
- `IO_SUBMIT`: I/O 명령어 제출 (`cmd_id`, `qid`, `op`, `lba`, `blocks`)
- `IO_COMPLETE`: I/O 명령어 정상 완료 (`cmd_id`, `status`)
- `PCI_AER_ERR`: PCIe AER 에러 발생 (`severity`, `code`, `affected_cmd_id`, `reset_params`)
- `CSTS_CFS_TRIGGER`: 컨트롤러 치명 상태 발생 (`reset_params`)
- `KATO_TRIGGER`: Keep Alive 타임아웃 발생 (`reset_params`)
- `MANUAL_RESET`: 관리자 수동 리셋 트리거 (`reset_params`)

---

## 출력 형식

표준 출력(stdout)으로 컨트롤러 상태, AER 에러 통계, 리셋 메트릭, 및 명령어 처리 결과를 포함하는 단일 JSON 라인을 출력합니다:

```json
{
  "controller_status": {
    "state": "NVME_CTRL_LIVE",
    "cc_en": 1,
    "csts_rdy": 1,
    "csts_cfs": 0,
    "is_operational": true
  },
  "aer_statistics": {
    "correctable_errors": 1,
    "uncorrectable_nonfatal_errors": 0,
    "uncorrectable_fatal_errors": 1,
    "total_aer_events": 2
  },
  "reset_metrics": {
    "resets_initiated": 1,
    "resets_successful": 1,
    "resets_failed": 0,
    "state_history": [
      "NVME_CTRL_LIVE",
      "NVME_CTRL_RESETTING",
      "NVME_CTRL_CONNECTING",
      "NVME_CTRL_LIVE"
    ]
  },
  "command_metrics": {
    "in_flight_count": 1,
    "completed_count": 1,
    "aborted_commands": [],
    "requeued_commands": ["CMD_02"],
    "recovered_commands": ["CMD_02"]
  }
}
```
