# Problem #390: Linux Kernel io_uring Direct Descriptors & Fixed Buffers Engine (`io_uring/filetable.c`, `io_uring/rsrc.c`)

## 문제 설명

리눅스 커널에서 전통적인 POSIX 파일 디스크립터(File Descriptor / FD) 기반 I/O는 백만 단위의 초고속 IOPS(NVMe SSD 및 100GbE 네트워킹) 환경에서 심각한 확장성 병목을 유발합니다:

1. **원자적 참조 카운트 바운싱 (Atomic Refcount Bouncing)**:
   - 모든 파일 연산(`read`, `write`, `preadv`)은 파일 구조체(`struct file`)를 보호하기 위해 진입 시 `fget()`, 탈출 시 `fput()`을 호출합니다.
   - 이는 멀티코어 환경에서 공유 파일 객체의 `f_count` 필드에 대해 원자적 증감(`atomic_long_inc/dec`)을 강제하므로, L1/L2 캐시라인 무효화 폭풍(Cacheline Bouncing)을 유발합니다.
2. **프로세스 파일 테이블 락 경합 (fdtable Contention)**:
   - 시스템 콜 호출 시마다 프로세스의 `struct files_struct` 파일 테이블 배열을 조회하고 슬롯을 잠그는 오버헤드가 발생합니다.
3. **런타임 페이지 핀/언핀 오버헤드 (Page Pinning Churn)**:
   - 비동기 DMA를 수행할 때마다 커널은 유저 메모리 페이지를 물리 메모리에 고정(`pin_user_pages()`)하고 완료 시 해제(`unpin_user_page()`)하는 페이지 테이블 순회 작업을 반복합니다.

Jens Axboe와 리눅스 커널 커뮤니티는 이 세 가지 근본적 한계를 완전히 타파하기 위해 **io_uring Direct Descriptors (고정 파일 테이블, `io_uring/filetable.c`)** 및 **Fixed Buffers (고정 버퍼, `io_uring/rsrc.c`)**를 도입했습니다:

```
+----------------------------------------------------------------------------------------------------+
|                               io_uring Direct Descriptors & Fixed Buffers                          |
+----------------------------------------------------------------------------------------------------+
| [ User Space Application ]                                                                         |
|   | ioctl(IORING_REGISTER_FILES) -> Pins files ONCE, assigns into io_ring fixed filetable slots    |
|   | ioctl(IORING_REGISTER_BUFFERS) -> Pins memory pages ONCE into io_mapped_ubuf structures       |
+---+------------------------------------------------------------------------------------------------+
| [ io_uring Fast Path: Submission Queue Entry (SQE) ]                                               |
|   | Case A: fd_type == "DIRECT" (IOSQE_FIXED_FILE):                                                |
|   |   -> Directly index io_ring_ctx->file_table[slot_idx]                                          |
|   |   -> ZERO fget() / ZERO fput() atomic operations! (Atomic Refcount Bouncing ELIMINATED)        |
|   | Case B: buf_type == "FIXED":                                                                   |
|   |   -> Directly index io_ring_ctx->buf_table[buf_idx]                                            |
|   |   -> ZERO pin_user_pages() / ZERO unpin overhead! (Page Pinning Churn ELIMINATED)              |
+---+------------------------------------------------------------------------------------------------+
| [ Completion Queue (CQE) ]                                                                         |
|   | Instant Zero-Syscall, Zero-Lock, Zero-Atomic Completion Delivery!                              |
+----------------------------------------------------------------------------------------------------+
```

### 아키텍처 동작 규칙

1. **파일 등록 (`REGISTER_FILES`) & 슬롯 갱신 (`UPDATE_FILES`)**:
   - `REGISTER_FILES`: 파일 배열을 io_uring 컨텍스트 내부 고정 파일 테이블(`file_table[slot]`)에 등록합니다. 등록 시 1회의 `fget()`만 수행됩니다.
   - `UPDATE_FILES`: 특정 슬롯의 파일을 동적으로 교체합니다 (`fput()` 이전 파일, `fget()` 새 파일).
2. **버퍼 등록 (`REGISTER_BUFFERS`)**:
   - 유저 메모리 버퍼를 사전 핀(Pre-pin)하여 `buf_table[buf_idx]`에 저장합니다. 등록 시 1회 페이지만 핀합니다.
3. **SQE 제출 및 처리 (`SUBMIT_SQE`)**:
   - `fd_type`:
     - `POSIX`: 기존 파일 테이블 조회. 연산 1회당 `atomic_refcount_ops += 2` (`fget` + `fput`). FD 부재 시 `EBADF`.
     - `DIRECT`: 고정 파일 테이블 인덱스 참조. `atomic_refcount_ops += 0`, `refcount_ops_saved += 2` 절감. 슬롯 비어있을 시 `EBADF_DIRECT_SLOT_EMPTY`.
   - `buf_type`:
     - `NORMAL`: 동적 버퍼. 연산 1회당 `page_pin_ops += 2` (`pin` + `unpin`).
     - `FIXED`: 사전 등록 버퍼 인덱스 참조. `page_pin_ops += 0`, `page_pins_saved += 2` 절감. 미등록 인덱스 시 `EFAULT_FIXED_BUF_NOT_REGISTERED`.

당신은 리눅스 커널 io_uring의 다이렉트 디스크립터 파일 테이블, 고정 버퍼 관리 및 원자적 참조 카운트 절감 메트릭을 정밀 시뮬레이션하는 엔진을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "file_table_capacity": 4,
    "buf_table_capacity": 4,
    "posix_fds": { "3": "/data/file.txt" }
  },
  "commands": [
    { "op": "REGISTER_FILES", "files": ["/data/direct.txt"] },
    { "op": "REGISTER_BUFFERS", "buffers": [{"buf_idx": 0, "vaddr": 2130706432, "size": 65536}] },
    { "op": "SUBMIT_SQE", "user_data": 1, "fd_type": "DIRECT", "fd_val": 0, "buf_type": "FIXED", "buf_val": 0, "length": 4096 }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없이 컴팩트한 단일 JSON 객체를 출력합니다:

```json
{
  "total_sqes": 1,
  "total_cqes": 1,
  "atomic_refcount_ops": 1,
  "refcount_ops_saved": 2,
  "page_pin_ops": 1,
  "page_pins_saved": 2,
  "active_direct_files": 1,
  "active_fixed_buffers": 1,
  "events": [ ... ]
}
```
