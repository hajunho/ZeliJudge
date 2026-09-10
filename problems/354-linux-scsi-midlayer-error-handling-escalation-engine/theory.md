# 리눅스 커널 SCSI 미드레이어 오류 처리(SCSI EH) 및 센스 데이터 심층 분석

## 1. 개요 및 SCSI 서브시스템 아키텍처

리눅스 커널의 SCSI 서브시스템은 전통적으로 세 개의 계층(3-Layer Architecture)으로 명확히 구분됩니다:
1. **상위 계층 (Upper Level Drivers / ULD)**:
   - 블록 디바이스 드라이버 `sd`(SCSI Disk), `sr`(SCSI CD-ROM), `st`(SCSI Tape), `sg`(SCSI Generic passthrough) 등 사용자 공간 및 VFS 파일시스템과의 인터페이스를 제공합니다.
2. **중간 계층 (SCSI Mid-Layer)**:
   - `drivers/scsi/scsi_lib.c`, `scsi_scan.c`, `scsi_error.c` 등으로 구성되며, 공통 명령 할당, 큐잉(Queueing), 타임아웃 감시, 그리고 장애 발생 시 오류 복구(Error Handling)를 총괄합니다.
3. **하위 계층 (Low-Level Device Drivers / LLDD)**:
   - 물리 하드웨어 HBA 컨트롤러 칩셋 드라이버 (예: `megaraid_sas`, `mpt3sas`, `qla2xxx`, `lpfc`, `ahci` 등).

---

## 2. SCSI 센스 데이터(Sense Data) 구조와 해석

SCSI 타깃 장치가 명령 수행에 실패하면 상태 바이트로 `SAM_STAT_CHECK_CONDITION` (0x02)을 반환합니다. 이니시에이터(리눅스 커널)는 곧바로 `REQUEST SENSE` 명령을 실행하거나 자동 센스(Auto-Sense) 메커니즘을 통해 18바이트 이상의 **센스 데이터(Sense Data)**를 수신합니다:

```
+--------------------+--------------------+--------------------+
| Byte 2: Sense Key  | Byte 12: ASC       | Byte 13: ASCQ      |
| (주요 오류 카테고리) | (추가 센스 코드)   | (세부 한정자)      |
+--------------------+--------------------+--------------------+
```

### 2.1 주요 센스 키(Sense Key) 명세 (SPC-4)
- **`0x00 NO_SENSE`**: 오류 없음.
- **`0x01 RECOVERED_ERROR`**: 장치 내부의 ECC 또는 자동 재시도로 데이터가 정상 복구됨 (성공 간주).
- **`0x02 NOT_READY`**: 장치가 회전 속도 가속 중이거나 준비 중 (`ASC=0x04, ASCQ=0x01: Logical unit in process of becoming ready`). 지연 후 재시도 필요.
- **`0x03 MEDIUM_ERROR`**: 디스크 플래터/NAND 플래시의 물리적 배드 섹터로 인해 읽기 실패. 재시도해도 실패하므로 즉시 상위 I/O 실패 통보.
- **`0x04 HARDWARE_ERROR`**: 패리티 에러, 컨트롤러 내부 펌웨어 크래시 등 심각한 결함. EH 에스컬레이션 직행.
- **`0x05 ILLEGAL_REQUEST`**: 잘못된 LBA 요청, 지원하지 않는 명령. 상위 레이어의 소프트웨어 버그이므로 재시도 무의미.
- **`0x06 UNIT_ATTENTION`**: 전원 리셋, 버스 리셋 발생 또는 미디어 교체됨. 1회 재시도로 상태 클리어 후 정상 처리.
- **`0x0B ABORTED_COMMAND`**: 타깃 컨트롤러가 버스 타임아웃 등으로 명령을 중단함. 재시도 대상.

---

## 3. SCSI EH 전용 커널 스레드 (`scsi_eh_<host_no>`)

