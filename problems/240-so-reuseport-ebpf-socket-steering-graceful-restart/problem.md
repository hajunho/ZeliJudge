# Problem 240: 리눅스 커널 네트워크: `SO_REUSEPORT` 4-튜플 해시 불균형, 무중단 재로드 SYN 드롭 함정 및 eBPF 소켓 스티어링 (`BPF_MAP_TYPE_REUSEPORT_SOCKARRAY`)

## 1. 개요 및 배경 시나리오

초당 수십만 QPS(Queries Per Second) 이상의 인바운드 TCP 트래픽을 처리하는 초대규모 엣지 리버스 프록시 및 API 게이트웨이(Envoy, NGINX, HAProxy 클러스터) 환경에서는 네트워크 I/O 병목을 제거하기 위한 커널 레벨 튜닝이 필수적입니다.

전통적인 멀티 프로세스/스레드 웹 서버는 단일 리슨 소켓(Listen Socket)을 여러 워커가 공유하고, 각 워커가 `epoll_wait()`을 호출하는 **단일 리슨 소켓 모델**을 사용했습니다. 그러나 이 구조는 모든 워커가 동일한 소켓 파일 디스크립터의 락(`sk->sk_lock`)을 두고 경합하며, 새로운 연결이 도착할 때 모든 대기 워커가 깨어나는 **Thundering Herd** 현상과 극심한 컨텍스트 스위칭 오버헤드를 유발했습니다.

이를 해결하기 위해 리눅스 커널 3.9에 **`SO_REUSEPORT`** 소켓 옵션이 도입되었습니다. 동일한 포트에 복수의 독립적인 리슨 소켓을 바인딩할 수 있게 함으로써, 각 워커 스레드가 고유한 리슨 소켓과 백로그 큐(`sk_receive_queue`)를 소유하고 락 경합 없이 독립적으로 `accept()`할 수 있게 되었습니다.

```
[전통적인 SO_REUSEPORT의 4-튜플 해싱 한계]
Client SYNs ──► NIC RSS (Core 0) ──► inet_lookup_listener() 
                                           │ (4-tuple Hash: src_ip, src_port)
                      ┌────────────────────┼────────────────────┐
                      ▼                    ▼                    ▼
             Worker 0 (Core 0)    Worker 1 (Core 1)    Worker 2 (Core 2)
             [Backlog Queue]      [Backlog Queue]      [Backlog Queue]
             (NAT 트래픽 몰림)       (유휴 상태)           (유휴 상태)
             ██████████ FULL!     ░░░░░░░░░░           ░░░░░░░░░░
             ▼
             ListenOverflow Drop! (SYN 재전송 & 1~3초 지연 타임아웃)
```

그러나 수백 대의 대규모 프로덕션 노드에 `SO_REUSEPORT`를 적용한 직후, 인프라 엔지니어링 팀은 다음과 같은 세 가지 심각한 프로덕션 장애와 마주하게 되었습니다:

1. **NAT/프록시 환경에서의 4-튜플 해시 편중 및 큐 오버플로우 (`REUSEPORT_HASH_SKEW_QUEUE_OVERFLOW`)**:
   - 커널 기본 `SO_REUSEPORT`는 인입되는 SYN 패킷의 4-튜플(`src_ip`, `src_port`, `dst_ip`, `dst_port`) 해시값을 기반으로 목적지 소켓을 모듈로($\text{hash} \pmod N$) 분배합니다.
   - 대규모 엔터프라이즈 게이트웨이나 클라우드 NAT 풀을 통해 들어오는 트래픽은 출발지 IP가 소수로 제한되어 특정 워커 소켓으로 트래픽이 집중됩니다.
   - 그 결과 특정 워커의 백로그 큐(`backlog_queue`)가 가득 차 신규 SYN 패킷이 사일런트 드롭(`ListenOverflows`)되는 동안, 다른 워커 소켓의 큐는 거의 비어 있는 극심한 자원 불균형이 발생합니다.

2. **무중단 롤링 재로드(Graceful Reload) 중 연결 리셋(RST) 함정 (`REUSEPORT_RELOAD_RST_UNACCEPTED_DROP` & `OLD_WORKER_DRAIN_STARVATION`)**:
   - 서비스 배포를 위해 이전 버전 워커를 종료하고 신규 워커를 기동하는 무중단 재로드 시점:
     - **함정 A (즉시 Close)**: 이전 워커가 프로세스 종료를 위해 리슨 소켓을 닫으면(`close()`), 커널은 핸드셰이크가 완료되어 백로그 큐에서 유저스페이스 `accept()`를 기다리던 미수락(`unaccepted`) 완료 연결 소켓들을 모두 폐기하고 클라이언트에 강제 **TCP RST**를 전송합니다.
     - **함정 B (지연 Close / Drain 시도)**: 이전 워커가 기존 요청만 처리하고 `accept()`를 중단한 채 소켓을 열어두면, 커널의 4-튜플 해시 테이블(`reuse->socks[]`)에는 이전 소켓이 여전히 남아 있어 신규 SYN 패킷이 계속해서 이전 워커로 유입되어 영구 대기 타임아웃이 발생합니다.

