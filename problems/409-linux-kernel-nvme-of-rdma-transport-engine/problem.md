# 문제 409: Linux 커널 NVMe-oF(RDMA) 전송 엔진 및 CQ 폴링·메모리 등록(FRWR) 상태 머신

## 문제 설명

인공지능(AI) 파운데이션 모델 학습, 초거대 딥러닝 분산 체크포인팅, 대규모 GPU 클러스터 및 실시간 분산 데이터베이스 환경에서는 마이크로초(µs) 단위의 초저지연과 수천만 IOPS의 극한 처리량을 보장하는 초고속 네트워크 스토리지 아키텍처가 필수적입니다.

전통적인 TCP/IP 기반 네트워크 스토리지(iSCSI, NVMe-oF TCP)는 OS 커널 네트워크 스택의 소켓 버퍼링, 패킷 분할 및 재조립, 소프트웨어 체크섬 연산, 그리고 유저-커널-소켓 간의 빈번한 메모리 복사 및 컨텍스트 스위칭 오버헤드로 인해 스토리지 플래시 NVMe SSD 자체의 마이크로초 대역 성능을 완전히 소모시키지 못하는 병목(CPU Bottleneck)에 직면합니다.

이를 극복하기 위해 리눅스 커널에 도입된 **NVMe over Fabrics RDMA 전송 드라이버 (`drivers/nvme/host/rdma.c`, `drivers/nvme/target/rdma.c`, `CONFIG_NVME_RDMA`)**는 RoCEv2(RDMA over Converged Ethernet) 및 InfiniBand 패브릭을 활용하여 CPU 개입 없이 원격 호스트와 타깃 간 메모리를 직접 읽고 쓰는(Kernel Zero-Copy Direct Memory Access) 첨단 전송 계층을 제공합니다.

### NVMe-oF RDMA 전송의 핵심 메커니즘

1. **큐 쌍(Queue Pair, QP) 및 완료 큐(Completion Queue, CQ)**:
   - 각 NVMe I/O 서브미션/컴플리션 큐는 1:1로 RDMA RC(Reliable Connected) QP(`struct ib_qp`)에 매핑됩니다.
   - 호스트의 작업 요청은 Send Queue(SQ)에 등록되며, 완료 통지는 CQ(`struct ib_cq`)를 통해 전달됩니다.
   - 전송 엔진은 인터럽트 모드 또는 초저지연 바운디드 비동기 폴링 모드(`nvme_rdma_poll()`, `ib_poll_cq()`)로 동작하며, 한 번의 폴링 루프에서 최대 `cq_poll_budget`개의 완료 엔트리(CQE)를 일괄 수확(Batch Reaping)합니다.

2. **인-캡슐(In-Capsule) 데이터 패스트패스 vs RDMA SGL**:
   - **소용량 I/O ($size \le in\_capsule\_data\_size$)**:
     - 명령 캡슐 내부의 여유 공간(보통 4KB 또는 8KB)에 데이터 페이로드를 직접 포함시켜 단일 `IB_WR_SEND` 작업으로 원샷 전송합니다.
     - 추가적인 메모리 등록(MR)이나 RDMA Read/Write 핸드셰이크가 전혀 발생하지 않아 최저 지연 시간(Zero-MR Fastpath)을 달성합니다.
   - **대용량 I/O ($size > in\_capsule\_data\_size$)**:
     - 호스트는 고속 메모리 등록(FRWR, Fast Registration Work Request, `IB_WR_REG_MR`)을 구동하여 메모리 영역(MR)을 할당받고 고유한 암호화 키인 원격 키(`rkey`)를 획득합니다.
     - 명령 캡슐 내부에 Keyed SGL Data Block Descriptor(`(addr, length, rkey)`)를 담아 보냅니다.
     - 타깃 HCA(Host Channel Adapter)는 이 R_Key를 이용하여 호스트 메모리로부터 데이터를 직접 RDMA Read(쓰기 명령 시)하거나, 호스트 메모리로 직접 RDMA Write(읽기 명령 시)를 수행합니다.
     - I/O 완료 시 호스트는 로컬 무효화(`IB_WR_LOCAL_INV`)를 통해 해당 MR을 안전하게 회수하여 풀로 반환합니다.

