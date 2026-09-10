# Linux Kernel io_uring NVMe Passthrough (uring_cmd) & 블록 레이어 직통 바이패스 엔진

## 문제 설명

초고속 NVMe SSD와 CXL 메모리 풀이 보편화된 최신 분산 스토리지 환경에서 기존 리눅스 커널의 블록 I/O 스택은 심각한 CPU 오버헤드 병목을 유발합니다. 전통적인 `read()`/`write()` 및 `libaio` 경로는 다음과 같이 복잡한 계층을 통과합니다:

```
[ 전통적인 Linux Block I/O 경로 ]
User Space ──(syscall)──> VFS ──> Page Cache / Direct I/O ──> struct bio 할당
  └──> blk-mq Request Queue ──> I/O 스케줄러 ──> Hardware Dispatch Tag 할당
       └──> NVMe Driver ──> Hardware SQ Doorbell Ring (수 마이크로초 CPU 지연!)

[ io_uring NVMe Passthrough (uring_cmd) 바이패스 경로 ]
User Space (SQ Ring) ──[ IORING_OP_URING_CMD ]──> io_uring_cmd()
  └──> nvme_uring_cmd() ──> Zero-Copy / Direct Tag ──> NVMe SQ (블록 레이어 완전 우회!)
       ├── SQPOLL 활성화: io_sq_thread 커널 폴링 (시스템콜 0회!)
       ├── IOPOLL 활성화: NVMe CQ 하드웨어 폴링 (인터럽트 IRQ 0회!)
       └── CQE32 확장: 32바이트 Big CQE로 NVMe Status DW0/DW1 즉시 반환
```

Linux 5.19 커널에 공식 도입된 **`IORING_OP_URING_CMD` (io_uring passthrough)**는 유저 영역 애플리케이션(SPDK, RocksDB, Ceph, QEMU 등)이 블록 계층(`struct request`, `struct bio`, I/O 엘리베이터 등)의 오버헤드를 완전히 건너뛰고 커널 NVMe 드라이버의 하드웨어 제출 큐에 직접 NVMe 명령어를 투입할 수 있도록 혁신했습니다.

본 문제는 `io_uring` 파스스루 프레임워크와 NVMe 문자 디바이스(`nvme_uring_cmd`)의 명령어 해석, 유효성 검증, 폴링 최적화, Big CQE 반환 상태 머신을 정밀하게 에뮬레이션하는 **`io_uring` NVMe Passthrough 엔진**을 구현하는 것입니다.

---

## 핵심 엔진 요구사항

### 1. 명령어 검증 및 네임스페이스 상태 검사
- **Opcode 유효성 검증**:
  - 오직 `IORING_OP_URING_CMD`만 허용됩니다. 다른 opcode 전달 시 즉시 `-EINVAL` (`-22`), status: `ERR_INVALID_OPCODE`로 실패 CQE를 생성합니다.
- **네임스페이스 존재 검증**:
  - 지정된 `nsid`가 컨트롤러에 등록된 네임스페이스 목록에 없으면 `-ENODEV` (`-19`), status: `ERR_INVALID_NSID`를 반환합니다.
- **읽기 전용 보호 (Read-only Namespace)**:
  - 네임스페이스가 `readonly: true`일 때 `WRITE` 또는 `DSM_TRIM` 명령이 들어오면 `-EROFS` (`-30`), status: `ERR_READONLY_NAMESPACE`를 반환합니다. (CQE32 활성화 시 NVMe Status `640` / `0x280` 반환)
- **LBA 경계 검사**:
  - `slba < 0` 또는 `slba + nlb > size_lba`인 경우 `-ENOSPC` (`-28`), status: `ERR_LBA_OUT_OF_BOUNDS`를 반환합니다. (CQE32 활성화 시 NVMe Status `128` / `0x80` 반환)
- **버퍼 길이 정합성 검사**:
  - `READ` 및 `WRITE` 요청 시 필요한 바이트 수($	ext{nlb} 	imes 	ext{lba\_bytes}$)보다 유저 버퍼 `buffer_len`이 작으면 `-EFAULT` (`-14`), status: `ERR_BUFFER_OVERFLOW`를 반환합니다.
