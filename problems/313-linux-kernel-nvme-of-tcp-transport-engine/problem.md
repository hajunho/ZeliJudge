# 리눅스 커널 NVMe-oF TCP 트랜스포트 캡슐 PDU 및 상태 머신 엔진 (Linux Kernel NVMe-oF TCP Transport & Capsule PDU State Machine Engine)

## 문제 설명

초대규모 클라우드 데이터센터와 초고속 분산 스토리지 클러스터(Ceph, SPDK, DAOS)에서는 네트워크 패브릭을 경유하여 원격 NVMe 솔리드 스테이트 드라이브(SSD)에 마이크로초(µs) 단위의 초저지연으로 접근하기 위해 **NVMe over Fabrics (NVMe-oF)** 프로토콜을 사용합니다. 특히 고가의 무손실 RoCEv2(RDMA) 네트워크 장비 없이도 범용 데이터센터 이더넷 인프라 위에서 구동할 수 있는 **NVMe-oF TCP 트랜스포트(`drivers/nvme/host/tcp.c`, `drivers/nvme/target/tcp.c`)** 규격(NVMe-oF 1.1 / TP 8000)이 표준으로 널리 채택되고 있습니다.

NVMe-oF TCP는 신뢰성 있는 바이트 스트림을 제공하는 TCP 소켓 위에 고유한 **PDU(Protocol Data Unit)** 캡슐화 계층을 구성합니다. 모든 통신 단위는 8바이트 기본 헤더와 선택적 4바이트 Castagnoli CRC32C 다이제스트(Header Digest, Data Digest), 그리고 인-캡슐 데이터 페이로드로 구성됩니다.

```
+-------------------------------------------------------------------------+
|                  NVMe-oF TCP PDU 일반 프레임 구조                         |
+-------------------+-------------------+-----------------+---------------+
| Byte 0: pdu_type  | Byte 1: flags     | Byte 2: hlen    | Byte 3: pdo   |
+-------------------+-------------------+-----------------+---------------+
| Bytes 4..7: plen (Total PDU Length, Little-Endian uint32)               |
+-------------------------------------------------------------------------+
| Specific Header Payload (64B SQE / 16B CQE / 16B R2T / 16B Data Hdr)     |
+-------------------------------------------------------------------------+
| [선택적] Header Digest (HDGST): Castagnoli CRC32C (4바이트, LE uint32)   |
+-------------------------------------------------------------------------+
| [선택적] In-Capsule Data Payload (가변 길이)                            |
+-------------------------------------------------------------------------+
| [선택적] Data Digest (DDGST): Castagnoli CRC32C (4바이트, LE uint32)     |
+-------------------------------------------------------------------------+
```

그러나 TCP는 패킷 경계를 보존하지 않는 스트림 지향 프로토콜이므로, 네트워크 버퍼 지연이나 MTU 단편화로 인해 단일 PDU가 여러 TCP 세그먼트로 나뉘어 수신되거나(Fragmentation), 여러 PDU가 하나의 소켓 수신 버퍼로 병합(Coalescing)되어 도착할 수 있습니다.

또한 대용량 쓰기(Write) 작업 시 호스트가 모든 데이터를 명령 캡슐에 한꺼번에 담아 보내면 타깃 컨트롤러의 메모리가 고갈될 수 있으므로, 인-캡슐 임계값(`ioccsz`)을 초과하는 데이터는 타깃이 수신 준비가 되었을 때 **R2T(Ready-to-Transfer)** PDU를 발급하고 호스트가 이에 맞춰 분할된 **H2C_DATA** PDU를 전송하는 정교한 크레딧 기반 흐름 제어가 수행됩니다.

본 문제는 리눅스 커널 스토리지 타깃 서브시스템(`nvmet-tcp`)의 소켓 스트림 프레이밍, Castagnoli CRC32C 다이제스트 무결성 검증, R2T 기반 멀티 청크 분할 전송, 그리고 소켓 상태 전이 머신을 완벽하게 모사하는 커널급 NVMe-oF TCP 트랜스포트 엔진을 구현하는 것입니다.

