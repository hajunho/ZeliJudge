# 문제 238: 리눅스 커널 eBPF 고성능 이벤트 파이프라인: Perf Buffer(BPF_MAP_TYPE_PERF_EVENT_ARRAY) 코어 불균형 누락 vs Lockless Ring Buffer(BPF_MAP_TYPE_RINGBUF)

## 1. 개요 및 배경 (Incident Scenario)

초대형 128코어 베어메탈 서버에서 전사 보안 감사(Security Audit) 및 네트워크 패킷 추적을 위해 eBPF 기반의 모니터링 에이전트(Tetragon, Falco, Datadog Agent)를 배포한 직후, 시스템 관리자는 두 가지 치명적인 결함에 직면했습니다:

1. **기가바이트 단위의 커널 메모리 낭비 (Kernel Memory Bloat)**:
   - Linux 5.8 이전의 전통적인 eBPF 이벤트 전송 맵인 **`BPF_MAP_TYPE_PERF_EVENT_ARRAY` (Perf Buffer)**는 **CPU 코어마다 독립된 링 버퍼를 강제 할당**합니다.
   - 버스트 트래픽을 감당하기 위해 코어당 8MB 버퍼를 설정하자, 128코어 서버에서 단일 eBPF 프로그램이 무려 **$128 \times 8\text{MB} = 1,024\text{MB}$ (1.0GB)**의 스왑 불가능한(Locked/Pinned) 커널 메모리를 집어삼켰습니다(`PERF_BUFFER_MASSIVE_MEMORY_BLOAT`).
2. **코어 편중(Core Skew)으로 인한 보안 이벤트 대량 누락**:
   - 네트워크 카드(NIC)의 RSS(Receive Side Scaling) 또는 단일 인터럽트 큐 집중으로 인해 전체 네트워크 이벤트의 80%가 Core 0으로 쏠렸습니다.
   - Core 0의 8MB 버퍼는 순식간에 오버플로우되어 수천 건의 핵심 TCP 연결 로그가 소실(`PERF_BUFFER_CORE_SKEW_EVENT_DROPS`)되었습니다. 반면 나머지 127개 코어의 1,016MB 버퍼는 사용률 0%로 텅 빈 채 방치되는 극단적인 비효율이 발생했습니다.
3. **이벤트 역전 현상 (Out-of-Order Delivery)**:
   - 유저스페이스 데몬이 128개 코어의 독립된 버퍼에서 폴링(epoll)하여 데이터를 읽어 들이다 보니, 물리적 시간순으로 먼저 발생한 이벤트가 나중에 도착하여 시간 역전 현상이 발생하고 타임스탬프 정렬에 막대한 CPU 연산이 낭비되었습니다.

```
[Legacy Perf Buffer vs Modern eBPF Ring Buffer Architecture]

1. Legacy Perf Buffer (BPF_MAP_TYPE_PERF_EVENT_ARRAY):
   [Core 0 (80% Traffic)] ---> [ Core 0 Buffer 8MB: OVERFLOW & DROPS! ]
   [Core 1 (2% Traffic) ] ---> [ Core 1 Buffer 8MB: 98% Empty         ]
   ...
   [Core 127 (0% Traffic)] ---> [ Core 127 Buffer 8MB: 100% Empty       ]
   * Total Memory: 128 * 8MB = 1024MB | Core 0 drops events!

2. Modern BPF Ring Buffer (BPF_MAP_TYPE_RINGBUF, Linux 5.8+):
   [Core 0 (80% Traffic)] ───┐
   [Core 1 (2% Traffic) ] ───┼──> [ Single Shared MPSC Lockless Ring Buffer: 16MB ]
   ...                       │    (All cores write into one shared pool. 0 Drops!)
   [Core 127 (0% Traffic)] ──┘    * Total Memory: 16MB (98.4% reduction!)
                                  * Strict Total Chronological Ordering!
```

이 고질적인 문제를 근원적으로 해결하기 위해 Linux 5.8 커널에 Andrii Nakryiko가 설계한 **`BPF_MAP_TYPE_RINGBUF` (BPF Ring Buffer)**가 도입되었습니다. BPF Ring Buffer는 모든 CPU 코어가 단 하나의 잠금 없는(Lockless) 공유 MPSC(Multi-Producer, Single-Consumer) 링 버퍼를 공유함으로써 메모리를 98% 절감하고 코어 편중 드롭을 0건으로 박멸합니다.

본 문제에서는 커널 버전, 버퍼 아키텍처, 코어 수, 트래픽 편중도에 따른 메모리 점유율, 이벤트 누락 수, 글로벌 순서 보장 여부를 분석하고 최적 이벤트 파이프라인을 판정하는 엔진을 구현합니다.

---

