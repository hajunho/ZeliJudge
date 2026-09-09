# Problem 180: Linux io_uring 비동기 I/O 링 버퍼(SQE/CQE), 시스템 콜 제로-카피와 Polled I/O 커널 스레드

## 문제 설명

초당 수백만 건의 금융 트랜잭션과 시계열 데이터를 처리하는 글로벌 초고빈도 매매(HFT) 인프라 팀은 차세대 NVMe SSD 스토리지 클러스터 도입 후 기이한 성능 한계에 직면했습니다.
하드웨어 사양상 최대 200만 IOPS를 뿜어낼 수 있는 초고속 SSD를 장착했음에도 불구하고, 전통적인 **`epoll` 기반 비동기 I/O와 동기식 `preadv` 시스템 콜** 방식을 사용하던 데이터베이스 엔진은 초당 50만 IOPS 부근에서 **CPU 사용률이 100%에 달하며 컨텍스트 스위칭 및 Syscall Trap 오버헤드로 인해 심각한 병목(Syscall Bottleneck)**을 겪었습니다.

인프라 엔지니어링 팀은 리눅스 커널 5.1+에 도입된 혁신적인 비동기 I/O 프레임워크인 **`io_uring`**을 도입하여, 유저 공간과 커널 공간이 공유하는 **SQ(Submission Queue) / CQ(Completion Queue) 원형 링 버퍼**, **배치 제출(Batched io_uring_enter)**, 그리고 **커널 폴링 스레드(SQPOLL)**를 통한 **완전한 제로-시스템콜(Zero-Syscall) 라인 레이트 I/O 엔진**을 구축하기로 결정했습니다.

당신은 전통 `epoll` 모드, `io_uring` 배치 모드, 그리고 커널 폴링 스레드(`SQPOLL`) 모드를 정밀하게 시뮬레이션하고 완료 큐(CQ) 역압 및 메모리 절감 지표를 산출하는 엔진을 구현해야 합니다.

---

## 핵심 처리 규칙

### 1. 3대 I/O 처리 모드

#### 모드 1: `EPOLL_TRADITIONAL` (전통 동기식 I/O)
- 요청된 각 I/O마다 정확히 1회의 시스템 콜(`preadv`)이 발생합니다 (`total_syscalls_issued += 1`).
- I/O당 CPU 지연시간으로 `syscall_overhead_us` ($1.5\,\mu\text{s}$)가 그대로 누적되며, 하드웨어 I/O 시간(`io_latency_us`)과 합산됩니다.

#### 모드 2: `IOURING_BATCHED` (배치 io_uring)
- 배치 내 모든 SQE는 유저 메모리에 기록된 후, 배치당 단 1회의 **`io_uring_enter()`** 시스템 콜로 일괄 제출됩니다 (`total_syscalls_issued += 1`).
- 배치 1회 제출에 따른 시스템 콜 오버헤드(`syscall_overhead_us`)는 배치 내 요청들에게 균등하게 분할 분배됩니다.
- 고정 버퍼 등록(`use_registered_buffers == True`) 시 요청당 메모리 고정 비용이 $0.05\,\mu\text{s}$로 대폭 절감되며, 미등록 시 $0.25\,\mu\text{s}$가 소요됩니다.

#### 모드 3: `IOURING_SQPOLL` (커널 폴링 스레드 모드)
- 커널의 전용 폴링 스레드가 SQ 링을 직접 감시하므로 **시스템 콜이 전혀 발생하지 않습니다 (`total_syscalls_issued += 0`)**.
- CPU 비용은 유저 공간 메모리 쓰기 비용(등록 버퍼 시 $0.03\,\mu\text{s}$, 미등록 시 $0.15\,\mu\text{s}$)만 극소량 소모됩니다.

### 2. 완료 큐(CQ) 드레인 및 오버플로우 제어 (CQ Backpressure)
- 각 배치는 유저스페이스가 직전 완료된 CQE를 수확하는 `drain_cqe_count` 값을 가질 수 있습니다:
  - `drain_cqe_count > 0`이면 `cq_head`를 최대 가용량만큼 전진시켜 CQ 링 버퍼 공간을 확보합니다.
- 새로운 I/O 완료 시 현재 대기 중인 완료 수(`pending_cq = cq_tail - cq_head`)가 링 버퍼 용량(`queue_depth`) 이상이면:
  - **CQ 오버플로우가 발생**하여 완료 엔트리가 폐기되고 `cq_overflow_count`가 1 증가합니다 (`status: "CQ_OVERFLOW_DROPPED"`).
  - 정상적인 경우 `cq_tail`이 1 증가하고 `total_ios_completed`가 1 증가합니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "mode": "IOURING_SQPOLL",
    "queue_depth": 128,
    "io_latency_us": 10.0,
    "syscall_overhead_us": 1.5,
    "use_registered_buffers": false
  },
  "batches": [
    {
      "drain_cqe_count": 0,
      "requests": [
        {
          "io_id": "req_001",
          "opcode": "READ",
          "bytes": 4096
        }
      ]
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 JSON 객체를 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "mode": "IOURING_SQPOLL",
  "metrics": {
    "total_ios_requested": 64,
    "total_ios_completed": 64,
    "total_syscalls_issued": 0,
    "cq_overflow_count": 0,
    "total_cpu_time_us": 9.6,
    "total_io_time_us": 640.0,
    "average_latency_per_io_us": 10.15,
    "cq_utilization_peak": 16,
    "verdict": "ZERO_SYSCALL_SQPOLL_LINE_RATE"
  },
  "sample_completions": [
    {
      "io_id": "req_001",
      "opcode": "READ",
      "status": "COMPLETED",
      "syscalls": 0,
      "latency_us": 10.15
    }
  ]
}
```

### 최종 판정 (Verdict) 규칙
1. `CQ_RING_BUFFER_OVERFLOW_BACKPRESSURE`: `cq_overflow_count > 0`인 경우 (완료 큐 드레인 누락으로 역압 발생).
2. `SYSCALL_OVERHEAD_BOTTLENECK`: `mode == "EPOLL_TRADITIONAL"`이고 I/O 수와 시스템 콜 수가 $1:1$로 일치하는 경우.
3. `BATCHED_IO_URING_ACCELERATION`: `mode == "IOURING_BATCHED"`이고 시스템 콜 수가 I/O 수보다 현저히 적은 경우.
4. `ZERO_SYSCALL_SQPOLL_LINE_RATE`: `mode == "IOURING_SQPOLL"`이고 `total_syscalls_issued == 0`인 경우.
5. `DEGRADED_IO_PERFORMANCE`: 그 외의 경우.
