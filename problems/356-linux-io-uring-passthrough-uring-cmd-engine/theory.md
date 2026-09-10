# Linux Kernel io_uring Passthrough (uring_cmd) 및 NVMe 다이렉트 바이패스 이론

## 1. 리눅스 스토리지 스택의 병목과 역사적 진화

초기 유닉스와 리눅스의 I/O 서브시스템은 기계적 회전 디스크(HDD)를 위해 설계되었습니다. 회전 암의 이동(Seek Time)과 회전 지연(Rotational Latency)이 수 밀리초($ms$)에 달했으므로, 커널 내부의 소프트웨어 레이어가 소비하는 수 마이크로초($\mu s$)의 지연시간은 전체 I/O 시간에 비하면 무시할 만한 수준이었습니다.

그러나 PCIe NVMe SSD, CXL 메모리 디바이스 및 초고속 비휘발성 저장장치가 보편화되면서 장치 자체의 하드웨어 응답 지연은 $10\,\mu s$ 이하, IOPS는 수백만 단위를 초과하게 되었습니다. 이때 커널 내부의 기존 블록 계층(Block Layer)이 병목의 주원인으로 부상했습니다:
1. **`struct bio` 및 `struct request` 할당 오버헤드**:
   메모리 슬랩 할당자(`kmem_cache_alloc`) 호출, 분할/병합 검사, 바운스 버퍼링.
2. **I/O 스케줄러(Elevator) 경유**:
   MQ-DEADLINE, BFQ, 또는 None 설정에도 불구하고 블록 큐 락 및 디스패치 큐 이동 비용 발생.
3. **태그 매핑 및 변환**:
   소프트웨어 블록 큐의 요청 ID를 하드웨어 NVMe SQ 태그로 상호 매핑하는 이중 관리.
4. **시스템 콜 및 컨텍스트 스위칭**:
   동기식 `pread`/`pwrite`의 유저-커널 전환 트랩 비용.

---

## 2. io_uring과 uring_cmd의 등장 (Linux 5.19+)

Jens Axboe에 의해 도입된 `io_uring`은 SQ(Submission Queue)와 CQ(Completion Queue)라는 공유 링 버퍼(Shared Ring Buffer)를 유저 영역과 커널이 직접 공유하여 시스템 콜 없이 비동기 I/O를 수행하는 획기적 프레임워크였습니다.

그러나 초기 `io_uring`(`IORING_OP_READ`, `IORING_OP_WRITE`) 역시 블록 계층(`blk-mq`)을 통과해야 했습니다. 이를 극복하기 위해 Linux 5.19에서 **`IORING_OP_URING_CMD`**가 도입되었습니다.

```c
struct io_uring_sqe {
    __u8    opcode;         /* IORING_OP_URING_CMD */
    __u8    flags;          /* IOSQE_FIXED_FILE 등 */
    __u16   ioprio;
    __s32   fd;             /* /dev/ng0n1 (NVMe Generic Char Device) */
    union {
        __u64   off;
        __u64   addr2;
    };
    union {
        __u64   addr;       /* struct nvme_uring_cmd 포인터 */
        __u64   splice_off_in;
    };
    __u32   len;
    union {
        __kernel_rwf_t  rw_flags;
        __u32           cmd_op; /* NVME_URING_CMD_IO / NVME_URING_CMD_ADMIN */
    };
    __u64   user_data;
    ...
};
```

`file_operations` 구조체에 새로 추가된 `uring_cmd` 함수 포인터를 통해, 커널 VFS와 블록 레이어를 통째로 건너뛰고 대상 디바이스 드라이버(예: `nvme_uring_cmd`)로 SQE가 즉시 직행합니다:

```c
int nvme_uring_cmd(struct io_uring_cmd *ioucmd, unsigned int issue_flags);
```

---

## 3. NVMe 캐릭터 디바이스 (`/dev/ngXnY`)와 제로카피

