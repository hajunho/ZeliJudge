# #258 [커널 블록 레이어가 병목이라고요?!: 리눅스 커널 NVMe io_uring 패스스루(IORING_OP_URING_CMD) 커널 블록 레이어 바이패스, CQE 링 오버플로우 및 Polled Completion 락리스 제어 (Linux Storage: io_uring NVMe Passthrough IORING_OP_URING_CMD Block Layer Bypass, CQE Ring Overflow & Polled Completion Control)]

## 1. 장애 및 실무 시나리오

초고성능 분산 시계열 데이터베이스 및 금융 초단타 매매(HFT) 거래소 엔진 팀은 Gen5 NVMe SSD 클러스터를 도입하여 단일 서버당 400만 IOPS(4.0M IOPS) 이상의 극한 I/O 처리량을 목표로 시스템을 구축했습니다.

기존 POSIX AIO(`io_submit`)를 걷어내고 리눅스 5.x 커널의 표준 비동기 프레임워크인 `io_uring`을 적용했으나, 성능 벤치마크 도중 심각한 성능 저하와 커널 병목이 발생했습니다:

```
[운영 장애 및 프로파일링 현상]
1. 단일 코어 IOPS 정체: 초당 400만 IOPS 하드웨어 스펙에도 불구하고, 코어당 78만 IOPS에서 CPU 사용률이 100%에 도달함.
2. 커널 스핀락 및 메모리 할당 병목: `perf top` 프로파일링 결과 `kmem_cache_alloc`(`struct bio`), `blk_mq_dispatch_rq_list`, `blk_queue_enter`의 스핀락 경합률이 38.5%를 차지함.
3. mmap_lock 경합 및 TLB Shootdown 지연: Direct I/O 수행 시 매 요청마다 `get_user_pages_fast()`와 `unpin_user_page()`가 반복 호출되어 P99 지연시간이 24.5us로 튀어 오름.
4. CQ 링 오버플로우 메모리 폭증: 비동기 완료(CQE) 속도를 유저스페이스 리핑 스레드가 따라가지 못해 커널 내부 보조 연결 리스트(`cq_overflow_list`)로 누출, cgroup OOMKilled 사살 위기에 직면함.
```

스토리지 코어 팀은 리눅스 커널 5.19+ 및 6.0+에 도입된 혁신적 기능인 **`io_uring` NVMe 패스스루(`IORING_OP_URING_CMD`)**를 도입하여 커널 블록 레이어(`bio` / `blk-mq`)를 완전히 바이패스하고, 사전에 등록된 고정 버퍼(`IORING_REGISTER_BUFFERS`)와 락리스 폴링(`IORING_SETUP_IOPOLL`)을 결합한 극한의 제로카피 스토리지 파이프라인을 구축하기로 결정했습니다.

---

## 2. 리눅스 커널 아키텍처 및 컴퓨터 과학 원리

### 2.1 전통적 블록 I/O 경로 vs NVMe io_uring 패스스루
- **전통적 블록 레이어 경로 (VFS + blk-mq)**:
  `User Space` $\rightarrow$ `sys_read/write` $\rightarrow$ `VFS` $\rightarrow$ `struct bio 할당` $\rightarrow$ `blk-mq 멀티큐 스케줄러` $\rightarrow$ `NVMe 드라이버`
  - 요청당 다수의 힙 메모리 할당/해제 발생.
  - blk-mq 큐 잠금 및 락 경합으로 단일 코어 80만~100만 IOPS 상한선 봉착.
- **io_uring NVMe 패스스루 (`IORING_OP_URING_CMD`)**:
  유저스페이스가 64바이트 NVMe SQE 커맨드를 직접 io_uring SQ에 채우고, 커널은 `bio`를 일체 생성하지 않고 하드웨어 NVMe 컨트롤러 큐로 직통 전달.
  - 단일 코어 380만 IOPS 이상 달성, 제로 블록 레이어 오버헤드.