3. **타깃 크레딧(Credit) 기반 플로우 제어 (Flow Control)**:
   - 원격 타깃의 수신 큐(Receive Queue) 오버플로우를 방지하기 위해, 호스트는 `active_credits = sq_tail - sq_head`를 추적합니다.
   - 만약 활성 크레딧이 `queue_depth`에 도달하면 신규 명령 발주를 즉각 중단하고 `pending_queue`에 대기(Backpressure)시킵니다.
   - 타깃이 응답 CQE를 보낼 때 포함된 `sqhd` (Submission Queue Head Doorbell) 값을 수신하면 `sq_head`가 전진하며 크레딧이 반환되어 대기 중인 명령이 발주됩니다.

4. **MR 풀 고갈(MR Starvation) 제어**:
   - 시스템의 동시 RDMA SGL 전송을 위해 사전 할당된 MR 풀(`mr_pool_size`)이 모두 소진되면, 신규 대용량 요청은 `mr_wait_queue`에서 대기합니다.
   - CQ 폴링을 통해 기존 요청이 완료되어 MR이 로컬 무효화(`IB_WR_LOCAL_INV`) 반환되는 즉시 대기자에게 우선 할당됩니다.
   - 단, 소용량 인-캡슐 I/O는 MR을 전혀 소모하지 않으므로 MR 풀이 고갈된 상태에서도 크레딧만 충분하다면 대기열을 우회하여 즉시 발주됩니다!

5. **패브릭 링크 장애(QP Fatal Error) 및 원자적 플러시/복구**:
   - 케이블 단선, RoCE 포트 다운, 패브릭 타임아웃 등으로 인해 QP가 오류 상태(`IB_QPS_ERR`)로 전이되면, 현재 인플라이트(In-flight) 중인 모든 명령과 `pending_queue`, `mr_wait_queue`의 대기 명령들은 즉시 `NVME_SC_TRANSPORT_ERROR` 상태로 강제 완료(Flush) 처리됩니다.
   - 점유 중이던 모든 MR은 즉시 정상 상태로 무효화 반환됩니다.
   - QP 재연결(`RECONNECT_QP`) 이벤트가 수신되면 전송 상태 머신과 크레딧 카운터가 초기화되어 정상 트래픽 처리가 재개됩니다.

여러분은 리눅스 커널의 NVMe-oF RDMA 호스트 전송 계층의 크레딧 플로우 제어, 인-캡슐/RDMA SGL 분기, FRWR MR 생명주기 관리, CQ 일괄 폴링, 장애 플러시 엔진을 충실히 모델링하는 시뮬레이터를 구현해야 합니다.

---

## 시스템 아키텍처 다이어그램

```
+==================================================================================================+
|                       Linux Kernel NVMe-oF RDMA Transport Architecture                           |
+==================================================================================================+

   [ NVMe Block Layer / Upper Storage Driver ]
                    |
                    | submit_cmd(req_id, opcode, lba, size_bytes)
                    v
+--------------------------------------------------------------------------------------------------+
| NVMe RDMA Host Transport Driver (drivers/nvme/host/rdma.c)                                       |
|                                                                                                  |
|  [ Flow Control / Credit Manager ]                                                               |
|    active_credits = sq_tail - sq_head                                                            |
|    - If active_credits >= queue_depth  ---> Enqueue into [ pending_queue ] (Backpressure)        |
|    - Else                              ---> Proceed to Data Routing                              |
|                                                                                                  |
|  [ In-Capsule vs RDMA SGL Routing ]                                                              |
|    - size <= in_capsule_data_size:                                                               |
|        * Mode: IN_CAPSULE (Single IB_WR_SEND, Zero MR Overhead!)                                  |
|    - size > in_capsule_data_size:                                                                |
|        * Mode: RDMA_SGL (Requires Memory Region from mr_pool)                                    |
|        * If mr_pool EMPTY              ---> Enqueue into [ mr_wait_queue ] (MR Starvation)       |
|        * If MR Available               ---> Fast Registration (IB_WR_REG_MR) & Keyed SGL         |
|                                                                                                  |
|  [ RDMA Queue Pair (QP) & Completion Queue (CQ) ]                                                |
|    - Host Send Queue (SQ)  ---> Fabric (RoCEv2 / InfiniBand) ---> Target Receive Queue (RQ)      |
|    - Host Recv / CQ        <--- Target NVMe CQE (sqhd update) <--- Target NVMe Controller        |
|                                                                                                  |
|  [ CQ Polling Engine (nvme_rdma_poll / ib_poll_cq) ]                                              |
|    - Poll up to cq_poll_budget completions                                                       |
|    - For each completed CQE:                                                                     |
|        * Free & Invalidate MR (IB_WR_LOCAL_INV) ---> Wake up mr_wait_queue head                  |
|        * Advance sq_head based on Target sqhd  ---> Release credits & Wake up pending_queue      |
|                                                                                                  |
|  [ Error Handling & Recovery ]                                                                   |
|    - QP Fatal Error (IB_QPS_ERR): Flush in-flight + pending + mr_wait with TRANSPORT_ERROR       |
|    - Reconnect QP: Reset sq_head/sq_tail, reinitialize MR pool, resume normal RTS state          |
+==================================================================================================+
```