전통적인 블록 디바이스(`/dev/nvme0n1`) 대신 NVMe 일반 문자 디바이스(Generic Character Device, `/dev/ng0n1`)를 타깃으로 삼음으로써 다음 최적화가 달성됩니다:
1. **No Block Layer Allocation**:
   `struct request`나 `blk-mq`를 전혀 거치지 않고 드라이버가 하드웨어 커맨드(64바이트 NVMe Submission Dword)를 직접 구성합니다.
2. **Zero-Copy DMA Mapping**:
   유저 공간의 가상 주소 버퍼를 커널 내부로 복사하지 않고 `bio_map_user_iov()`를 통해 물리 페이지로 즉시 핀(Pin)한 뒤 컨트롤러의 PRP(Physical Region Page) 또는 SGL(Scatter Gather List)로 직결합니다.
3. **하드웨어 큐 태그 직접 사용**:
   NVMe 하드웨어 큐의 고유 Command ID(CID)를 직접 부여하여 완성 시 `io_uring_cmd_done()` 콜백으로 0.1마이크로초 내에 CQE를 발행합니다.

---

## 4. 고성능 3대 기둥: SQPOLL, IOPOLL, Big CQE (CQE32)

### 4.1 SQPOLL (Submission Queue Polling)
- 플래그: `IORING_SETUP_SQPOLL`
- 전용 커널 스레드(`io_sq_thread`)가 백그라운드에서 유저 공간의 SQ 링 버퍼 헤드/테일을 감시합니다.
- 유저 프로세스는 `io_uring_enter()` 시스템 콜을 단 1회도 호출하지 않고 메모리 쓰기(`atomic_store`)만으로 I/O를 제출합니다.

### 4.2 IOPOLL (Hardware Completion Polling)
- 플래그: `IORING_SETUP_IOPOLL`
- 하드웨어 NVMe Completion Queue(CQ)의 Phase Bit를 소프트웨어 루프에서 직접 폴링합니다.
- 하드웨어 MSI-X 인터럽트 수신, 커널 IRQ 핸들러 진입, 락 획득 및 컨텍스트 스위칭 비용이 완전히 소거됩니다.

### 4.3 32-Byte Big CQE (`IORING_SETUP_CQE32`)
- 기본 16바이트 CQE(`user_data`, `res`, `flags`)는 NVMe의 풍부한 반환 정보(예: CQE Dword 0의 명령어 특정 결과, CQE Dword 1의 상태 코드 및 Phase)를 모두 담기 부족합니다.
- `CQE32` 모드는 완성 큐 항목을 32바이트로 확장하여 `extra1`과 `extra2`에 NVMe 원시 상태를 온전히 보존하여 유저 영역으로 전달합니다.

---

## 5. 실무 스토리지 아키텍처 및 벤치마크 결과

fio(Flexible I/O Tester) 및 RocksDB 환경에서 `io_uring_cmd` 파스스루를 적용한 실측 결과:
- **IOPS**: 전통적인 `sync` 대비 약 300% ~ 400% 향상, 표준 `io_uring` 블록 대비 약 20% ~ 35% 추가 향상.
- **평균 지연시간(Average Latency)**: $15\,\mu s ightarrow 4\,\mu s$ 수준으로 70% 이상 단축.
- **p99.99 꼬리 지연(Tail Latency)**: 블록 레이어 락 경합 및 인터럽트 지터 제거로 극적인 안정화 달성.
- **SPDK(Storage Performance Development Kit)와의 비교**:
  SPDK는 완전한 유저 스페이스 전용 드라이버(UIO/VFIO)로 최고 성능을 내지만 커널의 보호, 메모리 격리, 권한 제어를 모두 상실합니다. 반면 `io_uring` 파스스루는 **커널의 안전성(Security Boundary)과 POSIX 파일 권한을 완벽히 유지하면서도 SPDK에 근접하는 초고성능**을 제공하는 최적의 엔터프라이즈 솔루션입니다.
