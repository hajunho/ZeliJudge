# Problem 246: 엔터프라이즈 클라우드 스토리지: NVMe-over-Fabrics (NVMe-oF) 멀티패스 ANA 상태 플래핑, KATO 타임아웃 단절 및 I/O 정책 최적화

## 1. 개요 및 배경 시나리오

차세대 엔터프라이즈 올플래시(All-Flash) 스토리지 어레이 및 초고성능 클라우드 블록 스토리지(AWS EBS io2 Block Express, GCP Hyperdisk 등)는 전통적인 iSCSI/파이버 채널(FC) 프로토콜을 대체하여 **NVMe-over-Fabrics (NVMe-oF over RoCEv2/RDMA 또는 TCP)**를 채택하고 있습니다.

NVMe-oF 환경에서는 스토리지 이중화와 무중단 페일오버(Failover)를 위해 복수의 컨트롤러와 네트워크 경로를 묶는 **네이티브 NVMe 멀티패싱(`nvme_core.multipath=Y`)**과 **ANA (Asymmetric Namespace Access, 비대칭 네임스페이스 접근 - NVMe TP 4004)** 표준을 사용합니다.

```
                  NVMe-over-Fabrics ANA 비대칭 멀티패스 아키텍처
                  
   ┌─────────────────────────────────────────────────────────────┐
   │             Linux Host (nvme_core.multipath=Y)              │
   │               nvme_ns_head0 (가상 멀티패스 디바이스)             │
   └───────────────┬─────────────────────────────┬───────────────┘
                   │                             │
       Path 1 (Fabric A, RDMA)       Path 2 (Fabric B, RDMA)
       Base Latency: 150us           Base Latency: 750us
                   │                             │
                   ▼                             ▼
   ┌─────────────────────────────┐ ┌─────────────────────────────┐
   │ Controller 1 (Storage SP-A) │ │ Controller 2 (Storage SP-B) │
   │      [ANA OPTIMIZED]        │ │    [ANA NON-OPTIMIZED]      │
   │   Direct PCIe Local Path    │ │   Inter-Controller Link     │
   └───────────────┬─────────────┘ └─────────────┬───────────────┘
                   │                             │
                   │ (Direct)                    │ (NTB Mirror Proxy)
                   ▼                             ▼
           ┌─────────────────────────────────────────────┐
           │      Target NVMe SSD Media (Namespace 1)    │
           └─────────────────────────────────────────────┘
```

그러나 고성능 프로덕션 환경에서 잘못된 멀티패스 정책과 패브릭 불안정으로 인해 다음과 같은 세 가지 치명적인 스토리지 장애가 발생합니다:

1. **비대칭 경로에 대한 나이브 Round-Robin 정책 적용으로 인한 성능 반토막 (`NATIVE_NVME_MULTIPATH_ROUND_ROBIN_DEGRADATION`)**:
   - 스토리지 네임스페이스는 Controller 1(직접 연결된 로컬 컨트롤러, `OPTIMIZED`)을 통해 접근할 때 가장 낮은 지연시간(150us)을 제공함.
   - Controller 2는 백엔드 버스(NTB/PCIe 인터커넥트)를 거쳐 프록시 전달하므로 지연시간이 750us로 5배 높음(`NON_OPTIMIZED`).
   - 호스트의 멀티패스 I/O 정책이 단순 라운드로빈(`multipath_iopolicy = "round-robin"`)으로 설정된 경우, 최적 경로가 살아있음에도 불구하고 **I/O의 50%를 느린 Non-Optimized 경로로 전송**하여 전체 스토리지 처리량이 반토막 나고 지연시간이 4배 이상 급증함.