- **큐 깊이 (Queue Depth) 고갈 검사**:
  - 활성 태그 수가 `queue_depth`에 도달하면 `-EAGAIN` (`-11`), status: `ERR_QUEUE_FULL`을 반환합니다.

### 2. 고속 지연시간(Latency) 시뮬레이션
- 블록 레이어를 우회하는 uring_cmd 기본 처리 지연시간 모델:
  $$	ext{base\_lat} = 1.5 + \left(rac{	ext{bytes}}{4096}ight) 	imes 0.1 \quad (\mu s) \quad (	ext{READ/WRITE})$$
  (단, `FLUSH`나 `DSM_TRIM` 등 비데이터 명령어는 기본 $1.2\,\mu s$)
- **SQPOLL 활성화 시**: 시스템 콜 진입 비용 절감으로 지연시간 $-0.5\,\mu s$ 보정.
- **IOPOLL 활성화 시**: 하드웨어 인터럽트 컨텍스트 스위칭 생략으로 지연시간 $-0.4\,\mu s$ 보정.
- 최종 지연시간은 최소 $0.2\,\mu s$ 이상으로 보장하며 소수점 둘째 자리로 반올림합니다.

### 3. 완성 큐(CQE) 및 32바이트 Big CQE 포맷
- 성공 시 CQE:
  - `user_data`: 요청의 `user_data`
  - `res`: 전송된 총 바이트 수 (`READ`/`WRITE`) 또는 `0` (`FLUSH`/`DSM_TRIM` 등)
  - `status`: `"SUCCESS_PASSTHROUGH"`
  - `latency_us`: 계산된 지연시간
- **`cqe32_enabled` 활성화 시**:
  - `extra1`: 성공 시 `slba & 0xFFFFFFFF` (하위 32비트), 실패 시 해당 NVMe 에러 코드 (예: `0x280`, `0x80` 등 정수형)
  - `extra2`: `0` (NVMe CQE DW1 예약/상태)

---

## 입력 형식

JSON 문자열이 표준 입력(`stdin`)으로 주어집니다:

```json
{
  "config": {
    "sqpoll_enabled": true,
    "iopoll_enabled": true,
    "cqe32_enabled": true,
    "queue_depth": 128
  },
  "namespaces": [
    {
      "nsid": 1,
      "size_lba": 262144,
      "lba_bytes": 4096,
      "readonly": false
    }
  ],
  "sqes": [
    {
      "sqe_id": "SQE_WRITE_01",
      "user_data": "UD_WR_01",
      "opcode": "IORING_OP_URING_CMD",
      "cmd_op": "NVME_URING_CMD_IO",
      "nsid": 1,
      "nvme_opcode": "WRITE",
      "slba": 100,
      "nlb": 8,
      "buffer_len": 32768
    }
  ]
}
```

---

## 출력 형식

처리된 CQE 리스트와 통계 메트릭을 JSON 형태로 표준 출력(`stdout`)에 공백 없이 출력합니다:

```json
{
  "engine": "io_uring_passthrough_nvme",
  "metrics": {
    "total_sqes": 1,
    "completed_cqes": 1,
    "successful_bypasses": 1,
    "error_count": 0,
    "total_bytes_transferred": 32768,
    "avg_latency_us": 1.4,
    "peak_queue_utilization_pct": 0.8,
    "sqpoll_active": true,
    "iopoll_active": true,
    "cqe32_mode": true
  },
  "verdict": "ZERO_COPY_PASSTHROUGH_OPTIMAL",
  "cqes": [
    {
      "user_data": "UD_WR_01",
      "res": 32768,
      "status": "SUCCESS_PASSTHROUGH",
      "latency_us": 1.4,
      "extra1": 100,
      "extra2": 0
    }
  ]
}
```

---

## 판정 규칙 (`verdict`)

1. `error_count == 0`이고 `successful_bypasses > 0`:
   `"ZERO_COPY_PASSTHROUGH_OPTIMAL"`
2. `successful_bypasses > 0`이고 `error_count > 0`:
   `"PARTIAL_PASSTHROUGH_WITH_EXCEPTIONS"`
3. 그 외 (모든 SQE 실패 또는 빈 큐):
   `"PASSTHROUGH_PIPELINE_FAILED"`