---

## 상세 요구사항 및 동작 규칙

### 1. 시스템 설정 파라미터 (`config`)
- `queue_depth`: QP의 최대 동시 인플라이트 허용 명령 수 (기본값: `16`)
- `in_capsule_data_size`: 인-캡슐 데이터 패스트패스 최대 바이트 크기 (기본값: `4096`)
- `mr_pool_size`: 사전 할당된 고속 등록 메모리 영역(MR) 풀 크기 (기본값: `8`)
- `cq_poll_budget`: 한 번의 `POLL_CQ` 시 최대로 수확할 수 있는 완료 엔트리 수 (기본값: `4`)
- `fabric_rtt_ms`: 패브릭 기본 왕복 지연 시간 (기본값: `2`)
- `target_proc_time_ms`: 원격 NVMe 컨트롤러 내부 I/O 처리 시간 (기본값: `5`)
- `transfer_rate_kb_per_ms`: 대용량 RDMA 데이터 전송 대역폭 레이트 (기본값: `64` KB/ms)

### 2. 이벤트 트레이스 연산 (`trace`)

1. **`SUBMIT_CMD`**:
   - 명령 제출: `time`, `req_id`, `opcode` (`NVME_CMD_READ` 또는 `NVME_CMD_WRITE`), `lba`, `size_bytes`.
   - QP 상태가 `IB_QPS_RTS`가 아닌 경우 즉시 `SUBMIT_REJECTED_QP_ERR` 이벤트 로깅 후 무시됩니다.
   - **크레딧 검사**:
     - `active_credits = sq_tail - sq_head`
     - `active_credits >= queue_depth`인 경우: `pending_queue`에 추가하고 `credit_starvations` 1 증가.
   - **데이터 라우팅 분기**:
     - `size_bytes <= in_capsule_data_size`:
       - `mode = "IN_CAPSULE"`, `mr_id = None`, `rkey = None`.
       - `sq_tail` 1 증가, `in_capsule_count` 1 증가.
       - 완료 예상 시각 = `time + fabric_rtt_ms + target_proc_time_ms`.
     - `size_bytes > in_capsule_data_size`:
       - 사용 가능한 MR이 없는 경우: `mr_wait_queue`에 추가하고 `mr_starvations` 1 증가.
       - MR이 있는 경우: MR 풀의 맨 앞(`popleft`) MR을 획득하여 할당(`is_busy=True`, `assigned_req=req_id`).
       - `mode = "RDMA_SGL"`, `mr_id = mr.mr_id`, `rkey = mr.rkey`.
       - `sq_tail` 1 증가, `rdma_sgl_count` 1 증가.
       - 전송 지연 시간 계산: `transfer_delay = ceil(size_bytes / (transfer_rate_kb_per_ms * 1024))` ms.
       - 완료 예상 시각 = `time + fabric_rtt_ms + target_proc_time_ms + transfer_delay`.