2. **컨트롤러 링크 불안정으로 인한 ANA 상태 플래핑 및 I/O 프리즈 (`ANA_PATH_FLAPPING_IO_FREEZE`)**:
   - 스토리지 컨트롤러 간 내부 하트비트 지연이나 스위치 포트 플래핑으로 인해 Controller 1의 상태가 `OPTIMIZED` $\leftrightarrow$ `INACCESSIBLE`로 수 초 내에 반복 전환됨.
   - 호스트 NVMe 드라이버는 AEN(Asynchronous Event Notification) 폭풍을 맞으며 I/O를 `nvme_ns_head` 재시도 큐에 반복적으로 되돌려 넣음(Requeue).
   - 이로 인해 호스트의 디스크 I/O가 $5\sim15$초간 완전히 멈추는 **I/O 프리즈(Freeze)**와 P99 지연시간 폭증(5초 이상)이 발생하여 데이터베이스와 애플리케이션이 일제히 정지함.

3. **패브릭 정체에 의한 KATO(Keep-Alive Timeout) 하트비트 단절 (`NVME_KATO_HEARTBEAT_DISCONNECT`)**:
   - NVMe-oF는 호스트와 타깃 간의 연결성을 감시하기 위해 Keep-Alive 타이머(`kato_sec`, 기본 5초)를 가동함.
   - RoCEv2 네트워크의 PFC(Priority Flow Control) Pause 프레임 폭풍이나 일시적 정체로 인해 5초 이상 응답이 지연되면, 호스트는 컨트롤러가 사망한 것으로 간주하고 **RDMA 큐 페어(QP)를 강제 파기(Disconnect)**하여 진행 중이던 I/O가 대량 어보트되는 재앙이 발생함.

본 과제에서는 NVMe-oF ANA 상태 머신, 리눅스 네이티브 멀티패스 I/O 정책, KATO 타임아웃 감시 및 페일오버를 정밀하게 시뮬레이션하고 시스템을 진단해야 합니다.

---

## 2. 상태 머신 및 동작 명세

시뮬레이터는 서브시스템 환경 설정(`subsystem_config`), 경로 구성(`paths`), 그리고 일련의 이벤트(`events`)를 순차적으로 처리합니다.

### 2.1 서브시스템 설정 (`subsystem_config`)
- `multipath_enabled`: 네이티브 NVMe 멀티패싱 활성화 여부 (기본 true).
- `multipath_iopolicy`: `"ana-optimized-only"` (최적 경로 우선) | `"round-robin"` (단순 교대).
- `kato_sec`: Keep-Alive Timeout 한도 (초).
- `retry_timeout_sec`: 모든 경로 상실 시 I/O 에러를 반환하기 전 재시도 대기 시간 (초).

### 2.2 ANA 경로 상태 및 I/O 분배 규칙
- **ANA 상태**:
  - `OPTIMIZED`: 로컬 최적 경로 (최저 지연시간).
  - `NON_OPTIMIZED`: 비대칭 우회 경로 (높은 지연시간).
  - `INACCESSIBLE`: 접근 불가.
- **I/O 라우팅 정책**:
  - `ana-optimized-only`:
    - `OPTIMIZED` 상태의 활성 경로가 1개라도 존재하면 모든 I/O를 해당 경로로만 라우팅.
    - 모든 `OPTIMIZED` 경로가 상실된 경우에만 `NON_OPTIMIZED` 경로로 안전 페일오버.
  - `round-robin`:
    - `OPTIMIZED`와 `NON_OPTIMIZED` 경로를 가리지 않고 모든 접근 가능한 경로에 순차적으로 번갈아 분배.
    - `OPTIMIZED` 경로가 존재함에도 `NON_OPTIMIZED` 경로로 I/O가 30% 초과 분배되면 성능 저하 감지.
- **지연시간 계산**:
  - $\text{latency\_us} = \text{ctrl.base\_latency\_us} + (\text{size\_kb} \times 2)$.

### 2.3 이벤트 처리 규칙 (`events`)
1. **`IO_REQUEST` (`io_id`, `size_kb`)**:
   - 플래핑 감지 상태인 경우: I/O는 큐에 블로킹되어 5,000,000us (5초) 지연 후 완료.
   - 접근 가능한 경로가 전혀 없는 경우: `failed_io_requests` 1 증가.
   - 정상 경로 선정 시: 해당 컨트롤러를 통해 처리 완료 및 지연시간 기록.
