# 이론 문서 409: Linux 커널 NVMe-oF(RDMA) 전송 계층 및 메모리 등록(FRWR) 아키텍처 심층 분석

## 1. 개요 및 배경: 네트워크 스토리지의 진화와 커널 바이패스/제로카피의 필연성

과거 엔터프라이즈 데이터센터를 지배했던 네트워크 스토리지 프로토콜인 파이버 채널(Fibre Channel)이나 iSCSI(SCSI over TCP/IP)는 기계식 하드 디스크 드라이브(HDD)의 밀리초(ms) 단위 회전 지연 시간(Rotational Latency)을 전제로 설계되었습니다. 이러한 환경에서는 호스트 운영체제의 네트워크 스택(소켓 버퍼 복사, TCP 체크섬 계산, 컨텍스트 스위칭, 인터럽트 핸들러 오버헤드)이 차지하는 수십 마이크로초(µs)의 CPU 오버헤드는 병목으로 체감되지 않았습니다.

그러나 마이크로초(µs) 이하의 초저지연과 수백만 IOPS를 제공하는 PCIe NVMe SSD의 등장과, 초거대 AI 모델의 분산 텐서 병렬 학습(Tensor Parallelism), GPU Direct Storage(GDS), 실시간 분산 NoSQL 데이터베이스의 등장은 기존 스토리지 네트워크 스택의 한계를 여실히 드러냈습니다. 100Gbps~400Gbps 고속 네트워크 환경에서 TCP/IP 스택을 통과하는 것만으로 호스트 CPU 코어가 100% 포화되며 패킷 드롭과 지연 시간 스파이크가 발생하는 현상이 일상화되었습니다.

리눅스 커널은 이를 해결하기 위해 NVMe 사양의 패브릭 확장인 **NVMe over Fabrics (NVMe-oF)** 표준을 수립하고, 그중에서도 가장 뛰어난 성능을 자랑하는 **RDMA (Remote Direct Memory Access) 전송 계층 (`drivers/nvme/host/rdma.c`, `drivers/nvme/target/rdma.c`)**을 커널 서브시스템으로 완성하였습니다.

---

## 2. Linux 커널 RDMA 서브시스템과 Queue Pair(QP) 아키텍처

RDMA는 네트워크 어댑터(HCA, Host Channel Adapter)가 원격 노드의 메인 메모리에 CPU 개입 없이 직접 데이터를 읽거나 쓸 수 있도록 지원하는 하드웨어 가속 기술입니다. InfiniBand 네이티브 패브릭뿐만 아니라 데이터센터 이더넷 상에서 동작하는 RoCEv2(RDMA over Converged Ethernet) 환경에서도 완벽히 구동됩니다.

```
+==================================================================================================+
|                  Linux Host                                            NVMe-oF Target            |
|                                                                                                  |
| [ Host Memory Buffer ]                                            [ Target Controller RAM ]      |
|   (Registered MR)                                                                                |
|          ^                                                                    ^                  |
|          | Zero-Copy DMA                                                      | Zero-Copy DMA    |
|          v                                                                    v                  |
|   +--------------+      Send Queue: Command Capsule (SGL)      +------------------+              |
|   |   Host HCA   | ------------------------------------------> |   Target HCA     |              |
|   |  (Queue Pair)| <------------------------------------------ |  (Queue Pair)    |              |
|   +--------------+      RDMA Read/Write Direct Payload Data    +------------------+              |
|          ^                                                                                       |
|          | Poll CQ (ib_poll_cq)                                                                  |
|   [ nvme_rdma_poll ] <--- Target SQHD & CQE Completion Doorbell                                  |
+==================================================================================================+
```

### 2.1 큐 쌍(Queue Pair, QP)의 매핑 구조
- 리눅스 블록 계층(`blk-mq`)의 각 하드웨어 큐(`struct blk_mq_hw_ctx`)는 NVMe I/O 큐와 1:1로 대응되며, NVMe-oF RDMA 드라이버 내부에서 독립된 하나의 **RDMA RC(Reliable Connected) Queue Pair (`struct ib_qp`)**에 바인딩됩니다.
- QP는 크게 두 개의 하드웨어 링 버퍼로 구성됩니다:
  1. **송신 큐 (Send Queue, SQ)**: 호스트가 원격 타깃으로 NVMe 명령 캡슐(`struct nvme_command`) 또는 RDMA Read/Write Work Request를 전달하는 큐.
  2. **수신 큐 (Receive Queue, RQ)**: 타깃으로부터 반환되는 NVMe 응답 CQE(`struct nvme_completion`)를 수신하기 위해 사전 배치된 수신 버퍼 큐.

---

## 3. 메모리 등록(Memory Registration)과 고속 등록(FRWR)

운영체제의 가상 메모리는 페이지 단위로 물리적 메모리에 불연속적으로 매핑되어 있으며, 가상 메모리 관리자(VMM)에 의해 언제든지 스왑아웃되거나 다른 물리 프레임으로 이동될 수 있습니다.

따라서 하드웨어 NIC(HCA)가 호스트 메모리에 직접 DMA를 수행하려면 다음 두 가지 조건이 만족되어야 합니다:
1. 해당 메모리 페이지들이 물리적 메모리에 고정(Pinning)되어 마이그레이션이나 스왑아웃이 차단되어야 합니다.
2. HCA 하드웨어 내부의 변환 테이블(Translation Table)에 가상 주소(VA)와 물리 주소(PA)의 매핑이 등록되어야 하며, 불법적인 메모리 접근을 방지하는 고유한 보호 키인 **L_Key (Local Key)**와 **R_Key (Remote Key)**가 발급되어야 합니다.