```
               [ NVMe-oF TCP 프로토콜 핸드셰이크 및 전송 흐름도 ]

   Host (Initiator)                                Target (Controller)
          |                                                 |
          | ----- 1. CAPSULE_CMD (Fabric CONNECT) --------> | (소켓 ESTABLISHED 전이)
          | <---- 2. CAPSULE_RESP (Success, SC=0x0000) ---  | (SQ Head 증가)
          |                                                 |
          | ===== 대용량 쓰기 (Write > ioccsz) 시나리오 ===== |
          | ----- 3. CAPSULE_CMD (Write, 2048B 요청) -----> | (active_commands 등록)
          | <---- 4. R2T PDU (ttag=1, offset=0, len=1024) - | (수신 버퍼 준비)
          | ----- 5. H2C_DATA PDU (ttag=1, offset=0, 1024B) | (1차 데이터 적재)
          | <---- 6. R2T PDU (ttag=1, off=1024, len=1024) - | (2차 요청 전송)
          | ----- 7. H2C_DATA PDU (ttag=1, off=1024, LAST)-> | (2차 데이터 적재)
          |                                                 | (스토리지 LBA 커밋)
          | <---- 8. CAPSULE_RESP (Success, SC=0x0000) ---  |
          |                                                 |
          | ===== 읽기 (Read) 시나리오 ===================== |
          | ----- 9. CAPSULE_CMD (Read, SLBA=4) ----------> |
          | <---- 10. C2H_DATA PDU (LAST=1, DATA) --------- | (LBA 데이터 스트리밍)
          | <---- 11. CAPSULE_RESP (Success, SC=0x0000) --- | (or C2H_SUCCESS)
          |                                                 |
          | ===== CRC32C 다이제스트 손상 발생 시 =========== |
          | ----- 12. CAPSULE_CMD (손상된 Header CRC) -----> | (CRC 불일치 감지!)
          | <---- 13. C2H_TERM_REQ (FES=0x0281) ----------- | (소켓 TERMINATED)
```

---

## 알고리즘 및 상태 전이 명세

### 1. Castagnoli CRC32C 무결성 다이제스트
- 생성 다항식: $P(x) = 0x1EDC6F41$ (Bit-reflected: `0x82F63B78`)
- 초기값: `0xFFFFFFFF`, 최종 XOR: `0xFFFFFFFF`
- 256 엔트리 룩업 테이블 기반 고속 연산:
  $$	ext{table}[i] = 	ext{reflected\_poly\_step}(i, 8)$$
  $$	ext{crc} = (	ext{crc} \gg 8) \oplus 	ext{table}[(	ext{crc} \oplus 	ext{byte}) \& 0	ext{xFF}]$$
- 다이제스트는 리틀 엔디언 4바이트(uint32)로 패킷 내에 배치됩니다.
  - `HDGST` (Header Digest, 플래그 `0x01`): 오프셋 $0 \sim hlen-1$ 바이트 헤더의 CRC32C.
  - `DDGST` (Data Digest, 플래그 `0x02`): 페이로드 데이터 바이트의 CRC32C.

### 2. PDU 유형 및 규격
1. **CAPSULE_CMD (`0x04`)**:
   - `hlen = 72`, `pdo = (72 + 4)` (HDGST 활성화 시) 또는 `72` (데이터 페이로드 존재 시)
   - 64바이트 NVMe SQE: `opcode`(1B), `flags`(1B), `cid`(2B), `nsid`(4B), `slba`(8B), `nlb`(2B)
   - 주요 Opcode: `0x00` (CONNECT), `0x01` (WRITE), `0x02` (READ), `0x08` (FLUSH)
2. **CAPSULE_RESP (`0x05`)**:
   - `hlen = 24`, `pdo = 0`, `plen = 24 + (4 if HDGST else 0)`
   - 16바이트 NVMe CQE: `result`(4B), `sq_head`(2B), `sq_id`(2B), `cid`(2B), `status`(2B)