3. **멀티코어 NUMA 캐시 바운싱 및 코어 불일치 (`CROSS_CORE_NUMA_CACHE_THRASHING`)**:
   - 고성능 NIC의 RSS(Receive Side Scaling)가 패킷을 CPU 코어 $K$의 인터럽트로 처리하지만, 커널의 4-튜플 해시는 CPU 코어 $M$($K \neq M$)에 바인딩된 워커 소켓을 선택합니다.
   - 이로 인해 인터-프로세서 인터럽트(IPI)와 크로스-코어 캐시 라인 무효화(Cache-line bouncing)가 발생하여 패킷 처리 레이턴시가 급증합니다.

```
[eBPF Socket Steering (SO_ATTACH_REUSEPORT_EBPF) 해결책]
Client SYNs ──► NIC RSS (Core K) ──► BPF_PROG_TYPE_SK_REUSEPORT
                                           │
             ┌─────────────────────────────┴─────────────────────────────┐
             ▼                                                           ▼
     [CPU Core Locality]                                         [Drain & Balancing]
     bpf_get_smp_processor_id() == K                           Draining 소켓 마스킹 &
     Direct to sock_array[K] (No cross-core)                   Backlog Watermark 감지 우회
             │                                                           │
             ▼                                                           ▼
      Zero Cache Bounce                                          Zero-Drop Graceful Reload
```

이 문제를 해결하기 위해 최신 리눅스 커널의 **`SO_ATTACH_REUSEPORT_EBPF`**(`BPF_PROG_TYPE_SK_REUSEPORT` + `BPF_MAP_TYPE_REUSEPORT_SOCKARRAY`)를 도입하여 CPU 코어 로컬리티 유지, 백로그 수심 감지 기반 동적 우회, 안전한 무중단 소켓 드레이닝 상태 머신을 구현해야 합니다.

---

## 2. 상태 머신 및 동작 명세

시뮬레이터는 4가지 소켓 분배 모드(`mode`)와 4가지 네트워크/라이프사이클 이벤트(`events`)를 처리합니다.

### 2.1 동작 모드 (`mode`)

1. **`KERNEL_DEFAULT_REUSEPORT`**:
   - 커널 기본 4-튜플 CRC32 해시 분배를 모방합니다:
     $$\text{idx} = \text{crc32}(\text{src\_ip} + ":" + \text{src\_port}) \pmod N$$
     (여기서 $N$은 현재 등록된 유효 소켓 수이며, `ACTIVE` 및 `DRAINING` 소켓 모두 포함)
   - 소켓의 CPU 코어나 큐 깊이를 고려하지 않습니다.
   - 재로드 시작 후 `DRAINING` 상태인 구버전 소켓에도 해시에 의해 신규 SYN이 분배됩니다 (`OLD_WORKER_DRAIN_STARVATION`).

2. **`EBPF_CPU_AFFINITY`**:
   - eBPF 프로그램이 패킷이 도착한 NIC RSS 코어(`cpu_id`)를 확인하여 해당 코어에 매핑된 `ACTIVE` 워커 소켓으로 패킷을 직결합니다.
   - 크로스 코어 패킷 디스패치를 0으로 제거하여 CPU 캐시 로컬리티를 극대화합니다.

3. **`EBPF_LOAD_AWARE`**:
   - 기본적으로 패킷 도착 CPU 또는 해시에 해당하는 타깃 워커를 1차 선택합니다.
   - 타깃 워커의 현재 백로그 큐 길이(`backlog_len`)가 임계치($\lfloor \text{max\_backlog} \times \text{load\_watermark\_pct} \rfloor$) 이상인 경우:
     - `ACTIVE` 워커들 중 백로그 큐 길이가 가장 작은 워커로 동적 우회(Divert)합니다.
     - 이를 통해 특정 워커로의 해시 편중에 의한 오버플로우 드롭을 원천 방지합니다.

4. **`EBPF_GRACEFUL_RELOAD`**:
   - BPF 맵의 소켓 테이블에서 `DRAINING` 상태인 구버전 소켓을 신규 SYN 패킷 라우팅 대상에서 완전히 제외합니다.
   - 신규 SYN 패킷은 오직 신규 `ACTIVE` 워커들로만 분배됩니다.
   - 구버전 워커는 큐에 이미 들어와 있는 잔여 미수락 연결들을 안전하게 `accept()`하여 비운 후 소켓을 닫으므로 RST 드롭이 발생하지 않습니다.

---

### 2.2 이벤트 타입 (`events`)

1. **`SYN_PACKET`**:
   - 클라이언트의 TCP SYN 패킷 도착.
   - 속성: `time_ms`, `type`, `conn_id`, `src_ip`, `src_port`, `cpu_id`
   - 타깃 워커를 선정한 후:
     - 타깃 워커의 `cpu_id`와 패킷의 `cpu_id`가 다르면 `cross_core_dispatches` 1 증가.
     - 타깃 워커의 백로그 큐 크기가 `max_backlog`에 도달한 경우 패킷 폐기 (`dropped_overflow` 1 증가).
     - 여유가 있는 경우 타깃 워커의 백로그 큐에 추가 및 피크 큐 수신 지표 갱신.

