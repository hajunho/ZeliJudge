# PCIe AER(Advanced Error Reporting) 및 NVMe 컨트롤러 비동기 리셋 복구 아키텍처 심층 이론

## 1. PCIe 버스 계층 구조와 AER(Advanced Error Reporting)

PCIe(Peripheral Component Interconnect Express)는 직렬 점대점(Point-to-Point) 패킷 기반 버스 아키텍처로, 트랜잭션 계층(Transaction Layer), 데이터 링크 계층(Data Link Layer), 물리 계층(Physical Layer)의 3계층 구조로 동작합니다.

```
+-------------------------------------------------------------+
|                 PCIe 3-Tier Layer Stack                     |
|                                                             |
| [Transaction Layer]  TLP 생성, 헤더 검사, ECRC 무결성       |
|                               ^                             |
|                               v                             |
| [Data Link Layer]    DLLP, LCRC(32비트), ACK/NAK & Replay   |
|                               ^                             |
|                               v                             |
| [Physical Layer]     차동 신호, 128b/130b 인코딩, 심볼 락   |
+-------------------------------------------------------------+
```

### AER 3단계 에러 심각도 분류

PCIe 기본 규격(PCIe Base Spec) 및 AER 확장 사양에서 에러는 3단계로 엄격히 구분됩니다:

1. **수정 가능 에러 (Correctable Errors, COR_ERR)**:
   - 에러가 발생했으나 PCIe 데이터 링크 계층의 하드웨어 수준에서 호스트 소프트웨어의 개입 없이 100% 자동 정정됩니다.
   - 대표 에러:
     - `BAD_TLP`: TLP의 LCRC 체크섬이 불일치하여 수신 측이 NAK DLLP를 송신하고, 송신 측 Replay 버퍼에서 해당 TLP를 재전송하여 복구.
     - `BAD_DLLP`: 제어 패킷(DLLP)의 16비트 CRC 에러.
     - `RECEIVER_ERR`: 물리 계층의 일시적 비트 플립 또는 심볼 디코딩 실패.
     - `REPLAY_TIMER_TIMEOUT`: 재전송 타이머 만료 후 재전송 성공.
   - **영향**: I/O 레이턴시가 수 마이크로초 증가할 뿐, 시스템 안정성에는 영향이 없음.

2. **수정 불가능 비치명 에러 (Uncorrectable Non-Fatal Errors, UNCOR_NONFATAL)**:
   - 해당 패킷이나 트랜잭션 자체는 손상되어 완료할 수 없으나, 링크의 물리적 연결 및 패킷 송수신 상태 머신은 여전히 온전한 상태입니다.
   - 대표 에러:
     - `POISONED_TLP`: 이전 단계에서 이미 에러가 감지되어 EP(Error Poisoned) 비트가 마킹된 TLP.
     - `COMPLETER_ABORT`: 타겟 디바이스가 비정상 상태로 인해 요청 처리를 거부.
     - `UNEXPECTED_COMPLETION`: 요청하지 않은 태그(Tag)의 응답 수신.
   - **영향**: 영향을 받은 I/O 명령어만 개별적으로 실패(-EIO) 처리하면 되지만, 빈도가 높으면 하드웨어 고장의 징후입니다.

3. **수정 불가능 치명 에러 (Uncorrectable Fatal Errors, UNCOR_FATAL)**:
   - 링크의 신뢰성이 파괴되어 더 이상의 정상적인 데이터 전송이 불가능한 상태입니다.
   - 대표 에러:
     - `DATA_LINK_PROTOCOL_ERR`: DLLP 시퀀스 번호 위반 또는 ACK/NAK 프로토콜 데드락.
     - `SURPRISE_DOWN`: 링크 트레이닝 실패 또는 슬롯 전원 차단으로 인한 갑작스러운 링크 단절.
     - `MALFORMED_TLP`: TLP 헤더 필드 규격 위반(길이 초과, 잘못된 라우팅 등).
     - `FLOW_CONTROL_PROTOCOL_ERR`: 크레딧 기반 흐름 제어 버퍼 오버플로우/언더플로우.
   - **영향**: 링크 및 디바이스 전체가 즉시 마비되므로, 링크 트레이닝 재수행 및 컨트롤러 리셋이 필수적입니다.

---

## 2. NVMe MMIO 레지스터 및 컨트롤러 상태 제어 프로토콜

NVMe 컨트롤러는 호스트 메모리에 매핑된 MMIO(Memory-Mapped I/O) BAR0 레지스터를 통해 제어됩니다:

- **CAP (Controller Capabilities, Offset 0x00)**:
  - `CAP.TO` (Bits 31:24): 컨트롤러 상태 전이 대기 타임아웃 단위 ($500\text{ms}$ 배수).
  - 최대 허용 대기 시간: $T_{\max} = \text{CAP.TO} \times 500\text{ms}$.
- **CC (Controller Configuration, Offset 0x14)**:
  - `CC.EN` (Bit 0): 컨트롤러 활성화/비활성화 제어 비트.
  - $0 \to 1$: 컨트롤러 초기화 및 시작 요청.
  - $1 \to 0$: 컨트롤러 비활성화(정지) 요청.
- **CSTS (Controller Status, Offset 0x1C)**:
  - `CSTS.RDY` (Bit 0): 컨트롤러 준비 완료 상태 ($1 = \text{준비됨}, 0 = \text{정지됨}$).
  - `CSTS.CFS` (Bit 1): 컨트롤러 치명 에러 상태 (Controller Fatal Status). $1$이면 내부 복구 불가능 에러 발생.

---

## 3. 리눅스 커널의 비동기 리셋 워크큐 (`nvme_reset_work`)

치명적 에러 발생 시 리눅스 커널(`drivers/nvme/host/pci.c`)은 `nvme_reset_work()`를 워크큐에 스케줄링하여 비동기로 복구를 실행합니다:

```
[NVME_CTRL_LIVE]
       |
       | (PCIe Fatal AER / CSTS.CFS=1 / KATO)
       v
[NVME_CTRL_RESETTING]  <--- In-flight I/O Quiesce & Requeue / CC.EN = 0
       |
       | (CSTS.RDY == 0 도달, 타임아웃 시 -> DEAD)
       v
[NVME_CTRL_CONNECTING] <--- Admin SQ/CQ Ring 재설정 & CC.EN = 1
       |
       | (CSTS.RDY == 1 도달 & Identify & I/O Queues 생성 완료)
       v
[NVME_CTRL_LIVE]       <--- Unquiesce & Requeued Commands Resubmitted!
```

### 명령어 보존 및 blk-mq 재큐잉 기제
- 활성 I/O 큐에 묶여 있던 명령어들은 컨트롤러가 리셋되는 순간 하드웨어 완료 링에서 사라집니다.
- 드라이버는 이를 무조건 실패 처리하여 애플리케이션 크래시를 유발하는 대신, `cmd->retries < max_retries` 조건에 따라 blk-mq 소프트웨어 스테이징 큐로 안전하게 회수(`requeue`)합니다.
- 리셋이 성공하면 큐를 동결 해제(`unquiesce`)하고 보관된 명령어들을 투명하게 재제출하여 무중단 고가용성(Zero-Downtime HA)을 유지합니다.
