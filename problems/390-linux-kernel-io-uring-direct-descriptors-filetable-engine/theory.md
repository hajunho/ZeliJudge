# Theory: Linux Kernel io_uring Direct Descriptors & Resource Registration (`io_uring/filetable.c`, `io_uring/rsrc.c`)

## 1. POSIX 파일 디스크립터의 원자적 참조 카운트 병목

리눅스 VFS(Virtual File System) 계층에서 파일 디스크립터는 정수형 인덱스(`int fd`)로 표현됩니다.
- 프로세스가 `read(fd, ...)` 또는 `write(fd, ...)`를 호출하면 커널은 `fget_light()` 또는 `fget()`을 수행하여 `struct file` 객체를 조회합니다.
- `fget()`은 `atomic_long_inc(&file->f_count)`를 수행하여 멀티스레드 환경에서 다른 스레드가 `close(fd)`를 호출하더라도 I/O가 완료될 때까지 메모리 해제를 방어합니다.
- 연산 종료 시 `fput()`이 호출되어 `atomic_long_dec_and_test(&file->f_count)`를 실행합니다.

### 1.1 백만 IOPS 시대의 캐시라인 무효화 재앙
NVMe Gen5 SSD 및 100GbE/400GbE 네트워크 환경에서 단일 노드가 초당 1,000,000회 이상의 I/O를 처리할 때:
- 동일한 소켓이나 디스크립터를 공유하는 수십 개의 워커 스레드가 `f_count` 캐시라인에 대해 동시 원자적 쓰기 트랜잭션(Locked Instructions / Bus Lock / Cacheline Invalidation)을 발생시킵니다.
- 프로파일링 시 CPU 사이클의 15~25%가 오직 `fget()`/`fput()` 원자적 경합에 낭비되는 병목이 관측됩니다.

---

## 2. io_uring Direct Descriptors (`filetable.c`)

Jens Axboe는 io_uring에 **Direct Descriptors (고정 파일 테이블)**를 도입하여 VFS 파일 테이블과 `fget()`/`fput()` 오버헤드를 근본적으로 제거했습니다:

### 2.1 동작 원리
1. **사전 고정 등록 (`IORING_REGISTER_FILES`)**:
   - 유저가 파일 디스크립터 목록을 등록하면 커널은 각 파일에 대해 단 1회의 `fget()`만을 호출하여 고정 파일 테이블(`io_ring_ctx->file_table`)에 포인터를 영구 바인딩합니다.
2. **다이렉트 슬롯 참조 (`IOSQE_FIXED_FILE`)**:
   - 이후 제출되는 모든 SQE는 `fd` 필드에 POSIX 번호 대신 `file_table`의 정수 배열 인덱스를 전달합니다.
   - 커널은 프로세스 `files_struct`를 탐색하지 않고 `ctx->file_table.files[slot]`에서 포인터를 즉각 역참조합니다.
   - I/O 진입 및 종료 시 `fget()` 및 `fput()`이 **완전히 생략**되어 원자적 참조 카운트 오버헤드가 **정확히 0**이 됩니다.

---

## 3. io_uring Fixed Buffers (`rsrc.c`)

- 통상적인 Direct I/O(O_DIRECT)에서도 커널은 유저 가상 주소를 물리 메모리 페이지 프레임으로 변환하고 DMA 도중 페이지가 해제되지 않도록 `pin_user_pages()`를 호출합니다.
- `IORING_REGISTER_BUFFERS`를 사용하면 사전 등록 시점에 유저 버퍼를 한 번만 핀하고 I/O 시에는 사전 생성된 산재-집적 리스트(Scatter-Gather Table / `struct io_mapped_ubuf`)를 직통 참조하므로 페이지 핀/언핀 오버헤드가 완벽히 소멸합니다.