2. **`ANA_STATE_CHANGE` (`controller_id`, `new_ana_state`)**:
   - 컨트롤러의 ANA 상태 갱신.
   - 최근 5초(5,000ms) 내에 동일 컨트롤러의 상태 변경이 3회 이상 발생하면 **`flapping_detected = true`**로 전환.
3. **`FABRIC_CONGESTION_STALL` (`controller_id`, `duration_ms`)**:
   - 패브릭 지연이 $\text{kato\_sec} \times 1000$ ms 이상 지속되면 KATO 만료로 판단.
   - 세션을 `RECONNECTING` 상태로 전환하고 큐 파기 (`kato_disconnect_count` 증가).

---

### 2.4 감지해야 할 이상 징후 (`anomalies`) 및 권장안 (`recommendations`)

- `"NATIVE_NVME_MULTIPATH_ROUND_ROBIN_DEGRADATION"`:
  - `round-robin` 정책으로 인해 최적 경로가 존재함에도 Non-Optimized 경로로 I/O가 30% 초과 분배된 경우.
  - 권장안: `"SET_NVME_IOPOLICY_TO_ANA_OPTIMIZED_ONLY"`
- `"ANA_PATH_FLAPPING_IO_FREEZE"`:
  - ANA 상태 플래핑으로 인해 I/O가 프리즈되고 P99 지연시간이 2,000,000us (2초) 이상 급증한 경우.
  - 권장안: `"STABILIZE_INTER_CONTROLLER_HEARTBEAT_FABRIC"`
- `"NVME_KATO_HEARTBEAT_DISCONNECT"`:
  - 패브릭 지연으로 인해 KATO 타임아웃 및 세션 단절이 발생한 경우.
  - 권장안: `"TUNE_NVME_KATO_TIMEOUT_AND_PFC_PRIORITY"`
- `"ALL_PATHS_INACCESSIBLE_IO_ERROR"`:
  - 모든 경로 접근 불가로 인해 I/O 실패가 발생한 경우.
  - 권장안: `"VERIFY_PHYSICAL_FABRIC_REDUNDANCY"`

---

## 3. 입력 형식 (`sys.stdin`)

표준 입력으로 단일 JSON 객체가 주어집니다.

```json
{
  "subsystem_config": {
    "subsystem_nqn": "nqn.2014-08.org.nvmexpress:uuid:prod-storage-01",
    "multipath_enabled": true,
    "multipath_iopolicy": "round-robin",
    "kato_sec": 5,
    "retry_timeout_sec": 30
  },
  "paths": [
    {"controller_id": "ctrl-1", "transport": "rdma", "initial_ana_state": "OPTIMIZED", "base_latency_us": 150},
    {"controller_id": "ctrl-2", "transport": "rdma", "initial_ana_state": "NON_OPTIMIZED", "base_latency_us": 750}
  ],
  "events": [
    {"time_ms": 100, "type": "IO_REQUEST", "io_id": "io-1", "size_kb": 8}
  ]
}
```

---

## 4. 출력 형식 (`sys.stdout`)

표준 출력으로 JSON 객체를 단일 행으로 출력합니다 (`ensure_ascii=False`).

```json
{
  "subsystem_nqn": "nqn.2014-08.org.nvmexpress:uuid:prod-storage-01",
  "multipath_iopolicy": "round-robin",
  "total_io_requests": 1,
  "completed_io_requests": 1,
  "requeued_io_requests": 0,
  "failed_io_requests": 0,
  "avg_latency_us": 166.0,
  "p99_latency_us": 166.0,
  "ana_state_change_count": 0,
  "kato_disconnect_count": 0,
  "paths_status": {
    "ctrl-1": {
      "ana_state": "OPTIMIZED",
      "session_state": "CONNECTED",
      "io_handled": 1
    },
    "ctrl-2": {
      "ana_state": "NON_OPTIMIZED",
      "session_state": "CONNECTED",
      "io_handled": 0
    }
  },
  "anomalies": [],
  "recommendations": [],
  "diagnosis": "ANA Optimized 경로를 통해 초저지연 I/O가 안정적으로 처리되었으며 패브릭 연결이 정상 유지되었습니다."
}
```