```
+-------------------------------------------------------------------------+
|                  NVMe io_uring Passthrough 아키텍처                      |
|                                                                         |
|  [ User Space ]                                                         |
|    - Ring Buffer SQE (64-byte NVMe Command 직접 구성)                   |
|    - IORING_REGISTER_BUFFERS (Hugepage DMA 버퍼 사전 고정)               |
|                                     │                                   |
|                                     ▼ IORING_OP_URING_CMD               |
|  [ Linux Kernel ]                                                       |
|    - Block Layer (VFS, bio, blk-mq) 완전 바이패스!                      |
|    - get_user_pages_fast() 제거 (Fixed Buffer Zero-Pinning)             |
|                                     │                                   |
|                                     ▼ Direct Hardware Queue             |
|  [ NVMe SSD Controller ]                                                |
|    - NVMe ASQ/ACQ -> DMA -> Flash Array (P99 < 5us, 3.8M+ IOPS)         |
+-------------------------------------------------------------------------+
```

### 2.2 CQE 링 오버플로우와 백프레셔 제어
완료 이벤트 링(CQ Ring)의 크기가 부족하면 커널은 `cq_overflow_list`라는 보조 연결 리스트에 CQE를 동적 할당하여 적재합니다. 이는 무잠금(Lock-Free) 원칙을 깨뜨리고 메모리 누수를 유발하므로, `cq_size >= sq_size * 2` 크기를 확보하고 수거 지연을 엄격히 통제해야 합니다.

---

## 3. 입력 사양 (Input Specification)

표준 입력(stdin)으로 스토리지 I/O 설정 JSON 객체가 주어집니다:

```json
{
  "sq_size": 1024,
  "cq_size": 2048,
  "io_count": 500000,
  "use_nvme_passthrough": true,
  "use_fixed_buffers": true,
  "use_iopoll": true,
  "reap_batch_size": 64,
  "reap_interval_us": 5,
  "nvme_queue_depth": 1024
}
```

---

## 4. 출력 사양 (Output Specification)

표준 출력(stdout)으로 다음 스키마의 JSON을 한 줄로 출력합니다:

```json
{
  "status": "OPTIMAL_NVME_PASSTHROUGH_ZERO_COPY_PIPELINE",
  "io_performance": {
    "completed_iops": 3850000,
    "p99_latency_us": 4.8,
    "bio_allocations": 0,
    "blk_mq_spinlock_contention_pct": 0.0,
    "page_pin_unpin_cycles": 0,
    "cqe_overflow_count": 0,
    "sq_stall_count": 0
  },
  "diagnostics": [
    "커널 블록 레이어 완전 바이패스(bio/blk-mq 0건), 고정 버퍼 DMA 사전 핀닝, 락리스 IOPOLL 전용 수거 파이프라인이 완벽히 가동 중입니다.",
    "초당 385만 IOPS(3.85M IOPS) 달성 및 P99 극저지연(4.8us) 사수 성공. CQE 오버플로우 0건."
  ],
  "recommendation": "최적의 초고성능 NVMe io_uring 패스스루 아키텍처 상태 유지."
}
```

### 판정 상태 (`status`):
1. `"CLASSICAL_BLOCK_LAYER_BIO_OVERHEAD_BOTTLENECK"`: NVMe 패스스루 미적용으로 인한 `bio`/`blk-mq` 스핀락 병목.
2. `"DYNAMIC_PAGE_PINNING_TLB_SHOOTDOWN_STALL"`: 고정 버퍼 미등록으로 인한 동적 페이지 핀닝 및 mmap_lock 경합.
3. `"IOPOLL_COMPLETION_REAPING_STARVATION"`: IOPOLL 모드에서 수거 간격 초과로 인한 SQ 고갈 스톨.
4. `"CQE_RING_OVERFLOW_AUXILIARY_LIST_BLOAT"`: CQ 링 크기 부족으로 인한 커널 내부 오버플로우 리스트 메모리 유출.
5. `"OPTIMAL_NVME_PASSTHROUGH_ZERO_COPY_PIPELINE"`: 3.8M+ IOPS, P99 < 5us의 완전 제로카피 무잠금 파이프라인.
