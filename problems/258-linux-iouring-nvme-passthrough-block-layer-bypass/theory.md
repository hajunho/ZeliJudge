# 핵심 리눅스 커널 스토리지 및 분산 엔지니어링 이론: NVMe io_uring Passthrough

---

## 1. 리눅스 블록 I/O 스택의 진화와 태생적 오버헤드

### 1.1 `struct bio`와 `blk-mq`의 역사적 배경
리눅스 블록 레이어는 회전식 하드 디스크(HDD) 시절 엘리베이터 정렬 및 요청 병합(Merge)을 위해 설계되었습니다.
NVMe SSD의 등장으로 멀티큐 아키텍처인 `blk-mq`가 도입되었으나, 여전히 유저 공간 I/O 요청 하나당 `struct bio` 할당, 세그먼트 매핑, `struct request` 래핑 과정을 거치게 됩니다. 초당 수백만 IOPS 환경에서는 이 객체 생성과 CPU 캐시 미스 자체가 치명적인 병목이 됩니다.

### 1.2 `IORING_OP_URING_CMD`를 통한 패스스루 혁신
리눅스 커널 5.19에 머지된 io_uring char/nvme passthrough는 기존의 무거운 블록 레이어를 우회하고, NVMe 디바이스 노드(`/dev/ng0n1`)의 64바이트 큐 명령어를 커널 드라이버가 그대로 하드웨어 도어벨(Doorbell) 레지스터에 기록하도록 지원합니다.

---

## 2. 락리스 스토리지 파이프라인의 3대 핵심 기둥

### 2.1 Fixed Buffers (`IORING_REGISTER_BUFFERS`)
전통적 O_DIRECT는 매 I/O마다 유저 버퍼 가상 주소를 물리 주소로 변환하고 메모리가 스왑되지 않도록 핀닝(`get_user_pages`)해야 합니다.
`IORING_REGISTER_BUFFERS`는 애플리케이션 시작 시 대용량 Hugepage 메모리를 단 1회 핀닝하여 커널에 사전 등록함으로써, 런타임 페이지 핀닝 및 TLB shootdown 오버헤드를 100% 제거합니다.

### 2.2 Polled I/O (`IORING_SETUP_IOPOLL`)
하드웨어 인터럽트(MSI-X) 핸들링은 CPU 컨텍스트 스위칭과 인터럽트 핸들러 오버헤드를 유발합니다.
IOPOLL 모드는 인터럽트를 비활성화하고, CPU 코어가 직접 NVMe CQ를 폴링하여 완료 여부를 확인합니다. 레이턴시를 30~50us에서 3~5us 수준으로 극한까지 단축시킵니다.

---

## 3. 엔터프라이즈 데이터베이스 적용 사례

1. **RocksDB io_uring Passthrough Backend**:
   - 페이스북(Meta) 연구팀은 RocksDB의 SSTable 읽기/쓰기 백엔드에 io_uring passthrough를 적용하여 플래시 드라이브 처리량을 2.5배 향상시키고 CPU 소비를 40% 절감.
2. **ScyllaDB / Aerospike**:
   - Shard-per-core 아키텍처에서 코어당 전용 io_uring SQ/CQ 인스턴스를 격리 바인딩하여 1,000만 IOPS 초저지연 NoSQL 엔진 구현.