2. **`WORKER_ACCEPT`**:
   - 워커 프로세스가 `accept()` 시스템 콜을 호출하여 백로그 큐에서 최대 `batch_size`개의 연결을 꺼내어 수락(`ESTABLISHED`) 처리.
   - 속성: `time_ms`, `type`, `worker_id`, `batch_size`

3. **`RELOAD_START`**:
   - 무중단 롤링 재로드 프로세스 개시.
   - 속성: `time_ms`, `type`, `old_workers` (구버전 워커 ID 리스트), `new_workers` (신규 워커 ID 리스트), `new_worker_cpus` (신규 워커 코어 할당 리스트)
   - `old_workers`의 상태를 `DRAINING`으로 변경.
   - `new_workers`를 생성하고 상태를 `ACTIVE`로 등록.

4. **`CLOSE_SOCKET`**:
   - 워커 프로세스가 리슨 소켓을 닫음(`close()`).
   - 속성: `time_ms`, `type`, `worker_id`
   - 해당 워커의 상태를 `DEAD`로 전환.
   - **중요**: 소켓을 닫을 때 백로그 큐에 아직 꺼내가지 않은 미수락 연결(`unaccepted`)이 남아있는 경우, 커널은 이 연결들을 모두 드롭하고 클라이언트로 TCP RST를 전송함 (`dropped_rst_on_close` 증가).

---

### 2.3 감지해야 할 이상 징후 (`anomalies`)

- `"REUSEPORT_HASH_SKEW_QUEUE_OVERFLOW"`:
  - 오버플로우 드롭(`total_overflow > 0`)이 발생했으며, 특정 워커는 오버플로우 드롭을 겪는 동안 다른 활성 워커 중 피크 백로그가 `max_backlog * 0.5` 미만인 워커가 존재하는 경우.
- `"BACKLOG_CAPACITY_EXCEEDED"`:
  - 오버플로우 드롭이 발생했으나 모든 워커가 균등하게 높은 부하를 겪은 경우.
- `"REUSEPORT_RELOAD_RST_UNACCEPTED_DROP"`:
  - 소켓 종료 시 백로그에 남아있던 미수락 연결로 인해 RST 드롭(`total_rst > 0`)이 발생한 경우.
- `"OLD_WORKER_DRAIN_STARVATION"`:
  - 재로드 시작(`RELOAD_START`) 이후 종료 대기 중인(`DRAINING`) 구버전 워커로 신규 SYN 패킷이 유입된 경우.
- `"CROSS_CORE_NUMA_CACHE_THRASHING"`:
  - 모드가 `KERNEL_DEFAULT_REUSEPORT`이고, 크로스-코어 패킷 비율이 전체 SYN 패킷의 40%를 초과한 경우 ($\frac{\text{cross\_core\_count}}{\text{total\_syn}} > 0.40$).

---

## 3. 입력 형식 (`sys.stdin`)

표준 입력으로 단일 JSON 객체가 주어집니다.

```json
{
  "mode": "KERNEL_DEFAULT_REUSEPORT",
  "num_workers": 4,
  "worker_cpus": [0, 0, 0, 0],
  "max_backlog": 10,
  "load_watermark_pct": 0.8,
  "events": [
    {
      "time_ms": 0,
      "type": "SYN_PACKET",
      "conn_id": "c-1",
      "src_ip": "203.0.113.1",
      "src_port": 10001,
      "cpu_id": 0
    },
    {
      "time_ms": 10,
      "type": "WORKER_ACCEPT",
      "worker_id": 0,
      "batch_size": 5
    }
  ]
}
```

---

## 4. 출력 형식 (`sys.stdout`)

표준 출력으로 JSON 객체를 단일 행으로 출력합니다 (`ensure_ascii=False`).

```json
{
  "mode": "KERNEL_DEFAULT_REUSEPORT",
  "total_syn_packets": 20,
  "accepted_connections": 0,
  "dropped_overflow": 10,
  "dropped_rst_on_close": 0,
  "cross_core_dispatches": 0,
  "worker_stats": {
    "0": {
      "cpu_id": 0,
      "state": "ACTIVE",
      "syn_received": 20,
      "accepted": 0,
      "dropped_overflow": 10,
      "dropped_rst": 0,
      "peak_backlog": 10,
      "remaining_backlog": 10
    },
    "1": {
      "cpu_id": 0,
      "state": "ACTIVE",
      "syn_received": 0,
      "accepted": 0,
      "dropped_overflow": 0,
      "dropped_rst": 0,
      "peak_backlog": 0,
      "remaining_backlog": 0
    }
  },
  "anomalies": [
    "REUSEPORT_HASH_SKEW_QUEUE_OVERFLOW"
  ],
  "diagnosis": "SO_REUSEPORT의 단순 4-튜플 해싱으로 인해 특정 워커 큐로 SYN 집중 및 오버플로우 드롭 발생 (eBPF 큐 깊이 기반 동적 스티어링 필요)."
}
```