## 2. 입력 형식 (Input Specification)

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "buffer_type": "RINGBUF",
    "num_cpu_cores": 128,
    "buffer_size_per_cpu_mb": 8.0,
    "shared_ringbuf_size_mb": 16.0,
    "consumer_drain_rate_mbps": 500.0,
    "kernel_version": "5.15"
  },
  "workload": {
    "total_events": 500000,
    "event_size_bytes": 128,
    "core_distribution": "SKEWED_CORE_ZERO",
    "duration_sec": 1.0,
    "uncommitted_reserve_leak": false
  }
}
```

### 필드 설명
- `config`:
  - `buffer_type` (str): eBPF 버퍼 아키텍처 (`"RINGBUF"`, `"PERF_BUFFER"`)
  - `num_cpu_cores` (int): 호스트 시스템의 논리 CPU 코어 수 (예: 64, 128)
  - `buffer_size_per_cpu_mb` (float): Perf Buffer 사용 시 코어당 버퍼 크기 (MB)
  - `shared_ringbuf_size_mb` (float): Ring Buffer 사용 시 전역 공유 버퍼 크기 (MB)
  - `consumer_drain_rate_mbps` (float): 유저스페이스 컨슈머의 초당 데이터 처리 소비율 (MB/s)
  - `kernel_version` (str): 호스트 리눅스 커널 버전 (예: `"5.4"`, `"5.15"`)
- `workload`:
  - `total_events` (int): 벤치마크 기간 동안 발생한 총 커널 eBPF 이벤트 수
  - `event_size_bytes` (int): 이벤트 구조체당 평균 크기 (바이트)
  - `core_distribution` (str): 이벤트 발생 코어 분포 (`"SKEWED_CORE_ZERO"`, `"UNIFORM"`)
    - `"SKEWED_CORE_ZERO"`: 전체 트래픽의 80%가 Core 0에 집중
    - `"UNIFORM"`: 모든 코어에 균등 분산
  - `duration_sec` (float): 부하 발생 지속 시간 (초)
  - `uncommitted_reserve_leak` (bool): `bpf_ringbuf_reserve` 후 `submit/discard` 누락 여부

---

## 3. 출력 형식 (Output Specification)

표준 출력(stdout)으로 다음 JSON 구조를 반환해야 합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_EBPF_RINGBUF_STREAMING",
  "metrics": {
    "total_memory_allocated_mb": 16.0,
    "dropped_events_count": 0,
    "memory_reduction_pct": 98.4,
    "strict_ordering_guaranteed": true,
    "core_skew_drop_detected": false
  }
}
```

### 판정(Verdict) 및 상태(Status) 규칙
1. **커널 미지원 (`buffer_type == "RINGBUF"` 및 커널 버전 < 5.8)**:
   - `status`: `"FAILED"`, `verdict`: `"RINGBUF_UNSUPPORTED_KERNEL_VERSION"`
2. **`buffer_type == "PERF_BUFFER"`**:
   - `core_distribution == "SKEWED_CORE_ZERO"`이고 Core 0 축적량이 `buffer_size_per_cpu_mb`를 초과할 때:
     - `status`: `"FAILED"`, `verdict`: `"PERF_BUFFER_CORE_SKEW_EVENT_DROPS"`, `dropped_events_count > 0`
   - 균등 분산이나 총 메모리가 512MB 이상인 경우:
     - `status`: `"WARNING"`, `verdict`: `"PERF_BUFFER_MASSIVE_MEMORY_BLOAT"`
   - 저사양 시스템 정상 동작:
     - `status`: `"SUCCESS"`, `verdict`: `"PERF_BUFFER_BALANCED_BASELINE"`
3. **`buffer_type == "RINGBUF"`**:
   - `uncommitted_reserve_leak == true`:
     - 링 버퍼 헤더 포인터 진행 불가 교착상태 (`status`: `"FAILED"`, `verdict`: `"RINGBUF_RESERVATION_LEAK_DEADLOCK"`)
   - 총 데이터 축적량이 `shared_ringbuf_size_mb`를 초과할 때:
     - `status`: `"FAILED"`, `verdict`: `"RINGBUF_SHARED_BUFFER_OVERFLOW"`
   - 정상 수용 시:
     - 코어 편중과 무관하게 0건 드롭, 100% 글로벌 시간 순서 보장, 메모리 90%+ 절감
     - `status`: `"SUCCESS"`, `verdict`: `"OPTIMAL_EBPF_RINGBUF_STREAMING"`

---

## 4. 예제 입출력

### 예제 1 (입력)
```json
{
  "config": {
    "buffer_type": "RINGBUF",
    "num_cpu_cores": 128,
    "buffer_size_per_cpu_mb": 8.0,
    "shared_ringbuf_size_mb": 16.0,
    "consumer_drain_rate_mbps": 500.0,
    "kernel_version": "5.15"
  },
  "workload": {
    "total_events": 500000,
    "event_size_bytes": 128,
    "core_distribution": "SKEWED_CORE_ZERO",
    "duration_sec": 1.0,
    "uncommitted_reserve_leak": false
  }
}
```

### 예제 1 (출력)
```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_EBPF_RINGBUF_STREAMING",
  "metrics": {
    "total_memory_allocated_mb": 16.0,
    "dropped_events_count": 0,
    "memory_reduction_pct": 98.4,
    "strict_ordering_guaranteed": true,
    "core_skew_drop_detected": false
  }
}
```