```
+--------------------------------------------------------------------------------------------------+
| Fast Registration Work Request (FRWR) Lifecycle                                                  |
|                                                                                                  |
| 1. ib_map_mr_sg(mr, sg, sg_nents)                                                                |
|    - Scatterlist 물리 주소 배열을 MR에 매핑                                                      |
| 2. Post IB_WR_REG_MR Work Request to QP Send Queue                                               |
|    - HCA 하드웨어가 새 rkey 생성 및 활성화 (Zero CPU Interrupts!)                                |
| 3. Transmit Keyed SGL to Remote Target                                                           |
|    - Target HCA reads/writes directly using rkey                                                 |
| 4. Post IB_WR_LOCAL_INV Work Request                                                             |
|    - I/O 완료 시 rkey 즉각 무효화 및 MR Pool로 반환                                              |
+--------------------------------------------------------------------------------------------------+
```

### 3.1 레거시 FMR vs 현대 FRWR (Fast Registration Work Requests)
과거 리눅스 인피니밴드 서브시스템은 FMR(Fast Memory Registration)을 사용했으나, 이는 커널 공간에서 동기식 시스템 콜 인터페이스를 필요로 하여 확장성에 한계가 있었습니다.
현대 커널(`CONFIG_NVME_RDMA`)은 **FRWR (`IB_WR_REG_MR`)**을 전면 채택하였습니다:
- 메모리 등록 자체를 하나의 Work Request(WR) 형태로 Send Queue에 포스팅하여 하드웨어 파이프라인 상에서 비동기적으로 처리합니다.
- I/O가 완료되면 `IB_WR_LOCAL_INV` WR을 포스팅하여 하드웨어 단에서 원격 R_Key를 즉시 무효화시킵니다. 이를 통해 악의적인 원격 노드가 이전 키로 호스트 메모리를 침범하는 보안 위협을 원천 차단합니다.

---

## 4. 인-캡슐 데이터 패스트패스와 Keyed SGL 전송 분기

NVMe-oF RDMA 계층은 I/O 크기에 따라 성능과 오버헤드를 극대화하기 위해 엄격한 2-트랙 라우팅을 수행합니다:

### 4.1 소용량 I/O: 인-캡슐 데이터 (In-Capsule Data)
- 전송 데이터 크기가 임계값(`in_capsule_data_size`, 통상 4096바이트) 이하인 경우:
- 64바이트 NVMe Submission Queue Entry(SQE) 명령 캡슐 바로 뒤의 여유 버퍼에 페이로드 데이터를 연속해서 실어 보냅니다.
- 드라이버는 FRWR 메모리 등록(`IB_WR_REG_MR`)이나 로컬 무효화(`IB_WR_LOCAL_INV`)를 전혀 수행하지 않으며, 단 한 번의 `IB_WR_SEND`만으로 명령과 데이터를 원샷 전송합니다.
- RTT 지연 시간이 1회로 단축되며, MR 풀 경합이 발생하지 않습니다.

### 4.2 대용량 I/O: Keyed SGL (Scatter-Gather List)
- 데이터 크기가 임계값을 초과하는 경우:
- 데이터가 담긴 호스트 메모리 버퍼를 FRWR로 등록하고, 명령 캡슐의 `dptr` 필드에 **Keyed SGL Data Block Descriptor**(`(address, length, rkey)`)를 기록하여 보냅니다.
- 타깃 컨트롤러는 명령을 수신한 후, 하드웨어 RDMA 엔진을 통해 호스트 메모리로부터 직접 데이터를 읽어오거나(Write I/O), 스토리지에서 읽은 데이터를 호스트 메모리로 직접 씁니다(Read I/O).
- 타깃이 최종 NVMe 완료 CQE를 Send하면, 호스트는 CQE를 수신하고 MR을 로컬 무효화하여 풀에 반환합니다.

---

## 5. 크레딧 플로우 제어(Flow Control) 및 장애 격리(Fault Domain)

1. **타깃 수신 크레딧 (Target Credit / SQHD)**:
   - RDMA RC QP의 Send Queue는 유한한 깊이(`queue_depth`)를 가집니다.
   - 호스트는 발주한 명령의 개수(`sq_tail`)와 수신된 완료의 개수(`sq_head`)의 차이를 통해 사용 가능한 크레딧을 관리합니다.
   - 타깃이 보내는 모든 NVMe CQE 응답에는 현재 타깃의 Submission Queue Head 번호인 `sqhd`가 포함되어 있어, 호스트는 이를 통해 자신이 어디까지 명령을 발주할 수 있는지 엄격하게 동기화합니다.
2. **패브릭 링크 장애와 QP 상태 전이**:
   - 패브릭 케이블 분리, 스위치 버퍼 오버플로우, 또는 재시도 한계 초과(`IB_EVENT_QP_FATAL`) 시 QP는 `IB_QPS_ERR` 상태로 강제 전이됩니다.
   - 커널 드라이버는 즉시 모든 인플라이트 요청과 대기열 요청을 `NVME_SC_TRANSPORT_ERROR`로 반환(Flush)하여 상위 블록 계층의 타임아웃 행(Hang)을 방지하고, 다중 경로 장애 조치(NVMe Native Multipathing / ANA)가 즉각 발동될 수 있도록 유도합니다.