2. **`POLL_CQ`**:
   - 완료 큐 폴링: `time`, `budget` (지정되지 않은 경우 `cq_poll_budget` 사용).
   - `time` 시점에 완료 시각이 도래한 작업 중 최대 `budget`개만큼 도착 순서대로 수확합니다.
   - 각 완료 요청에 대해:
     - `sq_head`를 1 증가시키고, 타깃 헤드 도어벨 `sqhd`를 `sq_head`로 갱신.
     - MR을 사용한 요청(`RDMA_SGL`)이었다면, 해당 MR을 해제(`is_busy=False`, `assigned_req=None`)하고 `free_mrs`의 맨 뒤에 반환.
     - 지연 시간(`latency_ms = time - submit_time`)을 계산하여 `completed_requests`에 기록.
   - **대기열 처리 우선순위**:
     - 먼저 MR 해제로 인해 여유가 생겼고 크레딧 여유가 있다면, `mr_wait_queue`의 대기 요청을 꺼내어 발주.
     - 크레딧 여유가 있다면, `pending_queue`의 대기 요청을 꺼내어 발주.

3. **`TRIGGER_QP_ERROR`**:
   - 링크 장애 발생: `time`, `reason` (예: `FABRIC_DISCONNECT`, `IB_EVENT_QP_FATAL`).
   - QP 상태를 `IB_QPS_ERR`로 변경.
   - 현재 인플라이트 중인 모든 요청, `pending_queue`의 모든 요청, `mr_wait_queue`의 모든 요청을 즉시 강제 종료(`status = "NVME_SC_TRANSPORT_ERROR"`).
   - 점유 중이던 모든 MR은 즉시 해제하여 반환.
   - `sq_head = sq_tail`로 동기화하여 활성 크레딧을 0으로 초기화.

4. **`RECONNECT_QP`**:
   - 패브릭 재연결: `time`.
   - QP 상태를 `IB_QPS_RTS`로 복구.
   - `sq_head = 0`, `sq_tail = 0`, `sqhd = 0`으로 리셋.
   - MR 풀을 초기 미사용 상태로 재초기화.

---

## 입출력 형식 (JSON)

### 입력 형식 (Standard Input)

```json
{
  "config": {
    "queue_depth": 16,
    "in_capsule_data_size": 4096,
    "mr_pool_size": 8,
    "cq_poll_budget": 4,
    "fabric_rtt_ms": 2,
    "target_proc_time_ms": 5,
    "transfer_rate_kb_per_ms": 64
  },
  "trace": [
    {
      "time": 0,
      "type": "SUBMIT_CMD",
      "req_id": "r1",
      "opcode": "NVME_CMD_WRITE",
      "lba": 0,
      "size_bytes": 2048
    },
    {
      "time": 1,
      "type": "SUBMIT_CMD",
      "req_id": "r2",
      "opcode": "NVME_CMD_READ",
      "lba": 100,
      "size_bytes": 65536
    },
    {
      "time": 10,
      "type": "POLL_CQ",
      "budget": 4
    }
  ]
}
```

### 출력 형식 (Standard Output)

공백 없이 압축된 단일 라인 JSON 문자열(`separators=(',', ':')`, `ensure_ascii=False`)로 출력해야 합니다:

```json
{
  "summary": {
    "total_submitted": 2,
    "completed_count": 2,
    "in_capsule_count": 1,
    "rdma_sgl_count": 1,
    "credit_starvations": 0,
    "mr_starvations": 0,
    "active_credits": 0,
    "free_mr_count": 8,
    "qp_state": "IB_QPS_RTS"
  },
  "completed_requests": [
    {
      "req_id": "r1",
      "opcode": "NVME_CMD_WRITE",
      "size_bytes": 2048,
      "mode": "IN_CAPSULE",
      "completion_time": 10,
      "latency_ms": 10,
      "status": "SUCCESS"
    },
    {
      "req_id": "r2",
      "opcode": "NVME_CMD_READ",
      "size_bytes": 65536,
      "mode": "RDMA_SGL",
      "completion_time": 10,
      "latency_ms": 9,
      "status": "SUCCESS"
    }
  ],
  "mr_pool_status": [
    {
      "mr_id": 0,
      "rkey": "0x1000",
      "is_busy": false,
      "assigned_req": null
    }
  ],
  "event_logs": [ ... ]
}
```