명령이 지정된 타임아웃(`scsi_cmnd->timeout`, 기본 30초) 내에 완료되지 않으면, 커널은 소프트웨어 타이머 만료 인터럽트(`scsi_timeout`)를 호출합니다. 이때 커널 인터럽트 문맥에서 직접 복잡하고 무거운 리셋을 실행할 수 없으므로, 커널은 호스트별 전용 스레드인 **`scsi_eh_<host_no>`**를 기상시킵니다.

`scsi_error_handler()` 메인 루프는 오류가 발생한 명령들을 수집한 뒤, 다음 원칙에 따라 복구를 시도합니다:
> *"최소한의 파괴적인(Least Invasive) 복구부터 시작하여, 점진적으로 더 넓은 스토리지 도메인으로 에스컬레이션한다."*

---

## 4. 4단계 계층적 에스컬레이션 사다리 (Hierarchical Escalation Ladder)

```
[Level 1] eh_abort_handler()       --> 타임아웃된 단일 scsi_cmnd만 취소 시도
              | (실패 시)
              v
[Level 2] eh_device_reset_handler() --> 특정 LUN의 태스크 큐 전체 플러시 및 리셋
              | (실패 시)
              v
[Level 3] eh_target_reset_handler() --> 해당 타깃 컨트롤러(다중 LUN) 전체 리셋
              | (실패 시)
              v
[Level 4] eh_bus_host_reset()       --> 물리 PCIe HBA 칩셋 재부팅 및 PHY 재협상
              | (실패 시)
              v
[Level 5] scsi_eh_offline_sdevs()   --> 장치를 SDEV_OFFLINE으로 영구 격리
```

1. **Stage 1: Command Abort**:
   - `scsi_try_to_abort_cmd()`를 통해 LLDD의 `eh_abort_handler`를 호출합니다.
   - 드라이버가 하드웨어 태스크 관리 요청(TMR: Task Management Request / `ABORT TASK`)을 디바이스에 전송하여 해당 태스크 태그만 안전하게 취소합니다.
2. **Stage 2: Device / LUN Reset**:
   - 명령 중단이 응답하지 않거나 타깃 내부 큐가 락에 걸린 경우, `LOGICAL UNIT RESET` TMR을 전송합니다.
   - 해당 LUN만 리셋되므로, 같은 타깃에 물려 있는 다른 LUN의 정상 I/O는 중단되지 않습니다.
3. **Stage 3: Target Reset**:
   - LUN 리셋이 실패하면 스토리지 인클로저 컨트롤러 자체를 리셋하는 `TARGET RESET` TMR을 발행합니다.
   - 타깃 산하의 모든 LUN 큐가 함께 플러시됩니다.
4. **Stage 4: Bus / Host Adapter Reset**:
   - 타깃 수준에서도 응답이 없는 파이버 채널/SAS 패브릭 장애 시, 물리 PCIe HBA 카드를 하드웨어 리셋(`scsi_try_host_reset`)합니다.
   - HBA의 모든 펌웨어 상태가 재초기화되고 링크 트레이닝이 재수행됩니다.
5. **Stage 5: Device Offline 격리**:
   - 호스트 리셋마저 실패하면 더 이상의 소프트웨어 복구가 불가능한 영구 하드웨어 결함으로 판정합니다.
   - 디바이스를 `SDEV_OFFLINE` 상태로 고정하여 커널 패닉을 막고 후속 I/O를 즉각 거부합니다.

---

## 5. 결론 및 실무적 중요성

SCSI 미드레이어의 에스컬레이션 구조는 수천 대의 서버와 페타바이트급 스토리지가 맞물린 현대 클라우드 데이터센터에서 단일 디스크의 결함이 스토리지 네트워크 전체를 다운시키는 캐스케이딩 장애를 원천 차단하는 리눅스 I/O 서브시스템의 핵심적인 생존 방어선입니다.
