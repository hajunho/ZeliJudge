# 심층 시스템 이론: 리눅스 커널 NVMe 호스트 드라이버 (`drivers/nvme/host/core.c`) AEN 및 스토리지 신뢰성 아키텍처

## 1. NVMe 비동기 이벤트 통지 (AEN)의 프로토콜 설계

엔터프라이즈 NVMe 아키텍처에서 호스트는 관리자 제출 큐(Admin Submission Queue, ASQ)를 통해 장치 제어 및 상태 조회를 수행합니다.

### 1) Asynchronous Event Request (AER) 메커니즘
전통적인 블록 디바이스(SATA/SCSI)와 달리 NVMe는 비동기 인터럽트 통지를 위해 **AER 명령 선등록(Pre-posting)** 방식을 사용합니다:
1. 호스트 드라이버는 부팅 시 `nvme_init_identify()` 과정에서 컨트롤러가 지원하는 최대 비동기 이벤트 수(`AERL` - Asynchronous Event Request Limit, 보통 4~8개)를 확인합니다.
2. 호스트는 `nvme_submit_aer()`를 호출하여 `AERL` 한도만큼 AER 명령을 미리 제출합니다.
3. 이 명령들은 일반 I/O와 달리 **컨트롤러 내부에서 이벤트가 발생할 때까지 영구 대기(Pending)**합니다.
4. 하드웨어 장애나 설정 변경이 발생하면 컨트롤러는 대기 중인 AER 명령 하나를 완료(ACQ) 처리하고 인터럽트를 발송합니다.
5. 호스트는 완료를 수신하자마자 **지체 없이 즉시 새로운 AER 명령을 재제출**하여 Inflight 버짓을 항상 일정하게 유지합니다.

---

## 2. SMART / Health 로그 페이지 (Log Page 0x02) 및 치명적 경고

NVMe 컨트롤러는 내부 펌웨어와 센서를 통해 SSD의 하드웨어 상태를 밀리초 단위로 감시합니다.
AEN을 통해 `0x02` 로그 페이지 이벤트가 보고되면 호스트는 `nvme_get_log()`를 발송하여 512바이트 SMART 데이터를 판독합니다.

```
Critical Warning Byte (Byte 0):
┌───────┬───────┬───────┬───────┬───────┬───────┬───────┬───────┐
│ Bit 7 │ Bit 6 │ Bit 5 │ Bit 4 │ Bit 3 │ Bit 2 │ Bit 1 │ Bit 0 │
└───────┴───────┴───────┴───────┴───────┴───────┴───────┴───────┘
  Rsvd    Rsvd    Rsvd    PMM     RO      DEG     TEMP    SPARE
```

### 1) 비트별 하드웨어 위협 정의
- **Bit 0 (Available Spare Below Threshold)**:
  NAND 플래시의 배드 블록을 대체하기 위한 프로비저닝 예비 블록이 임계치 미만으로 떨어짐. SSD 수명 임박.
- **Bit 1 (Temperature Threshold)**:
  컨트롤러 ASIC 또는 NAND 패키지 온도가 한계치(예: 85°C)를 초과하여 스로틀링이 필요하거나 저온 상태임.
- **Bit 2 (NVM Subsystem Reliability Degraded)**:
  심각한 다중 비트 ECC 오류, 다이(Die) 손상 또는 내부 NVMe 인터커넥트 장애로 인해 데이터 무결성이 위험에 처함.
- **Bit 3 (Media Read-Only)**:
  SSD가 더 이상의 쓰기를 수행할 수 없는 영구 잠금 상태로 진입함.
- **Bit 4 (Volatile Memory Backup Device Failed)**:
  갑작스러운 정전(PLP, Power Loss Protection) 시 DRAM 캐시 데이터를 플래시에 플러시하기 위한 슈퍼 커패시터(Supercap) 배터리가 방전되거나 고장남.

### 2) 커널 블록 레이어의 강제 읽기 전용 격리 (`set_disk_ro`)
- Bit 3 (`MEDIA_READ_ONLY`)이 켜진 상태에서 계속 쓰기 명령(`REQ_OP_WRITE`)을 내보내면 파일 시스템(ext4, XFS, Btrfs) 저널이 깨지고 커널 패닉이 유발됩니다.
- 리눅스 커널은 Bit 3 감지 즉시 `set_disk_ro(ns->disk, true)`를 호출하여 상위 VFS 및 파일 시스템에 쓰기 차단 신호를 전달하고, 더티 버퍼 라이트백을 안전하게 중단시킵니다.

---

## 3. 네임스페이스 변경 통지 (Notice Log Page 0x04)와 온라인 핫플러그

SAN(Storage Area Network) 및 NVMe-oF(NVMe over Fabrics) 환경에서는 가상 볼륨의 크기가 동적으로 확장되거나(Thin Provisioning), 새로운 네임스페이스가 런타임에 동적으로 매핑/언매핑됩니다.

1. **AEN 수신**: 컨트롤러가 `NVME_AER_NOTICE_NS_CHANGED`를 발행.
2. **Changed NS List 읽기**: 1024개 엔트리로 구성된 비동기 네임스페이스 목록(`Log Page 0x04`)을 인출.
3. **`kworker/nvme_scan_work` 스케줄링**:
   - 변경된 NSID에 대해 `nvme_validate_ns()` 실행.
   - 네임스페이스가 제거된 경우 `nvme_ns_remove()`를 통해 대기 중인 BIO를 안전하게 드레인하고 블록 디바이스(`/dev/nvme0n1`) 노드를 삭제.
   - 새로 추가된 경우 새 블록 디바이스를 등록하고 파티션 테이블을 스캔(`blkdev_reread_part`).

---

## 4. 컨트롤러 장애 복구 (Controller Reset Lifecycle)

컨트롤러 펌웨어 크래시 또는 하드웨어 데드락으로 인해 컨트롤러가 응답하지 않는 경우(Controller Fatal Status, CFS=1):
1. **Queue Freeze**: I/O 큐를 동결하여 신규 I/O 제출을 차단.
2. **Abort Inflight**: 미완료된 채 허공에 갇힌 모든 I/O를 타임아웃 처리(`-EIO`).
3. **PCIe Reset**: PCIe 레벨에서 `NVME_REG_CC` 제어 레지스터를 비활성화(`EN=0`)한 후 재활성화(`EN=1`).
4. **Queue Re-creation**: Admin 큐 및 I/O 큐를 재생성하고, `aer_limit`만큼의 신규 AER 명령을 일괄 제출하여 자가 치유(Self-Healing)를 완성.

---

## 5. 결론

NVMe AEN 메커니즘은 초고속 스토리지 환경에서 호스트 CPU 부하를 0으로 유지하면서도, 물리적 플래시 장애와 클라우드 볼륨 동적 변경을 밀리초 단위로 포착하여 대응할 수 있게 해 주는 핵심적인 엔터프라이즈 스토리지 인프라 기술입니다.