3. **R2T (`0x08`, Ready-to-Transfer)**:
   - `hlen = 24`, `pdo = 0`, `plen = 24 + (4 if HDGST else 0)`
   - 페이로드: `cid`(2B), `ttag`(2B), `r2t_offset`(4B), `r2t_length`(4B)
4. **H2C_DATA (`0x06`)**:
   - `hlen = 24`, `pdo = 24 + (4 if HDGST else 0)`, 페이로드: `cid`(2B), `ttag`(2B), `data_offset`(4B), `data_length`(4B)
   - 이어지는 데이터 페이로드 및 선택적 DDGST
5. **C2H_DATA (`0x07`)**:
   - 타깃이 호스트로 읽기 데이터 반환 시 사용. 플래그 `DATA_LAST(0x04)`, `DATA_SUCCESS(0x08)` 지원.
6. **C2H_TERM_REQ (`0x01`)**:
   - 치명적 오류 감지 시 소켓을 닫고 전송하는 종료 요청 PDU (`fes` 오류 코드 명시).

### 3. 소켓 스트림 파싱 및 상태 머신
1. 소켓 수신 버퍼 `rx_stream`에 바이트가 누적됩니다.
2. 최소 8바이트 누적 시 `hlen`과 `plen`을 검사합니다.
   - `hlen < 8` 또는 `plen < hlen + hdgst_len`인 경우: `NVME_SC_PDU_LENGTH_ERROR (0x0283)`를 담은 `C2H_TERM_REQ` 전송 후 소켓을 `"TERMINATED"`로 전이합니다.
3. `len(rx_stream) < plen`이면 다음 네트워크 세그먼트가 도착할 때까지 대기합니다.
4. 패킷 슬라이스 추출 후:
   - `HDGST` 활성화 시: 헤더 CRC 검증. 불일치 시 `NVME_SC_HEADER_DIGEST_ERROR (0x0281)` 발생 및 종료.
   - `DDGST` 활성화 시: 데이터 CRC 검증. 불일치 시 `NVME_SC_DATA_DIGEST_ERROR (0x0280)` 발생 및 종료.
5. 유효한 PDU 디스패치 및 명령 처리 수행.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 전달됩니다:

```json
{
  "config": {
    "block_size": 512,
    "ioccsz": 1024,
    "max_r2t": 1024,
    "hdgst_enable": true,
    "ddgst_enable": true,
    "c2h_success": false
  },
  "initial_storage": {
    "0": "00...00"
  },
  "operations": [
    {"op": "CONNECT", "cid": 1},
    {"op": "WRITE", "cid": 2, "slba": 0, "nlb": 0, "data_hex": "4141..."},
    {"op": "READ", "cid": 3, "slba": 0, "nlb": 0},
    {"op": "FLUSH", "cid": 4}
  ],
  "dump_lbas": [0]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 한 줄로 출력합니다:

```json
{
  "socket_state": "ESTABLISHED",
  "stats": {
    "commands_processed": 4,
    "r2t_pdus_sent": 0,
    "h2c_data_pdus_received": 0,
    "c2h_data_pdus_sent": 1,
    "bytes_read": 512,
    "bytes_written": 512,
    "digest_errors": 0,
    "terminations": 0
  },
  "tx_pdus": [
    {"pdu_type": "CAPSULE_RESP", "cid": 1, "status": "0x0000", "sq_head": 1},
    {"pdu_type": "CAPSULE_RESP", "cid": 2, "status": "0x0000", "sq_head": 2},
    {"pdu_type": "C2H_DATA", "cid": 3, "data_offset": 0, "data_length": 512, "last": true, "success": false},
    {"pdu_type": "CAPSULE_RESP", "cid": 3, "status": "0x0000", "sq_head": 3},
    {"pdu_type": "CAPSULE_RESP", "cid": 4, "status": "0x0000", "sq_head": 4}
  ],
  "storage_dump": {
    "0": "4141..."
  },
  "event_log": [
    "RX CAPSULE_CMD (CONNECT) cid=1",
    "TX CAPSULE_RESP cid=1 status=0x0000 sq_head=1",
    ...
  ]
}
```
